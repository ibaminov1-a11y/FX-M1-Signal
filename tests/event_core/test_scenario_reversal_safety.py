"""Exercise the real Engine lifecycle; FakeBroker never connects to MT5."""
import copy
import tempfile
import unittest
import uuid
from pathlib import Path

from event_core.compute_core import ComputeCore
from event_core.engine import Engine
from event_core.model import Config, Decision
from event_core.store import Store
from event_core.strategy import Strategy
from fakes import FakeBroker

NOW = 1_800_000_000.0


class ClosingBroker(FakeBroker):
    close_mode = 'FILLED'
    positions_fail = False

    def positions(self):
        if self.positions_fail:
            raise ValueError('positions_get unavailable')
        return super().positions()

    def close_position(self, p):
        if self.close_mode == 'RAISE':
            raise TimeoutError('close transport lost')
        if self.close_mode == 'REJECTED':
            return dict(status='REJECTED', reason='temporarily rejected')
        if self.close_mode == 'UNKNOWN':
            return dict(status='UNKNOWN', reason='response lost')
        if self.close_mode == 'PARTIAL':
            partial = dict(p, volume=p['volume'] / 2)
            result = super().close_position(partial)
            self._positions.append(dict(p, volume=p['volume'] - partial['volume']))
            return result  # A positive response does not prove the full position closed.
        return super().close_position(p)


