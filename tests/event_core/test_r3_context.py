import unittest

from event_core.model import Bar, Config, Quote
from event_core.strategy import Strategy
from fakes import wave

NOW=1800000000.0


def flat_bars(tf, count=64):
    end=int(NOW)//tf*tf
    bars=[]
    for i in range(count):
        p=1.1000+i*.000001
        bars.append(Bar(end-(count-i)*tf,p,p+.00002,p-.00002,p,10))
    return bars


class R3ContextTests(unittest.TestCase):
    def strategy(self):
        return Strategy(Config(timeframe='M5',mode='NORMAL',fee_per_lot=0,approved=True))

    def test_strategy_accepts_independent_r3_market_inputs(self):
        s=self.strategy()
        m5=wave(int(NOW),count=96,tf=300,trend=.00003)
        m1=wave(int(NOW),count=96,tf=60,trend=.000006)
        m15=wave(int(NOW),count=64,tf=900,trend=.00004)
        h1=wave(int(NOW),count=64,tf=3600,trend=.00008)
        live=Bar(int(NOW)//300*300,1.1030,1.1032,1.1029,1.1031,3)
        q=Quote(int(NOW*1000),m5[-1].close,m5[-1].close+.00001)
        decision=s.update(m5,m15,q,NOW,m1=m1,m15=m15,h1=h1,live_bar=live)
        self.assertIsNotNone(decision)

    def test_neutral_higher_context_does_not_block_side(self):
        s=self.strategy()
        neutral_m15=flat_bars(900)
        neutral_h1=flat_bars(3600)
        self.assertTrue(s._context_allows(1,neutral_m15,neutral_h1))
        self.assertTrue(s._context_allows(-1,neutral_m15,neutral_h1))

    def test_confirmed_opposite_h1_or_m15_blocks_new_side(self):
        s=self.strategy()
        up_m15=wave(int(NOW),count=64,tf=900,trend=.00004)
        up_h1=wave(int(NOW),count=64,tf=3600,trend=.00008)
        down_m15=wave(int(NOW),count=64,tf=900,trend=-.00004)
        down_h1=wave(int(NOW),count=64,tf=3600,trend=-.00008)
        self.assertFalse(s._context_allows(1,up_m15,down_h1))
        self.assertFalse(s._context_allows(1,down_m15,up_h1))
        self.assertFalse(s._context_allows(-1,up_m15,down_h1))
        self.assertTrue(s._context_allows(1,up_m15,up_h1))


if __name__=='__main__':
    unittest.main()
