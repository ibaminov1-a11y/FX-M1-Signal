import tempfile
import time
import unittest
from pathlib import Path

from event_core.engine import Engine
from event_core.model import Bar
from event_core.mt5_adapter import MT5Broker
from event_core.store import Store
from fakes import FakeBroker, wave


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


class LayeredFakeBroker(FakeBroker):
    def __init__(self, clock):
        super().__init__(clock)
        end=int(clock())
        self.layers={
            'M1': wave(end,count=96,tf=60,trend=.000005),
            'M5': wave(end,count=96,tf=300,trend=.00002),
            'M15': wave(end,count=96,tf=900,trend=.00004),
            'H1': wave(end,count=96,tf=3600,trend=.00008),
        }
        start=end//300*300
        self.live_m5=Bar(start,1.1030,1.1037,1.1029,1.1036,3)
        self.market_requests=[]

    def bars(self, symbol, tf):
        self.market_requests.append(tf)
        return self.layers[tf]

    def current_bar(self, symbol, tf):
        self.market_requests.append('LIVE:'+tf)
        if tf!='M5':
            raise AssertionError('R3 current_bar is only required for M5')
        return self.live_m5


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

    def test_refresh_market_populates_each_r3_layer_without_mixing_live_bar(self):
        now=[1800000000.0]
        broker=LayeredFakeBroker(lambda:now[0])
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'state.sqlite3')
            try:
                engine=Engine(broker,store,lambda:now[0])
                engine._refresh_market(now[0])
                self.assertEqual(engine.bars, broker.layers['M5'])
                self.assertEqual(engine.m1, broker.layers['M1'])
                self.assertEqual(engine.m15, broker.layers['M15'])
                self.assertEqual(engine.h1, broker.layers['H1'])
                self.assertEqual(engine.live_bar, broker.live_m5)
                self.assertEqual(set(broker.market_requests), {'M1','M5','M15','H1','LIVE:M5'})
                self.assertLess(engine.bars[-1].time, engine.live_bar.time)
            finally:
                store.close()


if __name__=='__main__':
    unittest.main()
