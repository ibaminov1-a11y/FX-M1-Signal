import tempfile
import unittest
from pathlib import Path

from event_core.engine import Engine
from event_core.model import Bar
from event_core.store import Store
from fakes import FakeBroker


class LiveBarLoadingTests(unittest.TestCase):
    def test_current_open_bar_does_not_hide_closed_history(self):
        now = 1_800_000_123.0
        broker = FakeBroker(lambda: now)
        m5_open = int(now // 300 * 300)
        m15_open = int(now // 900 * 900)
        broker.bar_data = broker.bar_data + [Bar(m5_open, 1.1030, 1.1034, 1.1028, 1.1032, 5)]
        broker.ctx_data = broker.ctx_data + [Bar(m15_open, 1.1030, 1.1035, 1.1027, 1.1031, 5)]
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td) / 'state.db')
            try:
                engine = Engine(broker, store, lambda: now)
                state = engine.step()
                self.assertGreaterEqual(len(state['bars']), 32)
                self.assertLessEqual(state['bars'][-1]['time'] + 300, now)
                self.assertFalse(state['market_errors'])
                self.assertGreater(state['analysis_time'], 0)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
