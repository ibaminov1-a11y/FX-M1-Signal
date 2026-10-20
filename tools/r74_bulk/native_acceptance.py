"""Windows acceptance on a synthetic terminal, never the user's account."""
import contextlib,hashlib,http.server,json,os,runpy,socket,sqlite3,subprocess,sys,tempfile,threading,time,types,zipfile
from pathlib import Path
from unittest.mock import patch

def invoke_cmd(path,args,env,log):
    command='"'+os.environ['COMSPEC']+'" /d /s /c ""'+str(path)+'"'+(' '+args if args else '')+'"'
    r=subprocess.run(command,env=env,cwd=path.parent,capture_output=True,timeout=90)
    text=(r.stdout+r.stderr).decode('utf-8','replace');log.write_text(text,encoding='utf-8');return r.returncode,text

def driver(root,out):
    # Uses the packaged Python and the real embedded source, but replaces only the
    # terminal at the I/O boundary. Actual native imports are checked separately.
    sys.path[:0]=[str(root/'mt5_bridge'),str(root/'tests/event_core'),str(root/'tools/r74_bulk')]
    from test_startup_clock import Timer,FakeMT5
    from event_core.store import Store
    source=(root/'START.cmd').read_text(encoding='utf-8').split('\n#R74_PY_BEGIN\n',1)[1]
    m=types.ModuleType('embedded_start');m.__file__=str(root/'START.cmd');sys.modules[m.__name__]=m;exec(compile(source,'<embedded>','exec'),m.__dict__)
    state=Path(os.environ['LOCALAPPDATA'])/'FXM1/R74-Recovery/event_state';state.mkdir(parents=True,exist_ok=True)
    store=Store(state/'campaign.sqlite3');store.save('retain',{'value':'existing-history'});store.close()
    token=state/'bridge-token.txt';token.write_text('fixture-only-key-preserve-01234567890123456789',encoding='utf-8')
    original=token.read_bytes();db_before=(state/'campaign.sqlite3').read_bytes();timer=Timer();fake=FakeMT5(timer)
    details=dict(key='123@DEMO',terminal='fixture-terminal64.exe',currency='USD')
    real_prepare=m.prepare_startup_clock;launches=[]
    def prepare(*args,**kwargs):
        return real_prepare(*args,**kwargs,mt5=fake,now=timer.time,monotonic=timer.mono,sleep=timer.sleep)
    def launch(path,**kwargs):
        assert path.endswith('bridge_v10_0.py');assert json.loads((state/'broker-clock.json').read_text())=={'account':'123@DEMO','offset_minutes':180,'confirmed':True}
        launches.append(list(sys.argv));return {}
    with patch.object(m,'inspect_terminal',return_value=(fake.account_info(),(),(),details)),patch.object(m,'prepare_startup_clock',side_effect=prepare),patch.object(m.runpy,'run_path',side_effect=launch):
        assert m.main([])==0
        assert len(launches)==1 and '--state-dir' in launches[0]
        report=json.loads((root/'STARTUP_CLOCK.json').read_text());assert report['status']=='CLOCK_POLICY_SAVED' and report['observations']>=8
        assert (state/'campaign.sqlite3').read_bytes()==db_before and token.read_bytes()==original
        policy=(state/'broker-clock.json').read_bytes();assert m.main([])==0
        assert json.loads((root/'STARTUP_CLOCK.json').read_text())['status']=='CLOCK_POLICY_PRESENT'
        assert policy==(state/'broker-clock.json').read_bytes() and token.read_bytes()==original
        assert (state/'campaign.sqlite3').read_bytes()==db_before
    out.write_text(json.dumps(dict(main_reached_server_without_restart=True,duplicate_samples_tolerated=True,
        repeat_start_idempotent=True,key_preserved=True,database_preserved=True,broker_orders_sent=0,real_terminal_used=False),indent=2))

