"""Regression: real adapter's bar-zero semantics through Engine; fake external MT5 only."""
import copy, tempfile, unittest, uuid
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
from unittest.mock import patch
from event_core.mt5_adapter import MT5Broker
from event_core.model import Bar, Quote, Config, atr, TF_SECONDS
from event_core.engine import Engine
from event_core.store import Store
from event_core.scenarios.stable_plans import StablePlans
from fakes import wave
from test_r7_release_runtime import TradingBroker, NOW

class RatesTerminal:
    """Bar 0 remains the MT5 current row until the rates stream rolls over."""
    def __init__(self, owner, offset=0):
        self.owner=owner; self.offset=offset; self.boundary_delay=.5
        for frame in TF_SECONDS: setattr(self, 'TIMEFRAME_'+frame, frame)
    def account_info(self): return SimpleNamespace(login=123,server='DEMO')
    def last_error(self): return (0, 'fixture')
    def copy_rates_from_pos(self, symbol, frame, start, count):
        span=TF_SECONDS[frame]
        b=self.owner
        t=int((b.clock()-self.boundary_delay)//span)*span
        rows=[dict(time=x.time+self.offset,open=x.open,high=x.high,low=x.low,close=x.close,tick_volume=x.volume)
              for x in b.frames[frame] if x.time<t]
        rows.append(dict(time=t+self.offset,open=b.bid,high=b.ask,low=b.bid,close=b.bid,tick_volume=1))
        end=len(rows)-start
        return rows[max(0,end-count):end]

class NativeRatesBroker(TradingBroker):
    def __init__(self, clock, offset=0):
        super().__init__(clock)
        self.frames['M5']=wave(NOW,tf=300,trend=0)
        self.terminal=RatesTerminal(self,offset)
        self.native=MT5Broker(self.terminal,**(dict(clock_account='123@DEMO',clock_offset_minutes=offset//60) if offset else {}))
    def bars(self,symbol,tf):return self.native.bars(symbol,tf)
    def history_bars(self,symbol,tf,count=1200):return self.native.history_bars(symbol,tf,count)
    def current_bar(self,symbol,tf):return self.native.current_bar(symbol,tf)
    def clock_identity(self):return self.native.clock_identity()

class CandleBoundaryTests(unittest.TestCase):
    def test_zero_row_not_closed_half_second_before_boundary(self):
        for offset in (0,10800):
            with self.subTest(offset=offset):
                now=[float(NOW)+299.5]; b=NativeRatesBroker(lambda:now[0],offset)
                with patch('event_core.mt5_adapter.time.time',return_value=now[0]):
                    closed=b.bars('EURUSD','M5');live=b.current_bar('EURUSD','M5')
                self.assertLess(closed[-1].time,live.time,'BAR_ZERO_LEAKED_INTO_HISTORY')
                self.assertTrue(all(x.time+300<=now[0] for x in closed))
    def test_zero_row_not_closed_while_terminal_waits_for_new_bar(self):
        now=[float(NOW)+300.2];b=NativeRatesBroker(lambda:now[0])
        with patch('event_core.mt5_adapter.time.time',return_value=now[0]):
            closed=b.bars('EURUSD','M5');live=b.current_bar('EURUSD','M5')
        self.assertLess(closed[-1].time,live.time,'ROLLOVER_MUST_NOT_DUPLICATE_LIVE_AS_CLOSED')
    def test_confirmed_closed_rows_remain_native_no_offset_inference(self):
        now=[float(NOW)+280];b=NativeRatesBroker(lambda:now[0])
        with patch('event_core.mt5_adapter.time.time',return_value=now[0]):
            actual=b.bars('EURUSD','M5')
        self.assertEqual(actual,b.frames['M5'])
    def setup_engine(self,side=1,mode='NORMAL',offset=0):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        s=Store(Path(tmp.name)/'db');self.addCleanup(s.close)
        self.now=[float(NOW)+296];self.b=NativeRatesBroker(lambda:self.now[0],offset)
        self.a=atr(self.b.frames['M5']);self.zone=(min(x.low for x in self.b.frames['M5'][-12:]) if side==1 else max(x.high for x in self.b.frames['M5'][-12:]))
        cfg=asdict(Config(engine_mode='SCENARIO_V2',runtime_model='R7',entry_model='STABLE_V1',mode=mode,fee_per_lot=0,cooldown_sec=0,lot_cap=.01,volume_mode='FIXED'))
        s.save('engine',dict(config=cfg));self.e=Engine(self.b,s,lambda:self.now[0])
        with patch('event_core.mt5_adapter.time.time',return_value=self.now[0]):
            self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True,accept_pending_profile=True,config={k:v for k,v in cfg.items() if k not in ('approved','technical_position_fuse','max_orders_per_minute')}))
    def tick(self,seconds,price):
        self.now[0]=float(NOW)+seconds;self.b.bid=price;self.b.ask=price+.00001
        with patch('event_core.mt5_adapter.time.time',return_value=self.now[0]): return self.e.step()
    def test_first_buy_sell_crossing_boundary_preserves_observed_touch(self):
        for side in (1,-1):
            for mode in ('NORMAL','SCALP'):
                with self.subTest(side=side,mode=mode):
                    self.setup_engine(side,mode,10800)
                    for sec,d in [(297,.5),(298.5,.04),(299.6,.20),(300.2,.28)]:
                        st=self.tick(sec,self.zone+side*d*self.a)
                    self.assertEqual(len(self.b.sent),1,'ROLLOVER_LOST_ENTRY: '+self.e.execution)
                    self.assertEqual(self.b.sent[0].side,side)
                    self.assertEqual(self.e.market_errors,[])
                    self.assertTrue(st['quote_fresh'])
                    self.assertTrue(st['forecast'].get('price_forecast',{}).get('available'))
    def test_previously_cached_live_row_does_not_poison_closed_history(self):
        self.setup_engine()
        self.tick(297,self.zone+.5*self.a)
        live=self.b.current_bar('EURUSD','M5')
        # Simulates SQLite written by the old now+1 classification, not a real trade.
        self.e.store.save_bars(self.e.market_scope(),'M5',[live],self.now[0])
        self.tick(298.5,self.zone+.04*self.a)
        self.assertFalse(self.e.market_errors,'CACHED_LIVE_ROW_POISON: '+repr(self.e.market_errors))
        self.assertLess(self.e.bars[-1].time,self.e.live_bar.time)
    def test_actual_live_read_failure_and_stale_tick_still_block_entries(self):
        self.setup_engine();self.tick(297,self.zone+.5*self.a)
        self.b.current_bar=lambda *a:(_ for _ in ()).throw(ValueError('real read failure'))
        st=self.tick(298.5,self.zone+.04*self.a)
        self.assertTrue(self.e.market_errors);self.assertFalse(self.b.sent)
        self.assertEqual(self.e.decision.phase,'DATA_BLOCK')

class ResumeExplanationTests(unittest.TestCase):
    def test_recovered_feed_no_longer_claims_interrupted_but_requires_new_touch(self):
        cfg=Config(entry_model='STABLE_V1',mode='NORMAL'); bars=wave(NOW,tf=300,trend=0)
        low=min(b.low for b in bars[-12:]);a=atr(bars);book=StablePlans(cfg)
        q=lambda t,p:Quote(int(t*1000),p,p+.00001)
        book.observe(bars,q(NOW+1,low+.5*a),NOW+1,a)
        book.observe(bars,q(NOW+2,low+.04*a),NOW+2,a)
        book.suspend()
        for t,d in [(3,.20),(4,.28)]:self.assertIsNone(book.observe(bars,q(NOW+t,low+d*a),NOW+t,a))
        self.assertNotIn('Наблюдение прервано',book.status(low)['reason'],'STALE_INTERRUPTION_REASON')
        self.assertTrue(all(not p['entry_ready'] for p in book.plans.values()))
        self.assertTrue(all(p['stage']=='WATCHING' for p in book.plans.values()))

class DirectResumptionTests(unittest.TestCase):
    def test_return_tick_crossing_old_peak_can_add_without_an_artificial_extra_tick(self):
        # Exercise actual Engine transport with existing risk and confirmation rules.
        from test_r74_execution import StableExecutionTests
        for side in (1,-1):
            case=StableExecutionTests();case.setUp()
            try:
                case.enter(side)
                zone=case.low if side>0 else case.high
                for d in (.5,1.,.6,1.04):case.tick(zone+side*d*case.a)
                self.assertEqual(len(case.b.sent),2,'DIRECT_RESUMPTION_LOST_ADD: '+case.e.execution)
                self.assertEqual(len({p.event_id for p in case.b.sent}),2)
                self.assertTrue(all(p.total_risk<=case.e.campaign['budget'] for p in case.b.sent))
            finally:case.doCleanups()

if __name__=='__main__':unittest.main(verbosity=2)
