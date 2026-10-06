"""Real Flask/controller semantics with only broker transport substituted."""
import tempfile, threading, unittest
from pathlib import Path
from event_core.portfolio import Portfolio
from event_core.server import create_app
from event_core.store import Store
from fakes import FakeBroker

class QueuedControls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Store(Path(self.tmp.name)/'campaign.sqlite3');self.addCleanup(self.s.close)
        self.now=[1800000000.];self.b=FakeBroker(lambda:self.now[0])
        self.p=Portfolio(self.b,self.s,lambda:self.now[0]);self.p.step()
        self.app=create_app(self.p,'queue-test');self.c=self.app.test_client()
        self.h={'Authorization':'Bearer queue-test','X-FXM1-Client':'R51','X-FXM1-Control':'queued-v1'}
        self.seq=0
    def packet(self,**extra):
        self.seq+=1
        return dict(client_id='queue-test-client',sequence=self.seq,command_id='r74-queue-command-'+str(self.seq),
                    profile_id=self.p.profile_id,account_key=self.p.account['key'],**extra)
    def hold(self):
        ready=threading.Event();done=threading.Event()
        def fn():
            with self.p.lock:ready.set();done.wait(3)
        t=threading.Thread(target=fn);self.holder=t;t.start();self.assertTrue(ready.wait(1))
        self.addCleanup(t.join,2);self.addCleanup(done.set)
        return done
    def test_explicit_refresh_retains_queued_control_capability(self):
        r=self.c.get('/ec/state?refresh=1',headers=self.h)
        self.assertEqual(r.status_code,200,r.json)
        self.assertTrue(r.json.get('capabilities',{}).get('queued_controls'),
                        'Full refresh drops queued-controls support from the phone snapshot')
        self.assertIn('control_queue',r.json)

    def test_busy_pause_uses_queue_after_explicit_refresh(self):
        r=self.c.get('/ec/state?refresh=1',headers=self.h)
        self.assertEqual(r.status_code,200,r.json)
        # Mirror the actual Android capability negotiation; do not force the header.
        headers={k:v for k,v in self.h.items() if k!='X-FXM1-Control'}
        if r.json.get('capabilities',{}).get('queued_controls'):
            headers['X-FXM1-Control']='queued-v1'
        release=self.hold()
        response=self.c.post('/ec/command/pause',json=self.packet(),headers=headers)
        self.assertEqual(response.status_code,202,
                         'After full refresh the client falls back to busy legacy control: '+str(response.json))
        self.assertFalse(response.json['applied'])
        self.assertTrue(self.app.config['command_inbox'].inhibited(self.p.profile_id))
        release.set();self.holder.join(2)

    def test_full_refresh_does_not_apply_a_queued_configuration(self):
        r=self.c.post('/ec/command/configure',json=self.packet(config={'mode':'SCALP'}),headers=self.h)
        self.assertEqual(r.status_code,202,r.json)
        response=self.c.get('/ec/state?refresh=1',headers=self.h)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.p.config.mode,'NORMAL')
        self.assertEqual(self.app.config['command_inbox'].status(r.json['command_id'])['command_status'],'QUEUED')
        self.assertFalse(self.b.sent)

    def test_busy_config_is_received_not_falsely_applied(self):
        release=self.hold()
        r=self.c.post('/ec/command/configure',json=self.packet(config={'mode':'SCALP'}),headers=self.h)
        self.assertEqual(r.status_code,202,r.json)
        self.assertTrue(r.json['accepted']);self.assertFalse(r.json['applied'])
        self.assertEqual(r.json['command_status'],'QUEUED');self.assertEqual(self.p.config.mode,'NORMAL')
        release.set();self.holder.join(2)
        self.app.config['command_inbox'].drain()
        status=self.c.get('/ec/commands/r74-queue-command-1',headers=self.h).json
        self.assertEqual(status['command_status'],'APPLIED',status)
        self.assertEqual(self.p.config.mode,'SCALP')
    def test_receipt_duplicate_never_reexecutes_and_payload_collision_is_rejected(self):
        body=self.packet(config={'mode':'SCALP'})
        a=self.c.post('/ec/command/configure',json=body,headers=self.h)
        self.assertEqual(a.status_code,202,a.json)
        b=self.c.post('/ec/command/configure',json=body,headers=self.h)
        self.assertEqual(a.json['command_id'],b.json['command_id'])
        bad=self.c.post('/ec/command/configure',json=dict(body,config={'mode':'NORMAL'}),headers=self.h)
        self.assertEqual(bad.status_code,409)
        self.app.config['command_inbox'].drain()
        self.assertEqual(self.app.config['command_inbox'].status('r74-queue-command-1')['command_status'],'APPLIED')
        self.assertEqual(self.app.config['command_inbox'].summary()['applied'],1)
    def test_pause_inhibits_before_worker_is_available_and_cancels_old_enable(self):
        self.p.engines[self.p.profile_id].auto=True;self.p.engines[self.p.profile_id].paused=False
        self.c.post('/ec/command/enable',json=self.packet(confirmation='ENABLE_DEMO',allow_wait=True),headers=self.h)
        release=self.hold()
        r=self.c.post('/ec/command/pause',json=self.packet(),headers=self.h)
        self.assertEqual(r.status_code,202,r.json)
        inbox=self.app.config['command_inbox']
        self.assertTrue(inbox.inhibited(self.p.profile_id))
        release.set();self.holder.join(2);inbox.drain()
        self.assertTrue(self.p.paused);self.assertTrue(inbox.inhibited(self.p.profile_id))
        self.assertEqual(inbox.status('r74-queue-command-1')['command_status'],'CANCELLED')
    def test_global_emergency_receipt_keeps_identity_after_profile_switch(self):
        body=self.packet();body.pop('profile_id')
        original=self.p.profile_id
        first=self.c.post('/ec/command/emergency',json=body,headers=self.h)
        self.assertEqual(first.status_code,202,first.json)
        self.p.command('configure',dict(command_id='independent-view-change',config={'symbol':'USD/JPY'},allow_deferred=True))
        self.assertNotEqual(original,self.p.profile_id)
        duplicate=self.c.post('/ec/command/emergency',json=body,headers=self.h)
        self.assertEqual(duplicate.status_code,202,duplicate.json)
        inbox=self.app.config['command_inbox'];inbox.drain()
        self.assertEqual(inbox.status(body['command_id'])['command_status'],'APPLIED')
        self.assertTrue(all(e.emergency for e in self.p.engines.values()))
        self.assertEqual(inbox.summary()['applied'],1)
    def test_expired_config_is_not_applied(self):
        r=self.c.post('/ec/command/configure',json=self.packet(config={'mode':'SCALP'}),headers=self.h)
        self.assertEqual(r.status_code,202,r.json)
        self.now[0]+=31;self.app.config['command_inbox'].drain()
        self.assertEqual(self.p.config.mode,'NORMAL')
        self.assertEqual(self.app.config['command_inbox'].status('r74-queue-command-1')['command_status'],'EXPIRED')
    def test_account_change_rejects_queued_non_safety_command(self):
        r=self.c.post('/ec/command/configure',json=self.packet(config={'mode':'SCALP'}),headers=self.h)
        self.assertEqual(r.status_code,202,r.json)
        self.p.engines[self.p.profile_id].account=dict(self.p.account,key='different')
        self.app.config['command_inbox'].drain()
        self.assertEqual(self.p.config.mode,'NORMAL')
        self.assertEqual(self.app.config['command_inbox'].status('r74-queue-command-1')['command_status'],'REJECTED')
    def test_new_profile_selection_does_not_retarget_queued_packet(self):
        r=self.c.post('/ec/command/pause',json=self.packet(),headers=self.h)
        self.assertEqual(r.status_code,202,r.json)
        self.assertEqual(r.json['profile_id'],self.p.profile_id)
    def test_slow_account_read_does_not_apply_expired_configuration(self):
        self.c.post('/ec/command/configure',json=self.packet(config={'mode':'SCALP'}),headers=self.h)
        original=self.b.account
        def slow():
            self.now[0]+=31
            return original()
        self.b.account=slow
        self.app.config['command_inbox'].drain()
        self.assertEqual(self.p.config.mode,'NORMAL')
        self.assertFalse(self.app.config['command_inbox'].status('r74-queue-command-1')['applied'])
    def test_pending_unsafe_commands_cancel_after_restart_without_erasing_safety(self):
        inbox=self.app.config['command_inbox']
        self.c.post('/ec/command/pause',json=self.packet(),headers=self.h)
        self.c.post('/ec/command/configure',json=self.packet(config={'mode':'SCALP'}),headers=self.h)
        from event_core.command_inbox import CommandInbox
        recovered=CommandInbox(self.p,inbox.sequence,inbox.views)
        self.assertTrue(recovered.inhibited(self.p.profile_id))
        self.assertEqual(recovered.status('r74-queue-command-2')['command_status'],'CANCELLED')
        recovered.drain()
        self.assertEqual(recovered.status('r74-queue-command-1')['command_status'],'APPLIED')
    def test_newer_safety_while_enable_is_applying_cannot_be_cleared(self):
        body=self.packet(confirmation='ENABLE_DEMO',allow_wait=True,accept_pending_profile=True,
                         config={'account_mode':'DEMO'})
        self.c.post('/ec/command/enable',json=body,headers=self.h)
        original=self.b.account;called=[False]
        def slow():
            if not called[0]:
                called[0]=True
                r=self.c.post('/ec/command/pause',json=self.packet(),headers=self.h)
                self.assertEqual(r.status_code,202,r.json)
            return original()
        self.b.account=slow
        inbox=self.app.config['command_inbox'];inbox.drain()
        self.assertTrue(inbox.inhibited(self.p.profile_id));self.assertTrue(self.p.paused)
        self.assertFalse(self.b.sent)
    def test_queue_protocol_does_not_bypass_auth_or_enable_real(self):
        self.assertEqual(self.c.post('/ec/command/pause',json=self.packet(),headers={}).status_code,401)
        r=self.c.post('/ec/command/arm_real',json=self.packet(),headers=self.h)
        self.assertEqual(r.status_code,409)

if __name__=='__main__':unittest.main()
