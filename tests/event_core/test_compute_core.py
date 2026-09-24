import unittest

from event_core.compute_core import ComputeCore
from event_core.model import Bar, Config, Quote, atr
from fakes import wave

NOW=1800000000.0


def series(count,tf,step,flat=False):
    end=int(NOW)//tf*tf
    out=[]
    for i in range(count):
        wobble=((i%4)-1.5)*.000004 if not flat else ((i%4)-1.5)*.000006
        center=1.1000+(0 if flat else i*step)+wobble
        o=center-(step*.35 if not flat else .000003)
        c=center+(step*.35 if not flat else -.000003)
        hi=max(o,c)+.00004;lo=min(o,c)-.00004
        out.append(Bar(end-(count-i)*tf,o,hi,lo,c,10+(i%3)))
    return out


def market(side=1, flat=False):
    bars=series(96,300,.000025*side,flat)
    m1=series(120,60,.000006*side,flat)
    m15=series(72,900,.000035*side,flat)
    h1=series(72,3600,.00006*side,flat)
    a=atr(bars)
    last=bars[-1]
    if flat:
        live=Bar(int(NOW)//300*300,last.close,last.close+.08*a,last.close-.08*a,last.close,8)
    elif side==1:
        live=Bar(int(NOW)//300*300,last.close-.05*a,last.close+.28*a,last.close-.08*a,last.close+.22*a,24)
    else:
        live=Bar(int(NOW)//300*300,last.close+.05*a,last.close+.08*a,last.close-.28*a,last.close-.22*a,24)
    return bars,m1,m15,h1,live,a


class ComputeCoreTests(unittest.TestCase):
    def core(self):
        return ComputeCore(Config(timeframe='M5',mode='NORMAL',engine_mode='COMPUTE_V1',
                                  fee_per_lot=0,approved=True,cooldown_sec=0))

    def test_strong_uptrend_has_buy_bias_and_projection(self):
        bars,m1,m15,h1,live,a=market(1)
        q=Quote(int(NOW*1000),live.close,live.close+.00001)
        d=self.core().evaluate(bars,m1,m15,h1,live,q,NOW)
        f=d.forecast
        self.assertGreater(f['up_probability'],f['down_probability'],f)
        self.assertEqual(f['side'],1,f)
        self.assertEqual(len(f['projection']),3)
        self.assertEqual([x['minutes'] for x in f['projection']],[5,10,15])

    def test_strong_downtrend_has_sell_bias(self):
        bars,m1,m15,h1,live,a=market(-1)
        q=Quote(int(NOW*1000),live.close,live.close+.00001)
        d=self.core().evaluate(bars,m1,m15,h1,live,q,NOW)
        self.assertEqual(d.forecast['side'],-1,d.forecast)
        self.assertGreater(d.forecast['down_probability'],d.forecast['up_probability'])

    def test_flat_market_waits_without_fake_direction(self):
        bars,m1,m15,h1,live,a=market(flat=True)
        q=Quote(int(NOW*1000),live.close,live.close+.00001)
        d=self.core().evaluate(bars,m1,m15,h1,live,q,NOW)
        self.assertEqual(d.signal,'WAIT')
        self.assertEqual(d.forecast['side'],0,d.forecast)
        self.assertIn('нет вычислительного преимущества',d.reason.lower())

    def test_live_microbreak_can_enter_before_m1_close_beyond_trigger(self):
        bars,m1,m15,h1,live,a=market(1)
        core=self.core()
        prior=m1[-5:-1]
        trigger=max(x.high for x in prior)+max(a*.02,.000012)
        # Last closed M1 is improving but has not closed beyond the trigger.
        old=m1[-1]
        m1[-1]=Bar(old.time,trigger-.07*a,trigger-.01*a,trigger-.10*a,trigger-.02*a,30)
        live=Bar(live.time,trigger-.10*a,trigger+.10*a,trigger-.12*a,trigger+.06*a,35)
        safe=Quote(int((NOW-1)*1000),trigger-.03*a,trigger-.03*a+.00001)
        first=core.evaluate(bars,m1,m15,h1,live,safe,NOW-1)
        self.assertEqual(first.signal,'WAIT')
        cross=Quote(int(NOW*1000),trigger+.03*a,trigger+.03*a+.00001)
        d=core.evaluate(bars,m1,m15,h1,live,cross,NOW)
        self.assertEqual((d.signal,d.phase,d.path),('BUY','ENTRY_READY','COMPUTE'),d)
        self.assertEqual(d.entry_class,'PROBE')
        self.assertGreater(d.stop,0)
        self.assertAlmostEqual(d.trigger,trigger,places=6)

    def test_first_observation_far_beyond_level_never_chases(self):
        bars,m1,m15,h1,live,a=market(1)
        core=self.core()
        trigger=max(x.high for x in m1[-5:-1])+max(a*.02,.000012)
        far=Quote(int(NOW*1000),trigger+.60*a,trigger+.60*a+.00001)
        d=core.evaluate(bars,m1,m15,h1,live,far,NOW)
        self.assertEqual(d.signal,'WAIT')
        self.assertTrue(d.forecast.get('late_entry') or 'далеко' in d.reason.lower() or 'позд' in d.reason.lower(),(d.reason,d.forecast))

    def test_exhausted_vertical_move_is_not_bought_at_top(self):
        bars,m1,m15,h1,live,a=market(1)
        # Force a stretched last leg and loss of acceleration near the high.
        base=bars[-8].close
        stretched=list(bars[:-7])
        for i in range(7):
            o=base+i*.22*a;c=o+.18*a;t=bars[-7+i].time
            stretched.append(Bar(t,o,c+.03*a,o-.02*a,c,20+i))
        top=stretched[-1].high
        live=Bar(int(NOW)//300*300,top-.06*a,top+.03*a,top-.16*a,top-.12*a,8)
        q=Quote(int(NOW*1000),live.close,live.close+.00001)
        d=self.core().evaluate(stretched,m1,m15,h1,live,q,NOW)
        self.assertEqual(d.signal,'WAIT')
        self.assertTrue(d.forecast['exhaustion'] or d.forecast['late_entry'],d.forecast)


if __name__=='__main__':
    unittest.main()
