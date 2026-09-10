"""Synthetic integration fixtures, not market backtests or profit evidence."""
import math
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from campaign_core import Candle,analyse,Blocked
from coordinator import Engine
from fake_mt5 import FakeMT5,Clock

NOW=1789045205.0

def candles(n,seconds,fn,spread=.00002):
    end=int(NOW)//seconds*seconds
    out=[]
    for i in range(n):
        a,b=fn(i-.3),fn(i)
        out.append(Candle(end-(n-i)*seconds,a,max(a,b)+spread,min(a,b)-spread,b))
    return out

def fixture(side):
    h1=candles(100,3600,lambda i:1.096+i*.00004)
    m15=candles(100,900,lambda i:1.098+i*.00002)
    m5=candles(100,300,lambda i:1.098+i*.00002+math.sin((i+2)*math.pi/5)*.00014)
    m1=candles(40,60,lambda i:1.09990,spread=.00001)
    values=[1.09994,1.10004,1.10012,1.10002,1.09996,1.09994,1.09999,1.10003,1.10014]
    for i,x in enumerate(values):
        old=values[i-1] if i else 1.09990
        m1[-9+i]=Candle(m1[-9+i].time,old,max(x,old)+.00001,min(x,old)-.00001,x)
    data={60:h1,15:m15,5:m5,1:m1}
    if side<0:
        data={k:[Candle(c.time,2.2-c.open,2.2-c.low,2.2-c.high,2.2-c.close) for c in v] for k,v in data.items()}
    return data

class FullPipelineTests(unittest.TestCase):
    def run_side(self,side):
        data=fixture(side)
        setup=analyse('EURUSD',data[60],data[15],data[5],data[1],NOW,.00001)
        self.assertEqual(setup.side,side)
        self.assertGreaterEqual(len(setup.proof),4)
        self.assertTrue(all(p['confirmed_at']<=setup.event_time for p in setup.proof))
        clock=Clock(NOW);mt=FakeMT5(clock)
        mt.bid=1.10014 if side==1 else 2.2-1.10015;mt.ask=mt.bid+.00001
        mt.copy_rates_from_pos=lambda symbol,tf,start,count:[asdict(c) for c in data[tf]]
        with tempfile.TemporaryDirectory() as folder:
            e=Engine(mt,Path(folder)/'db.sqlite3',clock)
            try:
                e.connect();e.positions();e.history(True)
                e.s.update(auto=True,paused=False,fee_per_lot=0);e.heartbeat=clock()
                e.step()
                self.assertTrue(e.snapshot['ok'],e.snapshot['reason'])
                self.assertEqual(len(mt.ps),1,e.snapshot['reason'])
                self.assertEqual(mt.ps[0].type,0 if side==1 else 1)
                self.assertLessEqual(e.risk()[0],.50)
                e.step()  # Same event is not a second entry.
                self.assertEqual(len(mt.ps),1)
            finally:e.store.db.close()
    def test_buy_analysis_to_order(self):self.run_side(1)
    def test_sell_analysis_to_order(self):self.run_side(-1)
    def test_future_candles_do_not_change_current_decision(self):
        d=fixture(1)
        original=analyse('EURUSD',d[60],d[15],d[5],d[1],NOW,.00001)
        for tf in d:
            future=Candle(int(NOW)//(tf*60)*(tf*60)+tf*60,1,10,.1,9)
            d[tf].append(future)
        repeated=analyse('EURUSD',d[60],d[15],d[5],d[1],NOW,.00001)
        self.assertEqual(original,repeated)

if __name__=='__main__':unittest.main(verbosity=2)
