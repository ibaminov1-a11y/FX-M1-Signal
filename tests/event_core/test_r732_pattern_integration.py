"""Use actual Engine, HTTP views and immutable Store, with a fake MT5 boundary."""
import copy
import unittest
from unittest.mock import patch
import test_r56_multiframe as mtf
import test_r5_integration as v2
FRAMES=mtf.FRAMES

class PatternIntegrationTests(unittest.TestCase):
    setUp=mtf.MultiFrameTests.setUp
    warm=mtf.MultiFrameTests.warm
    view=mtf.MultiFrameTests.view

    def chart(self,state):
        self.assertIn('pattern_chart',state['forecast'],'PATTERN_VIEW_NOT_PUBLISHED')
        return state['forecast']['pattern_chart']

    def test_pattern_visible_when_entry_waits(self):
        self.warm();state=self.engine.snapshot();view=self.chart(state)
        self.assertEqual(state['decision']['signal'],'WAIT');self.assertTrue(view['patterns'])
        self.assertTrue(any(p['geometry_state']=='DETECTED' for p in view['patterns']))
        self.assertFalse(self.engine.auto);self.assertFalse(self.broker.sent)

    def test_reads_do_not_change_execution_or_read_mt5_again(self):
        self.warm();before=copy.deepcopy(self.store.load('engine'));calls=list(self.broker.calls)
        auto=self.engine.auto;sent=copy.deepcopy(self.broker.sent)
        for tf in FRAMES:
            response=self.view(tf);chart=self.chart(response)
            self.assertTrue(chart['patterns'],tf);self.assertEqual(chart['timeframe'],tf)
            self.assertEqual(chart['history_clock'],response['market_history_generation'])
            self.assertEqual(chart['scope'],response['market_scope'])
        self.assertEqual(self.broker.sent,sent);self.assertEqual(self.broker.calls,calls)
        self.assertEqual(self.engine.auto,auto);self.assertEqual(self.store.load('engine'),before)

    def test_observers_do_not_write_trade_archive(self):
        self.warm();scope=self.engine.market_scope();before=copy.deepcopy(self.store.scenario_snapshots(scope))
        self.assertTrue(before);self.chart(before[0])
        self.now[0]+=2;self.engine._refresh_observers(self.now[0],budget=9)
        for tf in FRAMES:self.view(tf)
        self.assertEqual(self.store.scenario_snapshots(scope),before)

    def test_published_catalogs_are_independent_copies(self):
        self.warm();first=self.engine.snapshot();view=self.chart(first);saved=copy.deepcopy(view)
        view['patterns'][0]['anchors'][0]['price']=999
        self.assertEqual(self.chart(self.engine.snapshot()),saved)
        other=self.view('M15');p=self.chart(other);p['patterns'].clear()
        self.assertTrue(self.chart(self.view('M15'))['patterns'])

    def test_stale_data_does_not_claim_live_catalog(self):
        self.warm();self.chart(self.engine.snapshot());self.now[0]+=30;self.broker.quote_age=30;self.engine.step()
        state=self.engine.snapshot();self.assertFalse(state['forecast'].get('available',False))
        self.assertFalse(state['entry_gate']['allowed']);self.assertFalse(self.broker.sent)

    def test_branches_have_separate_read_only_outcomes(self):
        self.warm();chart=self.chart(self.engine.snapshot())
        self.assertIn('branches',chart);self.assertTrue(chart['branches'])
        ids={p['view_id']:set(p['scenario_ids']) for p in chart['patterns']}
        for branch in chart['branches']:
            self.assertIn(branch['scenario_id'],ids[branch['view_id']])
            self.assertTrue(branch['read_only']);self.assertIn(branch['display_outcome']['status'],('PENDING','TARGET_REACHED','INVALIDATED','EXPIRED','UNKNOWN'))
        direct=next(b for b in chart['branches'] if b['type']=='DIRECT_BREAKOUT')
        retest=next(b for b in chart['branches'] if b['type']=='BREAKOUT_RETEST' and b['view_id']==direct['view_id'] and b['side']==direct['side'])
        self.assertNotEqual([x['anchor'] for x in direct['path']],[x['anchor'] for x in retest['path']])

    def test_repeated_quotes_do_not_write_every_tick(self):
        self.warm();self.chart(self.engine.snapshot());scope=self.engine.market_scope()
        before=len(self.store.scenario_snapshots(scope))
        for _ in range(8):self.now[0]+=.25;self.engine.step()
        self.assertEqual(len(self.store.scenario_snapshots(scope)),before)

    def test_first_chart_snapshot_remains_immutable(self):
        self.warm();scope=self.engine.market_scope();before=copy.deepcopy(self.store.scenario_snapshots(scope))
        self.chart(before[0]);self.now[0]+=1;self.broker.bid+=.000003;self.broker.ask+=.000003;self.engine.step()
        for snapshot in before:
            self.assertEqual(self.store.scenario_snapshots(scope,snapshot_id=snapshot['snapshot_id'])[0],snapshot)

    def test_display_disabled_does_not_change_actual_entry(self):
        def exercise(disabled):
            harness=v2.V2IntegrationTests('test_actual_engine_opens_exact_lot_and_records_scenario_identity')
            try:
                harness.setUp()
                if disabled:
                    with patch('event_core.scenarios.pattern_view.PatternCatalog.update',return_value={'version':1,'patterns':[],'branches':[],'available':False}):state=harness.entry()
                else:
                    state=harness.entry();self.assertIn('pattern_chart',state['forecast'])
                    self.assertTrue(state['forecast']['pattern_chart']['patterns'])
                self.assertEqual(len(harness.b.sent),1,'No real Engine dispatch was exercised')
                return (copy.deepcopy(harness.b.sent),state['decision']['event_id'],copy.deepcopy(state['risk']),harness.e.config,
                        {k:state['campaign'].get(k) for k in ('scenario_id','last_entry','invalidation','requested_volume')})
            finally:harness.tearDown()
        self.assertEqual(exercise(False),exercise(True))

if __name__=='__main__':unittest.main()
