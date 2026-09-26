"""R5 regression contracts. Synthetic broker only, never imports MetaTrader5."""
import copy
import tempfile
import unittest
from dataclasses import fields, replace
from pathlib import Path
from unittest.mock import patch
from event_core.model import Config, Decision, Blocked, Bar
from event_core.risk import plan_order
from event_core.mt5_adapter import MT5Broker
from event_core.store import Store
from fakes import FakeBroker
from test_mt5_market_clock import _OffsetMT5, BASE


class FixedLotTests(unittest.TestCase):
    def setUp(self):
        self.now=1_800_000_000.
        self.b=FakeBroker(lambda:self.now);self.b.balance=100000
        self.cfg=Config(risk_pct=.25,lot_cap=.5,probe_lot_cap=.5,fee_per_lot=0,approved=True)
        # Attribute assignment deliberately lets baseline tests expose ignored fixed-volume intent.
        self.cfg.volume_mode='FIXED'
        self.d=Decision('BUY','ENTRY_READY','fixed lot test','r5-lot',1,
                        self.b.bid-.001,self.b.bid-.00001,self.b.bid-.001,.002,int(self.now*1000),entry_class='PROBE')
    def plan(self):
        return plan_order(self.b,self.cfg,self.b.account(),self.b.info,self.b.quote('EURUSD'),self.d,[],None,self.now)
    def test_fixed_mode_is_part_of_persisted_profile(self):
        self.assertIn('volume_mode',{f.name for f in fields(Config)})
    def test_selected_volume_is_used_for_the_first_entry(self):
        self.assertEqual(self.plan().volume,.5)
    def test_insufficient_risk_does_not_silently_shrink_user_lot(self):
        self.cfg.risk_pct=.001
        with self.assertRaisesRegex(Blocked,'[Лл]от|объём'):self.plan()
    def test_bad_volume_step_is_not_silently_rounded(self):
        self.cfg.lot_cap=self.cfg.probe_lot_cap=.015
        with self.assertRaisesRegex(Blocked,'шаг'):self.plan()
    def test_volume_above_broker_max_is_not_silently_clamped(self):
        self.b.info['volume_max']=.10
        with self.assertRaisesRegex(Blocked,'объём|лот'):self.plan()
    def test_fixed_volume_does_not_override_margin_limit(self):
        self.b.calc_margin=lambda *a:1000000
        with self.assertRaisesRegex(Blocked,'марж'):self.plan()
    def test_nan_and_negative_volume_are_rejected(self):
        for v in (-1,0,float('nan'),float('inf')):
            self.cfg.lot_cap=self.cfg.probe_lot_cap=v
            with self.assertRaises(Blocked):self.plan()
    def test_real_pilot_limit_remains(self):
        self.cfg.account_mode='REAL'
        with self.assertRaisesRegex(Blocked,'REAL'):self.cfg.validate()


class StableBarClockTests(unittest.TestCase):
    def test_normal_tick_latency_cannot_move_closed_candle_identity(self):
        local=BASE+197.;mt5=_OffsetMT5(local+120);broker=MT5Broker(mt5)
        with patch('event_core.mt5_adapter.time.time',return_value=local),patch('event_core.mt5_adapter.time.monotonic',return_value=1.):
            broker.quote('EURUSD');before=broker.bars('EURUSD','M5')[-1].time
        mt5.server_now+=2
        with patch('event_core.mt5_adapter.time.time',return_value=local+3.2),patch('event_core.mt5_adapter.time.monotonic',return_value=4.2):
            broker.quote('EURUSD');after=broker.bars('EURUSD','M5')[-1].time
        self.assertEqual(before,after,'Receiving latency must not rewrite candle IDs / rearm every scenario')


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.s=Store(Path(self.folder.name)/'r5.db')
    def tearDown(self):self.s.close();self.folder.cleanup()
    def test_history_accumulates_without_duplicate_bars(self):
        self.assertTrue(callable(getattr(self.s,'save_bars',None)),'Durable closed-bar history is missing')
        bars=[Bar(300*i,1.1,1.11,1.09,1.105) for i in range(1,31)]
        self.s.save_bars('acct|EURUSD','M5',bars,9600)
        self.s.save_bars('acct|EURUSD','M5',bars[-4:],9700)
        out=self.s.read_bars('acct|EURUSD','M5',limit=100)
        self.assertEqual(len(out),30);self.assertEqual(out[0]['time'],300)
        self.assertEqual(len(self.s.read_bars('other','M5')),0)
        page=self.s.read_bars('acct|EURUSD','M5',before=1500,limit=3)
        self.assertEqual([r['time'] for r in page],[600,900,1200])
    def test_immutable_snapshot_cannot_be_rewritten(self):
        self.assertTrue(callable(getattr(self.s,'save_scenario_snapshot',None)),'Immutable scenario snapshot store is missing')
        body={'snapshot_id':'s1','forecast':{'live_price':1.1},'scenario_id':'pattern-one'}
        self.s.save_scenario_snapshot('acct|EURUSD',body,10)
        body['forecast']['live_price']=9
        self.s.save_scenario_snapshot('acct|EURUSD',body,11)
        out=self.s.scenario_snapshots('acct|EURUSD')
        self.assertEqual(len(out),1);self.assertEqual(out[0]['forecast']['live_price'],1.1)
        self.assertEqual(self.s.scenario_snapshots('other'),[])
