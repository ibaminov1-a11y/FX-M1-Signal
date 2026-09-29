import json
import tempfile
import unittest
from pathlib import Path
from event_core.clock_setup import load_clock_policy


class ClockSetupTests(unittest.TestCase):
    def test_absent_policy_keeps_native_utc(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_clock_policy(Path(d)), {})

    def test_explicit_policy_requires_account_and_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'broker-clock.json'
            for data in ({'offset_minutes':180}, {'account':'123@server','offset_minutes':True,'confirmed':True},
                         {'account':'123@server','offset_minutes':180,'confirmed':False}):
                p.write_text(json.dumps(data))
                with self.assertRaises(ValueError):load_clock_policy(Path(d))
            p.write_text(json.dumps({'account':'123@server','offset_minutes':180,'confirmed':True}))
            self.assertEqual(load_clock_policy(Path(d)),dict(clock_account='123@server',clock_offset_minutes=180))
