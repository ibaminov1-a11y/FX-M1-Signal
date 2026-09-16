import tempfile
import unittest
from pathlib import Path

from event_core.engine import Engine
from event_core.model import Config, Decision, Setup
from event_core.mt5_adapter import MAGIC
from event_core.store import Store
from event_core.strategy import Strategy
from fakes import FakeBroker
from test_r3_impulse import impulse_fixture

NOW = 1_800_000_000.0


class OppositeReversalTests(unittest.TestCase):
    def test_open_sell_campaign_and_old_sell_setup_must_not_hide_confirmed_buy_analysis(self):
        bars, m1, m15, h1, live, quote, _, _ = impulse_fixture(1)
        strategy = Strategy(Config(timeframe='M5', mode='NORMAL', fee_per_lot=0, approved=True))
        strategy.setup = Setup(
            'old-sell-trigger', -1, 'IMPULSE_PULLBACK', 'TRIGGER', bars[-2].time,
            int(NOW+900), 1.1060, 1.1040, 1.1040,
            pullback=1.1030, trigger=1.1025, trigger_bar=bars[-2].time,
            armed_msc=int((NOW-30)*1000), last_bid=1.1030,
            seen_safe_side=True, last_bar=bars[-2].time,
        )
        decision = strategy.update(
            bars, m15, quote, NOW, campaign_side=-1,
            m1=m1, m15=m15, h1=h1, live_bar=live,
        )
        self.assertEqual((decision.signal, decision.phase, decision.path),
                         ('BUY', 'ENTRY_READY', 'IMPULSE'))
        self.assertIn('old-sell-trigger', strategy.consumed,
                      'opposite confirmed impulse must supersede the stale SELL setup')

    def test_confirmed_opposite_entry_exits_old_campaign_before_any_reverse(self):
        now = [NOW]
        broker = FakeBroker(lambda: now[0])
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'state.sqlite3')
            try:
                engine = Engine(broker, store, lambda: now[0])
                engine.config = Config(timeframe='M5', mode='NORMAL', risk_pct=.25,
                                       fee_per_lot=0, approved=True, cooldown_sec=0)
                engine.strategy = Strategy(engine.config)
                broker._positions = [dict(
                    ticket=101, identifier=101, magic=MAGIC, symbol='EURUSD', side=-1,
                    volume=.01, price_open=1.1040, price_current=1.1030,
                    sl=1.1060, tp=0., profit=0., swap=0., time=int(now[0]),
                    comment='EC1:existing-sell',
                )]
                engine.campaign = dict(
                    id='old-sell', side=-1, mode='NORMAL', timeframe='M5', symbol='EURUSD',
                    started=now[0]-60, budget=100., initial_risk=10., last_entry=1.1040,
                    best_price=1.1030, last_progress=now[0], invalidation=1.1060,
                    add_step_atr=.3, peak=0., position_ids=[101], realized=0., events=['old-sell'],
                )
                engine.auto = True
                engine.paused = False
                opposite = Decision('BUY', 'ENTRY_READY', 'confirmed opposite buy',
                                    'new-buy', 1, 1.1020, 1.1029, 1.1020,
                                    .0005, int(now[0]*1000), path='IMPULSE')
                seen_campaign_side = []

                def update(*args, **kwargs):
                    seen_campaign_side.append(args[4])
                    return opposite

                engine.strategy.update = update
                sent_before = len(broker.sent)
                state = engine.step()

                self.assertEqual(seen_campaign_side, [0],
                                 'market analysis must stay independent of the open campaign side')
                self.assertEqual(broker.closed, [101],
                                 'confirmed opposite market event must exit the old campaign')
                self.assertEqual(len(broker.sent), sent_before,
                                 'do not reverse into BUY in the same engine step')
                self.assertEqual(state['decision']['signal'], 'BUY')
                self.assertTrue(state['exit_pending'],
                                'old campaign remains in exit/reconciliation state until MT5 history confirms close')
                self.assertIn('new-buy', engine.strategy.consumed,
                              'the event that forced exit must not be reused as a late reversal')
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
