import unittest,tempfile,sys,copy
from dataclasses import replace,asdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'mt5_bridge'))
from event_core.model import *
from event_core.risk import *
from event_core.engine import Engine
from event_core.store import Store, ProcessLock
from event_core.mt5_adapter import MAGIC
from fakes import FakeBroker,wave


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.now=1800000000.
        self.b=FakeBroker(lambda:self.now)
        self.cfg=Config(risk_pct=1,absolute_risk_cap=10,test_capital=1000,fee_per_lot=0,approved=True)
        self.d=Decision('BUY','ENTRY_READY','test','id',1,1.1028,1.10299,1.102,.0005,int(self.now*1000))
    def plan(self,**kw):
        return plan_order(self.b,kw.get('cfg',self.cfg),self.b.account(),self.b.info,self.b.quote('EURUSD'),self.d,
                          kw.get('positions',[]),kw.get('campaign'),self.now)
    def test_stop_adjusted_before_lot(self):
        self.b.info['stops_level']=100
        p=self.plan(cfg=replace(self.cfg,absolute_risk_cap=2,lot_cap=.1))
        self.assertLessEqual(p.stop, self.b.bid-.001)
        self.assertLessEqual(p.total_risk,2+1e-7)
    def test_tiny_budget_skips_not_minimum_lot_override(self):
        with self.assertRaises(Blocked):self.plan(cfg=replace(self.cfg,absolute_risk_cap=.001))
    def test_unknown_fees_not_zero(self):
        with self.assertRaises(Blocked):self.plan(cfg=replace(self.cfg,fee_per_lot=None))
    def test_nan_profit_blocks(self):
        self.b.calc_profit=lambda *a:float('nan')
        with self.assertRaises(Blocked):self.plan()
    def test_real_forbidden(self):
        self.b.demo=False
        with self.assertRaises(Blocked):self.plan()
    def test_negative_campaign_no_add(self):
        p=dict(symbol='EURUSD',side=1,sl=1.102,volume=.01,price_open=1.104,profit=-1,swap=0)
        with self.assertRaisesRegex(Blocked,'усреднение'):self.plan(positions=[p],campaign={'budget':10,'last_entry':1.102,'add_step_atr':.3})
    def test_no_fixed_ten_cap(self):
        positions=[dict(symbol='EURUSD',side=1,sl=1.102,volume=.01,price_open=1.101,profit=2,swap=0) for _ in range(12)]
        p=self.plan(positions=positions,campaign={'budget':10,'last_entry':1.102,'add_step_atr':.3})
        self.assertGreater(p.volume,0)
    def test_budget_applies_to_whole_group(self):
        positions=[dict(symbol='EURUSD',side=1,sl=1.09,volume=.01,price_open=1.101,profit=2,swap=0)]
        with self.assertRaises(Blocked):self.plan(positions=positions,campaign={'budget':10,'last_entry':1.102,'add_step_atr':.3})
    def test_unprotected_position_blocks(self):
        p=dict(symbol='EURUSD',side=1,sl=0,volume=.01,price_open=1.101,profit=2,swap=0)
        with self.assertRaises(Blocked):self.plan(positions=[p],campaign={'budget':10,'last_entry':1.102,'add_step_atr':.3})
    def test_bad_margin_blocks(self):
        self.b.calc_margin=lambda *a:10000
        with self.assertRaises(Blocked):self.plan()
    def test_fee_accounted_before_add(self):
        p=dict(symbol='EURUSD',side=1,sl=1.102,volume=.01,price_open=1.101,profit=.01,swap=0)
        with self.assertRaisesRegex(Blocked,'усреднение'):self.plan(cfg=replace(self.cfg,fee_per_lot=7),positions=[p],campaign={'budget':10,'last_entry':1.102,'add_step_atr':.3})
    def test_price_must_advance_since_last_entry(self):
        p=dict(symbol='EURUSD',side=1,sl=1.102,volume=.01,price_open=1.101,profit=2,swap=0)
        with self.assertRaisesRegex(Blocked,'следующий шаг'):self.plan(positions=[p],campaign={'budget':10,'last_entry':1.103,'add_step_atr':.3})


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.now=1800000000.
        self.b=FakeBroker(lambda:self.now);self.path=Path(self.temp.name)/'state.sqlite3'
        self.store=Store(self.path);self.e=Engine(self.b,self.store,lambda:self.now)
        self.e.config=Config(risk_pct=1,absolute_risk_cap=10,test_capital=1000,fee_per_lot=0,approved=True,cooldown_sec=0)
        self.e.strategy=__import__('event_core.strategy',fromlist=['Strategy']).Strategy(self.e.config)
        self.e._refresh(self.now);self.e.info=self.b.symbol('EUR/USD');self.e.quote=self.b.quote('EURUSD')
    def tearDown(self):
        self.store.close();self.temp.cleanup()
    def decision(self,key='test-entry'):
        return Decision('BUY','ENTRY_READY','test',key,1,1.1028,1.10299,1.102,.0005,int(self.now*1000))
    def test_boot_auto_off(self):self.assertFalse(self.e.auto)
    def test_play_cannot_arm(self):
        with self.assertRaises(Blocked):self.e.command('play',{'command_id':'play0001'})
    def test_enable_explicit(self):
        with self.assertRaises(Blocked):self.e.command('enable',{'command_id':'enable0001'})
        self.e.command('enable',{'command_id':'enable0002','confirmation':'ENABLE_DEMO'})
        self.assertTrue(self.e.auto)
    def test_repeat_intent_never_duplicate(self):
        self.e._entry(self.decision(),self.now)
        with self.assertRaises(Blocked):self.e._entry(self.decision(),self.now)
        self.assertEqual(len(self.b.sent),1)
    def test_unknown_send_latches_no_retry(self):
        self.b.result='UNKNOWN';self.b.visible=False
        self.e._entry(self.decision(),self.now)
        self.assertTrue(self.e.recovery);self.assertFalse(self.e.auto)
        with self.assertRaises(Blocked):self.e._entry(self.decision('new-one'),self.now)
        self.assertEqual(len(self.b.sent),1)
    def test_unknown_survives_restart(self):
        self.b.result='UNKNOWN';self.b.visible=False;self.e._entry(self.decision(),self.now)
        other=Engine(self.b,self.store,lambda:self.now)
        self.assertTrue(other.recovery)
        with self.assertRaises(Blocked):other.command('reset',{'command_id':'reset0001','confirmation':'RESET_DEMO_FLAT'})
    def test_known_fill_preserves_ticket(self):
        self.e._entry(self.decision(),self.now)
        self.assertEqual(len(self.e._owned()),1)
        self.assertEqual(self.e.campaign['position_ids'],[101])
        self.assertFalse(self.store.pending())
    def test_real_blocks_order_and_close(self):
        self.b.demo=False
        with self.assertRaises(Blocked):self.e._entry(self.decision(),self.now)
        self.assertFalse(self.b.sent)
    def test_emergency_persists_and_play_cannot_reset(self):
        self.e.command('emergency',{'command_id':'stop0001'})
        other=Engine(self.b,self.store,lambda:self.now)
        self.assertTrue(other.emergency)
        with self.assertRaises(Blocked):other.command('play',{'command_id':'play0001'})
        with self.assertRaises(Blocked):other.command('enable',{'command_id':'arm00001','confirmation':'ENABLE_DEMO'})
    def test_emergency_closes_even_when_history_unavailable(self):
        self.e._entry(self.decision(),self.now);self.now+=11
        self.b.history_failure=True
        self.e.command('emergency',{'command_id':'stop0001'})
        self.e.step()
        self.assertEqual(self.b.closed,[101])
        self.assertFalse(self.e.auto)
    def test_exit_cannot_open_same_step(self):
        self.e._entry(self.decision(),self.now);self.e.exit_pending=True
        n=len(self.b.sent);self.e.step()
        self.assertEqual(len(self.b.sent),n);self.assertTrue(self.b.closed)
    def test_foreign_positions_not_closed(self):
        self.b._positions=[dict(ticket=9,identifier=9,magic=999,symbol='EURUSD',side=1,volume=.01,price_open=1.1,sl=1.09,tp=0,profit=3,swap=0,time=int(self.now),comment='manual')]
        self.e.command('emergency',{'command_id':'stop0001'});self.e.step()
        self.assertFalse(self.b.closed);self.assertEqual(len(self.b._positions),1)
    def test_profile_frozen_in_campaign(self):
        self.e._entry(self.decision(),self.now)
        with self.assertRaises(Blocked):self.e.command('configure',{'command_id':'config0001','config':{'mode':'SCALP'}})
    def test_command_idempotence(self):
        out=self.e.command('emergency',{'command_id':'stop0001'})
        self.assertEqual(out,self.e.command('emergency',{'command_id':'stop0001'}))
    def test_no_auto_restore_after_restart(self):
        self.e.auto=True;self.e.paused=False;self.e.save()
        self.assertFalse(Engine(self.b,self.store,lambda:self.now).auto)
    def test_history_failure_blocks_entry(self):
        self.e.history_ok=False
        with self.assertRaises(Blocked):self.e._entry(self.decision(),self.now)
        self.assertFalse(self.b.sent)
    def test_post_fill_excess_risk_forces_exit(self):
        send=self.b.send
        def bad_fill(p,comment):
            out=send(p,comment)
            self.b._positions[-1]['price_open']+=.10
            return out
        self.b.send=bad_fill
        self.e._entry(self.decision(),self.now)
        self.assertTrue(self.e.recovery);self.assertFalse(self.e.auto)
        self.assertTrue(self.b.closed);self.assertFalse(self.b._positions)
    def test_missing_acknowledged_sl_forces_exit(self):
        send=self.b.send
        def missing_stop(p,comment):
            out=send(p,comment);self.b._positions[-1]['sl']=0;return out
        self.b.send=missing_stop
        self.e._entry(self.decision(),self.now)
        self.assertTrue(self.e.recovery);self.assertTrue(self.b.closed)
    def test_no_process_double_start(self):
        p=Path(self.temp.name)/'runtime.lock';lock=ProcessLock(p)
        try:
            with self.assertRaises(Blocked):ProcessLock(p)
        finally:lock.close()

if __name__=='__main__':unittest.main()
