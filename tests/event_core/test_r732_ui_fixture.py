import importlib.util,unittest,sys
from export_r732_chart_fixtures import state_for
class ChartFixtureTests(unittest.TestCase):
 def test_numeric_catalog_can_be_observed_at_live_clock(self):
  import inspect
  self.assertIn('observed_now',inspect.signature(state_for).parameters,'LIVE_CATALOG_CLOCK_MISSING')
  now=1800000437.
  s=state_for('HEAD_SHOULDERS','TOP',observed_now=now)
  self.assertEqual(s['forecast']['data_asof'],now)
  self.assertTrue(s['forecast']['pattern_chart']['patterns'])
  self.assertTrue(all(a['time']<=now for p in s['forecast']['pattern_chart']['patterns'] for a in p['anchors']))
 def test_normal_http_path_exposes_real_catalog_without_trade(self):
  self.assertIsNotNone(importlib.util.find_spec('r732_ui_fixture'),'HTTP_PATTERN_FIXTURE_MISSING')
  import ui_fixture
  c=ui_fixture.app.test_client();h={'Authorization':'Bearer ci-fixture-token-not-for-real-trading','X-FXM1-Client':'R51'}
  c.post('/test/reset',json={},headers=h)
  r=c.post('/test/r732-pattern',json={'index':17},headers=h);self.assertEqual(r.status_code,200)
  r=c.get('/ec/state',headers=h);s=r.get_json();self.assertIn('pattern_chart',s['forecast'])
  self.assertFalse(s['auto']);self.assertTrue(s['forecast']['pattern_chart']['patterns'])
  self.assertFalse(ui_fixture.broker.sent)
  c.post('/test/reset',json={},headers=h)
if __name__=='__main__':unittest.main()
