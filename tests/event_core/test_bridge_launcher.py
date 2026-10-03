import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

class BridgeLauncherTests(unittest.TestCase):
    def test_launcher_uses_only_normal_import_path(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'mt5_bridge/bridge_v10_0.py').read_text(encoding='utf-8')
        self.assertNotIn('_vendor',source)
        self.assertNotIn('sys.path.insert',source)
        self.assertIn('from event_core.server import main',source)

    def test_launcher_imports_event_core_from_python_environment(self):
        root=Path(__file__).resolve().parents[2]
        source=root/'mt5_bridge/bridge_v10_0.py'
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);target=td/'bridge_v10_0.py';shutil.copy2(source,target)
            fake=td/'site';(fake/'event_core').mkdir(parents=True)
            (fake/'event_core/__init__.py').write_text("VERSION='test'\n",encoding='utf-8')
            (fake/'event_core/server.py').write_text("def main(): pass\n",encoding='utf-8')
            env=os.environ.copy();env['PYTHONPATH']=str(fake)
            code=f"import runpy; runpy.run_path({str(target)!r}, run_name='ec1_launcher_import_test'); print('IMPORT_OK')"
            result=subprocess.run([sys.executable,'-c',code],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertIn('IMPORT_OK',result.stdout)

if __name__=='__main__':unittest.main()
