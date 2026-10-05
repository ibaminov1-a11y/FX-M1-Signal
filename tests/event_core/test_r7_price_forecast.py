"""Causal forecast checks: no trading decisions or manufactured broker executions."""
import copy
import importlib
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from event_core.model import Bar, Quote, TF_SECONDS
from event_core.store import Store
from fakes import wave

T=1800000000

class PriceForecastTests(unittest.TestCase):
    def predictor(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('event_core.price_forecast'),
                             'Independent price forecast module is missing')
        return importlib.import_module('event_core.price_forecast').PriceForecaster()

    def data(self,tf='M5',trend=.000003):
        return wave(T,count=240,tf=TF_SECONDS[tf],trend=trend)

    def issue(self,p,bars=None,tf='M5',mode='NORMAL',scope='123@DEMO|EURUSD',now=T,price=1.106):
        return p.update(bars or self.data(tf),Quote(int(now*1000),price,price+.00001),now,
                        symbol='EURUSD',timeframe=tf,mode=mode,scope=scope)

    def test_forecast_has_real_time_horizons_without_an_entry_signal(self):
        f=self.issue(self.predictor())
        self.assertTrue(f['available'],f)
        self.assertEqual([p['minutes'] for p in f['projection']],[5,10,15,30,60])
        for p in f['projection']:
            self.assertEqual(p['time'],T+60*p['minutes'])
            self.assertLessEqual(p['low'],p['center']);self.assertLessEqual(p['center'],p['high'])
        self.assertFalse(f['calibrated']);self.assertNotIn('entry_ready',f)
        self.assertTrue(all(p['sample_count']>=8 for p in f['projection']))

    def test_history_used_for_analogs_ends_before_query_window(self):
        f=self.issue(self.predictor())
        self.assertTrue(f['available'])
        for p in f['projection']:
            self.assertLessEqual(p['latest_training_outcome'],f['query_window_start'])
            self.assertLessEqual(p['latest_training_outcome'],f['issued_at'])

    def test_first_forecast_does_not_repaint_in_same_minute(self):
        p=self.predictor();before=self.issue(p);frozen=copy.deepcopy(before)
        after=self.issue(p,now=T+1,price=1.1062)
        self.assertEqual(after,before)
        after['projection'][0]['center']=999
        self.assertEqual(self.issue(p,now=T+2),frozen)
        new=self.issue(p,now=T+60,price=1.1062)
        self.assertNotEqual(new['snapshot_id'],before['snapshot_id'])
        self.assertEqual(before,frozen)

    def test_brief_feed_failure_cannot_rewrite_an_already_issued_minute(self):
        p=self.predictor();before=self.issue(p)
        unavailable=p.update(self.data(),Quote((T+1)*1000,1.1062,1.10621,False),T+1,
            symbol='EURUSD',timeframe='M5',mode='NORMAL',scope='123@DEMO|EURUSD')
        self.assertFalse(unavailable['available'])
        self.assertEqual(unavailable['projection'],[])
        restored=self.issue(p,now=T+2,price=1.1062)
        self.assertEqual(restored,before,'Reconnect must not repaint a previously issued minute')

    def test_scopes_modes_and_timeframes_do_not_share_forecasts(self):
        p=self.predictor();a=self.issue(p);b=self.issue(p,scope='456@DEMO|EURUSD')
        c=self.issue(p,mode='SCALP');d=self.issue(p,tf='M15')
        self.assertEqual(len({x['snapshot_id'] for x in (a,b,c,d)}),4)
        self.assertEqual(d['timeframe'],'M15')
        self.assertEqual([x['minutes'] for x in d['projection']],[15,30,60])
        self.assertEqual(d['unavailable_horizons'],[5,10])

    def test_flat_history_has_neutral_forecast_not_invented_direction(self):
        bars=[Bar(T-(240-i)*300,1.1,1.1001,1.0999,1.1,10) for i in range(240)]
        f=self.issue(self.predictor(),bars=bars,price=1.1)
        self.assertTrue(f['available']);self.assertEqual(f['direction'],0)
        self.assertTrue(all(x['center']==1.1 for x in f['projection']))
        self.assertNotIn('up_probability',f)

    def test_too_little_history_or_stale_data_has_no_synthetic_path(self):
        p=self.predictor()
        f=self.issue(p,bars=self.data()[-20:]);self.assertFalse(f['available']);self.assertEqual(f['projection'],[])
        for now,rows in ((T+3000,self.data()),(T,self.data()+[Bar(T,1.1,1.2,1.,1.1)])):
            f=self.issue(p,now=now,bars=rows)
            self.assertFalse(f['available']);self.assertEqual(f['projection'],[])
            self.assertTrue(f['reason'])

    def test_recorded_snapshot_is_immutable_and_outcomes_wait_for_actual_quote(self):
        f=self.issue(self.predictor())
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'state.db')
            try:
                self.assertTrue(hasattr(s,'save_price_forecast'),'Immutable price archive is missing')
                s.save_price_forecast(f)
                modified=copy.deepcopy(f);modified['origin']=5
                with self.assertRaises(ValueError):s.save_price_forecast(modified)
                s.settle_price_forecasts(f['scope'],Quote((T+299)*1000,1.2,1.20001),T+299)
                self.assertEqual(s.price_forecast_report(f['scope'])['evaluated'],0)
                s.settle_price_forecasts(f['scope'],Quote((T+301)*1000,1.2,1.20001),T+301)
                report=s.price_forecast_report(f['scope'])
                self.assertEqual(report['evaluated'],1);self.assertEqual(report['pending'],4)
                s.settle_price_forecasts(f['scope'],Quote((T+605)*1000,1.2,1.20001),T+605)
                self.assertEqual(s.price_forecast_report(f['scope'])['evaluated'],2)
                s.settle_price_forecasts(f['scope'],Quote((T+1000)*1000,1.2,1.20001),T+1000)
                self.assertEqual(s.price_forecast_report(f['scope'])['missing'],1)
                self.assertEqual(s.price_forecasts(f['scope'])[0],f)
            finally:s.close()

if __name__=='__main__':unittest.main()
