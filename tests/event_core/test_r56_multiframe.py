"""Independent cached forecasts must never become a second order owner."""
import calendar
import copy
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fakes import FakeBroker
from event_core.engine import Engine
from event_core.model import Bar, Blocked, Config, TF_SECONDS, validate_bar_history
from event_core.mt5_adapter import MT5Broker
from event_core.server import create_app
from event_core.store import Store
from test_r5_scenarios import lane

FRAMES=('M1','M5','M15','M30','H1','H4','D1','W1','MN1')
NOW=calendar.timegm((2026,9,29,12,0,0))


class IndependentBroker(FakeBroker):
    def __init__(self,clock):
        super().__init__(clock)
        self.key='123@DEMO';self.generation='UTC_NATIVE_R51'
        self.fail=set();self.calls=[];self.live_calls=[]
        self.bid=1.101;self.ask=1.10101
        self.frames={}
        spans=dict(TF_SECONDS,M30=1800)
        for i,tf in enumerate(FRAMES):
            source=lane(('RANGE','TRIANGLE','CHANNEL','BROADENING','WEDGE')[i%5])
            end=NOW//spans[tf]*spans[tf]
            times=[end+(n-len(source))*spans[tf] for n in range(len(source))]
            if tf=='MN1':
                times=[calendar.timegm((2018+(8+n)//12,(8+n)%12+1,1,0,0,0)) for n in range(96)]
            self.frames[tf]=[replace(b,time=t) for b,t in zip(source,times)]
    def clock_identity(self):return self.generation
    def account(self):return dict(super().account(),key=self.key)
    def bars(self,symbol,tf):
        self.calls.append((symbol,tf))
        if tf in self.fail:raise Blocked('offline '+tf)
        return list(self.frames[tf])
    def current_bar(self,symbol,tf):
        self.live_calls.append((symbol,tf))
        if tf in self.fail:raise Blocked('offline '+tf)
        t=calendar.timegm((2026,9,1,0,0,0)) if tf=='MN1' else int(self.clock())//dict(TF_SECONDS,M30=1800)[tf]*dict(TF_SECONDS,M30=1800)[tf]
        return Bar(t,1.101,max(1.104,self.bid),min(1.098,self.bid),self.bid,1)


class MultiFrameTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state.sqlite3');self.addCleanup(self.store.close)
        self.store.save('engine',{'config':{'engine_mode':'SCENARIO_V2','timeframe':'M5'}})
        self.now=[NOW];self.broker=IndependentBroker(lambda:self.now[0])
        self.engine=Engine(self.broker,self.store,lambda:self.now[0])
        self.client=create_app(self.engine,'secret').test_client()
        self.headers={'Authorization':'Bearer secret','X-FXM1-Client':'R51'}
    def view(self,tf):
        response=self.client.get('/ec/forecast?tf='+tf,headers=self.headers)
        self.assertEqual(response.status_code,200,response.get_json())
        return response.get_json()
    def warm(self):
        for _ in range(5):
            self.engine.step();self.now[0]+=.25

    def test_m30_config_validates_native_duration_and_rejects_malformed_history(self):
        self.assertEqual(Config(timeframe='M30').validate().timeframe,'M30')
        self.assertEqual(TF_SECONDS.get('M30'),1800)
        with self.assertRaises(Blocked):
            validate_bar_history([Bar(NOW-3600,1,2,.5,1),Bar(NOW-2100,1,2,.5,1)],'M30',NOW)

    def test_all_frames_warm_with_distinct_geometry_and_live_overlay(self):
        self.warm()
        state=self.engine.snapshot()
        self.assertEqual([x['timeframe'] for x in state.get('timeframes',[])],list(FRAMES))
        ids=[]
        for tf in FRAMES:
            with self.subTest(tf=tf):
                result=self.view(tf)
                self.assertTrue(result['available'],result.get('reason'))
                self.assertEqual(result['config']['timeframe'],tf)
                self.assertEqual(result['trade_timeframe'],'M5')
                self.assertTrue(result['view_only'])
                self.assertEqual(result['bars'],[asdict(b) for b in self.broker.frames[tf]])
                self.assertTrue(result['live_structure'])
                self.assertTrue(result['forecast']['scenarios'])
                self.assertEqual(result['forecast'].get('timeframe'),tf)
                self.assertTrue(all(s['pattern']['timeframe']==tf for s in result['forecast']['scenarios']))
                ids.extend(s['scenario_id'] for s in result['forecast']['scenarios'])
        self.assertEqual(len(ids),len(set(ids)))
        self.assertNotEqual({s['family'] for s in self.view('M1')['forecast']['scenarios']},
                            {s['family'] for s in self.view('M5')['forecast']['scenarios']})
        self.assertEqual(self.view('M5')['forecast']['snapshot_id'],state['forecast']['snapshot_id'])

    def test_endpoint_is_cached_does_not_execute_and_rejects_unknown_frame(self):
        self.warm();before=copy.deepcopy(self.store.load('engine'))
        calls=list(self.broker.calls);live=list(self.broker.live_calls)
        for tf in FRAMES:self.view(tf)
        self.assertEqual(self.broker.calls,calls);self.assertEqual(self.broker.live_calls,live)
        self.assertEqual(self.store.load('engine'),before)
        self.assertEqual(self.broker.sent,[])
        self.assertEqual(self.client.get('/ec/forecast?tf=M2',headers=self.headers).status_code,409)
        self.assertEqual(self.client.get('/ec/forecast?tf=M1').status_code,401)

    def test_observer_cross_is_never_dispatched_even_with_auto_enabled(self):
        self.warm()
        self.engine.command('approve_profile',{'command_id':'approve-mtf-test','confirmation':'APPROVE_DEMO_RISK'})
        self.engine.command('enable',{'command_id':'enable-mtf-test','confirmation':'ENABLE_DEMO'})
        scenario=next(s for s in self.engine.observers.cores['M1'].scenarios.values()
                      if s['type']=='DIRECT_BREAKOUT' and s['side']==1)
        trigger=scenario['activation'];atr=scenario['pattern']['atr']
        for distance in (-.10,.03,.06):
            self.now[0]+=1.1;self.broker.bid=trigger+distance*atr;self.broker.ask=self.broker.bid+.00001
            self.engine.step();self.engine._refresh_observers(self.now[0],budget=9)
        self.assertTrue(self.engine.auto)
        self.assertEqual(self.view('M1')['decision']['phase'],'ENTRY_READY')
        self.assertEqual(self.view('M1')['decision']['signal'],'BUY')
        self.assertEqual(self.engine.decision.signal,'WAIT')
        self.assertEqual(self.broker.sent,[])
        # Polling the ready candidate still has no dispatch/consume side effect.
        self.view('M1');self.view('M1')
        self.assertEqual(self.broker.sent,[])
        self.assertIsNone(self.engine.campaign)

    def test_refresh_budget_warms_all_frames_without_duplicate_native_reads(self):
        # Holding time fixed makes the one-second shared cache measurable.
        for _ in range(4):
            before=len(self.broker.live_calls)
            self.engine.step()
            remote=[tf for _,tf in self.broker.live_calls[before:] if tf!='M5']
            self.assertLessEqual(len(remote),2)
        self.assertTrue(all(self.view(tf)['available'] for tf in FRAMES))
        self.assertEqual(len(self.broker.calls),len(set(self.broker.calls)))
        before=(list(self.broker.calls),list(self.broker.live_calls))
        self.engine.step()
        self.assertEqual((self.broker.calls,self.broker.live_calls),before)

    def test_quote_and_live_refresh_when_scenario_identity_stays_same(self):
        self.warm();before=self.view('M1')
        self.now[0]+=2;self.broker.bid+=.000002;self.broker.ask+=.000002
        self.warm();after=self.view('M1')
        self.assertEqual(before['forecast']['selection'],after['forecast']['selection'])
        self.assertNotEqual(before['forecast']['snapshot_id'],after['forecast']['snapshot_id'])
        self.assertGreater(after['forecast']['data_asof'],before['forecast']['data_asof'])
        self.assertGreater(after['analysis_time'],before['analysis_time'])
        self.assertNotEqual(before['live_bar']['close'],after['live_bar']['close'])

    def test_remote_failure_keeps_other_frames_and_trade_gate_unchanged(self):
        self.warm();before=self.view('M30');self.broker.fail.add('M30')
        self.now[0]+=2;self.warm()
        bad=self.view('M30');good=self.view('M1')
        self.assertFalse(bad['available']);self.assertIn('M30',bad['reason'])
        self.assertEqual(bad['bars'],before['bars'])
        self.assertTrue(good['available']);self.assertTrue(self.view('M5')['available'])
        self.assertEqual(self.engine.market_errors,[])
        self.assertNotIn('MARKET_WAIT',self.engine.snapshot()['entry_gate']['blocks'])
        self.assertFalse(bad['entry_allowed']);self.assertEqual(self.broker.sent,[])

    def test_unrelated_h1_failure_does_not_block_m1_observer(self):
        self.broker.fail.add('H1');self.warm()
        self.assertFalse(self.view('H1')['available'])
        self.assertTrue(self.view('M1')['available'],self.view('M1')['reason'])
        self.assertEqual(self.view('M1')['forecast']['context_timeframe'],'M5')

    def test_monthly_stale_history_is_not_relabelled_as_fresh_forecast(self):
        self.broker.frames['MN1']=self.broker.frames['MN1'][:-3]
        self.warm()
        self.assertFalse(self.view('MN1')['available'])
        self.assertFalse(self.view('W1')['available'])
        self.assertTrue(self.view('M1')['available'])

    def test_incompatible_timestamp_refresh_does_not_interleave_observer_history(self):
        self.warm();before=self.view('M30')
        # Each new batch is regular on its own, but its grid conflicts with the
        # established same-clock history and must not silently contaminate it.
        self.broker.frames['M30']=[replace(b,time=b.time-60) for b in self.broker.frames['M30']]
        self.now[0]+=2;self.warm();after=self.view('M30')
        self.assertFalse(after['available'])
        self.assertIn('интервал',after['reason'])
        self.assertEqual(after['bars'],before['bars'])
        self.assertTrue(self.view('M1')['available'])

    def test_unwarmed_stale_account_symbol_profile_and_clock_never_relabel_cached_frames(self):
        initial=self.view('M30')
        self.assertFalse(initial['available']);self.assertEqual(initial['config']['timeframe'],'M30')
        self.assertTrue(initial['reason']);self.assertEqual(initial['bars'],[])
        self.warm();old=self.view('M1');self.now[0]+=15
        self.assertFalse(self.view('M1')['available'])
        self.now[0]-=15;self.broker.key='456@DEMO';self.engine.step()
        changed=self.view('M1')
        self.assertFalse(changed['available']);self.assertEqual(changed['bars'],[])
        self.assertEqual(changed['account']['key'],'456@DEMO')
        self.broker.key='123@DEMO';self.warm()
        self.engine.config=replace(self.engine.config,symbol='GBP/USD')
        changed=self.view('M1');self.assertFalse(changed['available']);self.assertEqual(changed['bars'],[])
        self.assertIn('GBPUSD',changed['market_scope'])
        self.engine.config=replace(self.engine.config,symbol='EUR/USD',mode='SCALP')
        self.assertFalse(self.view('M1')['available']);self.warm()
        self.broker.generation='UTC_EXPLICIT_R55:123@DEMO:180'
        changed=self.view('M1');self.assertFalse(changed['available']);self.assertEqual(changed['bars'],[])
        self.assertEqual(old['market_history_generation'],'UTC_NATIVE_R51')

    def test_adopting_account_hides_selected_cache_until_new_account_market_is_read(self):
        self.warm();old=self.view('M5');scope=old['market_scope']
        archived_bars=self.store.read_bars(scope,'M5')
        archived_scenarios=self.store.scenario_snapshots(scope,limit=100)
        self.broker.key='456@DEMO';self.engine.step()
        self.engine.command('adopt_account',{'command_id':'adopt-new-account',
            'confirmation':'ADOPT_MT5_ACCOUNT'})
        for tf in ('M5','M1'):
            view=self.view(tf)
            self.assertFalse(view['available'])
            self.assertEqual(view['account']['key'],'456@DEMO')
            self.assertIn('456@DEMO',view['market_scope'])
            self.assertEqual(view['bars'],[])
            self.assertIsNone(view['live_bar']);self.assertIsNone(view['quote'])
            self.assertEqual(view['analysis_time'],0)
            self.assertNotIn('snapshot_id',view['forecast'])
        state=self.engine.snapshot()
        self.assertEqual(state['bars'],[]);self.assertEqual(state['forecast'].get('scenarios',[]),[])
        self.assertFalse(state['quote_fresh']);self.assertEqual(state['analysis_time'],0)
        self.assertTrue(all(not row['available'] for row in state['timeframes']))
        self.assertEqual(state['market_history_generation'],old['market_history_generation'])
        self.assertEqual(self.store.read_bars(scope,'M5'),archived_bars)
        self.assertEqual(self.store.scenario_snapshots(scope,limit=100),archived_scenarios)
        # A genuinely new read restores the selected forecast under the new scope.
        last=self.broker.frames['M5'][-1]
        self.broker.frames['M5'][-1]=replace(last,close=last.close+.000002)
        self.now[0]+=1;self.engine.step();fresh=self.view('M5')
        self.assertTrue(fresh['available'],fresh['reason'])
        self.assertGreater(fresh['analysis_time'],old['analysis_time'])
        self.assertNotEqual(fresh['forecast']['snapshot_id'],old['forecast']['snapshot_id'])
        self.assertEqual(fresh['bars'][-1]['close'],last.close+.000002)
        self.assertEqual(self.store.read_bars(scope,'M5'),archived_bars)
        self.assertEqual(self.store.scenario_snapshots(scope,limit=100),archived_scenarios)
        self.assertFalse(self.engine.auto);self.assertEqual(self.broker.sent,[])

    def test_observer_scenarios_do_not_contaminate_trade_archive_or_persistence(self):
        self.warm()
        snapshots=self.store.scenario_snapshots(self.engine.market_scope(),limit=100)
        self.assertTrue(snapshots)
        self.assertTrue(all(s['timeframe']=='M5' for s in snapshots))
        self.assertTrue(all(s['forecast'].get('timeframe')=='M5' for s in snapshots))
        saved=self.store.load('engine')['compute']
        self.assertTrue(all(s['pattern']['timeframe']=='M5' for s in saved['scenarios'].values()))
        self.assertNotIn('M10',[x['timeframe'] for x in self.engine.snapshot().get('timeframes',[])])

    def test_context_explains_actual_opposition_then_support_after_observed_events(self):
        self.engine.command('configure',{'command_id':'context-m15-profile','config':{'timeframe':'M15'}})
        self.warm()
        def move(price):
            self.now[0]+=2;self.broker.bid=price;self.broker.ask=price+.00001
            self.engine.step();self.engine._refresh_observers(self.now[0],budget=9)
        for price in (1.1015,1.102):move(price)
        rows={r['timeframe']:r for r in self.engine.snapshot()['timeframes']}
        self.assertEqual(rows['M15']['side'],1)
        self.assertEqual(rows['M1']['side'],-1)
        self.assertEqual(rows['M1']['alignment'],'OPPOSES')
        self.assertEqual(rows['M1']['stage'],'TOUCH_SEEN')
        for price in (1.1025,1.103,1.102):move(price)
        state=self.engine.snapshot();rows={r['timeframe']:r for r in state['timeframes']}
        self.assertEqual(rows['M15']['side'],1)
        self.assertEqual(rows['M1']['side'],1)
        self.assertEqual(rows['M1']['alignment'],'SUPPORTS')
        self.assertEqual(rows['M1']['stage'],'RETEST_SEEN')
        self.assertIn('M1',state['timeframe_context']['supports'])
        self.assertEqual(self.broker.sent,[])

    def test_context_rows_compare_real_frame_sides_without_changing_execution(self):
        self.warm();state=self.engine.snapshot();rows=state.get('timeframes',[])
        self.assertEqual(len(rows),9)
        reference=state['forecast']['side']
        for row in rows:
            view=self.view(row['timeframe'])
            self.assertEqual(row['side'],view['forecast']['side'])
            expected=('REFERENCE' if row['timeframe']=='M5' else 'NEUTRAL' if not row['side'] or not reference
                      else 'SUPPORTS' if row['side']==reference else 'OPPOSES')
            self.assertEqual(row['alignment'],expected)
            self.assertTrue(row['alignment_reason'])
            self.assertTrue(row['next_event'])
        self.assertEqual(state['timeframe_context']['reference_timeframe'],'M5')
        self.assertFalse(state['timeframe_context']['affects_execution'])


class M30NativeTests(unittest.TestCase):
    def test_native_m30_closed_and_live_rows_keep_explicit_clock_conversion(self):
        class Terminal:
            TIMEFRAME_M30=30
            def account_info(self):return SimpleNamespace(login=123,server='DEMO')
            def copy_rates_from_pos(self,symbol,tf,start,count):
                assert tf==30
                rows=[dict(time=NOW+10800+i*1800,open=1.1,high=1.2,low=1.,close=1.11,tick_volume=5)
                      for i in (-2,-1,0)]
                return rows[-count:] if start==0 else rows[:-start][-count:]
        broker=MT5Broker(Terminal(),clock_account='123@DEMO',clock_offset_minutes=180)
        with patch('event_core.mt5_adapter.time.time',return_value=NOW):
            bars=broker.bars('EURUSD','M30')
            live=broker.current_bar('EURUSD','M30')
        self.assertEqual([b.time for b in bars],[NOW-3600,NOW-1800])
        self.assertEqual(live.time,NOW)
        self.assertEqual(bars[0].clock_offset_seconds,10800)
