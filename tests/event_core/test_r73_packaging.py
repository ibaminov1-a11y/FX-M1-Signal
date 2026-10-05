"""Release gates must reject missing native evidence rather than package optimistically."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import package_r7


class ReleaseEvidenceTests(unittest.TestCase):
    def test_old_windows_pass_does_not_certify_fresh_install_or_diagnostics(self):
        self.assertTrue(hasattr(package_r7, 'validate_windows_evidence'))
        old = dict(ok=True, platform='win32', commit='abc', cmd_install=True,
                   broken_colorama_repaired=True, mixed_event_core_replaced=True, installed_help=True)
        with self.assertRaisesRegex(RuntimeError, 'fresh_environment'):
            package_r7.validate_windows_evidence(old, 'abc')

    def test_every_new_windows_gate_and_exact_commit_are_required(self):
        self.assertTrue(hasattr(package_r7, 'validate_windows_evidence'))
        valid = dict(ok=True, platform='win32', commit='abc', cmd_install=True,
                     broken_colorama_repaired=True, mixed_event_core_replaced=True, installed_help=True,
                     fresh_environment=True, installed_launcher_check=True, read_only_diagnostics=True)
        package_r7.validate_windows_evidence(valid, 'abc')
        for field in ('fresh_environment', 'installed_launcher_check', 'read_only_diagnostics'):
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, field):
                package_r7.validate_windows_evidence(dict(valid, **{field: False}), 'abc')
        with self.assertRaisesRegex(RuntimeError, 'commit'):
            package_r7.validate_windows_evidence(valid, 'different-commit')

    def test_no_screenshots_cannot_be_claimed_as_visual_evidence(self):
        self.assertTrue(hasattr(package_r7, 'collect_r73_screenshots'))
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, 'screenshot|PNG'):
                package_r7.collect_r73_screenshots(Path(folder))

    def test_invalid_png_cannot_be_packaged_as_visual_evidence(self):
        self.assertTrue(hasattr(package_r7, 'collect_r73_screenshots'))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'r73-chart-broker-position.png').write_text('not a PNG')
            with self.assertRaisesRegex(RuntimeError, 'PNG'):
                package_r7.collect_r73_screenshots(root)

    def test_complete_native_chart_matrix_is_collected(self):
        self.assertTrue(hasattr(package_r7, 'collect_r73_screenshots'))
        names = ['r73-chart-broker-position.png', 'r73-chart-two-scenarios.png']
        names += ['r73-chart-frame-' + frame + '.png' for frame in
                  ('m1', 'm5', 'm15', 'm30', 'h1', 'h4', 'd1', 'w1', 'mn1')]
        names += ['r73-chart-' + symbol + '-' + width + '.png'
                  for symbol in ('eurusd', 'usdjpy', 'xauusd', 'btcusd') for width in ('320', '360')]
        names += ['r73-chart-' + state + '.png' for state in ('history_only', 'stale', 'archive', 'client_offline')]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # Header fixture: native rendering itself is covered by Android instrumentation.
            header = b'\x89PNG\r\n\x1a\n' + struct.pack('>I4sII', 13, b'IHDR', 320, 220)
            for name in names:
                (root / name).write_bytes(header + b'\x00' * 1100)
            collected = package_r7.collect_r73_screenshots(root)
            self.assertEqual({p.name for p in collected}, set(names))


if __name__ == '__main__':
    unittest.main()
