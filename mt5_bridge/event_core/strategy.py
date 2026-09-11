from __future__ import annotations
from dataclasses import asdict
from .model import Bar, Quote, Config, Setup, Decision, PROFILES, TF_SECONDS, atr, ordered, pivots, direction, Blocked


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

    def update(self, bars: list[Bar], context: list[Bar], q: Quote, now: float, campaign_side=0):
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
        ctx=direction(pivots(context))
        last=bars[-1]
        s=self.setup
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
            return Decision(phase='PULLBACK',reason='Импульс подтверждён; ждём откат/ретест',
                            side=s.side,invalidation=s.invalidation,atr=a,levels=lines)
        if last.time<=self.last_scanned:
            return Decision(reason='Нового структурного события пока нет',atr=a)
        self.last_scanned=last.time
        # Only pivots known before this impulse candle. No retrospective pivot at entry.
        known=[p for p in points if p['known_at']<last.time]
        highs=[p for p in known if p['kind']=='H']; lows=[p for p in known if p['kind']=='L']
        if not highs or not lows:
            return Decision(reason='Нужны подтверждённые вершина и впадина',atr=a)
        prev=bars[-2]
        up=last.close>highs[-1]['price']+pad and prev.close<=highs[-1]['price']+pad
        down=last.close<lows[-1]['price']-pad and prev.close>=lows[-1]['price']-pad
        side=1 if up else -1 if down else direction(known)
        kind='BREAK_RETEST' if up or down else 'IMPULSE_PULLBACK'
        if not side or (campaign_side and side!=campaign_side):
            return Decision(reason='Нет согласованного структурного сценария',atr=a)
        if ctx and ctx!=side:
            return Decision(reason='Контекст старшего ТФ против сценария; новый вход запрещён',atr=a)
        if kind=='IMPULSE_PULLBACK' and (last.close-bars[-4].close)*side<a*.8:
            return Decision(reason='Структура есть; нового импульса ещё нет',atr=a)
        invalidation=lows[-1]['price']-pad if side==1 else highs[-1]['price']+pad
        if (last.close-invalidation)*side<=0:
            return Decision(reason='Уровень отмены сценария уже пробит',atr=a)
        event=f'{self.config.symbol}|{self.config.timeframe}|{self.config.mode}|{last.time:014d}|{side}'
        if event in self.consumed:
            return Decision(reason='Это событие уже обработано',atr=a)
        self.setup=Setup(event,side,kind,'PULLBACK',last.time,int(now+profile.setup_bars*tf),
                         invalidation,highs[-1]['price'] if side==1 else lows[-1]['price'],
                         last.high if side==1 else last.low,last_bar=last.time)
        return Decision(phase='PULLBACK',reason='Новый '+kind+': ждём откат, ордер не отправлен',
                        side=side,invalidation=invalidation,atr=a,
                        levels=({'kind':'invalidation','price':invalidation,'time':last.time},
                                {'kind':'level','price':self.setup.level,'time':last.time}))
