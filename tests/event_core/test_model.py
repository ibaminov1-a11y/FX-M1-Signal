import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'mt5_bridge'))
from event_core.model import *
from event_core.strategy import Strategy
from fakes import wave


class ModelTests(unittest.TestCase):
    def test_bad_quote(self):
        for q in [Quote(0,1,2),Quote(1000,2,1),Quote(1000,float('nan'),2),Quote(1000,1,2)]:
            with self.assertRaises(Blocked):q.validate(200)
    def test_future_quote(self):
        with self.assertRaises(Blocked):Quote(999000,1,1).validate(10)
    def test_bad_bar(self):
        with self.assertRaises(Blocked):Bar(1,1,2,1.5,2)
    def test_pivot_cannot_know_future(self):
        bars=wave()
        for n in range(5,len(bars)):
            seen=pivots(bars[:n]);later=pivots(bars)
            for p in seen:
                self.assertLessEqual(p['known_at'],bars[n-1].time)
                self.assertIn(p,later)
    def test_modes_independent(self):
        self.assertEqual(Config(mode='SCALP',timeframe='M5').validate().timeframe,'M5')
        self.assertEqual(Config(mode='NORMAL',timeframe='M5').validate().mode,'NORMAL')
        self.assertNotEqual(PROFILES['SCALP'],PROFILES['NORMAL'])
    def test_no_artificial_balance(self):
        a={'balance':99868.35,'equity':99868.35};cfg=Config(test_capital=100)
        self.assertEqual(cfg.base(a),100);self.assertEqual(a['balance'],99868.35)
    def test_config_nan(self):
        with self.assertRaises(Blocked):Config(risk_pct=float('nan')).validate()
    def test_no_current_bar_in_strategy(self):
        bars=wave(1800000000);cfg=Config();s=Strategy(cfg)
        with self.assertRaises(Blocked):s.update(bars,wave(1800000000,tf=900),Quote(1799999800000,1.1,1.10001),1799999800)
    def test_no_score_override_and_no_entry_without_setup(self):
        bars=[Bar(1800000000-(96-i)*300,1.1,1.1001,1.0999,1.1) for i in range(96)]
        d=Strategy(Config()).update(bars,bars,Quote(1800000000000,1.1,1.10001),1800000000)
        self.assertEqual(d.signal,'WAIT')
    def test_cross_requires_prior_observation(self):
        now=1800000000.;bars=wave(int(now));s=Strategy(Config())
        s.setup=Setup('test',1,'IMPULSE_PULLBACK','TRIGGER',int(now-600),int(now+300),1.09,1.1,1.102,
                      pullback=1.099,trigger=1.101,trigger_bar=int(now-300),last_bar=bars[-1].time,armed_msc=int(now*1000))
        d=s.update(bars,bars,Quote(int(now*1000),1.1011,1.10111),now)
        self.assertEqual(d.signal,'WAIT')
        d=s.update(bars,bars,Quote(int((now+.5)*1000),1.1009,1.10091),now+.5)
        self.assertEqual(d.signal,'WAIT')
        d=s.update(bars,bars,Quote(int((now+1)*1000),1.10101,1.10102),now+1)
        self.assertEqual(d.signal,'BUY')
        s.consume(d.event_id)
        d=s.update(bars,bars,Quote(int((now+2)*1000),1.10102,1.10103),now+2)
        self.assertNotEqual(d.signal,'BUY')
    def test_unknown_mode_rejected(self):
        with self.assertRaises(Blocked):Config(mode='MARTINGALE').validate()

if __name__=='__main__':unittest.main()