class ScenarioReversalSafetyTests(unittest.TestCase):
    def setUp(self):
        self.now = [NOW]
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / 'state.sqlite3')
        self.broker = ClosingBroker(lambda: self.now[0])
        self.engine = Engine(self.broker, self.store, lambda: self.now[0])
        e = self.engine
        e.config = Config(timeframe='M5', mode='NORMAL', engine_mode='COMPUTE_V1',
                          risk_pct=.25, fee_per_lot=0, lot_cap=.01,
                          probe_lot_cap=.01, approved=True, cooldown_sec=600)
        e.strategy = Strategy(e.config)
        e.compute = ComputeCore(e.config)
        e._refresh(self.now[0])
        e.info = self.broker.symbol('EUR/USD')
        e.quote = self.broker.quote('EURUSD')
        d = Decision('BUY', 'ENTRY_READY', 'initial buy', 'initial-buy', 1,
                     self.broker.bid - .0004, self.broker.bid - .00001,
                     self.broker.bid - .0004, .0005, int(self.now[0] * 1000),
                     path='COMPUTE', entry_class='PROBE',
                     forecast={'snapshot_marker': {'value': 7}})
        self.initial_decision = d
        e._entry(d, self.now[0])
        e.campaign['confirmed'] = True
        e.auto = True
        e.paused = False
        self.signal = self.sell()
        e.compute.evaluate = lambda *a, **k: self.signal

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def sell(self, event='confirmed-sell'):
        return Decision('SELL', 'ENTRY_READY', 'confirmed opposite sell', event, -1,
                        self.broker.ask + .0004, self.broker.bid + .00001,
                        self.broker.ask + .0004, .0005, int(self.now[0] * 1000),
                        path='COMPUTE', entry_class='PROBE',
                        forecast={'side': -1, 'confidence': .72, 'edge_strength': .57,
                                  'up_probability': .15, 'down_probability': .72,
                                  'range_probability': .13, 'engine': 'COMPUTE_V1'})

    def wait(self):
        return Decision(reason='independent opposite entry not confirmed', path='COMPUTE',
                        forecast={'side': 0, 'confidence': .4, 'engine': 'COMPUTE_V1'})

    def tick(self, seconds=1.2):
        self.now[0] += seconds
        return self.engine.step()

    def test_repeated_opposite_signal_never_renews_reversal_deadline(self):
        self.broker.close_mode = 'REJECTED'
        self.engine.step()
        first = copy.deepcopy(self.engine.pending_reversal)
        self.assertIsNotNone(first)
        self.tick(3)
        self.assertEqual(self.engine.pending_reversal['expires'], first['expires'])
        self.assertEqual(self.engine.pending_reversal['created'], first['created'])

    def test_expired_intent_is_not_rearmed_while_old_position_is_closing(self):
        self.broker.close_mode = 'REJECTED'
        self.engine.step()
        self.tick(21)
        self.assertTrue(self.engine.exit_pending)
        self.assertIsNone(self.engine.pending_reversal)
        self.assertEqual(len(self.broker.sent), 1)

    def test_pause_cannot_be_undone_by_an_opposite_signal_during_closing(self):
        self.broker.close_mode = 'REJECTED'
        self.engine.step()
        self.engine.command('pause', {'command_id': str(uuid.uuid4())})
        self.tick(3)
        self.assertTrue(self.engine.paused)
        self.assertIsNone(self.engine.pending_reversal)
        self.assertEqual(len(self.broker.sent), 1)

    def test_partial_close_is_not_flat_even_when_response_says_filled(self):
        self.broker.close_mode = 'PARTIAL'
        self.engine.step()
        self.tick(1.2)
        self.assertEqual(len(self.broker.sent), 1)
        self.assertTrue(self.broker._positions)
        self.assertIsNotNone(self.engine.campaign)
        self.broker.close_mode = 'FILLED'
        self.tick(1.2)
        self.tick(1.2)
        self.assertFalse(self.broker._positions)
        self.tick(.2)
        self.assertEqual(len(self.broker.sent), 2, self.engine.execution)
        self.assertEqual(self.broker._positions[0]['side'], -1)

    def test_missing_position_read_never_opens_reverse_or_keeps_intent(self):
        self.engine.step()
        self.broker.positions_fail = True
        self.tick()
        self.assertEqual(len(self.broker.sent), 1)
        self.assertIsNone(self.engine.pending_reversal)

    def test_unknown_close_enters_recovery_without_reversal(self):
        self.broker.close_mode = 'UNKNOWN'
        self.engine.step()
        self.tick()
        self.assertTrue(self.engine.recovery)
        self.assertFalse(self.engine.auto)
        self.assertIsNone(self.engine.pending_reversal)
        self.assertEqual(len(self.broker.sent), 1)

    def test_invalidation_closes_without_waiting_for_sell_and_can_wait_for_fresh_sell(self):
        self.signal = self.wait()
        self.broker.bid = self.engine.campaign['invalidation'] - .00002
        self.broker.ask = self.broker.bid + .00001
        self.engine.step()
        self.assertEqual(len(self.broker.closed), 1)
        self.assertEqual(len(self.broker.sent), 1)
        self.assertIsNotNone(self.engine.pending_reversal)
        self.assertFalse(self.engine.pending_reversal['confirmed'])
        self.tick()
        self.assertIsNone(self.engine.campaign)
        self.signal = self.sell('sell-after-independent-invalidation')
        self.tick(.2)
        self.assertEqual(len(self.broker.sent), 2, self.engine.execution)
        self.assertEqual(self.broker._positions[0]['side'], -1)

    def test_first_exit_cause_survives_history_reconciliation(self):
        self.engine.step()
        self.tick()
        records = [e['body'] for e in self.store.events() if e['kind'] == 'CAMPAIGN_CLOSED']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].get('exit_code'), 'OPPOSITE_CONFIRMED')
        self.assertIn('SELL', records[0].get('exit_reason', ''))
        self.assertNotIn('ожидаем завершения', records[0].get('exit_reason', ''))

    def test_entry_forecast_is_frozen_not_aliased_to_live_forecast(self):
        self.initial_decision.forecast['snapshot_marker']['value'] = 99
        frozen = self.engine.campaign.get('forecast_at_entry', {})
        self.assertEqual(frozen.get('snapshot_marker', {}).get('value'), 7)

    def test_lost_sell_during_close_cancels_exceptional_cooldown_bypass(self):
        self.broker.close_mode = 'REJECTED'
        self.engine.step()
        self.signal = self.wait()
        self.tick(1)
        self.assertIsNone(self.engine.pending_reversal)
        self.broker.close_mode = 'FILLED'
        self.signal = self.sell()
        self.tick(2)
        self.tick(1.2)
        self.tick(.2)
        self.assertEqual(len(self.broker.sent), 1)

    def test_restart_does_not_restore_intent_or_auto(self):
        self.broker.close_mode = 'REJECTED'
        self.engine.step()
        restarted = Engine(self.broker, self.store, lambda: self.now[0])
        self.assertIsNone(restarted.pending_reversal)
        self.assertFalse(restarted.auto)
        self.assertTrue(restarted.paused)
        self.assertTrue(restarted.exit_pending)

    def test_stale_quote_cancels_reverse_without_opening(self):
        self.engine.step()
        self.broker.quote_age = 30
        self.tick()
        self.assertEqual(len(self.broker.sent), 1)
        self.assertIsNone(self.engine.pending_reversal)

    def test_close_transport_exception_during_retry_cancels_reverse_and_requires_recovery(self):
        self.broker.close_mode = 'REJECTED'
        self.engine.step()
        self.broker.close_mode = 'RAISE'
        self.tick(3)
        self.assertIsNone(self.engine.pending_reversal)
        self.assertTrue(self.engine.recovery)
        self.assertFalse(self.engine.auto)
        self.assertEqual(len(self.broker.sent), 1)

    def test_slow_preflight_cannot_outlive_reversal_deadline(self):
        self.engine.step()
        self.tick()
        original = self.broker.calc_margin
        def slow_margin(*args):
            self.now[0] += 21
            return original(*args)
        self.broker.calc_margin = slow_margin
        self.tick(.2)
        self.assertEqual(len(self.broker.sent), 1)
        self.assertIsNone(self.engine.pending_reversal)
