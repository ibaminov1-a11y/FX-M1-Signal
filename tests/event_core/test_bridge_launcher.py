import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BridgeLauncherTests(unittest.TestCase):
    def test_broken_vendor_does_not_shadow_installed_flask(self):
        root = Path(__file__).resolve().parents[2]
        source = root / 'mt5_bridge' / 'bridge_v10_0.py'
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            target = td / 'bridge_v10_0.py'
            shutil.copy2(source, target)
            broken = td / '_vendor' / 'flask'
            broken.mkdir(parents=True)
            (broken / '__init__.py').write_text("raise RuntimeError('BROKEN_VENDOR_SHADOW')\n", encoding='utf-8')
            env = os.environ.copy()
            env['PYTHONPATH'] = str(root / 'mt5_bridge')
            code = (
                "import runpy; "
                f"runpy.run_path({str(target)!r}, run_name='ec1_launcher_import_test'); "
                "print('IMPORT_OK')"
            )
            result = subprocess.run([sys.executable, '-c', code], env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn('IMPORT_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
