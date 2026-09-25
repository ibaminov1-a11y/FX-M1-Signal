from __future__ import annotations

import math
from dataclasses import asdict

from .model import Bar, Quote, Config, Decision, atr, pivots, direction, context_direction, swing_labels


class ComputeCore:
    """One deterministic market calculator -> one decision.

    It does not run competing impulse/pullback/probe state machines. All inputs are
    reduced to one normalized directional estimate and one timing gate.
    """

    ENTRY_CONFIDENCE=.52
    MIN_EDGE=.08
    MAX_CHASE_ATR=.25
    MOMENTUM_WINDOW_ATR=.18

    def __init__(self,config:Config,saved=None):
        self.config=config
        self.previous_quote=None
        self.bias_side=int((saved or {}).get('bias_side',0) or 0)
        self.bias_since=float((saved or {}).get('bias_since',0) or 0)
        self.consumed=set((saved or {}).get('consumed',[]))

    def state(self):
        return {'bias_side':self.bias_side,'bias_since':self.bias_since,
                'consumed':sorted(self.consumed)[-2048:]}

    def consume(self,event_id):
        if event_id:
            self.consumed.add(event_id)
            if len(self.consumed)>4096:self.consumed=set(sorted(self.consumed)[-2048:])

    def clear(self):
        self.previous_quote=None
        self.bias_side=0
        self.bias_since=0.

    @staticmethod
    def _clip(x,lo=-1.,hi=1.):
        return max(lo,min(hi,float(x)))

    @staticmethod
    def _slope(values,n,a):
        rows=list(values[-n:])
        if len(rows)<3:return 0.
        ys=[x.close for x in rows];m=(len(ys)-1)/2
        den=sum((i-m)**2 for i in range(len(ys)))
        if den<=0:return 0.
        slope=sum((i-m)*(y-sum(ys)/len(ys)) for i,y in enumerate(ys))/den
        return slope*(len(ys)-1)/a

    @staticmethod
    def _probabilities(directional):
        # Leave explicit probability mass for range/uncertainty.
        range_p=max(.08,min(.46,.12+.34*(1-abs(directional))))
        mass=1-range_p
        up=mass*(1+directional)/2
        down=mass-up
        total=up+down+range_p
        return up/total,down/total,range_p/total

    def _projection(self,current,a,directional,up,down,range_p):
        if abs(directional)<.08:
            return []
        out=[]
        for horizon in (1,2,3):
            decay=1/(1+.28*(horizon-1))
            d=directional*decay
            pu,pd,pr=self._probabilities(d)
            center=current+d*a*.34*(horizon**.72)
            width=a*(.30*math.sqrt(horizon)+.18*pr*horizon)
            out.append(dict(minutes=horizon*5,center=round(center,10),
                            low=round(center-width,10),high=round(center+width,10),
                            up_probability=round(pu,4),down_probability=round(pd,4),
                            range_probability=round(pr,4)))
        return out

    def _scenarios(self,current,a,side,up,down,range_p,projection,support,resistance):
        if side not in (-1,1):
            return []
        primary_prob=up if side==1 else down
        opposite_prob=down if side==1 else up
        strength=max(.20,min(1.0,abs(up-down)*2.2))
        # The main path deliberately contains a retest leg before continuation,
        # so the chart reads as a scenario map rather than a fake future price line.
        retest=current-side*a*(.08+.08*(1-strength))
        if side==1 and support:
            retest=max(retest,support+a*.03)
        if side==-1 and resistance:
            retest=min(retest,resistance-a*.03)
        projected=(projection[-1]['center'] if projection else current+side*a*.35*strength)
        target=projected
        if (target-current)*side<a*.18:
            target=current+side*a*(.18+.30*strength)
        main=dict(name='PRIMARY',side=side,probability=round(primary_prob,4),
                  path=[dict(minutes=0,price=round(current,10)),
                        dict(minutes=4,price=round(retest,10)),
                        dict(minutes=9,price=round(current+side*a*(.16+.16*strength),10)),
                        dict(minutes=15,price=round(target,10))])
        if range_p>=opposite_prob:
            alt=dict(name='ALTERNATIVE',side=0,probability=round(range_p,4),
                     path=[dict(minutes=0,price=round(current,10)),
                           dict(minutes=5,price=round(current+side*a*.06,10)),
                           dict(minutes=10,price=round(current-side*a*.05,10)),
                           dict(minutes=15,price=round(current+side*a*.02,10))])
        else:
            alt_side=-side
            alt=dict(name='ALTERNATIVE',side=alt_side,probability=round(opposite_prob,4),
                     path=[dict(minutes=0,price=round(current,10)),
                           dict(minutes=4,price=round(current+side*a*.06,10)),
                           dict(minutes=9,price=round(current+alt_side*a*.20,10)),
                           dict(minutes=15,price=round(current+alt_side*a*(.30+.20*strength),10))])
        return [main,alt]

    def evaluate(self,bars,m1,m15,h1,live_bar,q:Quote,now,campaign_side=0):
        q.validate(now)
        if self.config.timeframe!='M5' or live_bar is None or len(bars)<20 or len(m1)<8:
            return Decision(reason='ComputeCore: недостаточно свежих M1/M5 данных',path='COMPUTE')
        a=atr(bars)
        points=pivots(bars)
        structure_side=direction(points)
        ctx15=context_direction(m15) if m15 else 0
        ctx1=context_direction(h1) if h1 else 0

        m1_fast=self._slope(m1,8,a)
        m1_slow=self._slope(m1,16,a)
        m1_prev=self._slope(m1[:-4],8,a) if len(m1)>=12 else 0.
        acceleration=m1_fast-m1_prev
        m5_trend=self._slope(bars,16,a)
        m5_momentum=(live_bar.close-bars[-1].close)/a
        live_body=(live_bar.close-live_bar.open)/a
        m15_trend=self._slope(m15,12,a) if m15 else 0.
        h1_trend=self._slope(h1,12,a) if h1 else 0.

        recent=bars[-12:]
        low=min(x.low for x in recent)
        high=max(x.high for x in recent)
        range_pos=0.0 if high<=low else ((q.bid-low)/(high-low)*2-1)

        vols=[max(0.,float(x.volume)) for x in m1[-12:-1]]
        avg_vol=sum(vols)/len(vols) if vols else 0.
        vol_ratio=(float(m1[-1].volume)/avg_vol-1.) if avg_vol>0 else 0.
        vol_sign=1 if m1[-1].close>m1[-1].open else -1 if m1[-1].close<m1[-1].open else 0
        volume_pressure=self._clip(vol_ratio)*vol_sign

        tick_speed=0.
        previous=self.previous_quote
        if previous is not None and q.time_msc>previous.time_msc:
            tick_speed=(q.bid-previous.bid)/a

        context_numeric=self._clip(.35*self._clip(m15_trend/.9)+.25*self._clip(h1_trend/1.1)+
                                   .25*ctx15+.15*ctx1)
        components={
            'structure':float(structure_side),
            'm1_fast':self._clip(m1_fast/.35),
            'm1_slow':self._clip(m1_slow/.55),
            'acceleration':self._clip(acceleration/.35),
            'm5_trend':self._clip(m5_trend/.90),
            'm5_momentum':self._clip(m5_momentum/.55),
            'live_body':self._clip(live_body/.50),
            'context':context_numeric,
            'range_position':self._clip(range_pos),
            'volume_pressure':volume_pressure,
            'tick_speed':self._clip(tick_speed/.18),
        }
        score=(1.20*components['structure']+
               1.25*components['m1_fast']+
               1.05*components['m1_slow']+
               .55*components['acceleration']+
               1.10*components['m5_trend']+
               .90*components['m5_momentum']+
               .85*components['live_body']+
               .85*components['context']+
               .20*components['range_position']+
               .25*components['volume_pressure']+
               .45*components['tick_speed'])
        directional=math.tanh(score/3.85)
        up,down,range_p=self._probabilities(directional)
        confidence=max(up,down)
        other=down if up>=down else up
        edge=confidence-max(other,range_p)
        side=1 if up>=down else -1
        if confidence<.52 or edge<.08:
            side=0

        tracking=side
        if tracking:
            if tracking!=self.bias_side:
                self.bias_side=tracking
                self.bias_since=now
            stable=max(0.,now-self.bias_since)
        else:
            self.bias_side=0
            self.bias_since=now
            stable=0.

        # Exhaustion is directional: a stretched leg plus deceleration/reversal near
        # the edge blocks chasing, without erasing the directional estimate itself.
        bias=side if side else structure_side if structure_side else (1 if m5_trend>.35 else -1 if m5_trend<-.35 else (1 if directional>.08 else -1 if directional<-.08 else 0))
        tail=list(bars[-10:])+[live_bar]
        extension=0.;near_edge=False;decelerating=False
        if bias==1:
            floor=min(x.low for x in tail);top=max(x.high for x in tail)
            extension=max(0.,(q.bid-floor)/a)
            near_edge=(top-q.bid)<=.22*a
            decelerating=acceleration<-.08 or live_body<-.04
        elif bias==-1:
            top=max(x.high for x in tail);floor=min(x.low for x in tail)
            extension=max(0.,(top-q.bid)/a)
            near_edge=(q.bid-floor)<=.22*a
            decelerating=acceleration>.08 or live_body>.04
        exhaustion=bool(bias and extension>=1.00 and near_edge and decelerating)
        late_entry=bool(bias and extension>=1.40 and near_edge)

        projection=self._projection(q.bid,a,directional,up,down,range_p)
        highs=[p['price'] for p in points if p['kind']=='H']
        lows=[p['price'] for p in points if p['kind']=='L']
        support=lows[-1] if lows else low
        resistance=highs[-1] if highs else high
        scenarios=self._scenarios(q.bid,a,side,up,down,range_p,projection,support,resistance)
        forecast=dict(side=side,candidate_side=0,confidence=round(confidence,4),
                      edge_strength=round(edge,4),up_probability=round(up,4),
                      down_probability=round(down,4),range_probability=round(range_p,4),
                      stable_for_sec=round(stable,2),late_entry=late_entry,
                      exhaustion=exhaustion,regime=('EXHAUSTION' if exhaustion else
                          'TREND_UP' if side==1 else 'TREND_DOWN' if side==-1 else 'RANGE'),
                      available=True,projection=projection,scenarios=scenarios,
                      support=round(support,10),resistance=round(resistance,10),
                      components={k:round(v,3) for k,v in components.items()},
                      score=round(score,3),directional=round(directional,4),
                      engine='COMPUTE_V1')

        if side==0:
            self.previous_quote=q
            return Decision(reason='ComputeCore: нет вычислительного преимущества — WAIT',
                            atr=a,path='COMPUTE',structure=swing_labels(bars),forecast=forecast)
        if exhaustion or late_entry:
            self.previous_quote=q
            return Decision(reason='ComputeCore: направление есть, но вход поздний/импульс истощён',
                            side=side,atr=a,path='COMPUTE',structure=swing_labels(bars),forecast=forecast)

        # Two higher timeframes simultaneously against the score are a hard veto.
        if ctx15==-side and ctx1==-side:
            self.previous_quote=q
            return Decision(reason='ComputeCore: M15 и H1 одновременно против входа',
                            side=side,atr=a,path='COMPUTE',structure=swing_labels(bars),forecast=forecast)

        pad=max(a*.02,q.spread*1.2)
        prior=m1[-5:-1]
        trigger=(max(x.high for x in prior)+pad) if side==1 else (min(x.low for x in prior)-pad)
        distance=(q.bid-trigger)*side
        crossed=bool(previous is not None and q.time_msc>previous.time_msc and
                     (previous.bid-trigger)*side<=0 and distance>0)
        aligned=(m1_fast*side>.06 and live_body*side>.06)
        continuation=(0<distance<=self.MOMENTUM_WINDOW_ATR*a and aligned)
        too_far=distance>self.MAX_CHASE_ATR*a

        self.previous_quote=q
        levels=({'kind':'trigger','price':trigger,'time':m1[-1].time},)
        if too_far:
            forecast['late_entry']=True
            return Decision(reason='ComputeCore: цена уже слишком далеко от расчётного входа — не догоняем',
                            side=side,trigger=trigger,atr=a,levels=levels,path='COMPUTE',
                            structure=swing_labels(bars),forecast=forecast)
        if distance<=0:
            return Decision(reason=('ComputeCore: '+('BUY' if side==1 else 'SELL')+
                                    f' {confidence*100:.0f}% — ждём уровень {trigger:.5f}'),
                            side=side,trigger=trigger,atr=a,levels=levels,path='COMPUTE',
                            structure=swing_labels(bars),forecast=forecast)
        if confidence<self.ENTRY_CONFIDENCE or edge<self.MIN_EDGE:
            return Decision(reason=('ComputeCore: направление есть, но преимущество пока недостаточно для сделки '
                                    f'({confidence*100:.0f}%)'),
                            side=side,trigger=trigger,atr=a,levels=levels,path='COMPUTE',
                            structure=swing_labels(bars),forecast=forecast)
        if not (crossed or continuation):
            return Decision(reason='ComputeCore: направление подтверждено, но момент входа ещё не готов',
                            side=side,trigger=trigger,atr=a,levels=levels,path='COMPUTE',
                            structure=swing_labels(bars),forecast=forecast)

        if side==1:
            stop=min(min(x.low for x in m1[-7:])-pad,q.bid-.30*a)
        else:
            stop=max(max(x.high for x in m1[-7:])+pad,q.ask+.30*a)
        event=(f'{self.config.symbol}|M5|COMPUTE_V1|{m1[-1].time:014d}|'
               f'{side}|{trigger:.10f}')
        levels=({'kind':'invalidation','price':stop,'time':m1[-1].time},
                {'kind':'trigger','price':trigger,'time':m1[-1].time})
        if event in self.consumed:
            return Decision(reason='ComputeCore: это торговое событие уже использовано',
                            side=side,trigger=trigger,atr=a,levels=levels,path='COMPUTE',
                            structure=swing_labels(bars),forecast=forecast)
        return Decision('BUY' if side==1 else 'SELL','ENTRY_READY',
                        ('ComputeCore: единый расчёт подтвердил направление и момент входа'),
                        event,side,stop,trigger,stop,a,q.time_msc,levels,
                        path='COMPUTE',structure=swing_labels(bars),
                        forecast=forecast,entry_class='PROBE')
