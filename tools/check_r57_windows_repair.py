"""Run the delivered CMD in Windows against the screenshot's broken package.

No terminal, broker credentials, account data or trading API is used.
"""
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import venv

from make_bridge_installer import build_installer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'mt5_bridge'


def run():
    if sys.platform != 'win32':
        raise SystemExit('This gate requires real Windows cmd.exe')
    evidence = ROOT / 'evidence/windows-repair'
    evidence.mkdir(parents=True, exist_ok=True)
    installer = evidence / 'REPAIR_BRIDGE_R57.cmd'
    build_installer(SOURCE, installer, '10.9-EC1-R5.7')
    expected = {p.relative_to(SOURCE).as_posix(): p.read_bytes()
                for p in (list((SOURCE / 'event_core').rglob('*.py')) +
                          [SOURCE / 'bridge_v10_0.py', SOURCE / 'START_BRIDGE_V10_0.bat'])}
    env = dict(os.environ, PYTHONUTF8='1')
    env.pop('PYTHONPATH', None)
    cases = []
    with tempfile.TemporaryDirectory(prefix='fxm1_windows_') as tmp:
        base = Path(tmp)
        for mode in ('path_python', 'venv_python'):
            working = base / ('Тест Bridge (R57) ' + mode)
            shutil.copytree(SOURCE, working, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            interpreter = Path(sys.executable)
            if mode == 'venv_python':
                venv.EnvBuilder(system_site_packages=True, with_pip=False).create(working / '.venv')
                interpreter = working / '.venv/Scripts/python.exe'
            sentinels = {'event_state/campaign.sqlite3': b'original trade history',
                         'event_state/broker-clock.json': b'original account-bound clock',
                         'event_state/bridge-token.txt': b'original private token',
                         'broker-clock.json': b'legacy clock',
                         'research_config.json': b'original user settings',
                         '.venv/preserved.txt': b'original environment'}
            for name, data in sentinels.items():
                path = working / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            # Keep a stale cache alongside an empty initializer, as may happen
            # with partial copies. First prove the exact reported import failure.
            py_compile.compile(str(working / 'event_core/__init__.py'), doraise=True)
            (working / 'event_core/__init__.py').write_bytes(b'')
            before = subprocess.run([str(interpreter), 'bridge_v10_0.py', '--help'],
                                    cwd=working, env=env, capture_output=True, timeout=30)
            assert before.returncode != 0 and b"cannot import name 'VERSION'" in before.stderr, before.stderr
            (evidence / (mode + '-before.log')).write_bytes(before.stdout + before.stderr)
            target = working / installer.name
            shutil.copyfile(installer, target)
            repaired = subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'call', str(target)],
                                      cwd=base, env=env, input=b'\r\n' * 5, capture_output=True, timeout=60)
            (evidence / (mode + '-repair.log')).write_bytes(repaired.stdout + repaired.stderr)
            assert repaired.returncode == 0, (repaired.returncode, repaired.stdout, repaired.stderr)
            assert b'SERVER_IMPORT_OK' in repaired.stdout, repaired.stdout
            for name, data in expected.items():
                assert (working / name).read_bytes() == data, name
            for name, data in sentinels.items():
                assert (working / name).read_bytes() == data, 'Changed user data: ' + name
            backups = list(working.glob('bridge_program_backup_*'))
            assert len(backups) == 1 and (backups[0] / 'event_core/__init__.py').read_bytes() == b''
            after = subprocess.run([str(interpreter), 'bridge_v10_0.py', '--help'],
                                   cwd=working, env=env, capture_output=True, timeout=30)
            (evidence / (mode + '-after.log')).write_bytes(after.stdout + after.stderr)
            assert after.returncode == 0 and b'--state-dir' in after.stdout, (after.stdout, after.stderr)
            cases.append(dict(case=mode, reproduced_import_error=True, windows_cmd_exit=0,
                              server_and_launcher_imported=True, launcher_help_exit=0,
                              program_files_verified=len(expected), saved_data_preserved=True,
                              broken_program_backed_up=True))
        wrong = base / 'wrong folder'
        wrong.mkdir()
        target = wrong / installer.name
        shutil.copyfile(installer, target)
        rejected = subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'call', str(target)],
                                  cwd=base, env=env, input=b'\r\n' * 5, capture_output=True, timeout=30)
        (evidence / 'wrong-folder.log').write_bytes(rejected.stdout + rejected.stderr)
        assert rejected.returncode != 0 and b'working mt5_bridge folder' in rejected.stdout
        assert sorted(p.name for p in wrong.iterdir()) == [installer.name]
        cases.append(dict(case='wrong_folder', rejected=True, no_program_written=True))
    result = dict(platform=sys.platform, python=sys.version, cases=cases,
                  installer_sha256=hashlib.sha256(installer.read_bytes()).hexdigest(),
                  commit=os.environ.get('GITHUB_SHA'),
                  limitations='No live MT5 connection or trading; Android unchanged and not rerun.')
    (evidence / 'WINDOWS_REPAIR_RESULTS.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run()
