"""Fixed prospective plans: the data prefix, not future bars, creates each event."""
import copy,unittest,importlib.util
from event_core.model import Config, Quote, Bar
from fakes import wave

class StablePlanTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.find_spec('event_core.scenarios.stable_plans')
        self.assertIsNotNone(spec,'No stable plan lifecycle exists in the shipped engine')
        from event_core.scenarios.stable_plans import StablePlans
        self.now=1800000000.;self.cfg=Config(mode='NORMAL',runtime_model='R7')
        self.bars=wave(self.now,count=48,trend=0)
        self.a=.0002;self.low=min(b.low for b in self.bars[-12:]);self.high=max(b.high for b in self.bars[-12:])
        self.book=StablePlans(self.cfg)
    def tick(self,price,seconds=1):
        self.now+=seconds;q=Quote(int(self.now*1000),price,price+.00001)
        return self.book.observe(self.bars,q,self.now,self.a)
    def test_first_quote_cannot_retroactively_confirm(self):
        self.assertIsNone(self.tick(self.low+.4*self.a))
        self.assertFalse(any(p['entry_ready'] for p in self.book.plans.values()))
    def test_buy_reclaim_requires_touch_return_and_later_confirmation(self):
        self.tick(self.low+.5*self.a)
        self.assertIsNone(self.tick(self.low+.04*self.a))
        self.assertIsNone(self.tick(self.low+.20*self.a))
        s=self.tick(self.low+.28*self.a)
        self.assertIsNotNone(s);self.assertEqual(s['side'],1);self.assertTrue(s['entry_ready'])
        self.assertEqual(s['type'],'BOUNDARY_RECLAIM')
        self.assertEqual(s['event_id'].split('|')[-1],str(int(self.now*1000)))
    def test_missed_confirmation_rearms_without_moving_plan_levels(self):
        for d in (.5,.04,.20,.28):s=self.tick(self.low+d*self.a)
        fixed={k:s[k] for k in ('scenario_id','trigger','invalidation','target1','expires_at')}
        self.tick(self.low+.30*self.a,seconds=6)
        self.assertEqual(s['stage'],'WATCHING','An unexecuted confirmation cannot remain armed forever')
        self.assertFalse(s['entry_ready'])
        self.assertEqual(fixed,{k:s[k] for k in fixed})
    def test_sell_reclaim_is_symmetric(self):
        self.tick(self.high-.5*self.a)
        self.assertIsNone(self.tick(self.high-.04*self.a))
        self.assertIsNone(self.tick(self.high-.20*self.a))
        s=self.tick(self.high-.28*self.a)
        self.assertIsNotNone(s);self.assertEqual(s['side'],-1)
    def test_plain_new_low_does_not_open_buy_and_stop_never_widens(self):
        self.tick(self.low+.5*self.a)
        plans=copy.deepcopy(self.book.state())
        for d in (.05,-.05,-.15,-.25):self.assertIsNone(self.tick(self.low+d*self.a))
        old=next(p for p in plans['plans'].values() if p['side']==1 and p['type']=='BOUNDARY_RECLAIM')
        new=self.book.plans[old['scenario_id']]
        self.assertEqual(old['invalidation'],new['invalidation']);self.assertEqual(old['target1'],new['target1'])
    def test_small_changes_and_new_closed_bar_do_not_move_plan(self):
        self.tick(self.low+.5*self.a);before=copy.deepcopy(self.book.state())
        for d in (.49,.48,.50,.46):self.tick(self.low+d*self.a)
        self.bars=self.bars[1:]+[Bar(self.bars[-1].time+300,1.1,1.1001,1.0999,1.1,1)]
        self.tick(self.low+.45*self.a)
        for key,p in before['plans'].items():
            for f in ('scenario_id','trigger','invalidation','target1','expires_at'):
                self.assertEqual(p[f],self.book.plans[key][f])
    def test_duplicate_quote_never_emits_second_event(self):
        self.tick(self.low+.5*self.a);self.tick(self.low+.04*self.a);self.tick(self.low+.20*self.a)
        s=self.tick(self.low+.28*self.a);self.assertIsNotNone(s)
        self.assertIsNone(self.tick(self.low+.28*self.a,0))
        self.book.consume(s['event_id'])
        self.assertIsNone(self.tick(self.low+.30*self.a))
    def test_feed_gap_requires_new_observation(self):
        self.tick(self.low+.5*self.a);self.tick(self.low+.04*self.a);self.tick(self.low+.20*self.a)
        self.assertIsNone(self.tick(self.low+.28*self.a,15))
    def test_restart_keeps_fixed_plan_but_not_permission(self):
        from event_core.scenarios.stable_plans import StablePlans
        self.tick(self.low+.5*self.a);self.tick(self.low+.04*self.a);self.tick(self.low+.20*self.a)
        before=self.book.state();self.book=StablePlans(self.cfg,before)
        self.assertIsNone(self.tick(self.low+.28*self.a))
        self.assertEqual(set(before['plans']),set(self.book.plans))
    def test_hard_invalidation_retires_not_repaints(self):
        self.tick(self.low+.5*self.a);self.tick(self.low-.05*self.a)
        s=next(p for p in self.book.plans.values() if p['side']==1 and p['type']=='BOUNDARY_RECLAIM')
        self.assertIsNone(self.tick(s['invalidation']-.1*self.a))
        self.assertEqual(s['status'],'FAILED')
    def test_plan_expiry_is_not_renewed_by_each_tick(self):
        self.tick(self.low+.5*self.a);s=next(iter(self.book.plans.values()));expires=s['expires_at']
        self.now=expires;self.tick(self.low+.45*self.a)
        self.assertEqual(s['status'],'EXPIRED');self.assertEqual(s['expires_at'],expires)

if __name__=='__main__':unittest.main()
