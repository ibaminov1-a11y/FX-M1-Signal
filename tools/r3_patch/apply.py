from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

# 1) NORMAL setup lifetime: 3 x M5 = 15 minutes.
mp=ROOT/'mt5_bridge/event_core/model.py'
model=mp.read_text(encoding='utf-8')
old="'NORMAL': Profile('NORMAL', .35, .65, .60, 8, 12, 1.5, .50),"
new="'NORMAL': Profile('NORMAL', .35, .65, .60, 3, 12, 1.5, .50),"
if model.count(old)!=1:
    raise SystemExit('NORMAL profile block not found exactly once')
mp.write_text(model.replace(old,new,1),encoding='utf-8')

# 2) R3 continuation + fast-path supersession.
sp=ROOT/'mt5_bridge/event_core/strategy.py'
text=sp.read_text(encoding='utf-8')

insert_after="""        return Decision('BUY' if side==1 else 'SELL','ENTRY_READY',\n            'Большая M5 свеча + закрытое M1 подтверждение: быстрый вход по импульсу',\n            event,side,invalidation,trigger,invalidation,a,q.time_msc,lines,\n            path='IMPULSE',structure=structure)\n\n"""
continuation="""    def _r3_continuation(self,bars,m1,m15,h1,q,now,a,pad,profile,points,campaign_side=0):\n        \"\"\"Arm a shallow-pause continuation; execution still needs a later fresh tick cross.\"\"\"\n        if self.config.timeframe!='M5' or not m1 or not m15 or not h1 or len(bars)<6:\n            return None\n        side=direction(points)\n        if not side or (campaign_side and side!=campaign_side):\n            return None\n        if context_direction(m15)==-side or context_direction(h1)==-side:\n            return None\n        highs=[x for x in points if x['kind']=='H'];lows=[x for x in points if x['kind']=='L']\n        if not highs or not lows:\n            return None\n        source=bars[-1]\n        # A continuation needs an actual pause/micro-leg, not uninterrupted chasing.\n        if (source.close-source.open)*side>=0:\n            return None\n        recent=bars[-5:-1]\n        extreme=max(x.high for x in recent) if side==1 else min(x.low for x in recent)\n        pullback=source.low if side==1 else source.high\n        retrace=(extreme-pullback) if side==1 else (pullback-extreme)\n        if retrace<a*.10 or retrace>=profile.pullback_atr*a:\n            return None\n        trigger=source.high+pad if side==1 else source.low-pad\n        invalidation=lows[-1]['price']-pad if side==1 else highs[-1]['price']+pad\n        if (q.bid-invalidation)*side<=0:\n            return None\n        level=highs[-1]['price'] if side==1 else lows[-1]['price']\n        event=(f'{self.config.symbol}|M5|{self.config.mode}|CONTINUATION|'\n               f'{source.time:014d}|{side}|{trigger:.8f}')\n        if event in self.consumed:\n            return None\n        setup=Setup(event,side,'CONTINUATION','TRIGGER',source.time,\n                    int(now+profile.setup_bars*TF_SECONDS['M5']),invalidation,level,extreme,\n                    pullback=pullback,trigger=trigger,trigger_bar=source.time,\n                    armed_msc=q.time_msc,last_bid=q.bid,\n                    seen_safe_side=(q.bid-trigger)*side<=0,last_bar=source.time)\n        structure=tuple(swing_labels(bars)[-12:])\n        lines=({'kind':'invalidation','price':invalidation,'time':source.time},\n               {'kind':'level','price':level,'time':source.time},\n               {'kind':'trigger','price':trigger,'time':source.time})\n        decision=Decision(phase='TRIGGER',\n            reason='Неглубокая пауза в подтверждённом тренде; ждём свежее продолжение',\n            side=side,stop=invalidation,trigger=trigger,invalidation=invalidation,atr=a,levels=lines,\n            path='CONTINUATION',structure=structure)\n        return setup,decision\n\n"""
if text.count(insert_after)!=1:
    raise SystemExit('impulse return block not found exactly once')
text=text.replace(insert_after,insert_after+continuation,1)

