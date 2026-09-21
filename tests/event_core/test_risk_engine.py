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
        p=self.plan(cfg=replace(self.cfg,lot_cap=.1))
        self.assertLessEqual(p.stop, self.b.bid-.001)
        self.assertLessEqual(p.total_risk,replace(self.cfg,lot_cap=.1).budget(self.b.account())+1e-7)
    def test_tiny_budget_skips_not_minimum_lot_override(self):
        with self.assertRaises(Blocked):self.plan(cfg=replace(self.cfg,risk_pct=.000001))
    def test_unknown_fees_not_zero(self):
        with self.assertRaises(Blocked):self.plan(cfg=replace(self.cfg,fee_per_lot=None))
    def test_nan_profit_blocks(self):
        self.b.calc_profit=lambda *a:float('nan')
        with self.assertRaises(Blocked):self.plan()
    def test_real_account_is_forbidden_when_profile_is_demo(self):
        self.b.demo=False
        with self.assertRaisesRegex(Blocked,'режим счёта'):self.plan()

    def test_real_pilot_plan_allowed_only_with_real_profile_and_strict_caps(self):
        self.b.demo=False
        cfg=replace(self.cfg,account_mode='REAL',risk_pct=.25,lot_cap=.01,probe_lot_cap=.01)
        p=self.plan(cfg=cfg)
        self.assertEqual(p.volume,.01)
        with self.assertRaisesRegex(Blocked,'REAL pilot'):
            self.plan(cfg=replace(cfg,risk_pct=.5))
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
        self.b.calc_margin=lambda *a:100000
        with self.assertRaises(Blocked):self.plan()
    def test_fee_accounted_before_add(self):
        p=dict(symbol='EURUSD',side=1,sl=1.102,volume=.01,price_open=1.101,profit=.01,swap=0)
        with self.assertRaisesRegex(Blocked,'усреднение'):self.plan(cfg=replace(self.cfg,fee_per_lot=7),positions=[p],campaign={'budget':10,'last_entry':1.102,'add_step_atr':.3})
    def test_price_must_advance_since_last_entry(self):
        p=dict(symbol='EURUSD',side=1,sl=1.102,volume=.01,price_open=1.101,profit=2,swap=0)
        with self.assertRaisesRegex(Blocked,'следующий шаг'):self.plan(positions=[p],campaign={'budget':10,'last_entry':1.103,'add_step_atr':.3})

    def test_account_wide_old_losses_and_manual_float_do_not_block_ec1(self):
        foreign_position=dict(ticket=900,identifier=900,magic=999,symbol='EURUSD',side=1,volume=.01,price_open=1.10,sl=1.09,tp=0,profit=-25,swap=0,time=int(self.now),comment='manual')
        deals=[]
        for i in range(4):
            pid=800+i
            deals.extend([
                dict(ticket=pid*10,position_id=pid,magic=999,symbol='EURUSD',comment='legacy',type=0,entry=0,time_msc=int((self.now-100+i)*1000),volume=.01,profit=0.,commission=0.,swap=0.,fee=0.),
                dict(ticket=pid*10+1,position_id=pid,magic=999,symbol='EURUSD',comment='legacy',type=1,entry=1,time_msc=int((self.now-90+i)*1000),volume=.01,profit=-5.,commission=0.,swap=0.,fee=0.)])
        account=dict(self.b.account());account['equity']=account['balance']-25
        rs=risk_state(account,[foreign_position],deals,self.cfg,self.now)
        self.assertTrue(rs['allowed'])
        self.assertEqual(rs['blocks'],[])

    def test_campaign_budget_uses_actual_mt5_equity_not_artificial_base_or_dollar_cap(self):
        account=dict(self.b.account());account['balance']=100000.;account['equity']=99800.
        cfg=replace(self.cfg,risk_pct=.25,test_capital=100,absolute_risk_cap=.50)
        self.assertAlmostEqual(cfg.base(account),99800.)
        self.assertAlmostEqual(cfg.budget(account),249.50)

    def test_margin_guard_uses_actual_account_not_test_capital(self):
        self.b.calc_margin=lambda *a:500
        cfg=replace(self.cfg,risk_pct=.25,test_capital=100,absolute_risk_cap=.50,margin_fraction=.30,lot_cap=.01)
        plan=self.plan(cfg=cfg)
        self.assertGreater(plan.volume,0)


    def test_commission_estimator_uses_completed_roundtrip_per_lot(self):
        deals=[
            dict(ticket=1,position_id=77,magic=MAGIC,symbol='EURUSD',comment='x',type=0,entry=0,time_msc=1,volume=1.0,profit=0,commission=-3.5,swap=0,fee=0),
            dict(ticket=2,position_id=77,magic=MAGIC,symbol='EURUSD',comment='x',type=1,entry=1,time_msc=2,volume=1.0,profit=4,commission=-3.5,swap=0,fee=0),
        ]
        self.assertAlmostEqual(estimate_roundtrip_fee_per_lot(deals),7.0)

    def test_custom_symbol_is_not_restricted_to_eurusd(self):
        cfg=replace(self.cfg,symbol='BTCUSD.pro',spread_pips=999)
        self.b.info.update(name='BTCUSD.pro',digits=2,point=.01,tick_size=.01)
        self.b.bid=50000.;self.b.ask=50000.5
        self.b.calc_profit=lambda side,symbol,volume,entry,exit: side*(exit-entry)*volume*10
        self.d=Decision('BUY','ENTRY_READY','test','btc',1,49990.,50000.4,49990.,20.,int(self.now*1000))
        p=plan_order(self.b,cfg,self.b.account(),self.b.info,self.b.quote('BTCUSD.pro'),self.d,[],None,self.now)
        self.assertEqual(p.symbol,'BTCUSD.pro')



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
    def test_demo_profile_defaults_fee_to_zero_without_manual_settings(self):
        self.e.config=replace(self.e.config,fee_per_lot=None,approved=False,account_mode='DEMO')
        self.e.strategy=__import__('event_core.strategy',fromlist=['Strategy']).Strategy(self.e.config)
        self.e._refresh(self.now)
        self.assertEqual(self.e.effective_fee_per_lot,0.0)
        out=self.e.command('approve_profile',{'command_id':'approve-demo-auto-fee','confirmation':'APPROVE_DEMO_RISK'})
        self.assertTrue(self.e.config.approved,out)

    def test_real_account_is_shadow_until_explicit_arm_then_can_enable_pilot(self):
        self.b.demo=False
        self.e.account_key=''
        self.e.config=Config(symbol='GBP/JPY',account_mode='REAL',risk_pct=.25,fee_per_lot=7.0,
                             lot_cap=.01,probe_lot_cap=.01,approved=True,cooldown_sec=0)
        self.e.strategy=__import__('event_core.strategy',fromlist=['Strategy']).Strategy(self.e.config)
        self.e._refresh(self.now)
        self.assertEqual(self.e.account['type'],'REAL')
        self.assertFalse(self.e.real_armed)
        with self.assertRaisesRegex(Blocked,'ARM REAL'):
            self.e.command('enable',{'command_id':'real-enable-before-arm','confirmation':'ENABLE_REAL'})
        arm=self.e.command('arm_real',{'command_id':'real-arm-explicit','confirmation':'ARM_REAL_LIVE'})
        self.assertTrue(arm['real_armed'])
        out=self.e.command('enable',{'command_id':'real-enable-after-arm','confirmation':'ENABLE_REAL'})
        self.assertTrue(out['auto'])

    def test_real_armed_pilot_can_send_only_minimum_lot(self):
        self.b.demo=False;self.e.account_key=''
        self.e.config=Config(account_mode='REAL',risk_pct=.25,fee_per_lot=7.0,lot_cap=.01,probe_lot_cap=.01,approved=True,cooldown_sec=0)
        self.e.strategy=__import__('event_core.strategy',fromlist=['Strategy']).Strategy(self.e.config)
        self.e._refresh(self.now);self.e.info=self.b.symbol('EUR/USD');self.e.quote=self.b.quote('EURUSD')
        self.e.command('arm_real',{'command_id':'real-arm-entry','confirmation':'ARM_REAL_LIVE'})
        self.e.command('enable',{'command_id':'real-enable-entry','confirmation':'ENABLE_REAL'})
        self.e._entry(self.decision('real-pilot-entry'),self.now)
        self.assertEqual(len(self.b.sent),1)
        self.assertEqual(self.b.sent[0].volume,.01)

    def test_real_arm_does_not_survive_bridge_restart(self):
        self.b.demo=False;self.e.account_key=''
        self.e.config=Config(account_mode='REAL',risk_pct=.25,fee_per_lot=7.0,lot_cap=.01,probe_lot_cap=.01,approved=True,cooldown_sec=0)
        self.e.strategy=__import__('event_core.strategy',fromlist=['Strategy']).Strategy(self.e.config)
        self.e._refresh(self.now)
        self.e.command('arm_real',{'command_id':'real-arm-restart','confirmation':'ARM_REAL_LIVE'})
        self.assertTrue(self.e.real_armed)
        other=Engine(self.b,self.store,lambda:self.now)
        self.assertFalse(other.real_armed)

    def test_real_commission_is_auto_estimated_and_persisted_by_account(self):
        self.b.demo=False
        self.b.deals=[
            dict(ticket=1,position_id=50,magic=MAGIC,symbol='EURUSD',comment='old',type=0,entry=0,time_msc=int((self.now-20)*1000),volume=1.,profit=0.,commission=-3.5,swap=0.,fee=0.),
            dict(ticket=2,position_id=50,magic=MAGIC,symbol='EURUSD',comment='old',type=1,entry=1,time_msc=int((self.now-10)*1000),volume=1.,profit=10.,commission=-3.5,swap=0.,fee=0.),
        ]
        self.e.account_key=''
        self.e.config=Config(account_mode='REAL',risk_pct=.25,fee_per_lot=None,lot_cap=.01,probe_lot_cap=.01,approved=False,cooldown_sec=0)
        self.e.strategy=__import__('event_core.strategy',fromlist=['Strategy']).Strategy(self.e.config)
        self.e.history_time=0
        self.e._refresh(self.now)
        self.assertAlmostEqual(self.e.effective_fee_per_lot,7.0)
        self.assertEqual(self.e.fee_source,'MT5_HISTORY')
        saved=self.store.load('fee_profiles',{})
        self.assertAlmostEqual(saved[self.e.fee_profile_key]['fee_per_lot'],7.0)

    def test_reapproving_same_profile_does_not_turn_auto_off(self):
        self.e.command('enable',{'command_id':'enable-again-1','confirmation':'ENABLE_DEMO'})
        self.assertTrue(self.e.auto);self.assertFalse(self.e.paused)
        out=self.e.command('approve_profile',{'command_id':'approve-again-1','confirmation':'APPROVE_DEMO_RISK'})
        self.assertTrue(self.e.auto,out)
        self.assertFalse(self.e.paused,out)

    def test_enable_reports_exit_pending_not_emergency(self):
        self.e._entry(self.decision(),self.now)
        self.e.exit_pending=True;self.e.auto=False;self.e.paused=True
        with self.assertRaisesRegex(Blocked,'подтверждение закрытия'):
            self.e.command('enable',{'command_id':'enable-exit-1','confirmation':'ENABLE_DEMO'})

    def test_flat_campaign_reconciles_quickly_even_without_exit_pending(self):
        self.e._entry(self.decision('flat-reconcile'),self.now)
        self.assertIsNotNone(self.e.campaign)
        self.b.close(self.e._owned()[0])
        self.e.positions=self.b.positions();self.e.orders=self.b.orders()
        self.e.exit_pending=False
        self.now+=1.2
        self.e.step()
        self.assertIsNone(self.e.campaign,self.e.execution)

    def test_exit_pending_refreshes_history_quickly_and_clears_after_mt5_close(self):
        self.e._entry(self.decision(),self.now)
        self.e.auto=True;self.e.paused=False
        self.e._close_campaign('test exit')
        self.assertEqual(self.b._positions,[])
        self.assertTrue(self.e.exit_pending)
        # Closing deal already exists in fake MT5 history, but prior behaviour waited 10 seconds.
        self.now+=1.2
        self.e.step()
        self.assertFalse(self.e.exit_pending,self.e.execution)
        self.assertIsNone(self.e.campaign)
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
        self.e.config=replace(self.e.config,risk_pct=.05)
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
