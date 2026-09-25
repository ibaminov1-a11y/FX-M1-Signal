import unittest
from event_core.compute_core import ComputeCore
from event_core.model import Bar, Config, Quote
from test_compute_core import NOW, market


class ScenarioMapTests(unittest.TestCase):
    def core(self):
        return ComputeCore(Config(timeframe='M5', mode='NORMAL', engine_mode='COMPUTE_V1',
                                  fee_per_lot=0, approved=True, cooldown_sec=0))

    def data(self, side=1):
        bars,m1,m15,h1,live,a=market(side)
        pad=max(a*.02,.000012)
        trigger=(max(x.high for x in m1[-5:-1])+pad if side==1 else
                 min(x.low for x in m1[-5:-1])-pad)
        return bars,m1,m15,h1,live,a,trigger

    def test_map_exposes_the_same_trigger_and_invalidation_before_entry(self):
        bars,m1,m15,h1,live,a,t=self.data()
        q=Quote(int(NOW*1000),t-.03*a,t-.03*a+.00001)
        d=self.core().evaluate(bars,m1,m15,h1,live,q,NOW)
        primary=d.forecast['scenarios'][0]
        self.assertGreater(d.trigger,0)
        self.assertGreater(d.invalidation,0)
        self.assertAlmostEqual(primary.get('activation',0),d.trigger,places=9)
        self.assertAlmostEqual(primary.get('invalidation',0),d.invalidation,places=9)
        self.assertEqual(d.signal,'WAIT')

    def test_alternative_is_the_opposite_side_not_a_range_replacement(self):
        bars,m1,m15,h1,live,a,t=self.data()
        q=Quote(int(NOW*1000),live.close,live.close+.00001)
        f=self.core().evaluate(bars,m1,m15,h1,live,q,NOW).forecast
        self.assertEqual(f['scenarios'][1]['side'],-f['scenarios'][0]['side'])
        self.assertGreater(f['range_probability'],0)

    def test_path_points_identify_their_structural_origin(self):
        bars,m1,m15,h1,live,a,t=self.data()
        q=Quote(int(NOW*1000),live.close,live.close+.00001)
        f=self.core().evaluate(bars,m1,m15,h1,live,q,NOW).forecast
        for scenario in f['scenarios']:
            self.assertIn(scenario.get('target_source'),('CONFIRMED_STRUCTURE','MEASURED_RANGE_EXTENSION'))
            self.assertAlmostEqual(scenario['path'][0]['price'],q.bid,places=9)
            self.assertAlmostEqual(scenario['path'][-1]['price'],scenario['target'],places=9)
            self.assertTrue(all('anchor' in p for p in scenario['path']))

    def test_model_weights_are_not_claimed_to_be_calibrated_probabilities(self):
        bars,m1,m15,h1,live,a,t=self.data()
        q=Quote(int(NOW*1000),live.close,live.close+.00001)
        f=self.core().evaluate(bars,m1,m15,h1,live,q,NOW).forecast
        self.assertEqual(f.get('model_weight_kind'),'UNCALIBRATED_SCORE')
        self.assertEqual(f.get('path_time_kind'),'ILLUSTRATIVE_NOT_ETA')

    def test_unclear_market_has_levels_but_no_synthetic_future_paths(self):
        bars,m1,m15,h1,live,a=market(flat=True)
        q=Quote(int(NOW*1000),live.close,live.close+.00001)
        f=self.core().evaluate(bars,m1,m15,h1,live,q,NOW).forecast
        self.assertEqual(f['scenarios'],[])
        self.assertIn('entry_levels',f)
        self.assertGreater(f['entry_levels']['BUY']['trigger'],f['entry_levels']['SELL']['trigger'])

    def test_first_quote_just_beyond_trigger_only_arms_observer(self):
        bars,m1,m15,h1,live,a,t=self.data()
        q=Quote(int(NOW*1000),t+.03*a,t+.03*a+.00001)
        d=self.core().evaluate(bars,m1,m15,h1,live,q,NOW)
        self.assertEqual(d.signal,'WAIT',d)
        self.assertIn('наблю',d.reason.lower())

    def test_continuation_without_observed_crossing_is_not_a_new_entry(self):
        bars,m1,m15,h1,live,a,t=self.data()
        core=self.core()
        q=Quote(int((NOW-1)*1000),t+.02*a,t+.02*a+.00001)
        core.evaluate(bars,m1,m15,h1,live,q,NOW-1)
        q=Quote(int(NOW*1000),t+.03*a,t+.03*a+.00001)
        d=core.evaluate(bars,m1,m15,h1,live,q,NOW)
        self.assertEqual(d.signal,'WAIT',d)

    def test_changed_m1_frame_cannot_manufacture_a_price_crossing(self):
        bars,m1,m15,h1,live,a,t=self.data()
        core=self.core()
        q=Quote(int((NOW-1)*1000),t-.02*a,t-.02*a+.00001)
        core.evaluate(bars,m1,m15,h1,live,q,NOW-1)
        # Level moved down while price did not move: this is not a prospective crossing.
        shifted=[Bar(x.time+60,x.open-.08*a,x.high-.08*a,x.low-.08*a,x.close-.08*a,x.volume) for x in m1]
        q=Quote(int(NOW*1000),q.bid,q.ask)
        d=core.evaluate(bars,shifted,m15,h1,live,q,NOW)
        self.assertEqual(d.signal,'WAIT',d)

    def test_uncertainty_widens_but_is_not_a_statistical_confidence_interval(self):
        bars,m1,m15,h1,live,a,t=self.data()
        q=Quote(int(NOW*1000),t-.03*a,t-.03*a+.00001)
        f=self.core().evaluate(bars,m1,m15,h1,live,q,NOW).forecast
        self.assertEqual(f['uncertainty_kind'],'ATR_SCALE_NOT_CONFIDENCE_INTERVAL')
        for scenario in f['scenarios']:
            widths=[p.get('uncertainty',-1) for p in scenario['path']]
            self.assertEqual(widths[0],0)
            self.assertTrue(all(b>a for a,b in zip(widths,widths[1:])),widths)

    def test_scenarios_have_two_named_targets_and_retest_not_three_flat_dots(self):
        bars,m1,m15,h1,live,a,t=self.data()
        q=Quote(int(NOW*1000),t-.03*a,t-.03*a+.00001)
        f=self.core().evaluate(bars,m1,m15,h1,live,q,NOW).forecast
        for v in f['scenarios']:
            self.assertIn('target1',v)
            self.assertIn('target2',v)
            self.assertGreater((v['target2']-v['target1'])*v['side'],0)
            self.assertGreaterEqual(len(v['path']),5)
            self.assertTrue(any(p.get('label')=='HL?' or p.get('label')=='LH?' for p in v['path']))
