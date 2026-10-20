"""Packaging tests. No live MT5 connection or real broker orders."""
from pathlib import Path
import argparse, contextlib, hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile, types, unittest, zipfile
BASE=PATCH=BUNDLE=OUT=None

def unpack_base(where):
    with zipfile.ZipFile(BASE) as z:z.extractall(where)
    return where/'FX-M1-Signal'

def assert_product(test,root):
    with zipfile.ZipFile(PATCH) as p:
        for n in p.namelist():
            if n.startswith('mt5_bridge/') and n.endswith('.py'):
                test.assertEqual(p.read(n),(root/n).read_bytes(),n)

def red():
    with tempfile.TemporaryDirectory() as tmp:
        root=unpack_base(Path(tmp))
        with zipfile.ZipFile(PATCH) as z:
            for n in z.namelist():
                if n.startswith('mt5_bridge/'):(root/n).write_bytes(z.read(n))
        text=(root/'START.cmd').read_text(encoding='utf-8')
        src=text.split('\n#R74_PY_BEGIN\n',1)[1]
        m=types.ModuleType('folder_old_launcher');m.__file__=str(root/'START.cmd');sys.modules[m.__name__]=m
        exec(compile(src,m.__file__,'exec'),m.__dict__)
        m.verify_package(root)
        with zipfile.ZipFile(PATCH) as p:
            expect=p.read('mt5_bridge/event_core/engine.py')
            assert (root/'mt5_bridge/event_core/engine.py').read_bytes()!=expect,'RED not reproduced'
        print('RED_CONFIRMED: old root launcher restores old engine after copying only Bridge source.')

@unittest.skipUnless(os.name=='nt','Windows native launch')
class Native(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='FXM1 папка ')
        self.work=Path(self.tmp.name);self.root=unpack_base(self.work)
        with zipfile.ZipFile(BUNDLE) as z:z.extractall(self.root)
        self.local=self.work/'Local';self.state=self.local/'FXM1/R74-Recovery/event_state';self.state.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(self.state/'campaign.sqlite3')) as db:
            for t in ('state','intents','campaigns','commands'):db.execute(f'CREATE TABLE {t}(id TEXT)')
            db.commit()
        (self.state/'bridge-token.txt').write_text('fake-ci-key-preserve-never-print-0123456789')
        (self.state/'broker-clock.json').write_text('{"account":"123@DEMO","offset_minutes":180,"confirmed":true}')
        self.before={p.name:p.read_bytes() for p in self.state.iterdir()}
    def tearDown(self):self.tmp.cleanup()
    def run_start(self,args=('--check',)):
        env=dict(os.environ,LOCALAPPDATA=str(self.local),R7_NO_PAUSE='1')
        path=self.root/'mt5_bridge/START_BRIDGE_V10_0.bat'
        cmd='"'+str(path)+'" '+ ' '.join(args)
        command='"'+os.environ.get('COMSPEC','cmd.exe')+'" /d /s /c "'+cmd+'"'
        r=subprocess.run(command,env=env,cwd=self.work,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
        text=r.stdout.decode('utf-8','replace')
        (OUT/(self._testMethodName+'.log')).write_text(text,encoding='utf-8')
        self.assertNotIn('fake-ci-key',text)
        for k,v in self.before.items():self.assertEqual(v,(self.state/k).read_bytes(),k)
        return r.returncode,text
    def primary(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for p in [self.root/'START.cmd',self.root/'PROGRAM_MANIFEST.json',self.root/'Runtime/program_recovery.json']}
    def test_complete_folder_applies_support_and_launches_patched_engine(self):
        code,text=self.run_start();self.assertEqual(code,0,text);self.assertIn('ENTRY-HF1',text);self.assertIn('PACKAGE CHECK OK',text);assert_product(self,self.root)
        with zipfile.ZipFile(PATCH) as p:
            self.assertEqual(p.read('START.cmd'),(self.root/'START.cmd').read_bytes())
        hashes=self.primary();n=len(list((self.root/'mt5_bridge/_entry_hf1/backups').rglob('*.before')))
        code,text=self.run_start();self.assertEqual(code,0,text);self.assertEqual(hashes,self.primary())
        self.assertEqual(n,len(list((self.root/'mt5_bridge/_entry_hf1/backups').rglob('*.before'))))
    def test_new_source_recovery_does_not_roll_back_hf1(self):
        code,text=self.run_start();self.assertEqual(code,0,text)
        (self.root/'mt5_bridge/event_core/engine.py').write_text('broken')
        code,text=self.run_start();self.assertEqual(code,0,text);assert_product(self,self.root)
    def test_corrupt_support_refused_before_parent_changes(self):
        original=self.primary();(self.root/'mt5_bridge/_entry_hf1/Runtime/program_recovery.json').write_text('broken')
        code,text=self.run_start();self.assertNotEqual(code,0);self.assertIn('SUPPORT_HASH_MISMATCH',text);self.assertEqual(original,self.primary())
    def test_missing_runtime_refused_without_falling_back_to_system_python(self):
        original=self.primary();(self.root/'Runtime/python.exe').rename(self.root/'Runtime/python.exe.hold')
        code,text=self.run_start();self.assertNotEqual(code,0);self.assertIn('WRONG_PARENT',text);self.assertEqual(original,self.primary())
    def test_unknown_parent_version_not_overwritten(self):
        (self.root/'START.cmd').write_text('@echo different release');original=self.primary()
        code,text=self.run_start();self.assertNotEqual(code,0);self.assertIn('UNKNOWN_PARENT_VERSION',text);self.assertEqual(original,self.primary())
    def test_runtime_lock_blocks_update(self):
        import msvcrt
        lock=self.state/'runtime.lock';lock.write_bytes(b'0');original=self.primary()
        with lock.open('r+b') as stream:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            try:code,text=self.run_start()
            finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        self.assertNotEqual(code,0);self.assertIn('CLOSE_BRIDGE',text);self.assertEqual(original,self.primary())
    def test_no_uninstall_no_personal_files_in_bundle(self):
        with zipfile.ZipFile(BUNDLE) as z:
            names=z.namelist();self.assertTrue(all(n.startswith('mt5_bridge/') for n in names))
            self.assertFalse(any(n.lower().endswith(('.zip','.apk','.jks','.sqlite3','.ttf','.otf')) for n in names))
            self.assertFalse(any('bridge-token' in n or 'event_state/' in n for n in names))
            self.assertIn('mt5_bridge/event_core/engine.py',names)
        code,text=self.run_start();self.assertEqual(code,0,text);self.assertIn('old_venv_required',text)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('base');a.add_argument('patch');a.add_argument('bundle');a.add_argument('output');a.add_argument('--red',action='store_true');v=a.parse_args()
    BASE=Path(v.base);PATCH=Path(v.patch);BUNDLE=Path(v.bundle);OUT=Path(v.output);OUT.mkdir(parents=True,exist_ok=True)
    if v.red:red()
    else:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Native))
        (OUT/'RESULT.json').write_text(json.dumps(dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),ok=result.wasSuccessful()),indent=2))
        sys.exit(0 if result.wasSuccessful() else 1)
