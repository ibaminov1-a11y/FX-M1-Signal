"""Contract -> real Engine dispatch. External MT5 is the only simulated part."""
import copy
import unittest
from dataclasses import replace
import test_r74_execution as baseline
from event_core.model import Config,Blocked
from event_core.risk import plan_order


class PinnedExecutionTests(baseline.StableExecutionTests):
    def setUp(self):
        try:Config(entry_model='PINNED_V1').validate()
        except Blocked:self.fail('PINNED_ENTRY_MODEL_NOT_CONNECTED')
        super().setUp()
        cfg=self.e.config
        self.e.config=replace(cfg,entry_model='PINNED_V1')
        self.cfg['entry_model']='PINNED_V1'
        from event_core.compute_core import make_compute
        self.e.compute=make_compute(self.e.config)

    def test_first_resumption_crossing_executes_second_buy_and_sell(self):
        for side in (1,-1):
            with self.subTest(side=side):
                if side<0:self.setUp()
                self.enter(side)
                frozen=copy.deepcopy(self.e.campaign['forecast_at_entry'])
                zone=self.low if side>0 else self.high
                for d in (.5,1.,.6,1.04):state=self.tick(zone+side*d*self.a)
                self.assertEqual(len(self.b.sent),2,self.e.execution)
                self.assertEqual(frozen,self.e.campaign['forecast_at_entry'])
                self.assertEqual(len({p.event_id for p in self.b.sent}),2)
                self.assertEqual(state['forecast']['execution_plan']['plan_id'],self.e.campaign['scenario_id'])

    def test_plan_does_not_change_after_opposite_candidate_rank_increase(self):
        self.tick(self.low+.5*self.a)
        pin=copy.deepcopy(self.e.compute.commitment.state())
        self.assertTrue(pin['plan_id'])
        for d in (.7,.9,.4,.5):self.tick(self.low+d*self.a)
        self.assertEqual(self.e.compute.commitment.state()['plan_id'],pin['plan_id'])
        self.assertEqual(self.e.compute.commitment.state()['original'],pin['original'])
        self.assertFalse(self.b.sent)

    def test_only_pinned_root_may_supply_initial_order(self):
        state=self.tick(self.low+.5*self.a)
        pin=self.e.compute.commitment.ident
        for d in (.04,.20,.28):state=self.tick(self.low+d*self.a)
        self.assertEqual(len(self.b.sent),1,self.e.execution)
        self.assertEqual(self.e.campaign['scenario_id'],pin)
        self.assertEqual(self.e.campaign['forecast_at_entry']['execution_plan']['plan_id'],pin)

if __name__=='__main__':unittest.main()

class PinnedLifecycleTests(unittest.TestCase):
    def test_restart_and_pause_keep_contract_but_not_authority_to_send(self):
        import uuid
        from event_core.engine import Engine
        import test_r75_ten_positions as fixture
        f=fixture.SeriesFixture()
        try:
            f.tick(f.zone+.5*f.a)
            original=copy.deepcopy(f.e.compute.commitment.state())
            f.e.command('pause',dict(command_id=str(uuid.uuid4())))
            for d in (.04,.20,.24):f.tick(f.zone+d*f.a)
            self.assertFalse(f.b.sent)
            self.assertEqual(f.e.compute.commitment.ident,original['plan_id'])
            from event_core.portfolio import Portfolio
            reloaded=Portfolio(f.b,f.store,lambda:f.t[0],entry_model='PINNED_V1')
            self.assertFalse(reloaded.auto)
            self.assertEqual(reloaded.compute.commitment.ident,original['plan_id'])
            self.assertEqual(reloaded.compute.commitment.original,original['original'])
            self.assertFalse(any(s.get('entry_ready') for s in reloaded.compute.scenarios.values()))
        finally:f.close()
