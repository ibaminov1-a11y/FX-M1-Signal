import unittest
import test_r5_scenarios as cases
from event_core.scenarios.lifecycle import remaining_path, _confirm
from event_core.model import Quote
from test_r5_scenarios import BASE

class PathTests(unittest.TestCase):
    setUp=cases.LifecycleTests.setUp
    pick=cases.LifecycleTests.pick
    update=cases.LifecycleTests.update
    def test_false_break_has_explicit_neutral_confirmation_before_trade(self):
        s=self.pick('FALSE_BREAK_RETURN',-1)
        path=remaining_path(s,1.101,BASE)
        confirm=next((p for p in path if p.get('anchor')=='MICRO_CONFIRM'),None)
        self.assertIsNotNone(confirm,'SELL return is preparation; fresh continuation confirmation must be visible')
        self.assertEqual(confirm.get('phase'),'PREPARATION')
        for p in path:
            self.assertEqual(p.get('phase'),'TRADE' if p.get('label') in ('T1','T2') else 'LIVE' if p.get('anchor')=='LIVE' else 'PREPARATION')

    def test_direct_break_continuation_is_still_visible_after_break(self):
        s=self.pick('DIRECT_BREAKOUT');t=s['activation']
        self.update(s,[t-.1*self.a,t+.03*self.a])
        path=remaining_path(s,t+.03*self.a,BASE+1)
        self.assertTrue(any(p.get('anchor')=='MICRO_CONFIRM' for p in path))

    def test_no_entry_when_nearest_target_already_passed(self):
        s=self.pick('FALSE_BREAK_RETURN',-1)
        trigger=s['target1']-.01*self.a
        q=Quote((BASE+10)*1000,trigger-.02*self.a,trigger-.02*self.a+.00001)
        _confirm(s,q,BASE+10,trigger,self.a)
        self.assertFalse(s['entry_ready'],'A completed target cannot justify a new entry')
