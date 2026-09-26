"""Closed-bar geometry only; no drawing, broker calls, or knowledge of future bars.

Research thresholds are explicit and scale with ATR. A name is assigned only after
its own geometric conditions pass. Multiple descriptions never become extra votes.
"""
from __future__ import annotations
import hashlib
import json
import math
from ..model import atr, pivots, ordered, TF_SECONDS

VERSION='geometry-1'
FAMILIES=('TRIANGLE','FLAG','PENNANT','CHANNEL','RANGE','WEDGE','BROADENING',
          'MULTI_EXTREME','HEAD_SHOULDERS')


def value(line, when):
    return line['price']+line['slope']*(when-line['t0'])


def causal_points(bars,tf='M5'):
    span=TF_SECONDS[tf]
    raw=pivots(bars,2)
    # Outside bars with simultaneous H/L do not tell us intrabar ordering.
    ambiguous={p['time'] for p in raw if sum(q['time']==p['time'] for q in raw)>1}
    out=[]
    for p in raw:
        if p['time'] in ambiguous:continue
        point=dict(p,occurred_at=p['time'],available_at=p['known_at']+span,
                   provisional=False,role=p['kind'])
        if out and out[-1]['kind']==point['kind']:
            if (point['price']-out[-1]['price'])*(1 if point['kind']=='H' else -1)>0:out[-1]=point
        else:out.append(point)
    return out


def fit(points):
    t0=points[0]['time'];xs=[p['time']-t0 for p in points];ys=[p['price'] for p in points]
    mx=sum(xs)/len(xs);my=sum(ys)/len(ys);den=sum((x-mx)**2 for x in xs)
    slope=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/den if den else 0.
    line=dict(t0=t0,price=my-slope*mx,slope=slope)
    error=math.sqrt(sum((value(line,p['time'])-p['price'])**2 for p in points)/len(points))
    return line,error


def pattern(family,variant,anchors,upper,lower,a,symbol,tf,quality,measurements,bias=0):
    identity=[(p['time'],p['kind'],round(p['price'],10)) for p in anchors]
    key=hashlib.sha256(json.dumps([VERSION,symbol,tf,family,variant,identity]).encode()).hexdigest()[:20]
    return dict(pattern_id=key,geometry_version=VERSION,family=family,variant=variant,
                symbol=symbol,timeframe=tf,anchors=anchors,upper=upper,lower=lower,
                boundaries=[dict(upper,role='RESISTANCE'),dict(lower,role='SUPPORT')],
                formed_at=anchors[-1]['time'],available_at=max(p['available_at'] for p in anchors),
                quality=max(0.,min(1.,quality)),measurements=measurements,bias=bias,atr=a,
                validation=dict(valid=True,reasons=['causal pivots','distinct alternating reactions','geometry passed']))


def _pole(bars,start,a,width,drift):
    prior=[b for b in bars if b.time<start][-18:]
    if len(prior)<6:return None
    end=prior[-1].close
    # Fixed recent windows, no best-return optimisation on future candles.
    for n in (6,10,16):
        if len(prior)<n:continue
        rows=prior[-n:];move=end-rows[0].open
        travel=sum(abs(y.close-x.close) for x,y in zip(rows,rows[1:]))+abs(rows[0].close-rows[0].open)
        sign=1 if move>0 else -1
        if abs(move)>=3*a and travel>0 and abs(move)/travel>=.80 and width<=abs(move)*.60 and drift*sign<=a*.30:
            return dict(side=sign,height=abs(move),start=rows[0].time,end=rows[-1].time,efficiency=min(1.,abs(move)/travel))
    return None


