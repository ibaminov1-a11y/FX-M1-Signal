import unittest
from unittest.mock import patch

from event_core.mt5_adapter import MT5Broker


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


class MT5MarketClockTests(unittest.TestCase):
    def test_closed_bar_filter_uses_same_normalized_clock_as_quote(self):
        # Screenshot shape: Windows is 17:23:17 while the MT5 server is already
        # 17:25:17. Ticks are normalized to Windows time, so candles must be
        # normalized by the same observed +120 s server offset before closure checks.
        local_now = BASE + 197.0
        server_now = local_now + 120.0
        mt5 = _OffsetMT5(server_now)
        broker = MT5Broker(mt5)
        with patch('event_core.mt5_adapter.time.time', return_value=local_now), \
             patch('event_core.mt5_adapter.time.monotonic', return_value=10.0):
            broker.quote('EURUSD')
            bars = broker.bars('EURUSD', 'M5')
        # Raw closed MT5 bar is BASE; normalized wall-clock opening time is BASE-120.
        self.assertEqual(bars[-1].time, BASE - 120)

    def test_current_bar_uses_same_normalized_clock_as_quote(self):
        local_now = BASE + 197.0
        server_now = local_now + 120.0
        mt5 = _OffsetMT5(server_now)
        broker = MT5Broker(mt5)
        with patch('event_core.mt5_adapter.time.time', return_value=local_now), \
             patch('event_core.mt5_adapter.time.monotonic', return_value=10.0):
            broker.quote('EURUSD')
            live = broker.current_bar('EURUSD', 'M5')
        # Raw server candle opens at BASE+300 (103 s "future" versus Windows),
        # but on the normalized quote clock it opened at BASE+180, 17 s ago.
        self.assertEqual(live.time, BASE + 180)
        self.assertLessEqual(live.time, local_now)


if __name__ == '__main__':
    unittest.main()
