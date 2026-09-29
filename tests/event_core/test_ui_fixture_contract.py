"""The Android fixture must obey the same native candle clock as production MT5."""
import unittest
from unittest.mock import patch
import ui_fixture as fixture

class UiFixtureClockTests(unittest.TestCase):
    def setUp(self):
        self.now=1_800_000_137.0
        self.clock_patch=patch('ui_fixture.time.time',return_value=self.now)
        self.clock_patch.start()
        self.old_engine_clock=fixture.engine.clock
        self.old_broker_clock=fixture.broker.clock
        fixture.engine.clock=lambda:self.now
        fixture.broker.clock=lambda:self.now
        fixture.reset()
    def tearDown(self):
        fixture.engine.clock=self.old_engine_clock
        fixture.broker.clock=self.old_broker_clock
        self.clock_patch.stop()
    def test_scene_transition_keeps_native_time_slots_in_all_layers(self):
        fixture.prime_r5_market('TRIANGLE')
        for name,span in [('m1_data',60),('bar_data',300),('ctx_data',900),('h1_data',3600)]:
            self.assertTrue(all(b.time%span==0 for b in getattr(fixture.broker,name)),name)
    def test_scene_transition_passes_real_engine_history_validation(self):
        client=fixture.app.test_client()
        response=client.post('/test/r5-market',json={'family':'TRIANGLE'},
            headers={'Authorization':'Bearer ci-fixture-token-not-for-real-trading'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['forecast'].get('map_version'),3,fixture.engine.market_errors)
        self.assertFalse(fixture.engine.market_errors)
