"""Exercise exact shipped CMD on Windows; never connect to a live terminal."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile

SOURCE_HASH='c6b11cbc98db06820ab9502cbada25c2256d16788e3ccceac5a214ed39181278'
CHECKS={};CALLS=[]

def sha(data):return hashlib.sha256(data).hexdigest()

def run_cmd(root,env,args='--check',alias='START.cmd'):
    line='"'+os.environ['COMSPEC']+'" /d /s /c ""'+str(root/alias)+'" '+args+'"'
    p=subprocess.run(line,env=env,cwd=root.parent,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=100)
    CALLS.append(dict(alias=alias,args=args,exit=p.returncode,stdout=p.stdout[-7000:],stderr=p.stderr[-2500:]))
    return p

def require_ok(p):
    assert p.returncode==0,(p.returncode,p.stdout,p.stderr)
    assert '"ok": true' in p.stdout and 'AUTO OFF' in p.stdout,p.stdout
    assert 'INSTALL_R7_3' not in p.stdout

def main():
    stage,filename=sys.argv[1:]
    assert sys.platform=='win32'
    archive=Path(filename).resolve();evidence=Path('evidence');evidence.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='R74-library-') as tmp:
        base=Path(tmp);destination=base/"Полная папка ! & (тест)";destination.mkdir()
        # Use Windows' archive extraction, not only Python zipfile extraction.
        env=dict(os.environ,R7_NO_PAUSE='1',LOCALAPPDATA=str(base/'Local data'),
                 PYTHONHOME='invalid-old-python',PYTHONPATH='invalid-old-venv',
                 PATH=str(Path(os.environ['SystemRoot'])/'System32'))
        ps=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
        extraction="Expand-Archive -LiteralPath '"+str(archive).replace("'","''")+"' -DestinationPath '"+str(destination).replace("'","''")+"'"
        p=subprocess.run([ps,'-NoProfile','-NonInteractive','-Command',extraction],capture_output=True,text=True,timeout=100)
        assert p.returncode==0,(p.stdout,p.stderr)
        root=destination/'FX-M1-Signal';state=base/'Local data/FXM1/R74-Recovery/event_state'
        manifest=json.loads((root/'PROGRAM_MANIFEST.json').read_text(encoding='utf-8'))
        for name,expected in manifest['files'].items():assert sha((root/name).read_bytes())==expected,name
        CHECKS['windows_expand_archive_preserves_all_hashes']=True
        require_ok(run_cmd(root,env));assert not state.exists()
        CHECKS['intact_launch_without_old_python_or_state']=True
        abc=root/'Runtime/Lib/abc.pyc';original=abc.read_bytes();abc.unlink()
        p=run_cmd(root,env)
        if stage=='red':
            (evidence/'RED.json').write_text(json.dumps(dict(archive_sha256=sha(archive.read_bytes()),calls=CALLS),ensure_ascii=False,indent=2),encoding='utf-8')
            assert p.returncode==0,'ABC_MISSING_NOT_RECOVERED: '+p.stdout
            raise AssertionError('Original failure unexpectedly disappeared')
        assert stage=='green'
        require_ok(p);assert abc.read_bytes()==original
        assert 'RUNTIME_LIBRARY_RESTORED 1' in p.stdout,p.stdout
        CHECKS['missing_abc_restored_to_exact_original']=True
        abc.write_bytes(b'not-python-bytecode')
        require_ok(run_cmd(root,env));assert abc.read_bytes()==original
        CHECKS['changed_abc_restored_and_verified']=True
        bytecode=[n for n in manifest['files'] if n.startswith('Runtime/Lib/') and n.endswith('.pyc') and '/site-packages/' not in n]
        assert len(bytecode)>500
        for name in bytecode:(root/name).unlink()
        p=run_cmd(root,env);require_ok(p)
        assert 'RUNTIME_LIBRARY_RESTORED '+str(len(bytecode)) in p.stdout,p.stdout
        for name in bytecode:assert sha((root/name).read_bytes())==manifest['files'][name],name
        CHECKS['all_stdlib_bytecode_including_bootstrap_restored_before_python']=True
        CHECKS['no_new_keys_or_state_after_repair']=not state.exists()
        aliases=sorted((root/'mt5_bridge').glob('*.cmd'))+sorted((root/'mt5_bridge').glob('*.bat'))
        assert len(aliases)==9
        for alias in aliases:
            abc.unlink();require_ok(run_cmd(root,env,alias=alias.relative_to(root).as_posix()))
            assert abc.read_bytes()==original
        CHECKS['all_nine_legacy_aliases_repair_before_python']=True
        reserve=root/'Runtime/stdlib_recovery.json';data=reserve.read_bytes()
        abc.unlink();reserve.write_bytes(data+b' ')
        p=run_cmd(root,env);assert p.returncode!=0 and 'RESERVE_CHECKSUM_MISMATCH' in p.stdout+p.stderr
        assert not abc.exists() and not state.exists()
        reserve.write_bytes(data);require_ok(run_cmd(root,env))
        CHECKS['damaged_recovery_payload_fails_closed_before_repair']=True
        abc.unlink();backup=reserve.with_suffix('.saved');reserve.rename(backup)
        p=run_cmd(root,env);assert p.returncode!=0 and 'RESERVE_MISSING' in p.stdout+p.stderr
        assert not abc.exists();backup.rename(reserve);require_ok(run_cmd(root,env))
        CHECKS['missing_recovery_payload_fails_closed']=True
        dependency=root/'Runtime/Lib/site-packages/colorama/__init__.py';saved=dependency.read_bytes()
        dependency.write_bytes(saved+b'\n# unexpected modification\n')
        p=run_cmd(root,env);assert p.returncode!=0 and 'повреждён' in p.stdout
        assert dependency.read_bytes()!=saved
        dependency.write_bytes(saved)
        CHECKS['full_integrity_check_not_removed_and_sources_not_silently_replaced']=True
        moved=base/'Перемещенная папка ! &';root.rename(moved)
        abc=moved/'Runtime/Lib/abc.pyc';abc.unlink();require_ok(run_cmd(moved,env));assert abc.read_bytes()==original
        moved.rename(root)
        CHECKS['folder_can_move_without_installing']=True
        state.mkdir(parents=True);token=state/'bridge-token.txt'
        token.write_text('local-test-token-never-publish-as-a-real-key',encoding='utf-8');token_bytes=token.read_bytes()
        (root/'Runtime/Lib/abc.pyc').unlink();p=run_cmd(root,env)
        assert p.returncode!=0 and 'состояние неполное' in p.stdout
        assert token.read_bytes()==token_bytes and not (state/'campaign.sqlite3').exists()
        CHECKS['partial_user_state_not_replaced_or_reinitialized']=True
        for name,expected in manifest['files'].items():assert sha((root/name).read_bytes())==expected,name
        CHECKS['all_distributed_bytes_exact_after_recovery_tests']=True
    assert all(CHECKS.values()),CHECKS
    (evidence/'WINDOWS_LIBRARY_REPAIR.json').write_text(json.dumps(dict(ok=True,checks=CHECKS,calls=CALLS,
        count=len(CHECKS),stdlib_files=len(bytecode),live_mt5=False,orders_sent=0,archive_sha256=sha(archive.read_bytes())),ensure_ascii=False,indent=2),encoding='utf-8')
    print('WINDOWS_LIBRARY_REPAIR_OK',len(CHECKS))

if __name__=='__main__':main()
