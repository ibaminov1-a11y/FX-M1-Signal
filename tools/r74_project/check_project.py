"""Inspect shipped bytes: full project layout, existing source, and self-contained runtime."""
from pathlib import PurePosixPath, Path
import hashlib, json, sys, zipfile, lzma

SOURCE_SHA='796c54d93f212aa9424670c72aac5d56bbae1081'
APK_SHA='9cb2b370b8bc1a13c49b2c7b4da87aaf39a84e96da1231ff7b1f2cfcf8a0381d'
REQUIRED={'.ci','.github','app','docs','mt5_bridge','tests','tools'}
ARCHIVES={'.zip','.7z','.rar','.whl','.tar','.gz','.bz2','.xz'}

def inspect(path, source_zip=None):
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if not n.endswith('/')]
        roots={n.split('/')[0] for n in names}
        root=next(iter(roots)) if len(roots)==1 else ''
        files={n[len(root)+1:]:z.read(n) for n in names} if root else {}
        top={n.split('/')[0] for n in files}
        checks={
            'one_project_root':root=='FX-M1-Signal',
            'full_source_directories':REQUIRED <= top,
            'top_level_runtime': 'Runtime/python.exe' in files and 'restore_launcher.py' in files,
            'single_main_start': 'START.cmd' in files and b'system\\' not in files.get('START.cmd',b''),
            'ready_apk': hashlib.sha256(files.get('FXM1_R7_4.apk',b'')).hexdigest()==APK_SHA,
            'gradle_and_existing_helpers':all(n in files for n in ('build.gradle','settings.gradle','gradle.properties','BUILD_APK_V10_SDK.py','APPLY_V10_NORMAL_ONLY.py','README_RU.md')),
            'no_nested_archives':not any(PurePosixPath(n).suffix.lower() in ARCHIVES for n in files),
            'no_font_files':not any(PurePosixPath(n).suffix.lower() in {'.ttf','.otf','.woff','.woff2'} for n in files),
            'no_user_identity':not any(PurePosixPath(n).name in {'bridge-token.txt','campaign.sqlite3','recovery-install.json'} or '.venv' in PurePosixPath(n).parts or 'event_state' in PurePosixPath(n).parts for n in files),
            'zip_crc':z.testzip() is None,
        }
        source_equal=0; forwarded=[]; missing=[]; changed=[]
        if source_zip:
            with zipfile.ZipFile(source_zip) as s:
                assert s.comment.decode()==SOURCE_SHA
                for info in s.infolist():
                    if info.is_dir():continue
                    n=info.filename; data=s.read(n)
                    if n.startswith('tools/r5delta/part') and n.endswith('.xz'):
                        continue
                    if n=='tools/apply_r5_delta.py':
                        if files.get('docs/original_launchers/'+n+'.txt')!=data or b'transport.json' not in files.get(n,b''):
                            changed.append(n)
                        continue
                    if n not in files:missing.append(n);continue
                    if n.endswith(('.cmd','.bat')):
                        if files.get('docs/original_launchers/'+n+'.txt')!=data:changed.append(n)
                        if b'Runtime\\python.exe' not in files[n] or b'restore_launcher.py' not in files[n] or b'DisableDelayedExpansion' not in files[n]:changed.append(n)
                        forwarded.append(n)
                    elif files[n]!=data:changed.append(n)
                    else:source_equal+=1
                payload=lzma.decompress(b''.join(s.read(f'tools/r5delta/part{i:02d}.xz') for i in range(9)))
            checks['legacy_transport_unpacked']=files.get('tools/r5delta/transport.json')==payload
            checks['all_source_components_preserved']=not missing and not changed
        try:
            manifest=json.loads(files['PROGRAM_MANIFEST.json'])
            bad=[n for n,h in manifest['files'].items() if n not in files or hashlib.sha256(files[n]).hexdigest()!=h]
            checks['integrity_manifest']=bool(manifest['files']) and not bad and manifest['repository_sha']==SOURCE_SHA
        except (KeyError,ValueError,TypeError):checks['integrity_manifest']=False
        return dict(ok=all(checks.values()),checks=checks,root=root,top_level=sorted(top),files=len(files),source_files_identical=source_equal,forwarded_launchers=forwarded,missing_source=missing,changed_source=changed,sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())

if __name__=='__main__':
    r=inspect(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None)
    print(json.dumps(r,ensure_ascii=False,indent=2));sys.exit(0 if r['ok'] else 1)
