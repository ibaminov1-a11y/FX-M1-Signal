"""Actual Engine -> broker transport replay; no bypass of normal order guards."""
import copy,tempfile,unittest,uuid
from pathlib import Path
from dataclasses import asdict
from event_core.model import Config,atr
from event_core.store import Store
from event_core.engine import Engine
from test_r7_release_runtime import TradingBroker,NOW
from fakes import wave

class StableExecutionTests(unittest.TestCase):
    def setUp(self):
        self.assertIn('entry_model',Config.__dataclass_fields__,'Stable event model is not connected to Engine')
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.s=Store(Path(tmp.name)/'db');self.addCleanup(self.s.close)
        self.now=[float(NOW)];self.b=TradingBroker(lambda:self.now[0])
        self.b.frames['M5']=wave(NOW,tf=300,trend=0)
        self.a=atr(self.b.frames['M5']);self.low=min(b.low for b in self.b.frames['M5'][-12:]);self.high=max(b.high for b in self.b.frames['M5'][-12:])
        self.cfg=asdict(Config(engine_mode='SCENARIO_V2',runtime_model='R7',entry_model='STABLE_V1',fee_per_lot=0,cooldown_sec=0,lot_cap=.01,volume_mode='FIXED'))
        self.s.save('engine',dict(config=self.cfg));self.e=Engine(self.b,self.s,lambda:self.now[0])
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True,accept_pending_profile=True,config={k:v for k,v in self.cfg.items() if k not in ('approved','technical_position_fuse','max_orders_per_minute')}))
    def tick(self,price):
        self.now[0]+=1;self.b.bid=price;self.b.ask=price+.00001
        return self.e.step()
    def enter(self,side=1):
        zone=self.low if side>0 else self.high
        for d in (.5,.04,.20,.28):self.tick(zone+side*d*self.a)
        self.assertEqual(len(self.b.sent),1,self.e.execution)
        self.assertEqual(self.b.sent[0].side,side)
        self.assertIn(self.e.campaign['scenario_type'],('BOUNDARY_RECLAIM','RANGE_ROTATION'))
        self.assertEqual(self.e.campaign['forecast_at_entry']['execution_policy'],'STABLE_V1')
    def test_buy_then_add_then_target_exit_with_frozen_plan(self):
        self.enter();frozen=copy.deepcopy(self.e.campaign['forecast_at_entry'])
        for d in (.5,1.,.6,.7,1.04):self.tick(self.low+d*self.a)
        self.assertEqual(len(self.b.sent),2,self.e.execution)
        self.assertEqual(len({p.event_id for p in self.b.sent}),2)
        self.assertEqual(frozen,self.e.campaign['forecast_at_entry'])
        self.assertTrue(all(p.volume==.01 and p.total_risk<=self.e.campaign['budget'] for p in self.b.sent))
        target=frozen['entry_target1']
        self.tick(target+.00001);self.now[0]+=2;state=self.tick(target+.00001)
        self.assertFalse(self.b.positions(),self.e.execution)
        self.assertIsNone(self.e.campaign,self.e.execution)
        self.assertEqual(state['all']['count'],2)
    def test_sell_then_add_is_symmetric(self):
        self.enter(-1)
        for d in (.5,1.,.6,.7,1.04):self.tick(self.high-d*self.a)
        self.assertEqual(len(self.b.sent),2,self.e.execution)
        self.assertTrue(all(p.side==-1 for p in self.b.sent))
    def test_addition_plan_displays_direction_and_original_target(self):
        self.enter()
        state=self.tick(self.low+.5*self.a)
        setup=state['forecast']['execution_setup']
        self.assertEqual(setup.get('side'),1,'Addition direction missing from executable plan')
        self.assertEqual(setup.get('target1'),self.e.campaign['forecast_at_entry']['entry_target1'])
    def test_expired_unfilled_addition_can_observe_a_new_sequence(self):
        from event_core.model import Blocked
        self.enter()
        self.b.preflight=lambda *args:(_ for _ in ()).throw(Blocked('Transient margin limit'))
        for d in (.5,1.,.6,.7,1.04):self.tick(self.low+d*self.a)
        self.assertEqual(len(self.b.sent),1)
        self.assertTrue(self.e.compute.continuation.emitted)
        self.now[0]+=5
        self.b.preflight=lambda *args:None
        self.tick(self.low+1.04*self.a)
        self.assertFalse(self.e.compute.continuation.emitted,'Expired unfilled addition left the observer permanently consumed')
        for d in (1.2,1.3,.85,.95,1.34):self.tick(self.low+d*self.a)
        self.assertEqual(len(self.b.sent),2,self.e.execution)
    def test_no_averaging_on_adverse_movement(self):
        self.enter()
        for d in (.1,.05,-.05):self.tick(self.low+d*self.a)
        self.assertEqual(len(self.b.sent),1)
    def test_entry_inhibit_is_rechecked_after_slow_preflight(self):
        flag=[False];self.e.entry_inhibited=lambda:flag[0]
        self.b.preflight=lambda *args:flag.__setitem__(0,True)
        for d in (.5,.04,.20,.28):self.tick(self.low+d*self.a)
        self.assertFalse(self.b.sent)
        self.assertTrue(self.e.entry_inhibited())
    def test_soft_risk_rejection_does_not_delete_fixed_plan(self):
        from event_core.model import Blocked
        self.b.preflight=lambda *args:(_ for _ in ()).throw(Blocked('Временный предел маржи'))
        for d in (.5,.04,.20):self.tick(self.low+d*self.a)
        before=copy.deepcopy(self.e.compute.stable.state())
        self.tick(self.low+.28*self.a)
        self.assertFalse(self.b.sent)
        self.assertEqual(self.e.decision.phase,'ENTRY_BLOCKED')
        for k,s in before['plans'].items():
            for f in ('trigger','invalidation','target1','expires_at'):self.assertEqual(s[f],self.e.compute.stable.plans[k][f])
    def test_optional_observer_analysis_does_not_precede_ready_order(self):
        calls=[]
        self.e._refresh_observers=lambda now:calls.append(len(self.b.sent))
        self.enter()
        self.assertEqual(calls[-1],1,'Observer analysis ran ahead of an executable entry')
    def test_initial_reclaim_permission_is_not_restored_after_restart(self):
        for d in (.5,.04,.20):self.tick(self.low+d*self.a)
        self.e.save();self.e=Engine(self.b,self.s,lambda:self.now[0])
        self.assertFalse(self.e.auto)
        self.tick(self.low+.28*self.a);self.assertFalse(self.b.sent)

if __name__=='__main__':unittest.main()
