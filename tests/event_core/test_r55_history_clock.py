"""Broker-stamped account history must not disappear behind the PC UTC cutoff."""
import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from event_core.model import Blocked
from event_core.mt5_adapter import MAGIC, MT5Broker
from event_core.risk import day_start, ledger, summary
from event_core.engine import Engine
from event_core.store import Store
from fakes import FakeBroker
from test_r51_repairs import NativeTerminal, TerminalBroker, NOW


class HistoryTerminal(NativeTerminal):
    def __init__(self):
        super().__init__([NOW])
        self.tick = NOW + 10800 - 2.3
        self.deals = []
        # Two real completed positions, the second stamped in broker UTC+3.
        for pid, opened, closed, profit in (
            (101, NOW - 5000, NOW - 4500, .23),
            (102, NOW + 10600, NOW + 10700, 1.27),
        ):
            for entry, timestamp, pnl in ((0, opened, 0.), (1, closed, profit)):
                self.deals.append(SimpleNamespace(ticket=pid*10+entry, order=pid,
                    time=int(timestamp), time_msc=int(timestamp*1000), type=entry,
                    entry=entry, magic=MAGIC, position_id=pid, reason=3, volume=.01,
                    price=1.137, commission=0., swap=0., profit=pnl, fee=0.,
                    symbol='EURUSD', comment='EC1 test', external_id=''))

    def history_deals_get(self, start=None, end=None, *, position=None):
        if position is not None:
            return tuple(d for d in self.deals if d.position_id == position)
        return tuple(d for d in self.deals
                     if start.timestamp() <= d.time_msc/1000 <= end.timestamp())


class CompleteNativeHistoryTests(unittest.TestCase):
    def test_completed_account_trades_survive_broker_clock_ahead_of_pc(self):
        broker = MT5Broker(HistoryTerminal())
        rows = ledger(broker.history(NOW))
        self.assertEqual([r['position_id'] for r in rows], [101, 102])
        self.assertAlmostEqual(summary(rows)['net'], 1.50)
        self.assertEqual(rows[-1]['time_msc'], int((NOW+10700)*1000))

    def test_complete_history_does_not_validate_future_tick(self):
        broker = MT5Broker(HistoryTerminal())
        broker.history(NOW)
        with patch('event_core.mt5_adapter.time.time', return_value=NOW):
            quote = broker.quote('EURUSD')
        with self.assertRaises(Blocked):
            quote.validate(NOW)

    def test_position_lookup_preserves_broker_deal_timestamps(self):
        broker = MT5Broker(HistoryTerminal())
        rows = ledger(broker.history_position(102))
        self.assertEqual(rows[0]['time_msc'], int((NOW+10700)*1000))
        self.assertAlmostEqual(rows[0]['net'], 1.27)

    def test_retrieval_keeps_prior_year_history(self):
        terminal = HistoryTerminal()
        for deal in terminal.deals[:2]:
            deal.time_msc -= 400*86400*1000
            deal.time -= 400*86400
        rows = ledger(MT5Broker(terminal).history(NOW))
        self.assertEqual([r['position_id'] for r in rows], [101, 102])
        self.assertAlmostEqual(summary(rows)['net'], 1.50)

    def test_position_reconciliation_deduplicates_expanded_account_history(self):
        broker = FakeBroker(lambda: NOW)
        native = MT5Broker(HistoryTerminal())
        broker.history = native.history
        broker.history_position = native.history_position
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'state.sqlite3')
            try:
                engine = Engine(broker, store, lambda: NOW)
                engine.campaign_history_cache = {d['ticket']: d for d in native.history_position(102)}
                engine._refresh(NOW)
                self.assertEqual(len(engine.deals), 4)
                self.assertEqual(len(engine.rows), 2)
                self.assertAlmostEqual(summary(engine.rows)['net'], 1.50)
            finally:
                store.close()


