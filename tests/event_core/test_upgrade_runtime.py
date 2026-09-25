"""Upgrade from saved LEGACY state, never a fresh-install-only test."""
import copy
import tempfile
import unittest
import uuid
from pathlib import Path
from dataclasses import asdict
from event_core.engine import Engine
from event_core.model import Config, Decision, Blocked
from event_core.store import Store
from event_core.mt5_adapter import MT5Broker, MAGIC
from fakes import FakeBroker


class UpgradeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.now=1800000000.
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'state.db')
        self.b=FakeBroker(lambda:self.now)
        self.e=Engine(self.b,self.store,lambda:self.now)
        self.e.config=Config(engine_mode='LEGACY',fee_per_lot=0,approved=True,cooldown_sec=0)
        self.e._refresh(self.now)
        self.e.info=self.b.symbol('EURUSD');self.e.quote=self.b.quote('EURUSD')
        d=Decision('SELL','ENTRY_READY','old campaign','old-entry',-1,1.1034,1.10301,1.1034,.0005,int(self.now*1000))
        self.e._entry(d,self.now)
        self.old=copy.deepcopy(self.e.campaign)
        self.want=dict(engine_mode='COMPUTE_V1',timeframe='M5',mode='NORMAL',lot_cap=.01,probe_lot_cap=.01,cooldown_sec=0)

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def command(self, name, **data):
        return self.e.command(name,dict(command_id=str(uuid.uuid4()),**data))

    def queue(self):
        return self.command('configure',config=self.want,allow_deferred=True)

    def enable(self):
        return self.command('enable',confirmation='ENABLE_DEMO',accept_pending_profile=True,allow_wait=True)

    def test_busy_campaign_queues_profile_without_modifying_its_risk_or_levels(self):
        out=self.queue()
        self.assertTrue(out['ok'])
        self.assertEqual(self.e.config.engine_mode,'LEGACY')
        self.assertEqual(self.e.campaign,self.old)
        self.assertEqual(self.e.snapshot()['pending_config']['engine_mode'],'COMPUTE_V1')

    def test_auto_can_be_on_while_new_entries_wait_for_profile_and_old_campaign(self):
        self.queue();out=self.enable()
        self.assertTrue(out['auto']);self.assertFalse(out['paused'])
        s=self.e.snapshot()
        self.assertFalse(s['entry_gate']['allowed'])
        self.assertIn('PROFILE_PENDING',s['entry_gate']['blocks'])
        with self.assertRaises(Blocked):
            self.e._entry(Decision('SELL','ENTRY_READY','add','new',-1,1.1034,1.10301,1.1034,.0005,int(self.now*1000)),self.now)
        self.assertEqual(len(self.b.sent),1)

    def test_profile_applies_only_after_closed_volume_is_confirmed_then_keeps_user_auto(self):
        self.queue();self.enable()
        self.b.close_position(self.b._positions[0]);self.now+=1.2
        self.e.step()
        s=self.e.snapshot()
        self.assertIsNone(s['campaign'])
        self.assertEqual(s['config']['engine_mode'],'COMPUTE_V1')
        self.assertTrue(s['auto']);self.assertIsNone(s['pending_config'])
        self.assertEqual(len(self.b.sent),1,'Changing profile cannot backfill an entry')
        self.assertEqual(s['forecast'].get('map_version'),2)

    def test_zero_positions_with_missing_history_never_discards_campaign_or_unlocks(self):
        self.queue();self.enable()
        self.b._positions=[];self.now+=1.2
        self.e.step();s=self.e.snapshot()
        self.assertIsNotNone(s['campaign'])
        self.assertEqual(s['campaign_state'],'RECONCILING')
        self.assertFalse(s['entry_gate']['allowed']);self.assertTrue(s['auto'])
        self.assertEqual(len(self.b.sent),1)

    def test_history_by_position_resolves_closed_old_campaign_and_money_journal(self):
        self.queue();self.enable()
        self.b.close_position(self.b._positions[0]);complete=copy.deepcopy(self.b.deals)
        self.b.deals=self.b.deals[:1]
        calls=[]
        def lookup(pid):
            calls.append(pid);return [d for d in complete if d['position_id']==pid]
        self.b.history_position=lookup
        self.now+=1.2;self.e.step()
        self.assertIsNone(self.e.campaign)
        self.assertEqual(self.e.snapshot()['all']['count'],1)
        self.assertEqual(self.e.config.engine_mode,'COMPUTE_V1')
        self.assertTrue(calls)

    def test_pause_during_queued_change_does_not_resume_when_profile_applies(self):
        self.queue();self.enable();self.command('pause')
        self.b.close_position(self.b._positions[0]);self.now+=1.2;self.e.step()
        self.assertTrue(self.e.paused)
        self.assertFalse(self.e.snapshot()['entry_gate']['allowed'])
        self.assertEqual(len(self.b.sent),1)

    def test_restarting_with_pending_profile_never_restores_auto_or_approval(self):
        self.queue();self.enable()
        restarted=Engine(self.b,self.store,lambda:self.now)
        self.assertFalse(restarted.auto);self.assertTrue(restarted.paused)
        self.assertIsNotNone(restarted.snapshot()['pending_config'])
        self.assertFalse(restarted.snapshot()['pending_config']['approved'])

    def test_emergency_is_not_bypassed_by_armed_wait(self):
        self.queue();self.command('emergency')
        with self.assertRaises(Blocked):self.enable()
        self.assertFalse(self.e.auto)

    def test_allow_wait_is_demo_only(self):
        self.b.demo=False
        with self.assertRaises(Blocked):self.enable()
        self.assertFalse(self.e.auto)

    def test_unapproved_pending_config_cannot_execute_with_old_approval(self):
        self.e.auto=True;self.e.paused=False;self.queue()
        self.b.close_position(self.b._positions[0]);self.now+=1.2;self.e.step()
        self.assertFalse(self.e.config.approved)
        self.assertFalse(self.e.auto)

    def test_enable_approves_the_requested_profile_atomically_after_deferred_apply(self):
        self.queue()
        self.b.close_position(self.b._positions[0]);self.now+=1.2;self.e.step()
        self.assertFalse(self.e.config.approved)
        out=self.command('enable',confirmation='ENABLE_DEMO',allow_wait=True,
            accept_pending_profile=True,config=self.want)
        self.assertTrue(out['auto']);self.assertTrue(self.e.config.approved)

    def test_config_in_enable_without_explicit_confirmation_does_not_approve(self):
        self.e.config.approved=False
        with self.assertRaises(Blocked):
            self.command('enable',allow_wait=True,accept_pending_profile=True,config=self.want)
        self.assertFalse(self.e.auto);self.assertFalse(self.e.config.approved)


class HistoryReadTests(unittest.TestCase):
    def test_position_lookup_is_independent_of_pc_end_time(self):
        class MT5:
            def history_deals_get(self, **kwargs):
                self.kwargs=kwargs;return []
        m=MT5();b=MT5Broker(m)
        self.assertTrue(hasattr(b,'history_position'),'Adapter must query the campaign position ID directly')
        self.assertEqual(b.history_position(42),[])
        self.assertEqual(m.kwargs,{'position':42})
