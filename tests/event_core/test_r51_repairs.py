"""Regression examples from R5 screenshots; no actual broker is connected."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from event_core.model import Bar, Quote, Config, Blocked, atr
from event_core.mt5_adapter import MT5Broker
from event_core.engine import Engine
from event_core.store import Store
from event_core.scenarios.core import ScenarioCore
from event_core.scenarios.lifecycle import create_scenarios, _targets
from event_core.scenarios.structure import detect_patterns, value
from fakes import FakeBroker
from test_r5_scenarios import lane, shaped

NOW = 1_800_000_000.0

class NativeTerminal:
    TIMEFRAME_M1 = 60
    TIMEFRAME_M5 = 300
    TIMEFRAME_M15 = 900
    TIMEFRAME_H1 = 3600
    def __init__(self, now): self.now = now; self.tick = now[0] - 7205
    def symbol_info_tick(self, symbol):
        return SimpleNamespace(time_msc=int(self.tick*1000),bid=1.137,ask=1.13701)
    def copy_rates_from_pos(self, symbol, tf, start, count):
        current = int(self.tick//tf)*tf
        rows = [dict(time=current-i*tf,open=1.137,high=1.1371,low=1.1369,close=1.137,tick_volume=8) for i in range(count+start)]
        return list(reversed(rows[start:]))
    def last_error(self):return (1, 'OK')

class TerminalBroker(FakeBroker):
    def __init__(self, now):
        super().__init__(lambda: now[0]); self.now=now
        self.terminal=NativeTerminal(now);self.native=MT5Broker(self.terminal)
    def quote(self,symbol):return self.native.quote(symbol)
    def bars(self,symbol,tf,count=240):return self.native.bars(symbol,tf,count)
    def history_bars(self,symbol,tf,count=1200):return self.native.history_bars(symbol,tf,count)
    def current_bar(self,symbol,tf):return self.native.current_bar(symbol,tf)

class NativeClockTests(unittest.TestCase):
    def test_stale_first_tick_never_moves_native_bar_identity(self):
        now=[NOW]; t=NativeTerminal(now);b=MT5Broker(t)
        with patch('event_core.mt5_adapter.time.time',return_value=NOW),patch('event_core.mt5_adapter.time.monotonic',return_value=10):
            b.quote('EURUSD')
            self.assertEqual(b._bar_time('EURUSD',int(NOW)-7500),int(NOW)-7500)
    def test_progressing_but_hours_old_ticks_cannot_become_fresh(self):
        now=[NOW]; t=NativeTerminal(now);b=MT5Broker(t)
        with patch('event_core.mt5_adapter.time.time',return_value=NOW),patch('event_core.mt5_adapter.time.monotonic',return_value=10):b.quote('EURUSD')
        t.tick+=.2
        with patch('event_core.mt5_adapter.time.time',return_value=NOW+.2),patch('event_core.mt5_adapter.time.monotonic',return_value=10.2):
            q=b.quote('EURUSD')
        with self.assertRaises(Blocked):q.validate(NOW+.2)
    def test_new_tick_identity_is_native_not_receive_timestamp(self):
        now=[NOW];t=NativeTerminal(now);t.tick=NOW-.5;b=MT5Broker(t)
        with patch('event_core.mt5_adapter.time.time',return_value=NOW),patch('event_core.mt5_adapter.time.monotonic',return_value=10):b.quote('EURUSD')
        t.tick=NOW-.3
        with patch('event_core.mt5_adapter.time.time',return_value=NOW+.2),patch('event_core.mt5_adapter.time.monotonic',return_value=10.2):q=b.quote('EURUSD')
        self.assertEqual(q.time_msc,int(t.tick*1000));q.validate(NOW+.2)
    def test_cached_tick_id_does_not_advance_with_wall_clock(self):
        now=[NOW];t=NativeTerminal(now);t.tick=NOW;b=MT5Broker(t)
        for x in (0,.2):
            t.tick=NOW+x
            with patch('event_core.mt5_adapter.time.time',return_value=NOW+x),patch('event_core.mt5_adapter.time.monotonic',return_value=10+x):q=b.quote('EURUSD')
        with patch('event_core.mt5_adapter.time.time',return_value=NOW+2.9),patch('event_core.mt5_adapter.time.monotonic',return_value=12.8):same=b.quote('EURUSD')
        self.assertEqual(q.time_msc,same.time_msc)

class CacheRepairTests(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory();self.store=Store(Path(self.td.name)/'db.sqlite3')
        self.now=[NOW];self.broker=TerminalBroker(self.now);self.e=Engine(self.broker,self.store,lambda:self.now[0])
        self.e.config=Config(engine_mode='SCENARIO_V2',approved=True,fee_per_lot=0)
        self.e._refresh(NOW)
    def tearDown(self):self.store.close();self.td.cleanup()
    def refresh(self,dt,raw):
        self.now[0]=NOW+dt;self.broker.terminal.tick=raw
        with patch('event_core.mt5_adapter.time.time',return_value=self.now[0]),patch('event_core.mt5_adapter.time.monotonic',return_value=10+dt):self.e._refresh_market(self.now[0])
    def test_unverified_tick_does_not_write_history(self):
        self.refresh(0,NOW-7205)
        self.assertFalse(self.e.quote_ready)
        self.assertEqual(self.store.read_bars(self.e.market_scope(),'M5'),[])
    def test_stale_to_fresh_never_interleaves_old_shifted_history(self):
        self.refresh(0,NOW-7205)
        for n in (1.2,1.4,2.6):self.refresh(n,NOW+n)
        self.assertTrue(self.e.quote_ready)
        times=[b.time for b in self.e.bars]
        self.assertTrue(times)
        self.assertTrue(all((b-a)>=300 and (b-a)%300==0 for a,b in zip(times,times[1:])),times[-15:])
        self.assertTrue(all(t%300==0 for t in times),times[-15:])
    def test_migration_quarantines_only_market_cache_preserves_money_and_intents(self):
        scope=self.e.market_scope()
        polluted=[Bar(int(NOW)-900,1.139,1.14,1.138,1.139),Bar(int(NOW)-895,1.137,1.138,1.136,1.137)]
        self.store.save_bars(scope,'M5',polluted,NOW)
        self.store.campaign('cash-sentinel',{'net':17.25})
        self.store.intent('unknown-sentinel','UNKNOWN',{'ticket':91})
        self.store.save_scenario_snapshot(scope,{'snapshot_id':'old-view','forecast':{'map_version':3}},NOW)
        for n in (0,.2,1.3):self.refresh(n,NOW+n)
        times=[b.time for b in self.e.bars]
        self.assertNotIn(int(NOW)-895,times)
        self.assertEqual(self.store.pending()[0]['id'],'unknown-sentinel')
        self.assertEqual(self.store.db.execute('SELECT body FROM campaigns WHERE id=?',('cash-sentinel',)).fetchone()[0],'{"net": 17.25}')
        self.assertEqual(len(self.store.scenario_snapshots(scope)),1)
        tables={r[0] for r in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn('market_bars_quarantine',tables,'Suspect history must remain recoverable')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM market_bars_quarantine WHERE scope=?',(scope,)).fetchone()[0],2)
    def test_bad_spacing_blocks_before_cache_write(self):
        b=FakeBroker(lambda:NOW);e=Engine(b,self.store,lambda:NOW);e._refresh(NOW)
        b.bar_data=[Bar(int(NOW)-600,1.1,1.101,1.099,1.1),Bar(int(NOW)-595,1.1,1.101,1.099,1.1)]
        e._refresh_market(NOW)
        self.assertTrue(any('интервал' in x.lower() or 'врем' in x.lower() for x in e.market_errors),e.market_errors)
        self.assertEqual(self.store.read_bars(e.market_scope(),'M5'),[])

class ExplanationTests(unittest.TestCase):
    def setUp(self):
        self.bars=lane('TRIANGLE');self.a=atr(self.bars)
        self.p=next(p for p in detect_patterns(self.bars,'EUR/USD','M5') if p['family']=='TRIANGLE')
    def evaluate(self,c,now):
        q=Quote(int(now*1000),1.101,1.10101)
        m1=[Bar(int(NOW)-60*i,1.101,1.10103,1.10097,1.101) for i in range(20,0,-1)]
        return c.evaluate(self.bars,m1,[],[],Bar(int(NOW),1.101,1.102,1.1,1.101),q,now)
    def test_two_neighboring_extremes_are_one_target_zone(self):
        b=shaped([1.13990,1.1390,1.13991,1.1390,1.14101])
        t1,t2,*_= _targets(self.p,b,1,1.1392,.0005)
        self.assertAlmostEqual(t1,1.13991,places=4)
        self.assertIsNotNone(t2)
        self.assertGreaterEqual(abs(t2-t1),.15*.0005)
    def test_equal_scores_have_no_primary_claim(self):
        c=ScenarioCore(Config(engine_mode='SCENARIO_V2'))
        f=self.evaluate(c,NOW).forecast
        scores=[s['quality_score'] for s in f['scenarios']]
        self.assertEqual(scores[0],scores[1])
        self.assertEqual(f.get('selection_status'),'TIED')
        self.assertEqual(f['side'],0)
        self.assertTrue(all(s['name']!='PRIMARY' for s in f['scenarios']))
    def test_current_path_boundary_matches_current_card_without_mutating_origin(self):
        c=ScenarioCore(Config(engine_mode='SCENARIO_V2'))
        self.evaluate(c,NOW)
        originals={k:copy.deepcopy(v['path']) for k,v in c.scenarios.items()}
        f=self.evaluate(c,NOW+6).forecast
        routes=[s for s in f['scenarios'] if s['type'] in ('DIRECT_BREAKOUT','BREAKOUT_RETEST')]
        self.assertTrue(routes)
        for s in routes:
            p=next(x for x in s['path'] if x['anchor']=='TRIGGER')
            self.assertAlmostEqual(p['price'],s['activation'],places=12)
        for k,v in originals.items():self.assertEqual(c.scenarios[k]['path'],v)
    def test_watching_describes_distinct_required_event_and_exact_level(self):
        c=ScenarioCore(Config(engine_mode='SCENARIO_V2'));f=self.evaluate(c,NOW).forecast
        for s in f['scenarios']:
            self.assertNotEqual(s['next_event'],'ждём новое событие у границы')
            self.assertIn(f"{s['activation']:.5f}",s['next_event'])
            self.assertTrue(s.get('required_event'))
    def test_two_unfulfilled_directions_remain_watch_not_orders(self):
        c=ScenarioCore(Config(engine_mode='SCENARIO_V2'))
        self.assertEqual(self.evaluate(c,NOW).signal,'WAIT')
        self.assertEqual(self.evaluate(c,NOW+1).signal,'WAIT')

if __name__=='__main__':unittest.main()

class WatchlistEndpointTests(unittest.TestCase):
    def test_scan_before_filter_keeps_pairs_after_thousands_of_equities(self):
        rows=[SimpleNamespace(name='AAA'+str(i),trade_mode=4) for i in range(2500)]
        rows+=[SimpleNamespace(name='EURUSD',trade_mode=4),SimpleNamespace(name='GBPUSD',trade_mode=4)]
        terminal=SimpleNamespace(symbols_get=lambda:rows,SYMBOL_TRADE_MODE_DISABLED=0)
        self.assertEqual(MT5Broker(terminal).symbols(),['EURUSD','GBPUSD'])
    def test_disabled_pair_is_not_exposed(self):
        terminal=SimpleNamespace(symbols_get=lambda:[SimpleNamespace(name='EURUSD',trade_mode=0)],SYMBOL_TRADE_MODE_DISABLED=0)
        self.assertEqual(MT5Broker(terminal).symbols(),[])
