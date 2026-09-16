from __future__ import annotations
from dataclasses import asdict
from .model import Bar, Quote, Config, Setup, Decision, PROFILES, TF_SECONDS, atr, ordered, pivots, direction, swing_labels, context_direction, Blocked


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
        self.setup=None

    def clear(self):
        self.setup=None
        self.previous_quote=None

    def _r3_impulse(self,bars,m1,m15,h1,live_bar,q,a,pad,profile,points,campaign_side=0):
        """Return an R3 live-M5 IMPULSE entry or None.

        Confirmed pivots and higher-timeframe context remain closed-bar only. The forming
        M5 candle is allowed solely to qualify a large impulse; a CLOSED M1 candle plus
        the live tick must already be beyond the broken M5 level.
        """
        if self.config.timeframe!='M5' or live_bar is None or not m1 or not m15 or not h1:
            return None
        body=abs(live_bar.close-live_bar.open)
        span=live_bar.high-live_bar.low
        if span<=0 or body<a*.70 or span<a*1.00 or body/span<.65:
            return None
        side=1 if live_bar.close>live_bar.open else -1 if live_bar.close<live_bar.open else 0
        if not side or (campaign_side and side!=campaign_side):
            return None
        highs=[x for x in points if x['kind']=='H'];lows=[x for x in points if x['kind']=='L']
        if not highs or not lows:
            return None
        level=highs[-1]['price'] if side==1 else lows[-1]['price']
        trigger=level+side*pad
        # The forming M5 candle and current quote must have actually broken the level.
        if (live_bar.close-trigger)*side<=0 or (q.bid-trigger)*side<=0:
            return None
        # A confirmed opposite M5/H1/M15 structure blocks a fast entry; neutral is allowed.
        m5_dir=direction(points)
        if m5_dir==-side or context_direction(m15)==-side or context_direction(h1)==-side:
            return None
        # One large spike is not enough: the latest CLOSED M1 must confirm beyond the break.
        last_m1=m1[-1]
        if (last_m1.close-last_m1.open)*side<=0 or (last_m1.close-trigger)*side<=0:
            return None
        # Do not buy/sell the end of an already overextended candle.
        if abs(q.bid-trigger)>profile.no_chase_atr*a:
            return None
        invalidation=(lows[-1]['price']-pad) if side==1 else (highs[-1]['price']+pad)
        if (q.bid-invalidation)*side<=0:
            return None
        event=(f'{self.config.symbol}|M5|{self.config.mode}|IMPULSE|'
               f'{live_bar.time:014d}|{side}|{level:.8f}')
        if event in self.consumed:
            return None
        structure=tuple(swing_labels(bars)[-12:])
        lines=({'kind':'invalidation','price':invalidation,'time':live_bar.time},
               {'kind':'level','price':level,'time':live_bar.time},
               {'kind':'trigger','price':trigger,'time':live_bar.time})
        return Decision('BUY' if side==1 else 'SELL','ENTRY_READY',
            'Большая M5 свеча + закрытое M1 подтверждение: быстрый вход по импульсу',
            event,side,invalidation,trigger,invalidation,a,q.time_msc,lines,
            path='IMPULSE',structure=structure)

    def update(self, bars: list[Bar], context: list[Bar], q: Quote, now: float, campaign_side=0, *,
               m1=None, m15=None, h1=None, live_bar=None):
        q.validate(now); ordered(bars); ordered(context)
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
        ctx_bars=m15 if m15 is not None else context
        ctx=direction(pivots(ctx_bars))
        last=bars[-1]
        s=self.setup
        # R3 fast path is evaluated only when no older setup currently owns the state.
        # Task 4 will add explicit safe supersession rules for an existing pullback setup.
        if s is None and self.config.timeframe=='M5':
            fast=self._r3_impulse(bars,m1,m15,h1,live_bar,q,a,pad,profile,points,campaign_side)
            if fast is not None:
                return fast
        if s and (now>s.expires or (s.side==1 and q.bid<=s.invalidation) or
                  (s.side==-1 and q.bid>=s.invalidation) or (campaign_side and s.side!=campaign_side)):
            self.consume(s.id)
            return Decision(phase='CANCELLED',reason='Сценарий отменён: срок/структура',atr=a)
        if s and last.time>s.last_bar:
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
                on_safe=(q.bid-s.trigger)*s.side<=0
                crossed=s.seen_safe_side and q.time_msc>s.armed_msc and (q.bid-s.trigger)*s.side>0 and (s.last_bid-s.trigger)*s.side<=0
                s.seen_safe_side|=on_safe
                s.last_bid=q.bid
                if crossed and s.id not in self.consumed:
                    if abs(q.bid-s.trigger)>profile.no_chase_atr*a:
                        self.consume(s.id)
                        return Decision(phase='CANCELLED',reason='Резкий скачок за триггер: вход не догоняем',atr=a,levels=lines)
                    stop=(s.pullback-pad if s.side==1 else s.pullback+pad)
                    if self.config.mode=='NORMAL':
                        stop=min(stop,s.invalidation) if s.side==1 else max(stop,s.invalidation)
                    return Decision('BUY' if s.side==1 else 'SELL','ENTRY_READY',
                        'Откат/ретест завершён; свежая котировка пересекла триггер',s.id,s.side,
                        stop,s.trigger,s.invalidation,a,q.time_msc,lines)
                return Decision(phase='TRIGGER',reason='Откат есть; ждём пересечение локального уровня',
                                side=s.side,stop=s.invalidation,trigger=s.trigger,invalidation=s.invalidation,atr=a,levels=lines)
            return Decision(phase='PULLBACK',reason='Импульс/структура подтверждены; ждём откат/ретест',
                            side=s.side,invalidation=s.invalidation,atr=a,levels=lines)
        if last.time<=self.last_scanned:
            return Decision(reason='Нового структурного события пока нет',atr=a)
        self.last_scanned=last.time

        # A pivot confirmed by the just-closed bar is known NOW and is therefore safe to use.
        # The previous strict '< last.time' skipped exactly those fresh structure events.
        known=[p for p in points if p['known_at']<=last.time]
        fresh=[p for p in known if p['known_at']==last.time]
        highs=[p for p in known if p['kind']=='H']; lows=[p for p in known if p['kind']=='L']
        if not highs or not lows:
            return Decision(reason='Нужны подтверждённые вершина и впадина',atr=a)
        prev=bars[-2]
        up=last.close>highs[-1]['price']+pad and prev.close<=highs[-1]['price']+pad
        down=last.close<lows[-1]['price']-pad and prev.close>=lows[-1]['price']-pad
        structural_side=direction(known)
        side=1 if up else -1 if down else structural_side
        kind='BREAK_RETEST' if up or down else 'IMPULSE_PULLBACK'
        if not side or (campaign_side and side!=campaign_side):
            return Decision(reason='Нет согласованного структурного сценария',atr=a)
        if ctx and ctx!=side:
            return Decision(reason='Контекст старшего ТФ против сценария; новый вход запрещён',atr=a)
        invalidation=lows[-1]['price']-pad if side==1 else highs[-1]['price']+pad
        if (last.close-invalidation)*side<=0:
            return Decision(reason='Уровень отмены сценария уже пробит',atr=a)
        event=f'{self.config.symbol}|{self.config.timeframe}|{self.config.mode}|{last.time:014d}|{side}'
        if event in self.consumed:
            return Decision(reason='Это событие уже обработано',atr=a)

        impulse_ok=kind!='IMPULSE_PULLBACK' or (last.close-bars[-4].close)*side>=a*.8
        fresh_structure=bool(fresh) and structural_side==side

        if kind=='IMPULSE_PULLBACK' and not impulse_ok and fresh_structure:
            # Smooth stair-step trends often confirm a new HH/HL or LH/LL without one large
            # 3-bar candle burst. A newly CONFIRMED pivot is itself a fresh structural event.
            # It may arm a scenario, but it still cannot open a trade without a later quote
            # crossing, so this does not turn trend recognition into an immediate order.
            favorable_kind='H' if side==1 else 'L'
            favorable=[p for p in fresh if p['kind']==favorable_kind]
            level=highs[-1]['price'] if side==1 else lows[-1]['price']
            extreme=(favorable[-1]['price'] if favorable else
                     (last.high if side==1 else last.low))
            setup_kind='STRUCTURE_PULLBACK'
            self.setup=Setup(event,side,setup_kind,'PULLBACK',last.time,int(now+profile.setup_bars*tf),
                             invalidation,level,extreme,last_bar=last.time)

            # If the pivot being confirmed is the favorable impulse extreme, the two bars
            # that confirmed it may already form the pullback. Arm a NEW future crossing
            # from that closed-bar information instead of discarding the completed pullback.
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
                            invalidation=invalidation,atr=a,levels=lines)
            return Decision(phase='PULLBACK',
                reason='Свежая подтверждённая структура; ждём откат/ретест, ордер не отправлен',
                side=side,invalidation=invalidation,atr=a,
                levels=({'kind':'invalidation','price':invalidation,'time':last.time},
                        {'kind':'level','price':level,'time':last.time}))

        if kind=='IMPULSE_PULLBACK' and not impulse_ok:
            # The process may first observe an already established trend during its pullback.
            # Do not require witnessing the original impulse live: reconstruct only from
            # confirmed closed bars, then still require a NEW quote crossing after arming.
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
                    side=side,stop=invalidation,trigger=trigger,invalidation=invalidation,atr=a,levels=lines)
            return Decision(reason='Структура есть; нового импульса или завершённого отката ещё нет',atr=a)

        self.setup=Setup(event,side,kind,'PULLBACK',last.time,int(now+profile.setup_bars*tf),
                         invalidation,highs[-1]['price'] if side==1 else lows[-1]['price'],
                         last.high if side==1 else last.low,last_bar=last.time)
        return Decision(phase='PULLBACK',reason='Новый '+kind+': ждём откат, ордер не отправлен',
                        side=side,invalidation=invalidation,atr=a,
                        levels=({'kind':'invalidation','price':invalidation,'time':last.time},
                                {'kind':'level','price':self.setup.level,'time':last.time}))