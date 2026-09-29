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
    def test_closed_bar_filter_preserves_native_utc_clock(self):
        # A 120-second discrepancy must not rewrite every historical candle ID.
        # Only candles certainly closed on native UTC time can enter analysis.
        local_now = BASE + 197.0
        server_now = local_now + 120.0
        mt5 = _OffsetMT5(server_now)
        broker = MT5Broker(mt5)
        with patch('event_core.mt5_adapter.time.time', return_value=local_now), \
             patch('event_core.mt5_adapter.time.monotonic', return_value=10.0):
            broker.quote('EURUSD')
            bars = broker.bars('EURUSD', 'M5')
        # BASE is not certainly closed at local BASE+197; BASE-300 is closed.
        self.assertEqual(bars[-1].time, BASE - 300)

    def test_current_bar_keeps_native_identity_even_when_the_clock_is_wrong(self):
        local_now = BASE + 197.0
        server_now = local_now + 120.0
        mt5 = _OffsetMT5(server_now)
        broker = MT5Broker(mt5)
        with patch('event_core.mt5_adapter.time.time', return_value=local_now), \
             patch('event_core.mt5_adapter.time.monotonic', return_value=10.0):
            broker.quote('EURUSD')
            live = broker.current_bar('EURUSD', 'M5')
        # The adapter does not conceal the future timestamp. Engine's guard
        # rejects it; making it appear 120 seconds older would corrupt the cache.
        self.assertEqual(live.time, BASE + 300)
        self.assertGreater(live.time, local_now)


if __name__ == '__main__':
    unittest.main()
