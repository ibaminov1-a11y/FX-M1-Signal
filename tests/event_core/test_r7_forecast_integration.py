"""Run the real Engine/ScenarioCore; forecast must never authorize a trade."""
import copy
import tempfile
import unittest
from pathlib import Path
from event_core.engine import Engine
from event_core.model import Bar
from event_core.store import Store
from event_core.server import create_app
from test_r56_multiframe import IndependentBroker,NOW

class ForecastIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=Store(Path(temp.name)/'s.db');self.addCleanup(self.store.close)
        self.store.save('engine',{'config':{'engine_mode':'SCENARIO_V2','timeframe':'M5'}})
        self.now=[float(NOW)];self.b=IndependentBroker(lambda:self.now[0])
        # Actual neutral candles, not an injected WAIT decision.
        for tf in ('M1','M5','M15','H1'):
            from event_core.model import TF_SECONDS
            span=TF_SECONDS[tf];end=NOW//span*span
            self.b.frames[tf]=[Bar(end-(240-i)*span,1.101,1.1011,1.1009,1.101,10) for i in range(240)]
        self.e=Engine(self.b,self.store,lambda:self.now[0])
        self.c=create_app(self.e,'secret').test_client()
        self.h={'Authorization':'Bearer secret','X-FXM1-Client':'R51'}
    def warm(self):
        for _ in range(6):self.e.step();self.now[0]+=.25
    def test_wait_preserves_independent_forecast_without_any_order_or_auto(self):
        self.warm();s=self.e.snapshot()
        self.assertEqual(s['decision']['signal'],'WAIT')
        f=s['forecast'].get('price_forecast',{})
        self.assertTrue(f.get('available'),f)
        self.assertIn(self.e.account_key,f['scope'])
        self.assertEqual(len(self.store.price_forecasts(f['scope'])),1)
        self.assertFalse(self.e.auto);self.assertFalse(self.b.sent)
    def test_each_observer_uses_own_frame_and_read_endpoint_never_trades(self):
        self.warm()
        f=self.e.forecast_snapshot('M15')['forecast'].get('price_forecast',{})
        self.assertTrue(f.get('available'),f);self.assertEqual(f['timeframe'],'M15')
        self.assertNotEqual(f['scope'],self.e.forecast['price_forecast']['scope'])
        before=copy.deepcopy(self.store.load('engine'))
        response=self.c.get('/ec/price-forecasts?tf=M15',headers=self.h)
        self.assertEqual(response.status_code,200,response.get_json())
        self.assertEqual(response.get_json()['snapshots'][0]['scope'],f['scope'])
        self.assertEqual(self.store.load('engine'),before);self.assertFalse(self.b.sent)
        self.assertEqual(self.c.get('/ec/price-forecasts?tf=M15').status_code,401)
    def test_stale_market_cannot_be_published_as_live_price_forecast(self):
        self.warm();self.b.quote_age=60
        self.now[0]+=2;self.e.step()
        f=self.e.snapshot()['forecast']
        self.assertFalse(f.get('available',False))
        self.assertFalse(self.b.sent)
