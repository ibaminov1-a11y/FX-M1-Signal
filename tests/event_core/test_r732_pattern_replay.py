"""Chronology is necessary to label an outcome; geometry alone is not evidence."""
import copy
import unittest
from event_core.model import Bar, Quote, atr
from event_core.scenarios.structure import detect_patterns
from event_core.scenarios.lifecycle import create_scenarios, advance
from event_core.scenarios import pattern_view
from test_r5_scenarios import lane, BASE

class PatternOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.bars=lane('RANGE');self.a=atr(self.bars)
        pattern=next(p for p in detect_patterns(self.bars) if p['family']=='RANGE')
        self.s=next(s for s in create_scenarios(pattern,self.bars,self.a,1.101,BASE) if s['type']=='DIRECT_BREAKOUT' and s['side']==1)
    def outcome(self,s,bars=(),now=BASE+180):
        self.assertTrue(hasattr(pattern_view,'display_outcome'),'READ_ONLY_OUTCOME_MISSING')
        before=copy.deepcopy(s)
        result=pattern_view.display_outcome(s,list(bars),'M1',now)
        self.assertEqual(s,before,'Display evaluation changed trading state')
        return result
    def confirm(self):
        prev=None;t=self.s['activation']
        for i,d in enumerate((-.1,.03,.06)):
            price=t+d*self.a;q=Quote((BASE+i)*1000,price,price+.00001)
            advance(self.s,q,prev,BASE+i,self.a,self.bars);prev=q
        self.assertEqual(self.s['status'],'CONFIRMED')
        return prev
    def test_same_bar_target_and_cancel_is_unknown_without_ticks(self):
        self.confirm();s=self.s
        b=Bar(BASE+60,s['trigger'],s['target1']+.00001,s['invalidation']-.00001,s['trigger'])
        self.assertEqual(self.outcome(s,[b])['status'],'UNKNOWN')
    def test_price_before_confirmation_cannot_be_counted_as_success(self):
        b=Bar(BASE,1.101,self.s['target1']+.00001,self.s['invalidation']-.00001,1.101)
        self.assertEqual(self.outcome(self.s,[b])['status'],'PENDING')
        self.confirm();self.assertEqual(self.outcome(self.s,[b])['status'],'UNKNOWN')
    def test_recorded_terminal_tick_has_its_own_evidence_time(self):
        prev=self.confirm();target=self.s['target'];q=Quote((BASE+3)*1000,target+.00001,target+.00002)
        advance(self.s,q,prev,BASE+3,self.a,self.bars)
        result=self.outcome(self.s)
        self.assertEqual(result['status'],'TARGET_REACHED');self.assertEqual(result['evidence_time'],BASE+3)
        self.assertEqual(result['source'],'OBSERVED_TICK')
    def test_cancel_and_expiry_are_not_targets(self):
        prev=self.confirm();p=self.s['invalidation']-.00001
        advance(self.s,Quote((BASE+3)*1000,p,p+.00001),prev,BASE+3,self.a,self.bars)
        self.assertEqual(self.outcome(self.s)['status'],'INVALIDATED')
        expired=copy.deepcopy(self.s);expired['status']='EXPIRED';expired['stage']='EXPIRED';expired['observed_events']=[]
        self.assertEqual(self.outcome(expired)['status'],'EXPIRED')
    def test_new_bar_target_is_not_execution_confirmation(self):
        self.confirm();s=self.s;b=Bar(BASE+60,s['trigger'],s['target']+.00001,s['trigger'],s['target'])
        result=self.outcome(s,[b]);self.assertEqual(result['status'],'TARGET_REACHED')
        self.assertEqual(result['source'],'CLOSED_BID_BAR');self.assertFalse(result['execution_confirmed'])
    def test_future_bar_is_not_evidence(self):
        self.confirm();s=self.s;b=Bar(BASE+600,s['trigger'],s['target']+.00001,s['trigger'],s['target'])
        self.assertEqual(self.outcome(s,[b])['status'],'PENDING')
    def test_sell_bid_bar_without_spread_is_not_ask_execution_evidence(self):
        self.confirm();s=copy.deepcopy(self.s);s.update(side=-1,target=1.100,target1=1.100,invalidation=1.105)
        b=Bar(BASE+60,1.101,1.102,1.09999,1.100)
        self.assertEqual(self.outcome(s,[b])['status'],'UNKNOWN')

if __name__=='__main__':unittest.main()
