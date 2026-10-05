"""Test inputs must model clock advancement and transport loss, not false UI flags."""
import unittest,calendar
from event_core.model import bar_close_time,validate_bar_history
class FixtureBoundaryTests(unittest.TestCase):
 def test_multiframe_fixture_closes_old_forming_bar_when_clock_advances(self):
  from ui_fixture import R56Broker
  now=[float(calendar.timegm((2026,10,5,14,6,58)))];broker=R56Broker(lambda:now[0])
  before=broker.bars('EURUSD','M1');live=broker.current_bar('EURUSD','M1');now[0]+=40
  after=broker.bars('EURUSD','M1')
  self.assertEqual(after[-1].time,live.time,'FIXTURE_LEFT_M1_HISTORY_STALE')
  self.assertEqual(before[-1],after[-2]);self.assertLessEqual(bar_close_time(after[-1].time,'M1',0),now[0])
  validate_bar_history(after,'M1',now[0])
 def test_offline_scene_fails_http_instead_of_claiming_disconnected_in_success(self):
  import ui_fixture
  c=ui_fixture.app.test_client();h={'Authorization':'Bearer ci-fixture-token-not-for-real-trading','X-FXM1-Client':'R51'}
  try:
   c.post('/test/reset',json={},headers=h)
   c.post('/test/r732-pattern',json={'index':17,'view':'offline'},headers=h)
   self.assertEqual(c.get('/ec/state',headers=h).status_code,503,'OFFLINE_FIXTURE_RETURNED_SUCCESS')
   c.post('/test/r732-pattern',json={'index':17,'view':'live'},headers=h)
   self.assertEqual(c.get('/ec/state',headers=h).status_code,200)
  finally:c.post('/test/reset',json={},headers=h)
if __name__=='__main__':unittest.main()
