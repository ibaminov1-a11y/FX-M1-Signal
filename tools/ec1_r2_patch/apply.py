from pathlib import Path

p=Path('mt5_bridge/event_core/strategy.py')
s=p.read_text(encoding='utf-8')
old="""        if kind=='IMPULSE_PULLBACK' and (last.close-bars[-4].close)*side<a*.8:\n            return Decision(reason='Структура есть; нового импульса ещё нет',atr=a)\n        invalidation=lows[-1]['price']-pad if side==1 else highs[-1]['price']+pad\n        if (last.close-invalidation)*side<=0:\n            return Decision(reason='Уровень отмены сценария уже пробит',atr=a)\n        event=f'{self.config.symbol}|{self.config.timeframe}|{self.config.mode}|{last.time:014d}|{side}'\n"""
new="""        invalidation=lows[-1]['price']-pad if side==1 else highs[-1]['price']+pad\n        if (last.close-invalidation)*side<=0:\n            return Decision(reason='Уровень отмены сценария уже пробит',atr=a)\n        event=f'{self.config.symbol}|{self.config.timeframe}|{self.config.mode}|{last.time:014d}|{side}'\n        if kind=='IMPULSE_PULLBACK' and (last.close-bars[-4].close)*side<a*.8:\n            # The process may first observe an already established trend during its pullback.\n            # Do not require witnessing the original impulse live: reconstruct only from\n            # confirmed closed bars, then still require a NEW quote crossing after arming.\n            recent=bars[-5:-1]\n            opposing=(last.close-last.open)*side<0\n            extreme=max(x.high for x in recent) if side==1 else min(x.low for x in recent)\n            retrace=(extreme-last.low) if side==1 else (last.high-extreme)\n            if opposing and retrace>=profile.pullback_atr*a:\n                if event in self.consumed:\n                    return Decision(reason='Это событие уже обработано',atr=a)\n                pullback=last.low if side==1 else last.high\n                trigger=last.high+pad if side==1 else last.low-pad\n                level=highs[-1]['price'] if side==1 else lows[-1]['price']\n                self.setup=Setup(event,side,kind,'TRIGGER',last.time,int(now+profile.setup_bars*tf),\n                                 invalidation,level,extreme,pullback=pullback,trigger=trigger,\n                                 trigger_bar=last.time,armed_msc=q.time_msc,last_bid=q.bid,\n                                 seen_safe_side=False,last_bar=last.time)\n                lines=({'kind':'invalidation','price':invalidation,'time':last.time},\n                       {'kind':'level','price':level,'time':last.time},\n                       {'kind':'trigger','price':trigger,'time':last.time})\n                return Decision(phase='TRIGGER',\n                    reason='Подтверждённый тренд; откат уже сформирован; ждём свежий пробой локального уровня',\n                    side=side,stop=invalidation,trigger=trigger,invalidation=invalidation,atr=a,levels=lines)\n            return Decision(reason='Структура есть; нового импульса или завершённого отката ещё нет',atr=a)\n"""
if old not in s:
    raise SystemExit('strategy target block not found; refusing blind patch')
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')

v=Path('mt5_bridge/event_core/__init__.py')
t=v.read_text(encoding='utf-8')
for old_build in ("BUILD = '10.9-EC1-R2.3'","BUILD = '10.9-EC1-R2.4'"):
    if old_build in t:
        t=t.replace(old_build,"BUILD = '10.9-EC1-R2.5'",1)
        break
v.write_text(t,encoding='utf-8')
print('patched: bootstrap confirmed pullback to fresh trigger; build R2.5')
