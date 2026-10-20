"""Native diagnostic acceptance: fake localhost Bridge; never a trading connection."""
import hashlib, http.server, json, os, shutil, subprocess, tempfile, threading, time, unittest
from pathlib import Path
ROOT=Path(__file__).parent
HELPER=ROOT/'CHECK_TIME.cmd'
TOKEN='fake-test-token-should-never-appear-in-report-0123456789'

class Contract(unittest.TestCase):
    def test_single_file_read_only_contract(self):
        self.assertTrue(HELPER.is_file(), 'Missing one-file clock report helper')
        text=HELPER.read_text(encoding='utf-8-sig')
        self.assertIn('/ec/state',text)
        self.assertIn('127.0.0.1:8000',text)
        self.assertIn('AllowAutoRedirect = $false',text)
        for forbidden in ['order_send(', 'Set-Date ', 'w32tm /resync', 'Set-Content ', "Method = 'POST'"]:
            self.assertNotIn(forbidden,text)

@unittest.skipUnless(os.name=='nt','native Windows CMD acceptance')
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                cls.calls.append((self.command,self.path,self.headers.get('Authorization')))
                if self.headers.get('Authorization')!='Bearer '+TOKEN:
                    self.send_error(401); return
                now=time.time()
                body={'bridge_version':'10.9-EC1-R7.4','server_time':now,
                    'account':{'key':'123@DEMO','balance':999999,'password':'DO_NOT_EXPORT_BALANCE_OR_PASSWORD'},
                    'auto':False,'quote_fresh':False,'entry_allowed':False,
                    'config':{'symbol':'EURUSD','timeframe':'M5'},
                    'quote_diagnostics':{'clock':'UTC_NATIVE','clock_identity':'UTC_NATIVE_R51',
                        'offset_minutes':0,'raw_tick_time_msc':int((now+10798)*1000),
                        'tick_time_msc':int((now+10798)*1000),'received_at':now,
                        'raw_age_at_receive_sec':-10798,'age_at_receive_sec':-10798,'feed_confirmed':False},
                    'secret_debug':TOKEN,'bars':[{'time':1,'close':2}], 'forecast':{'available':False}}
                encoded=json.dumps(body).encode();self.send_response(200); self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
            def do_POST(self):
                cls.calls.append(('POST',self.path,None));self.send_error(405)
        cls.server=http.server.ThreadingHTTPServer(('127.0.0.1',8000),Handler)
        cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()
    def run_case(self,policy=None,token=True):
        with tempfile.TemporaryDirectory(prefix='FXM1 проверка ') as temp:
            base=Path(temp); install=base/'Downloads (проверка)';install.mkdir()
            helper=install/'CHECK_TIME.cmd';shutil.copyfile(HELPER,helper)
            local=base/'AppData';state=local/'FXM1'/'R74-Recovery'/'event_state';state.mkdir(parents=True)
            (state/'campaign.sqlite3').write_bytes(b'do not read or change this database')
            if token:(state/'bridge-token.txt').write_text(TOKEN)
            if policy is not None:(state/'broker-clock.json').write_text(json.dumps(policy))
            before={p.name:p.read_bytes() for p in state.iterdir()}
            env=dict(os.environ,LOCALAPPDATA=str(local),FXM1_REPORT_NO_OPEN='1',FXM1_REPORT_NO_PAUSE='1')
            self.calls.clear()
            result=subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(helper)],env=env,cwd=base,
                 capture_output=True,timeout=55)
            self.assertEqual(result.returncode,0,result.stdout.decode('utf-8','replace')+result.stderr.decode('utf-8','replace'))
            reports=list(install.glob('FXM1_TIME_REPORT_*.txt'));self.assertEqual(len(reports),1)
            text=reports[0].read_text(encoding='utf-8-sig');report=json.loads(text)
            self.assertNotIn(TOKEN,text);self.assertNotIn('DO_NOT_EXPORT',text);self.assertNotIn('999999',text)
            self.assertEqual(before,{p.name:p.read_bytes() for p in state.iterdir()})
            self.assertFalse(report['settings_changed']);self.assertFalse(report['orders_sent'])
            self.assertTrue(all(method=='GET' and path=='/ec/state' for method,path,_ in self.calls))
            if token:
                self.assertEqual(len(self.calls),3)
                self.assertEqual(len(report['bridge_samples']),3)
                self.assertAlmostEqual(report['bridge_samples'][0]['effective_tick_minus_windows_seconds'],10798,delta=3)
            else:self.assertEqual(len(self.calls),0)
            return report
    def test_future_ticks_are_reported_not_corrected(self):
        r=self.run_case();self.assertFalse(r['saved_policy']['present']);self.assertEqual(r['result'],'EVIDENCE_ONLY_NO_CLOCK_CHANGE')
    def test_policy_is_reported_without_rewriting_or_exporting_extra_fields(self):
        r=self.run_case({'account':'123@DEMO','offset_minutes':180,'confirmed':True,'password':TOKEN})
        self.assertEqual(r['saved_policy']['offset_minutes'],180);self.assertTrue(r['saved_policy']['account_matches_connected'])
    def test_missing_key_makes_no_bridge_calls_and_creates_report(self):
        r=self.run_case(token=False);self.assertEqual(r['bridge_error'],'LOCAL_KEY_NOT_FOUND');self.assertEqual(r['bridge_samples'],[])

if __name__=='__main__':unittest.main(verbosity=2)
