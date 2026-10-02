import copy,tempfile,unittest,uuid
from pathlib import Path
from event_core.store import Store
from event_core.model import Blocked
from event_core.server import create_app
from test_r7_release_runtime import TradingBroker,NOW

class ProfileTests(unittest.TestCase):
 def setUp(self):
  from event_core.portfolio import Portfolio
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=Store(Path(self.tmp.name)/'db');self.addCleanup(self.store.close)
  self.now=[float(NOW)];self.b=TradingBroker(lambda:self.now[0])
  self.store.save('engine',{'config':{'symbol':'EUR/USD','engine_mode':'SCENARIO_V2'}})
  self.p=Portfolio(self.b,self.store,lambda:self.now[0]);self.a=self.p.profile_id
 def command(self,cmd,**args):return self.p.command(cmd,dict(command_id=str(uuid.uuid4()),**args))
 def test_selecting_new_symbol_does_not_change_or_enable_old_campaign(self):
  self.p.step();old=self.p.engines[self.a];old.auto=True;old.paused=False
  result=self.command('configure',profile_id=self.a,config=dict(symbol='GBP/USD',mode='SCALP',timeframe='M15'),preserve_auto=True)
  b=result['profile_id'];self.assertNotEqual(self.a,b)
  self.assertTrue(old.auto);self.assertEqual(old.config.symbol,'EUR/USD')
  self.assertFalse(self.p.engines[b].auto);self.assertEqual(self.p.engines[b].config.runtime_model,'R7')
  self.command('configure',profile_id=b,config=dict(symbol='EUR/USD',mode='NORMAL',timeframe='M5'))
  self.assertEqual(len(self.p.engines),2)
  self.assertTrue(old.auto,'Returning to a saved instrument is a view selection, not disable')
  self.assertFalse(old.paused)
 def test_ownership_isolated_and_global_unknown_blocks_new_order(self):
  r=self.command('configure',profile_id=self.a,config=dict(symbol='GBP/USD',mode='SCALP'))
  a=self.p.engines[self.a];b=self.p.engines[r['profile_id']]
  from event_core.mt5_adapter import MAGIC
  self.b._positions=[dict(ticket=1,identifier=1,symbol='EURUSD',magic=MAGIC,side=1,volume=.01,price_open=1.10,sl=1.09,swap=0)]
  self.assertEqual(len(a.broker.positions()),1);self.assertEqual(b.broker.positions(),[])
  self.store.intent('pending','UNKNOWN',{'plan':{'symbol':'EURUSD'}})
  self.assertEqual(len(a.store.pending()),1);self.assertFalse(b.store.pending())
  from types import SimpleNamespace
  with self.assertRaisesRegex(Blocked,'неизвест'):
   b.broker.preflight(SimpleNamespace(event_id='other'),b.config)
 def test_state_reads_scoped_and_emergency_is_account_wide(self):
  r=self.command('configure',profile_id=self.a,config=dict(symbol='GBP/USD',timeframe='M15',mode='SCALP'))
  c=create_app(self.p,'secret').test_client();h={'Authorization':'Bearer secret','X-FXM1-Client':'R51'}
  s=c.get('/ec/state?profile_id='+self.a,headers=h).get_json()
  self.assertEqual(s['config']['symbol'],'EUR/USD');self.assertEqual(s['profile_id'],self.a)
  self.assertTrue(s['capabilities']['profile_registry']);self.assertEqual(len(s['profiles']),2)
  self.command('emergency',profile_id=self.a)
  self.assertTrue(all(e.emergency and not e.auto for e in self.p.engines.values()))
 def test_restart_recovers_saved_profiles_but_not_auto(self):
  from event_core.portfolio import Portfolio
  r=self.command('configure',profile_id=self.a,config=dict(symbol='GBP/USD',timeframe='M15',mode='SCALP'))
  self.p.engines[r['profile_id']].auto=True;self.p.engines[r['profile_id']].save()
  p=Portfolio(self.b,self.store,lambda:self.now[0])
  self.assertEqual(len(p.engines),2);self.assertTrue(all(not e.auto for e in p.engines.values()))
 def test_two_symbols_open_then_emergency_closes_both_without_cross_ownership(self):
  from event_core.model import atr
  self.command('configure',profile_id=self.a,config=dict(symbol='EUR/USD',mode='SCALP',timeframe='M5',lot_cap=.01,fee_per_lot=0,cooldown_sec=0))
  b=self.command('configure',profile_id=self.a,config=dict(symbol='GBP/USD',mode='NORMAL',timeframe='M15',lot_cap=.01,fee_per_lot=0,cooldown_sec=0))['profile_id']
  for ident in (self.a,b):
   self.command('enable',profile_id=ident,confirmation='ENABLE_DEMO',allow_wait=True,accept_pending_profile=True,config=as_dict(self.p.engines[ident].config))
  a=atr(self.b.frames['M5'])
  for delta in (0,2,1.45,1.55,2.04):
   self.now[0]+=1;self.b.bid=1.106+delta*a;self.b.ask=self.b.bid+.00001;self.p.step()
  self.assertEqual(len(self.b.sent),2,[(k,e.execution) for k,e in self.p.engines.items()])
  self.assertEqual({p.symbol for p in self.b.sent},{'EURUSD','GBPUSD'})
  ids=[e.campaign['position_ids'] for e in self.p.engines.values()]
  self.assertEqual(len(set(ids[0])&set(ids[1])),0)
  self.command('emergency',profile_id=self.a);self.now[0]+=1;self.p.step()
  self.assertFalse(self.b.positions())

 def test_nonfinite_foreign_risk_cannot_pass_account_preflight(self):
  from types import SimpleNamespace
  from event_core.mt5_adapter import MAGIC
  self.p.step()
  self.b._positions=[dict(ticket=1,identifier=1,symbol='EURUSD',magic=MAGIC,side=1,volume=.01,price_open=1.10,sl=1.09,swap=0)]
  old=self.b.calc_profit;self.b.calc_profit=lambda *args:float('nan')
  with self.assertRaises(Blocked):
   self.p.engines[self.a].broker.preflight(SimpleNamespace(risk=1.,margin=1.),self.p.engines[self.a].config)
  self.b.calc_profit=old


def as_dict(cfg):
 from dataclasses import asdict
 return {k:v for k,v in asdict(cfg).items() if k not in ('approved','technical_position_fuse','max_orders_per_minute')}
