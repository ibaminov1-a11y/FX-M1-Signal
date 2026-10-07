"""Actual dispatcher and risk checks, causal synthetic quotes, fake MT5 transport.

No forecast injection or fabricated entry decisions. Synthetic replay is not
broker execution or financial-performance evidence.
"""
import copy
import tempfile
import unittest
import uuid
from dataclasses import asdict
from pathlib import Path
from event_core.model import Config, Bar, atr
from event_core.portfolio import Portfolio
from event_core.store import Store
import test_r7_release_runtime as runtime

class SeriesFixture:
    def __init__(self, side=1, mode='NORMAL', balance=100000., limit=0):
        self.side=side;self.mode=mode;self.t=[float(runtime.NOW)]
        self.b=runtime.TradingBroker(lambda:self.t[0]);self.b.balance=balance
        base=1.22332;rows=[]
        for i in range(48):
            c=base if i<36 else base+(i-35)*.001
            h=.0002 if i in (34,35) else .00001
            rows.append(Bar(runtime.NOW-(48-i)*300,c,c+h,c-h,c,10))
        if side<0:
            rows=[Bar(r.time,2*base-r.open,2*base-r.low,2*base-r.high,2*base-r.close,r.volume) for r in rows]
        self.b.frames['M5']=rows;self.a=atr(rows)
        low=min(r.low for r in rows[-12:]);high=max(r.high for r in rows[-12:])
        self.zone=low if side>0 else high
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db')
        cfg=asdict(Config(engine_mode='SCENARIO_V2',runtime_model='R7',entry_model='PINNED_V1',mode=mode,
                         lot_cap=.01,volume_mode='FIXED',fee_per_lot=0.,cooldown_sec=0,optional_position_limit=limit))
        self.store.save('engine',{'config':cfg});self.e=Portfolio(self.b,self.store,lambda:self.t[0],entry_model='PINNED_V1')
        self.e.command('enable',dict(command_id=str(uuid.uuid4()),confirmation='ENABLE_DEMO',allow_wait=True,
            accept_pending_profile=True,config={k:v for k,v in cfg.items() if k not in ('approved','technical_position_fuse','max_orders_per_minute')}))
    def close(self):self.store.close();self.tmp.cleanup()
    def tick(self,price,seconds=1):
        self.t[0]+=seconds;self.b.bid=price;self.b.ask=price+.00001
        start=int(self.t[0])//60*60
        # Only already observed ticks create newly closed M1 bars. No future path.
        while self.b.frames['M1'][-1].time+60<start:
            tm=self.b.frames['M1'][-1].time+60
            self.b.frames['M1'].append(Bar(tm,price,price+.00001,price-.00001,price,10))
        return self.e.step()
    def first(self):
        for d in (.5,.04,.20,.24):state=self.tick(self.zone+self.side*d*self.a)
        return state
    def add(self):
        last=self.e.campaign['last_entry']
        peak=.601 if self.mode=='NORMAL' else (.651 if len(self.b.sent)==1 else .401)
        pull=.355 if self.mode=='NORMAL' else .205
        for d in (.12,peak,peak-pull,peak+.006):state=self.tick(last+self.side*d*self.a,2.5)
        return state

class TenPositionTests(unittest.TestCase):
    def test_buy_sell_normal_and_scalp_reach_ten_distinct_risk_checked_positions(self):
        for mode in ('NORMAL','SCALP'):
            for side in (1,-1):
                with self.subTest(mode=mode,side=side):
                    f=SeriesFixture(side,mode)
                    try:
                        state=f.first();self.assertEqual(len(f.b.sent),1,f.e.execution)
                        root=f.e.campaign['scenario_id'];frozen=copy.deepcopy(f.e.campaign['forecast_at_entry'])
                        for count in range(2,11):
                            state=f.add();self.assertEqual(len(f.b.sent),count,(mode,side,count,f.e.execution))
                            self.assertEqual(len(f.b.positions()),count)
                            self.assertEqual(root,f.e.campaign['scenario_id'])
                            self.assertEqual(frozen,f.e.campaign['forecast_at_entry'])
                            self.assertEqual(len({p.event_id for p in f.b.sent}),count)
                            self.assertTrue(all(p.volume==.01 and p.total_risk<=f.e.campaign['budget'] for p in f.b.sent))
                            self.assertEqual(state['campaign_progress']['open_positions'],count)
                            # Same delivered tick is not another opportunity.
                            before=len(f.b.sent);f.e.step();self.assertEqual(len(f.b.sent),before)
                        self.assertEqual(state['campaign_progress']['max_positions'],10)
                        self.assertFalse(state['account']['type']=='REAL')
                    finally:f.close()
    def test_eleventh_fresh_confirmation_rejected_without_touching_existing_positions(self):
        for side in (1,-1):
            with self.subTest(side=side):
                f=SeriesFixture(side,'SCALP')
                try:
                    f.first()
                    for _ in range(9):f.add()
                    self.assertEqual(len(f.b.sent),10)
                    before={p['ticket'] for p in f.b.positions()}
                    f.add()
                    self.assertEqual(len(f.b.sent),10,f.e.execution)
                    self.assertEqual({p['ticket'] for p in f.b.positions()},before)
                    self.assertIn('10',f.e.execution)
                finally:f.close()
    def test_small_budget_allows_two_and_rejects_third_for_money_not_detector(self):
        for side in (1,-1):
            with self.subTest(side=side):
                f=SeriesFixture(side,'NORMAL',balance=500.)
                try:
                    f.first();f.add();self.assertEqual(len(f.b.sent),2,f.e.execution)
                    f.add();self.assertEqual(len(f.b.sent),2)
                    self.assertIn('риска',f.e.execution)
                    self.assertGreaterEqual(len(f.e.compute.continuation.reason),1)
                    self.assertTrue(all(p.volume==.01 for p in f.b.sent))
                finally:f.close()
    def test_smaller_user_limit_wins_over_ten_ceiling(self):
        f=SeriesFixture(1,'SCALP',limit=2)
        try:
            f.first();f.add();f.add()
            self.assertEqual(len(f.b.sent),2,f.e.execution)
            self.assertIn('лимит',f.e.execution.lower())
        finally:f.close()
if __name__=='__main__':unittest.main()
