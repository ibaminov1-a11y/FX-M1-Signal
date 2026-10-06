"""Durable control receipts independent of the MT5 execution lock.

A receipt is NOT a broker execution acknowledgement. Only the serialized owner
applies controls. A safety receipt inhibits new sends before slow MT5 work returns.
No order placement endpoint is introduced, and REAL remains unavailable.
"""
from __future__ import annotations
import copy, hashlib, json, sqlite3, threading, time
from contextlib import contextmanager
from pathlib import Path
from .model import Blocked

SAFE=frozenset(('pause','disable','emergency','close'))
ALLOWED=SAFE|frozenset(('configure','enable','play','reset'))
FINAL=frozenset(('APPLIED','REJECTED','EXPIRED','CANCELLED'))

class CommandInbox:
    TTL=30.
    LIMIT=64
    def __init__(self,engine,sequence,views):
        self.engine=engine;self.sequence=sequence;self.views=views
        self.clock=engine.clock;self.lock=threading.RLock();self._inhibit=set()
        rows=engine.store.db.execute('PRAGMA database_list').fetchall()
        location=next((r[2] for r in rows if r[1]=='main'),None)
        if not location:raise ValueError('Persistent state required for control receipts')
        self.path=Path(location).with_name(Path(location).name+'.controls.sqlite3')
        with self._db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS inbox (
              id TEXT PRIMARY KEY, fingerprint TEXT, cmd TEXT, client TEXT, seq INTEGER,
              profile TEXT, account TEXT, received REAL, expires REAL, status TEXT,
              payload TEXT, result TEXT);
              CREATE TABLE IF NOT EXISTS order_seen(client TEXT PRIMARY KEY,seq INTEGER);
              CREATE TABLE IF NOT EXISTS inhibits(profile TEXT PRIMARY KEY);
            ''')
            self._inhibit={r[0] for r in db.execute('SELECT profile FROM inhibits')}
            for ident,cmd,status in db.execute("SELECT id,cmd,status FROM inbox WHERE status IN ('QUEUED','APPLYING')").fetchall():
                if cmd in SAFE:db.execute("UPDATE inbox SET status='QUEUED' WHERE id=?",(ident,))
                else:db.execute("UPDATE inbox SET status='CANCELLED',result=? WHERE id=?",
                    (json.dumps({'message':'Bridge перезапущен; подтвердите управление заново'},ensure_ascii=False),ident))
        # The coordinator is the only MT5 owner. All Engines share a fast inhibit.
        engine.control_inbox=self
        for ident,e in getattr(engine,'engines',{'':engine}).items():
            e.entry_inhibited=lambda ident=ident:self.inhibited(ident)
    @contextmanager
    def _db(self):
        db=sqlite3.connect(str(self.path),timeout=1.)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:yield db
        finally:db.close()
    def inhibited(self,profile=''):
        with self.lock:return '*' in self._inhibit or profile in self._inhibit
    def _render(self,row):
        body=json.loads(row['result'] or '{}');status=row['status']
        return dict(body,ok=status not in ('REJECTED','EXPIRED','CANCELLED'),accepted=True,
            applied=status=='APPLIED',command_status=status,command_id=row['id'],profile_id=body.get('profile_id',row['profile']),
            received_at=row['received'],expires_at=row['expires'],
            message=body.get('message','Команда принята; ожидается применение. Это не подтверждение сделки.'))
    def status(self,ident):
        with self.lock,self._db() as db:
            row=db.execute('SELECT * FROM inbox WHERE id=?',(ident,)).fetchone()
            if row is None:raise Blocked('Команда не найдена; её принятие не подтверждено')
            return self._render(row)
    def summary(self):
        with self.lock,self._db() as db:
            counts=dict(db.execute('SELECT status,COUNT(*) FROM inbox GROUP BY status'))
            rows=db.execute('SELECT * FROM inbox ORDER BY received DESC,seq DESC LIMIT 4').fetchall()
            return dict(pending=counts.get('QUEUED',0)+counts.get('APPLYING',0),applied=counts.get('APPLIED',0),
                inhibited_profiles=sorted(self._inhibit),recent=[self._render(r) for r in rows])
    def receive(self,cmd,data):
        if cmd not in ALLOWED:raise Blocked('Команда не разрешена; REAL остаётся выключенным')
        if not isinstance(data,dict):raise Blocked('Ожидался объект команды')
        key=data.get('command_id','');client=data.get('client_id','');seq=data.get('sequence')
        if not isinstance(key,str) or not 8<=len(key)<=128:raise Blocked('Нужен уникальный идентификатор команды')
        if not isinstance(client,str) or not 8<=len(client)<=128 or not isinstance(seq,int) or isinstance(seq,bool) or seq<1:
            raise Blocked('Требуется идентификатор клиента и порядок команд')
        ident='' if cmd=='emergency' else str(data.get('profile_id') or getattr(self.engine,'profile_id',''))
        if cmd!='emergency' and hasattr(self.engine,'engines') and ident not in self.engine.engines:raise Blocked('Профиль команды не найден')
        account=str(data.get('account_key',''))
        if cmd not in SAFE and not account:raise Blocked('Обновите счёт перед управлением')
        # Do not acquire the engine lock here. Capture immutable client intent.
        payload=dict(data,profile_id=ident)
        raw=json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False)
        if len(raw)>16000:raise Blocked('Слишком большая команда')
        fingerprint=hashlib.sha256((cmd+'\n'+raw).encode()).hexdigest();now=self.clock()
        with self.lock,self._db() as db:
            prior=db.execute('SELECT * FROM inbox WHERE id=?',(key,)).fetchone()
            if prior:
                if prior['fingerprint']!=fingerprint:raise Blocked('Идентификатор команды уже связан с другим содержимым')
                return self._render(prior)
            last=db.execute('SELECT seq FROM order_seen WHERE client=?',(client,)).fetchone()
            if last and seq<=last[0] and cmd not in SAFE:raise Blocked('Устаревшая управляющая команда отклонена')
            count=db.execute("SELECT COUNT(*) FROM inbox WHERE status IN ('QUEUED','APPLYING')").fetchone()[0]
            if count>=self.LIMIT and cmd not in SAFE:raise Blocked('Очередь управления заполнена; принятие не подтверждено')
            db.execute('INSERT INTO order_seen VALUES (?,?) ON CONFLICT(client) DO UPDATE SET seq=MAX(seq,excluded.seq)',(client,seq))
            if cmd in SAFE:
                scope='*' if cmd=='emergency' else ident
                db.execute('INSERT OR IGNORE INTO inhibits VALUES (?)',(scope,));self._inhibit.add(scope)
                # A later stop cancels all older pending enables/configures in its scope.
                rows=db.execute("SELECT id,profile,cmd FROM inbox WHERE status='QUEUED'").fetchall()
                for row in rows:
                    if row['cmd'] not in SAFE and (scope=='*' or row['profile']==scope):
                        db.execute("UPDATE inbox SET status='CANCELLED',result=? WHERE id=?",
                            (json.dumps({'message':'Команда отменена последующей остановкой'},ensure_ascii=False),row['id']))
            elif cmd=='configure':
                for row in db.execute("SELECT id FROM inbox WHERE client=? AND profile=? AND cmd='configure' AND status='QUEUED'",(client,ident)).fetchall():
                    db.execute("UPDATE inbox SET status='CANCELLED',result=? WHERE id=?",
                        (json.dumps({'message':'Выбран более новый профиль'},ensure_ascii=False),row['id']))
            db.execute('INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (key,fingerprint,cmd,client,seq,ident,account,now,0 if cmd in SAFE else now+self.TTL,'QUEUED',raw,'{}'))
            return self._render(db.execute('SELECT * FROM inbox WHERE id=?',(key,)).fetchone())
    def drain(self,limit=8):
        # Called by the serialized owner, never by a receipt HTTP handler.
        if not self.engine.lock.acquire(blocking=False):return 0
        applied=0
        try:
            for _ in range(limit):
                with self.lock,self._db() as db:
                    row=db.execute("SELECT * FROM inbox WHERE status='QUEUED' ORDER BY CASE WHEN cmd IN ('pause','disable','close','emergency') THEN 0 ELSE 1 END, received,seq LIMIT 1").fetchone()
                    if row is None:break
                    row=dict(row);key=row['id'];cmd=row['cmd'];data=json.loads(row['payload'])
                    if row['expires'] and self.clock()>row['expires']:
                        db.execute("UPDATE inbox SET status='EXPIRED',result=? WHERE id=?",
                            (json.dumps({'message':'Срок команды истёк; подтвердите текущий выбор заново'},ensure_ascii=False),key));continue
                    db.execute("UPDATE inbox SET status='APPLYING' WHERE id=?",(key,))
                # Release receipt lock and SQLite transaction before any MT5 I/O.
                try:
                    if hasattr(self.engine,'select_request'):self.engine.select_request(None if cmd=='emergency' else row['profile'])
                    if cmd not in SAFE:
                        if self.engine.account.get('key')!=row['account']:raise Blocked('Счёт изменился; отложенная команда отменена')
                        actual=self.engine.broker.account()
                        if actual.get('key')!=row['account']:raise Blocked('Счёт MT5 изменился; подтвердите команду заново')
                    if row['expires'] and self.clock()>row['expires']:
                        raise Blocked('Срок команды истёк во время проверки MT5; подтвердите заново')
                    data['_receipt_expires']=row['expires']
                    data['_receipt_account']=row['account']
                    self.sequence(data,cmd)
                    result=self.engine.command(cmd,data)
                    state='APPLIED' if result.get('ok') else 'REJECTED'
                except Exception as exc:
                    result=dict(ok=False,message=str(exc));state='REJECTED'
                finally:
                    if hasattr(self.engine,'select_request'):self.engine.select_request(None)
                with self.lock,self._db() as db:
                    db.execute('UPDATE inbox SET status=?,result=? WHERE id=?',(state,json.dumps(result,ensure_ascii=False),key))
                    if state=='APPLIED' and cmd in ('enable','play','reset'):
                        # A newer stop received during slow enable/reset still wins.
                        newer=db.execute("SELECT 1 FROM inbox WHERE cmd IN ('pause','disable','close','emergency') AND received>=? AND id!=? AND (profile=? OR cmd='emergency') AND status IN ('QUEUED','APPLYING') LIMIT 1",(row['received'],key,row['profile'])).fetchone()
                        if not newer:
                            scopes=(row['profile'],'*') if cmd=='reset' else (row['profile'],)
                            for scope in scopes:
                                db.execute('DELETE FROM inhibits WHERE profile=?',(scope,));self._inhibit.discard(scope)
                    applied+=state=='APPLIED'
                self.views.publish()
            return applied
        finally:self.engine.lock.release()
