"""Behavioral R7.3 safety regressions; only the external broker is simulated."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from event_core.engine import Engine
from event_core.model import Blocked, Config, Decision, TF_SECONDS
from event_core.mt5_adapter import MAGIC
from event_core.risk import plan_order
from event_core.store import Store
from fakes import FakeBroker
from test_r56_multiframe import IndependentBroker, NOW


class CampaignNetRiskTests(unittest.TestCase):
    def campaign_with_partial_exit(self, *, partial=False, delayed=False):
        now=[float(NOW)]
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        store=Store(Path(folder.name)/'state.sqlite3');self.addCleanup(store.close)
        broker=FakeBroker(lambda:now[0])
        engine=Engine(broker,store,lambda:now[0])
        engine.config=Config(approved=True,fee_per_lot=0,cooldown_sec=0)
        broker.bid=1.103;broker.ask=1.10301
        broker._positions=[dict(ticket=pid,identifier=pid,magic=MAGIC,
            symbol='EURUSD',side=1,volume=.01,price_open=1.101,
            sl=1.100,tp=0.,profit=0.,swap=0.,time=NOW-10,comment='leg-'+str(pid))
            for pid in (201,202)]
        broker.deals=[dict(ticket=pid*10,position_id=pid,magic=MAGIC,
            symbol='EURUSD',comment='leg-'+str(pid),type=0,entry=0,
            time_msc=(NOW-10)*1000,volume=.01,profit=0.,commission=0.,swap=0.,fee=0.)
            for pid in (201,202)]
        engine.campaign=dict(id='two-legs',position_ids=[201,202],side=1,
            symbol='EURUSD',mode='NORMAL',timeframe='M5',started=NOW-10,
            last_entry=1.101,budget=100.,realized=0.,add_step_atr=.3,
            invalidation=1.100,events=['first','second'],confirmed=True)
        engine._refresh(now[0]);engine._reconcile()
        engine.info=broker.symbol('EUR/USD')
        opening_history=list(broker.deals)
        if partial:broker._positions[0]['volume']=.005
        else:broker._positions.pop(0)
        broker.deals.append(dict(broker.deals[0],ticket=2011,type=1,entry=1,
            time_msc=(NOW+1)*1000,volume=.005 if partial else .01,profit=-4. if partial else -3.))
        if delayed:broker.history=lambda observed: list(opening_history)
        now[0]+=1
        decision=Decision('BUY','ENTRY_READY','fresh add','temporal-add',1,
            1.1025,1.10299,1.1025,.001,int(now[0]*1000),entry_class='CONFIRMED')
        return engine,broker,now,decision

    def test_position_or_volume_decrease_refreshes_history_before_regular_interval(self):
        for partial in (False,True):
            with self.subTest(partial=partial):
                engine,broker,now,_=self.campaign_with_partial_exit(partial=partial)
                engine._refresh(now[0]);engine._reconcile()
                self.assertAlmostEqual(engine.campaign['realized'],-4. if partial else -3.)
                self.assertEqual(engine.history_time,now[0])

    def test_actual_add_refreshes_realized_loss_before_sending(self):
        for partial in (False,True):
            with self.subTest(partial=partial):
                engine,broker,now,decision=self.campaign_with_partial_exit(partial=partial)
                with self.assertRaisesRegex(Blocked,'усреднение'):
                    engine._entry(decision,now[0])
                self.assertFalse(broker.sent)

    def test_delayed_close_history_blocks_add_until_volume_reconciles(self):
        for partial in (False,True):
            with self.subTest(partial=partial):
                engine,broker,now,decision=self.campaign_with_partial_exit(partial=partial,delayed=True)
                engine._refresh(now[0]);engine._reconcile()
                with self.assertRaisesRegex(Blocked,'сверк'):
                    engine._entry(decision,now[0])
                self.assertFalse(broker.sent)
                self.assertIn('RECONCILING',engine._entry_gate()['blocks'])
                # Broker history becomes visible with a small realized loss and
                # the complete campaign is now positive. A new confirmation can add.
                broker.deals[-1]['profit']=-.50
                broker.history=lambda observed: list(broker.deals)
                now[0]+=.1
                engine._entry(replace(decision,event_id='reconciled-add'),now[0])
                self.assertEqual(len(broker.sent),1)
                self.assertAlmostEqual(engine.campaign['realized'],-.50)

    def test_fx_suffix_jpy_metal_and_crypto_keep_native_price_and_risk_rules(self):
        # Synthetic contract specs exercise symbol classification and monetary
        # sizing; these fixtures do not claim to describe any particular broker.
        cases = (
            ('EURUSD.pro', 1.10, .00001, 5, .0002, .01, 100000., True),
            ('USDJPY.a', 150., .001, 3, .02, 1., 1000., True),
            ('XAUUSD.pro', 2000., .01, 2, .20, 5., 100., False),
            ('BTCUSD.pro', 60000., .01, 2, 2., 100., 1., False),
        )
        for symbol, bid, tick, digits, spread, volatility, contract, is_fx in cases:
            for side in (1, -1):
                with self.subTest(symbol=symbol, side=side):
                    broker = FakeBroker(lambda: NOW)
                    broker.bid=bid;broker.ask=bid+spread
                    broker.info.update(name=symbol, point=tick, tick_size=tick, digits=digits)
                    broker.calc_profit=lambda s, name, volume, entry, exit: s*(exit-entry)*volume*contract
                    cfg=Config(symbol=symbol, approved=True, fee_per_lot=0, lot_cap=.10)
                    stop=bid-side*.5*volatility
                    decision=Decision('BUY' if side>0 else 'SELL', 'ENTRY_READY',
                        'native instrument', symbol+str(side), side, stop,
                        bid-side*tick, stop, volatility, NOW*1000, entry_class='CONFIRMED')
                    plan=plan_order(broker,cfg,broker.account(),broker.info,
                        broker.quote(symbol),decision,[],None,NOW)
                    self.assertEqual(plan.symbol,symbol)
                    self.assertGreater((plan.entry-plan.stop)*side,0)
                    self.assertGreater(plan.volume,0)
                    self.assertLessEqual(plan.total_risk,250.)
                    self.assertAlmostEqual(plan.stop/tick,round(plan.stop/tick),places=7)
                    if is_fx:
                        broker.ask=bid+spread*2
                        with self.assertRaisesRegex(Blocked, 'FX-спред'):
                            plan_order(broker,cfg,broker.account(),broker.info,
                                broker.quote(symbol),decision,[],None,NOW)

    def test_closed_volume_retains_its_opening_commission_and_fees(self):
        for closed_volume, expected in ((1., -2.), (.5, -1.)):
            with self.subTest(closed_volume=closed_volume):
                folder = tempfile.TemporaryDirectory()
                self.addCleanup(folder.cleanup)
                store = Store(Path(folder.name) / 'state.sqlite3')
                self.addCleanup(store.close)
                broker = FakeBroker(lambda: NOW)
                engine = Engine(broker, store, lambda: NOW)
                engine.campaign = dict(id='costed-campaign', position_ids=[201, 202])
                broker._positions = [dict(ticket=202, identifier=202, magic=MAGIC,
                    symbol='EURUSD', side=1, volume=.01, price_open=1.102,
                    sl=1.101, swap=0., comment='still-live')]
                common = dict(position_id=201, magic=MAGIC, symbol='EURUSD',
                    comment='campaign', swap=0., profit=0., commission=0., fee=0.)
                broker.deals = [
                    dict(common, ticket=2010, type=0, entry=0,
                         time_msc=(NOW-10)*1000, volume=1., commission=-3., fee=-1.),
                    dict(common, ticket=2011, type=1, entry=1,
                         time_msc=(NOW-5)*1000, volume=closed_volume,
                         profit=4.*closed_volume, commission=-2.*closed_volume),
                ]
                if closed_volume < 1.:
                    broker._positions.append(dict(broker._positions[0], ticket=201,
                        identifier=201, volume=1.-closed_volume))
                engine._refresh(NOW)
                engine._reconcile()
                self.assertAlmostEqual(engine.campaign['realized'], expected)

    def test_realized_loss_must_be_recovered_before_either_side_can_scale_in(self):
        for side in (1, -1):
            with self.subTest(side=side):
                broker = FakeBroker(lambda: NOW)
                cfg = Config(approved=True, fee_per_lot=0, risk_pct=1)
                decision = Decision('BUY' if side == 1 else 'SELL', 'ENTRY_READY',
                    'fresh confirmation', 'new-add', side,
                    broker.bid - side * .0005, broker.bid - side * .00001,
                    broker.bid - side * .0005, .0005, NOW * 1000,
                    entry_class='CONFIRMED')
                position = dict(symbol='EURUSD', side=side, sl=broker.bid-side*.001,
                    volume=.01, price_open=broker.bid-side*.0008, profit=2., swap=0.)
                campaign = dict(budget=100., realized=-3.,
                    last_entry=broker.bid-side*.0007, add_step_atr=.3)
                with self.assertRaisesRegex(Blocked, 'усреднение'):
                    plan_order(broker, cfg, broker.account(), broker.info,
                        broker.quote('EURUSD'), decision, [position], campaign, NOW)
                # The same favorable confirmation becomes eligible only once the
                # complete campaign, including its realized loss, is in net profit.
                campaign['realized'] = -1.
                plan = plan_order(broker, cfg, broker.account(), broker.info,
                    broker.quote('EURUSD'), decision, [position], campaign, NOW)
                self.assertEqual(plan.side, side)
                self.assertGreater(plan.volume, 0)
                self.assertLessEqual(plan.total_risk, 100.)


class SelectedMarketSafetyTests(unittest.TestCase):
    def engine(self, timeframe):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        store = Store(Path(folder.name) / 'state.sqlite3')
        self.addCleanup(store.close)
        store.save('engine', {'config': dict(engine_mode='SCENARIO_V2',
            runtime_model='R7', timeframe=timeframe, mode='NORMAL',
            approved=True, fee_per_lot=0)})
        broker = IndependentBroker(lambda: NOW)
        broker.frames['M10'] = [replace(b, time=NOW+(i-96)*600)
            for i, b in enumerate(broker.frames['M5'])]
        engine = Engine(broker, store, lambda: NOW)
        engine.auto = True
        engine.paused = False
        return engine, broker

    def test_forming_candle_must_follow_closed_history_on_every_selected_frame(self):
        for timeframe in TF_SECONDS:
            with self.subTest(timeframe=timeframe):
                engine, broker = self.engine(timeframe)
                original = broker.current_bar
                broker.current_bar = lambda symbol, tf: (
                    broker.frames[tf][-1] if tf == timeframe else original(symbol, tf))
                state = engine.step()
                self.assertFalse(state['entry_allowed'], timeframe)
                self.assertIn('MARKET_WAIT', state['entry_gate']['blocks'])
                self.assertEqual(state['decision']['phase'], 'DATA_BLOCK')
                self.assertFalse(broker.sent)

    def test_old_monthly_history_blocks_selected_month_and_weekly_context(self):
        for timeframe in ('W1', 'MN1'):
            with self.subTest(timeframe=timeframe):
                engine, broker = self.engine(timeframe)
                broker.frames['MN1'] = broker.frames['MN1'][:-3]
                state = engine.step()
                self.assertFalse(state['entry_allowed'], timeframe)
                self.assertIn('MARKET_WAIT', state['entry_gate']['blocks'])
                self.assertEqual(state['decision']['phase'], 'DATA_BLOCK')
                self.assertFalse(broker.sent)


if __name__ == '__main__':
    unittest.main()
