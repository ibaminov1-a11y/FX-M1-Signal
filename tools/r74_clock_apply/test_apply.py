"""Native tests use a local synthetic Bridge; no financial orders are sent."""
import http.server,json,os,subprocess,tempfile,threading,time,unittest
from pathlib import Path
ROOT=Path(__file__).parent
TEMPLATE=ROOT/'APPLY_CLOCK.template.cmd'
ACCOUNT='123@DemoBroker'
TOKEN='LOCAL_TEST_ONLY_0123456789abcdefgh_abcdefghijklmnopqrstuvwxyz'
class Contract(unittest.TestCase):
    def test_helper_exists_with_explicit_account_and_offset(self):
        self.assertTrue(TEMPLATE.is_file(),'Missing account-bound configuration writer')
        text=TEMPLATE.read_text('utf-8')
        self.assertIn('__PINNED_ACCOUNT__',text)
        self.assertIn('$offsetMinutes = 180',text)
        self.assertIn("$request.Method = 'GET'",text)
        self.assertIn("$request.Headers['X-FXM1-Client'] = 'R51'",text)
        for forbidden in ("Method = 'POST'",'order_send','Set-Date','w32tm','ExecutionPolicy Bypass','Stop-Process','/ec/command'):
            self.assertNotIn(forbidden,text)
@unittest.skipUnless(os.name=='nt','Windows CMD tests')
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario='normal';cls.calls=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                cls.calls.append((self.command,self.path))
                if self.path!='/ec/state' or self.headers.get('Authorization')!='Bearer '+TOKEN or self.headers.get('X-FXM1-Client')!='R51':
                    self.send_error(403);return
                now=time.time();s=cls.scenario;raw=int((now+10800-.5)*1000)
                if s=='frozen':raw=cls.frozen_tick
                if s=='other_offset':raw=int((now+7200-.5)*1000)
                offset=180 if s=='already_applied' else 0
                account=ACCOUNT if s!='other_account' else '456@DemoBroker'
                data=dict(account=dict(key=account,type='DEMO'),auto=(s=='auto_on'),
                    profiles=[dict(auto=(s=='other_profile_auto'),campaign={'id':'c'} if s=='campaign' else None)],
                    positions_ok=s!='positions_unknown',all_positions=[{'ticket':1}] if s=='positions' else [],
                    campaign=None,pending_reversal=None,exit_pending=False,
                    account_age=0.1,snapshot_age=50 if s=='stale' else 0.01,server_time=now,
                    quote_diagnostics=dict(raw_tick_time_msc=raw,tick_time_msc=raw-offset*60000,received_at=now,
                        offset_minutes=offset,clock='UTC_EXPLICIT' if offset else 'UTC_NATIVE',
                        clock_identity='UTC_EXPLICIT_R55:'+ACCOUNT+':180' if offset else 'UTC_NATIVE_R51'))
                if s=='missing_auto':del data['auto']
                if s=='wrong_effective':data['quote_diagnostics']['tick_time_msc']-=1000
                body=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):cls.calls.append(('POST',self.path));self.send_error(405)
        cls.server=http.server.ThreadingHTTPServer(('127.0.0.1',8000),Handler)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def run_case(self,scenario='normal',existing=None,no_key=False):
        with tempfile.TemporaryDirectory(prefix='FXM1 проверка ') as d:
            root=Path(d);state=root/'LocalAppData'/'FXM1'/'R74-Recovery'/'event_state';state.mkdir(parents=True)
            files={'campaign.sqlite3':b'DATABASE_NOT_TO_BE_CHANGED','bridge-token.txt':TOKEN.encode(),'sentinel.txt':b'KEEP'}
            for name,data in files.items():
                if no_key and name=='bridge-token.txt':continue
                (state/name).write_bytes(data)
            if existing is not None:(state/'broker-clock.json').write_bytes(existing)
            before={p.name:p.read_bytes() for p in state.iterdir()}
            helper=root/'Downloads (русский)'/'FIX_MT5_TIME.cmd';helper.parent.mkdir()
            helper.write_bytes(TEMPLATE.read_bytes().replace(b'__PINNED_ACCOUNT__',ACCOUNT.encode()))
            self.__class__.scenario=scenario;self.__class__.calls.clear();self.__class__.frozen_tick=int((time.time()+10800-.5)*1000)
            env=dict(os.environ,LOCALAPPDATA=str(root/'LocalAppData'),FXM1_CLOCK_NO_PAUSE='1')
            p=subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(helper)],cwd=root,env=env,capture_output=True,timeout=25)
            text=(p.stdout+p.stderr).decode('utf-8','replace');self.assertNotIn(TOKEN,text)
            after={p.name:p.read_bytes() for p in state.iterdir()}
            for name,old in before.items():self.assertEqual(after[name],old,name)
            self.assertTrue(all(x==('GET','/ec/state') for x in self.calls),self.calls)
            return p.returncode,text,before,after
    def test_writes_only_account_bound_180_policy(self):
        rc,text,b,a=self.run_case();self.assertEqual(rc,0,text)
        self.assertEqual(set(a)-set(b),{'broker-clock.json'})
        self.assertEqual(json.loads(a['broker-clock.json'].decode('utf-8-sig')),dict(account=ACCOUNT,offset_minutes=180,confirmed=True))
        self.assertIn('CLOCK_POLICY_SAVED_RESTART_REQUIRED',text)
    def test_idempotent_same_policy_is_preserved_exactly(self):
        existing=json.dumps(dict(account=ACCOUNT,offset_minutes=180,confirmed=True),indent=4).encode()
        rc,text,b,a=self.run_case(existing=existing);self.assertEqual(rc,0,text);self.assertEqual(b,a)
        self.assertIn('CLOCK_POLICY_ALREADY_SAVED',text)
    def test_already_active_policy_does_not_apply_twice(self):
        existing=json.dumps(dict(account=ACCOUNT,offset_minutes=180,confirmed=True)).encode()
        rc,text,b,a=self.run_case('already_applied',existing);self.assertEqual(rc,0,text);self.assertEqual(b,a)
        self.assertIn('CLOCK_POLICY_ACTIVE',text)
    def test_unsafe_observations_write_nothing(self):
        for scenario in ('other_account','auto_on','other_profile_auto','campaign','positions','positions_unknown','stale','missing_auto','wrong_effective','other_offset','frozen'):
            with self.subTest(scenario=scenario):
                rc,text,b,a=self.run_case(scenario);self.assertNotEqual(rc,0,text);self.assertEqual(b,a)
    def test_conflicting_policy_never_overwritten(self):
        for data in (b'{invalid',json.dumps(dict(account=ACCOUNT,offset_minutes=120,confirmed=True)).encode(),json.dumps(dict(account='other@broker',offset_minutes=180,confirmed=True)).encode()):
            with self.subTest(data=data):
                rc,text,b,a=self.run_case(existing=data);self.assertNotEqual(rc,0,text);self.assertEqual(b,a)
    def test_missing_key_no_writes(self):
        rc,text,b,a=self.run_case(no_key=True);self.assertNotEqual(rc,0,text);self.assertEqual(b,a);self.assertEqual(self.calls,[])
if __name__=='__main__':unittest.main(verbosity=2)
