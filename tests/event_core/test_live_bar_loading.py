import time
import unittest

from event_core.mt5_adapter import MT5Broker


class FakeMT5Rates:
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15

    def __init__(self):
        self.calls=[]

    def last_error(self):
        return (1, 'ok')

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.calls.append((symbol,timeframe,start_pos,count))
        span=300 if timeframe==self.TIMEFRAME_M5 else 900
        now=time.time()
        current=int(now//span*span)
        rows=[]
        # Return closed bars plus the currently forming bar, exactly the live-terminal
        # shape that previously made EC1 discard the complete history.
        for i in range(40,0,-1):
            t=current-i*span
            rows.append(dict(time=t,open=1.1000,high=1.1004,low=1.0998,close=1.1002,tick_volume=10))
        rows.append(dict(time=current,open=1.1002,high=1.1005,low=1.1001,close=1.1003,tick_volume=3))
        return rows


class LiveBarLoadingTests(unittest.TestCase):
    def test_adapter_keeps_closed_history_and_discards_current_open_bar(self):
        mt5=FakeMT5Rates();broker=MT5Broker(mt5)
        bars=broker.bars('EURUSD','M5')
        self.assertGreaterEqual(len(bars),32)
        self.assertEqual(mt5.calls[0][2],0)
        self.assertTrue(all(a.time<b.time for a,b in zip(bars,bars[1:])))
        self.assertLessEqual(bars[-1].time+300,time.time()+1)
        self.assertGreater(time.time()+1,bars[-1].time+300)


if __name__=='__main__':
    unittest.main()
