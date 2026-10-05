import importlib.util,json,tempfile,unittest,zipfile,hashlib
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
class ReadyArchiveTests(unittest.TestCase):
 def module(self):
  self.assertIsNotNone(importlib.util.find_spec('package_r732'),'R732_PACKAGER_MISSING')
  import package_r732
  return package_r732
 def test_full_runtime_has_no_state_or_old_installers(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'bridge.zip';proof=m.package_bridge(ROOT,out,'a'*40)
   with zipfile.ZipFile(out) as z:
    names=z.namelist();self.assertTrue(any(n.endswith('/event_core/scenarios/pattern_view.py') for n in names))
    self.assertTrue(any(n.endswith('/ready_launcher.py') for n in names));self.assertTrue(any(n.endswith('/START_BRIDGE_V10_0.bat') for n in names))
    self.assertFalse(any('/event_state/' in n or '/.venv/' in n or '/__pycache__/' in n or n.endswith('.pyc') or n.endswith('.jks') for n in names))
    self.assertEqual(z.read('mt5_bridge_R732/START_BRIDGE_V10_0.bat'),(ROOT/'mt5_bridge/READY_BRIDGE_R732.cmd').read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))
    build=json.loads(z.read('mt5_bridge_R732/BUILD.json'));self.assertEqual(build['source_sha'],'a'*40)
    for name,digest in build['program_sha256'].items():self.assertEqual(hashlib.sha256(z.read('mt5_bridge_R732/'+name)).hexdigest(),digest)
   self.assertEqual(proof['sha256'],hashlib.sha256(out.read_bytes()).hexdigest())
 def test_altered_archived_runtime_is_rejected(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'bridge.zip';m.package_bridge(ROOT,out,'a'*40)
   with zipfile.ZipFile(out) as z:files={n:z.read(n) for n in z.namelist()}
   files['mt5_bridge_R732/event_core/__init__.py']+=b'\nBAD=True\n'
   with zipfile.ZipFile(out,'w') as z:
    for n,b in files.items():z.writestr(n,b)
   with self.assertRaises(ValueError):m.verify_bridge(out,'a'*40)
 def test_wrong_source_and_extra_state_are_rejected(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'bridge.zip';m.package_bridge(ROOT,out,'a'*40)
   with self.assertRaises(ValueError):m.verify_bridge(out,'b'*40)
   with zipfile.ZipFile(out,'a') as z:z.writestr('mt5_bridge_R732/event_state/bridge-token.txt','not-a-user-key')
   with self.assertRaises(ValueError):m.verify_bridge(out,'a'*40)
if __name__=='__main__':unittest.main()
