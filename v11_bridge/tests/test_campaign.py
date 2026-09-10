import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from campaign_core import *
from bridge_v11 import Engine,create_app,day_id
from fake_mt5 import FakeMT5,Clock

class CoreTests(unittest.TestCase):
    def bars(self,n=90,seconds=300,now=1789045205.):
        end=int(now)//seconds*seconds
        return [Candle(end-(n-i)*seconds,1+i*.001,1.002+i*.001,.999+i*.001,1.001+i*.001) for i in range(n)]
    def test_monotonic_has_no_pivots(self):
        d,p=structure(self.bars());self.assertEqual(d,0);self.assertEqual(p,[])
    def test_monotonic_sell_has_no_pivots(self):
        b=[Candle(c.time,3-c.open,3-c.low,3-c.high,3-c.close) for c in self.bars()]
        self.assertEqual(structure(b)[0],0)
    def test_high_bias_cannot_replace_structure(self):
        now=1789045205.
        with self.assertRaisesRegex(Blocked,'Swing/Pivot'):
            analyse('EURUSD',self.bars(seconds=3600),self.bars(seconds=900),self.bars(),self.bars(seconds=60),now,.00001)
    def test_open_future_bars_are_not_used(self):
        b=self.bars();now=1789045205.
        future=Candle(int(now)//300*300,1.,2.,.5,1.8)
        self.assertEqual(checked_bars(b+[future],300,now,40),b)
    def test_duplicate_bars_block(self):
        b=self.bars()
        with self.assertRaises(Blocked):checked_bars(b+[b[-1]],300,1789045205.,40)
    def test_stale_bars_block(self):
        with self.assertRaises(Blocked):checked_bars(self.bars(),300,1789048805.,40)
    def test_ohlc_invalid_block(self):
        b=self.bars();b[-1]=replace(b[-1],high=.1)
        with self.assertRaises(Blocked):checked_bars(b,300,1789045205.,40)
    def test_pivot_requires_right_confirmation(self):
        b=[Candle(i*300,1,high,.8,1) for i,high in enumerate([1.1,1.2,1.5,1.2,1.1])]
        self.assertEqual(pivots(b[:4]),[])
        p=pivots(b);self.assertEqual(len(p),1);self.assertEqual(p[0].confirmed_at,1500)
    def test_no_pullback_no_retest(self):
        self.assertFalse(retest_trigger(self.bars(seconds=60),1,0,.00001))
    def test_pullback_resume_buy(self):
        b=self.bars(n=30,seconds=60)
        values=[1.1,1.1002,1.1004,1.1003,1.1001,1.1,1.1001,1.1002,1.1005]
        b=[Candle(c.time,1.1,1.10005,1.09995,1.1) for c in b]
        for i,x in enumerate(values):
            old=values[i-1] if i else 1.0999
            b[-9+i]=Candle(b[-9+i].time,old,max(x,old)+.00001,min(x,old)-.00001,x)
        self.assertTrue(retest_trigger(b,1,0,.00001))
        self.assertTrue(retest_trigger([Candle(c.time,3-c.open,3-c.low,3-c.high,3-c.close) for c in b],-1,0,.00001))
    def test_tick_stale_block(self):
        with self.assertRaises(Blocked):fresh_quote(1,1.01,100,111)
    def test_tick_future_block(self):
        with self.assertRaises(Blocked):fresh_quote(1,1.01,120,110)
    def test_tick_crossed_block(self):
        with self.assertRaises(Blocked):fresh_quote(1.01,1,100,100)
    def test_nan_block(self):
        with self.assertRaises(Blocked):finite(float('nan'),'test')
    def test_round_down(self):
        self.assertAlmostEqual(rounded(.019999,.01),.01)
    def test_add_all_conditions(self):
        k=dict(count=1,maximum=5,pnl=1,side=1,price=1.1,last_price=1.0,step_distance=.01,new_event=True,closing=False,paused=False)
        self.assertTrue(add_allowed(**k))
        for key,value in [('pnl',-.01),('new_event',False),('closing',True),('paused',True),('count',5),('price',.99)]:
            self.assertFalse(add_allowed(**dict(k,**{key:value})))

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=Clock();self.mt=FakeMT5(self.clock)
        self.engine=Engine(self.mt,Path(self.tmp.name)/'state.db',self.clock)
        self.engine.connect();self.engine.positions();self.engine.history(True)
        self.engine.s.update(auto=True,paused=False,fee_per_lot=0.0)
        self.engine.heartbeat=self.clock()
    def tearDown(self):
        self.engine.store.db.close();self.tmp.cleanup()
    def setup(self,n=0):
        return Setup(1,'setup'+str(n),'event'+str(n),int(self.clock())-5,self.mt.bid-.00020,self.mt.ask,.0004,'fixture',())
    def open(self,n=0):
        self.engine.open_event(self.setup(n),self.mt.info,self.mt.symbol_info_tick('EURUSD'),sum(p.profit for p in self.mt.positions_get()))
    def command(self,c,**kw):
        return self.engine.command(c,dict(id='id-'+c+str(len(self.mt.sent))+str(self.clock()),generation=self.engine.s['generation'],expires=self.clock()+8,**kw))
    def test_demo_entry_has_stop(self):
        self.open();self.assertEqual(len(self.mt.ps),1);self.assertGreater(self.mt.ps[0].sl,0)
    def test_real_environment_never_enables_real(self):
        self.mt.ai.trade_mode=2
        with patch.dict(os.environ,{'FXM1_ALLOW_REAL':'1'}):
            with self.assertRaises(Blocked):self.open()
        self.assertEqual(len(self.mt.sent),0)
    def test_contest_block(self):
        self.mt.ai.trade_mode=1
        with self.assertRaises(Blocked):self.engine.connect()
    def test_netting_block(self):
        self.mt.ai.margin_mode=0
        with self.assertRaises(Blocked):self.engine.connect()
    def test_changed_account_block(self):
        self.mt.ai.login=456
        with self.assertRaises(Blocked):self.engine.connect()
    def test_missing_fee_blocks_enable(self):
        self.engine.s['fee_per_lot']=None
        with self.assertRaises(Blocked):self.command('enable')
    def test_stale_quote_no_send(self):
        self.mt.tick_age=100
        with self.assertRaises(Blocked):self.open()
        self.assertFalse(self.mt.sent)
    def test_bad_risk_calculation_no_send(self):
        self.mt.calc_failure=True
        with self.assertRaises(Blocked):self.open()
        self.assertFalse(self.mt.sent)
    def test_simulated_margin_not_big_demo_balance(self):
        self.mt.margin_override=101
        with self.assertRaises(Blocked):self.open()
        self.assertFalse(self.mt.sent)
    def test_minimum_lot_does_not_fit_no_send(self):
        self.mt.info.trade_stops_level=200
        with self.assertRaises(Blocked):self.open()
        self.assertFalse(self.mt.sent)
    def test_final_sl_normalization_precedes_volume_risk(self):
        self.mt.info.trade_stops_level=30
        self.open()
        p=self.mt.ps[0]
        actual=-self.mt.order_calc_profit(p.type,p.symbol,p.volume,p.price_open,p.sl)
        self.assertLessEqual(actual,.50);self.assertLessEqual(p.sl,self.mt.bid-.00032+1e-10)
    def test_duplicate_event_not_executed(self):
        self.open();count=len(self.mt.sent)
        with self.assertRaises(Blocked):self.open()
        self.assertEqual(len(self.mt.sent),count)
    def test_stale_signal_not_executed(self):
        st=replace(self.setup(),event_time=int(self.clock())-100)
        with self.assertRaises(Blocked):self.engine.open_event(st,self.mt.info,self.mt.symbol_info_tick('EURUSD'),0)
        self.assertFalse(self.mt.sent)
    def test_losing_campaign_no_add(self):
        self.open();self.mt.bid-=.00005;self.mt.ask-=.00005
        with self.assertRaises(Blocked):self.open(1)
        self.assertEqual(len(self.mt.ps),1)
    def test_maximum_one_enforced(self):
        self.engine.s['max_positions']=1;self.open();self.mt.bid+=.00030;self.mt.ask+=.00030
        with self.assertRaises(Blocked):self.open(1)
        self.assertEqual(len(self.mt.ps),1)
    def test_add_1_2_3_and_budget(self):
        self.open()
        for i in (1,2):
            self.mt.bid+=.00030;self.mt.ask+=.00030
            for p in self.mt.ps:p.sl=p.price_open+.00010
            self.engine.positions();self.engine.history(True)
            self.open(i)
        self.assertEqual(len(self.mt.ps),3)
        self.assertLessEqual(self.engine.risk()[0],.50)
    def test_emergency_then_play_blocked(self):
        self.open();self.command('emergency')
        self.engine.step();self.assertFalse(self.mt.ps)
        self.assertTrue(self.engine.s['emergency']);self.assertFalse(self.engine.s['auto'])
        with self.assertRaises(Blocked):self.command('play')
    def test_emergency_survives_restart(self):
        self.command('emergency')
        other=Engine(self.mt,Path(self.tmp.name)/'state.db',self.clock)
        self.assertTrue(other.s['emergency']);self.assertFalse(other.s['auto']);other.store.db.close()
    def test_pause_preserves_structural_exit(self):
        self.open();self.command('pause');self.mt.bid=self.engine.s['campaign']['guard']-.00001;self.mt.ask=self.mt.bid+.00001
        self.engine.step();self.assertFalse(self.mt.ps)
    def test_exit_prevents_entry_same_cycle(self):
        self.open();self.mt.bid=self.engine.s['campaign']['guard']-.00001;self.mt.ask=self.mt.bid+.00001
        with patch('bridge_v11.analyse',return_value=self.setup(1)) as analyse_mock:
            self.engine.step();analyse_mock.assert_not_called()
        self.assertFalse(self.mt.ps)
    def test_ambiguous_send_never_retries_entry(self):
        self.mt.send_mode='ambiguous'
        with self.assertRaises(Blocked):self.open()
        self.assertTrue(self.engine.s['recovery']);self.assertIsNotNone(self.engine.s['pending'])
        count=sum(1 for r in self.mt.sent if not r.get('position'))
        with self.assertRaises(Blocked):self.open()
        self.assertEqual(sum(1 for r in self.mt.sent if not r.get('position')),count)
    def test_partial_fill_recorded_actual_volume(self):
        self.mt.send_mode='partial';self.open();self.assertEqual(self.engine.s['campaign']['entries'][0]['volume'],.005)
    def test_manual_positions_not_closed(self):
        self.open();manual=N(**vars(self.mt.ps[0]));manual.magic=0;manual.ticket=999;manual.identifier=999;self.mt.ps.append(manual)
        self.command('emergency');self.engine.step();self.assertEqual([p.ticket for p in self.mt.ps],[999])
    def test_reset_does_not_enable_auto(self):
        self.command('emergency');self.engine.step();self.command('reset');self.assertFalse(self.engine.s['auto']);self.assertFalse(self.engine.s['emergency'])
    def test_cannot_reset_with_positions(self):
        self.open()
        with self.assertRaises(Blocked):self.command('reset')
    def test_same_day_stop_cannot_reset(self):
        self.engine.s['daily_latch']=day_id(self.clock())
        with self.assertRaises(Blocked):self.command('reset')
    def test_history_error_not_false_zero(self):
        self.mt.history_failure=True
        with self.assertRaises(Blocked):self.engine.history(True)
    def test_history_includes_manual_exit_cost_allocation(self):
        self.mt.deal(8,0,0,.01,1.1,commission=-.02)
        self.mt.deal(8,1,1,.005,1.1004,profit=.2,magic=0,commission=-.01)
        self.engine.history(True);self.assertAlmostEqual(self.engine.history_rows[0]['net'],.18)
    def test_profile_rejects_excess_max(self):
        self.engine.s['auto']=False
        with self.assertRaises(Blocked):self.command('profile',fee_per_lot=0,max_positions=10)
    def test_no_auto_permission_after_restart(self):
        self.engine.save();other=Engine(self.mt,Path(self.tmp.name)/'state.db',self.clock)
        self.assertFalse(other.s['auto']);other.store.db.close()
    def test_auth_and_protocol(self):
        app=create_app(self.engine,'fixture-token-1234567890');client=app.test_client()
        self.assertEqual(client.get('/v11/state').status_code,401)
        r=client.get('/v11/state',headers={'Authorization':'Bearer fixture-token-1234567890'})
        self.assertEqual(r.json['protocol'],11)
    def test_command_generation_blocks_stale_enable(self):
        self.engine.s['generation']+=1
        with self.assertRaises(Blocked):self.engine.command('enable',dict(id='stale',generation=self.engine.s['generation']-1,expires=self.clock()+8))
    def test_no_history_emergency_must_still_close(self):
        self.open();self.mt.history_failure=True;self.command('emergency');self.engine.step()
        self.assertFalse(self.mt.ps)

if __name__=='__main__':unittest.main(verbosity=2)
