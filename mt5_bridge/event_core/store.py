from __future__ import annotations
import json, sqlite3, time
from dataclasses import asdict
from pathlib import Path
from .model import Blocked


class Store:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(path),check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY,t REAL,kind TEXT,body TEXT);
          CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,status TEXT,body TEXT);
          CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY,body TEXT);
          CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY,body TEXT);
          CREATE TABLE IF NOT EXISTS market_bars(scope TEXT, tf TEXT, t INTEGER, first_seen REAL, body TEXT,
            PRIMARY KEY(scope,tf,t));
          CREATE TABLE IF NOT EXISTS scenario_snapshots(scope TEXT, id TEXT, t REAL, body TEXT,
            PRIMARY KEY(scope,id));
          CREATE INDEX IF NOT EXISTS scenario_time ON scenario_snapshots(scope,t);
        ''')
        self.db.commit()

    def load(self,key,default=None):
        row=self.db.execute('SELECT value FROM state WHERE k=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save(self,key,value):
        text=json.dumps(value,ensure_ascii=False,allow_nan=False)
        with self.db:
            self.db.execute('INSERT INTO state VALUES (?,?) ON CONFLICT(k) DO UPDATE SET value=excluded.value',(key,text))

    def event(self,kind,body,now=None):
        with self.db:
            self.db.execute('INSERT INTO journal(t,kind,body) VALUES (?,?,?)',
                (time.time() if now is None else now,kind,json.dumps(body,ensure_ascii=False,allow_nan=False)))

    def events(self,limit=100):
        return [dict(time=r[0],kind=r[1],body=json.loads(r[2])) for r in
                self.db.execute('SELECT t,kind,body FROM journal ORDER BY id DESC LIMIT ?',(min(limit,1000),))]

    def intent(self,event_id,status,body):
        with self.db:
            self.db.execute('INSERT INTO intents VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,body=excluded.body',
                            (event_id,status,json.dumps(body,allow_nan=False)))

    def has_intent(self,event_id):
        return self.db.execute('SELECT 1 FROM intents WHERE id=?',(event_id,)).fetchone() is not None

    def pending(self):
        return [dict(id=r[0],status=r[1],body=json.loads(r[2])) for r in self.db.execute(
            "SELECT id,status,body FROM intents WHERE status IN ('SENDING','UNKNOWN')")]

    def command_result(self,key):
        row=self.db.execute('SELECT body FROM commands WHERE id=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def command_done(self,key,body):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO commands VALUES (?,?)',(key,json.dumps(body,ensure_ascii=False,allow_nan=False)))

    def campaign(self,key,body):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO campaigns VALUES (?,?)',(key,json.dumps(body,ensure_ascii=False,allow_nan=False)))

    def save_bars(self,scope,tf,bars,now):
        rows=[(scope,tf,int(b.time),float(now),json.dumps(asdict(b),allow_nan=False)) for b in bars]
        with self.db:
            self.db.executemany("INSERT INTO market_bars VALUES (?,?,?,?,?) ON CONFLICT(scope,tf,t) DO UPDATE SET body=excluded.body",rows)

    def read_bars(self,scope,tf,before=None,limit=1000):
        limit=max(1,min(int(limit),2000))
        query='SELECT body FROM market_bars WHERE scope=? AND tf=?';args=[scope,tf]
        if before is not None:query+=' AND t<?';args.append(int(before))
        query+=' ORDER BY t DESC LIMIT ?';args.append(limit)
        return list(reversed([json.loads(row[0]) for row in self.db.execute(query,args)]))

    def save_scenario_snapshot(self,scope,body,now):
        key=str(body['snapshot_id'])
        frozen=dict(body,recorded_at=float(now))
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO scenario_snapshots VALUES (?,?,?,?)',
                (scope,key,float(now),json.dumps(frozen,ensure_ascii=False,allow_nan=False)))

    def scenario_snapshots(self,scope,before=None,limit=100,snapshot_id=None):
        query='SELECT body FROM scenario_snapshots WHERE scope=?';args=[scope]
        if snapshot_id is not None:query+=' AND id=?';args.append(str(snapshot_id))
        if before is not None:query+=' AND t<?';args.append(float(before))
        query+=' ORDER BY t DESC,id DESC LIMIT ?';args.append(max(1,min(int(limit),500)))
        return [json.loads(row[0]) for row in self.db.execute(query,args)]

    def close(self): self.db.close()


class ProcessLock:
    """OS lock released on crash. Lock file is deliberately not deleted on exit."""
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.file=open(path,'a+b');self.file.seek(0);self.file.write(b'0');self.file.flush();self.file.seek(0)
        try:
            import os
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as e:
            self.file.close()
            raise Blocked('Уже запущен EventCore для этой папки. Второй экземпляр запрещён.') from e

    def close(self): self.file.close()
