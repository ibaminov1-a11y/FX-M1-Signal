from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]

class R72SimpleRuntimeContractTests(unittest.TestCase):
    def test_launcher_uses_normal_python_environment_without_vendor_path(self):
        src=(ROOT/'mt5_bridge/bridge_v10_0.py').read_text(encoding='utf-8')
        self.assertNotIn('_vendor',src)
        self.assertNotIn('sys.path.insert',src)
        self.assertIn('from event_core.server import main',src)

    def test_colorama_is_an_explicit_environment_dependency(self):
        req=(ROOT/'mt5_bridge/requirements_event.txt').read_text(encoding='utf-8')
        self.assertIn('colorama==0.4.6',req)

    def test_updater_does_not_rename_live_program_directories(self):
        src=(ROOT/'tools/r7_updater.py').read_text(encoding='utf-8')
        self.assertNotIn('os.replace(',src)
        self.assertIn('repair_colorama',src)

    def test_release_package_does_not_ship_runtime_vendor_tree(self):
        src=(ROOT/'tools/package_r7.py').read_text(encoding='utf-8')
        self.assertNotIn("vendor=bridge/'_vendor'",src)
        self.assertNotIn("dst=vendor/",src)
        self.assertIn("runtime_vendor=False",src)
        self.assertIn("package/'Dependencies'",src)

if __name__=='__main__':unittest.main()
