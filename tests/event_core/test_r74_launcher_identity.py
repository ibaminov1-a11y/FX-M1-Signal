"""The ready console must identify the loaded release, not a hard-coded old one."""
import io
import unittest
from unittest.mock import patch
import ready_launcher

class LauncherIdentityTests(unittest.TestCase):
    def test_ready_banner_uses_verified_runtime_build(self):
        output=io.StringIO()
        with patch.object(ready_launcher,'resolve_runtime'), \
             patch.object(ready_launcher,'check_runtime',return_value={'ok':True,'build':'10.9-EC1-R7.4'}), \
             patch.object(ready_launcher,'require_stopped'),patch('sys.stdout',output):
            self.assertEqual(ready_launcher.main(['--check']),0)
        line=output.getvalue().splitlines()[0]
        self.assertTrue(line.startswith('10.9-EC1-R7.4 READY:'),line)
        self.assertNotIn('R7.3.2',line)
if __name__=='__main__':unittest.main()
