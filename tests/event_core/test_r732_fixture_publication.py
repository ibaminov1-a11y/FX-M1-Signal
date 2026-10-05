"""Fixture scene publication must be coherent even while the real Engine is busy."""
import threading
import unittest
import ui_fixture as fixture


class FixturePublicationTests(unittest.TestCase):
    def setUp(self):
        self.client = fixture.app.test_client()
        self.headers = {'Authorization': 'Bearer ci-fixture-token-not-for-real-trading',
                        'X-FXM1-Client': 'R51'}
        self.client.post('/test/reset', json={}, headers=self.headers)
        self.client.get('/ec/state', headers=self.headers)

    def read_while_worker_is_busy(self):
        acquired = threading.Event()
        release = threading.Event()
        def worker():
            with fixture.engine.lock:
                acquired.set()
                release.wait(5)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.assertTrue(acquired.wait(2))
        try:
            response = self.client.get('/ec/state', headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['runtime_busy'])
            return response.json
        finally:
            release.set()
            thread.join(2)

    def test_r5_scene_publishes_before_next_nonblocking_state_read(self):
        primed = self.client.post('/test/r5-market', json={'family': 'TRIANGLE'},
                                  headers=self.headers)
        self.assertEqual(primed.status_code, 200)
        self.assertEqual(primed.json['forecast'].get('map_version'), 3)
        state = self.read_while_worker_is_busy()
        self.assertEqual(state['forecast'].get('map_version'), 3,
                         'R5 scene changed Engine but left RuntimeViews on pre-scene state')
        self.assertGreater(len(state['forecast'].get('scenarios', [])), 1)

    def test_reset_cannot_replay_previous_r5_scene_when_worker_is_busy(self):
        self.client.post('/test/r5-market', json={'family': 'TRIANGLE'}, headers=self.headers)
        before = self.client.get('/ec/state', headers=self.headers)
        self.assertEqual(before.json['forecast'].get('map_version'), 3)
        self.client.post('/test/reset', json={}, headers=self.headers)
        expected = fixture.engine.snapshot()
        state = self.read_while_worker_is_busy()
        self.assertEqual(state['config'], expected['config'])
        self.assertEqual(state['forecast'].get('map_version'),
                         expected['forecast'].get('map_version'))
        self.assertFalse(fixture.broker.sent)

if __name__ == '__main__':
    unittest.main()
