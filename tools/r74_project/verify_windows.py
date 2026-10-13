"""Reuse all existing portable runtime safety gates against the new full project ZIP."""
from pathlib import Path

root=Path.cwd()
source=root/'tools/r74_simple/verify_windows.py'
code=source.read_text(encoding='utf-8')
replacements={
    'from check_layout import inspect':'from check_project import inspect',
    "dist/FXM1_R74_ONE_FOLDER.zip":"dist/FXM1_R74_COMPLETE_PROJECT.zip",
    "layout=inspect(ARCHIVE)":"layout=inspect(ARCHIVE,ROOT/'dist/reference/source.zip')",
    "package=extract/'FXM1_R74_READY';system=package/'system';cmd=package/'START.cmd'":"package=extract/'FX-M1-Signal';system=package;cmd=package/'START.cmd'",
    "'ONE FOLDER' in p.stdout":"'FULL PROJECT' in p.stdout",
    "ROOT/'dist/FXM1_R74_READY'":"ROOT/'dist/FX-M1-Signal'",
    "one_folder_one_start_no_nested_archives":"full_project_ready_runtime_no_nested_archives",
    "WINDOWS_ONE_FOLDER":"WINDOWS_FULL_PROJECT",
}
for before,after in replacements.items():
    assert before in code,before
    code=code.replace(before,after)
anchor="    checks['check_creates_no_state_or_credentials']=True\n"
assert code.count(anchor)==1
extra='''    # Every familiar legacy launcher must use the portable runtime, never the deleted venv.
    aliases=sorted(system.joinpath('mt5_bridge').glob('*.cmd'))+sorted(system.joinpath('mt5_bridge').glob('*.bat'))
    assert len(aliases)==9
    for alias in aliases:
        result=start(alias,'--check',base,env)
        assert 'FULL PROJECT' in result.stdout and 'AUTO OFF' in result.stdout
        assert '"ok": true' in result.stdout and 'ModuleNotFoundError' not in result.stdout
        assert 'INSTALL_R7_3' not in result.stdout
        assert not state.exists()
    checks['nine_legacy_entrypoints_use_same_bundled_runtime']=True
    relocated=base/'Другая папка ! & после переноса'
    package.rename(relocated)
    result=start(relocated/'START.cmd','--check',base,env)
    assert '"state": "NEW"' in result.stdout and not state.exists()
    relocated.rename(package)
    checks['whole_project_relocation_without_installation']=True
'''
code=code.replace(anchor,anchor+extra)
(root/'evidence').mkdir(exist_ok=True)
(root/'evidence/ACTUAL_WINDOWS_TEST_RUNNER.py').write_text(code,encoding='utf-8')
exec(compile(code,str(source),'exec'),{'__name__':'__main__','__file__':str(source)})
