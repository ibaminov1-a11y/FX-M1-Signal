"""A new MT5 account must never inherit the previous account's financial history."""
from pathlib import Path
import tempfile
import unittest

from fakes import FakeBroker
from event_core.engine import Engine
from event_core.model import Blocked
from event_core.server import create_app
from event_core.store import Store


class AccountHistoryTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.store=Store(Path(directory.name)/'state.sqlite3');self.addCleanup(self.store.close)
        self.now=1800000000
        self.broker=FakeBroker(lambda:self.now)
        self.original_account=self.broker.account
        for entry in (0,1):
            self.broker.deals.append(dict(ticket=10+entry,position_id=1,magic=self.broker.magic,
                symbol='EURUSD',comment='',type=entry,entry=entry,
                time_msc=(self.now-20+entry*10)*1000,volume=.01,profit=7 if entry else 0,
                commission=0,swap=0,fee=0,price=1.1))
        self.engine=Engine(self.broker,self.store,lambda:self.now)
        self.engine._refresh(self.now)
        self.client=create_app(self.engine,'test-token').test_client()
        self.headers={'Authorization':'Bearer test-token','X-FXM1-Client':'R51'}

    def switch_account(self):
        account=self.original_account();account.update(key='456@DEMO',login=456)
        self.broker.account=lambda:account
        with self.assertRaisesRegex(Blocked,'Счёт MT5 изменён'):
            self.engine._refresh(self.now)

    def test_account_switch_invalidates_financial_snapshot_and_ledger(self):
        self.assertEqual(self.client.get('/trade-ledger',headers=self.headers).json['summary']['net'],7)
        self.switch_account()
        snapshot=self.client.get('/ec/state',headers=self.headers).json
        self.assertEqual(snapshot['account']['key'],'456@DEMO')
        self.assertFalse(snapshot['history_ok'])
        self.assertEqual(snapshot['history_time'],0)
        self.assertEqual(snapshot['all']['count'],0)
        self.assertEqual(snapshot['today']['count'],0)
        self.assertEqual(self.client.get('/trade-ledger',headers=self.headers).status_code,409)
        self.assertFalse(snapshot['auto']);self.assertTrue(snapshot['recovery'])

    def test_return_to_bound_account_reload_preserves_campaign_reconciliation(self):
        campaign={'id':'saved-campaign','position_ids':[1],'symbol':'EURUSD'}
        self.engine.campaign=campaign.copy();self.engine.save()
        self.engine.campaign_history_cache={d['ticket']:d.copy() for d in self.broker.deals}
        self.switch_account()
        self.assertEqual(self.engine.deals,[])
        self.assertEqual(self.store.load('engine')['campaign'],campaign)
        self.assertEqual(self.engine.campaign,campaign)
        self.broker.account=self.original_account
        self.broker.deals=[]  # The saved position-specific history is still needed.
        self.engine._refresh(self.now)
        self.assertEqual(len(self.engine.rows),1)
        self.assertEqual(self.engine.rows[0]['net'],7)
        self.assertTrue(self.engine.history_ok)
        self.assertEqual(self.engine.account_key,'123@DEMO')


if __name__=='__main__':unittest.main()
