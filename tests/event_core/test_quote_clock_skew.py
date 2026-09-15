import unittest
from unittest.mock import patch

from event_core.model import Blocked
from event_core.mt5_adapter import MT5Broker


class _Tick:
    def __init__(self, time_msc, bid=1.15335, ask=1.15337):
        self.time_msc=time_msc; self.bid=bid; self.ask=ask


class _MT5:
    def __init__(self):
        self.time_msc=13_000_000
    def symbol_info_tick(self, symbol):
        return _Tick(self.time_msc)


class QuoteClockSkewTests(unittest.TestCase):
    def test_progressing_tick_is_fresh_even_when_mt5_clock_is_offset(self):
        mt5=_MT5(); broker=MT5Broker(mt5)
        with patch('event_core.mt5_adapter.time.time', side_effect=[1000.0,1000.2,1011.5]), \
             patch('event_core.mt5_adapter.time.monotonic', side_effect=[10.0,10.2,21.5]):
            first=broker.quote('EURUSD')
            with self.assertRaises(Blocked):
                first.validate(1000.0)

            mt5.time_msc += 200
            second=broker.quote('EURUSD')
            second.validate(1000.2)

            stale=broker.quote('EURUSD')
            with self.assertRaises(Blocked):
                stale.validate(1011.5)


if __name__ == '__main__':
    unittest.main()
