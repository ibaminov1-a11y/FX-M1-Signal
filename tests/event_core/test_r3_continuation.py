import unittest

from event_core.model import Bar, Config, PROFILES, Quote, Setup, atr, pivots, direction
from event_core.strategy import Strategy
from fakes import wave
from test_r3_impulse import impulse_fixture

NOW=1800000000.0
TF=300


def shallow_fixture(side=1, retrace_atr=.20, *, opposite_h1=False, no_pause=False):
    bars=wave(int(NOW),count=96,tf=TF,trend=.00003*side)
    a0=atr(bars)
    if not no_pause:
        recent=bars[-5:-1]
        extreme=max(x.high for x in recent) if side==1 else min(x.low for x in recent)
        old=bars[-1]
        if side==1:
            low=extreme-retrace_atr*a0
            high=extreme-.03*a0
            open_=extreme-.06*a0
            close=extreme-.14*a0
        else:
            high=extreme+retrace_atr*a0
            low=extreme+.03*a0
            open_=extreme+.06*a0
            close=extreme+.14*a0
        bars[-1]=Bar(old.time,open_,max(high,open_,close),min(low,open_,close),close,10)
    a=atr(bars)
    m1=wave(int(NOW),count=48,tf=60,trend=.000006*side)
    m15=wave(int(NOW),count=64,tf=900,trend=.00004*side)
    h1=wave(int(NOW),count=64,tf=3600,trend=(-.00008*side if opposite_h1 else .00008*side))
    live=Bar(int(NOW)//300*300,bars[-1].close,bars[-1].close+.02*a,bars[-1].close-.02*a,bars[-1].close,3)
    bid=bars[-1].close
    q=Quote(int(NOW*1000),bid,bid+.00001)
    return bars,m1,m15,h1,live,q,a


def update(s,bars,q,m1,m15,h1,live,now=NOW):
    return s.update(bars,m15,q,now,m1=m1,m15=m15,h1=h1,live_bar=live)


class R3ContinuationTests(unittest.TestCase):
    def strategy(self):
        return Strategy(Config(timeframe='M5',mode='NORMAL',fee_per_lot=0,approved=True))

    def test_shallow_buy_pause_arms_continuation_then_fresh_tick_enters(self):
        s=self.strategy();bars,m1,m15,h1,live,q,a=shallow_fixture(1,.20)
        d=update(s,bars,q,m1,m15,h1,live)
        self.assertEqual((d.signal,d.phase,d.path),('WAIT','TRIGGER','CONTINUATION'))
        self.assertIsNotNone(s.setup)
        trigger=s.setup.trigger
        q2=Quote(q.time_msc+1000,trigger+.01*a,trigger+.01*a+.00001)
        d2=update(s,bars,q2,m1,m15,h1,live,NOW+1)
        self.assertEqual((d2.signal,d2.phase,d2.path),('BUY','ENTRY_READY','CONTINUATION'))

    def test_shallow_sell_pause_is_mirrored(self):
        s=self.strategy();bars,m1,m15,h1,live,q,a=shallow_fixture(-1,.20)
        d=update(s,bars,q,m1,m15,h1,live)
        self.assertEqual((d.signal,d.phase,d.path),('WAIT','TRIGGER','CONTINUATION'))
        trigger=s.setup.trigger
        q2=Quote(q.time_msc+1000,trigger-.01*a,trigger-.01*a+.00001)
        d2=update(s,bars,q2,m1,m15,h1,live,NOW+1)
        self.assertEqual((d2.signal,d2.phase,d2.path),('SELL','ENTRY_READY','CONTINUATION'))

    def test_no_pause_does_not_create_continuation(self):
        s=self.strategy();args=shallow_fixture(1,.20,no_pause=True)
        d=update(s,args[0],args[5],args[1],args[2],args[3],args[4])
        self.assertNotEqual(d.path,'CONTINUATION')

    def test_pause_below_point_one_atr_does_not_create_continuation(self):
        s=self.strategy();args=shallow_fixture(1,.06)
        d=update(s,args[0],args[5],args[1],args[2],args[3],args[4])
        self.assertNotEqual(d.path,'CONTINUATION')

    def test_deep_pause_uses_classic_path_not_continuation(self):
        s=self.strategy();args=shallow_fixture(1,.45)
        d=update(s,args[0],args[5],args[1],args[2],args[3],args[4])
        self.assertNotEqual(d.path,'CONTINUATION')
        self.assertEqual(d.signal,'WAIT')

    def test_opposite_h1_blocks_continuation(self):
        s=self.strategy();args=shallow_fixture(1,.20,opposite_h1=True)
        d=update(s,args[0],args[5],args[1],args[2],args[3],args[4])
        self.assertNotEqual(d.path,'CONTINUATION')
        self.assertEqual(d.signal,'WAIT')

    def test_normal_setup_lifetime_is_three_m5_bars(self):
        self.assertEqual(PROFILES['NORMAL'].setup_bars,3)

    def test_same_direction_live_impulse_can_supersede_pending_pullback(self):
        bars,m1,m15,h1,live,q,a,level=impulse_fixture(1)
        s=self.strategy()
        pts=pivots(bars);highs=[p for p in pts if p['kind']=='H'];lows=[p for p in pts if p['kind']=='L']
        self.assertEqual(direction(pts),1)
        s.setup=Setup('old-pullback',1,'STRUCTURE_PULLBACK','PULLBACK',bars[-1].time-300,
                      int(NOW+1800),lows[-1]['price']-.05*a,highs[-1]['price'],bars[-1].high,
                      last_bar=bars[-1].time)
        d=update(s,bars,q,m1,m15,h1,live)
        self.assertEqual((d.signal,d.path),('BUY','IMPULSE'))
        self.assertNotEqual(d.event_id,'old-pullback')


if __name__=='__main__':
    unittest.main()
