"""Coherent, read-only status publication independent of a blocked MT5 call."""
import copy
import threading


class RuntimeViews:
    def __init__(self, engine):
        self.engine=engine
        self._lock=threading.Lock()
        self._views={}
        self.publish()

    def remember(self, snapshot):
        ident=snapshot.get('profile_id','')
        value=(copy.deepcopy(snapshot),self.engine.clock())
        with self._lock:self._views[ident]=value

    def publish(self):
        with self.engine.lock:
            snapshots=(self.engine.view_snapshots() if hasattr(self.engine,'view_snapshots')
                       else [self.engine.snapshot()])
            for snapshot in snapshots:self.remember(snapshot)

    def read(self):
        acquired=self.engine.lock.acquire(blocking=False)
        try:
            if acquired:self.remember(self.engine.snapshot())
        finally:
            if acquired:self.engine.lock.release()
        ident=getattr(self.engine,'profile_id','')
        with self._lock:
            item=self._views.get(ident)
            if item is None:return None
            snapshot,captured=copy.deepcopy(item)
        now=self.engine.clock();age=max(0.,now-captured)
        snapshot.update(server_connected=True,runtime_busy=not acquired,
                        snapshot_age=age,snapshot_time=captured,server_time=now)
        snapshot['account_age']=max(0.,snapshot.get('account_age',1e9)+age)
        if 'positions_age' in snapshot:
            snapshot['positions_age']+=age
            snapshot['positions_ok']=bool(snapshot.get('positions_ok') and snapshot['positions_age']<10)
        snapshot['history_ok']=bool(snapshot.get('history_ok') and now-snapshot.get('history_time',0)<15)
        quote=snapshot.get('quote') or {}
        snapshot['quote_fresh']=bool(snapshot.get('quote_fresh') and -2<=now-quote.get('time_msc',0)/1000<=10)
        if age>=10 or snapshot['account_age']>=10 or not snapshot['quote_fresh']:
            snapshot['entry_allowed']=False
            gate=snapshot.setdefault('entry_gate',{})
            gate['allowed']=False
            if 'STATUS_STALE' not in gate.setdefault('blocks',[]):gate['blocks'].append('STATUS_STALE')
            snapshot.setdefault('forecast',{}).update(stale=True,available=False)
            reason='Данные MT5 устарели; ожидается обновление'
            for row in snapshot.get('timeframes',[]):
                row.update(available=False,alignment='UNAVAILABLE',alignment_reason=reason,reason=reason)
            snapshot.setdefault('timeframe_context',{}).update(supports=[],opposes=[],summary=reason,affects_execution=False)
        return snapshot
