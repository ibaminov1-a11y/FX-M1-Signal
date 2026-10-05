"""Real Engine/ScenarioCore paths; fake only the external broker transport."""
import copy, calendar, tempfile, unittest, uuid
from pathlib import Path
from dataclasses import asdict, replace
from fakes import FakeBroker, wave
from event_core.engine import Engine
from event_core.model import Config, Quote, Bar, atr, TF_SECONDS
from event_core.store import Store
from test_r56_multiframe import IndependentBroker, NOW, FRAMES

class TradingBroker(IndependentBroker):
    def __init__(self,clock,side=1):
        super().__init__(clock)
        self.bid=1.106; self.ask=self.bid+.00001
        self.frames['M10']=wave(NOW,tf=600)
        for tf in TF_SECONDS:
            original=self.frames[tf]
            bars=wave(NOW,tf=60,trend=.00006)
            if side<0:bars=[Bar(x.time,2.212-x.open,2.212-x.low,2.212-x.high,2.212-x.close,10) for x in bars]
            self.frames[tf]=[replace(b,time=t.time) for b,t in zip(bars,original)]
    def current_bar(self,symbol,tf):
        t=calendar.timegm((2026,9,1,0,0,0)) if tf=='MN1' else int(self.clock())//TF_SECONDS[tf]*TF_SECONDS[tf]
        return Bar(t,self.bid,self.ask,self.bid,self.bid,1)

class R7RuntimeTests(unittest.TestCase):
    def start(self,mode='SCALP',tf='M5',side=1):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        s=Store(Path(tmp.name)/'db');self.addCleanup(s.close)
        self.now=[float(NOW)];self.b=TradingBroker(lambda:self.now[0],side);self.side=side
        cfg=dict(engine_mode='SCENARIO_V2',runtime_model='R7',timeframe=tf,mode=mode,fee_per_lot=0,cooldown_sec=0,lot_cap=.01)
        s.save('engine',{'config':cfg});self.e=Engine(self.b,s,lambda:self.now[0])
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True,accept_pending_profile=True,config=cfg))
        self.tick(0);self.a=atr(self.b.frames[tf])
    def tick(self,delta):
        self.now[0]+=1;self.b.bid=1.106+self.side*delta;self.b.ask=self.b.bid+.00001
        return self.e.step()
    def first(self):
        for d in (2.,1.45,1.55,2.04):s=self.tick(d*self.a)
        return s
    def test_both_modes_all_native_frames_first_buy_sell(self):
        for mode in ('NORMAL','SCALP'):
            for tf in TF_SECONDS:
                for side in (1,-1):
                    with self.subTest(mode=mode,tf=tf,side=side):
                        self.start(mode,tf,side);s=self.first()
                        self.assertEqual(len(self.b.sent),1,self.e.execution)
                        self.assertEqual(self.b.sent[0].side,side)
                        self.assertEqual(self.e.campaign['timeframe'],tf)
                        self.assertEqual(s['forecast']['execution_setup']['timeframe'],tf)
                        frozen=copy.deepcopy(self.e.campaign['forecast_at_entry'])
                        initial_stop=self.b.sent[0].stop
                        self.tick(2.2*self.a)
                        self.assertEqual(len(self.b.sent),1,'Management must not invent a new entry')
                        self.assertGreaterEqual((self.b.positions()[0]['sl']-initial_stop)*side,-1e-10)
                        self.e.save();self.e=Engine(self.b,self.e.store,lambda:self.now[0])
                        self.assertFalse(self.e.auto,'Restart must preserve management without AUTO consent')
                        self.tick(2.2*self.a)
                        self.assertEqual(self.e.campaign['forecast_at_entry'],frozen)
                        self.e.command('emergency',dict(command_id=str(uuid.uuid4())))
                        self.tick(2.2*self.a)
                        self.now[0]+=1.2;state=self.tick(2.2*self.a)
                        self.assertFalse(self.b.positions())
                        self.assertIsNone(self.e.campaign,state['execution'])
                        self.assertEqual(state['all']['count'],1)
                        self.assertEqual(len(self.b.sent),1)
                        self.assertFalse(self.e.auto)
                        self.assertTrue(self.e.emergency)
    def test_no_entry_without_pullback_no_duplicate_and_pause(self):
        for mode in ('NORMAL','SCALP'):
            self.start(mode)
            for d in (.5,1,1.5,2):self.tick(d*self.a)
            self.assertFalse(self.b.sent)
            self.tick(1.45*self.a)
            self.e.command('pause',dict(command_id=str(uuid.uuid4())))
            self.tick(2.04*self.a);self.assertFalse(self.b.sent)
    def test_additions_have_distinct_events_frozen_forecast_and_shared_budget(self):
        for mode in ('NORMAL','SCALP'):
            for side in (1,-1):
                self.start(mode,side=side);self.first()
                self.assertEqual(len(self.b.sent),1,self.e.execution)
                frozen=copy.deepcopy(self.e.campaign['forecast_at_entry'])
                for base in (3.0,3.75):
                    for d in (base,base-(.45 if mode=='NORMAL' else .22),base-.1,base+.04):self.tick(d*self.a)
                self.assertEqual(len(self.b.sent),3,self.e.execution)
                self.assertEqual(len({p.event_id for p in self.b.sent}),3)
                self.assertEqual(self.e.campaign['forecast_at_entry'],frozen)
                self.assertTrue(all(p.total_risk<=self.e.campaign['budget'] for p in self.b.sent))
                fixed=self.b.quote('EURUSD');self.b.quote=lambda s:fixed
                for _ in range(3):self.e.step()
                self.assertEqual(len(self.b.sent),3)
    def test_restart_requires_new_sequence(self):
        self.start();self.tick(2*self.a);self.tick(1.45*self.a);self.e.save()
        self.e=Engine(self.b,self.e.store,lambda:self.now[0]);self.assertFalse(self.e.auto)
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True))
        self.tick(2.04*self.a);self.assertFalse(self.b.sent)
