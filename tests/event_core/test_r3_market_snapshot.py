import tempfile
import time
import unittest
from pathlib import Path

from event_core.engine import Engine
from event_core.mt5_adapter import MT5Broker
from event_core.store import Store
from fakes import FakeBroker


class FakeMT5Rates:
    TIMEFRAME_M5 = 5

    def last_error(self):
        return (1, 'ok')

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        span = 300
        current = int(time.time() // span * span)
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


if __name__ == '__main__':
    unittest.main()
