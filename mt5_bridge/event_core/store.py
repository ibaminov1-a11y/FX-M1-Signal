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
          CREATE TABLE IF NOT EXISTS market_bars_quarantine(scope TEXT, tf TEXT, t INTEGER,
            first_seen REAL, body TEXT, quarantined_at REAL, clock_version TEXT);
          CREATE TABLE IF NOT EXISTS market_clock(scope TEXT PRIMARY KEY, version TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS scenario_snapshots(scope TEXT, id TEXT, t REAL, body TEXT,
            PRIMARY KEY(scope,id));
          CREATE INDEX IF NOT EXISTS scenario_time ON scenario_snapshots(scope,t);
          CREATE TABLE IF NOT EXISTS price_forecasts(scope TEXT, id TEXT, t REAL, body TEXT,
            PRIMARY KEY(scope,id));
          CREATE INDEX IF NOT EXISTS price_forecast_time ON price_forecasts(scope,t);
          CREATE TABLE IF NOT EXISTS price_forecast_outcomes(scope TEXT, id TEXT, minutes INTEGER,
            target_time REAL, origin REAL, center REAL, low REAL, high REAL,
            status TEXT NOT NULL, observed_at REAL, actual REAL,
            PRIMARY KEY(scope,id,minutes));
          CREATE INDEX IF NOT EXISTS price_outcome_due ON price_forecast_outcomes(scope,status,target_time);
        ''')
        self.db.commit()

    def save_price_forecast(self, forecast):
        """Insert a frozen estimate once; reject attempts to rewrite its contents."""
        if not forecast.get('available'):return
        body=json.dumps(forecast,sort_keys=True,ensure_ascii=False,allow_nan=False)
        scope,key=forecast['scope'],forecast['snapshot_id']
        with self.db:
            prior=self.db.execute('SELECT body FROM price_forecasts WHERE scope=? AND id=?',(scope,key)).fetchone()
            if prior and prior[0]!=body:raise ValueError('Исходный прогноз нельзя перезаписать')
            self.db.execute('INSERT OR IGNORE INTO price_forecasts VALUES (?,?,?,?)',
                            (scope,key,forecast['issued_at'],body))
            for point in forecast['projection']:
                self.db.execute('INSERT OR IGNORE INTO price_forecast_outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (scope,key,point['minutes'],point['time'],forecast['origin'],point['center'],
                     point['low'],point['high'],'PENDING',None,None))

    def settle_price_forecasts(self,scope,quote,now):
        """First actual fresh quote within ten seconds, else mark the outcome missing.

        Never replace an old outcome with a newer, more favorable observation.
        Missing outcomes stay in statistics rather than disappearing from the denominator.
        """
        quote.validate(now)
        observed=quote.time_msc/1000
        with self.db:
            self.db.execute("UPDATE price_forecast_outcomes SET status='MISSING' WHERE scope=? AND status='PENDING' AND target_time<?",
                            (scope,observed-10))
            self.db.execute("UPDATE price_forecast_outcomes SET status='OBSERVED',observed_at=?,actual=? WHERE scope=? AND status='PENDING' AND target_time<=?",
                            (observed,quote.bid,scope,observed))

    def price_forecasts(self,scope,limit=100):
        return [json.loads(r[0]) for r in self.db.execute(
            'SELECT body FROM price_forecasts WHERE scope=? ORDER BY t DESC LIMIT ?',
            (scope,max(1,min(1000,int(limit)))))]

    def price_forecast_report(self,scope):
        counts=dict(self.db.execute('SELECT status,COUNT(*) FROM price_forecast_outcomes WHERE scope=? GROUP BY status',(scope,)))
        rows=self.db.execute("SELECT minutes,COUNT(*),AVG(ABS(actual-center)),AVG(ABS(actual-origin)),AVG(CASE WHEN actual>=low AND actual<=high THEN 1.0 ELSE 0.0 END),AVG(high-low) FROM price_forecast_outcomes WHERE scope=? AND status='OBSERVED' GROUP BY minutes ORDER BY minutes",(scope,))
        return dict(scope=scope,evaluated=counts.get('OBSERVED',0),missing=counts.get('MISSING',0),
                    pending=counts.get('PENDING',0),calibrated=False,
                    horizons=[dict(minutes=r[0],count=r[1],mae=r[2],baseline_mae=r[3],
                                   empirical_coverage=r[4],mean_band_width=r[5]) for r in rows])

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

    def ensure_market_clock(self,scope,version,now):
        """One atomic cache migration. Money, intents, settings and snapshots stay intact."""
        with self.db:
            row=self.db.execute('SELECT version FROM market_clock WHERE scope=?',(scope,)).fetchone()
            if row and row[0]==version:return dict(changed=False,quarantined=0,version=version)
            count=self.db.execute('SELECT COUNT(*) FROM market_bars WHERE scope=?',(scope,)).fetchone()[0]
            self.db.execute('INSERT INTO market_bars_quarantine SELECT scope,tf,t,first_seen,body,?,? FROM market_bars WHERE scope=?',
                            (float(now),row[0] if row else 'R5_UNVERIFIED',scope))
            self.db.execute('DELETE FROM market_bars WHERE scope=?',(scope,))
            self.db.execute('INSERT OR REPLACE INTO market_clock VALUES (?,?)',(scope,version))
        return dict(changed=True,quarantined=count,version=version)

    def market_clock_ready(self,scope,version='UTC_NATIVE_R51'):
        row=self.db.execute('SELECT version FROM market_clock WHERE scope=?',(scope,)).fetchone()
        return bool(row and row[0]==version)

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