class ConfiguredClockTests(unittest.TestCase):
    def terminal(self):
        terminal = HistoryTerminal()
        terminal.login = 123
        terminal.account_info = lambda: SimpleNamespace(login=terminal.login, server='DemoBroker')
        terminal.positions_get = lambda: [SimpleNamespace(ticket=102, identifier=102,
            magic=MAGIC, symbol='EURUSD', type=0, volume=.01, price_open=1.137,
            price_current=1.137, sl=1.13, tp=0., profit=0., swap=0.,
            time=int(NOW+10600), comment='EC1 test')]
        terminal.POSITION_TYPE_BUY = 0
        return terminal

    def broker(self, terminal):
        return MT5Broker(terminal, clock_account='123@DemoBroker', clock_offset_minutes=180)

    def test_explicit_clock_requires_two_fresh_ticks_and_preserves_raw_diagnostics(self):
        terminal = self.terminal(); broker = self.broker(terminal)
        with patch('event_core.mt5_adapter.time.time', return_value=NOW):
            first = broker.quote('EURUSD')
            with self.assertRaises(Blocked): first.validate(NOW)
            terminal.tick += .2
            second = broker.quote('EURUSD')
            second.validate(NOW)
        self.assertEqual(second.time_msc, int(terminal.tick*1000)-10800000)
        diag = broker.quote_diagnostics('EURUSD')
        self.assertEqual(diag['raw_tick_time_msc'], int(terminal.tick*1000))
        self.assertEqual(diag['offset_minutes'], 180)

    def test_every_timestamp_uses_the_same_explicit_policy(self):
        terminal = self.terminal(); broker = self.broker(terminal)
        with patch('event_core.mt5_adapter.time.time', return_value=NOW):
            bars = broker.bars('EURUSD', 'M5', 3)
            live = broker.current_bar('EURUSD', 'M5')
            chart = broker.chart_snapshot('EURUSD', 'M5', 3)
        self.assertEqual(live.time, int(NOW)-300)
        self.assertEqual(bars[-1].time, int(NOW)-300)
        self.assertEqual(chart['live_bar'].time, live.time)
        self.assertEqual(broker.history(NOW)[-1]['time_msc'], int((NOW-100)*1000))
        self.assertEqual(broker.history_position(102)[-1]['raw_time_msc'], int((NOW+10700)*1000))
        self.assertEqual(broker.positions()[0]['time'], int(NOW-200))
        self.assertEqual(broker.positions()[0]['raw_time'], int(NOW+10600))
        self.assertNotEqual(broker.clock_identity(), MT5Broker(terminal).clock_identity())

    def test_account_switch_rejects_every_corrected_data_path(self):
        terminal = self.terminal(); broker = self.broker(terminal)
        terminal.login = 456
        operations = [lambda: broker.quote('EURUSD'), lambda: broker.bars('EURUSD', 'M5'),
            lambda: broker.current_bar('EURUSD', 'M5'), lambda: broker.chart_snapshot('EURUSD', 'M5'),
            lambda: broker.history(NOW), lambda: broker.history_position(102), broker.positions]
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(Blocked): operation()

    def test_nonzero_offset_without_account_binding_is_rejected(self):
        with self.assertRaises((Blocked, ValueError)):
            MT5Broker(self.terminal(), clock_offset_minutes=180)

    def test_explicit_policy_never_revives_a_stale_or_future_normalized_tick(self):
        terminal = self.terminal(); broker = self.broker(terminal)
        for age in (30., -30.):
            terminal.tick = NOW+10800-age
            with patch('event_core.mt5_adapter.time.time', return_value=NOW):
                broker.quote('EURUSD')
                terminal.tick += .2
                quote = broker.quote('EURUSD')
            with self.subTest(age=age):
                with self.assertRaises(Blocked): quote.validate(NOW)

    def test_account_switch_during_read_rejects_data(self):
        terminal = self.terminal(); broker = self.broker(terminal)
        original = terminal.symbol_info_tick
        def switching_read(symbol):
            terminal.login = 456
            return original(symbol)
        terminal.symbol_info_tick = switching_read
        with self.assertRaises(Blocked): broker.quote('EURUSD')

    def test_invalid_offsets_rejected_at_startup(self):
        for offset in (True, '180', 180.5, 841, -841):
            with self.subTest(offset=offset):
                with self.assertRaises(Blocked):
                    MT5Broker(self.terminal(), clock_account='123@DemoBroker', clock_offset_minutes=offset)

    def test_tashkent_day_uses_normalized_deal_time_at_midnight(self):
        terminal = self.terminal(); broker = self.broker(terminal)
        # 00:05 Tashkent on Sep29. Broker UTC+3 shows Sep28 22:05.
        now = datetime(2026, 9, 28, 19, 5, tzinfo=timezone.utc).timestamp()
        # Position101 closes23:59 Tashkent yesterday,102 closes00:01 today.
        for deal, minute in zip(terminal.deals, (-3, -1, 0, 1)):
            deal.time_msc = int((now-5*60+minute*60+10800)*1000)
        rows = ledger(broker.history(now))
        today = summary([r for r in rows if r['time'] >= day_start(now)])
        self.assertEqual(today['count'], 1)
        self.assertAlmostEqual(today['net'], 1.27)

    def test_broker_month_closes_at_its_calendar_boundary_after_conversion(self):
        terminal = self.terminal(); broker = self.broker(terminal)
        terminal.TIMEFRAME_MN1 = 30
        opened = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
        closed = datetime(2026, 9, 30, 21, tzinfo=timezone.utc).timestamp()
        terminal.copy_rates_from_pos = lambda *args: [dict(time=opened,
            open=1.137, high=1.138, low=1.136, close=1.137, tick_volume=8)]
        with patch('event_core.mt5_adapter.time.time', return_value=closed-2):
            with self.assertRaises(Blocked): broker.bars('EURUSD', 'MN1')
        with patch('event_core.mt5_adapter.time.time', return_value=closed):
            bars = broker.bars('EURUSD', 'MN1')
        self.assertEqual(bars[0].time, opened-10800)
        self.assertEqual(bars[0].clock_offset_seconds, 10800)


