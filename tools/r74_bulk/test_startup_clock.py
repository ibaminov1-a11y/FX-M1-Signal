"""Clock setup is a startup concern; all MT5 calls below are read-only fixtures."""
from __future__ import annotations
import contextlib, importlib.util, json, sqlite3, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace as NS

MODULE=Path(__file__).with_name('startup_clock.py')
KEY='123@DEMO'
class Timer:
    def __init__(self): self.t=1800000000.;self.m=0.
    def time(self):return self.t
    def mono(self):return self.m
    def sleep(self,n):self.t+=n;self.m+=n

class FakeMT5:
    def __init__(self,timer,pattern='delayed'):
        self.timer=timer;self.pattern=pattern;self.calls=[];self.raw=None;self.reads=0;self.key=KEY;self.ps=();self.os=();self.connected=True
    def initialize(self,*a,**kw):self.calls.append('initialize');return True
    def shutdown(self):self.calls.append('shutdown')
    def last_error(self):return (0,'fixture')
    def account_info(self):
        self.calls.append('account_info');login,server=self.key.split('@');return NS(login=int(login),server=server,trade_mode=0,margin_mode=2,currency='USD')
    def terminal_info(self):self.calls.append('terminal_info');return NS(connected=self.connected)
    def positions_get(self):self.calls.append('positions_get');return self.ps
    def orders_get(self):self.calls.append('orders_get');return self.os
    def symbol_info_tick(self,symbol):
        self.calls.append('symbol_info_tick');self.reads+=1
        offset=10800 if self.pattern!='wrong-offset' else 7200
        if self.pattern=='switch' and self.reads>=2:self.key='456@DEMO'
        if self.pattern=='late-exposure' and self.reads>=3:self.os=(NS(ticket=1),)
        if self.raw is None:self.raw=int((self.timer.t+offset-.2)*1000)
        if self.pattern in ('rapid','wrong-offset','switch','late-exposure') or (self.pattern=='delayed' and self.reads%4==0):self.raw=int((self.timer.t+offset-.2)*1000)
        if self.pattern=='backward' and self.reads==2:self.raw-=1000
        return NS(time_msc=self.raw,bid=1.12300,ask=1.12301)

class ClockFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.state=self.root/'event_state';self.state.mkdir()
        self.db=sqlite3.connect(self.state/'campaign.sqlite3');self.db.executescript("CREATE TABLE state(k TEXT PRIMARY KEY,value TEXT);CREATE TABLE intents(id TEXT PRIMARY KEY,status TEXT,body TEXT);");self.db.commit();self.db.close()
        (self.state/'bridge-token.txt').write_text('existing-key-do-not-replace'*2)
        self.timer=Timer();self.fake=FakeMT5(self.timer)
        self.original={p.name:p.read_bytes() for p in self.state.iterdir()}
    def tearDown(self):self.temp.cleanup()
    def module(self):
        self.assertTrue(MODULE.exists(),'INTEGRATED_CLOCK_SETUP_MISSING')
        spec=importlib.util.spec_from_file_location('startup_clock',MODULE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    def run_setup(self,**kwargs):
        m=self.module();return m.prepare_startup_clock(self.state,'terminal64.exe',KEY,180,mt5=self.fake,now=self.timer.time,monotonic=self.timer.mono,sleep=self.timer.sleep,log=lambda *a:None,timeout=kwargs.pop('timeout',15),**kwargs)
    def unchanged(self):
        for k,v in self.original.items():self.assertEqual(v,(self.state/k).read_bytes(),k)
        self.assertFalse(any(c.startswith('order_send') for c in self.fake.calls))

class ClockTests(ClockFixture,unittest.TestCase):
    def test_duplicate_samples_wait_for_new_tick_and_save_explicit_policy(self):
        result=self.run_setup();self.assertEqual(result['status'],'CLOCK_POLICY_SAVED');self.assertGreaterEqual(self.fake.reads,8)
        self.assertEqual(json.loads((self.state/'broker-clock.json').read_text()),dict(account=KEY,offset_minutes=180,confirmed=True))
        self.unchanged()
    def test_already_saved_exact_policy_is_idempotent(self):
        self.run_setup();before=(self.state/'broker-clock.json').read_bytes();self.fake.reads=0
        self.assertEqual(self.run_setup()['status'],'CLOCK_POLICY_PRESENT');self.assertEqual(self.fake.reads,0)
        self.assertEqual(before,(self.state/'broker-clock.json').read_bytes());self.unchanged()
    def test_all_repeats_timeout_without_writing_policy(self):
        self.fake.pattern='frozen'
        with self.assertRaisesRegex(RuntimeError,'CLOCK_WAIT_TIMEOUT'):self.run_setup(timeout=5)
        self.assertGreaterEqual(self.timer.m,5);self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_other_account_never_receives_confirmed_policy(self):
        self.fake.key='456@DEMO'
        with self.assertRaisesRegex(RuntimeError,'CLOCK_ACCOUNT_MISMATCH'):self.run_setup()
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_mid_check_account_change_prevents_write(self):
        self.fake.pattern='switch'
        with self.assertRaisesRegex(RuntimeError,'CLOCK_ACCOUNT_MISMATCH'):self.run_setup()
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_offset_is_not_guessed_from_ticks(self):
        self.fake.pattern='wrong-offset'
        with self.assertRaisesRegex(RuntimeError,'CLOCK_WAIT_TIMEOUT|CLOCK_OFFSET_MISMATCH'):self.run_setup(timeout=4)
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_positions_prevent_clock_change(self):
        self.fake.ps=(NS(ticket=1),)
        with self.assertRaisesRegex(RuntimeError,'CLOCK_EXPOSURE_ACTIVE'):self.run_setup()
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_orders_appearing_during_sampling_prevent_write(self):
        self.fake.pattern='late-exposure'
        with self.assertRaisesRegex(RuntimeError,'CLOCK_EXPOSURE_ACTIVE'):self.run_setup()
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_unknown_positions_fail_closed(self):
        self.fake.ps=None
        with self.assertRaisesRegex(RuntimeError,'CLOCK_MT5_UNCONFIRMED'):self.run_setup()
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_saved_campaign_prevents_clock_change(self):
        with contextlib.closing(sqlite3.connect(self.state/'campaign.sqlite3')) as db:
            db.execute('INSERT INTO state VALUES (?,?)',('profile:fixture:engine',json.dumps({'campaign':{'id':'active'}})));db.commit()
        self.original['campaign.sqlite3']=(self.state/'campaign.sqlite3').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'CLOCK_SAVED_EXPOSURE'):self.run_setup()
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_unknown_intent_prevents_clock_change(self):
        with contextlib.closing(sqlite3.connect(self.state/'campaign.sqlite3')) as db:
            db.execute('INSERT INTO intents VALUES (?,?,?)',('intent','UNKNOWN','{}'));db.commit()
        self.original['campaign.sqlite3']=(self.state/'campaign.sqlite3').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'CLOCK_UNKNOWN_EXECUTION'):self.run_setup()
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_existing_other_policy_is_never_overwritten(self):
        file=self.state/'broker-clock.json';file.write_text(json.dumps({'account':'456@DEMO','offset_minutes':120,'confirmed':True}));before=file.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'CLOCK_POLICY_CONFLICT'):self.run_setup()
        self.assertEqual(file.read_bytes(),before);self.unchanged()
    def test_raw_tick_backwards_is_not_a_new_tick(self):
        self.fake.pattern='backward'
        with self.assertRaisesRegex(RuntimeError,'CLOCK_TICK_BACKWARDS'):self.run_setup()
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()
    def test_disconnected_terminal_never_saves(self):
        self.fake.connected=False
        with self.assertRaisesRegex(RuntimeError,'CLOCK_MT5_UNCONFIRMED'):self.run_setup()
        self.assertFalse((self.state/'broker-clock.json').exists());self.unchanged()

class ClockForecastIntegration(ClockFixture,unittest.TestCase):
    def test_saved_clock_is_consumed_by_adapter_and_http_forecast(self):
        from unittest.mock import patch
        from event_core.clock_setup import load_clock_policy
        from event_core.mt5_adapter import MT5Broker
        from event_core.engine import Engine
        from event_core.store import Store
        from event_core.server import create_app
        from test_r55_history_clock import ConfiguredForecastBroker
        from test_r51_repairs import NOW
        self.run_setup();self.unchanged()
        policy=load_clock_policy(self.state)
        now=[NOW];broker=ConfiguredForecastBroker(now,False)
        broker.native=MT5Broker(broker.terminal,**policy)
        store=Store(self.root/'integration.sqlite3')
        try:
            store.save('engine',{'config':{'engine_mode':'SCENARIO_V2','timeframe':'M5','approved':True,'fee_per_lot':0}})
            engine=Engine(broker,store,lambda:now[0])
            for dt in (0.,1.2):
                now[0]=NOW+dt;broker.terminal.tick=now[0]+10800
                with patch('event_core.mt5_adapter.time.time',return_value=now[0]),patch('event_core.mt5_adapter.time.monotonic',return_value=10+dt):
                    state=engine.step()
            self.assertTrue(state['quote_fresh'],state.get('market_errors'))
            self.assertTrue(state['forecast']['available'])
            self.assertTrue(state['forecast']['price_forecast']['available'],state['forecast']['price_forecast'])
            self.assertGreater(len(state['forecast']['price_forecast']['projection']),0)
            app=create_app(engine,'fixture-token-not-a-user-secret-0123456789')
            app.config['runtime_views'].publish()
            with app.test_client() as client:
                response=client.get('/ec/state',headers={'Authorization':'Bearer fixture-token-not-a-user-secret-0123456789','X-FXM1-Client':'R51'})
                self.assertEqual(response.status_code,200)
                body=response.get_json();self.assertTrue(body['forecast']['price_forecast']['available'])
                self.assertFalse(body['auto']);self.assertEqual(broker.sent,[])
        finally:store.close()

if __name__=='__main__':unittest.main(verbosity=2)
