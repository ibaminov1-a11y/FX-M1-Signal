import unittest

from event_core.model import Bar, Config, PROFILES, Quote, atr
from event_core.strategy import Strategy
from fakes import wave

NOW=1800000000.0


def shallow_fixture(side=1,retrace_atr=.20,*,opposite_h1=False,opposite_m15=False,no_pause=False):
    bars=wave(int(NOW),count=96,tf=300,trend=.00003*side)
    a0=atr(bars)
    if not no_pause:
        recent=bars[-5:-1]
        extreme=max(x.high for x in recent) if side==1 else min(x.low for x in recent)
        old=bars[-1]
        if side==1:
            low=extreme-retrace_atr*a0
            high=extreme-.02*a0
            open_=extreme-.04*a0
            close=extreme-min(retrace_atr*.60,.20)*a0
        else:
            high=extreme+retrace_atr*a0
            low=extreme+.02*a0
            open_=extreme+.04*a0
            close=extreme+min(retrace_atr*.60,.20)*a0
        bars[-1]=Bar(old.time,open_,max(high,open_,close),min(low,open_,close),close,10)
    a=atr(bars)
    m1=wave(int(NOW),count=96,tf=60,trend=.000006*side)
    m15=wave(int(NOW),count=64,tf=900,trend=(-.00004*side if opposite_m15 else .00004*side))
    h1=wave(int(NOW),count=64,tf=3600,trend=(-.00008*side if opposite_h1 else .00008*side))
    bid=bars[-1].close
    q=Quote(int(NOW*1000),bid,bid+.00001)
    live=Bar(int(NOW)//300*300,bid,bid+.03*a,bid-.03*a,bid,2)
    return bars,m1,m15,h1,live,q,a


def update(s,args,now=NOW,q=None,m1=None):
    return s.update(args[0],args[2],q or args[5],now,
                    m1=m1 or args[1],m15=args[2],h1=args[3],live_bar=args[4])


def confirmed_m1(m1,trigger,side,a):
    rows=list(m1)
    t=rows[-1].time+60
    if side==1:
        open_=trigger-.03*a;close=trigger+.06*a
    else:
        open_=trigger+.03*a;close=trigger-.06*a
    rows.append(Bar(t,open_,max(open_,close)+.02*a,min(open_,close)-.02*a,close,10))
    return rows


class R3ContinuationTests(unittest.TestCase):
    def strategy(self):
        return Strategy(Config(timeframe='M5',mode='NORMAL',fee_per_lot=0,approved=True))

    def test_shallow_buy_pause_arms_continuation_then_new_m1_confirms_entry(self):
        s=self.strategy();args=shallow_fixture(1,.20)
        first=update(s,args)
        self.assertEqual((first.signal,first.phase,first.path),('WAIT','TRIGGER','CONTINUATION'))
        trigger=s.setup.trigger
        m1=confirmed_m1(args[1],trigger,1,args[6])
        q=Quote(int((NOW+61)*1000),trigger+.07*args[6],trigger+.07*args[6]+.00001)
        second=update(s,args,NOW+61,q=q,m1=m1)
        self.assertEqual((second.signal,second.phase,second.path),('BUY','ENTRY_READY','CONTINUATION'))

    def test_shallow_sell_pause_is_mirrored(self):
        s=self.strategy();args=shallow_fixture(-1,.20)
        first=update(s,args)
        self.assertEqual((first.signal,first.phase,first.path),('WAIT','TRIGGER','CONTINUATION'))
        trigger=s.setup.trigger
        m1=confirmed_m1(args[1],trigger,-1,args[6])
        q=Quote(int((NOW+61)*1000),trigger-.07*args[6],trigger-.07*args[6]+.00001)
        second=update(s,args,NOW+61,q=q,m1=m1)
        self.assertEqual((second.signal,second.phase,second.path),('SELL','ENTRY_READY','CONTINUATION'))

    def test_retrace_below_point_one_atr_is_not_continuation(self):
        s=self.strategy();args=shallow_fixture(1,.06)
        d=update(s,args)
        self.assertNotEqual(d.path,'CONTINUATION')

    def test_deep_retrace_remains_classic_path(self):
        s=self.strategy();args=shallow_fixture(1,.45)
        d=update(s,args)
        self.assertNotEqual(d.path,'CONTINUATION')

    def test_no_pause_is_not_continuation(self):
        s=self.strategy();args=shallow_fixture(1,.20,no_pause=True)
        d=update(s,args)
        self.assertNotEqual(d.path,'CONTINUATION')

    def test_opposite_h1_or_m15_blocks_continuation(self):
        for kwargs in ({'opposite_h1':True},{'opposite_m15':True}):
            with self.subTest(**kwargs):
                s=self.strategy();args=shallow_fixture(1,.20,**kwargs)
                d=update(s,args)
                self.assertNotEqual(d.path,'CONTINUATION')

    def test_continuation_requires_a_new_m1_close_after_arming(self):
        s=self.strategy();args=shallow_fixture(1,.20)
        first=update(s,args);trigger=s.setup.trigger
        q=Quote(int((NOW+1)*1000),trigger+.07*args[6],trigger+.07*args[6]+.00001)
        second=update(s,args,NOW+1,q=q,m1=args[1])
        self.assertEqual(second.signal,'WAIT')
        self.assertEqual(second.path,'CONTINUATION')

    def test_normal_setup_lifetime_is_three_m5_bars(self):
        self.assertEqual(PROFILES['NORMAL'].setup_bars,3)


if __name__=='__main__':
    unittest.main()
