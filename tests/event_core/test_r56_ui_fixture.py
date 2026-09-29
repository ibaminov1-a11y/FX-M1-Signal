"""The Android R56 scene must exercise real observer forecasts and scoped faults."""
import calendar
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import ui_fixture as fixture


FRAMES=('M1','M5','M15','M30','H1','H4','D1','W1','MN1')
HEADERS={'Authorization':'Bearer ci-fixture-token-not-for-real-trading','X-FXM1-Client':'R51'}


class R56UiFixtureTests(unittest.TestCase):
    def setUp(self):
        self.now=calendar.timegm((2026,9,29,12,0,17))
        self.old_clock=fixture.engine.clock
        self.old_broker_clock=fixture.normal_broker.clock
        self.time_patch=patch('ui_fixture.time.time',return_value=self.now)
        self.time_patch.start()
        fixture.engine.clock=lambda:self.now
        fixture.normal_broker.clock=lambda:self.now
        self.client=fixture.app.test_client()
        self.client.post('/test/reset',json={},headers=HEADERS)

    def tearDown(self):
        self.client.post('/test/reset',json={},headers=HEADERS)
        fixture.engine.clock=self.old_clock
        fixture.normal_broker.clock=self.old_broker_clock
        self.time_patch.stop()

    def setup_scene(self,**options):
        response=self.client.post('/test/r56-multiframe',json=options,headers=HEADERS)
        self.assertEqual(response.status_code,200,response.get_json())
        self.assertTrue(response.get_json()['ok'])
        return response.get_json()

    def view(self,tf):
        response=self.client.get('/ec/forecast?tf='+tf,headers=HEADERS)
        self.assertEqual(response.status_code,200,response.get_json())
        return response.get_json()

    def test_scene_exposes_real_distinct_forecasts_for_all_native_frames(self):
        self.setup_scene()
        ids=set();histories=set()
        for tf in FRAMES:
            with self.subTest(tf=tf):
                result=self.view(tf)
                self.assertTrue(result['available'],result.get('reason'))
                self.assertEqual(result['config']['timeframe'],tf)
                self.assertEqual(result['trade_timeframe'],'M5')
                self.assertTrue(result['forecast']['scenarios'])
                first=result['forecast']['scenarios'][0]
                self.assertEqual(first['pattern']['timeframe'],tf)
                self.assertNotIn(first['scenario_id'],ids)
                ids.add(first['scenario_id'])
                histories.add(tuple(b['close'] for b in result['bars']))
                self.assertEqual(result['live_bar']['close'],result['forecast']['live_price'])
        self.assertEqual(len(histories),9)
        monthly=self.view('MN1')
        self.assertEqual(monthly['live_bar']['time'],calendar.timegm((2026,9,1,0,0,0)))
        self.assertEqual(monthly['bars'][-1]['time'],calendar.timegm((2026,8,1,0,0,0)))
        self.assertTrue(all(time.gmtime(b['time']).tm_mday==1 for b in monthly['bars']))
        state=self.client.get('/ec/state',headers=HEADERS).get_json()
        self.assertEqual(self.view('M5')['forecast']['snapshot_id'],state['forecast']['snapshot_id'])
        self.assertEqual(state['config']['timeframe'],'M5')
        self.assertEqual(self.client.get('/test/r53-command-audit',headers=HEADERS).get_json()['commands'],[])
        self.assertEqual(fixture.broker.sent,[])

    def test_bump_refreshes_existing_observers_and_quote_without_commands(self):
        self.setup_scene()
        before=self.view('M1')
        self.now+=2
        self.setup_scene(bump=True)
        for tf in FRAMES:
            after=self.view(tf)
            self.assertTrue(after['available'],after.get('reason'))
            self.assertEqual(after['forecast']['live_price'],before['forecast']['live_price']+.0002)
            self.assertEqual(after['live_bar']['close'],before['forecast']['live_price']+.0002)
        self.assertGreater(self.view('M1')['analysis_time'],before['analysis_time'])
        self.assertEqual(self.client.get('/test/r53-command-audit',headers=HEADERS).get_json()['commands'],[])

    def test_identity_faults_affect_forecast_response_without_poisoning_real_state(self):
        self.setup_scene()
        good=self.view('M30')
        for flag,key in (('wrong_frame','config'),('wrong_scope','market_scope'),
                         ('wrong_clock','market_history_generation'),('wrong_account','account')):
            with self.subTest(flag=flag):
                self.setup_scene(**{flag:True})
                self.assertNotEqual(self.view('M30')[key],good[key])
                state=self.client.get('/ec/state',headers=HEADERS).get_json()
                self.assertEqual(state['config']['timeframe'],'M5')
                self.assertEqual(state['account']['key'],'123@DEMO')
                self.setup_scene()
                self.assertEqual(self.view('M30')[key],good[key])

    def test_unavailable_frame_is_explicit_and_does_not_break_other_frames(self):
        self.setup_scene(unavailable_tf='M30')
        bad=self.view('M30')
        self.assertFalse(bad['available'])
        self.assertTrue(bad['reason'])
        self.assertFalse(bad['entry_allowed'])
        self.assertTrue(self.view('M1')['available'])
        self.assertTrue(self.view('M5')['available'])
        self.setup_scene()
        self.assertTrue(self.view('M30')['available'])

    def test_delay_applies_only_to_requested_forecast_frame_and_reset_clears_controls(self):
        self.setup_scene(delayed_tf='M15',delay_ms=500)
        started=time.monotonic();self.view('M15')
        self.assertGreaterEqual(time.monotonic()-started,.45)
        started=time.monotonic();self.view('H1')
        self.assertLess(time.monotonic()-started,.35)
        self.client.post('/test/reset',json={},headers=HEADERS)
        self.setup_scene()
        started=time.monotonic();self.view('M15')
        self.assertLess(time.monotonic()-started,.35)

    def hold_state_response(self):
        armed=self.client.post('/test/r56-read-hold',json={'hold':True},headers=HEADERS)
        self.assertEqual(armed.status_code,200,armed.get_json())
        self.assertFalse(armed.get_json()['captured'])
        result={}
        def read():
            result['response']=fixture.app.test_client().get('/ec/state',headers=HEADERS)
        worker=threading.Thread(target=read,daemon=True)
        worker.start()
        self.addCleanup(worker.join,9)
        self.addCleanup(lambda:self.client.post('/test/r56-read-release',json={},headers=HEADERS))
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            status=self.client.get('/test/r56-read-hold',headers=HEADERS)
            if status.get_json().get('captured'):break
            time.sleep(.005)
        self.assertTrue(status.get_json()['captured'])
        self.assertTrue(worker.is_alive(),'Captured response must remain withheld until release')
        return worker,result

    def test_held_snapshot_allows_real_reset_and_new_state_then_releases_old_body(self):
        self.setup_scene()
        with fixture.engine.lock:fixture.engine.emergency=True
        worker,result=self.hold_state_response()
        command=self.client.post('/ec/command/reset',headers=HEADERS,json={
            'client_id':'fixture-r56-'+str(uuid.uuid4()),'sequence':1,'command_id':str(uuid.uuid4()),
            'confirmation':'RESET_DEMO_FLAT'})
        self.assertEqual(command.status_code,200,command.get_json())
        self.assertFalse(command.get_json()['emergency'])
        newer=self.client.get('/ec/state',headers=HEADERS)
        self.assertFalse(newer.get_json()['emergency'])
        self.assertTrue(worker.is_alive(),'Only the captured response remains held')
        released=self.client.post('/test/r56-read-release',json={},headers=HEADERS)
        self.assertEqual(released.status_code,200)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(result['response'].get_json()['emergency'],'Held body is the actual pre-reset snapshot')

    def test_fixture_reset_releases_inflight_hold_and_disarms_next_read(self):
        self.setup_scene()
        worker,result=self.hold_state_response()
        reset=self.client.post('/test/reset',json={},headers=HEADERS)
        self.assertEqual(reset.status_code,200)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result['response'].status_code,200)
        status=self.client.get('/test/r56-read-hold',headers=HEADERS).get_json()
        self.assertFalse(status['captured'])
        self.assertFalse(status['armed'])
        self.assertEqual(self.client.get('/ec/state',headers=HEADERS).status_code,200)
