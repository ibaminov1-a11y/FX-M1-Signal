import unittest
from event_core.replay import ReplayBroker
from event_core.model import Config,Quote,Blocked,Decision
from event_core.risk import Plan
class ReplayTests(unittest.TestCase):
 def meta(self):return dict(symbol='EURUSD',point=.00001,digits=5,tick_size=.00001,stops_level=0,volume_min=.01,volume_max=100,volume_step=.01,contract_size=100000,currency_profit='USD',margin_per_lot=1000)
 def test_closed_bars_no_future(self):
  b=ReplayBroker(self.meta(),Config(fee_per_lot=0),100);b.advance(Quote(1800000000000,1.1,1.10001));self.assertEqual(len(b.bars('', 'M5')),0)
  b.advance(Quote(1800000300000,1.2,1.20001));self.assertEqual(b.bars('','M5')[0].close,1.1)
 def test_gap_stop_costs_not_fill_at_ideal_level(self):
  b=ReplayBroker(self.meta(),Config(fee_per_lot=7),100,0);b.advance(Quote(1800000000000,1.1,1.10001))
  p=Plan(1,'EURUSD',.01,1.10001,1.099,1.10004,1.09897,1.1,1.1,10,'test')
  b.send(p,'test');b.advance(Quote(1800000001000,1.098,1.09801));self.assertFalse(b._positions);self.assertLess(b.balance,98)
 def test_non_usd_profit_currency_requires_conversion_data(self):
  m=self.meta();m['currency_profit']='JPY'
  with self.assertRaises(Blocked):ReplayBroker(m,Config(fee_per_lot=0),100)
 def test_latency_returns_unknown_not_false_fill(self):
  b=ReplayBroker(self.meta(),Config(fee_per_lot=0),100,200);b.advance(Quote(1800000000000,1.1,1.10001))
  p=Plan(1,'EURUSD',.01,1.10001,1.099,1.10004,1.09897,1.1,1.1,10,'test')
  self.assertEqual(b.send(p,'test')['status'],'UNKNOWN');self.assertFalse(b._positions)
  b.advance(Quote(1800000000300,1.1002,1.10021));self.assertEqual(len(b._positions),1)
