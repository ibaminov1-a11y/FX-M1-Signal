import copy
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from event_core.engine import Engine
from event_core.model import Config, Bar
from event_core.store import Store
from event_core.server import create_app
from event_core.replay import ReplayBroker
from fakes import FakeBroker
from test_r5_scenarios import lane, BASE


class V2IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now=[float(BASE)];self.dir=tempfile.TemporaryDirectory();self.store=Store(Path(self.dir.name)/'db')
        self.b=FakeBroker(lambda:self.now[0]);self.b.balance=100000
        bars=lane('RANGE');self.b.bar_data=bars
        self.b.ctx_data=[replace(b,time=BASE-(len(bars)-i)*900) for i,b in enumerate(bars)]
        self.b.h1_data=[replace(b,time=BASE-(len(bars)-i)*3600) for i,b in enumerate(bars)]
        self.b.m1_data=[Bar(BASE-(20-i)*60,1.101,1.10103,1.10097,1.101) for i in range(20)]
        self.b.live_bar_data=Bar(BASE,1.101,1.1011,1.1009,1.101)
        self.b.bid=1.101;self.b.ask=1.10101
        self.e=Engine(self.b,self.store,lambda:self.now[0])
        self.e.command('configure',dict(command_id=str(uuid.uuid4()),config=dict(engine_mode='SCENARIO_V2',lot_cap=.1,probe_lot_cap=.1,volume_mode='FIXED',fee_per_lot=0,cooldown_sec=0)))
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True,accept_pending_profile=True,config=dict(engine_mode='SCENARIO_V2',lot_cap=.1,probe_lot_cap=.1,volume_mode='FIXED',fee_per_lot=0,cooldown_sec=0)))
    def tearDown(self):self.store.close();self.dir.cleanup()
    def tick(self,bid=None):
        self.now[0]+=1
        if bid is not None:self.b.bid=bid;self.b.ask=bid+.00001
        return self.e.step()
    def entry(self):
        s=self.tick();self.assertEqual(s['forecast'].get('map_version'),3,'SCENARIO_V2 must use the new library')
        core=self.e.compute
        d=next(x for x in core.scenarios.values() if x['type']=='DIRECT_BREAKOUT' and x['side']==1)
        t=d['activation'];a=d['pattern']['atr']
        self.tick(t+.03*a)
        return self.tick(t+.06*a)
    def test_actual_engine_opens_exact_lot_and_records_scenario_identity(self):
        state=self.entry()
        self.assertEqual(len(self.b.sent),1,self.e.execution)
        self.assertEqual(self.b._positions[0]['volume'],.1)
        campaign=state['campaign']
        self.assertTrue(campaign.get('scenario_id'))
        frozen=copy.deepcopy(campaign['forecast_at_entry'])
        self.tick()
        self.assertEqual(self.e.campaign['forecast_at_entry'],frozen)
        self.assertGreater(len(self.store.scenario_snapshots(self.e.market_scope())),0)
        self.assertTrue(self.store.scenario_snapshots(self.e.market_scope(),snapshot_id=campaign['snapshot_id']))
    def test_explicit_lot_change_waits_inside_running_auto(self):
        self.entry()
        self.e.command('configure',dict(command_id=str(uuid.uuid4()),allow_deferred=True,accept_pending_profile=True,
            preserve_auto=True,config=dict(lot_cap=.5,probe_lot_cap=.5)))
        self.assertTrue(self.e.auto)
        self.assertEqual(self.e.config.lot_cap,.1)
        self.assertEqual(self.e.pending_config['lot_cap'],.5)
        self.assertTrue(self.e.pending_config['approved'])
        self.assertEqual(self.b._positions[0]['volume'],.1)
    def test_history_endpoint_is_read_only_and_paginated(self):
        self.tick();app=create_app(self.e,'x'*40).test_client()
        headers={'Authorization':'Bearer '+'x'*40,'X-FXM1-Client':'R5'}
        r=app.get('/ec/history?tf=M5&limit=20',headers=headers)
        self.assertEqual(r.status_code,200)
        rows=r.get_json()['bars'];self.assertEqual(len(rows),20)
        older=app.get('/ec/history?tf=M5&limit=20&before='+str(rows[0]['time']),headers=headers).get_json()['bars']
        self.assertLess(older[-1]['time'],rows[0]['time'])
        self.assertEqual(len(self.b.sent),0)
        archive=app.get('/ec/scenarios?limit=20',headers=headers)
        self.assertEqual(archive.status_code,200);self.assertTrue(archive.get_json()['snapshots'])
    def test_old_client_cannot_misinterpret_new_map(self):
        self.tick();client=create_app(self.e,'x'*40).test_client()
        r=client.get('/ec/state',headers={'Authorization':'Bearer '+'x'*40})
        self.assertEqual(r.status_code,426)
    def test_lost_feed_keeps_auto_but_no_entry_and_exposes_cached_map_as_stale(self):
        self.tick();self.b.quote_age=30
        s=self.tick()
        self.assertTrue(s['auto']);self.assertFalse(s['entry_gate']['allowed']);self.assertEqual(len(self.b.sent),0)
        self.assertTrue(s['forecast'].get('stale'))
        self.assertEqual(s['forecast'].get('map_version'),3)


class ReplayV2Tests(unittest.TestCase):
    def test_same_engine_replay_builds_all_timeframes_and_forming_bar(self):
        from event_core.model import Quote
        b=ReplayBroker(dict(symbol='EURUSD',currency_profit='USD',contract_size=100000,margin_per_lot=1000,
            point=.00001,digits=5,tick_size=.00001,stops_level=0,volume_min=.01,volume_max=100,volume_step=.01),
            Config(engine_mode='SCENARIO_V2',fee_per_lot=0),1000)
        b.advance(Quote(BASE*1000,1.1,1.10001))
        b.advance(Quote((BASE+301)*1000,1.101,1.10101))
        self.assertIn('H1',b.barsets)
        self.assertIn('M1',b.barsets)
        self.assertTrue(callable(getattr(b,'current_bar',None)))
        self.assertEqual(b.current_bar('EURUSD','M5').time,BASE+300)