old_fast="""        s=self.setup\n        # R3 fast path is evaluated only when no older setup currently owns the state.\n        # Task 4 will add explicit safe supersession rules for an existing pullback setup.\n        if s is None and self.config.timeframe=='M5':\n            fast=self._r3_impulse(bars,m1,m15,h1,live_bar,q,a,pad,profile,points,campaign_side)\n            if fast is not None:\n                return fast\n        if s and (now>s.expires or (s.side==1 and q.bid<=s.invalidation) or\n                  (s.side==-1 and q.bid>=s.invalidation) or (campaign_side and s.side!=campaign_side)):\n"""
new_fast="""        s=self.setup\n        if self.config.timeframe=='M5':\n            # A genuine same-side live acceleration may replace a stale pullback immediately.\n            if s is None or s.phase=='PULLBACK':\n                fast=self._r3_impulse(bars,m1,m15,h1,live_bar,q,a,pad,profile,points,campaign_side)\n                if fast is not None and (s is None or fast.side==s.side):\n                    self.setup=None\n                    return fast\n            # Confirmed opposite higher-timeframe context invalidates a pending new-entry idea.\n            if s and ((m15 and context_direction(m15)==-s.side) or\n                      (h1 and context_direction(h1)==-s.side)):\n                old_id=s.id;self.consume(old_id)\n                return Decision(phase='CANCELLED',reason='Сценарий отменён: старший контекст развернулся',\n                                atr=a,path='SEARCH',structure=tuple(swing_labels(bars)[-12:]))\n            # With no setup, a shallow 0.10-0.35 ATR pause can arm CONTINUATION.\n            if s is None:\n                continuation=self._r3_continuation(bars,m1,m15,h1,q,now,a,pad,profile,points,campaign_side)\n                if continuation is not None:\n                    self.setup,decision=continuation\n                    return decision\n        if s and (now>s.expires or (s.side==1 and q.bid<=s.invalidation) or\n                  (s.side==-1 and q.bid>=s.invalidation) or (campaign_side and s.side!=campaign_side)):\n"""
if text.count(old_fast)!=1:
    raise SystemExit('R3 fast path block not found exactly once')
text=text.replace(old_fast,new_fast,1)

# Propagate the chosen path and structural overlays through an existing setup.
old_lines="""        if s:\n            lines=({'kind':'invalidation','price':s.invalidation,'time':s.born},\n                   {'kind':'level','price':s.level,'time':s.born})\n            if s.phase=='TRIGGER':\n"""
new_lines="""        if s:\n            setup_path='CONTINUATION' if s.kind=='CONTINUATION' else 'PULLBACK'\n            structure=tuple(swing_labels(bars)[-12:]) if self.config.timeframe=='M5' else ()\n            lines=({'kind':'invalidation','price':s.invalidation,'time':s.born},\n                   {'kind':'level','price':s.level,'time':s.born})\n            if s.phase=='TRIGGER':\n"""
if text.count(old_lines)!=1:
    raise SystemExit('setup lines block not found exactly once')
text=text.replace(old_lines,new_lines,1)

old_entry="""                    return Decision('BUY' if s.side==1 else 'SELL','ENTRY_READY',\n                        'Откат/ретест завершён; свежая котировка пересекла триггер',s.id,s.side,\n                        stop,s.trigger,s.invalidation,a,q.time_msc,lines)\n                return Decision(phase='TRIGGER',reason='Откат есть; ждём пересечение локального уровня',\n                                side=s.side,stop=s.invalidation,trigger=s.trigger,invalidation=s.invalidation,atr=a,levels=lines)\n            return Decision(phase='PULLBACK',reason='Импульс/структура подтверждены; ждём откат/ретест',\n                            side=s.side,invalidation=s.invalidation,atr=a,levels=lines)\n"""
new_entry="""                    return Decision('BUY' if s.side==1 else 'SELL','ENTRY_READY',\n                        'Продолжение подтверждено; свежая котировка пересекла триггер' if setup_path=='CONTINUATION' else\n                        'Откат/ретест завершён; свежая котировка пересекла триггер',s.id,s.side,\n                        stop,s.trigger,s.invalidation,a,q.time_msc,lines,\n                        path=setup_path,structure=structure)\n                return Decision(phase='TRIGGER',\n                                reason='Неглубокая пауза есть; ждём пересечение локального уровня' if setup_path=='CONTINUATION' else\n                                       'Откат есть; ждём пересечение локального уровня',\n                                side=s.side,stop=s.invalidation,trigger=s.trigger,invalidation=s.invalidation,atr=a,levels=lines,\n                                path=setup_path,structure=structure)\n            return Decision(phase='PULLBACK',reason='Импульс/структура подтверждены; ждём откат/ретест',\n                            side=s.side,invalidation=s.invalidation,atr=a,levels=lines,\n                            path='PULLBACK',structure=structure)\n"""
if text.count(old_entry)!=1:
    raise SystemExit('setup decision block not found exactly once')
text=text.replace(old_entry,new_entry,1)

# H1 is an additional blocker for newly created classic R3 M5 entries.
old_ctx="""        if ctx and ctx!=side:\n            return Decision(reason='Контекст старшего ТФ против сценария; новый вход запрещён',atr=a)\n"""
new_ctx="""        h1_dir=context_direction(h1) if self.config.timeframe=='M5' and h1 else 0\n        if (ctx and ctx!=side) or h1_dir==-side:\n            return Decision(reason='Контекст старшего ТФ против сценария; новый вход запрещён',atr=a,\n                            structure=tuple(swing_labels(bars)[-12:]) if self.config.timeframe=='M5' else ())\n"""
if text.count(old_ctx)!=1:
    raise SystemExit('classic context block not found exactly once')
text=text.replace(old_ctx,new_ctx,1)

sp.write_text(text,encoding='utf-8')
