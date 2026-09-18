from __future__ import annotations
from dataclasses import asdict
import math
from .model import Bar, Quote, Config, Setup, Decision, PROFILES, TF_SECONDS, atr, ordered, pivots, direction, context_direction, swing_labels, Blocked


class Strategy:
    """Forward-only event machine. No score vote can grant an entry."""
    def __init__(self, config: Config, saved=None):
        self.config=config
        self.setup=Setup(**saved['setup']) if saved and saved.get('setup') else None
        self.last_scanned=int((saved or {}).get('last_scanned',0))
        self.consumed=set((saved or {}).get('consumed',[]))
        self.previous_quote=None  # Must reobserve a crossing after process recovery.

    def state(self):
        return {'setup':asdict(self.setup) if self.setup else None,
                'last_scanned':self.last_scanned,'consumed':sorted(self.consumed)[-2048:]}

    def consume(self, event_id):
        self.consumed.add(event_id)
        if len(self.consumed)>4096:
            self.consumed=set(sorted(self.consumed)[-2048:])
        # A forecast probe is an independent execution event. Do not erase a
        # different confirmed pullback/trigger setup that may later validate scale-in.
        if self.setup and self.setup.id==event_id:
            self.setup=None

    def clear(self):
        self.setup=None
        self.previous_quote=None

    def _context_allows(self, side: int, m15: list[Bar], h1: list[Bar]):
        for values in (m15 or [], h1 or []):
            ctx=context_direction(values)
            if ctx and ctx!=side:
                return False
        return True

    def _impulse_decision(self,bars,m1,m15,h1,live_bar,q,now,campaign_side,a,pad,structure):
        if self.config.timeframe!='M5' or live_bar is None or not m1:
            return None
        body=live_bar.close-live_bar.open
        side=1 if body>0 else -1 if body<0 else 0
        if not side:
            return None
        full_range=live_bar.high-live_bar.low
        if full_range<=0 or abs(body)<.70*a or full_range<1.00*a or abs(body)/full_range<.65:
            return None
        if not self._context_allows(side,m15,h1):
            return None
        points=pivots(bars)
        highs=[p for p in points if p['kind']=='H'];lows=[p for p in points if p['kind']=='L']
        if not highs or not lows:
            return None
        structural_side=direction(points)
        # A neutral map may establish its first direction with this break. A confirmed
        # opposite M5 structure is not overridden by one still-forming candle.
        if structural_side and structural_side!=side:
            return None
        level=highs[-1]['price'] if side==1 else lows[-1]['price']
        trigger=level+side*pad
        if (live_bar.close-trigger)*side<=0:
            return None
        if (m1[-1].close-trigger)*side<=0:
            return None
        if (q.bid-trigger)*side<=0:
            return None
        profile=PROFILES[self.config.mode]
        if abs(q.bid-trigger)>profile.no_chase_atr*a:
            return None
        invalidation=lows[-1]['price']-pad if side==1 else highs[-1]['price']+pad
        if (q.bid-invalidation)*side<=0:
            return None
        event=(f'{self.config.symbol}|M5|{self.config.mode}|IMPULSE|'
               f'{live_bar.time:014d}|{side}|{level:.10f}')
        if event in self.consumed:
            return None
        lines=({'kind':'invalidation','price':invalidation,'time':live_bar.time},
               {'kind':'level','price':level,'time':live_bar.time},
               {'kind':'trigger','price':trigger,'time':live_bar.time})
        return Decision('BUY' if side==1 else 'SELL','ENTRY_READY',
            'Большая текущая M5 подтверждена структурой, закрытой M1 и живой котировкой',
            event,side,invalidation,trigger,invalidation,a,q.time_msc,lines,
            path='IMPULSE',structure=structure)

    def _continuation_candidate(self,bars,m1,m15,h1,q,now,campaign_side,a,pad,structure):
        if self.config.timeframe!='M5' or not m1:
            return None
        points=pivots(bars)
        side=direction(points)
        if not side:
            return None
        if not self._context_allows(side,m15,h1):
            return None
        last=bars[-1]
        # A real pause must push against the trend or close neutral. An uninterrupted
        # same-direction stair is not re-labelled as a continuation entry.
        if (last.close-last.open)*side>0:
            return None
        recent=bars[-5:-1]
        if len(recent)<4:
            return None
        extreme=max(x.high for x in recent) if side==1 else min(x.low for x in recent)
        retrace=(extreme-last.low) if side==1 else (last.high-extreme)
        if retrace<.10*a or retrace>=.35*a:
            return None
        highs=[p for p in points if p['kind']=='H'];lows=[p for p in points if p['kind']=='L']
        if not highs or not lows:
            return None
        invalidation=lows[-1]['price']-pad if side==1 else highs[-1]['price']+pad
        trigger=last.high+pad if side==1 else last.low-pad
        if (q.bid-trigger)*side>0:
            return None
        event=(f'{self.config.symbol}|M5|{self.config.mode}|CONTINUATION|'
               f'{last.time:014d}|{side}|{trigger:.10f}')
        if event in self.consumed:
            return None
        if self.setup and self.setup.id==event:
            return None
        previous=self.setup
        if previous and previous.id!=event:
            self.consumed.add(previous.id)
        self.setup=Setup(event,side,'CONTINUATION','TRIGGER',last.time,
            int(now+PROFILES[self.config.mode].setup_bars*TF_SECONDS[self.config.timeframe]),
            invalidation,trigger,extreme,
            pullback=last.low if side==1 else last.high,
            trigger=trigger,trigger_bar=m1[-1].time,armed_msc=q.time_msc,
            last_bid=q.bid,seen_safe_side=True,last_bar=last.time)
        lines=({'kind':'invalidation','price':invalidation,'time':last.time},
               {'kind':'level','price':trigger,'time':last.time},
               {'kind':'trigger','price':trigger,'time':last.time})
        return Decision(phase='TRIGGER',
            reason='Неглубокая пауза подтверждена; ждём новую закрытую M1 за локальным уровнем',
            side=side,stop=invalidation,trigger=trigger,invalidation=invalidation,atr=a,
            levels=lines,path='CONTINUATION',structure=structure)

    @staticmethod
    def _clip(value, lo=-1.0, hi=1.0):
        return max(lo,min(hi,float(value)))

    def forecast(self,bars,m1,m15,h1,live_bar,q,now):
        """Forward-only live directional estimate.

        This is a deterministic research ensemble, not a promise of future returns.
        It uses only closed M1/M5/M15/H1 data, the isolated forming M5 and the live
        quote. Confirmed pivot logic remains unchanged.
        """
        neutral=dict(side=0,confidence=0.0,up_probability=.33,down_probability=.33,
                     range_probability=.34,late_entry=False,exhaustion=False,
                     regime='RANGE',components={},projection=[],available=False,
                     reason='Недостаточно данных для LIVE forecast')
        if self.config.timeframe!='M5' or len(bars)<16 or len(m1)<8 or live_bar is None:
            return neutral
        try:
            q.validate(now)
            a=atr(bars)
        except Exception:
            return neutral
        pts=pivots(bars)
        struct=direction(pts)
        c15=context_direction(m15) if m15 else 0
        c1=context_direction(h1) if h1 else 0
        m5_delta=(live_bar.close-bars[-4].close)/a
        m1_delta=(m1[-1].close-m1[-6].close)/a
        fast=(m1[-1].close-m1[-3].close)/a
        slow=(m1[-3].close-m1[-6].close)/a
        acceleration=fast-slow
        live_body=(live_bar.close-live_bar.open)/a
        recent=bars[-7:]
        lo=min(x.low for x in recent);hi=max(x.high for x in recent)
        breakout=0.0 if hi<=lo else ((q.bid-lo)/(hi-lo)*2-1)
        vols=[max(0.0,float(x.volume)) for x in m1[-12:-1]]
        avg_vol=sum(vols)/len(vols) if vols else 0
        vol_ratio=(float(m1[-1].volume)/avg_vol-1) if avg_vol>0 else 0
        vol_sign=1 if m1[-1].close>m1[-1].open else -1 if m1[-1].close<m1[-1].open else 0
        components={
            'structure':float(struct),
            'momentum':self._clip(m5_delta/1.15),
            'micro_momentum':self._clip(m1_delta/.70),
            'acceleration':self._clip(acceleration/.45),
            'live_body':self._clip(live_body/.55),
            'context':self._clip((c15*.60+c1*.40)),
            'breakout_pressure':self._clip(breakout),
            'volume_pressure':self._clip(vol_ratio)*vol_sign,
        }
        score=(1.15*components['structure']+
               1.25*components['momentum']+
               1.45*components['micro_momentum']+
               .70*components['acceleration']+
               .95*components['live_body']+
               .75*components['context']+
               .65*components['breakout_pressure']+
               .35*components['volume_pressure'])
        directional=math.tanh(score/3.2)
        range_p=max(.05,min(.40,.34*(1-abs(directional))))
        mass=1-range_p
        up=mass*(1+directional)/2
        down=mass-up
        confidence=max(up,down)
        side=1 if up>=self.config.forecast_min_confidence else -1 if down>=self.config.forecast_min_confidence else 0

        bias=side if side else (1 if directional>.12 else -1 if directional<-.12 else 0)
        tail=list(bars[-8:])+[live_bar]
        extension=0.0;near_extreme=False;same_closes=0
        if bias==1:
            floor=min(x.low for x in tail)
            top=max(x.high for x in tail)
            extension=max(0,(q.bid-floor)/a)
            near_extreme=(top-q.bid)<=.18*a
            same_closes=sum((x.close-x.open)>0 for x in bars[-6:])
        elif bias==-1:
            top=max(x.high for x in tail)
            floor=min(x.low for x in tail)
            extension=max(0,(top-q.bid)/a)
            near_extreme=(q.bid-floor)<=.18*a
            same_closes=sum((x.close-x.open)<0 for x in bars[-6:])
        fresh_breakout=bool(bias and live_body*bias>0 and abs(live_body)>=.55 and
                            components['breakout_pressure']*bias>=.55)
        meaningful_pullback=any((x.close-x.open)*bias<0 and abs(x.close-x.open)>=.12*a for x in bars[-3:])
        late=bool(bias and near_extreme and extension>=self.config.late_entry_atr and
                  not fresh_breakout and not meaningful_pullback)
        exhausted=bool(bias and near_extreme and extension>=self.config.exhaustion_atr and same_closes>=4 and
                       not fresh_breakout and not meaningful_pullback)
        if exhausted:
            regime='EXHAUSTION'
        elif fresh_breakout:
            regime='BREAKOUT'
        elif struct==1 and directional>.12:
            regime='TREND_UP'
        elif struct==-1 and directional<-.12:
            regime='TREND_DOWN'
        elif abs(directional)<.18:
            regime='RANGE'
        else:
            regime='TRANSITION'
        if side==1: reason='Преимущество вверх по LIVE-ансамблю'
        elif side==-1: reason='Преимущество вниз по LIVE-ансамблю'
        else: reason='Преимущество пока недостаточно выражено'
        if late: reason+='; цена уже у края растянутого движения'
        if exhausted: reason+='; признаки истощения импульса'
        projection=[]
        current=q.bid
        for horizon in (1,2,3):
            decay=1/(1+.24*(horizon-1))
            pu=1/3+(up-1/3)*decay
            pd=1/3+(down-1/3)*decay
            pr=max(.04,1-pu-pd)
            total=pu+pd+pr;pu/=total;pd/=total;pr/=total
            dir_h=pu-pd
            center=current+dir_h*a*.40*(horizon**.72)
            uncertainty=a*(.34*math.sqrt(horizon)+.16*pr*horizon)
            pu=round(pu,4);pd=round(pd,4);pr=round(max(0,1-pu-pd),4)
            projection.append(dict(minutes=horizon*5,center=round(center,10),
                low=round(center-uncertainty,10),high=round(center+uncertainty,10),
                up_probability=pu,down_probability=pd,range_probability=pr))
        return dict(side=side,confidence=round(confidence,4),
                    up_probability=round(up,4),down_probability=round(down,4),
                    range_probability=round(range_p,4),late_entry=late,
                    exhaustion=exhausted,regime=regime,extension_atr=round(extension,3),
                    same_direction_closes=same_closes,available=True,projection=projection,
                    components={k:round(v,3) for k,v in components.items()},
                    reason=reason)

    def probe_decision(self,bars,m1,m15,h1,live_bar,q,now,forecast):
        if not self.config.probe_enabled or self.config.timeframe!='M5' or live_bar is None:
            return None
        side=int(forecast.get('side',0) or 0)
        if side not in (-1,1):
            return None
        if float(forecast.get('confidence',0))<self.config.probe_probability:
            return None
        if float(forecast.get('stable_for_sec',0))<self.config.probe_stability_sec:
            return None
        if forecast.get('late_entry') or forecast.get('exhaustion'):
            return None
        if len(m1)<6 or not self._context_allows(side,m15,h1):
            return None
        if m1[-1].time+60>now+1:
            return None
        a=atr(bars);pad=max(a*.025,q.spread*1.2)
        prior=m1[-5:-1]
        if side==1:
            micro=max(x.high for x in prior);trigger=micro+pad
            if m1[-1].close<=trigger or q.bid<=trigger or m1[-1].close<=m1[-1].open:
                return None
            stop=min(x.low for x in m1[-6:])-pad
            stop=min(stop,q.bid-.25*a)
        else:
            micro=min(x.low for x in prior);trigger=micro-pad
            if m1[-1].close>=trigger or q.bid>=trigger or m1[-1].close>=m1[-1].open:
                return None
            stop=max(x.high for x in m1[-6:])+pad
            stop=max(stop,q.ask+.25*a)
        if abs(q.bid-trigger)>PROFILES[self.config.mode].no_chase_atr*a*.70:
            return None
        event=(f'{self.config.symbol}|M5|{self.config.mode}|FORECAST|'
               f'{m1[-1].time:014d}|{side}|{trigger:.10f}')
        if event in self.consumed:
            return None
        lines=({'kind':'invalidation','price':stop,'time':m1[-1].time},
               {'kind':'trigger','price':trigger,'time':m1[-1].time})
        return Decision('BUY' if side==1 else 'SELL','PROBE_READY',
            'LIVE forecast устойчив; свежий M1 micro-break разрешил маленький probe',
            event,side,stop,trigger,stop,a,q.time_msc,lines,
            path='FORECAST',structure=swing_labels(bars),forecast=forecast,entry_class='PROBE')

    def update(self, bars: list[Bar], context: list[Bar], q: Quote, now: float, campaign_side=0,
               *, m1=None, m15=None, h1=None, live_bar=None):
        # Market analysis is deliberately independent from any already-open campaign.
        # campaign_side remains in the signature for compatibility with older callers.
        m1=[] if m1 is None else m1
        m15=context if m15 is None else m15
        h1=[] if h1 is None else h1
        q.validate(now); ordered(bars); ordered(context)
        if m1: ordered(m1)
        if m15 is not context: ordered(m15)
        if h1: ordered(h1)
        if len(bars)<32 or len(context)<16:
            return Decision(reason='Недостаточно закрытых свечей MT5')
        tf=TF_SECONDS[self.config.timeframe]
        # Adapter sends closed bars only. Reject a caller leaking a not-yet-closed bar.
        if self.config.timeframe!='MN1' and bars[-1].time+tf>now:
            raise Blocked('Анализ получил незакрытую свечу')
        if now-(bars[-1].time+tf)>tf*1.5:
            raise Blocked('Закрытые свечи MT5 устарели')
        a=atr(bars); pad=max(a*.05,q.spread*1.2)
        profile=PROFILES[self.config.mode]
        points=pivots(bars)
        structure=swing_labels(bars)
        last=bars[-1]
        s=self.setup

        impulse=self._impulse_decision(bars,m1,m15,h1,live_bar,q,now,campaign_side,a,pad,structure)
        if impulse is not None:
            if s is not None and s.id!=impulse.event_id:
                self.consumed.add(s.id)
                self.setup=None
            return impulse

        continuation=self._continuation_candidate(bars,m1,m15,h1,q,now,campaign_side,a,pad,structure)
        if continuation is not None:
            return continuation
        s=self.setup

        if s and (now>s.expires or (s.side==1 and q.bid<=s.invalidation) or
                  (s.side==-1 and q.bid>=s.invalidation) or
                  not self._context_allows(s.side,m15,h1)):
            old=s.id
            self.consume(old)
            return Decision(phase='CANCELLED',reason='Сценарий отменён: срок/структура/контекст',atr=a,
                            structure=structure)
        if s and s.kind!='CONTINUATION' and last.time>s.last_bar:
            s.last_bar=last.time
            favorable=max if s.side==1 else min
            s.extreme=favorable(s.extreme,last.high if s.side==1 else last.low)
            retrace=(s.extreme-last.low) if s.side==1 else (last.high-s.extreme)
            opposing=(last.close-last.open)*s.side<0
            if s.phase=='PULLBACK' and last.time>s.born and opposing and retrace>=profile.pullback_atr*a:
                touch=s.kind!='BREAK_RETEST' or (last.low<=s.level+pad if s.side==1 else last.high>=s.level-pad)
                if touch:
                    s.phase='TRIGGER'; s.pullback=last.low if s.side==1 else last.high
                    s.trigger=last.high+pad if s.side==1 else last.low-pad
                    s.trigger_bar=last.time; s.armed_msc=q.time_msc
                    s.seen_safe_side=False
                    s.last_bid=q.bid
            elif s.phase=='TRIGGER' and opposing:
                s.pullback=min(s.pullback,last.low) if s.side==1 else max(s.pullback,last.high)
                s.trigger=last.high+pad if s.side==1 else last.low-pad
                s.trigger_bar=last.time; s.armed_msc=q.time_msc
                s.seen_safe_side=False
                s.last_bid=q.bid
        if s:
            lines=({'kind':'invalidation','price':s.invalidation,'time':s.born},
                   {'kind':'level','price':s.level,'time':s.born})
            if s.phase=='TRIGGER':
                lines+=({'kind':'trigger','price':s.trigger,'time':s.trigger_bar},)
                if s.kind=='CONTINUATION':
                    fresh_m1=bool(m1) and m1[-1].time>s.trigger_bar and m1[-1].time+60<=now
                    m1_confirm=fresh_m1 and (m1[-1].close-s.trigger)*s.side>0
                    tick_confirm=q.time_msc>s.armed_msc and (q.bid-s.trigger)*s.side>0
                    if m1_confirm and tick_confirm and s.id not in self.consumed:
                        if abs(q.bid-s.trigger)>profile.no_chase_atr*a:
                            self.consume(s.id)
                            return Decision(phase='CANCELLED',reason='Продолжение уже убежало за допустимую цену',
                                            atr=a,levels=lines,path='CONTINUATION',structure=structure)
                        stop=s.pullback-pad if s.side==1 else s.pullback+pad
                        if self.config.mode=='NORMAL':
                            stop=min(stop,s.invalidation) if s.side==1 else max(stop,s.invalidation)
                        return Decision('BUY' if s.side==1 else 'SELL','ENTRY_READY',
                            'Неглубокая пауза завершена; новая закрытая M1 и тик подтвердили продолжение',
                            s.id,s.side,stop,s.trigger,s.invalidation,a,q.time_msc,lines,
                            path='CONTINUATION',structure=structure)
                    return Decision(phase='TRIGGER',
                        reason='Пауза есть; ждём новую закрытую M1 и живой тик за trigger',
                        side=s.side,stop=s.invalidation,trigger=s.trigger,invalidation=s.invalidation,
                        atr=a,levels=lines,path='CONTINUATION',structure=structure)

                on_safe=(q.bid-s.trigger)*s.side<=0
                crossed=s.seen_safe_side and q.time_msc>s.armed_msc and (q.bid-s.trigger)*s.side>0 and (s.last_bid-s.trigger)*s.side<=0
                s.seen_safe_side|=on_safe
                s.last_bid=q.bid
                if crossed and s.id not in self.consumed:
                    if abs(q.bid-s.trigger)>profile.no_chase_atr*a:
                        self.consume(s.id)
                        return Decision(phase='CANCELLED',reason='Резкий скачок за триггер: вход не догоняем',atr=a,levels=lines,structure=structure)
                    stop=(s.pullback-pad if s.side==1 else s.pullback+pad)
                    if self.config.mode=='NORMAL':
                        stop=min(stop,s.invalidation) if s.side==1 else max(stop,s.invalidation)
                    return Decision('BUY' if s.side==1 else 'SELL','ENTRY_READY',
                        'Откат/ретест завершён; свежая котировка пересекла триггер',s.id,s.side,
                        stop,s.trigger,s.invalidation,a,q.time_msc,lines,
                        path='PULLBACK',structure=structure)
                return Decision(phase='TRIGGER',reason='Откат есть; ждём пересечение локального уровня',
                                side=s.side,stop=s.invalidation,trigger=s.trigger,invalidation=s.invalidation,atr=a,levels=lines,
                                path='TRIGGER',structure=structure)
            return Decision(phase='PULLBACK',reason='Импульс/структура подтверждены; ждём откат/ретест',
                            side=s.side,invalidation=s.invalidation,atr=a,levels=lines,path='PULLBACK',structure=structure)
        if last.time<=self.last_scanned:
            return Decision(reason='Нового структурного события пока нет',atr=a,structure=structure)
        self.last_scanned=last.time

        # A pivot confirmed by the just-closed bar is known NOW and is therefore safe to use.
        known=[p for p in points if p['known_at']<=last.time]
        fresh=[p for p in known if p['known_at']==last.time]
        highs=[p for p in known if p['kind']=='H']; lows=[p for p in known if p['kind']=='L']
        if not highs or not lows:
            return Decision(reason='Нужны подтверждённые вершина и впадина',atr=a,structure=structure)
        prev=bars[-2]
        up=last.close>highs[-1]['price']+pad and prev.close<=highs[-1]['price']+pad
        down=last.close<lows[-1]['price']-pad and prev.close>=lows[-1]['price']-pad
        structural_side=direction(known)
        side=1 if up else -1 if down else structural_side
        kind='BREAK_RETEST' if up or down else 'IMPULSE_PULLBACK'
        if not side:
            return Decision(reason='Нет согласованного структурного сценария',atr=a,structure=structure)
        if not self._context_allows(side,m15,h1):
            return Decision(reason='Контекст старшего ТФ против сценария; новый вход запрещён',atr=a,structure=structure)
        invalidation=lows[-1]['price']-pad if side==1 else highs[-1]['price']+pad
        if (last.close-invalidation)*side<=0:
            return Decision(reason='Уровень отмены сценария уже пробит',atr=a,structure=structure)
        event=f'{self.config.symbol}|{self.config.timeframe}|{self.config.mode}|{last.time:014d}|{side}'
        if event in self.consumed:
            return Decision(reason='Это событие уже обработано',atr=a,structure=structure)

        impulse_ok=kind!='IMPULSE_PULLBACK' or (last.close-bars[-4].close)*side>=a*.8
        fresh_structure=bool(fresh) and structural_side==side

        if kind=='IMPULSE_PULLBACK' and not impulse_ok and fresh_structure:
            favorable_kind='H' if side==1 else 'L'
            favorable=[p for p in fresh if p['kind']==favorable_kind]
            level=highs[-1]['price'] if side==1 else lows[-1]['price']
            extreme=(favorable[-1]['price'] if favorable else
                     (last.high if side==1 else last.low))
            setup_kind='STRUCTURE_PULLBACK'
            self.setup=Setup(event,side,setup_kind,'PULLBACK',last.time,int(now+profile.setup_bars*tf),
                             invalidation,level,extreme,last_bar=last.time)
            if favorable:
                pivot=favorable[-1]
                after=[b for b in bars if b.time>pivot['time']]
                opposing=[b for b in after if (b.close-b.open)*side<0]
                if after and opposing:
                    pullback=min(b.low for b in after) if side==1 else max(b.high for b in after)
                    retrace=(extreme-pullback) if side==1 else (pullback-extreme)
                    if retrace>=profile.pullback_atr*a:
                        source=opposing[-1]
                        self.setup.phase='TRIGGER'
                        self.setup.pullback=pullback
                        self.setup.trigger=source.high+pad if side==1 else source.low-pad
                        self.setup.trigger_bar=source.time
                        self.setup.armed_msc=q.time_msc
                        self.setup.seen_safe_side=False
                        self.setup.last_bid=q.bid
                        lines=({'kind':'invalidation','price':invalidation,'time':last.time},
                               {'kind':'level','price':level,'time':last.time},
                               {'kind':'trigger','price':self.setup.trigger,'time':source.time})
                        return Decision(phase='TRIGGER',
                            reason='Свежая структура подтверждена; откат уже есть; ждём новое пересечение триггера',
                            side=side,stop=invalidation,trigger=self.setup.trigger,
                            invalidation=invalidation,atr=a,levels=lines,path='TRIGGER',structure=structure)
            return Decision(phase='PULLBACK',
                reason='Свежая подтверждённая структура; ждём откат/ретест, ордер не отправлен',
                side=side,invalidation=invalidation,atr=a,path='PULLBACK',structure=structure,
                levels=({'kind':'invalidation','price':invalidation,'time':last.time},
                        {'kind':'level','price':level,'time':last.time}))

        if kind=='IMPULSE_PULLBACK' and not impulse_ok:
            recent=bars[-5:-1]
            opposing=(last.close-last.open)*side<0
            extreme=max(x.high for x in recent) if side==1 else min(x.low for x in recent)
            retrace=(extreme-last.low) if side==1 else (last.high-extreme)
            if opposing and retrace>=profile.pullback_atr*a:
                pullback=last.low if side==1 else last.high
                trigger=last.high+pad if side==1 else last.low-pad
                level=highs[-1]['price'] if side==1 else lows[-1]['price']
                self.setup=Setup(event,side,kind,'TRIGGER',last.time,int(now+profile.setup_bars*tf),
                                 invalidation,level,extreme,pullback=pullback,trigger=trigger,
                                 trigger_bar=last.time,armed_msc=q.time_msc,last_bid=q.bid,
                                 seen_safe_side=False,last_bar=last.time)
                lines=({'kind':'invalidation','price':invalidation,'time':last.time},
                       {'kind':'level','price':level,'time':last.time},
                       {'kind':'trigger','price':trigger,'time':last.time})
                return Decision(phase='TRIGGER',
                    reason='Подтверждённый тренд; откат уже сформирован; ждём свежий пробой локального уровня',
                    side=side,stop=invalidation,trigger=trigger,invalidation=invalidation,atr=a,levels=lines,
                    path='TRIGGER',structure=structure)
            return Decision(reason='Структура есть; нового импульса или завершённого отката ещё нет',atr=a,structure=structure)

        self.setup=Setup(event,side,kind,'PULLBACK',last.time,int(now+profile.setup_bars*tf),
                         invalidation,highs[-1]['price'] if side==1 else lows[-1]['price'],
                         last.high if side==1 else last.low,last_bar=last.time)
        return Decision(phase='PULLBACK',reason='Новый '+kind+': ждём откат, ордер не отправлен',
                        side=side,invalidation=invalidation,atr=a,path='PULLBACK',structure=structure,
                        levels=({'kind':'invalidation','price':invalidation,'time':last.time},
                                {'kind':'level','price':self.setup.level,'time':last.time}))
