from pathlib import Path

p=Path('mt5_bridge/event_core/engine.py')
s=p.read_text(encoding='utf-8')
old="""                if not self.auto or self.paused:self.execution=self._idle_status()\n                elif now-self.heartbeat>30:\n                    self.auto=False;self.paused=True;self.execution='Нет связи с телефоном 30 секунд: новые входы остановлены';self.save()\n                elif self.recovery:self.execution='Нужна сверка неизвестного исполнения; новые входы запрещены'\n"""
new="""                if not self.auto or self.paused:self.execution=self._idle_status()\n                elif self.recovery:self.execution='Нужна сверка неизвестного исполнения; новые входы запрещены'\n"""
if old not in s:
    raise SystemExit('heartbeat block not found; refusing blind patch')
p.write_text(s.replace(old,new,1),encoding='utf-8')
print('patched: AUTO no longer depends on phone foreground heartbeat')