def _lanes(bars,pts,a,symbol,tf):
    out=[];now=bars[-1].time+TF_SECONDS[tf]
    for count in (6,8,10):
        anchors=pts[-count:]
        hs=[p for p in anchors if p['kind']=='H'];ls=[p for p in anchors if p['kind']=='L']
        if len(hs)<3 or len(ls)<3:continue
        start=anchors[0]['time'];duration=anchors[-1]['time']-start
        if duration<TF_SECONDS[tf]*8:continue
        upper,he=fit(hs);lower,le=fit(ls)
        if max(he,le)>.22*a:continue
        w0=value(upper,start)-value(lower,start);w1=value(upper,now)-value(lower,now)
        if min(w0,w1)<=.35*a:continue
        segment=[b for b in bars if start<=b.time<=anchors[-1]['time']]
        outside=sum(b.close>value(upper,b.time)+.25*a or b.close<value(lower,b.time)-.25*a for b in segment)
        if outside>max(1,len(segment)*.10):continue
        us=upper['slope']*duration;lslope=lower['slope']*duration
        horizontal=.22*a;ratio=w1/w0
        family=variant='';bias=0
        if ratio<.85:
            if us>horizontal and lslope>horizontal:family='WEDGE';variant='RISING'
            elif us<-horizontal and lslope<-horizontal:family='WEDGE';variant='FALLING'
            elif us<=horizontal and lslope>=-horizontal:
                family='TRIANGLE'
                variant='ASCENDING' if abs(us)<=horizontal else 'DESCENDING' if abs(lslope)<=horizontal else 'SYMMETRIC'
        elif ratio>1.18:
            family='BROADENING';variant='EXPANDING'
        elif abs(us)<=horizontal and abs(lslope)<=horizontal:
            family='RANGE';variant='HORIZONTAL'
        elif us*lslope>0 and abs(us-lslope)<=.25*a:
            family='CHANNEL';variant='RISING' if us>0 else 'FALLING';bias=1 if us>0 else -1
        if not family:continue
        pole=_pole(bars,start,a,max(w0,w1),(us+lslope)/2)
        if pole and now-start<=TF_SECONDS[tf]*64:
            if family=='CHANNEL' and bias==-pole['side']:
                family='FLAG';variant='BULL' if pole['side']>0 else 'BEAR';bias=pole['side']
            elif family=='TRIANGLE':
                family='PENNANT';variant='BULL' if pole['side']>0 else 'BEAR';bias=pole['side']
        q=.90-min(.35,(he+le)/max(a,1e-12))
        measurement=dict(width=w0,width_now=w1,contraction=ratio,upper_error_atr=he/a,lower_error_atr=le/a,
                         touches_high=len(hs),touches_low=len(ls),duration=duration,pole=pole)
        out.append(pattern(family,variant,anchors,upper,lower,a,symbol,tf,q,measurement,bias))
    # Prefer freshest shortest explanatory geometry within each family. No extra votes.
    chosen={}
    for p in out:
        prior=chosen.get(p['family'])
        if prior is None or (p['available_at'],p['quality'])>(prior['available_at'],prior['quality']):chosen[p['family']]=p
    return list(chosen.values())


def _reversals(pts,a,symbol,tf):
    result=[]
    for kind,side in (('H',-1),('L',1)):
        sign=-side
        for n in (3,5):
            # The latest usable extreme must be the final peak/trough, not an old template.
            candidates=[i for i,p in enumerate(pts) if p['kind']==kind]
            if not candidates:continue
            end=candidates[-1];start=end-n+1
            if start<0:continue
            nodes=pts[start:end+1]
            if nodes[0]['kind']!=kind:continue
            peaks=nodes[::2];reactions=nodes[1::2]
            height=(sum(p['price'] for p in peaks)/len(peaks)-sum(p['price'] for p in reactions)/len(reactions))*sign
            if height<.7*a:continue
            neck,_=fit(reactions) if len(reactions)>=2 else (dict(t0=reactions[0]['time'],price=reactions[0]['price'],slope=0.),0)
            # Tops/bottoms are zones, but too much slope is a different formation.
            spread=max(p['price'] for p in peaks)-min(p['price'] for p in peaks)
            family=variant='';quality=.82
            if spread<=max(.22*a,.12*height):
                family='MULTI_EXTREME';variant=('TRIPLE' if len(peaks)==3 else 'DOUBLE')+('_TOP' if kind=='H' else '_BOTTOM')
            elif len(peaks)==3:
                left,head,right=peaks
                shoulder_gap=abs(left['price']-right['price'])
                prominence=(head['price']-max(left['price'],right['price'])) if kind=='H' else (min(left['price'],right['price'])-head['price'])
                if prominence>=.5*a and shoulder_gap<=max(.30*a,.25*height):
                    family='HEAD_SHOULDERS';variant='TOP' if kind=='H' else 'INVERSE';quality=.88
            if not family:continue
            extreme=max(p['price'] for p in peaks) if kind=='H' else min(p['price'] for p in peaks)
            outer=dict(t0=nodes[0]['time'],price=extreme,slope=0.)
            upper,lower=(outer,neck) if kind=='H' else (neck,outer)
            result.append(pattern(family,variant,nodes,upper,lower,a,symbol,tf,quality,
                                  dict(width=height,width_now=height,duration=nodes[-1]['time']-nodes[0]['time'],pole=None),side))
    return result


def detect_patterns(bars,symbol='EUR/USD',tf='M5'):
    if len(bars)<24:return []
    ordered(bars);a=atr(bars);pts=causal_points(bars,tf)
    if len(pts)<3:return []
    now=bars[-1].time+TF_SECONDS[tf]
    patterns=_lanes(bars,pts,a,symbol,tf)+_reversals(pts,a,symbol,tf)
    # Detection at bar close only. Old shapes are not fresh trading invitations.
    patterns=[p for p in patterns if now-p['available_at']<=TF_SECONDS[tf]*8]
    return sorted(patterns,key=lambda p:(p['available_at'],p['quality']),reverse=True)[:8]
