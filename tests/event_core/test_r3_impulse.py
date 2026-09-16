import inspect
import unittest

from event_core.model import Bar, Config, Quote, atr, pivots
from event_core.strategy import Strategy
from fakes import wave

NOW=1800000000.0


def impulse_fixture(side=1, *, small=False, m1_confirm=True, opposite_h1=False, chase=False):
    trend=.00003*side
    bars=wave(int(NOW),count=96,tf=300,trend=trend)
    a=atr(bars)
    pts=pivots(bars)
    level=([p for p in pts if p['kind']=='H'][-1]['price'] if side==1
           else [p for p in pts if p['kind']=='L'][-1]['price'])
    body=(.40 if small else .75)*a
    span=(.80 if small else 1.05)*a
    if side==1:
        open_=level-.10*a
        close=open_+body
        low=open_-.15*a
        high=low+span
        if chase: close=level+1.20*a; high=max(high,close+.05*a)
        m1_close=level+(.20*a if m1_confirm else -.05*a)
        m1_open=m1_close-.12*a
        bid=close
    else:
        open_=level+.10*a
        close=open_-body
        high=open_+.15*a
        low=high-span
        if chase: close=level-1.20*a; low=min(low,close-.05*a)
        m1_close=level-(.20*a if m1_confirm else -.05*a)
        m1_open=m1_close+.12*a
        bid=close
    live=Bar(int(NOW)//300*300,open_,max(high,open_,close),min(low,open_,close),close,30)
    m1=wave(int(NOW),count=40,tf=60,trend=.000006*side)
    x=m1[-1]
    m1[-1]=Bar(x.time,m1_open,max(m1_open,m1_close)+.03*a,min(m1_open,m1_close)-.03*a,m1_close,15)
    m15=wave(int(NOW),count=64,tf=900,trend=.00004*side)
    h1=wave(int(NOW),count=64,tf=3600,trend=(-.00008*side if opposite_h1 else .00008*side))
    q=Quote(int(NOW*1000),bid,bid+.00001)
    return bars,m1,m15,h1,live,q,a,level


def r3_update(strategy,bars,q,*,m1,m15,h1,live):
    sig=inspect.signature(strategy.update)
    for name in ('m1','m15','h1','live_bar'):
        if name not in sig.parameters:
            raise AssertionError('Strategy.update missing R3 input '+name)
    return strategy.update(bars,m15,q,NOW,m1=m1,m15=m15,h1=h1,live_bar=live)


class R3ImpulseTests(unittest.TestCase):
    def strategy(self):
        return Strategy(Config(timeframe='M5',mode='NORMAL',fee_per_lot=0,approved=True))

    def test_large_live_m5_buy_can_be_entry_ready_before_close(self):
        bars,m1,m15,h1,live,q,a,level=impulse_fixture(1)
        d=r3_update(self.strategy(),bars,q,m1=m1,m15=m15,h1=h1,live=live)
        self.assertEqual((d.signal,d.phase,d.path),('BUY','ENTRY_READY','IMPULSE'))
        self.assertGreater(d.trigger,level)
        self.assertLess(d.stop,q.bid)
        self.assertTrue(d.event_id)

    def test_large_live_m5_sell_is_mirrored(self):
        bars,m1,m15,h1,live,q,a,level=impulse_fixture(-1)
        d=r3_update(self.strategy(),bars,q,m1=m1,m15=m15,h1=h1,live=live)
        self.assertEqual((d.signal,d.phase,d.path),('SELL','ENTRY_READY','IMPULSE'))
        self.assertLess(d.trigger,level)
        self.assertGreater(d.stop,q.bid)

    def test_small_live_m5_does_not_fire_impulse(self):
        bars,m1,m15,h1,live,q,*_=impulse_fixture(1,small=True)
        d=r3_update(self.strategy(),bars,q,m1=m1,m15=m15,h1=h1,live=live)
        self.assertNotEqual(d.path,'IMPULSE')
        self.assertEqual(d.signal,'WAIT')

    def test_large_m5_without_closed_m1_confirmation_does_not_enter(self):
        bars,m1,m15,h1,live,q,*_=impulse_fixture(1,m1_confirm=False)
        d=r3_update(self.strategy(),bars,q,m1=m1,m15=m15,h1=h1,live=live)
        self.assertNotEqual(d.path,'IMPULSE')
        self.assertEqual(d.signal,'WAIT')

    def test_confirmed_opposite_h1_blocks_impulse(self):
        bars,m1,m15,h1,live,q,*_=impulse_fixture(1,opposite_h1=True)
        d=r3_update(self.strategy(),bars,q,m1=m1,m15=m15,h1=h1,live=live)
        self.assertNotEqual(d.path,'IMPULSE')
        self.assertEqual(d.signal,'WAIT')

    def test_impulse_does_not_chase_price_far_beyond_break(self):
        bars,m1,m15,h1,live,q,*_=impulse_fixture(1,chase=True)
        d=r3_update(self.strategy(),bars,q,m1=m1,m15=m15,h1=h1,live=live)
        self.assertNotEqual(d.path,'IMPULSE')
        self.assertEqual(d.signal,'WAIT')


if __name__=='__main__':
    unittest.main()
