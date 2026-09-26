import copy
import importlib.util
import math
import unittest
from event_core.model import Bar, Quote, Config

BASE=1_800_000_000


def lane(kind='TRIANGLE',n=96):
    out=[]
    for i in range(n):
        if kind=='TRIANGLE':lo,hi=1.100+i*.00001,1.104-i*.00001
        elif kind=='WEDGE':lo,hi=1.100+i*.00003,1.104+i*.00001
        elif kind=='BROADENING':lo,hi=1.100-i*.00001,1.102+i*.00001
        elif kind=='CHANNEL':lo,hi=1.100+i*.000015,1.102+i*.000015
        else:lo,hi=1.100,1.102
        v=lo+(hi-lo)*(1+math.sin(i*math.pi/6))/2
        out.append(Bar(BASE+(i-n)*300,v-.000004,v+.000015,v-.000015,v,10))
    return out


def pole_pattern(kind,side=1):
    close=[]
    for i in range(36): close.append(1.08+i*.0007)
    top=close[-1]
    for i in range(40):
        width=.0012*(1-.5*i/40) if kind=='PENNANT' else .0012
        center=top-.0008-i*.000015 if kind=='FLAG' else top-.0008
        close.append(center+width/2*math.sin(i*math.pi/6))
    if side<0:close=[2.2-v for v in close]
    return [Bar(BASE+(i-len(close))*300,close[i-1] if i else v-.0004,v+.00002 if i==0 else max(v,close[i-1])+.00002,min(v,close[i-1])-.00002 if i else v-.00042,v) for i,v in enumerate(close)]

def shaped(vals,side=1):
    points=[(0,1.098),(6,1.099)]+[(14+i*8,v) for i,v in enumerate(vals)]+[(14+len(vals)*8,vals[-1]-.001 if vals[-1]>1.1 else vals[-1]+.001)]
    closes=[]
    for (x,a),(y,b) in zip(points,points[1:]):
        for i in range(x,y):closes.append(a+(b-a)*(i-x)/(y-x))
    closes += [points[-1][1]]*3
    if side<0:closes=[2.202-v for v in closes]
    return [Bar(BASE+(i-len(closes))*300,v,v+.00001,v-.00001,v) for i,v in enumerate(closes)]



def module():
    if importlib.util.find_spec('event_core.scenarios') is None:return None
    from event_core.scenarios.core import ScenarioCore
    return ScenarioCore


class StructureTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module(),'Numeric structural scenario engine is missing')
    def test_geometric_families_are_not_one_renamed_path(self):
        from event_core.scenarios.structure import detect_patterns
        for family in ('TRIANGLE','WEDGE','BROADENING','CHANNEL','RANGE'):
            with self.subTest(family=family):
                found=detect_patterns(lane(family),'EUR/USD','M5')
                self.assertIn(family,{p['family'] for p in found},found)
    def test_no_pole_means_no_flag_or_pennant(self):
        from event_core.scenarios.structure import detect_patterns
        for family in ('CHANNEL','TRIANGLE','RANGE'):
            self.assertFalse({p['family'] for p in detect_patterns(lane(family),'EUR/USD','M5')}&{'FLAG','PENNANT'})
    def test_anchors_are_available_only_after_right_bars_close(self):
        from event_core.scenarios.structure import detect_patterns
        found=detect_patterns(lane(),'EUR/USD','M5')
        self.assertTrue(found)
        for p in found:
            for a in p['anchors']:
                self.assertGreaterEqual(a['available_at'],a['occurred_at']+900)
                self.assertLessEqual(a['available_at'],BASE)
    def test_monotonic_history_does_not_manufacture_a_pattern(self):
        from event_core.scenarios.structure import detect_patterns
        bars=[Bar(BASE+(i-96)*300,1.1+i*.0001,1.10015+i*.0001,1.09998+i*.0001,1.10012+i*.0001) for i in range(96)]
        self.assertEqual(detect_patterns(bars,'EUR/USD','M5'),[])


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module(),'Numeric structural scenario engine is missing')
        from event_core.scenarios.lifecycle import create_scenarios
        from event_core.scenarios.structure import detect_patterns
        from event_core.model import atr
        self.bars=lane('RANGE');self.a=atr(self.bars)
        self.pattern=next(p for p in detect_patterns(self.bars,'EUR/USD','M5') if p['family']=='RANGE')
        self.s=create_scenarios(self.pattern,self.bars,self.a,1.101,BASE)
    def update(self,s,prices):
        from event_core.scenarios.lifecycle import advance
        prev=None
        for i,p in enumerate(prices):
            q=Quote(int((BASE+i)*1000),p,p+.00001)
            advance(s,q,prev,BASE+i,self.a,self.bars)
            prev=q
        return s
    def pick(self,t,side=1):return copy.deepcopy(next(s for s in self.s if s['type']==t and s['side']==side))
    def test_direct_break_does_not_require_retest(self):
        s=self.pick('DIRECT_BREAKOUT');t=s['activation']
        self.update(s,[t-.10*self.a,t+.03*self.a,t+.06*self.a])
        self.assertEqual(s['status'],'CONFIRMED',s)
        self.assertNotIn('RETEST',str(s['observed_events']))
    def test_retest_scenario_cannot_confirm_without_return(self):
        s=self.pick('BREAKOUT_RETEST');t=s['activation']
        self.update(s,[t-.1*self.a,t+.03*self.a,t+.1*self.a,t+.12*self.a])
        self.assertNotEqual(s['status'],'CONFIRMED')
    def test_first_tick_beyond_level_is_not_an_entry(self):
        s=self.pick('DIRECT_BREAKOUT');t=s['activation']
        self.update(s,[t+.03*self.a,t+.04*self.a])
        self.assertNotEqual(s['status'],'CONFIRMED')
    def test_two_buy_hypotheses_exist_and_paths_differ(self):
        a=self.pick('DIRECT_BREAKOUT');b=self.pick('BREAKOUT_RETEST')
        self.assertNotEqual(a['scenario_id'],b['scenario_id'])
        self.assertNotEqual([x['anchor'] for x in a['path']],[x['anchor'] for x in b['path']])
        self.assertFalse(any(x['anchor']=='TRIGGER_RETEST' for x in a['path']))
    def test_expiry_never_moves_with_repeated_quotes(self):
        s=self.pick('DIRECT_BREAKOUT');expiry=s['expires_at']
        self.update(s,[1.101]*7)
        self.assertEqual(expiry,s['expires_at'])
    def test_bar_frame_does_not_change_scenario_identity(self):
        from event_core.scenarios.structure import detect_patterns
        a=detect_patterns(self.bars,'EUR/USD','M5')[0]
        b=detect_patterns(self.bars,'EUR/USD','M5')[0]
        self.assertEqual(a['pattern_id'],b['pattern_id'])
    def test_no_fabricated_second_target_is_required(self):
        s=self.pick('DIRECT_BREAKOUT')
        self.assertIsNone(s['target2'])
        self.assertNotIn('T2',[p.get('label') for p in s['path']])
    def test_invalidation_finishes_a_confirmed_scenario(self):
        s=self.pick('DIRECT_BREAKOUT');t=s['activation']
        self.update(s,[t-.1*self.a,t+.03*self.a,t+.06*self.a,s['invalidation']-.01*self.a])
        self.assertEqual(s['status'],'FAILED')
    def test_moving_line_under_a_stationary_quote_is_not_a_crossing(self):
        from event_core.scenarios.lifecycle import advance
        s=self.pick('DIRECT_BREAKOUT');t=s['activation']
        s['boundary']['slope']=-.1*self.a
        s['boundary']['t0']=BASE
        q=Quote(int((BASE+1)*1000),t-.03*self.a,t-.03*self.a+.00001)
        advance(s,q,Quote(int(BASE*1000),q.bid,q.ask),BASE+1,self.a,self.bars)
        self.assertNotEqual(s['stage'],'BREAK_SEEN')


class ScenarioCoreTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module(),'Numeric structural scenario engine is missing')
    def evaluate(self,core,bars,q,now):
        live=Bar(BASE,q.bid,q.bid+.00001,q.bid-.00001,q.bid)
        m1=[Bar(BASE-60*(20-i),q.bid,q.bid+.00003,q.bid-.00003,q.bid) for i in range(20)]
        return core.evaluate(bars,m1,bars,bars,live,q,now)
    def test_map_v3_has_distinct_events_and_not_directional_probabilities(self):
        core=module()(Config(engine_mode='SCENARIO_V2'));q=Quote(BASE*1000,1.101,1.10101)
        d=self.evaluate(core,lane('RANGE'),q,BASE)
        self.assertEqual(d.forecast['map_version'],3)
        self.assertGreaterEqual(len(d.forecast['scenarios']),2)
        self.assertEqual(d.forecast['model_weight_kind'],'UNCALIBRATED_SCORE')
        self.assertTrue(all(s['calibrated_probability'] is None for s in d.forecast['scenarios']))
    def test_snapshot_is_immutable_and_repeated_tick_never_arms_new_signal(self):
        core=module()(Config(engine_mode='SCENARIO_V2'));q=Quote(BASE*1000,1.101,1.10101)
        d=self.evaluate(core,lane('RANGE'),q,BASE);old=copy.deepcopy(d.forecast)
        self.evaluate(core,lane('RANGE'),q,BASE+.1)
        self.assertEqual(d.forecast,old)
        self.assertEqual(core.previous_quote,q)
    def test_restart_does_not_restore_an_executable_old_crossing(self):
        core=module()(Config(engine_mode='SCENARIO_V2'));q=Quote(BASE*1000,1.101,1.10101)
        self.evaluate(core,lane('RANGE'),q,BASE)
        reloaded=module()(core.config,core.state())
        self.assertIsNone(reloaded.previous_quote)
        self.assertEqual(self.evaluate(reloaded,lane('RANGE'),Quote((BASE+1)*1000,1.1022,1.10221),BASE+1).signal,'WAIT')
    def test_completed_snapshot_not_rewritten_when_future_history_appended(self):
        core=module()(Config(engine_mode='SCENARIO_V2'));q=Quote(BASE*1000,1.101,1.10101)
        self.evaluate(core,lane('RANGE'),q,BASE)
        old=copy.deepcopy(core.snapshots)
        b=lane('RANGE')+[Bar(BASE,1.101,1.102,1.100,1.1015)]
        self.evaluate(core,b,Quote((BASE+301)*1000,1.1015,1.10151),BASE+301)
        for key,value in old.items():self.assertEqual(core.snapshots[key],value)


class ExtendedStructureTests(unittest.TestCase):
    def test_flag_and_pennant_require_measured_prior_pole_in_both_directions(self):
        from event_core.scenarios.structure import detect_patterns
        for family in ('FLAG','PENNANT'):
            for direction in (1,-1):
                found=[p for p in detect_patterns(pole_pattern(family,direction)) if p['family']==family]
                self.assertTrue(found,(family,direction));self.assertEqual(found[0]['bias'],direction)
                self.assertGreater(found[0]['measurements']['pole']['height'],found[0]['atr']*3)
    def test_distinct_reversal_structures_in_both_directions(self):
        from event_core.scenarios.structure import detect_patterns
        for values,family in (([1.102,1.100,1.102],'MULTI_EXTREME'),
                              ([1.102,1.100,1.104,1.100,1.102],'HEAD_SHOULDERS')):
            for direction in (1,-1):
                found=detect_patterns(shaped(values,direction))
                self.assertIn(family,{p['family'] for p in found})
    def test_equal_peaks_do_not_become_head_and_shoulders(self):
        from event_core.scenarios.structure import detect_patterns
        found=detect_patterns(shaped([1.102,1.100,1.102,1.100,1.102]))
        self.assertNotIn('HEAD_SHOULDERS',{p['family'] for p in found})
    def test_gap_cannot_resume_old_break_confirmation(self):
        from event_core.scenarios.core import ScenarioCore
        from event_core.model import atr
        bars=lane('RANGE');a=atr(bars);core=ScenarioCore(Config(engine_mode='SCENARIO_V2'))
        def evaluate(price,now):
            q=Quote(int(now*1000),price,price+.00001)
            live=Bar(BASE,price,price+.00001,price-.00001,price)
            m1=[Bar(BASE-(20-i)*60,1.101,1.10103,1.10097,1.101) for i in range(20)]
            return core.evaluate(bars,m1,bars,bars,live,q,now)
        evaluate(1.101,BASE)
        s=next(s for s in core.scenarios.values() if s['type']=='DIRECT_BREAKOUT' and s['side']==1)
        t=s['activation'];evaluate(t+.03*a,BASE+1)
        self.assertEqual(s['stage'],'BREAK_SEEN')
        evaluate(t+.04*a,BASE+20)
        d=evaluate(t+.05*a,BASE+21)
        self.assertNotEqual(s['status'],'CONFIRMED','A 19-second data gap must cancel old evidence')
        self.assertNotEqual(d.signal,'BUY')
