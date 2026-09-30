"""Release installer checks run against the generated, executable program."""
import base64
import importlib.util
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('make_bridge_installer_r57', ROOT / 'tools/make_bridge_installer.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class R57InstallerTests(unittest.TestCase):
    def make_bridge(self, root):
        bridge = root / 'new'
        (bridge / 'event_core/scenarios').mkdir(parents=True)
        files = {
            'event_core/__init__.py': "BUILD='10.9-EC1-R5.7'\n",
            'event_core/server.py': 'value=57\n',
            'event_core/scenarios/__init__.py': '',
            'event_core/scenarios/scalp.py': 'engine="SCALP_MICRO_V1"\n',
            'bridge_v10_0.py': 'from event_core.server import value\n',
            'START_BRIDGE_V10_0.bat': '@echo off\r\n',
        }
        for name, data in files.items():
            (bridge / name).write_text(data)
        return bridge, files

    def program(self, output):
        encoded = output.read_text(encoding='ascii').split('::FXM1_PAYLOAD_BEGIN::', 2)[-1]
        return zlib.decompress(base64.b64decode(encoded)).decode()

    def test_mismatched_bridge_build_is_rejected_before_installer_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge, _ = self.make_bridge(root)
            output = root / 'INSTALL_BRIDGE_R57.cmd'
            with self.assertRaisesRegex(ValueError, 'build'):
                installer.build_installer(bridge, output, '10.9-EC1-R5.6')
            self.assertFalse(output.exists())

    def test_current_release_diagnostic_names_the_delivered_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge, _ = self.make_bridge(root)
            output = root / 'INSTALL_BRIDGE_R57.cmd'
            installer.build_installer(bridge, output, '10.9-EC1-R5.7')
            attempt = subprocess.run([sys.executable, '-c', self.program(output)], cwd=root, capture_output=True, text=True)
            self.assertEqual(attempt.returncode, 2, attempt.stderr)
            self.assertIn('INSTALL_BRIDGE_R57.cmd', attempt.stdout)
            self.assertFalse(list(root.glob('bridge_program_backup_*')))

    def test_repair_installs_exact_program_and_preserves_saved_data_and_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bridge, files = self.make_bridge(root)
            working = root / 'working'
            for folder in ('event_core', 'event_state', '.venv', 'state'):
                (working / folder).mkdir(parents=True)
            (working / 'event_core/server.py').write_text('old=56\n')
            (working / 'event_core/obsolete.py').write_text('old=56\n')
            (working / 'bridge_v10_0.py').write_text('old=56\n')
            sentinels = {'event_state/broker-clock.json': 'confirmed clock',
                         'event_state/ledger.db': 'saved deals',
                         '.venv/sentinel': 'existing environment',
                         'state/settings.json': 'saved settings',
                         'broker-clock.json': 'legacy clock',
                         'research_config.json': 'custom research settings'}
            for name, data in sentinels.items():
                (working / name).write_text(data)
            output = root / 'INSTALL_BRIDGE_R57.cmd'
            installer.build_installer(bridge, output, '10.9-EC1-R5.7')
            repair = subprocess.run([sys.executable, '-c', self.program(output)], cwd=working, capture_output=True, text=True)
            self.assertEqual(repair.returncode, 0, repair.stderr)
            self.assertIn('OK: 10.9-EC1-R5.7 installed.', repair.stdout)
            for name in files:
                self.assertEqual((working / name).read_bytes(), (bridge / name).read_bytes())
            for name, data in sentinels.items():
                self.assertEqual((working / name).read_text(), data)
            self.assertFalse((working / 'event_core/obsolete.py').exists())
            backups = list(working.glob('bridge_program_backup_*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / 'event_core/obsolete.py').read_text(), 'old=56\n')


class R57AuditReportTests(unittest.TestCase):
    def audit(self):
        path = ROOT / 'tools/audit57_report.py'
        self.assertTrue(path.is_file(), 'R5.7 evidence validator is not implemented')
        spec = importlib.util.spec_from_file_location('audit57_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def evidence(self, root, python_result='OK', case_status=''):
        (root / 'evidence').mkdir()
        (root / 'evidence/python-tests.log').write_text('Ran 7 tests in 0.123s\n\n' + python_result + '\n')
        results = root / 'app/build/outputs/androidTest-results/connected/debug'
        results.mkdir(parents=True)
        (results / 'TEST-fixture.xml').write_text('<testsuite tests="2"><testcase classname="example.R57ScalpUiTest" name="buy"/>'
                '<testcase classname="example.R57ScalpUiTest" name="sell">' + case_status + '</testcase></testsuite>')

    def test_counts_come_from_log_and_executed_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.evidence(root)
            result = self.audit().read_results(root, required_classes=('R57ScalpUiTest',))
            self.assertEqual(result['python_tests'], 7)
            self.assertEqual(result['android_tests'], 2)
            self.assertEqual([row['name'] for row in result['android_cases']], ['buy', 'sell'])

    def test_python_failure_cannot_be_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.evidence(root, python_result='FAILED (failures=1)')
            with self.assertRaisesRegex(ValueError, 'Python'):
                self.audit().read_results(root)

    def test_android_skipped_or_failed_cases_block_release(self):
        for status in ('<failure message="bad"/>', '<error/>', '<skipped/>'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.evidence(root, case_status=status)
                with self.assertRaisesRegex(ValueError, 'Android'):
                    self.audit().read_results(root)

    def test_missing_required_native_class_blocks_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.evidence(root)
            with self.assertRaisesRegex(ValueError, 'Missing Android'):
                self.audit().read_results(root, required_classes=('R56TimeframesUiTest',))
