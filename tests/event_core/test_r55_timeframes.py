import unittest
from datetime import datetime, timezone
from event_core.model import Bar, Quote, Config, TF_SECONDS, atr
from event_core.scenarios.core import ScenarioCore
from event_core.scenarios.lifecycle import create_scenarios, advance, remaining_path
from event_core.scenarios.structure import detect_patterns
from test_r5_scenarios import lane, BASE


def history(tf):
    return [Bar(BASE+(i-96)*TF_SECONDS[tf], b.open,b.high,b.low,b.close,b.volume)
            for i,b in enumerate(lane('RANGE'))]


class SelectedTimeframeTests(unittest.TestCase):
    def test_scenario_forecast_available_on_every_selected_timeframe(self):
        for tf in TF_SECONDS:
            if tf == 'MN1':continue
            with self.subTest(timeframe=tf):
                bars=history(tf);q=Quote(BASE*1000,1.101,1.10101)
                live=Bar(BASE,q.bid,q.bid,q.bid,q.bid)
                d=ScenarioCore(Config(timeframe=tf)).evaluate(bars,history('M1'),[],[],live,q,BASE)
                self.assertTrue(d.forecast.get('available'),d.reason)
                self.assertTrue(d.forecast['scenarios'])
                self.assertTrue(all(s['pattern']['timeframe']==tf for s in d.forecast['scenarios']))

    def test_monthly_bar_must_reach_next_calendar_month(self):
        ts=lambda y,m,d: int(datetime(y,m,d,tzinfo=timezone.utc).timestamp())
        bars=[Bar(ts(2022+i//12,1+i%12,1),1.101,1.102,1.100,1.101) for i in range(48)]
        bars.append(Bar(ts(2026,1,1),1.101,1.102,1.100,1.101))
        now=ts(2026,1,31);q=Quote(now*1000,1.101,1.10101)
        live=Bar(now,q.bid,q.bid,q.bid,q.bid)
        with self.assertRaisesRegex(ValueError,'незакрытая'):
            ScenarioCore(Config(timeframe='MN1')).evaluate(bars,history('M1'),[],[],live,q,now)
        now=ts(2026,2,1);q=Quote(now*1000,1.101,1.10101)
        d=ScenarioCore(Config(timeframe='MN1')).evaluate(bars,history('M1'),[],[],live,q,now)
        self.assertTrue(d.forecast.get('available'),d.reason)

    def test_normalized_monthly_history_keeps_broker_calendar_boundary(self):
        ts=lambda y,m,d: int(datetime(y,m,d,tzinfo=timezone.utc).timestamp())
        offset=7200
        bars=[Bar(ts(2022+i//12,1+i%12,1)-offset,1.101,1.102,1.100,1.101,
                  clock_offset_seconds=offset) for i in range(49)]
        now=ts(2026,1,31)-offset
        q=Quote(now*1000,1.101,1.10101)
        live=Bar(now,q.bid,q.bid,q.bid,q.bid)
        with self.assertRaisesRegex(ValueError,'незакрытая'):
            ScenarioCore(Config(timeframe='MN1')).evaluate(bars,history('M1'),[],[],live,q,now)
        now=ts(2026,2,1)-offset
        q=Quote(now*1000,1.101,1.10101)
        d=ScenarioCore(Config(timeframe='MN1')).evaluate(bars,history('M1'),[],[],live,q,now)
        self.assertTrue(d.forecast.get('available'),d.reason)

    def test_m5_preserves_original_dual_context_ranking(self):
        bars=history('M5');q=Quote(BASE*1000,1.101,1.10101)
        live=Bar(BASE,q.bid,q.bid,q.bid,q.bid)
        trend=lane('CHANNEL')
        def evaluate(**kwargs):
            return ScenarioCore(Config(timeframe='M5')).evaluate(
                bars,history('M1'),trend,trend,live,q,BASE,**kwargs)
        baseline=evaluate()
        supplied=evaluate(context=[],context_tf='H1')
        scores=lambda d: {s['scenario_id']:s['quality_score'] for s in d.forecast['scenarios']}
        self.assertEqual(scores(baseline),scores(supplied))

    def scenarios(self,tf,duration=None):
        bars=history(tf);a=atr(bars)
        p=next(p for p in detect_patterns(bars,'EUR/USD',tf) if p['family']=='RANGE')
        if duration is not None:p['measurements']['duration']=duration
        return create_scenarios(p,bars,a,1.101,BASE),a

    def test_expiry_and_paths_scale_with_selected_timeframe(self):
        for tf in TF_SECONDS:
            with self.subTest(timeframe=tf):
                span=TF_SECONDS[tf]
                for duration,expected in ((1,span),(10*span,15*span),(100*span,24*span)):
                    scenarios,_=self.scenarios(tf,duration)
                    s=next(s for s in scenarios if s['type']=='DIRECT_BREAKOUT')
                    self.assertEqual(s['expires_at']-BASE,expected)
                    self.assertEqual(s['path'][-1]['minutes'],3*span/60)
                    self.assertEqual(remaining_path(s,1.101,BASE)[-1]['minutes'],3*span/60)

    def test_rotation_target_projects_to_selected_bar_close(self):
        bars=history('H1');a=atr(bars)
        p=next(p for p in detect_patterns(bars,'EUR/USD','H1') if p['family']=='RANGE')
        p['upper'].update(t0=BASE,price=1.102,slope=.000001)
        s=next(s for s in create_scenarios(p,bars,a,1.101,BASE) if s['type']=='RANGE_ROTATION' and s['side']==1)
        self.assertAlmostEqual(s['target2'],1.102)

    def test_retest_window_is_two_selected_bars(self):
        for tf in ('M1','M5','H1'):
            with self.subTest(timeframe=tf):
                scenarios,a=self.scenarios(tf)
                s=next(s for s in scenarios if s['type']=='BREAKOUT_RETEST' and s['side']==1)
                s.update(stage='BREAK_SEEN',break_at=BASE,expires_at=BASE+100000)
                price=s['activation']+.2*a
                for elapsed in (2*TF_SECONDS[tf],2*TF_SECONDS[tf]+1):
                    now=BASE+elapsed;q=Quote(now*1000,price,price+.00001)
                    prev=Quote((now-1)*1000,price,price+.00001)
                    advance(s,q,prev,now,a,history('M1'))
                    self.assertEqual(s['stage'],'BREAK_SEEN' if elapsed==2*TF_SECONDS[tf] else 'EXPIRED')
