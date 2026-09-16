import tempfile
import unittest
import uuid
from pathlib import Path

from event_core.engine import Engine
from event_core.model import Config
from event_core.store import Store
from event_core.strategy import Strategy
from fakes import FakeBroker
from test_r3_impulse import impulse_fixture

NOW=1800000000.0


class R3Broker(FakeBroker):
    def __init__(self,clock,side):
        super().__init__(clock)
        bars,m1,m15,h1,live,q,a,level=impulse_fixture(side)
        self.bar_data=bars;self.m1_data=m1;self.ctx_data=m15;self.h1_data=h1
        self.live_m5=live;self.bid=q.bid;self.ask=q.ask

    def current_bar(self,symbol,tf):
        if tf!='M5':raise AssertionError('R3 test expects live M5 only')
        return self.live_m5


class R3EngineFlowTests(unittest.TestCase):
    def run_impulse(self,side):
        now=[NOW]
        broker=R3Broker(lambda:now[0],side)
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'state.sqlite3')
            try:
                engine=Engine(broker,store,lambda:now[0])
                engine.config=Config(timeframe='M5',mode='NORMAL',risk_pct=.25,fee_per_lot=0,
                                     lot_cap=.01,approved=True,cooldown_sec=0)
                engine.strategy=Strategy(engine.config)
                engine.command('enable',{'command_id':str(uuid.uuid4()),'confirmation':'ENABLE_DEMO'})
                snap=engine.step()
                self.assertEqual(len(broker.sent),1,engine.execution)
                self.assertEqual(broker.sent[0].side,side)
                self.assertEqual(snap['decision']['path'],'IMPULSE')
                self.assertEqual(snap['decision']['phase'],'ENTRY_READY')
                self.assertTrue(snap['decision']['structure'])
                # Same live M5 event is single-use even while the candle is still open.
                for _ in range(3):
                    now[0]+=.5
                    engine.step()
                self.assertEqual(len(broker.sent),1,'same impulse event must not send twice')
            finally:
                store.close()

    def test_engine_executes_live_buy_impulse_once(self):
        self.run_impulse(1)

    def test_engine_executes_live_sell_impulse_once(self):
        self.run_impulse(-1)


if __name__=='__main__':
    unittest.main()
