import unittest

from event_core.model import Bar, Config, Quote, atr, pivots, direction
from event_core.strategy import Strategy
from fakes import wave

NOW=1800000000.0


def impulse_fixture(side=1, *, body_atr=.75, range_atr=1.05, m1_confirm=True,
                    opposite_h1=False, opposite_m15=False, tick_inside=False,
                    chase_atr=None):
    bars=wave(int(NOW),count=96,tf=300,trend=.00003*side)
    a=atr(bars)
    pts=pivots(bars)
    highs=[p for p in pts if p['kind']=='H']
    lows=[p for p in pts if p['kind']=='L']
    assert highs and lows and direction(pts)==side
    level=highs[-1]['price'] if side==1 else lows[-1]['price']

    if side==1:
        open_=level-.10*a
        close=open_+body_atr*a
        low=open_-.15*a
        high=low+range_atr*a
        high=max(high,close+.01*a)
    else:
        open_=level+.10*a
        close=open_-body_atr*a
        high=open_+.15*a
        low=high-range_atr*a
        low=min(low,close-.01*a)
    live=Bar(int(NOW)//300*300,open_,high,low,close,3)

    m1=wave(int(NOW),count=96,tf=60,trend=.000006*side)
    old=m1[-1]
    if m1_confirm:
        if side==1:
            m1_close=level+.20*a;m1_open=level+.10*a
        else:
            m1_close=level-.20*a;m1_open=level-.10*a
    else:
        if side==1:
            m1_close=level-.02*a;m1_open=level-.05*a
        else:
            m1_close=level+.02*a;m1_open=level+.05*a
    m1[-1]=Bar(old.time,m1_open,max(m1_open,m1_close)+.03*a,
               min(m1_open,m1_close)-.03*a,m1_close,10)

    m15=wave(int(NOW),count=64,tf=900,trend=(-.00004*side if opposite_m15 else .00004*side))
    h1=wave(int(NOW),count=64,tf=3600,trend=(-.00008*side if opposite_h1 else .00008*side))

    if tick_inside:
        bid=level-.02*a if side==1 else level+.02*a
    elif chase_atr is not None:
        bid=level+side*chase_atr*a
    else:
        bid=close
    q=Quote(int(NOW*1000),bid,bid+.00001)
    return bars,m1,m15,h1,live,q,a,level


def decide(side=1, **kwargs):
    args=impulse_fixture(side,**kwargs)
    s=Strategy(Config(timeframe='M5',mode='NORMAL',fee_per_lot=0,approved=True))
    d=s.update(args[0],args[2],args[5],NOW,m1=args[1],m15=args[2],h1=args[3],live_bar=args[4])
    return s,d,args


class R3ImpulseTests(unittest.TestCase):
    def test_large_live_m5_buy_can_be_entry_ready_before_close(self):
        s,d,args=decide(1)
        self.assertEqual((d.signal,d.phase,d.path),('BUY','ENTRY_READY','IMPULSE'))
        self.assertGreater(d.trigger,0)
        self.assertGreater(d.stop,0)
        self.assertTrue(d.structure)

    def test_large_live_m5_sell_is_mirrored(self):
        s,d,args=decide(-1)
        self.assertEqual((d.signal,d.phase,d.path),('SELL','ENTRY_READY','IMPULSE'))
        self.assertGreater(d.trigger,0)
        self.assertGreater(d.stop,0)

    def test_small_live_m5_does_not_fire_impulse(self):
        _,d,_=decide(1,body_atr=.40,range_atr=1.05)
        self.assertNotEqual(d.path,'IMPULSE')

    def test_short_range_does_not_fire_impulse(self):
        _,d,_=decide(1,body_atr=.75,range_atr=.85)
        self.assertNotEqual(d.path,'IMPULSE')

    def test_wicky_candle_does_not_fire_impulse(self):
        _,d,_=decide(1,body_atr=.55,range_atr=1.40)
        self.assertNotEqual(d.path,'IMPULSE')

    def test_large_m5_without_closed_m1_confirmation_does_not_enter(self):
        _,d,_=decide(1,m1_confirm=False)
        self.assertNotEqual(d.path,'IMPULSE')

    def test_live_tick_back_inside_break_does_not_enter(self):
        _,d,_=decide(1,tick_inside=True)
        self.assertNotEqual(d.path,'IMPULSE')

    def test_confirmed_opposite_h1_blocks_impulse(self):
        _,d,_=decide(1,opposite_h1=True)
        self.assertNotEqual(d.path,'IMPULSE')

    def test_confirmed_opposite_m15_blocks_impulse(self):
        _,d,_=decide(1,opposite_m15=True)
        self.assertNotEqual(d.path,'IMPULSE')

    def test_impulse_does_not_chase_price_far_beyond_break(self):
        _,d,_=decide(1,chase_atr=.90)
        self.assertNotEqual(d.path,'IMPULSE')

    def test_consumed_impulse_event_cannot_be_reused(self):
        s,d,args=decide(1)
        self.assertEqual(d.path,'IMPULSE')
        s.consume(d.event_id)
        again=s.update(args[0],args[2],args[5],NOW,m1=args[1],m15=args[2],h1=args[3],live_bar=args[4])
        self.assertNotEqual(again.path,'IMPULSE')


if __name__=='__main__':
    unittest.main()
