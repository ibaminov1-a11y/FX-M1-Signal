import importlib.util, os, sys, tempfile, types, unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch

class FakeMT5(types.ModuleType):
    def __getattr__(self,key):
        if key.startswith(('ACCOUNT_','DEAL_','ORDER_','POSITION_','TRADE_','TIMEFRAME_')): return 0
        raise AttributeError(key)
fake=FakeMT5('MetaTrader5')
for k,v in {'ACCOUNT_TRADE_MODE_DEMO':0,'ACCOUNT_TRADE_MODE_REAL':2,'ACCOUNT_TRADE_MODE_CONTEST':1,'DEAL_ENTRY_IN':0,'DEAL_ENTRY_OUT':1,'DEAL_ENTRY_OUT_BY':3}.items():setattr(fake,k,v)
sys.modules['MetaTrader5']=fake
spec=importlib.util.spec_from_file_location('bridge_under_test',Path(__file__).resolve().parents[1]/'mt5_bridge/bridge_v10_0.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return cls(2026,9,11,12,0,0)

class RiskTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'FXM1_RISK_ACK_PATH':self.temp.name+'/ack.json'});self.env.start();self.addCleanup(self.env.stop)
        b.datetime=Clock;b.time=types.SimpleNamespace(time=lambda:Clock.now().timestamp())
        self.acc=types.SimpleNamespace(login=123,server='Demo',trade_mode=0,balance=100000.,equity=100000.)
        now=Clock.now();self.deals=[self.deal(i,now-timedelta(days=1,minutes=10-i),pl) for i,pl in [(1,-1.15),(2,-24.5),(3,-7.35)]]
        self.positions=();self.orders=();self.bad=False
        fake.account_info=lambda:self.acc;fake.terminal_info=lambda:object();fake.initialize=lambda:True
        fake.positions_get=lambda:self.positions;fake.orders_get=lambda:self.orders;fake.last_error=lambda:(500,'unavailable')
        fake.history_deals_get=lambda start,end:None if self.bad else tuple(d for d in self.deals if start.timestamp()<=d.time<=end.timestamp())
        self.client=b.app.test_client()
    def deal(self,ticket,when,pl):return types.SimpleNamespace(ticket=ticket,time=int(when.timestamp()),time_msc=int(when.timestamp()*1000),entry=1,profit=pl,commission=0.,swap=0.,fee=0.)
    def state(self):return b.compute_risk_state(self.acc,3,5,3)
    def ack(self,**changes):
        data=dict(confirmation='ACK_LOSS_STREAK_DEMO',expected_last_deal=3,daily_loss_limit_pct=3,max_drawdown_pct=5,max_consecutive_losses=3,cooldown_sec=600);data.update(changes)
        return self.client.post('/risk-acknowledge',json=data)
    def test_01_yesterdays_streak_blocks_today(self):
        s=self.state();self.assertEqual(s['daily_pl'],0);self.assertEqual(s['consecutive_losses'],3);self.assertEqual(s['blocks'],['LOSS_STREAK'])
    def test_02_unordered_history_is_sorted(self):
        self.deals.reverse();self.assertEqual(self.state()['consecutive_losses'],3)
    def test_03_none_history_fails_closed(self):
        self.bad=True;self.assertEqual(self.state()['blocks'],['HISTORY_UNAVAILABLE']);self.assertFalse(self.state()['allowed'])
    def test_04_ack_requires_explicit_confirmation(self):self.assertEqual(self.ack(confirmation='').status_code,409)
    def test_05_real_ack_rejected(self):
        self.acc.trade_mode=2;self.assertEqual(self.ack().status_code,409)
    def test_06_ack_with_positions_rejected(self):
        self.positions=(object(),);self.assertEqual(self.ack().status_code,409)
    def test_07_ack_with_orders_rejected(self):
        self.orders=(object(),);self.assertEqual(self.ack().status_code,409)
    def test_08_unknown_exposure_rejected(self):
        self.orders=None;self.assertEqual(self.ack().status_code,409)
    def test_09_stale_review_rejected(self):self.assertEqual(self.ack(expected_last_deal=2).status_code,409)
    def test_10_cooldown_rejected(self):
        self.deals[-1]=self.deal(3,Clock.now()-timedelta(seconds=10),-7.35);self.assertEqual(self.ack().status_code,409)
    def test_11_valid_ack_persists(self):
        self.assertEqual(self.ack().status_code,200);self.assertEqual(self.state()['consecutive_losses'],0)
        self.assertTrue(self.state()['allowed']);self.assertEqual(len(self.deals),3);self.assertTrue(Path(self.temp.name+'/ack.json').is_file())
    def test_12_new_losses_count_again(self):
        self.assertEqual(self.ack().status_code,200)
        self.deals += [self.deal(i,Clock.now()-timedelta(minutes=20-i),-1) for i in (4,5,6)]
        self.assertEqual(self.state()['consecutive_losses'],3);self.assertFalse(self.state()['allowed'])
    def test_13_daily_block_not_reset(self):
        self.deals.append(self.deal(4,Clock.now()-timedelta(hours=1),-4000));self.assertIn('DAILY_LOSS',self.state()['blocks']);self.assertEqual(self.ack(expected_last_deal=4).status_code,409)
    def test_14_drawdown_not_reset(self):
        self.acc.equity=90000;self.assertIn('DRAWDOWN',self.state()['blocks']);self.assertEqual(self.ack().status_code,409)
    def test_15_another_account_separate(self):
        self.assertEqual(self.ack().status_code,200);self.acc.login=124;self.assertEqual(self.state()['consecutive_losses'],3)
    def test_16_corrupt_file_fails_closed(self):
        Path(self.temp.name+'/ack.json').write_text('not-json');self.assertFalse(self.state()['allowed']);self.assertEqual(self.ack().status_code,409)
    def test_17_unknown_account_fails_closed(self):
        self.acc.server='';self.assertFalse(self.state()['allowed'])
    def test_18_zero_or_nonfinite_limits_rejected(self):
        for limit in (0,float('nan'),float('inf')):self.assertFalse(b.compute_risk_state(self.acc,limit,5,3)['allowed'])
    def test_19_account_balance_not_virtual(self):self.assertEqual(self.acc.balance,100000);self.assertEqual(self.state()['drawdown_pct'],0)
    def test_20_real_default_off(self):
        self.acc.trade_mode=2;self.assertFalse(b.ALLOW_REAL);self.assertFalse(b.trading_allowed(self.acc)[0])
    def test_21_api_risk_state_contains_ack_metadata(self):
        s=self.client.get('/risk-state').get_json();self.assertTrue(s['ack_supported']);self.assertTrue(s['can_acknowledge']);self.assertEqual(s['last_closing_ticket'],3)

if __name__=='__main__':unittest.main(verbosity=2)
