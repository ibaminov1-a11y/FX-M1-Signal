import importlib.util, json, os, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('restore_launcher',HERE/'restore_launcher.py')
L=importlib.util.module_from_spec(spec);sys.modules[spec.name]=L;spec.loader.exec_module(L)

class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.base=Path(self.t.name).resolve()
        self.root=self.base/'Чистая папка ! test'/'FXM1_R74';self.root.mkdir(parents=True)
        (self.root/'Runtime').mkdir();(self.root/'Runtime/python.exe').write_bytes(b'test-exe')
        (self.root/'mt5_bridge/event_core').mkdir(parents=True)
        (self.root/'mt5_bridge/event_core/__init__.py').write_text('')
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(self.base/'Local App Data')});self.env.start()
    def tearDown(self):self.env.stop();self.t.cleanup()
    def test_fresh_install_does_not_require_deleted_old_environment(self):
        try: paths=L.resolve_runtime(self.root)
        except RuntimeError as e:self.fail('FRESH_INSTALL_REQUIRES_DELETED_ENVIRONMENT: '+str(e))
        self.assertEqual(paths.python,(self.root/'Runtime/python.exe').resolve())
        self.assertFalse(paths.state_dir.exists())
        self.assertNotEqual(paths.state_dir.parent,self.root)
    def test_new_state_creates_unique_identity_with_auto_off(self):
        paths=L.resolve_runtime(self.root)
        self.assertEqual(L.state_mode(paths.state_dir),'NEW')
        L.initialize_state(paths.state_dir,{'key':'123@demo','terminal':'terminal64.exe'})
        self.assertEqual(L.state_mode(paths.state_dir),'EXISTING')
        token=(paths.state_dir/'bridge-token.txt').read_text()
        self.assertGreaterEqual(len(token),32)
        import sqlite3
        c=sqlite3.connect(paths.state_dir/'campaign.sqlite3')
        try:self.assertEqual(c.execute('select count(*) from intents').fetchone()[0],0)
        finally:c.close()
        self.assertFalse(json.loads((paths.state_dir/'recovery-install.json').read_text())['auto_enabled'])
    def test_partial_state_is_never_silently_replaced(self):
        p=L.resolve_runtime(self.root).state_dir;p.mkdir(parents=True)
        (p/'bridge-token.txt').write_text('private-test-value')
        with self.assertRaises(RuntimeError):L.state_mode(p)
        with self.assertRaises((RuntimeError,FileExistsError)):L.initialize_state(p,{'key':'123@demo'})
        self.assertEqual((p/'bridge-token.txt').read_text(),'private-test-value')
    def test_existing_identity_and_history_are_preserved(self):
        p=L.resolve_runtime(self.root).state_dir
        L.initialize_state(p,{'key':'123@demo'})
        before={n:(p/n).read_bytes() for n in ('bridge-token.txt','recovery-install.json','campaign.sqlite3')}
        self.assertEqual(L.state_mode(p),'EXISTING')
        with self.assertRaises((RuntimeError,FileExistsError)):L.initialize_state(p,{'key':'456@demo'})
        self.assertEqual(before,{n:(p/n).read_bytes() for n in before})
    def test_independent_program_copies_use_same_state_path(self):
        a=L.resolve_runtime(self.root)
        b=self.base/'another';(b/'Runtime').mkdir(parents=True);(b/'Runtime/python.exe').write_bytes(b'x')
        (b/'mt5_bridge/event_core').mkdir(parents=True);(b/'mt5_bridge/event_core/__init__.py').write_text('')
        self.assertEqual(a.state_dir,L.resolve_runtime(b).state_dir)
    def test_first_launch_requires_flat_account_but_existing_state_does_not(self):
        for positions,orders in (([{}],[]),([],[{}])):
            with self.assertRaises(RuntimeError):L.validate_account(self.account(),positions,orders,True)
            L.validate_account(self.account(),positions,orders,False)
    def account(self,**changes):
        d=dict(login=123,server='demo',trade_mode=0,margin_mode=2,currency='USD');d.update(changes)
        return SimpleNamespace(**d)
    def test_live_netting_foreign_currency_and_unknown_state_remain_blocked(self):
        for a in (self.account(trade_mode=2),self.account(margin_mode=0),self.account(currency='EUR')):
            with self.assertRaises(RuntimeError):L.validate_account(a,[],[],True)
        with self.assertRaises(RuntimeError):L.validate_account(self.account(),None,[],True)
    def test_source_hash_tampering_is_detected(self):
        import hashlib
        p=self.root/'mt5_bridge'/'x.py';p.write_text('original')
        (self.root/'PROGRAM_MANIFEST.json').write_text(json.dumps({'files':{'mt5_bridge/x.py':hashlib.sha256(p.read_bytes()).hexdigest()}}))
        L.verify_package(self.root)
        p.write_text('altered')
        with self.assertRaises(RuntimeError):L.verify_package(self.root)

if __name__=='__main__':unittest.main()
