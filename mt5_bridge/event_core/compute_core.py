from __future__ import annotations

import math
from dataclasses import asdict

from .model import Bar, Quote, Config, Decision, atr, pivots, direction, context_direction, swing_labels


class ComputeCore:
    """One deterministic market calculator -> one decision.

    It does not run competing impulse/pullback/probe state machines. All inputs are
    reduced to one normalized directional estimate and one timing gate.
    """

    ENTRY_CONFIDENCE=.55
    MIN_EDGE=.12
    MAX_CHASE_ATR=.25
    MOMENTUM_WINDOW_ATR=.18

    def __init__(self,config:Config,saved=None):
        self.config=config
        self.previous_quote=None
        self.bias_side=int((saved or {}).get('bias_side',0) or 0)
        self.bias_since=float((saved or {}).get('bias_since',0) or 0)

    def state(self):
        return {'bias_side':self.bias_side,'bias_since':self.bias_since}

    def clear(self):
        self.previous_quote=None
        self.bias_side=0
        self.bias_since=0.

    @staticmethod
    def _clip(x,lo=-1.,hi=1.):
        return max(lo,min(hi,float(x)))

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

    def evaluate(self,bars,m1,m15,h1,live_bar,q:Quote,now,campaign_side=0):
        q.validate(now)
        if self.config.timeframe!='M5' or live_bar is None or len(bars)<20 or len(m1)<8:
            return Decision(reason='ComputeCore: недостаточно свежих M1/M5 данных',path='COMPUTE')
        a=atr(bars)
        points=pivots(bars)
        structure_side=direction(points)
        ctx15=context_direction(m15) if m15 else 0
        ctx1=context_direction(h1) if h1 else 0

        m1_fast=(m1[-1].close-m1[-4].close)/a
        m1_slow=(m1[-1].close-m1[-8].close)/a
        prev_fast=(m1[-4].close-m1[-7].close)/a
        acceleration=m1_fast-prev_fast
        m5_momentum=(live_bar.close-bars[-3].close)/a
        closed_m5=(bars[-1].close-bars[-4].close)/a
        live_body=(live_bar.close-live_bar.open)/a

        recent=bars[-10:]
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

        components={
            'structure':float(structure_side),
            'm1_fast':self._clip(m1_fast/.55),
            'm1_slow':self._clip(m1_slow/.85),
            'acceleration':self._clip(acceleration/.40),
            'm5_momentum':self._clip(m5_momentum/1.15),
            'closed_m5':self._clip(closed_m5/1.20),
            'live_body':self._clip(live_body/.55),
            'context':self._clip(ctx15*.60+ctx1*.40),
            'range_position':self._clip(range_pos),
            'volume_pressure':volume_pressure,
            'tick_speed':self._clip(tick_speed/.20),
        }
        score=(1.20*components['structure']+
               1.45*components['m1_fast']+
               .90*components['m1_slow']+
               .85*components['acceleration']+
               1.25*components['m5_momentum']+
               .65*components['closed_m5']+
               .95*components['live_body']+
               .75*components['context']+
               .45*components['range_position']+
               .30*components['volume_pressure']+
               .55*components['tick_speed'])
        directional=math.tanh(score/4.25)
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
        bias=side if side else (1 if directional>.08 else -1 if directional<-.08 else 0)
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
        exhaustion=bool(bias and extension>=1.35 and near_edge and decelerating)
        late_entry=bool(bias and extension>=1.65 and near_edge)

        projection=self._projection(q.bid,a,directional,up,down,range_p)
        forecast=dict(side=side,candidate_side=0,confidence=round(confidence,4),
                      edge_strength=round(edge,4),up_probability=round(up,4),
                      down_probability=round(down,4),range_probability=round(range_p,4),
                      stable_for_sec=round(stable,2),late_entry=late_entry,
                      exhaustion=exhaustion,regime=('EXHAUSTION' if exhaustion else
                          'TREND_UP' if side==1 else 'TREND_DOWN' if side==-1 else 'RANGE'),
                      available=True,projection=projection,
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
        aligned=(m1_fast*side>.10 and live_body*side>.06)
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
        return Decision('BUY' if side==1 else 'SELL','ENTRY_READY',
                        ('ComputeCore: единый расчёт подтвердил направление и момент входа'),
                        event,side,stop,trigger,stop,a,q.time_msc,levels,
                        path='COMPUTE',structure=swing_labels(bars),
                        forecast=forecast,entry_class='PROBE')
