"""Read-only diagnostic. Does not enable AUTO, send orders, or change clock settings."""
from datetime import datetime, timezone
from pathlib import Path
import json
import time
import MetaTrader5 as mt5


def main():
    if not mt5.initialize():raise RuntimeError(str(mt5.last_error()))
    try:
        account=mt5.account_info()
        if account is None:raise RuntimeError('MT5 account unavailable')
        rows=mt5.symbols_get() or ()
        name=next((s.name for s in rows if s.visible and s.name.startswith('EURUSD')),None)
        if name is None:name=next((s.name for s in rows if s.visible),None)
        samples=[]
        for _ in range(3):
            tick=mt5.symbol_info_tick(name) if name else None
            now=time.time()
            samples.append(dict(pc_utc=datetime.fromtimestamp(now,timezone.utc).isoformat(),
                pc_epoch=now,raw_tick_msc=int(tick.time_msc) if tick else None,
                raw_tick_minus_pc_seconds=round(tick.time_msc/1000-now,3) if tick else None))
            time.sleep(1)
        data=dict(account=f'{account.login}@{account.server}',symbol=name,samples=samples,
            explanation='Difference is diagnostic only: it does not prove broker timezone or PC clock correctness.',
            configured_clock='event_state/broker-clock.json if explicitly created; default native UTC')
        path=Path(__file__).resolve().parent/'BROKER_CLOCK_DIAGNOSTIC.json'
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(data,ensure_ascii=False,indent=2))
        print('Saved:',path)
    finally:mt5.shutdown()


if __name__=='__main__':main()
