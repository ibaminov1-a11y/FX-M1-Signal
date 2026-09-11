import unittest,tempfile,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'mt5_bridge'))
from event_core.engine import Engine
from event_core.model import *
from event_core.strategy import Strategy
from event_core.store import Store
from fakes import FakeBroker,wave


def mirror(b): return Bar(b.time,2.3-b.open,2.3-b.low,2.3-b.high,2.3-b.close,b.volume)

class FullFlow(unittest.TestCase):
    def test_real_strategy_through_engine_and_broker_both_modes_sides(self):
        for mode in ('NORMAL','SCALP'):
            for side in (1,-1):
                with self.subTest(mode=mode,side=side),tempfile.TemporaryDirectory() as tmp:
                    now=[1800000000.];b=FakeBroker(lambda:now[0]);store=Store(Path(tmp)/'test.db')
                    try:
                        e=Engine(b,store,lambda:now[0]);e.config=Config(mode=mode,test_capital=1000,risk_pct=1,absolute_risk_cap=10,fee_per_lot=0,approved=True,cooldown_sec=0)
                        e.strategy=Strategy(e.config)
                        if side==-1:b.bar_data=[mirror(x) for x in b.bar_data];b.ctx_data=[mirror(x) for x in b.ctx_data]
                        def q(price):
                            b.bid=price if side==1 else 2.3-price;b.ask=b.bid+.00001;e.heartbeat=now[0]
                        q(1.1026);e.command('enable',{'command_id':str(uuid.uuid4()),'confirmation':'ENABLE_DEMO'})
                        e.step();self.assertEqual(len(b.sent),0)
                        bar=Bar(int(now[0]),1.1026,1.1034,1.1026,1.10335)
                        b.bar_data.append(bar if side==1 else mirror(bar));now[0]+=300;q(1.10335)
                        e.step();self.assertEqual(e.decision.phase,'PULLBACK');self.assertFalse(b.sent)
                        bar=Bar(int(now[0]),1.10335,1.10336,1.1030,1.10305)
                        b.bar_data.append(bar if side==1 else mirror(bar));now[0]+=300;q(1.10305)
                        e.step();self.assertEqual(e.decision.phase,'TRIGGER');self.assertFalse(b.sent)
                        trigger=e.strategy.setup.trigger;now[0]+=1;b.bid=trigger+side*.000005;b.ask=b.bid+.00001;e.heartbeat=now[0]
                        e.step()
                        self.assertEqual(len(b.sent),1,e.execution)
                        self.assertEqual(e.campaign['side'],side);self.assertEqual(len(e._owned()),1)
                        for _ in range(4):now[0]+=.1;e.heartbeat=now[0];e.step()
                        self.assertEqual(len(b.sent),1)
                        # A structural invalidation closes the whole campaign and does not reopen.
                        now[0]+=1;b.bid=e.campaign['invalidation']-side*.0001;b.ask=b.bid+.00001;e.heartbeat=now[0]
                        e.step();self.assertEqual(len(b._positions),0);self.assertEqual(len(b.sent),1)
                    finally:store.close()

if __name__=='__main__':unittest.main()
