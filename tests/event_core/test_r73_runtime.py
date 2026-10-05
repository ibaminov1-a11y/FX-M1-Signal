"""Exercise the real Flask/Portfolio boundary; only MT5 transport is substituted."""
import tempfile, threading, time, unittest
from pathlib import Path
from event_core.model import Blocked
from event_core.portfolio import Portfolio
from event_core.server import create_app
from event_core.store import Store
from fakes import FakeBroker
from event_core.mt5_adapter import MT5Broker
from types import SimpleNamespace
import logging


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state.db');self.addCleanup(self.store.close)
        self.now=[1800000000.]
        self.broker=FakeBroker(lambda:self.now[0])
        self.p=Portfolio(self.broker,self.store,lambda:self.now[0]);self.p.step()
        self.app=create_app(self.p,'runtime-tests');self.client=self.app.test_client()
        self.headers={'Authorization':'Bearer runtime-tests','X-FXM1-Client':'R51'}
        self.client.get('/ec/state',headers=self.headers)

    def hold_engine(self):
        entered=threading.Event();release=threading.Event()
        def hold():
            with self.p.lock:entered.set();release.wait(5)
        worker=threading.Thread(target=hold,daemon=True);worker.start()
        self.assertTrue(entered.wait(1))
        self.addCleanup(worker.join,2);self.addCleanup(release.set)
        return release

    def request_while_busy(self,path,method='GET',body=None):
        release=self.hold_engine();done=threading.Event();result=[]
        def request():
            with self.app.test_client() as c:
                result.append(c.open(path,method=method,json=body,headers=self.headers));done.set()
        reader=threading.Thread(target=request,daemon=True);reader.start()
        try:self.assertTrue(done.wait(1),path+' waited behind the MT5 execution lock')
        finally:release.set();reader.join(2)
        return result[0]

    def test_state_read_does_not_touch_unavailable_mt5(self):
        def broken():raise Blocked('MT5 positions unavailable')
        self.broker.positions=broken
        response=self.client.get('/ec/state',headers=self.headers)
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        self.assertEqual(response.get_json()['protocol'],'fxm1.event.v1')

    def test_state_remains_responsive_while_mt5_owner_is_busy(self):
        response=self.request_while_busy('/ec/state')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.get_json()['runtime_busy'])

    def test_health_remains_reachable_while_mt5_owner_is_busy(self):
        response=self.request_while_busy('/health')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.get_json()['server_connected'])

    def test_cached_account_and_quote_expire_while_busy(self):
        self.now[0]+=20
        response=self.request_while_busy('/ec/state');s=response.get_json()
        self.assertGreaterEqual(s['account_age'],20)
        self.assertFalse(s['quote_fresh']);self.assertFalse(s['history_ok'])
        self.assertFalse(s['entry_allowed']);self.assertTrue(s['forecast']['stale'])

    def test_busy_cached_timeframe_alignment_also_expires(self):
        self.assertTrue(any(row['available'] for row in self.p.snapshot()['timeframes']))
        self.now[0]+=20
        s=self.request_while_busy('/ec/state').get_json()
        self.assertTrue(all(not row['available'] and row['alignment']=='UNAVAILABLE' for row in s['timeframes']))
        self.assertEqual(s['timeframe_context']['supports'],[])
        self.assertEqual(s['timeframe_context']['opposes'],[])

    def test_busy_command_is_rejected_before_acceptance_and_never_runs_later(self):
        response=self.request_while_busy('/ec/command/emergency','POST',dict(
            client_id='runtime-tests',sequence=1,command_id='busy-emergency'))
        self.assertEqual(response.status_code,503)
        self.assertFalse(response.get_json()['accepted'])
        self.assertFalse(self.p.emergency)
        self.assertIsNone(self.store.command_result('busy-emergency'))

    def test_busy_unknown_profile_does_not_receive_another_profiles_snapshot(self):
        response=self.request_while_busy('/ec/state?profile_id=p-does-not-exist')
        self.assertEqual(response.status_code,409)
        self.assertNotIn('account',response.get_json())

    def test_foreign_positions_are_retained_in_account_snapshot(self):
        self.broker._positions=[dict(ticket=7,identifier=7,symbol='GBPUSD',magic=123,side=1,
            volume=.01,price_open=1.1,price_current=1.1,sl=1.09,profit=3.,swap=0.)]
        self.p.step()
        s=self.client.get('/ec/state',headers=self.headers).get_json()
        self.assertEqual([p['ticket'] for p in s['all_positions']],[7])
        self.assertEqual(s['positions'],[])

    def test_health_and_state_preserve_authentication(self):
        for path in ('/health','/ec/state'):
            response=self.client.get(path)
            self.assertEqual(response.status_code,401)
            self.assertNotIn('account',response.get_json())

    def test_account_adoption_cannot_relabel_old_account_positions(self):
        self.broker._positions=[dict(ticket=7,identifier=7,symbol='GBPUSD',magic=123,side=1,
            volume=.01,price_open=1.1,price_current=1.1,sl=1.09,profit=3.,swap=0.)]
        self.p.step()
        old_account=self.broker.account
        self.broker.account=lambda:dict(old_account(),key='456@DEMO',login=456)
        self.broker._positions=[]
        self.p.command('adopt_account',dict(confirmation='ADOPT_MT5_ACCOUNT',command_id='adopt-test'))
        s=self.client.get('/ec/state',headers=self.headers).get_json()
        self.assertEqual(s['account']['key'],'456@DEMO')
        self.assertEqual(s['all_positions'],[],'Old positions were relabelled as the adopted account')
        self.assertFalse(s['positions_ok'])
        self.p.step()
        self.assertTrue(self.client.get('/ec/state',headers=self.headers).get_json()['positions_ok'])

    def test_lost_mt5_ipc_is_reinitialized_before_next_read(self):
        class Terminal:
            def __init__(self):self.ready=False;self.connects=0;self.args=None
            def initialize(self,*args,**kwargs):
                self.ready=True;self.connects+=1;self.args=(args,kwargs);return True
            def terminal_info(self):return SimpleNamespace(connected=True) if self.ready else None
            def last_error(self):return (-10004,'IPC connection lost')
        terminal=Terminal();broker=MT5Broker(terminal,'C:/MT5/terminal64.exe')
        broker.connect();terminal.ready=False
        with self.assertRaises(Blocked):broker.connect()
        try:broker.connect()
        except Blocked as exc:self.fail('Next read must reinitialize lost IPC: '+str(exc))
        self.assertEqual(terminal.connects,2)
        self.assertEqual(terminal.args,(('C:/MT5/terminal64.exe',),{'timeout':5000}))

    def test_runtime_diagnostic_rotates_and_redacts_token_even_in_exceptions(self):
        from event_core.server import configure_runtime_log
        token='private-runtime-test-token'
        logger=logging.getLogger('r73-test-log');logger.setLevel(logging.INFO);logger.propagate=False
        handler=configure_runtime_log(Path(self.tmp.name),token,logger)
        self.addCleanup(logger.removeHandler,handler);self.addCleanup(handler.close)
        try:raise RuntimeError('MT5 unavailable '+token)
        except RuntimeError:logger.exception('Runtime failed '+token)
        handler.flush();content=(Path(self.tmp.name)/'bridge-runtime.log').read_text(encoding='utf-8')
        self.assertIn('MT5 unavailable',content);self.assertNotIn(token,content)
        self.assertGreater(handler.maxBytes,0);self.assertGreater(handler.backupCount,0)


if __name__=='__main__':unittest.main()
