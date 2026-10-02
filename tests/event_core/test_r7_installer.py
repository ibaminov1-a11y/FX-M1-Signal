"""Runs on Linux AND native Windows. No user data, terminal or credentials."""
import hashlib,json,os,subprocess,sys,tempfile,unittest,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from r7_updater import apply_update,rollback,Lock

class InstallerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='r7 Unicode путь ');self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.src=self.root/'package';self.dst=self.root/'old bridge';self.src.mkdir();self.dst.mkdir()
  self.files={'event_core/__init__.py':b"BUILD='test-r7'\n",'event_core/server.py':b'# new server\n','bridge_v10_0.py':b'# entry\n','START_BRIDGE_V10_0.bat':b'@echo off\r\n'}
  for n,b in self.files.items():
   p=self.src/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
  self.manifest={n:hashlib.sha256(b).hexdigest() for n,b in self.files.items()}
  (self.dst/'event_core').mkdir();(self.dst/'event_core/server.py').write_text('# old server\n')
  (self.dst/'bridge_v10_0.py').write_text('# old entry\n')
  (self.dst/'event_state').mkdir();(self.dst/'event_state/bridge-token.txt').write_text('test-secret-not-real')
  (self.dst/'.venv').mkdir();(self.dst/'.venv/keep').write_text('environment')
  db=sqlite3.connect(self.dst/'event_state/campaign.sqlite3');db.executescript('CREATE TABLE state(k TEXT PRIMARY KEY,value TEXT);CREATE TABLE intents(id TEXT,status TEXT,body TEXT);');db.commit();db.close()
 def snapshot(self):return {p.relative_to(self.dst).as_posix():p.read_bytes() for d in ('event_state','.venv') for p in (self.dst/d).rglob('*') if p.is_file() and p.name!='runtime.lock'}
 def test_update_and_rollback_preserve_state_and_environment(self):
  before=self.snapshot();backup=apply_update(self.src,self.dst,self.manifest)
  for n,b in self.files.items():self.assertEqual((self.dst/n).read_bytes(),b)
  self.assertEqual(before,self.snapshot());rollback(self.dst,backup)
  self.assertEqual((self.dst/'event_core/server.py').read_text(),'# old server\n');self.assertEqual(before,self.snapshot())
 def test_running_process_lock_stops_update(self):
  lock=Lock(self.dst/'event_state/runtime.lock')
  try:
   with self.assertRaisesRegex(RuntimeError,'Bridge'):apply_update(self.src,self.dst,self.manifest)
  finally:lock.close()
 def test_active_campaign_or_unknown_order_stops_before_changes(self):
  db=sqlite3.connect(self.dst/'event_state/campaign.sqlite3');db.execute('INSERT INTO state VALUES (?,?)',('profile:x:engine',json.dumps({'campaign':{'id':'active'}})));db.commit();db.close()
  with self.assertRaisesRegex(RuntimeError,'campaign'):apply_update(self.src,self.dst,self.manifest)
  self.assertEqual((self.dst/'event_core/server.py').read_text(),'# old server\n')
 def test_invalid_payload_does_not_touch_destination(self):
  (self.src/'event_core/server.py').write_text('# corrupt')
  with self.assertRaisesRegex(RuntimeError,'checksum'):apply_update(self.src,self.dst,self.manifest)
  self.assertEqual((self.dst/'event_core/server.py').read_text(),'# old server\n')
 def test_failure_mid_update_restores_program(self):
  from unittest.mock import patch
  import r7_updater
  real=r7_updater.os.replace;count=[0]
  def fail_once(a,b):
   if 'staged' in str(a):
    count[0]+=1
    if count[0]==2:raise OSError('injected disk failure')
   return real(a,b)
  with patch.object(r7_updater.os,'replace',side_effect=fail_once):
   with self.assertRaises(OSError):apply_update(self.src,self.dst,self.manifest)
  self.assertEqual((self.dst/'event_core/server.py').read_text(),'# old server\n')
 def test_database_probe_closes_handles_and_leaves_wal_unchanged(self):
  db=sqlite3.connect(self.dst/'event_state/campaign.sqlite3');db.execute('PRAGMA journal_mode=WAL');db.execute('INSERT INTO state VALUES (?,?)',('x','{}'));db.commit()
  try:
   before=self.snapshot();apply_update(self.src,self.dst,self.manifest);self.assertEqual(before,self.snapshot())
  finally:db.close()
