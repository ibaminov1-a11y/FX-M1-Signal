import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'mt5_bridge'))

from event_core.model import Bar, Config, Quote, pivots
from event_core.strategy import Strategy


def gradual_downtrend(count=40, tf=300):
    """Smooth staircase trend: no 3-bar 0.8 ATR burst at the final bar.

    The final closed bar is exactly when a new lower-low pivot becomes confirmed.
    A structure-driven engine must notice that event instead of staying SEARCH.
    """
    phase = math.pi / 4
    start = 1_800_000_000
    bars = []
    for i in range(count):
        close = 1.2000 - i * 0.00001 + math.sin(i * math.pi / 4 + phase) * 0.00008
        open_ = close + 0.000005
        bars.append(Bar(start + i * tf, open_, max(open_, close) + 0.000015,
                        min(open_, close) - 0.000015, close, 10))
    return bars


def gradual_context(count=32, tf=900):
    start = 1_799_970_000
    bars = []
    for i in range(count):
        close = 1.2040 - i * 0.00004 + math.sin(i * math.pi / 4) * 0.00010
        open_ = close + 0.000008
        bars.append(Bar(start + i * tf, open_, max(open_, close) + 0.00002,
                        min(open_, close) - 0.00002, close, 10))
    return bars


class LiveStructureRegressionTests(unittest.TestCase):
    def test_fresh_confirmed_gradual_structure_creates_scenario(self):
        bars = gradual_downtrend()
        context = gradual_context()
        points = pivots(bars)
        self.assertTrue(any(p['known_at'] == bars[-1].time for p in points),
                        'fixture must confirm a fresh pivot on the latest closed bar')

        cfg = Config(symbol='EUR/USD', timeframe='M5', mode='NORMAL',
                     fee_per_lot=0, approved=True)
        s = Strategy(cfg)
        now = bars[-1].time + 300
        q = Quote(int(now * 1000), bars[-1].close, bars[-1].close + 0.00001)
        d = s.update(bars, context, q, now)

        self.assertIn(d.phase, ('PULLBACK', 'TRIGGER'),
                      'fresh confirmed LH/LL structure must start a scenario even without a 0.8 ATR burst')
        self.assertEqual(-1, d.side)
        self.assertIsNotNone(s.setup)

    def test_plateau_high_low_can_be_confirmed_deterministically(self):
        start = 1_800_000_000
        highs = [10, 11, 12, 12, 11, 10, 9]
        lows =  [ 9, 10, 11, 11, 10,  9, 8]
        bars = [Bar(start + i * 300, (hi + lo) / 2, hi, lo, (hi + lo) / 2, 1)
                for i, (hi, lo) in enumerate(zip(highs, lows))]
        ps = pivots(bars, width=2)
        self.assertTrue(any(p['kind'] == 'H' and p['price'] == 12 for p in ps),
                        'equal-price plateau must yield one deterministic confirmed high')


if __name__ == '__main__':
    unittest.main()
