"""Standalone ready runtime must preserve the installed environment/state."""
import importlib.util, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'mt5_bridge'))

class ReadyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='R732 путь space ! ');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.old=self.root/'mt5_bridge';self.new=self.root/'mt5_bridge_R732'
        self.new.mkdir();(self.old/'.venv/Scripts').mkdir(parents=True);(self.old/'event_state').mkdir()
        (self.old/'.venv/Scripts/python.exe').write_bytes(b'PYTHON')
        (self.old/'event_state/campaign.sqlite3').write_bytes(b'EXISTING_DB')
        (self.old/'event_state/bridge-token.txt').write_text('private-token-'*4)
        (self.new/'event_core').mkdir();(self.new/'event_core/__init__.py').write_text('VERSION="10.9-EC1"')
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('ready_launcher'),'READY_LAUNCHER_MISSING')
        import ready_launcher
        return ready_launcher
    def test_sibling_is_only_runtime_source(self):
        m=self.module();r=m.resolve_runtime(self.new)
        self.assertEqual(r.program_root,self.new.resolve());self.assertEqual(r.state_dir,(self.old/'event_state').resolve())
        self.assertEqual(r.python,(self.old/'.venv/Scripts/python.exe').resolve())
    def test_missing_state_never_creates_empty_history(self):
        m=self.module();(self.old/'event_state/campaign.sqlite3').unlink()
        with self.assertRaisesRegex(RuntimeError,'state|history|состоян|баз'):m.resolve_runtime(self.new)
        self.assertFalse((self.new/'event_state').exists())
    def test_missing_token_does_not_generate_a_new_identity(self):
        m=self.module();(self.old/'event_state/bridge-token.txt').unlink()
        with self.assertRaises(RuntimeError):m.resolve_runtime(self.new)
        self.assertFalse((self.old/'event_state/bridge-token.txt').exists())
    def test_invalid_environment_is_not_silently_replaced(self):
        m=self.module();(self.old/'.venv/Scripts/python.exe').unlink()
        with self.assertRaises(RuntimeError):m.resolve_runtime(self.new)
        self.assertFalse((self.new/'.venv').exists())
    def test_old_program_and_pycache_not_read(self):
        m=self.module();old=self.old/'event_core/__pycache__';old.mkdir(parents=True);(old/'locked.pyc').write_bytes(b'OLD')
        before={p.relative_to(self.old).as_posix():p.read_bytes() for p in self.old.rglob('*') if p.is_file()}
        r=m.resolve_runtime(self.new)
        self.assertNotEqual(r.program_root,self.old)
        self.assertEqual(before,{p.relative_to(self.old).as_posix():p.read_bytes() for p in self.old.rglob('*') if p.is_file()})
    def test_poisoning_environment_cannot_choose_program_or_state(self):
        m=self.module()
        with patch.dict(os.environ,{'PYTHONPATH':str(self.old),'PYTHONHOME':'poison'}):
            r=m.resolve_runtime(self.new);cmd,env=m.server_command(r,['--port','8000'])
        self.assertIn('-I',cmd);self.assertIn('-B',cmd);self.assertNotIn('PYTHONPATH',env);self.assertNotIn('PYTHONHOME',env)
        self.assertIn(str(self.new.resolve()),cmd);self.assertIn(str((self.old/'event_state').resolve()),cmd)
    def test_trade_state_argument_cannot_be_overridden(self):
        m=self.module();r=m.resolve_runtime(self.new)
        for args in (['--state-dir','other'],['--state-dir=other']):
            with self.assertRaises(RuntimeError):m.server_command(r,args)
    def test_wrong_architecture_and_platform_fail(self):
        m=self.module()
        for report in ({'bits':32,'version':[3,12,0],'platform':'win32'},{'bits':64,'version':[3,9,0],'platform':'win32'},{'bits':64,'version':[3,12,0],'platform':'linux'}):
            with self.assertRaises(RuntimeError):m.validate_python(report)
    def test_server_will_reuse_actual_lock_path(self):
        m=self.module();r=m.resolve_runtime(self.new)
        with (r.state_dir/'runtime.lock').open('a+b') as lock:
            if os.name=='nt':
                import msvcrt
                lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError,'running|работает|lock'):m.require_stopped(r)
    def test_no_sensitive_console_capture_or_dependency_install(self):
        m=self.module();r=m.resolve_runtime(self.new)
        with patch.object(m,'require_stopped'),patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            self.assertEqual(m.launch(r,['--port','8000']),0)
        args,kwargs=run.call_args
        self.assertNotIn('stdout',kwargs);self.assertNotIn('stderr',kwargs);self.assertNotIn('capture_output',kwargs)
        self.assertNotIn('pip',' '.join(args[0]));self.assertNotIn('install',' '.join(args[0]))

if __name__=='__main__':unittest.main()
