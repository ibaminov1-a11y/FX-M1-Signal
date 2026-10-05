"""R7.3 startup/install regressions; never connects to MT5 or sends orders."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import r7_updater as updater


class R73InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='R73 OneDrive путь spaces ! ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.package = self.root / 'package'
        self.source = self.package / 'Bridge'
        self.target = self.root / 'existing bridge'
        self.source.mkdir(parents=True)
        self.target.mkdir()
        self.files = {
            'event_core/__init__.py': b"BUILD='test'; VERSION='test'; REVISION='test'\n",
            'event_core/server.py': b'# harmless server fixture\n',
            'bridge_v10_0.py': b'# harmless entry fixture\n',
            'bridge_startup.py': b'# startup fixture\n',
            'START_BRIDGE_V10_0.bat': b'@echo off\r\n',
            'requirements_event.txt': b'Flask==3.1.2\nMetaTrader5>=5.0.45,<6\ncolorama==0.4.6\n',
        }
        for name, data in self.files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.manifest = {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()}
        (self.package / 'BRIDGE_MANIFEST.json').write_text(json.dumps(self.manifest))
        dep = self.package / 'Dependencies/colorama/__init__.py'
        dep.parent.mkdir(parents=True)
        dep.write_text("AnsiToWin32=object\n__version__='0.4.6'\n")
        (self.package / 'DEPENDENCY_MANIFEST.json').write_text(json.dumps({
            'colorama/__init__.py': hashlib.sha256(dep.read_bytes()).hexdigest()}))
        (self.target / 'bridge_v10_0.py').write_text('# original entry\n')
        (self.target / 'event_state').mkdir()
        (self.target / 'event_state/bridge-token.txt').write_text('SECRET-must-not-be-logged-' * 3)
        (self.target / 'broker-clock.json').write_text('{"offset":10800}')
        self.python = self.target / '.venv/Scripts/python.exe'
        self.python.parent.mkdir(parents=True)
        self.python.write_bytes(b'not a real executable')
        self.colorama = self.target / '.venv/Lib/site-packages/colorama/__init__.py'
        self.colorama.parent.mkdir(parents=True)
        self.colorama.write_text('BROKEN=True\n')

    def main(self):
        with patch.object(updater, '__file__', str(self.package / 'update_bridge.py')):
            with patch.object(sys, 'argv', ['update_bridge.py', str(self.target), '--yes']):
                updater.main()

    def test_running_bridge_blocks_before_dependency_mutation(self):
        before = self.colorama.read_bytes()
        lock = updater.Lock(self.target / 'event_state/runtime.lock')
        self.addCleanup(lock.close)
        # Only the external interpreter is replaced; real files/locks/update order run.
        with patch.object(updater.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'COLORAMA OK\n')):
            with self.assertRaisesRegex(RuntimeError, 'Bridge'):
                self.main()
        self.assertEqual(self.colorama.read_bytes(), before,
                         'Running Bridge must not have its installed dependencies replaced')

    def test_live_campaign_blocks_before_dependency_mutation(self):
        with sqlite3.connect(self.target / 'event_state/campaign.sqlite3') as db:
            db.execute('CREATE TABLE state(k TEXT PRIMARY KEY,value TEXT)')
            db.execute('INSERT INTO state VALUES (?, ?)', ('profile:a:engine', json.dumps({'campaign': {'id': 'live'}})))
        before = self.colorama.read_bytes()
        with patch.object(updater.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'COLORAMA OK\n')):
            with self.assertRaisesRegex(RuntimeError, 'campaign'):
                self.main()
        self.assertEqual(self.colorama.read_bytes(), before,
                         'An active campaign must be rejected before any environment changes')

    def test_postflight_cannot_claim_success_without_a_python_environment(self):
        self.python.unlink()
        with self.assertRaisesRegex(RuntimeError, 'Python|environment|venv'):
            updater.postflight(self.target)

    def test_unmanifested_program_file_is_not_installed(self):
        (self.source / 'event_core/unverified.py').write_text('raise RuntimeError("unverified")\n')
        with self.assertRaisesRegex(RuntimeError, 'manifest|payload'):
            updater.apply_update(self.source, self.target, self.manifest)
        self.assertEqual((self.target / 'bridge_v10_0.py').read_text(), '# original entry\n')

    def test_existing_environment_reports_wrong_python_architecture(self):
        result = subprocess.CompletedProcess([], 0, '{"version":[3,12,1],"bits":32,"platform":"win32"}')
        with patch.object(updater.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, '64.bit'):
                updater.postflight(self.target)

    def test_empty_venv_is_never_silently_replaced(self):
        self.python.unlink()
        before = self.colorama.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'venv|environment'):
            self.main()
        self.assertEqual(self.colorama.read_bytes(), before)
        self.assertEqual((self.target / 'bridge_v10_0.py').read_text(), '# original entry\n',
                         'Broken environment must be rejected before replacing program files')

    def test_dependency_failure_is_actionable_and_does_not_log_pip_credentials(self):
        # Simulate only external interpreter/pip processes, with a secret-bearing failure.
        self.assertTrue(hasattr(updater, 'ensure_dependencies'), 'Fresh installations must provision dependencies')
        responses = [subprocess.CompletedProcess([], 0, '{"flask":"ModuleNotFoundError","MetaTrader5":"ModuleNotFoundError","colorama":"OK"}'),
                     subprocess.CompletedProcess([], 1, 'https://user:PRIVATE-PIP-TOKEN@example.invalid/')]
        output = io.StringIO()
        with patch.object(updater.subprocess, 'run', side_effect=responses), contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError, 'dependenc|requirements|network') as failure:
                updater.ensure_dependencies(self.source, self.target)
        self.assertNotIn('PRIVATE-PIP-TOKEN', output.getvalue() + str(failure.exception))

    def test_fresh_environment_is_created_and_checked(self):
        self.assertTrue(hasattr(updater, 'prepare_environment'), 'Fresh installations must create a venv')
        fresh = self.root / 'fresh target'
        fresh.mkdir()
        def interpreter(command, **kwargs):
            if '-m' in command and 'venv' in command:
                exe = fresh / '.venv/Scripts/python.exe'
                exe.parent.mkdir(parents=True)
                exe.write_bytes(b'new environment fixture')
                return subprocess.CompletedProcess(command, 0, '')
            return subprocess.CompletedProcess(command, 0, '{"version":[3,12,1],"bits":64,"platform":"win32"}')
        with patch.object(updater.subprocess, 'run', side_effect=interpreter):
            result = updater.prepare_environment(fresh)
        self.assertEqual(result, fresh / '.venv/Scripts/python.exe')
        self.assertTrue(result.is_file())

    def test_dependency_payload_rejects_unverified_extra_file(self):
        extra = self.package / 'Dependencies/colorama/unverified.py'
        extra.write_text('raise RuntimeError("unverified")\n')
        before = self.colorama.read_bytes()
        with patch.object(updater.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'COLORAMA OK')):
            with self.assertRaisesRegex(RuntimeError, 'manifest|payload'):
                updater.repair_colorama(self.package, self.target)
        self.assertEqual(self.colorama.read_bytes(), before)

    def test_failed_fresh_install_can_be_retried_without_deleting_environment(self):
        import shutil
        shutil.rmtree(self.target)
        self.target.mkdir()
        def dependency_process(command, **kwargs):
            if '-m' in command and 'venv' in command:
                self.python.parent.mkdir(parents=True)
                self.python.write_bytes(b'fixture')
                self.colorama.parent.mkdir(parents=True)
                return subprocess.CompletedProcess(command, 0, '')
            if 'bits' in command[-1]:
                return subprocess.CompletedProcess(command, 0, '{"version":[3,12,1],"bits":64,"platform":"win32"}')
            if 'COLORAMA OK' in command[-1]:
                return subprocess.CompletedProcess(command, 0, 'COLORAMA OK')
            if 'pip' in command:
                return subprocess.CompletedProcess(command, 1, 'PRIVATE-PIP-TOKEN')
            return subprocess.CompletedProcess(command, 0, '{"flask":"ModuleNotFoundError","MetaTrader5":"ModuleNotFoundError","colorama":"OK"}')
        with patch.object(updater.subprocess, 'run', side_effect=dependency_process):
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, 'Dependency installation failed'):
                    self.main()
        self.assertEqual(self.python.read_bytes(), b'fixture')
        self.assertNotIn('PRIVATE-PIP-TOKEN', (self.target / 'r73-install.log').read_text())

    def test_postflight_failure_restores_program_while_install_lock_is_held(self):
        def interpreter(command, **kwargs):
            if 'bits' in command[-1]:
                return subprocess.CompletedProcess(command, 0, '{"version":[3,12,1],"bits":64,"platform":"win32"}')
            if 'COLORAMA OK' in command[-1]:
                return subprocess.CompletedProcess(command, 0, 'COLORAMA OK')
            return subprocess.CompletedProcess(command, 0, '{"flask":"OK","MetaTrader5":"OK","colorama":"OK"}')
        def failing_postflight(target):
            with self.assertRaisesRegex(RuntimeError, 'Bridge'):
                updater.Lock(target / 'event_state/runtime.lock')
            raise RuntimeError('Injected import failure')
        with patch.object(updater.subprocess, 'run', side_effect=interpreter):
            with patch.object(updater, 'postflight', side_effect=failing_postflight):
                with self.assertRaisesRegex(RuntimeError, 'Injected import failure'):
                    self.main()
        self.assertEqual((self.target / 'bridge_v10_0.py').read_text(), '# original entry\n')

    def test_backup_metadata_write_failure_restores_previous_program(self):
        real = Path.write_text
        def fail_metadata(path, *args, **kwargs):
            if path.name == 'ROLLBACK.json':
                raise OSError('injected full disk')
            return real(path, *args, **kwargs)
        with patch.object(Path, 'write_text', fail_metadata):
            with self.assertRaisesRegex(OSError, 'full disk'):
                updater.apply_update(self.source, self.target, self.manifest)
        self.assertEqual((self.target / 'bridge_v10_0.py').read_text(), '# original entry\n')

    def test_broken_python_is_not_misreported_as_wrong_architecture(self):
        with patch.object(updater.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '')):
            with self.assertRaisesRegex(RuntimeError, 'cannot run|could not run'):
                updater.postflight(self.target)

    def test_bad_dependency_manifest_is_rejected_before_fresh_environment_is_created(self):
        import shutil
        shutil.rmtree(self.target)
        self.target.mkdir()
        (self.package / 'Dependencies/colorama/extra.py').write_text('# unverified\n')
        def interpreter(command, **kwargs):
            if '-m' in command and 'venv' in command:
                self.python.parent.mkdir(parents=True)
                self.python.write_bytes(b'fixture')
                self.colorama.parent.mkdir(parents=True)
            return subprocess.CompletedProcess(command, 0, '{"version":[3,12,1],"bits":64,"platform":"win32"}')
        with patch.object(updater.subprocess, 'run', side_effect=interpreter):
            with self.assertRaisesRegex(RuntimeError, 'manifest|payload'):
                self.main()
        self.assertFalse((self.target / '.venv').exists())

    def test_release_without_startup_helper_is_rejected_before_environment_repair(self):
        (self.source / 'bridge_startup.py').unlink()
        del self.manifest['bridge_startup.py']
        (self.package / 'BRIDGE_MANIFEST.json').write_text(json.dumps(self.manifest))
        with patch.object(updater.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"version":[3,12,1],"bits":64,"platform":"win32"}')):
            with self.assertRaisesRegex(RuntimeError, 'startup'):
                self.main()
        self.assertEqual(self.colorama.read_text(), 'BROKEN=True\n')


class R73StartupTests(unittest.TestCase):
    def setUp(self):
        # Importing through the file also works before the helper has been packaged.
        self.path = ROOT / 'mt5_bridge/bridge_startup.py'
        self.assertTrue(self.path.is_file(), 'Windows launcher needs a testable stdlib startup/diagnostics helper')
        import bridge_startup
        self.startup = bridge_startup

    def test_dependency_error_does_not_include_secret_text(self):
        with patch.object(self.startup.importlib, 'import_module', side_effect=ImportError('Bearer TOP-SECRET')):
            report = self.startup.environment_report()
        serialized = json.dumps(report)
        self.assertNotIn('TOP-SECRET', serialized)
        self.assertIn('ImportError', serialized)
        self.assertFalse(report['ok'])

    def test_diagnosis_detects_local_listener_without_touching_trading_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / 'event_state'
            state.mkdir()
            secret = state / 'bridge-token.txt'
            secret.write_text('secret-cannot-appear-in-diagnosis')
            db = state / 'campaign.sqlite3'
            db.write_bytes(b'diagnostic must not open even an invalid database')
            listener = socket.socket()
            self.addCleanup(listener.close)
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            before = {p.name: p.read_bytes() for p in state.iterdir()}
            report = self.startup.network_report(state, listener.getsockname()[1])
            self.assertTrue(report['localhost_reachable'])
            self.assertEqual(before, {p.name: p.read_bytes() for p in state.iterdir()})
            self.assertNotIn('secret-cannot-appear-in-diagnosis', json.dumps(report))

    def test_runtime_exit_code_is_preserved_and_failure_is_logged_without_stdout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'bridge_v10_0.py').write_text("print('console-only-user-token'); raise SystemExit(23)\n")
            result = self.startup.launch(root, [], root / 'event_state')
            self.assertEqual(result, 23)
            log = (root / 'event_state/bridge-startup.log').read_text(encoding='utf-8')
            self.assertIn('23', log)
            self.assertNotIn('console-only-user-token', log)


@unittest.skipUnless(sys.platform == 'win32', 'Requires native cmd.exe and Windows venv')
class R73NativeLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='R73 OneDrive путь spaces ! ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        import shutil
        shutil.copy2(ROOT / 'mt5_bridge/START_BRIDGE_V10_0.bat', self.root)
        subprocess.run([sys.executable, '-m', 'venv', str(self.root / '.venv')], check=True, timeout=120)
        self.env = dict(os.environ, R7_NO_PAUSE='1', PYTHONUTF8='1')

    def test_batch_uses_venv_keeps_unicode_arguments_and_propagates_exit_code(self):
        (self.root / 'bridge_startup.py').write_text(
            "import json,sys\nfrom pathlib import Path\n"
            "Path('observed.json').write_text(json.dumps(dict(python=sys.executable,args=sys.argv[1:])))\n"
            "raise SystemExit(23)\n", encoding='utf-8')
        result = subprocess.run(['cmd.exe', '/d', '/c', 'call', str(self.root / 'START_BRIDGE_V10_0.bat'),
                                 '--state-dir', str(self.root / 'state путь !')],
                                env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        actual = json.loads((self.root / 'observed.json').read_text())
        self.assertEqual(Path(actual['python']).resolve(), (self.root / '.venv/Scripts/python.exe').resolve())
        self.assertEqual(actual['args'], ['--state-dir', str(self.root / 'state путь !')])


if __name__ == '__main__':
    unittest.main()
