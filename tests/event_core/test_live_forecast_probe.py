import unittest

from event_core.model import Bar, Config, Quote, Decision, atr
from event_core.strategy import Strategy
from event_core.risk import plan_order
from fakes import FakeBroker, wave

NOW=1800000000.0


def bearish_market():
    bars=wave(int(NOW),count=96,tf=300,trend=-.000025)
    m1=wave(int(NOW),count=96,tf=60,trend=-.000006)
    m15=wave(int(NOW),count=64,tf=900,trend=-.000035)
    h1=wave(int(NOW),count=64,tf=3600,trend=-.00006)
    a=atr(bars)
    last=bars[-1]
    live=Bar(int(NOW)//300*300,last.close+.08*a,last.close+.10*a,last.close-.28*a,last.close-.24*a,8)
    prev=m1[-2]
    low=min(x.low for x in m1[-5:-1])
    close=low-.08*a
    m1[-1]=Bar(m1[-1].time,prev.close,prev.close+.02*a,close-.03*a,close,20)
    q=Quote(int(NOW*1000),close-.01*a,close-.01*a+.00001)
    return bars,m1,m15,h1,live,q,a


class LiveForecastProbeTests(unittest.TestCase):
    def strategy(self):
        return Strategy(Config(timeframe='M5',mode='NORMAL',risk_pct=.25,fee_per_lot=0,
                               lot_cap=.10,probe_lot_cap=.01,approved=True,cooldown_sec=0))

    def test_forecast_detects_bearish_pressure_before_confirmed_entry(self):
        bars,m1,m15,h1,live,q,a=bearish_market()
        f=self.strategy().forecast(bars,m1,m15,h1,live,q,NOW)
        self.assertEqual(f['side'],-1,f)
        self.assertGreater(f['down_probability'],f['up_probability'])
        self.assertGreaterEqual(f['confidence'],.60)
        self.assertIn('momentum',f['components'])
        self.assertIn('structure',f['components'])

    def test_probe_requires_forecast_plus_fresh_microbreak_and_is_marked_probe(self):
        bars,m1,m15,h1,live,q,a=bearish_market()
        s=self.strategy()
        f=s.forecast(bars,m1,m15,h1,live,q,NOW)
        f={**f,'side':-1,'confidence':.82,'stable_for_sec':4.0,'late_entry':False,'exhaustion':False}
        d=s.probe_decision(bars,m1,m15,h1,live,q,NOW,f)
        self.assertIsNotNone(d)
        self.assertEqual((d.signal,d.phase,d.path,d.entry_class),('SELL','PROBE_READY','FORECAST','PROBE'))
        self.assertLess(q.bid,d.trigger)
        self.assertGreater(d.stop,q.ask)

    def test_late_sell_at_local_low_is_blocked_instead_of_chased(self):
        bars,m1,m15,h1,live,q,a=bearish_market()
        base=bars[-7].close
        extended=list(bars[:-6])
        for i in range(6):
            o=base-i*.23*a
            c=o-.20*a
            t=bars[-6+i].time
            extended.append(Bar(t,o,o+.03*a,c-.04*a,c,20+i))
        low=extended[-1].low
        live=Bar(int(NOW)//300*300,extended[-1].close,extended[-1].close+.02*a,
                 low-.08*a,low-.06*a,8)
        q=Quote(int(NOW*1000),live.close,live.close+.00001)
        s=self.strategy()
        f=s.forecast(extended,m1,m15,h1,live,q,NOW)
        self.assertTrue(f['late_entry'] or f['exhaustion'],f)
        forced={**f,'side':-1,'confidence':.90,'stable_for_sec':8.0}
        self.assertIsNone(s.probe_decision(extended,m1,m15,h1,live,q,NOW,forced))

    def test_probe_plan_is_capped_to_point_zero_one_even_when_profile_allows_more(self):
        bars,m1,m15,h1,live,q,a=bearish_market()
        cfg=Config(timeframe='M5',mode='NORMAL',risk_pct=1,fee_per_lot=0,
                   lot_cap=.10,probe_lot_cap=.01,approved=True,cooldown_sec=0)
        broker=FakeBroker(lambda:NOW)
        broker.bid=q.bid;broker.ask=q.ask
        info=broker.symbol('EURUSD')
        d=Decision('SELL','PROBE_READY','forecast probe','probe-1',-1,
                   q.ask+.45*a,q.bid+.02*a,q.ask+.45*a,a,q.time_msc,
                   entry_class='PROBE')
        p=plan_order(broker,cfg,broker.account(),info,q,d,[],None,NOW)
        self.assertEqual(p.volume,.01)


if __name__=='__main__':
    unittest.main()
