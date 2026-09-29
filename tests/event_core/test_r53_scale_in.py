"""Real SCENARIO_V2 -> Engine -> broker; no injected ready Decisions."""
import copy
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from event_core.engine import Engine
from event_core.model import Config, Bar, PROFILES
from event_core.store import Store
from fakes import FakeBroker
from test_r5_scenarios import lane, BASE


class ScaleInTests(unittest.TestCase):
    def setup_engine(self, mode='NORMAL', side=1):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=[float(BASE)];self.b=FakeBroker(lambda:self.now[0]);self.side=side
        self.store=Store(Path(self.tmp.name)/'db');self.addCleanup(self.store.close)
        bars=lane('RANGE')
        if side<0:bars=[Bar(b.time,2.202-b.open,2.202-b.low,2.202-b.high,2.202-b.close) for b in bars]
        self.b.bar_data=bars
        self.b.ctx_data=[replace(b,time=BASE-(len(bars)-i)*900) for i,b in enumerate(bars)]
        self.b.h1_data=[replace(b,time=BASE-(len(bars)-i)*3600) for i,b in enumerate(bars)]
        self.b.m1_data=[Bar(BASE-(20-i)*60,1.101,1.10103,1.10097,1.101) for i in range(20)]
        self.b.bid=1.101;self.b.ask=1.10101
        self.e=Engine(self.b,self.store,lambda:self.now[0])
        cfg=dict(engine_mode='SCENARIO_V2',mode=mode,lot_cap=.01,probe_lot_cap=.01,volume_mode='FIXED',fee_per_lot=0,cooldown_sec=0)
        self.e.command('configure',dict(command_id=str(uuid.uuid4()),config=cfg))
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True,accept_pending_profile=True,config=cfg))
        self.tick(1.101)
        scenario=next(s for s in self.e.compute.scenarios.values() if s['type']=='DIRECT_BREAKOUT' and s['side']==side)
        self.a=scenario['pattern']['atr'];t=scenario['activation']
        self.tick(t+side*.03*self.a);self.tick(t+side*.06*self.a)
        self.assertEqual(len(self.b.sent),1,self.e.execution)

    def tick(self, bid):
        self.now[0]+=1;self.b.bid=bid;self.b.ask=bid+.00001
        return self.e.step()

    def cycle(self):
        last=self.e.campaign['last_entry'];side=self.side;a=self.a
        # A new micro high/low is observed before the pullback begins.
        peak=last+side*1.1*a
        self.tick(peak)
        trough=peak-side*(PROFILES[self.e.config.mode].pullback_atr+.02)*a
        self.tick(trough)
        self.tick(trough+side*.06*a)
        self.tick(peak+side*.04*a)

    def test_actual_engine_one_two_three_in_both_modes_and_directions(self):
        for mode in ('NORMAL','SCALP'):
            for side in (1,-1):
                with self.subTest(mode=mode,side=side):
                    self.setup_engine(mode,side)
                    frozen=copy.deepcopy(self.e.campaign['forecast_at_entry'])
                    for count in (2,3):
                        self.cycle()
                        self.assertEqual(len(self.b._positions),count,self.e.execution)
                        self.assertEqual(len(self.e.campaign['position_ids']),count)
                        self.assertLessEqual(self.b.sent[-1].total_risk,self.e.campaign['budget'])
                    self.assertEqual(len({p.event_id for p in self.b.sent}),3)
                    self.assertEqual(self.e.campaign['forecast_at_entry'],frozen)
                    for _ in range(4):self.tick(self.b.bid)
                    self.assertEqual(len(self.b.sent),3)
                    expected=sum(p['profit'] for p in self.b.positions())
                    self.e.command('close',dict(command_id=str(uuid.uuid4())))
                    self.tick(self.b.bid);self.e.history_time=0
                    state=self.tick(self.b.bid)
                    self.assertEqual(len(self.b._positions),0)
                    self.assertEqual(state['all']['count'],3)
                    self.assertAlmostEqual(state['all']['net'],expected,places=7)

    def test_no_add_from_rising_price_without_new_pullback(self):
        self.setup_engine()
        last=self.b.bid
        for x in (.3,.6,.9,1.2):self.tick(last+x*self.a)
        self.assertEqual(len(self.b.sent),1)

    def test_pause_and_fresh_feed_gap_cancel_previously_armed_add(self):
        for interruption in ('pause','gap'):
            with self.subTest(interruption=interruption):
                self.setup_engine('SCALP')
                peak=self.e.campaign['last_entry']+self.a
                self.tick(peak);self.tick(peak-.25*self.a);self.tick(peak-.15*self.a)
                if interruption=='pause':
                    self.e.command('pause',dict(command_id=str(uuid.uuid4())))
                    self.tick(peak+.03*self.a)
                    self.e.command('play',dict(command_id=str(uuid.uuid4())))
                else:self.now[0]+=15
                self.tick(peak+.04*self.a)
                self.assertEqual(len(self.b.sent),1)

    def test_completed_source_cannot_authorize_an_add_after_pause(self):
        self.setup_engine()
        source=self.e.compute.scenarios[self.e.campaign['scenario_id']]
        target=source['target']
        self.tick(target+.01*self.a)
        self.assertEqual(source['status'],'TARGET_REACHED')
        self.e.command('pause',dict(command_id=str(uuid.uuid4())))
        self.e.command('play',dict(command_id=str(uuid.uuid4())))
        for x in (-.8,-.7,-1.1,-1.0,-.66):self.tick(target+x*self.a)
        self.assertEqual(len(self.b.sent),1)

    def test_overshot_micro_break_allows_a_later_independent_sequence(self):
        self.setup_engine()
        last=self.e.campaign['last_entry'];a=self.a
        for x in (1.1,.7,.8,1.4):self.tick(last+x*a)
        self.assertEqual(len(self.b.sent),1,'Overshot crossing must not be chased')
        for x in (1.9,1.5,1.6,1.94):self.tick(last+x*a)
        self.assertEqual(len(self.b.sent),2,self.e.execution)

    def test_restart_does_not_reuse_armed_continuation(self):
        self.setup_engine('SCALP')
        last=self.e.campaign['last_entry'];a=self.a
        for x in (1.1,.8,.9):self.tick(last+x*a)
        self.e.save();self.e=Engine(self.b,self.store,lambda:self.now[0])
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True))
        self.tick(last+1.14*a)
        self.assertEqual(len(self.b.sent),1)

    def test_buy_add_cannot_fill_beyond_target_after_spread_changes(self):
        self.setup_engine()
        source=self.e.compute.scenarios[self.e.campaign['scenario_id']]
        target=source['target1'];peak=target-.20*self.a
        for price in (peak,peak-.40*self.a,peak-.30*self.a):self.tick(price)
        original=self.b.quote
        def widening_quote(symbol):
            quote=original(symbol)
            if self.e.compute.continuation.emitted:
                return replace(quote,ask=quote.bid+.20*self.a)
            return quote
        self.b.quote=widening_quote
        self.tick(peak+.04*self.a)
        self.assertEqual(len(self.b.sent),1,'Final executable ask is beyond original target')

    def test_no_add_if_disabled_or_budget_exhausted(self):
        for guard in ('dynamic','budget'):
            with self.subTest(guard=guard):
                self.setup_engine()
                if guard=='dynamic':self.e.config.dynamic_adds=False
                else:self.e.campaign['budget']=self.e.campaign['initial_risk']*1.01
                self.cycle()
                self.assertEqual(len(self.b.sent),1)
