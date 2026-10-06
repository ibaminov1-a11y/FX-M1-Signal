"""A test reset starts a NEW fixture session, unlike a production Bridge restart."""
import unittest
import uuid
import ui_fixture as fixture


class FixtureIsolationTests(unittest.TestCase):
    def setUp(self):
        self.client = fixture.app.test_client()
        self.headers = {'Authorization': 'Bearer ci-fixture-token-not-for-real-trading',
                        'X-FXM1-Client': 'R51', 'X-FXM1-Control': 'queued-v1'}
        self.identity = 'fixture-test-' + uuid.uuid4().hex
        fixture.reset()
        self.addCleanup(fixture.reset)
        self.inbox = fixture.app.config['command_inbox']

    def packet(self, seq=1, **extra):
        return dict(client_id=self.identity, sequence=seq,
                    command_id='fixture-packet-' + uuid.uuid4().hex,
                    account_key=fixture.engine.account['key'], **extra)

    def reset_scene(self):
        response = self.client.post('/test/reset', json={}, headers=self.headers)
        self.assertEqual(200, response.status_code, response.json)

    def test_new_fixture_session_can_restart_fixed_android_client_sequence(self):
        first = self.client.post('/ec/command/configure',
                                 json=self.packet(42, config={'mode': 'SCALP'}), headers=self.headers)
        self.assertEqual(202, first.status_code, first.json)
        self.inbox.drain()
        self.assertEqual('SCALP', fixture.engine.config.mode)
        self.reset_scene()
        second = self.client.post('/ec/command/configure',
                                  json=self.packet(1, config={'mode': 'SCALP'}), headers=self.headers)
        self.assertEqual(202, second.status_code,
                         'Fixture reset leaked previous command sequence: ' + str(second.json))
        self.inbox.drain()
        self.assertEqual('APPLIED', self.inbox.status(second.json['command_id'])['command_status'])
        self.assertEqual('SCALP', fixture.engine.config.mode)

    def test_new_fixture_session_has_no_old_durable_or_memory_stop(self):
        response = self.client.post('/ec/command/emergency', json=self.packet(), headers=self.headers)
        self.assertEqual(202, response.status_code, response.json)
        self.assertTrue(self.inbox.inhibited(''))
        self.inbox.drain()
        self.assertTrue(fixture.engine.emergency)
        self.reset_scene()
        self.assertFalse(self.inbox.inhibited(''), 'Fixture reset leaked old entry-inhibit latch')
        self.assertFalse(fixture.engine.entry_inhibited())
        self.assertFalse(fixture.engine.emergency)
        with self.inbox._db() as db:
            self.assertEqual(0, db.execute('SELECT COUNT(*) FROM inhibits').fetchone()[0])
        self.assertFalse(fixture.broker.sent)

    def test_old_fixture_pending_control_cannot_apply_in_new_scene(self):
        response = self.client.post('/ec/command/configure',
                                    json=self.packet(config={'mode': 'SCALP'}), headers=self.headers)
        self.assertEqual(202, response.status_code, response.json)
        self.assertEqual(1, self.inbox.summary()['pending'])
        self.reset_scene()
        self.assertEqual(0, self.inbox.summary()['pending'], 'Fixture reset leaked old pending work')
        self.assertEqual(0, self.inbox.drain())
        self.assertEqual('NORMAL', fixture.engine.config.mode)
        self.assertFalse(fixture.broker.sent)

if __name__ == '__main__':
    unittest.main()
