import base64,subprocess,sys,tempfile,unittest,zlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

class InstallerTests(unittest.TestCase):
    def test_missing_package_files_are_restored_without_replacing_user_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bridge=root/'new';working=root/'working'
            for folder in (bridge/'event_core/scenarios',working/'event_core',working/'event_state',working/'.venv'):
                folder.mkdir(parents=True)
            files={'event_core/__init__.py':"BUILD='10.9-EC1-R5.6'\n",
                   'event_core/server.py':'value=56\n','event_core/scenarios/__init__.py':'',
                   'bridge_v10_0.py':'from event_core.server import value\n',
                   'START_BRIDGE_V10_0.bat':'@echo off\r\n'}
            for name,data in files.items():(bridge/name).write_text(data)
            (working/'event_core/server.py').write_text('old=55\n')
            (working/'bridge_v10_0.py').write_text('old=55\n')
            sentinels={'event_state/broker-clock.json':'confirmed clock','event_state/ledger.db':'saved deals','.venv/sentinel':'python env'}
            for name,data in sentinels.items():(working/name).write_text(data)
            output=root/'INSTALL_BRIDGE_R56.cmd'
            build=subprocess.run([sys.executable,str(ROOT/'tools/make_bridge_installer.py'),str(bridge),str(output),'10.9-EC1-R5.6'],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            encoded=output.read_text(encoding='ascii').split('::FXM1_PAYLOAD_BEGIN::',2)[-1]
            program=zlib.decompress(base64.b64decode(encoded)).decode()
            repair=subprocess.run([sys.executable,'-c',program],cwd=working,capture_output=True,text=True)
            self.assertEqual(repair.returncode,0,repair.stderr)
            for name in files:self.assertEqual((working/name).read_bytes(),(bridge/name).read_bytes())
            for name,data in sentinels.items():self.assertEqual((working/name).read_text(),data)
            backups=list(working.glob('bridge_program_backup_*'))
            self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'event_core/server.py').read_text(),'old=55\n')
            self.assertNotIn('event_state',str(list((bridge/'event_core').rglob('*'))))
