import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'mt5_bridge'))
from event_core.model import Config, Decision
from event_core.risk import risk_state, plan_order
from fakes import FakeBroker


class OwnRiskOnlyTests(unittest.TestCase):
    def setUp(self):
        self.now = 1800000000.0
        self.b = FakeBroker(lambda: self.now)
        self.cfg = Config(risk_pct=.25, test_capital=100, absolute_risk_cap=.50,
                          fee_per_lot=0, approved=True)

    def test_old_manual_and_v10_losses_do_not_block_ec1(self):
        foreign = dict(ticket=900, identifier=900, magic=999, symbol='EURUSD', side=1,
                       volume=.01, price_open=1.10, sl=1.09, tp=0, profit=-25, swap=0,
                       time=int(self.now), comment='manual')
        deals = []
        for i in range(4):
            pid = 800 + i
            deals += [
                dict(ticket=pid*10, position_id=pid, magic=999, symbol='EURUSD', comment='legacy',
                     type=0, entry=0, time_msc=int((self.now-100+i)*1000), volume=.01,
                     profit=0., commission=0., swap=0., fee=0.),
                dict(ticket=pid*10+1, position_id=pid, magic=999, symbol='EURUSD', comment='legacy',
                     type=1, entry=1, time_msc=int((self.now-90+i)*1000), volume=.01,
                     profit=-5., commission=0., swap=0., fee=0.)]
        account = dict(self.b.account())
        account['equity'] = account['balance'] - 25
        state = risk_state(account, [foreign], deals, self.cfg, self.now)
        self.assertTrue(state['allowed'])
        self.assertEqual(state['blocks'], [])

    def test_budget_uses_actual_mt5_equity_not_100_or_050_cap(self):
        account = dict(self.b.account())
        account['balance'] = 100000.
        account['equity'] = 99800.
        self.assertAlmostEqual(self.cfg.base(account), 99800.)
        self.assertAlmostEqual(self.cfg.budget(account), 249.50)

    def test_margin_guard_uses_actual_account_base(self):
        self.b.calc_margin = lambda *a: 500
        d = Decision('BUY','ENTRY_READY','test','own-risk',1,1.1028,1.10299,1.102,.0005,int(self.now*1000))
        plan = plan_order(self.b, self.cfg, self.b.account(), self.b.info, self.b.quote('EURUSD'),
                          d, [], None, self.now)
        self.assertGreater(plan.volume, 0)


if __name__ == '__main__':
    unittest.main()
