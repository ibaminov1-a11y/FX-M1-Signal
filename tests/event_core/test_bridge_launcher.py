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
            td = Path(td);target = td / 'bridge_v10_0.py';shutil.copy2(source,target)
            good = td / 'goodsite'
            (good/'colorama').mkdir(parents=True);(good/'colorama/__init__.py').write_text("AnsiToWin32=object\n",encoding='utf-8')
            (good/'flask').mkdir(parents=True);(good/'flask/__init__.py').write_text(
                "import colorama\nclass Flask: pass\ndef jsonify(*a,**k): return None\nrequest=object()\n",encoding='utf-8')
            broken = td / '_vendor' / 'flask';broken.mkdir(parents=True)
            (broken/'__init__.py').write_text("raise RuntimeError('BROKEN_VENDOR_SHADOW')\n",encoding='utf-8')
            env=os.environ.copy();env['PYTHONPATH']=str(good)+os.pathsep+str(root/'mt5_bridge')
            code=("import runpy; "+f"runpy.run_path({str(target)!r}, run_name='ec1_launcher_import_test'); "+"print('IMPORT_OK')")
            result=subprocess.run([sys.executable,'-c',code],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode,0,result.stdout);self.assertIn('IMPORT_OK',result.stdout)

    def test_broken_installed_colorama_falls_back_to_complete_vendor_stack(self):
        root = Path(__file__).resolve().parents[2]
        source = root / 'mt5_bridge' / 'bridge_v10_0.py'
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            target = td / 'bridge_v10_0.py'
            shutil.copy2(source, target)
            badsite = td / 'badsite'
            (badsite / 'colorama').mkdir(parents=True)
            (badsite / 'colorama' / '__init__.py').write_text("BROKEN=True\n", encoding='utf-8')
            (badsite / 'flask').mkdir(parents=True)
            (badsite / 'flask' / '__init__.py').write_text(
                "import colorama\nassert hasattr(colorama,'AnsiToWin32'),'BROKEN_INSTALLED_COLORAMA'\n"
                "class Flask: pass\ndef jsonify(*a,**k): return None\nrequest=object()\n", encoding='utf-8')
            vendor = td / '_vendor'
            (vendor / 'colorama').mkdir(parents=True)
            (vendor / 'colorama' / '__init__.py').write_text("AnsiToWin32=object\n", encoding='utf-8')
            (vendor / 'flask').mkdir(parents=True)
            (vendor / 'flask' / '__init__.py').write_text(
                "import colorama\nassert hasattr(colorama,'AnsiToWin32')\n"
                "class Flask: pass\ndef jsonify(*a,**k): return None\nrequest=object()\n", encoding='utf-8')
            env = os.environ.copy()
            env['PYTHONPATH'] = str(badsite) + os.pathsep + str(root / 'mt5_bridge')
            code = (
                "import runpy; "
                f"runpy.run_path({str(target)!r}, run_name='ec1_launcher_import_test'); "
                "import colorama; print('COLORAMA_OK',hasattr(colorama,'AnsiToWin32'))"
            )
            result = subprocess.run([sys.executable, '-c', code], env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn('COLORAMA_OK True', result.stdout)


if __name__ == '__main__':
    unittest.main()