class ConfiguredForecastBroker(TerminalBroker):
    """Real timestamp adapter, account/order operations isolated from real MT5."""
    def __init__(self, now, configured):
        super().__init__(now)
        self.terminal.account_info = lambda: SimpleNamespace(login=123, server='DEMO')
        self.native = MT5Broker(self.terminal, **(
            dict(clock_account='123@DEMO', clock_offset_minutes=180) if configured else {}))

    def clock_identity(self):return self.native.clock_identity()
    def quote_diagnostics(self, symbol):return self.native.quote_diagnostics(symbol)
    def chart_snapshot(self, symbol, tf, count=1200):return self.native.chart_snapshot(symbol, tf, count)


class NativeForecastIntegrationTests(unittest.TestCase):
    def test_explicit_bound_clock_restores_real_forecast_but_default_future_feed_stays_blocked(self):
        for configured in (False, True):
            with self.subTest(configured=configured), tempfile.TemporaryDirectory() as directory:
                now = [NOW]
                broker = ConfiguredForecastBroker(now, configured)
                store = Store(Path(directory)/'forecast.sqlite3')
                try:
                    store.save('engine', {'config': {'engine_mode': 'SCENARIO_V2',
                        'timeframe': 'M5', 'approved': True, 'fee_per_lot': 0}})
                    engine = Engine(broker, store, lambda: now[0])
                    states = []
                    for delta in (0., 1.2):
                        now[0] = NOW+delta
                        broker.terminal.tick = now[0]+10800
                        with patch('event_core.mt5_adapter.time.time', return_value=now[0]), \
                             patch('event_core.mt5_adapter.time.monotonic', return_value=10+delta):
                            states.append(engine.step())
                    self.assertFalse(states[0]['quote_fresh'], 'First observation must never confirm the feed')
                    state = states[-1]
                    self.assertEqual(broker.sent, [])
                    if configured:
                        self.assertTrue(state['quote_fresh'], state.get('market_errors'))
                        self.assertEqual(engine.market_errors, [])
                        self.assertEqual(state['forecast'].get('map_version'), 3, state['forecast'])
                        self.assertTrue(state['forecast']['available'])
                        self.assertEqual(state['forecast']['history_clock'], broker.clock_identity())
                        archived = store.scenario_snapshots(engine.market_scope())
                        self.assertTrue(archived, 'Verified forecast should be archived')
                        self.assertTrue(all(row['forecast']['history_clock'] == broker.clock_identity()
                                            for row in archived))
                        self.assertGreater(len(state['bars']), 24)
                        self.assertTrue(all(b['time']+300 <= now[0]+1 for b in state['bars']))
                        cached = store.read_bars(engine.market_scope(), 'M5')
                        self.assertTrue(cached)
                        self.assertTrue(all(b['time'] <= now[0] for b in cached))
                        self.assertEqual(state['quote']['time_msc'], int(now[0]*1000))
                    else:
                        self.assertFalse(state['quote_fresh'])
                        self.assertNotEqual(state['forecast'].get('map_version'), 3)
                        self.assertTrue(any('будущего' in error for error in engine.market_errors))
                        self.assertEqual(store.read_bars(engine.market_scope(), 'M5'), [])
                finally:
                    store.close()
