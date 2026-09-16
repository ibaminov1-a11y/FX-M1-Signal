import tempfile
import time
import unittest
from pathlib import Path

from event_core.engine import Engine
from event_core.mt5_adapter import MT5Broker
from event_core.store import Store
from fakes import FakeBroker


class FakeMT5Rates:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60

    def __init__(self):
        self.calls=[]

    def last_error(self):
        return (1, 'ok')

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.calls.append((symbol, timeframe, start_pos, count))
        spans={self.TIMEFRAME_M1:60,self.TIMEFRAME_M5:300,self.TIMEFRAME_M15:900,self.TIMEFRAME_H1:3600}
        span=spans[timeframe]
        now=time.time()
        current=int(now//span*span)
        rows=[]
        for i in range(48,0,-1):
            t=current-i*span
            rows.append(dict(time=t,open=1.1000,high=1.1004,low=1.0998,close=1.1002,tick_volume=10))
        rows.append(dict(time=current,open=1.1002,high=1.1008,low=1.1001,close=1.1007,tick_volume=3))
        return rows


class R3MarketSnapshotTests(unittest.TestCase):
    def test_adapter_exposes_forming_bar_separately_from_closed_history(self):
        self.assertTrue(hasattr(MT5Broker, 'current_bar'), 'R3 needs a current_bar() API')
        mt5=FakeMT5Rates(); broker=MT5Broker(mt5)
        closed=broker.bars('EURUSD','M5')
        live=broker.current_bar('EURUSD','M5')
        self.assertLess(closed[-1].time, live.time)
        self.assertGreater(live.high, live.open)

    def test_engine_has_independent_r3_market_layers(self):
        now=[1800000000.0]
        broker=FakeBroker(lambda:now[0])
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'state.sqlite3')
            try:
                engine=Engine(broker,store,lambda:now[0])
                for name in ('m1','m15','h1','live_bar'):
                    self.assertTrue(hasattr(engine,name),f'R3 Engine missing {name}')
            finally:
                store.close()


if __name__=='__main__':
    unittest.main()
