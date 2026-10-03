from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile, hashlib, sqlite3, json, sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from r7_updater import apply_update

class R71CleanDeliveryContract(unittest.TestCase):
    def test_launcher_uses_existing_environment_and_never_mentions_vendor(self):
        src=(ROOT/'mt5_bridge/bridge_v10_0.py').read_text(encoding='utf-8')
        self.assertIn('from event_core.server import main',src)
        self.assertNotIn('_vendor',src)
        self.assertNotIn('_prepare_http_stack',src)

    def test_packager_does_not_bundle_vendor_dependencies(self):
        src=(ROOT/'tools/package_r7.py').read_text(encoding='utf-8')
        self.assertNotIn("vendor=bridge/'_vendor'",src)
        self.assertNotIn("importlib.metadata",src)

    def test_updater_does_not_require_directory_rename(self):
        with tempfile.TemporaryDirectory(prefix='r71 copy delivery ') as td:
            root=Path(td);src=root/'src';dst=root/'dst';src.mkdir();dst.mkdir()
            files={
                'event_core/__init__.py':b"VERSION='10.9-EC1'\nBUILD='10.9-EC1-R7.1'\nREVISION='R7.1-DEMO'\nPROTOCOL='fxm1.event.v1'\n",
                'event_core/server.py':b'# clean server\n',
                'bridge_v10_0.py':b'from event_core.server import main\n',
                'START_BRIDGE_V10_0.bat':b'@echo off\r\n'
            }
            for name,data in files.items():
                p=src/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            manifest={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
            (dst/'event_core').mkdir();(dst/'event_core/__init__.py').write_text("VERSION='BROKEN'\n")
            (dst/'event_core/server.py').write_text('# old\n');(dst/'bridge_v10_0.py').write_text('# old\n')
            (dst/'event_state').mkdir()
            db=sqlite3.connect(dst/'event_state/campaign.sqlite3')
            db.executescript('CREATE TABLE state(k TEXT PRIMARY KEY,value TEXT);CREATE TABLE intents(id TEXT,status TEXT,body TEXT);')
            db.commit();db.close()
            # Reproduce OneDrive/Windows refusing directory rename. File-copy delivery must not need os.replace at all.
            with patch('r7_updater.os.replace',side_effect=PermissionError(5,'Access denied')):
                apply_update(src,dst,manifest)
            for name,data in files.items():
                self.assertEqual((dst/name).read_bytes(),data)

if __name__=='__main__':unittest.main()
