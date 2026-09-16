import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from event_core.engine import Engine
from event_core.model import Bar
from event_core.mt5_adapter import MT5Broker
from event_core.store import Store
from fakes import FakeBroker


BASE = 1_800_000_000


class _Tick:
    def __init__(self, seconds):
        self.time_msc = int(seconds * 1000)
        self.bid = 1.15328
        self.ask = 1.15329


class _OffsetMT5:
    TIMEFRAME_M5 = 5

    def __init__(self, server_now):
        self.server_now = server_now

    def symbol_info_tick(self, symbol):
        return _Tick(self.server_now)

    def last_error(self):
        return (1, 'ok')

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        current = int(self.server_now // 300 * 300)
        return [
            dict(time=current - 600, open=1.1530, high=1.1534, low=1.1529, close=1.1532, tick_volume=10),
            dict(time=current - 300, open=1.1532, high=1.1535, low=1.1531, close=1.1533, tick_volume=10),
            dict(time=current,       open=1.1533, high=1.1534, low=1.1532, close=1.15328, tick_volume=3),
        ]


class _ServerClockBroker(FakeBroker):
    def __init__(self, clock, offset):
        super().__init__(clock)
        self.offset = offset

    def market_time(self, symbol):
        return self.clock() + self.offset


class MT5MarketClockTests(unittest.TestCase):
    def test_closed_bar_filter_uses_mt5_server_clock_not_windows_clock(self):
        # Screenshot shape: Windows is 17:23:17 while the MT5 server is already
        # 17:25:17. The 17:20 MT5 candle is closed on the server and must not be
        # discarded merely because its raw timestamp is ahead of the PC clock.
        local_now = BASE + 197.0
        server_now = local_now + 120.0
        mt5 = _OffsetMT5(server_now)
        broker = MT5Broker(mt5)
        with patch('event_core.mt5_adapter.time.time', return_value=local_now), \
             patch('event_core.mt5_adapter.time.monotonic', return_value=10.0):
            broker.quote('EURUSD')  # establish the MT5 raw clock observation
            bars = broker.bars('EURUSD', 'M5')
        self.assertEqual(bars[-1].time, BASE)

    def test_engine_validates_current_m5_against_mt5_clock_domain(self):
        local_now = [BASE + 197.0]
        broker = _ServerClockBroker(lambda: local_now[0], offset=120.0)
        # Raw MT5 server candle 17:25 is +103 s versus Windows, but already open
        # for 17 s according to the MT5 server clock.
        broker.live_bar_data = Bar(BASE + 300, 1.1533, 1.1534, 1.1532, 1.15328, 3)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'state.sqlite3')
            try:
                engine = Engine(broker, store, lambda: local_now[0])
                engine._refresh_market(local_now[0])
                self.assertEqual(engine.live_bar, broker.live_bar_data)
                self.assertFalse(any('текущую M5 свечу из будущего' in x for x in engine.market_errors), engine.market_errors)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
