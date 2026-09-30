"""Real ScenarioCore/Engine on causal quote sequences, no ready-Decision injection."""
import copy
import tempfile
import unittest
import uuid
from pathlib import Path
from event_core.engine import Engine
from event_core.model import Bar, Config, Quote
from event_core.scenarios.core import ScenarioCore
from event_core.store import Store
from fakes import FakeBroker, wave

BASE=1800000000


def reflected(bars):
    return [Bar(b.time,2.212-b.open,2.212-b.low,2.212-b.high,2.212-b.close,b.volume) for b in bars]


class MicroBroker(FakeBroker):
    def __init__(self,clock,side=1):
        super().__init__(clock)
        self.m1_data=wave(BASE,tf=60,trend=.00006)
        self.bar_data=wave(BASE,tf=300,trend=.00006)
        self.ctx_data=wave(BASE,tf=900,trend=.00006)
        self.h1_data=wave(BASE,tf=3600,trend=.00006)
        if side<0:
            for key in ('m1_data','bar_data','ctx_data','h1_data'):setattr(self,key,reflected(getattr(self,key)))
        self.bid=1.106;self.ask=self.bid+.00001
    def current_bar(self,symbol,tf):
        span={'M1':60,'M5':300,'M15':900,'M30':1800,'H1':3600,'H4':14400,'D1':86400,'W1':604800}.get(tf,2592000)
        return Bar(int(self.clock())//span*span,self.bid,self.ask,self.bid,self.bid,1)


class FastScalpTests(unittest.TestCase):
    def start(self,side=1,mode='SCALP',tf='M1'):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'db');self.addCleanup(self.store.close)
        self.now=[float(BASE)];self.b=MicroBroker(lambda:self.now[0],side);self.side=side
        self.e=Engine(self.b,self.store,lambda:self.now[0])
        cfg=dict(engine_mode='SCENARIO_V2',mode=mode,timeframe=tf,lot_cap=.01,probe_lot_cap=.01,volume_mode='FIXED',fee_per_lot=0,cooldown_sec=0)
        self.e.command('configure',dict(command_id=str(uuid.uuid4()),config=cfg))
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True,accept_pending_profile=True,config=cfg))
        self.tick(0)
    def tick(self,delta):
        self.now[0]+=1;self.b.bid=1.106+self.side*delta;self.b.ask=self.b.bid+.00001
        return self.e.step()
    def first(self):
        for delta in (.00030,.00022,.00024,.00031):state=self.tick(delta)
        return state
    def test_fresh_micro_sequence_opens_first_buy_and_sell_away_from_old_levels(self):
        for side in (1,-1):
            with self.subTest(side=side):
                self.start(side);state=self.first()
                self.assertEqual(len(self.b.sent),1,self.e.execution)
                self.assertEqual(self.b.sent[0].side,side)
                self.assertEqual(self.e.campaign['timeframe'],'M1')
                self.assertEqual(state['forecast']['execution_setup']['engine'],'SCALP_MICRO_V1')
                self.assertTrue(self.e.campaign['forecast_at_entry']['entry_scenario_id'])
    def test_one_two_three_positions_have_new_events_and_fixed_initial_forecast(self):
        for side in (1,-1):
            with self.subTest(side=side):
                self.start(side);self.first()
                self.assertEqual(len(self.b.sent),1,self.e.execution)
                frozen=copy.deepcopy(self.e.campaign['forecast_at_entry'])
                for count,path in ((2,(.00042,.00037,.00039,.00043)),(3,(.00054,.00049,.00051,.00055))):
                    for delta in path:self.tick(delta)
                    self.assertEqual(len(self.b.sent),count,self.e.execution)
                    self.assertLessEqual(self.b.sent[-1].total_risk,self.e.campaign['budget'])
                self.assertEqual(len({p.event_id for p in self.b.sent}),3)
                self.assertEqual(self.e.campaign['forecast_at_entry'],frozen)
    def test_resumption_tick_can_itself_cross_the_observed_micro_level(self):
        self.start()
        for delta in (.00016,.00009,.00017):self.tick(delta)
        self.assertEqual(len(self.b.sent),1,self.e.execution)
    def test_no_trade_from_direction_or_uninterrupted_price_move(self):
        self.start()
        for delta in (.00006,.00012,.00018,.00024):self.tick(delta)
        self.assertEqual(len(self.b.sent),0)
    def test_fast_path_is_not_enabled_in_normal_or_other_entry_frames(self):
        for mode,tf in (('NORMAL','M1'),('SCALP','M5'),('NORMAL','M5')):
            with self.subTest(mode=mode,tf=tf):
                self.start(mode=mode,tf=tf);state=self.first()
                self.assertNotIn('execution_setup',state['forecast'])
    def test_pause_cancels_armed_micro_entry(self):
        self.start();self.tick(.00016);self.tick(.00009)
        self.e.command('pause',dict(command_id=str(uuid.uuid4())))
        self.tick(.00017)
        self.e.command('play',dict(command_id=str(uuid.uuid4())))
        self.tick(.00018)
        self.assertEqual(len(self.b.sent),0)

    def test_repeated_quote_cannot_duplicate_a_confirmed_order(self):
        self.start();self.first();fixed=self.b.quote('EURUSD')
        self.b.quote=lambda symbol:fixed
        for _ in range(4):self.now[0]+=.1;self.e.step()
        self.assertEqual(len(self.b.sent),1)

    def test_feed_gap_requires_new_sequence(self):
        self.start();self.tick(.00030);self.tick(.00022)
        self.now[0]+=15
        self.tick(.00031);self.tick(.00032)
        self.assertEqual(len(self.b.sent),0)

    def test_restart_and_enable_do_not_resurrect_armed_micro_entry(self):
        self.start();self.tick(.00030);self.tick(.00022);self.e.save()
        self.e=Engine(self.b,self.store,lambda:self.now[0])
        self.assertFalse(self.e.auto)
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True))
        self.tick(.00031);self.tick(.00032)
        self.assertEqual(len(self.b.sent),0)

    def test_enable_does_not_reuse_observations_collected_with_auto_off(self):
        self.start()
        self.e.command('disable',dict(command_id=str(uuid.uuid4())))
        self.tick(.00030);self.tick(.00022)
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True))
        self.tick(.00031);self.tick(.00032)
        self.assertEqual(len(self.b.sent),0)

    def test_conflicting_context_cannot_open_from_an_old_armed_sequence(self):
        self.start();self.tick(.00030);self.tick(.00022)
        self.b.ctx_data=reflected(self.b.ctx_data)
        state=self.tick(.00031)
        self.assertEqual(len(self.b.sent),0)
        self.assertEqual(state['forecast']['execution_setup']['stage'],'WAIT_CONTEXT')

    def test_overshot_crossing_is_not_chased(self):
        self.start();self.tick(.00030);self.tick(.00022);self.tick(.00040)
        self.assertEqual(len(self.b.sent),0)
        for delta in (.00055,.00047,.00056):self.tick(delta)
        self.assertEqual(len(self.b.sent),1,self.e.execution)

    def test_risk_margin_and_foreign_positions_still_block_first_entry(self):
        for guard in ('risk','margin','foreign'):
            with self.subTest(guard=guard):
                self.start()
                if guard=='risk':self.b.balance=1.
                elif guard=='margin':self.b.calc_margin=lambda *args:1000000.
                else:self.b._positions=[dict(ticket=1,identifier=1,magic=0,symbol='EURUSD',side=1,volume=.01,price_open=1.106,sl=1.1,profit=0.,swap=0.,time=BASE,comment='manual')]
                self.first()
                self.assertEqual(len(self.b.sent),0,self.e.execution)

    def test_pending_unknown_execution_does_not_retry_or_add(self):
        self.start();self.b.visible=False;self.b.result='UNKNOWN';self.first()
        self.assertEqual(len(self.b.sent),1)
        for delta in (.00042,.00037,.00039,.00043):self.tick(delta)
        self.assertEqual(len(self.b.sent),1)
        self.assertTrue(self.e.recovery or self.store.pending())

    def test_unprofitable_disabled_or_budget_exhausted_campaign_cannot_add(self):
        for guard in ('net','disabled','budget'):
            with self.subTest(guard=guard):
                self.start();self.first();self.assertEqual(len(self.b.sent),1)
                if guard=='net':self.b._positions[0]['swap']=-100.
                elif guard=='disabled':self.e.config.dynamic_adds=False
                else:self.e.campaign['budget']=self.e.campaign['initial_risk']*1.01
                for delta in (.00042,.00037,.00039,.00043):self.tick(delta)
                self.assertEqual(len(self.b.sent),1,self.e.execution)

    def test_emergency_closes_campaign_and_cancels_further_entries(self):
        self.start();self.first()
        self.e.command('emergency',dict(command_id=str(uuid.uuid4())))
        for delta in (.00042,.00037,.00039,.00043):self.tick(delta)
        self.assertEqual(len(self.b.sent),1)
        self.assertFalse(self.b.positions())
        self.assertTrue(self.e.emergency)

    def test_completed_source_cannot_authorize_new_micro_addition(self):
        self.start();self.first()
        source=self.e.compute.scenarios[self.e.campaign['scenario_id']]
        source['status']='TARGET_REACHED'
        for delta in (.00042,.00037,.00039,.00043):self.tick(delta)
        self.assertEqual(len(self.b.sent),1)

    def test_preview_labels_the_frozen_micro_trigger_not_the_old_macro_level(self):
        self.start();self.tick(.00030);state=self.tick(.00022)
        setup=state['forecast']['execution_setup'];route=state['forecast']['scenarios'][0]
        self.assertAlmostEqual(setup['trigger'],1.10630)
        self.assertAlmostEqual(route['event_level'],1.10630)
        self.assertTrue(route['micro'])
        self.assertFalse(route['entry_ready'])

    def test_terminal_blocked_confirmation_rearms_for_a_new_observed_sequence(self):
        for terminal,delta in (('TARGET_REACHED',.00065),('FAILED',.00015)):
            with self.subTest(terminal=terminal):
                self.start();self.e.config.session_filter=True;self.e.config.allowed_sessions='ASIA'
                self.first();old=self.e.compute.micro.current
                self.assertEqual(len(self.b.sent),0)
                state=self.tick(delta)
                self.assertEqual(old['status'],terminal)
                self.assertEqual(state['forecast']['execution_setup']['stage'],'PROGRESS')
                self.e.config.session_filter=False
                for move in (delta+.00030,delta+.00022,delta+.00031):self.tick(move)
                self.assertEqual(len(self.b.sent),1,self.e.execution)
                self.assertNotEqual(self.e.campaign['scenario_id'],old['scenario_id'])

    def test_expired_entry_window_cannot_stay_confirmed_or_reuse_old_crossing(self):
        self.start();self.e.config.session_filter=True;self.e.config.allowed_sessions='ASIA'
        self.first();old=self.e.compute.micro.current
        for _ in range(11):state=self.tick(.00031)
        self.assertEqual(state['forecast']['execution_setup']['stage'],'PROGRESS')
        self.e.config.session_filter=False
        self.tick(.00031)
        self.assertEqual(len(self.b.sent),0,'Expired crossing cannot be retried after a guard clears')
        for delta in (.00061,.00053,.00062):self.tick(delta)
        self.assertEqual(len(self.b.sent),1,self.e.execution)
        self.assertNotEqual(self.e.campaign['scenario_id'],old['scenario_id'])

    def test_opposite_micro_confirmation_closes_before_any_reverse_entry(self):
        self.start();self.first()
        old_ticket=self.b.positions()[0]['ticket']
        self.b.bar_data=reflected(self.b.bar_data);self.b.ctx_data=reflected(self.b.ctx_data)
        for delta in (.00030,.00022,.00027,.00024,.00021):self.tick(delta)
        self.assertIn(old_ticket,self.b.closed,self.e.execution)
        self.assertEqual(len(self.b.sent),1,'Opposite confirmation must close the original campaign first')
        self.assertFalse(self.b.positions())
