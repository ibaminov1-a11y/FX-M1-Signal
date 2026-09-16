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
from test_r3_continuation import shallow_fixture, confirmed_m1

NOW=1800000000.0


class R3ImpulseBroker(FakeBroker):
    def __init__(self, clock, side):
        super().__init__(clock)
        bars,m1,m15,h1,live,q,a,level=impulse_fixture(side)
        self.bar_data=list(bars)
        self.m1_data=list(m1)
        self.ctx_data=list(m15)
        self.h1_data=list(h1)
        self.live_m5=live
        self.bid=q.bid
        self.ask=q.ask

    def current_bar(self, symbol, tf):
        if tf!='M5':
            raise AssertionError('R3 Engine requests only current M5')
        return self.live_m5


class R3ContinuationBroker(FakeBroker):
    def __init__(self, clock, side):
        super().__init__(clock)
        bars,m1,m15,h1,live,q,a=shallow_fixture(side,.20)
        self.bar_data=list(bars)
        self.m1_data=list(m1)
        self.ctx_data=list(m15)
        self.h1_data=list(h1)
        self.live_m5=live
        self.bid=q.bid
        self.ask=q.ask
        self.fixture_atr=a

    def current_bar(self, symbol, tf):
        if tf!='M5':
            raise AssertionError('R3 Engine requests only current M5')
        return self.live_m5


class R3EngineFlowTests(unittest.TestCase):
    def arm(self,engine):
        engine.config=Config(timeframe='M5',mode='NORMAL',risk_pct=.25,
                             fee_per_lot=0,lot_cap=.01,approved=True,cooldown_sec=0)
        engine.strategy=Strategy(engine.config)
        engine.command('enable',{
            'command_id':str(uuid.uuid4()),
            'confirmation':'ENABLE_DEMO',
        })

    def run_impulse(self, side):
        now=[NOW]
        broker=R3ImpulseBroker(lambda:now[0],side)
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'state.sqlite3')
            try:
                engine=Engine(broker,store,lambda:now[0])
                self.arm(engine)
                engine.step()
                self.assertEqual(len(broker.sent),1,engine.execution)
                self.assertEqual(engine.decision.path,'IMPULSE')
                self.assertEqual(engine.decision.side,side)
                self.assertIsNotNone(engine.campaign)
                self.assertEqual(engine.campaign['side'],side)
                self.assertEqual(len(engine._owned()),1)

                # Same live M5 event and same tick cannot create a second order.
                now[0]+=.2
                engine.step()
                self.assertEqual(len(broker.sent),1,engine.execution)
            finally:
                store.close()

    def test_engine_executes_live_buy_impulse_once(self):
        self.run_impulse(1)

    def test_engine_executes_live_sell_impulse_once(self):
        self.run_impulse(-1)

    def test_engine_executes_continuation_only_after_new_closed_m1(self):
        now=[NOW]
        broker=R3ContinuationBroker(lambda:now[0],1)
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'state.sqlite3')
            try:
                engine=Engine(broker,store,lambda:now[0])
                self.arm(engine)
                engine.step()
                self.assertEqual(len(broker.sent),0)
                self.assertEqual((engine.decision.phase,engine.decision.path),('TRIGGER','CONTINUATION'))
                trigger=engine.strategy.setup.trigger

                # A price move alone is still insufficient: no new closed M1 yet.
                now[0]+=1
                broker.bid=trigger+.07*broker.fixture_atr
                broker.ask=broker.bid+.00001
                engine.step()
                self.assertEqual(len(broker.sent),0)
                self.assertEqual(engine.decision.path,'CONTINUATION')

                # After a genuinely new M1 closes beyond trigger, the same Engine path
                # reaches the unchanged R2.5 risk/_entry/broker.send boundary exactly once.
                broker.m1_data=confirmed_m1(broker.m1_data,trigger,1,broker.fixture_atr)
                now[0]+=60
                broker.bid=trigger+.07*broker.fixture_atr
                broker.ask=broker.bid+.00001
                engine.step()
                self.assertEqual(len(broker.sent),1,engine.execution)
                self.assertEqual((engine.decision.signal,engine.decision.path),('BUY','CONTINUATION'))
                self.assertEqual(engine.campaign['side'],1)

                now[0]+=.2
                engine.step()
                self.assertEqual(len(broker.sent),1)
            finally:
                store.close()


if __name__=='__main__':
    unittest.main()
