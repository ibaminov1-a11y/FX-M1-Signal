"""Real ComputeCore + real Engine; only broker transport/quotes are simulated."""
import tempfile
import unittest
from pathlib import Path

from event_core.compute_core import ComputeCore
from event_core.engine import Engine
from event_core.model import Bar, Config, Decision
from event_core.store import Store
from event_core.strategy import Strategy
from fakes import FakeBroker
from test_compute_core import NOW, market


class ComputeReversalIntegrationTests(unittest.TestCase):
    def test_prospective_sell_cross_closes_buy_then_opens_once_after_flat_history(self):
        now=[NOW]
        broker=FakeBroker(lambda:now[0])
        bars,m1,m15,h1,live,a=market(-1)
        trigger=min(x.low for x in m1[-5:-1])-max(a*.02,.000012)
        broker.bar_data=bars;broker.m1_data=m1;broker.ctx_data=m15;broker.h1_data=h1
        broker.bid=trigger+.03*a;broker.ask=broker.bid+.00001
        broker.live_bar_data=Bar(live.time,trigger+.10*a,trigger+.13*a,trigger-.08*a,trigger-.06*a,35)
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'state.sqlite3')
            try:
                e=Engine(broker,store,lambda:now[0])
                e.config=Config(timeframe='M5',engine_mode='COMPUTE_V1',risk_pct=.25,
                                fee_per_lot=0,lot_cap=.01,probe_lot_cap=.01,approved=True,cooldown_sec=600)
                e.strategy=Strategy(e.config);e.compute=ComputeCore(e.config)
                e._refresh(now[0]);e.info=broker.symbol(e.config.symbol);e.quote=broker.quote(e.info['name'])
                initial=Decision('BUY','ENTRY_READY','initial campaign','initial-buy',1,
                                 broker.bid-.0005,broker.bid-.00001,broker.bid-.0005,.0005,
                                 int(now[0]*1000),path='COMPUTE',entry_class='CONFIRMED')
                e._entry(initial,now[0]);e.auto=True;e.paused=False
                e.step()  # First bearish calculation observes the safe side, never backfills.
                self.assertEqual(len(broker.sent),1,e.execution)
                self.assertIsNone(e.pending_reversal)
                now[0]+=1
                broker.bid=trigger-.03*a;broker.ask=broker.bid+.00001
                e.step()
                self.assertEqual(len(broker.closed),1,e.execution)
                self.assertEqual(len(broker.sent),1)
                self.assertTrue(e.pending_reversal['confirmed'])
                self.assertEqual(e.campaign['exit_code'],'OPPOSITE_CONFIRMED')
                now[0]+=1.2
                e.step()  # Explicit flat/history boundary; no order this cycle.
                self.assertFalse(broker._positions)
                self.assertIsNone(e.campaign)
                self.assertEqual(len(broker.sent),1)
                now[0]+=.2
                e.step()
                self.assertEqual(len(broker.sent),2,e.execution)
                self.assertEqual(broker._positions[0]['side'],-1)
                self.assertEqual(e.reversal_status['status'],'OPENED')
                for _ in range(4):
                    now[0]+=.2;e.step()
                self.assertEqual(len(broker.sent),2,'Never resend a consumed crossing')
                events=store.events()
                self.assertEqual(sum(x['kind']=='REVERSAL_OPENED' for x in events),1)
            finally:
                store.close()
