"""R5.4: a blocked clock must not erase display candles or permit trading."""
import copy
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from event_core.engine import Engine
from event_core.model import Config
from event_core.server import create_app
from event_core.store import Store
from test_r51_repairs import TerminalBroker, NOW


class DisplayTerminalBroker(TerminalBroker):
    def chart_snapshot(self, symbol, tf, count=1200):
        return self.native.chart_snapshot(symbol, tf, count)
    def quote_diagnostics(self, symbol):
        return self.native.quote_diagnostics(symbol)


class DisplayMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = [NOW]
        self.broker = DisplayTerminalBroker(self.now)
        self.broker.terminal.tick = NOW + 10797.4
        self.store = Store(Path(self.tmp.name) / 'state.db')
        self.engine = Engine(self.broker, self.store, lambda: self.now[0])
        self.engine.config = Config(engine_mode='SCENARIO_V2', approved=True, fee_per_lot=0)
        self.client = create_app(self.engine, 'test-token').test_client()
        self.headers = {'Authorization': 'Bearer test-token', 'X-FXM1-Client': 'R51'}

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def step(self, dt=0, raw=None):
        self.now[0] = NOW + dt
        if raw is not None:
            self.broker.terminal.tick = raw
        with patch('event_core.mt5_adapter.time.time', return_value=self.now[0]), \
             patch('event_core.mt5_adapter.time.monotonic', return_value=10 + dt):
            return self.engine.step()

    def test_future_tick_shows_native_candles_without_analysis_cache_or_orders(self):
        self.engine.auto = True
        self.engine.paused = False
        state = self.step()
        chart = state.get('chart_market', {})
        self.assertGreater(len(chart.get('bars', [])), 1, 'Blocked clock erased the chart')
        self.assertEqual(chart['clock'], 'MT5_RAW')
        self.assertTrue(chart['read_only'])
        self.assertEqual(chart['status'], 'UNVERIFIED_TIME')
        self.assertGreater(chart['bars'][-1]['time'], NOW)
        self.assertEqual(chart['bars'][-1]['time'] + 300, chart['live_bar']['time'])
        self.assertIn('будущего', chart['reason'])
        self.assertFalse(state['entry_allowed'])
        self.assertFalse(state['quote_fresh'])
        self.assertEqual(state['decision']['phase'], 'DATA_BLOCK')
        self.assertEqual(state['bars'], [])
        self.assertEqual(self.store.read_bars(self.engine.market_scope(), 'M5'), [])
        self.assertEqual(self.broker.sent, [])

    def test_recovered_clock_removes_preview_and_never_merges_raw_future_bars(self):
        first = self.step()
        self.assertTrue(first.get('chart_market'), 'Missing blocked clock preview')
        for dt in (1.2, 1.4, 2.6):
            state = self.step(dt, NOW + dt)
        self.assertIsNone(state.get('chart_market'))
        self.assertTrue(state['quote_fresh'])
        self.assertGreater(len(state['bars']), 1)
        self.assertLessEqual(state['bars'][-1]['time'] + 300, self.now[0] + 1)
        self.assertTrue(all(x['time'] <= self.now[0] for x in self.store.read_bars(self.engine.market_scope(), 'M5')))

    def test_preview_switches_symbol_and_never_reuses_failed_other_symbol(self):
        self.assertTrue(self.step().get('chart_market'))
        self.engine.config.symbol = 'GBP/USD'
        with patch.object(self.broker, 'chart_snapshot', side_effect=ValueError('history unavailable')):
            state = self.step(1.2)
        self.assertEqual(state.get('chart_market', {}).get('symbol'), 'GBPUSD')
        self.assertEqual(state['chart_market']['bars'], [])
        self.assertIn('history unavailable', state['chart_market']['reason'])

    def test_forced_refresh_updates_financial_snapshot_without_order_or_campaign_command(self):
        self.step()
        self.broker.balance = 54321.0
        old_campaign = copy.deepcopy(self.engine.campaign)
        self.engine.auto = True
        self.engine.paused = False
        with patch('event_core.mt5_adapter.time.time', return_value=NOW), \
             patch('event_core.mt5_adapter.time.monotonic', return_value=10):
            response = self.client.get('/ec/state?refresh=1', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        state = response.get_json()
        self.assertEqual(state['account']['balance'], 54321.0, 'Forced refresh returned old cache')
        self.assertEqual(state['refresh_time'], NOW)
        self.assertTrue(state['refresh_errors'])
        self.assertTrue(state['auto'])
        self.assertFalse(state['paused'])
        self.assertEqual(self.engine.campaign, old_campaign)
        self.assertEqual(self.broker.sent, [])
        self.assertEqual(self.broker.closed, [])

    def test_forced_refresh_reports_history_failure_and_auth_required(self):
        self.step()
        self.broker.history_failure = True
        response = self.client.get('/ec/state?refresh=1', headers=self.headers)
        state = response.get_json()
        self.assertFalse(state['history_ok'], 'Forced refresh skipped new history failure')
        self.assertTrue(any('history unavailable' in x for x in state['refresh_errors']))
        self.assertEqual(self.client.get('/ec/state?refresh=1').status_code, 401)

    def test_adapter_returns_raw_history_and_raises_for_malformed_ohlc(self):
        self.assertTrue(hasattr(self.broker.native, 'chart_snapshot'), 'No independent candle display read')
        snapshot = self.broker.chart_snapshot('EURUSD', 'M5', 3)
        self.assertEqual(len(snapshot['bars']), 3)
        self.assertGreater(snapshot['bars'][-1].time, NOW)
        self.assertEqual(snapshot['bars'][-1].time + 300, snapshot['live_bar'].time)
        with patch.object(self.broker.terminal, 'copy_rates_from_pos', return_value=[dict(time=NOW,open=1,high=.5,low=.9,close=1,tick_volume=1)]):
            with self.assertRaises(ValueError):
                self.broker.chart_snapshot('EURUSD', 'M5')

    def test_profile_and_account_changes_clear_the_previous_chart_immediately(self):
        self.assertTrue(self.step().get('chart_market'))
        self.engine.command('configure', {'command_id':'r54-configure-test','config': {'symbol': 'GBP/USD'}})
        self.assertTrue(self.engine.snapshot().get('chart_market') is None, 'Previous profile preview must be cleared immediately')
        self.assertTrue(self.step(1.2).get('chart_market'))
        self.engine.command('adopt_account', {'command_id':'r54-adopt-test','confirmation': 'ADOPT_MT5_ACCOUNT'})
        self.assertTrue(self.engine.snapshot().get('chart_market') is None, 'Previous profile preview must be cleared immediately')


if __name__ == '__main__':
    unittest.main()
