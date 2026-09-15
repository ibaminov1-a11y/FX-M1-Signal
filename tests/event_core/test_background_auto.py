import tempfile,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'mt5_bridge'))
from event_core.engine import Engine
from event_core.model import Config
from event_core.store import Store
from fakes import FakeBroker

class BackgroundAutoTests(unittest.TestCase):
    def test_auto_stays_enabled_without_phone_foreground_heartbeat(self):
        now=[1800000000.0]
        broker=FakeBroker(lambda:now[0])
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'state.sqlite3')
            try:
                engine=Engine(broker,store,lambda:now[0])
                engine.config=Config(risk_pct=.25,fee_per_lot=0,approved=True,cooldown_sec=0)
                engine.strategy=__import__('event_core.strategy',fromlist=['Strategy']).Strategy(engine.config)
                engine._refresh(now[0])
                engine.command('enable',{'command_id':'enable-bg-0001','confirmation':'ENABLE_DEMO'})
                self.assertTrue(engine.auto)
                self.assertFalse(engine.paused)
                now[0]+=45.0
                engine.step()
                self.assertTrue(engine.auto,'AUTO must not depend on the Android app remaining foreground')
                self.assertFalse(engine.paused,'backgrounding the phone app must not PAUSE the Bridge')
            finally:
                store.close()

if __name__=='__main__':
    unittest.main()
