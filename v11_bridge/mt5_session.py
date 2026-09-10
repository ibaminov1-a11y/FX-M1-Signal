"""MT5 account/session, durable controls, cash ledger and conservative risk."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
import sqlite3
import threading
import time
from campaign_core import VERSION, PROTOCOL, MAGIC, Candle, Blocked, fresh_quote, finite

ZONE = timezone(timedelta(hours=5))
SYMBOLS = ['EUR/USD','GBP/USD','USD/JPY','USD/CHF','AUD/USD','USD/CAD','NZD/USD',
           'EUR/JPY','GBP/JPY','EUR/GBP','EUR/CHF','AUD/JPY','CAD/JPY','CHF/JPY',
           'GBP/CHF','EUR/AUD','GBP/AUD','AUD/NZD','NZD/JPY','XAU/USD']

def day_id(now):
    return datetime.fromtimestamp(now, ZONE).strftime('%Y-%m-%d')

class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL, kind TEXT, detail TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, time REAL)')
        if 'result' not in [r[1] for r in self.db.execute('PRAGMA table_info(commands)')]:
            self.db.execute('ALTER TABLE commands ADD COLUMN result TEXT')
        self.db.commit()
    def load(self):
        row = self.db.execute('SELECT value FROM state WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None
    def save(self, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (json.dumps(value, allow_nan=False),))
    def log(self, kind, detail, now):
        with self.db:
            self.db.execute('INSERT INTO events(time,kind,detail) VALUES (?,?,?)', (now,kind,str(detail)))
            self.db.execute('DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-3000 FROM events)')
    def events(self):
        rows = self.db.execute('SELECT time,kind,detail FROM events ORDER BY id DESC LIMIT 120').fetchall()
        return [dict(time=x[0],kind=x[1],detail=x[2]) for x in rows]
    def command_result(self, key):
        if not key or len(key)>80:
            raise Blocked('Некорректный идентификатор команды')
        row=self.db.execute('SELECT result FROM commands WHERE id=?',(key,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None
    def remember_command(self,key,result,now):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO commands(id,time,result) VALUES (?,?,?)',(key,now,json.dumps(result)))
            self.db.execute('DELETE FROM commands WHERE time < ?',(now-86400*7,))

class Session:
    def __init__(self, mt5, path, clock=time.time):
        self.mt5, self.clock = mt5, clock
        self.lock = threading.RLock()
        self.emergency_request = threading.Event()
        self.store = Store(path)
        now = clock()
        self.s = self.store.load() or dict(
            created=now, account='', baseline_cash=None, day='', day_base=100.0,
            daily_latch='', emergency=False, recovery=False, auto=False, paused=True,
            campaign=None, pending=None, consumed=[], blocked_setups=[], generation=0,
            max_positions=5, symbol='EUR/USD', fee_per_lot=None)
        self.s['auto'] = False
        self.s['paused'] = True
        self.s['generation'] += 1
        if self.s['pending']:
            self.s['recovery']=True
            if self.s['campaign']: self.s['campaign']['closing']=True
        self.store.save(self.s)
        self.heartbeat = 0.0
        self.last_poll = 0.0
        self.bars_cache = {}
        self.history_cache = []
        self.history_time = 0.0
        self.snapshot = dict(ok=False, protocol=PROTOCOL, version=VERSION, reason='Ожидание MT5', server_time=now)
        self.history_rows = []
        self.account = None
        self.own = []
        self.cash = 0.0
        self.virtual = 100.0
        self.last_count = -1
        self.last_error = ''
        self.money_ok=False
        self.money_error=''
        self.store.log('BOOT', 'V11: AUTO выключен; требуется явное разрешение', now)

    def save(self):
        self.store.save(self.s)

    def event(self, kind, text):
        self.store.log(kind, text, self.clock())

    def connect(self):
        if self.mt5.account_info() is None:
            if not self.mt5.initialize():
                raise Blocked('MT5 не подключён')
        ai = self.mt5.account_info()
        if ai is None:
            raise Blocked('MT5: account_info недоступен')
        if ai.trade_mode != self.mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise Blocked('REAL/неизвестный счёт запрещён. Требуется DEMO')
        if ai.currency != 'USD':
            raise Blocked('Профиль DEMO-100 требует счёт в USD')
        if ai.margin_mode != self.mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:
            raise Blocked('V11 RC: требуется DEMO hedging; netting не допущен')
        for field in ('balance','equity','margin_free'):
            finite(getattr(ai,field), field)
        key = str(ai.login) + '@' + ai.server
        if self.s['account'] and self.s['account'] != key:
            raise Blocked('Счёт MT5 изменён: используйте отдельное состояние Bridge для другого DEMO')
        if not self.s['account']:
            self.s['account'] = key
            self.save()
        self.account = ai
        return ai

    def positions(self):
        value = self.mt5.positions_get()
        if value is None:
            raise Blocked('MT5 не вернул позиции; входы запрещены')
        self.own = [p for p in value if int(p.magic) == MAGIC]
        for p in self.own:
            finite(p.volume,'объём позиции',True)
            for field in ('profit','swap','sl','price_open'): finite(getattr(p,field),field)
        return self.own

    def orders(self):
        value = self.mt5.orders_get()
        if value is None:
            raise Blocked('MT5 не вернул отложенные ордера')
        return [p for p in value if int(p.magic) == MAGIC]

    def resolve(self):
        pair = self.s['symbol'].replace('/','')
        direct = self.mt5.symbol_info(pair)
        candidates = [direct] if direct is not None else list(self.mt5.symbols_get() or [])
        valid = [x for x in candidates if x is not None and
                 getattr(x,'currency_base','') == pair[:3] and getattr(x,'currency_profit','') == pair[3:]]
        if len(valid) != 1:
            raise Blocked('Инструмент MT5 неоднозначен или отсутствует: ' + self.s['symbol'])
        info = valid[0]
        if not self.mt5.symbol_select(info.name, True):
            raise Blocked('Не удалось выбрать инструмент MT5')
        return info

    def quote(self, symbol):
        q = self.mt5.symbol_info_tick(symbol)
        if q is None:
            raise Blocked('Нет котировки ' + symbol)
        stamp = getattr(q,'time_msc',0) / 1000.0 or float(q.time)
        fresh_quote(q.bid, q.ask, stamp, self.clock())
        return q, stamp

    def bars(self, symbol, name, seconds):
        now = self.clock()
        key = symbol + name
        old = self.bars_cache.get(key)
        if old and now - old[0] < 2:
            return old[1]
        raw = self.mt5.copy_rates_from_pos(symbol, getattr(self.mt5,'TIMEFRAME_' + name), 0, 160)
        if raw is None:
            raise Blocked('MT5 не вернул свечи ' + name)
        result = [Candle(int(r['time']),float(r['open']),float(r['high']),float(r['low']),float(r['close'])) for r in raw]
        self.bars_cache[key] = (now,result)
        return result

    def history(self, force=False):
        now = self.clock()
        if force or now - self.history_time >= 5:
            start = datetime(1970,1,1,tzinfo=timezone.utc) if not self.history_time else datetime.fromtimestamp(max(0,self.history_time-86400*3),timezone.utc)
            rows = self.mt5.history_deals_get(start,datetime.fromtimestamp(now+1,timezone.utc))
            if rows is None:
                self.money_ok=False
                self.money_error='История MT5 недоступна'
                raise Blocked('История MT5 недоступна; денежные значения не обнулены')
            merged = {int(d.ticket): d for d in self.history_cache}
            merged.update({int(d.ticket): d for d in rows})
            self.history_cache = sorted(merged.values(),key=lambda d:(d.time,int(d.ticket)))
            self.history_time = now
            self.money_ok=True
            self.money_error=''
        trading = [d for d in self.history_cache if int(d.type) in (0,1)]
        bot_ids = {int(d.position_id) for d in trading if int(d.magic) == MAGIC}
        bot_ids.update(int(getattr(p,'identifier',p.ticket)) for p in self.own)
        relevant = [d for d in trading if int(d.position_id) in bot_ids]
        def costs(d):
            return float(d.commission)+float(d.swap)+float(getattr(d,'fee',0) or 0)
        self.cash = sum(float(d.profit)+costs(d) for d in relevant)
        self.history_rows = []
        entry_costs, entry_volumes, origins = {}, {}, {}
        for d in relevant:
            if int(d.entry) == self.mt5.DEAL_ENTRY_IN:
                k = int(d.position_id)
                origins.setdefault(k,dict(time=int(d.time),price=float(d.price),comment=getattr(d,'comment','')))
                entry_costs[k] = entry_costs.get(k,0.0)+costs(d)
                entry_volumes[k] = entry_volumes.get(k,0.0)+float(d.volume)
        for d in relevant:
            if int(d.entry) in (self.mt5.DEAL_ENTRY_OUT,self.mt5.DEAL_ENTRY_OUT_BY):
                k = int(d.position_id)
                allocation = entry_costs.get(k,0)*float(d.volume)/max(entry_volumes.get(k,0),float(d.volume))
                self.history_rows.append(dict(ticket=int(d.ticket),position_id=k,time=int(d.time),symbol=d.symbol,
                    side='BUY' if int(d.type)==1 else 'SELL',volume=float(d.volume),price=float(d.price),
                    net=float(d.profit)+costs(d)+allocation,comment=getattr(d,'comment',''),
                    entry_time=origins.get(k,{}).get('time',0),entry_price=origins.get(k,{}).get('price',0),
                    campaign=origins.get(k,{}).get('comment','legacy')))
        if self.s['baseline_cash'] is None:
            if self.own:
                self.s['recovery'] = True
            self.s['baseline_cash'] = self.cash
            self.save()
        floating = sum(float(p.profit)+float(p.swap) for p in self.own)
        previous_virtual=self.virtual
        self.virtual = 100.0 + self.cash - self.s['baseline_cash'] + floating
        today = day_id(now)
        if self.s['day'] != today:
            if self.s['day']:
                if 0 < now-self.last_poll < 3:
                    self.s['day_base']=max(previous_virtual,self.virtual)
                elif self.own or any(day_id(x['time'])==today for x in self.history_rows):
                    self.s['recovery']=True
                    self.s['daily_latch']=today
                    self.s['auto']=False
                    self.s['paused']=True
                    self.s['day_base']=self.virtual
                else:
                    self.s['day_base']=self.virtual
            else:
                self.s['day_base']=self.virtual
            self.s['day']=today
            self.save()
        self.last_poll=now
        return floating

    def summary(self, rows):
        return dict(profit=round(sum(max(x['net'],0) for x in rows),4),
                    loss=round(sum(min(x['net'],0) for x in rows),4),
                    net=round(sum(x['net'] for x in rows),4),count=len(rows))

    def order_type(self, side):
        return self.mt5.ORDER_TYPE_BUY if side==1 else self.mt5.ORDER_TYPE_SELL

    def profit(self, symbol, side, volume, start, end):
        value = self.mt5.order_calc_profit(self.order_type(side),symbol,volume,start,end)
        if value is None:
            raise Blocked('Не удалось рассчитать риск MT5')
        return finite(value,'order_calc_profit')

    def fee(self):
        value = self.s.get('fee_per_lot')
        if value is None:
            raise Blocked('Подтвердите комиссию DEMO-счёта в настройках профиля')
        return finite(value,'комиссия')

    def risk(self):
        planned,future,used_margin=0.0,0.0,0.0
        fees=self.fee()
        for p in self.own:
            if p.sl<=0: raise Blocked('Есть позиция без подтверждённого SL')
            info=self.mt5.symbol_info(p.symbol)
            q,_=self.quote(p.symbol)
            if info is None: raise Blocked('Нет спецификации позиции')
            side=1 if int(p.type)==0 else -1
            reserve=max(q.ask-q.bid,info.point*2)*2
            floor_pnl=self.profit(p.symbol,side,p.volume,p.price_open,p.sl-side*reserve)+float(p.swap)
            entry_deals=[d for d in self.history_cache if int(d.position_id)==int(getattr(p,'identifier',p.ticket)) and int(d.entry)==self.mt5.DEAL_ENTRY_IN]
            entry_volume=sum(float(d.volume) for d in entry_deals)
            incurred=sum(max(0,-float(d.commission)-float(getattr(d,'fee',0) or 0)) for d in entry_deals)
            allocated=incurred*float(p.volume)/entry_volume if entry_volume>0 else 0.0
            planned+=max(0,-floor_pnl)+max(allocated,fees*p.volume/2)+fees*p.volume/2
            future+=max(0,float(p.profit)+float(p.swap)-floor_pnl)+fees*p.volume/2
            m=self.mt5.order_calc_margin(self.order_type(side),p.symbol,p.volume,q.ask if side==1 else q.bid)
            if m is None: raise Blocked('Не удалось рассчитать занятую маржу')
            used_margin+=finite(m,'маржа')
        c=self.s['campaign']
        if c:
            tickets={x['ticket'] for x in c['entries']}
            planned+=sum(max(0,-x['net']) for x in self.history_rows if x['position_id'] in tickets)
        return planned,future,used_margin

    def latch(self, reason, emergency=False):
        self.s['auto'] = False
        self.s['paused'] = True
        self.s['generation'] += 1
        if emergency:
            self.s['emergency'] = True
        self.save()
        self.event('STOP',reason)

    def fill_policy(self, symbol):
        i = self.mt5.symbol_info(symbol)
        if i is None:
            raise Blocked('Нет спецификации исполнения')
        flags = int(i.filling_mode)
        if flags & 1:
            return self.mt5.ORDER_FILLING_FOK
        if flags & 2:
            return self.mt5.ORDER_FILLING_IOC
        if int(i.trade_exemode) != getattr(self.mt5,'SYMBOL_TRADE_EXECUTION_MARKET',2):
            return self.mt5.ORDER_FILLING_RETURN
        raise Blocked('Нет поддерживаемого режима исполнения')

    def publish(self, reason, floating, ok=True):
        now = self.clock()
        rows = self.history_rows
        positions = [dict(ticket=int(p.ticket),symbol=p.symbol,side='BUY' if int(p.type)==0 else 'SELL',
                     volume=float(p.volume),price=float(p.price_open),sl=float(p.sl),pnl=float(p.profit)+float(p.swap)) for p in self.own]
        self.snapshot.update(money_ok=self.money_ok,money_error=self.money_error,ok=ok,protocol=PROTOCOL,version=VERSION,server_time=now,reason=reason,
            symbol=self.s['symbol'],account_mode='DEMO' if self.account else 'UNKNOWN',
            balance=float(self.account.balance) if self.account else None,virtual_equity=self.virtual,
            virtual_base=100.0,floating=floating,auto=self.s['auto'],paused=self.s['paused'],
            emergency=self.s['emergency'],recovery=self.s['recovery'],daily_latch=self.s['daily_latch'],
            generation=self.s['generation'],connected=ok,positions=positions,campaign=self.s['campaign'],
            max_positions=self.s['max_positions'],fee_per_lot=self.s['fee_per_lot'],
            day_result=self.virtual-self.s['day_base'],history_time=self.history_time,
            today=self.summary([x for x in rows if day_id(x['time'])==day_id(now)]),all=self.summary(rows))
