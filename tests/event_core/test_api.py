import unittest,tempfile,uuid
from pathlib import Path
from event_core.engine import Engine
from event_core.store import Store
from event_core.server import create_app
from fakes import FakeBroker
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=1800000000.;self.b=FakeBroker(lambda:self.now)
        self.store=Store(Path(self.tmp.name)/'state.db');self.e=Engine(self.b,self.store,lambda:self.now)
        self.client=create_app(self.e,'test-only-token').test_client();self.h={'Authorization':'Bearer test-only-token'}
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def post(self,cmd,seq,**extra):
        return self.client.post('/ec/command/'+cmd,headers=self.h,json=dict(command_id='command-'+cmd+str(seq),client_id='test-client',sequence=seq,**extra))
    def test_no_auth_cannot_trade(self):
        self.assertEqual(self.client.post('/ec/command/enable',json={}).status_code,401)
    def test_old_signal_endpoint_is_disabled(self):
        self.assertEqual(self.client.post('/signal',headers=self.h,json={'signal':'BUY'}).status_code,410)
        self.assertFalse(self.b.sent)
    def test_delayed_enable_rejected_after_disable(self):
        self.post('disable',10)
        r=self.post('enable',9,confirmation='ENABLE_DEMO')
        self.assertEqual(r.status_code,409);self.assertIn('Устаревшая',r.get_json()['message']);self.assertFalse(self.e.auto)
    def test_explicit_protocol(self):
        r=self.client.get('/ec/state',headers=self.h)
        self.assertEqual(r.get_json()['protocol'],'fxm1.event.v1')
    def test_bad_config_no_change(self):
        r=self.post('configure',1,config={'mode':'SCALP','timeframe':'bad'})
        self.assertEqual(r.status_code,409);self.assertEqual(self.e.config.mode,'NORMAL')
    def test_daily_limit_not_reset_by_play(self):
        self.e.daily_latch='2027-01-15';self.e.config.approved=True
        # Regardless of a latch, PLAY cannot arm a previously off engine.
        self.assertEqual(self.post('play',1).status_code,409)

if __name__=='__main__':unittest.main()
