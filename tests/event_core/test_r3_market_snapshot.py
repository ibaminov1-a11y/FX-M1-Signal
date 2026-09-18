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
    TIMEFRAME_M5 = 5

    def __init__(self):
        self.current=int(time.time()//300*300)

    def last_error(self):
        return (1, 'ok')

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        span = 300
        current = self.current
        rows = []
        for t in (current - 600, current - 300, current):
            rows.append(dict(
                time=t,
                open=1.1000,
                high=1.1008,
                low=1.0998,
                close=1.1005,
                tick_volume=10,
            ))
        return rows


class LayeredBroker(FakeBroker):
    def __init__(self, clock):
        super().__init__(clock)
        end = int(clock())
        self.layers = {
            'M1': wave(end, count=96, tf=60, trend=.000006),
            'M5': wave(end, count=96, tf=300, trend=.00003),
            'M15': wave(end, count=96, tf=900, trend=.00004),
            'H1': wave(end, count=96, tf=3600, trend=.00008),
        }
        start = end // 300 * 300
        self.live_m5 = Bar(start, 1.1030, 1.1037, 1.1029, 1.1036, 3)
        self.requests = []

    def bars(self, symbol, tf):
        self.requests.append(tf)
        return self.layers[tf]

    def current_bar(self, symbol, tf):
        self.requests.append('LIVE:' + tf)
        if tf != 'M5':
            raise AssertionError('R3 only requests the forming M5 candle')
        return self.live_m5


class R3MarketSnapshotTests(unittest.TestCase):
    def test_current_m5_is_separate_from_closed_history(self):
        broker = MT5Broker(FakeMT5Rates())
        closed = broker.bars('EURUSD', 'M5')
        live = broker.current_bar('EURUSD', 'M5')
        self.assertLess(closed[-1].time, live.time)
        self.assertNotIn(live.time, {bar.time for bar in closed})

    def test_engine_declares_independent_r3_market_layers(self):
        now = [1800000000.0]
        broker = FakeBroker(lambda: now[0])
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'state.sqlite3')
            try:
                engine = Engine(broker, store, lambda: now[0])
                for name in ('m1', 'm15', 'h1', 'live_bar'):
                    self.assertTrue(hasattr(engine, name), f'Engine missing R3 market field: {name}')
            finally:
                store.close()

    def test_refresh_market_populates_each_r3_layer_without_mixing_live_bar(self):
        now = [1800000000.0]
        broker = LayeredBroker(lambda: now[0])
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'state.sqlite3')
            try:
                engine = Engine(broker, store, lambda: now[0])
                engine._refresh_market(now[0])
                self.assertEqual(engine.bars, broker.layers['M5'])
                self.assertEqual(engine.m1, broker.layers['M1'])
                self.assertEqual(engine.m15, broker.layers['M15'])
                self.assertEqual(engine.h1, broker.layers['H1'])
                self.assertEqual(engine.live_bar, broker.live_m5)
                self.assertEqual(set(broker.requests), {'M1', 'M5', 'M15', 'H1', 'LIVE:M5'})
                self.assertLess(engine.bars[-1].time, engine.live_bar.time)
            finally:
                store.close()

    def test_small_broker_clock_skew_does_not_discard_current_m5(self):
        # Real terminals can cross an M5 boundary a few seconds before the PC wall clock.
        # The forming bar is isolated from closed-history pivots, so a small skew must not
        # turn otherwise fresh MT5 data into DATA_BLOCK.
        now = [1800000284.0]  # local 16 seconds before the next M5 boundary
        broker = LayeredBroker(lambda: now[0])
        broker.live_m5 = Bar(1800000300, 1.1030, 1.1037, 1.1029, 1.1036, 3)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'state.sqlite3')
            try:
                engine = Engine(broker, store, lambda: now[0])
                engine._refresh_market(now[0])
                self.assertEqual(engine.live_bar, broker.live_m5)
                self.assertFalse(any('текущую M5 свечу из будущего' in x for x in engine.market_errors), engine.market_errors)
            finally:
                store.close()

    def test_large_future_live_m5_is_still_rejected(self):
        now = [1800000284.0]
        broker = LayeredBroker(lambda: now[0])
        broker.live_m5 = Bar(1800000585, 1.1030, 1.1037, 1.1029, 1.1036, 3)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'state.sqlite3')
            try:
                engine = Engine(broker, store, lambda: now[0])
                engine._refresh_market(now[0])
                self.assertIsNone(engine.live_bar)
                self.assertTrue(any('текущую M5 свечу из будущего' in x for x in engine.market_errors), engine.market_errors)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
