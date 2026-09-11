import importlib.util, os, sys, tempfile, time, types, unittest
from pathlib import Path
class Fake(types.ModuleType):
    ACCOUNT_TRADE_MODE_DEMO=0; ACCOUNT_TRADE_MODE_REAL=2; ACCOUNT_TRADE_MODE_CONTEST=1
    DEAL_ENTRY_OUT=1; DEAL_ENTRY_OUT_BY=3; DEAL_ENTRY_IN=0
    def __getattr__(self,name):
        if name.startswith(('TIMEFRAME_','TRADE_','ORDER_','POSITION_','SYMBOL_','DEAL_')): return 0
        raise AttributeError(name)
fake=Fake('MetaTrader5');sys.modules['MetaTrader5']=fake
spec=importlib.util.spec_from_file_location('bridge_test',Path(__file__).parents[1]/'mt5_bridge/bridge_v10_0.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
N=types.SimpleNamespace
def deal(ticket,pnl,stamp=None):
    stamp=stamp or int(time.time())-86400
    return N(ticket=ticket,time=stamp,time_msc=stamp*1000+ticket,entry=1,profit=pnl,commission=0.,swap=0.,fee=0.)
class RiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();os.environ['FXM1_RISK_STATE_PATH']=self.tmp.name+'/state.sqlite3'
        self.ai=N(login=1001,server='QA-DEMO',trade_mode=0,balance=99868.35,equity=99868.35)
        self.closing=[deal(1,-1.15),deal(2,-24.50),deal(3,-7.35)]
        self.today=[];self.positions=[];self.orders=[];self.history_error=False;self.day_error=False
        fake.account_info=lambda:self.ai;fake.terminal_info=lambda:object();fake.initialize=lambda:True
        fake.positions_get=lambda **kw:self.positions;fake.orders_get=lambda **kw:self.orders;fake.last_error=lambda:(-1,'test history error')
        def history(start,end):
            day=(end-start).total_seconds()<86401
            return None if (self.day_error if day else self.history_error) else (self.today if day else self.closing)
        fake.history_deals_get=history;b._RISK_REVIEWS.clear();self.client=b.app.test_client()
    def tearDown(self):self.tmp.cleanup()
    def state(self):return b.compute_risk_state(self.ai,3,5,3)
    def token(self):
        r=self.client.post('/risk-review',json={});self.assertEqual(r.status_code,200,r.get_json());return r.get_json()['token']
    def ack(self,t):return self.client.post('/risk-ack',json={'token':t,'confirm':True})
    def test_three_old_losses_block_even_without_today_trades(self):
        r=self.state();self.assertEqual(r['blocks'],['LOSS_STREAK']);self.assertEqual(r['daily_pl'],0);self.assertEqual(r['consecutive_losses'],3)
    def test_unsorted_history_is_sorted(self):
        self.closing=self.closing[::-1];self.assertEqual(self.state()['consecutive_losses'],3)
    def test_profit_breaks_streak(self):
        self.closing.append(deal(4,1));self.assertTrue(self.state()['allowed'])
    def test_missing_history_fails_closed(self):
        self.history_error=True;self.assertFalse(self.state()['allowed']);self.assertIn('RISK_DATA_UNAVAILABLE',self.state()['blocks'])
    def test_missing_daily_history_fails_closed(self):
        self.day_error=True;self.assertFalse(self.state()['allowed'])
    def test_invalid_equity_fails_closed(self):
        self.ai.equity=float('nan');self.assertFalse(self.state()['allowed'])
    def test_review_does_not_acknowledge(self):
        self.token();self.assertIn('LOSS_STREAK',self.state()['blocks'])
    def test_ack_needs_confirmation(self):
        t=self.token();r=self.client.post('/risk-ack',json={'token':t});self.assertEqual(r.status_code,409);self.assertFalse(self.state()['allowed'])
    def test_ack_preserves_money_and_history(self):
        self.today=[deal(4,-2,int(time.time())-60)];self.closing+=self.today
        old=self.state();self.assertEqual(self.ack(self.token()).status_code,200)
        new=self.state();self.assertTrue(new['allowed']);self.assertEqual(new['daily_pl'],old['daily_pl']);self.assertEqual(len(self.closing),4);self.assertEqual(self.ai.balance,99868.35)
    def test_ack_survives_restart_and_new_losses_reblock(self):
        self.ack(self.token());b._RISK_REVIEWS.clear();self.assertTrue(self.state()['allowed'])
        self.closing.extend([deal(4,-1),deal(5,-1),deal(6,-1)]);self.assertFalse(self.state()['allowed'])
    def test_other_account_does_not_inherit_ack(self):
        self.ack(self.token());self.ai.login=1002;self.assertFalse(self.state()['allowed'])
    def test_other_server_does_not_inherit_ack(self):
        self.ack(self.token());self.ai.server='OTHER';self.assertFalse(self.state()['allowed'])
    def test_history_change_cancels_ack(self):
        t=self.token();self.closing.append(deal(4,-1));self.assertEqual(self.ack(t).status_code,409)
    def test_account_change_cancels_ack(self):
        t=self.token();self.ai.login=99;self.assertEqual(self.ack(t).status_code,409)
    def test_open_position_blocks_review(self):
        self.positions=[object()];self.assertEqual(self.client.post('/risk-review',json={}).status_code,409)
    def test_pending_order_after_review_blocks_ack(self):
        t=self.token();self.orders=[object()];self.assertEqual(self.ack(t).status_code,409)
    def test_unknown_positions_blocks_review(self):
        self.positions=None;self.assertEqual(self.client.post('/risk-review',json={}).status_code,409)
    def test_daily_loss_cannot_be_reset(self):
        self.today=[deal(8,-3500,int(time.time())-30)];self.assertEqual(self.client.post('/risk-review',json={}).status_code,409);self.assertIn('DAILY_LOSS',self.state()['blocks'])
    def test_drawdown_cannot_be_reset(self):
        self.ai.equity=90000;self.assertEqual(self.client.post('/risk-review',json={}).status_code,409)
    def test_expired_or_reused_token_rejected(self):
        t=self.token();b._RISK_REVIEWS[t]['expires']=0;self.assertEqual(self.ack(t).status_code,409)
        t=self.token();self.assertEqual(self.ack(t).status_code,200);self.assertEqual(self.ack(t).status_code,409)
    def test_real_is_blocked(self):
        self.ai.trade_mode=2;self.assertFalse(b.trading_allowed(self.ai)[0]);self.assertEqual(self.client.post('/risk-review',json={}).status_code,409)
    def test_invalid_limits_rejected(self):
        self.assertFalse(b.compute_risk_state(self.ai,float('nan'),5,3)['allowed']);self.assertEqual(self.client.post('/risk-review',json={'max_consecutive_losses':0}).status_code,409)
    def test_corrupt_checkpoint_fails_closed(self):
        Path(os.environ['FXM1_RISK_STATE_PATH']).write_bytes(b'not a database');self.assertFalse(self.state()['allowed'])
    def test_http_risk_state_explains_checkpoint(self):
        r=self.client.get('/risk-state').get_json();self.assertEqual(r['streak_limit'],3);self.assertTrue(r['recovery_supported'])
if __name__=='__main__':unittest.main(verbosity=2)
