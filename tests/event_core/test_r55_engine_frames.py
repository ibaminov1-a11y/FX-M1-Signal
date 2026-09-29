"""Selected scenario frames reach the calculator without borrowing M5 data."""
import calendar
from pathlib import Path
import tempfile
import unittest

from fakes import FakeBroker, wave
from event_core.engine import Engine
from event_core.model import Bar, Blocked, TF_SECONDS, validate_bar_history
from event_core.scenarios.structure import causal_points
from event_core.store import Store


def stamp(year, month, day=1):
    return calendar.timegm((year, month, day, 0, 0, 0))


NOW = stamp(2026, 9, 29) + 43200
CONTEXTS = {'M1':'M5', 'M5':'M15', 'M10':'H1', 'M15':'H1', 'H1':'H4',
            'H4':'D1', 'D1':'W1', 'W1':'MN1', 'MN1':'MN1'}


class FrameBroker(FakeBroker):
    def __init__(self):
        super().__init__(lambda: NOW)
        self.requests=[];self.live_requests=[]
        self.frames={tf:wave(NOW,tf=span) for tf,span in TF_SECONDS.items()}
        dates=[stamp(2023+y//12,y%12+1) for y in range(44)]
        self.frames['MN1']=[Bar(t,1.1,1.102,1.099,1.101,10) for t in dates]
        self.future_live=False

    def bars(self,symbol,tf):
        self.requests.append(tf)
        return self.frames[tf]

    def current_bar(self,symbol,tf):
        self.live_requests.append(tf)
        opened=stamp(2026,9) if tf=='MN1' else NOW//TF_SECONDS[tf]*TF_SECONDS[tf]
        if self.future_live:opened=NOW+120
        return Bar(opened,1.1,1.102,1.099,1.101,2)


class EngineFrameTests(unittest.TestCase):
    def engine(self,tf):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        store=Store(Path(directory.name)/'state.sqlite3');self.addCleanup(store.close)
        store.save('engine',{'config':{'engine_mode':'SCENARIO_V2','timeframe':tf}})
        broker=FrameBroker()
        return Engine(broker,store,lambda:NOW),broker

    def test_all_selected_frames_load_live_fixed_layers_and_actual_context_once(self):
        for tf,context in CONTEXTS.items():
            with self.subTest(tf=tf):
                engine,broker=self.engine(tf)
                engine._refresh_market(NOW)
                self.assertEqual(engine.market_errors,[])
                self.assertEqual(engine.bars,broker.frames[tf])
                self.assertEqual(engine.context,broker.frames[context])
                self.assertEqual(engine.m1,broker.frames['M1'])
                self.assertEqual(engine.m15,broker.frames['M15'])
                self.assertEqual(engine.h1,broker.frames['H1'])
                self.assertEqual(broker.live_requests,[tf])
                self.assertEqual(set(broker.requests),{tf,context,'M1','M15','H1'})
                self.assertEqual(len(broker.requests),len(set(broker.requests)))
                decision=engine._evaluate_compute(NOW)
                self.assertNotEqual(decision.phase,'DATA_BLOCK')
                self.assertEqual(decision.forecast['context_timeframe'],context)

    def test_selected_future_live_is_rejected_for_every_frame(self):
        for tf in CONTEXTS:
            with self.subTest(tf=tf):
                engine,broker=self.engine(tf);broker.future_live=True
                engine._refresh_market(NOW)
                self.assertIsNone(engine.live_bar)
                self.assertTrue(any('будущего' in e for e in engine.market_errors))

    def test_selected_unclosed_history_blocks_every_frame(self):
        for tf in CONTEXTS:
            with self.subTest(tf=tf):
                engine,broker=self.engine(tf)
                opened=stamp(2026,9) if tf=='MN1' else NOW//TF_SECONDS[tf]*TF_SECONDS[tf]
                broker.frames[tf].append(Bar(opened,1.1,1.102,1.099,1.101))
                engine._refresh_market(NOW)
                self.assertTrue(any('Незакрытая/будущая' in e for e in engine.market_errors))
                self.assertEqual(engine.bars,[])

    def test_clock_change_restart_isolates_history_and_discards_observation_state(self):
        engine,broker=self.engine('M5');engine._refresh_market(NOW)
        old_scope=engine.market_scope()
        old_rows=engine.store.read_bars(old_scope,'M5')
        saved=engine.store.load('engine')
        saved['compute']={'known':['old-clock-pattern'],'scenarios':{
            'old-clock':{'status':'WATCHING','sent':False}},'consumed':['old-event']}
        engine.store.save('engine',saved)
        broker.clock_identity=lambda:'UTC_EXPLICIT_R55:123@DEMO:180'
        restarted=Engine(broker,engine.store,lambda:NOW)
        self.assertNotEqual(restarted.market_scope(),old_scope)
        self.assertEqual(restarted.compute.scenarios,{})
        self.assertEqual(restarted.compute.known,set())
        self.assertEqual(restarted.store.read_bars(restarted.market_scope(),'M5'),[])
        restarted._refresh_market(NOW)
        self.assertEqual(restarted.store.read_bars(old_scope,'M5'),old_rows)
        self.assertFalse(restarted.auto)
        self.assertTrue(restarted.paused)
        self.assertEqual(restarted.snapshot()['market_history_generation'],broker.clock_identity())
        self.assertEqual(restarted.store.load('engine')['broker_clock_identity'],broker.clock_identity())

    def test_clock_change_requires_flat_saved_campaign_and_no_unknown_intent(self):
        for exposure in ('campaign','intent','position','order'):
            with self.subTest(exposure=exposure):
                engine,broker=self.engine('M5')
                if exposure=='campaign':
                    saved=engine.store.load('engine');saved['campaign']={'id':'open'}
                    engine.store.save('engine',saved)
                elif exposure=='intent':engine.store.intent('pending-event','UNKNOWN',{})
                elif exposure=='position':broker.positions=lambda:[{'ticket':123}]
                else:broker.orders=lambda:[{'ticket':123}]
                before=engine.store.load('engine')
                broker.clock_identity=lambda:'UTC_EXPLICIT_R55:123@DEMO:180'
                with self.assertRaises(Blocked):Engine(broker,engine.store,lambda:NOW)
                self.assertEqual(engine.store.load('engine'),before)


class CalendarCloseTests(unittest.TestCase):
    def test_corrected_monthly_history_waits_for_broker_calendar_close(self):
        # UTC+3 monthly open is Sep 30 21:00 UTC; its close is Oct 31 21:00 UTC.
        bar=Bar(stamp(2026,10)-10800,1.,1.2,.9,1.1,clock_offset_seconds=10800)
        with self.assertRaises(Blocked):
            validate_bar_history([bar],'MN1',stamp(2026,10)+86400)
        validate_bar_history([bar],'MN1',stamp(2026,11)-10800)

    def test_monthly_history_closes_on_calendar_boundary(self):
        for opened,closed in ((stamp(2024,2),stamp(2024,3)),
                              (stamp(2025,2),stamp(2025,3)),
                              (stamp(2025,12),stamp(2026,1)),
                              (stamp(2026,1),stamp(2026,2))):
            with self.subTest(opened=opened):
                bars=[Bar(opened,1.,1.2,.9,1.1)]
                with self.assertRaises(Blocked):validate_bar_history(bars,'MN1',closed-2)
                validate_bar_history(bars,'MN1',closed)

    def test_monthly_pivot_is_available_only_after_confirmation_month_closes(self):
        dates=[stamp(2023,10),stamp(2023,11),stamp(2023,12),stamp(2024,1),stamp(2024,2)]
        bars=[Bar(t,1.,high,.9,1.) for t,high in zip(dates,[1.1,1.2,1.5,1.2,1.1])]
        points=causal_points(bars,'MN1')
        self.assertEqual(len(points),1)
        self.assertEqual(points[0]['available_at'],stamp(2024,3))
