"""START.cmd of the distributed archive; no terminal connections or orders."""
from pathlib import Path
import importlib.util,hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile
spec=importlib.util.spec_from_file_location('old_native_helpers',Path(__file__).resolve().parents[1]/'r74_stdlib_repair/verify_windows.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
sha=lambda b:hashlib.sha256(b).hexdigest()
checks={}
def main():
 stage,filename=sys.argv[1:];archive=Path(filename).resolve();evidence=Path('evidence');evidence.mkdir(exist_ok=True)
 assert sys.platform=='win32'
 with tempfile.TemporaryDirectory(prefix='R74-code-') as tmp:
  base=Path(tmp);dest=base/'Полная папка ! & (тест)';dest.mkdir()
  env=dict(os.environ,R7_NO_PAUSE='1',LOCALAPPDATA=str(base/'local data'),PYTHONHOME='wrong-old-python',PYTHONPATH='wrong-old-venv',PATH=str(Path(os.environ['SystemRoot'])/'System32'))
  ps=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
  command="Expand-Archive -LiteralPath '"+str(archive).replace("'","''")+"' -DestinationPath '"+str(dest).replace("'","''")+"'"
  p=subprocess.run([ps,'-NoProfile','-NonInteractive','-Command',command],capture_output=True,timeout=100)
  assert p.returncode==0,(p.stdout,p.stderr)
  root=dest/'FX-M1-Signal';state=base/'local data/FXM1/R74-Recovery/event_state'
  m=json.loads((root/'PROGRAM_MANIFEST.json').read_text(encoding='utf-8'));saved={}
  def damage(n,data=None):
   path=root/n;saved.setdefault(n,path.read_bytes())
   if data is None:path.unlink()
   else:path.write_bytes(data)
   return path
  def restore():
   for n,b in saved.items():
    path=root/n;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b)
   saved.clear()
  def launch():return helper.run_cmd(root,env)
  def ok(p):helper.require_ok(p)
  def verified():
   for n,h in m['files'].items():assert sha((root/n).read_bytes())==h,n
  init='mt5_bridge/event_core/__init__.py';abc='Runtime/Lib/abc.pyc'
  verified();ok(launch());assert not state.exists()
  checks['expand_archive_and_unmodified_start']=True
  original=(root/init).read_bytes();damage(init,original.replace(b'R7.4',b'R7.4.1-rc1'));damage(abc)
  p=launch()
  if stage=='red':
   assert p.returncode!=0 and 'mt5_bridge/event_core/__init__.py' in p.stdout,p.stdout
   assert 'RUNTIME_LIBRARY_RESTORED 1' in p.stdout,p.stdout
   assert (root/init).read_bytes()!=original
   (evidence/'RED.json').write_text(json.dumps(dict(expected_failure=True,calls=helper.CALLS),ensure_ascii=False,indent=2),encoding='utf-8')
   print('EXPECTED_ORIGINAL_INIT_FAILURE');return
  assert stage=='green'
  ok(p);assert (root/init).read_bytes()==original
  assert 'RUNTIME_LIBRARY_RESTORED 1' in p.stdout and 'PACKAGE_CODE_RESTORED 1' in p.stdout
  checks['screenshot_sequence_stdlib_then_wrong_bridge_recovered']=True
  report=json.loads((root/'PACKAGE_CHECK.json').read_text(encoding='utf-8'))
  r=next(r for r in report['repairs'] if r['path']==init)
  assert r['reason']=='HASH_MISMATCH' and (root/r['backup']).read_bytes()==original.replace(b'R7.4',b'R7.4.1-rc1')
  checks['old_modified_code_preserved_and_reason_recorded']=True
  restore();damage(init);ok(launch());assert (root/init).read_bytes()==original
  checks['missing_init_recovered_before_resolve_runtime']=True
  restore();damage(init,original.replace(b'\n',b'\r\n'));ok(launch());assert (root/init).read_bytes()==original
  checks['newline_changed_source_restored_exactly']=True
  restore()
  source_names=[n for n in m['files'] if n.endswith('.py') and (n.startswith('mt5_bridge/') or n.startswith('Runtime/Lib/site-packages/'))]
  pyc_names=[n for n in m['files'] if n.startswith('Runtime/Lib/') and n.endswith('.pyc') and '/site-packages/' not in n]
  assert len(source_names)==589 and len(pyc_names)==533
  for n in source_names+pyc_names:damage(n)
  p=launch();ok(p)
  assert 'PACKAGE_CODE_RESTORED 589' in p.stdout and 'RUNTIME_LIBRARY_RESTORED 533' in p.stdout
  verified();checks['all_589_sources_and_533_stdlib_files_recovered_together']=True;restore()
  for alias in sorted((root/'mt5_bridge').glob('*.cmd'))+sorted((root/'mt5_bridge').glob('*.bat')):
   damage(init);ok(helper.run_cmd(root,env,alias=alias.relative_to(root).as_posix()));assert (root/init).read_bytes()==original;restore()
  checks['all_nine_existing_launcher_aliases_use_same_recovery']=True
  reserve='Runtime/program_recovery.json';damage(reserve,b'{}');damage(init)
  p=launch();assert p.returncode!=0 and 'RESERVE_CHECKSUM' in p.stdout and not (root/init).exists();restore()
  checks['modified_reserve_refused_before_any_source_write']=True
  damage(reserve);damage(init);p=launch();assert p.returncode!=0 and 'RESERVE_MISSING' in p.stdout and not (root/init).exists();restore()
  checks['missing_reserve_refused']=True
  native=next(n for n in m['files'] if 'MetaTrader5/' in n and n.endswith('.pyd'))
  damage(native,b'blocked-native-library');damage('FXM1_R7_4.apk',b'changed-apk');damage(init)
  p=launch();assert p.returncode!=0 and 'UNREPAIRABLE' in p.stdout
  report=json.loads((root/'PACKAGE_CHECK.json').read_text(encoding='utf-8'))
  assert {r['path'] for r in report['unrepairable']}=={native,'FXM1_R7_4.apk'}
  assert (root/native).read_bytes()==b'blocked-native-library' and not (root/init).exists();restore()
  checks['all_unrecoverable_files_reported_and_native_code_not_recreated']=True
  moved=base/'Перенесено ! & (R74)';root.rename(moved);root=moved;damage(init);ok(launch());restore()
  checks['moving_folder_needs_no_installation']=True
  assert not state.exists();state.mkdir(parents=True);token=state/'bridge-token.txt';token.write_bytes(b'CI-incomplete-key-must-not-change')
  damage(init);p=launch();assert p.returncode!=0 and 'состояние неполное' in p.stdout
  assert token.read_bytes()==b'CI-incomplete-key-must-not-change' and not (state/'campaign.sqlite3').exists()
  checks['incomplete_local_state_and_key_not_recreated']=True;restore()
  original_dir=root/'mt5_bridge/event_core';external=base/'external-code';original_dir.rename(external)
  proc=subprocess.run([os.environ['COMSPEC'],'/d','/c','mklink','/J',str(original_dir),str(external)],capture_output=True)
  assert proc.returncode==0,(proc.stdout,proc.stderr)
  try:
   before={p.relative_to(external).as_posix():sha(p.read_bytes()) for p in external.rglob('*') if p.is_file()}
   p=launch();assert p.returncode!=0 and 'LINK_NOT_ALLOWED' in p.stdout,p.stdout
   after={p.relative_to(external).as_posix():sha(p.read_bytes()) for p in external.rglob('*') if p.is_file()}
   assert before==after
  finally:os.rmdir(original_dir);external.rename(original_dir)
  checks['junction_not_followed_and_external_files_unchanged']=True
  verified();checks['every_manifest_hash_matches_after_all_tests']=True
 result=dict(ok=True,checks=checks,count=len(checks),calls=helper.CALLS,live_mt5=False,orders_sent=0,archive_sha256=sha(archive.read_bytes()))
 (evidence/'WINDOWS_SOURCE_RECOVERY.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print('WINDOWS_SOURCE_RECOVERY_OK',len(checks))
if __name__=='__main__':main()
