"""Release regressions: real state machines, only external broker is synthetic."""
import copy
import importlib.util
import unittest
from event_core.model import Quote
from event_core.scenarios.continuation import Continuation


def scenario(ident='BUY', side=1):
    return dict(scenario_id=ident, scenario_version=1, side=side, status='WATCHING',
                stage='WATCHING', sent=False, entry_ready=False, event_id='',
                type='BOUNDARY_RECLAIM', stable_plan=True, title='fixed boundary',
                created_at=10., expires_at=1000., trigger=1.2 if side>0 else 1.3,
                activation=1.2 if side>0 else 1.3, invalidation=1.1 if side>0 else 1.4,
                target1=1.35 if side>0 else 1.15, target2=None,
                boundary=dict(price=1.2 if side>0 else 1.3,t0=0,slope=0),
                pattern={'atr':.01}, quality_score=60., reason='watch')


class ResumeCrossingTests(unittest.TestCase):
    def replay(self,side,values,age=0,invalid=False):
        observer=Continuation()
        now=100.
        root=scenario('root',side)
        root.update(status='CONFIRMED',target1=1.22+side*.02,target=1.22+side*.02,
                    invalidation=1.22-side*.001,expires_at=1000.,pattern={'atr':.0001})
        campaign=dict(id='campaign',events=['first'],confirmed=True,side=side,
                      last_entry=1.22,invalidation=root['invalidation'],scenario_id='root')
        out=[]
        for i,d in enumerate(values):
            t=now+i+(age if i>=3 else 0)
            bid=1.22+side*d*.0001
            q=Quote(int(t*1000),bid,bid+.000002)
            out.append(observer.observe(campaign,root,q,t,.0001,'NORMAL'))
        return observer,out

    def test_first_resumption_tick_can_also_be_the_breakout_buy_and_sell(self):
        for side in (1,-1):
            with self.subTest(side=side):
                observer,events=self.replay(side,(.2,1.,.6,1.05,1.06))
                self.assertIsNotNone(events[3], 'FIRST_RESUME_CROSSING_WAS_DROPPED')
                self.assertTrue(events[3]['entry_ready'])
                self.assertEqual(events[3]['side'],side)
                self.assertEqual(sum(e is not None for e in events),1)

    def test_late_crossing_stays_blocked(self):
        for side in (1,-1):
            _,events=self.replay(side,(.2,1.,.6,1.4))
            self.assertFalse(any(events))

    def test_feed_gap_cannot_be_recovered_as_entry(self):
        _,events=self.replay(1,(.2,1.,.6,1.05),age=12)
        self.assertFalse(any(events))

    def test_no_pullback_no_add(self):
        _,events=self.replay(1,(.2,.7,1.,1.05))
        self.assertFalse(any(events))


class CommitmentTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('event_core.scenarios.commitment'),
                             'PERSISTED_PRE_ENTRY_COMMITMENT_MISSING')
        from event_core.scenarios.commitment import PlanCommitment
        self.cls=PlanCommitment
        self.book=self.cls()
        self.buy=scenario();self.sell=scenario('SELL',-1)
        self.rows=[self.buy,self.sell]
        self.q=Quote(100000,1.2001,1.20012)

    def select(self, rows=None, q=None, now=100., scope='demo|EURUSD|M5', campaign=None):
        return self.book.select(self.rows if rows is None else rows,q or self.q,now,scope,campaign)

    def test_price_and_rank_changes_do_not_replace_selected_plan(self):
        first=self.select()
        self.assertEqual(first['scenario_id'],'BUY')
        fixed=copy.deepcopy(self.book.state())
        self.sell['quality_score']=99
        picked=self.select([self.sell,self.buy],Quote(101000,1.29,1.29002),101.)
        self.assertEqual(picked['scenario_id'],'BUY')
        self.assertEqual(self.book.state()['original'],fixed['original'])

    def test_initial_selection_does_not_pin_a_remote_high_score_boundary(self):
        self.sell['quality_score']=99
        picked=self.select([self.sell,self.buy])
        self.assertEqual(picked['scenario_id'],'BUY','REMOTE_SCORE_BLOCKED_NEARBY_SETUP')

    def test_restore_retains_identity_but_does_not_restore_entry_permission(self):
        self.select();saved=self.book.state();self.buy.update(entry_ready=True,status='CONFIRMED',confirmed_at=100,event_id='old')
        self.book=self.cls(saved)
        picked=self.select(now=101.)
        self.assertEqual(picked['scenario_id'],'BUY')
        self.assertFalse(picked['entry_ready'])
        self.assertEqual(self.book.state()['original'],saved['original'])

    def test_terminal_plan_is_reported_before_any_replacement(self):
        self.select();self.buy.update(status='FAILED',stage='FAILED',reason='stop crossed')
        self.assertIsNone(self.select(now=101.))
        self.assertEqual(self.book.state()['last_end']['reason'],'stop crossed')
        picked=self.select([self.sell],Quote(102000,1.3,1.30002),102.)
        self.assertEqual(picked['scenario_id'],'SELL')

    def test_unfilled_expiry_cannot_be_extended_by_quote_noise(self):
        self.select();self.buy['expires_at']=5000
        self.assertIsNone(self.select(now=1001.,q=Quote(1001000,1.21,1.21002)))
        self.assertEqual(self.book.state()['last_end']['code'],'PLAN_EXPIRED')

    def test_scope_change_cannot_reuse_permission(self):
        self.select();self.buy.update(entry_ready=True,status='CONFIRMED',event_id='old')
        self.assertIsNone(self.select(scope='other-account|EURUSD|M5',now=101.))
        self.assertEqual(self.book.state()['last_end']['code'],'SCOPE_CHANGED')

    def test_cannot_commit_an_already_confirmed_old_candidate(self):
        self.buy.update(status='CONFIRMED',stage='CONFIRMED',entry_ready=True,confirmed_at=90.)
        self.assertIsNone(self.select([self.buy]))

    def test_original_is_defensive_copy(self):
        self.select();state=self.book.state();state['original']['target1']=99
        self.assertEqual(self.book.state()['original']['target1'],1.35)

    def test_selected_id_is_not_silently_lost_by_display_filter(self):
        self.select();picked=self.select([self.sell],now=101.)
        self.assertIsNone(picked)
        self.assertEqual(self.book.state()['last_end']['code'],'SOURCE_UNAVAILABLE')

if __name__=='__main__':unittest.main()