def main(bundle,original_template,out):
    out=Path(out).resolve();out.mkdir(exist_ok=True,parents=True)
    with tempfile.TemporaryDirectory(prefix='FXM1 полная проверка ') as temp:
        temp=Path(temp);dest=temp/'Project (полный)';zipfile.ZipFile(bundle).extractall(dest);root=dest/'FX-M1-Signal'
        env=dict(os.environ,LOCALAPPDATA=str(temp/'LocalAppData'),R7_NO_PAUSE='1',FXM1_CLOCK_NO_PAUSE='1')
        # Reproduce the shipped helper's actual NO_NEW_TICK with a cached response.
        state=Path(env['LOCALAPPDATA'])/'FXM1/R74-Recovery/event_state';state.mkdir(parents=True)
        key='fixture-local-key-012345678901234567890123456789';(state/'bridge-token.txt').write_text(key);(state/'campaign.sqlite3').write_bytes(b'original-placeholder-not-used-by-http-helper')
        raw=int((time.time()+10800-.2)*1000)
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                assert self.path=='/ec/state';assert self.headers.get('Authorization')=='Bearer '+key;assert self.headers.get('X-FXM1-Client')=='R51'
                body=dict(account={'key':'123@DEMO','type':'DEMO'},auto=False,profiles=[{'auto':False,'campaign':None}],positions_ok=True,all_positions=[],campaign=None,pending_reversal=None,exit_pending=False,snapshot_age=0.,account_age=0.,
                    quote_diagnostics=dict(raw_tick_time_msc=raw,tick_time_msc=raw,offset_minutes=0,clock_identity='UTC_NATIVE_R51',received_at=time.time()))
                data=json.dumps(body).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',8000),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            old=temp/'OLD_FIX.cmd';old.write_bytes(Path(original_template).read_bytes().replace(b'__PINNED_ACCOUNT__',b'123@DEMO'))
            rc,text=invoke_cmd(old,'',env,out/'ORIGINAL_RED.log');assert rc==1 and 'NO_NEW_TICK' in text,text
            assert not (state/'broker-clock.json').exists()
        finally:server.shutdown();server.server_close()
        # Reset only this synthetic test directory, never a user's state.
        (state/'campaign.sqlite3').unlink();(state/'bridge-token.txt').unlink();state.rmdir()
        rc,text=invoke_cmd(root/'START.cmd','--check',env,out/'START_CHECK.log');assert rc==0 and 'PACKAGE CHECK OK' in text,text
        py=root/'Runtime/python.exe'
        code="import sys,runpy;sys.path[:0]="+repr([str(root/'mt5_bridge'),str(root/'tests/event_core')])+";runpy.run_path("+repr(str(root/'tools/r74_bulk/test_startup_clock.py'))+",run_name='__main__')"
        run=subprocess.run([str(py),'-I','-B','-X','utf8','-c',code],env=env,capture_output=True,timeout=60)
        text=(run.stdout+run.stderr).decode('utf-8','replace');(out/'BUNDLED_TESTS.log').write_text(text,encoding='utf-8');assert run.returncode==0 and 'Ran 15 tests' in text,text
        d=subprocess.run([str(py),'-I','-B','-X','utf8',str(Path(__file__).resolve()),'--driver',str(root),str(out/'NATIVE_MAIN.json')],env=env,capture_output=True,timeout=60)
        text=(d.stdout+d.stderr).decode('utf-8','replace');(out/'NATIVE_MAIN.log').write_text(text,encoding='utf-8');assert d.returncode==0,text
        # Repeat actual CMD after state creation: it must preserve saved state.
        rc,text=invoke_cmd(root/'START.cmd','--check',env,out/'START_RECHECK.log');assert rc==0,text
        manifest=json.loads((root/'PROGRAM_MANIFEST.json').read_text())
        assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in manifest['files'].items())
        (out/'WINDOWS.json').write_text(json.dumps(dict(bundle_sha256=hashlib.sha256(Path(bundle).read_bytes()).hexdigest(),new_tests=15,
            cmd_check_passed=True,original_failure_reproduced=True,embedded_main_verified=True,apk_sha256=manifest['apk_sha256'],real_broker_orders=0),indent=2))
if __name__=='__main__':
    if sys.argv[1]=='--driver':driver(Path(sys.argv[2]),Path(sys.argv[3]))
    else:main(*sys.argv[1:])
