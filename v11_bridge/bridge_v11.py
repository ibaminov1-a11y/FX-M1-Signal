"""FX-M1-Signal V11 Bridge. Run beside MT5 on Windows: python bridge_v11.py
The default profile is DEMO-100, AUTO off. Never imports or enables the V10 engine.
HTTP is for a trusted private LAN only; do not expose this port to the Internet.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import hmac
import json
import logging
import math
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import threading
import time
import uuid
from flask import Flask, jsonify, request
from campaign_core import (VERSION, PROTOCOL, MAGIC, Candle, Blocked, analyse, atr,
                           structure, checked_bars, fresh_quote, normalize_stop,
                           plan_order, add_allowed, finite)

ZONE = timezone(timedelta(hours=5))
SYMBOLS = ['EUR/USD','GBP/USD','USD/JPY','USD/CHF','AUD/USD','USD/CAD','NZD/USD',
           'EUR/JPY','GBP/JPY','EUR/GBP','EUR/CHF','AUD/JPY','CAD/JPY','CHF/JPY',
           'GBP/CHF','EUR/AUD','GBP/AUD','AUD/NZD','NZD/JPY','XAU/USD']

def day_id(now):
    return datetime.fromtimestamp(now, ZONE).strftime('%Y-%m-%d')

def data_dict(value):
    return dict(value._asdict()) if hasattr(value, '_asdict') else dict(vars(value))

class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL, kind TEXT, detail TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, time REAL)')
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
    def command_seen(self, key, now):
        if not key or len(key) > 80:
            raise Blocked('Некорректный идентификатор команды')
        try:
            with self.db:
                self.db.execute('INSERT INTO commands VALUES (?,?)', (key, now))
                self.db.execute('DELETE FROM commands WHERE time < ?', (now - 86400 * 7,))
            return False
        except sqlite3.IntegrityError:
            return True

class Engine:
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
        # Restart never inherits authority to create new market risk.
        self.s['auto'] = False
        self.s['paused'] = True
        self.s['generation'] += 1
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
        # Mandatory on every cycle and immediately before ANY trade operation.
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
                raise Blocked('История MT5 недоступна; денежные значения не обнулены')
            merged = {int(d.ticket): d for d in self.history_cache}
            merged.update({int(d.ticket): d for d in rows})
            self.history_cache = sorted(merged.values(),key=lambda d:(d.time,int(d.ticket)))
            self.history_time = now
        trading = [d for d in self.history_cache if int(d.type) in (0,1)]
        bot_ids = {int(d.position_id) for d in trading if int(d.magic) == MAGIC}
        bot_ids.update(int(getattr(p,'identifier',p.ticket)) for p in self.own)
        relevant = [d for d in trading if int(d.position_id) in bot_ids]
        def costs(d):
            return float(d.commission)+float(d.swap)+float(getattr(d,'fee',0) or 0)
        self.cash = sum(float(d.profit)+costs(d) for d in relevant)
        self.history_rows = []
        entry_costs, entry_volumes = {}, {}
        for d in relevant:
            if int(d.entry) == self.mt5.DEAL_ENTRY_IN:
                k = int(d.position_id)
                entry_costs[k] = entry_costs.get(k,0.0)+costs(d)
                entry_volumes[k] = entry_volumes.get(k,0.0)+float(d.volume)
        for d in relevant:
            if int(d.entry) in (self.mt5.DEAL_ENTRY_OUT,self.mt5.DEAL_ENTRY_OUT_BY):
                k = int(d.position_id)
                allocation = entry_costs.get(k,0)*float(d.volume)/max(entry_volumes.get(k,0),float(d.volume))
                self.history_rows.append(dict(ticket=int(d.ticket),position_id=k,time=int(d.time),symbol=d.symbol,
                    side='BUY' if int(d.type)==1 else 'SELL',volume=float(d.volume),price=float(d.price),
                    net=float(d.profit)+costs(d)+allocation,comment=getattr(d,'comment','')))
        if self.s['baseline_cash'] is None:
            if self.own:
                self.s['recovery'] = True
            self.s['baseline_cash'] = self.cash
            self.save()
        floating = sum(float(p.profit)+float(p.swap) for p in self.own)
        self.virtual = 100.0 + self.cash - self.s['baseline_cash'] + floating
        today = day_id(now)
        if self.s['day'] != today:
            # Offline rollover with exposure cannot invent the missing midnight equity.
            if self.s['day'] and (self.own or any(day_id(x['time'])==today for x in self.history_rows)):
                self.s['recovery'] = True
            self.s['day'],self.s['day_base'] = today,self.virtual
            self.save()
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
        planned, future, used_margin = 0.0,0.0,0.0
        fees = self.fee()
        for p in self.own:
            if not p.sl or p.sl <= 0:
                raise Blocked('Есть позиция без подтверждённого SL')
            info = self.mt5.symbol_info(p.symbol)
            q,_ = self.quote(p.symbol)
            if info is None:
                raise Blocked('Нет спецификации позиции')
            side = 1 if int(p.type)==0 else -1
            reserve = max(q.ask-q.bid,info.point*2)*2
            floor_pnl = self.profit(p.symbol,side,p.volume,p.price_open,p.sl-side*reserve)+float(p.swap)
            planned += max(0,-floor_pnl)+fees*p.volume
            future += max(0,float(p.profit)+float(p.swap)-floor_pnl)+fees*p.volume/2
            m = self.mt5.order_calc_margin(self.order_type(side),p.symbol,p.volume,q.ask if side==1 else q.bid)
            if m is None:
                raise Blocked('Не удалось рассчитать занятую маржу')
            used_margin += finite(m,'маржа')
        c = self.s['campaign']
        if c:
            planned += max(0.0,c['cash_start'] - self.cash)
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
    def send(self, req):
        self.connect()
        check = self.mt5.order_check(req)
        if check is None or int(check.retcode) != 0:
            raise Blocked('MT5 отклонил проверку ордера: ' + str(getattr(check,'comment','нет ответа')))
        result = self.mt5.order_send(req)
        if result is None:
            raise Blocked('Нет подтверждения order_send; повтор открытия запрещён')
        if result.retcode not in (self.mt5.TRADE_RETCODE_DONE,self.mt5.TRADE_RETCODE_DONE_PARTIAL):
            raise Blocked('MT5: ' + str(result.retcode) + ' ' + str(result.comment))
        return result
    def close_own(self):
        self.connect()  # Never operates on REAL even during Emergency.
        errors = []
        for o in self.orders():
            try:
                result = self.mt5.order_send(dict(action=self.mt5.TRADE_ACTION_REMOVE,order=int(o.ticket)))
                if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
                    raise Blocked('Отмена ордера не подтверждена')
            except Exception as e:
                errors.append(str(e))
        for p in self.positions():
            try:
                q,_ = self.quote(p.symbol)
                side = -1 if int(p.type)==0 else 1
                req = dict(action=self.mt5.TRADE_ACTION_DEAL,position=int(p.ticket),symbol=p.symbol,
                           volume=float(p.volume),type=self.order_type(side),price=q.ask if side==1 else q.bid,
                           deviation=10,magic=MAGIC,comment='FX11 CLOSE',type_time=self.mt5.ORDER_TIME_GTC,
                           type_filling=self.fill_policy(p.symbol))
                self.send(req)
            except Exception as e:
                errors.append(str(e))
        remaining = self.positions()
        remaining_orders = self.orders()
        self.history(force=True)
        if remaining or remaining_orders:
            self.event('CLOSE_PENDING','; '.join(errors) or 'Частичное исполнение; повтор после сверки')
            return False
        c = self.s.get('campaign')
        if c:
            self.s['blocked_setups'] = (self.s['blocked_setups']+[c['setup_id']])[-1000:]
            self.event('CAMPAIGN_CLOSED',f"{c['id']} · cash result {self.cash-c['cash_start']:+.4f} USD")
        self.s['campaign'],self.s['pending'] = None,None
        self.save()
        return True
    def start_close(self, reason):
        c = self.s['campaign']
        if c and not c.get('closing'):
            c['closing'] = True
            self.save()
            self.event('EXIT',reason)
    def trailing(self, c, bars, info, q):
        # Existing campaigns keep being managed even with AUTO off or phone offline.
        closed = checked_bars(bars,300,self.clock(),40)
        direction, proof = structure(closed)
        side = c['side']
        if direction == -side:
            self.start_close('Противоположная подтверждённая структура M5')
            return
        supports = [p for p in proof if p.high==(side<0) and p.confirmed_at > c['opened'] and p.time > c['opened']]
        if not supports:
            return
        candidate = supports[-1].price-side*atr(closed)*0.10
        if side*(candidate-c['guard']) <= info.point*2:
            return
        # A newly confirmed invalidated level is an exit, never a wider stop.
        if side*((q.bid if side==1 else q.ask)-candidate) <= 0:
            self.start_close('Новая структура уже нарушена')
            return
        accepted = []
        for p in self.own:
            if p.symbol != c['symbol'] or int(p.type)!=(0 if side==1 else 1):
                raise Blocked('Состав кампании требует сверки')
            sl = normalize_stop(side,candidate,q.bid,q.ask,info.point,info.trade_tick_size or info.point,
                                max(info.trade_stops_level,info.trade_freeze_level))
            if side*(sl-p.sl) <= info.point:
                accepted.append(float(p.sl)); continue
            r = self.mt5.order_send(dict(action=self.mt5.TRADE_ACTION_SLTP,position=int(p.ticket),symbol=p.symbol,sl=sl,tp=float(p.tp)))
            refreshed = self.mt5.positions_get(ticket=int(p.ticket))
            if r is None or r.retcode!=self.mt5.TRADE_RETCODE_DONE or refreshed is None or (refreshed and abs(refreshed[0].sl-sl)>info.point):
                raise Blocked('Перенос защиты не подтверждён; старый риск сохранён')
            if refreshed:
                accepted.append(sl)
        if accepted:
            c['guard'] = min(accepted) if side==1 else max(accepted)
            self.save()
            self.event('PROTECT',f"SL {c['guard']:.5f}")
        self.positions()
    def open_event(self, setup, info, q, floating):
        s,c = self.s,self.s['campaign']
        now = self.clock()
        if (not s['auto'] or s['paused'] or s['emergency'] or s['recovery'] or s['daily_latch'] or
                self.emergency_request.is_set() or now-self.heartbeat>20):
            raise Blocked('Новые входы запрещены состоянием управления')
        if s['symbol']!='EUR/USD':
            raise Blocked('Торговый профиль RC допущен только для EUR/USD')
        if setup.event_id in s['consumed'] or setup.setup_id in s['blocked_setups']:
            raise Blocked('WAIT: событие уже обработано; ждём новую структуру')
        if s['pending']:
            raise Blocked('Предыдущий запрос требует сверки; повтор запрещён')
        if self.orders():
            raise Blocked('Есть отложенные ордера бота: требуется сверка')
        if now-setup.event_time>90 or setup.event_time>now+1:
            raise Blocked('Событие входа устарело')
        q,_ = self.quote(info.name)
        price = q.ask if setup.side==1 else q.bid
        if setup.side*(price-setup.trigger)<-info.point*2 or abs(price-setup.trigger)>setup.atr*0.35:
            raise Blocked('WAIT: цена ушла от точки подтверждения; не догоняем')
        if q.ask-q.bid > 0.00030:
            raise Blocked('Спред EUR/USD превышает 3 пипса')
        net_open = floating - sum(p.volume*self.fee() for p in self.own)
        if c and (setup.side!=c['side'] or not add_allowed(count=len(self.own),maximum=s['max_positions'],pnl=net_open,
                 side=setup.side,price=price,last_price=c['last_price'],step_distance=max(setup.atr*0.25,info.point*5),
                 new_event=True,closing=c['closing'],paused=s['paused'])):
            raise Blocked('ADD WAIT: нужен новый рост прибыльной кампании в пределах лимита')
        planned,future,margin_used = self.risk()
        cap = max(0,min(100,self.virtual))*0.005
        daily_left = max(0,min(2,self.s['day_base']*0.02)+(self.virtual-self.s['day_base'])-future)
        budget = min(cap-planned,daily_left)
        if budget <= 0:
            raise Blocked('Общий бюджет риска исчерпан')
        p = plan_order(side=setup.side,stop=setup.stop,bid=q.bid,ask=q.ask,point=info.point,
            tick_size=info.trade_tick_size or info.point,stops_level=info.trade_stops_level,
            minimum=info.volume_min,step=info.volume_step,maximum=info.volume_max,cap=budget,
            fee_per_lot=self.fee(),equity=max(0,self.virtual-margin_used),available_margin=self.account.margin_free,
            calc_profit=lambda side,v,a,b:self.profit(info.name,side,v,a,b),
            calc_margin=lambda side,v,a:self.mt5.order_calc_margin(self.order_type(side),info.name,v,a))
        if not c:
            c = dict(id=uuid.uuid4().hex[:12],setup_id=setup.setup_id,side=setup.side,symbol=info.name,
                     opened=now,guard=p.stop,last_price=p.price,cash_start=self.cash,closing=False,entries=[])
            s['campaign'] = c
        s['consumed'] = (s['consumed']+[setup.event_id])[-5000:]
        s['pending'] = dict(event=setup.event_id,campaign=c['id'],time=now)
        self.save()  # Persist intent before any possibly ambiguous network operation.
        if self.emergency_request.is_set():
            self.start_close('Emergency перед отправкой'); return
        try:
            self.connect()
            q2,_ = self.quote(info.name)
            price2 = q2.ask if setup.side==1 else q2.bid
            if abs(price2-p.price)>max(info.point*2,(q.ask-q.bid)):
                raise Blocked('Цена изменилась перед отправкой: вход отменён')
            req = dict(action=self.mt5.TRADE_ACTION_DEAL,symbol=info.name,volume=p.volume,
                type=self.order_type(setup.side),price=price2,sl=p.stop,tp=0.0,deviation=2,
                magic=MAGIC,comment='FX11 '+c['id'],type_time=self.mt5.ORDER_TIME_GTC,type_filling=self.fill_policy(info.name))
            self.send(req)
            positions = self.positions()
            matching = [x for x in positions if x.symbol==info.name and int(x.type)==(0 if setup.side==1 else 1)]
            if not matching:
                raise Blocked('Исполнение получено, но позиция не найдена: требуется сверка')
            newest = max(matching,key=lambda x:(getattr(x,'time_msc',x.time*1000),x.ticket))
            if newest.sl <= 0:
                raise Blocked('Не подтверждён брокерский SL после исполнения')
            c['last_price'] = float(newest.price_open)
            c['entries'].append(dict(ticket=int(newest.ticket),time=int(newest.time),price=float(newest.price_open),volume=float(newest.volume)))
            s['pending'] = None
            self.history(force=True)
            self.save()
            self.event('OPEN',f"{c['id']} {info.name} {'BUY' if setup.side==1 else 'SELL'} {newest.volume:g} @ {newest.price_open:.5f}")
            after,_,_ = self.risk()
            if after > cap + 1e-6:
                self.start_close('Риск после исполнения превысил бюджет')
                self.latch('Превышение риска после исполнения')
        except Exception as e:
            s['recovery'] = True
            self.start_close('Неподтверждённое исполнение/защита')
            self.latch(str(e))
            raise
    def step(self):
        with self.lock:
            now = self.clock()
            reason = 'Ожидание'
            try:
                self.connect()
                self.positions()
                self.history(force=len(self.own)!=self.last_count)
                self.last_count = len(self.own)
                floating = sum(float(p.profit)+float(p.swap) for p in self.own)
                if self.emergency_request.is_set():
                    self.emergency_request.clear()
                    self.latch('Аварийная остановка',True)
                if self.s['emergency']:
                    done = self.close_own()
                    reason = 'EMERGENCY: закрытие подтверждено; AUTO заблокирован' if done else 'EMERGENCY: закрытие НЕ подтверждено'
                    self.publish(reason,floating); return
                if self.virtual-self.s['day_base'] <= -max(0,min(2,self.s['day_base']*0.02)):
                    if not self.s['daily_latch']:
                        self.s['daily_latch'] = day_id(now)
                        self.latch('Дневной порог потерь')
                    self.start_close('Дневной порог потерь')
                c = self.s['campaign']
                if self.own and not c:
                    self.s['recovery'] = True
                    self.save()
                    raise Blocked('Обнаружены прежние/неучтённые позиции бота. Новые входы запрещены')
                if c:
                    if c['closing']:
                        self.close_own(); self.publish('Выход кампании; вход запрещён',floating); return
                    if not self.own and not self.s['pending']:
                        self.close_own(); self.publish('Кампания завершена; ждём новый сценарий',0); return
                    q,_ = self.quote(c['symbol'])
                    live = q.bid if c['side']==1 else q.ask
                    if c['side']*(live-c['guard']) <= 0:
                        self.start_close('Цена нарушила защитную структуру')
                        self.close_own(); self.publish('Выход по структуре',floating); return
                    try:
                        planned,future,_ = self.risk()
                        if planned > max(0,min(100,self.virtual))*0.005+1e-6:
                            self.start_close('Общий риск превышен')
                    except Blocked:
                        # Do not remove broker protection on a temporary read/calculation error.
                        self.s['auto']=False; self.s['paused']=True; self.save()
                        raise
                    info = self.mt5.symbol_info(c['symbol'])
                    if info is None:
                        raise Blocked('Нет спецификации открытой кампании')
                    try:
                        self.trailing(c,self.bars(c['symbol'],'M5',300),info,q)
                    except Blocked as e:
                        reason = 'Сопровождение: ' + str(e)
                        self.publish(reason,floating); return
                    if c['closing']:
                        self.close_own(); self.publish('Выход имеет приоритет',floating); return
                if self.s['auto'] and now-self.heartbeat>20:
                    self.s['paused']=True; self.save()
                info = self.resolve()
                q,stamp = self.quote(info.name)
                m5 = self.bars(info.name,'M5',300)
                display = [asdict(x) for x in m5[-60:]]
                self.snapshot.update(bars=display,bid=float(q.bid),ask=float(q.ask),quote_time=stamp)
                if self.s['recovery']:
                    raise Blocked('Требуется явная сверка: сброс блокировки только без позиций/ордеров')
                if self.s['daily_latch']:
                    raise Blocked('Дневной стоп: новые входы заблокированы')
                try:
                    setup = analyse(info.name,self.bars(info.name,'H1',3600),self.bars(info.name,'M15',900),m5,
                                    self.bars(info.name,'M1',60),now,info.point)
                    self.snapshot['setup'] = setup.payload()
                    reason = setup.reason
                    if self.s['auto'] and not self.s['paused']:
                        self.open_event(setup,info,q,floating)
                    else:
                        reason += ' · AUTO выключен / PAUSE'
                except Blocked as e:
                    reason = str(e)
                self.publish(reason,floating)
            except Exception as e:
                reason = str(e) or type(e).__name__
                if not isinstance(e,Blocked):
                    self.s['auto']=False; self.s['paused']=True
                    self.save()
                if reason!=self.last_error:
                    self.event('BLOCK',reason); self.last_error=reason
                self.publish(reason,None,ok=False)
    def publish(self, reason, floating, ok=True):
        now = self.clock()
        rows = self.history_rows
        positions = [dict(ticket=int(p.ticket),symbol=p.symbol,side='BUY' if int(p.type)==0 else 'SELL',
                     volume=float(p.volume),price=float(p.price_open),sl=float(p.sl),pnl=float(p.profit)+float(p.swap)) for p in self.own]
        self.snapshot.update(ok=ok,protocol=PROTOCOL,version=VERSION,server_time=now,reason=reason,
            symbol=self.s['symbol'],account_mode='DEMO' if self.account else 'UNKNOWN',
            balance=float(self.account.balance) if self.account else None,virtual_equity=self.virtual,
            virtual_base=100.0,floating=floating,auto=self.s['auto'],paused=self.s['paused'],
            emergency=self.s['emergency'],recovery=self.s['recovery'],daily_latch=self.s['daily_latch'],
            generation=self.s['generation'],connected=ok,positions=positions,campaign=self.s['campaign'],
            max_positions=self.s['max_positions'],fee_per_lot=self.s['fee_per_lot'],
            day_result=self.virtual-self.s['day_base'],history_time=self.history_time,
            today=self.summary([x for x in rows if day_id(x['time'])==day_id(now)]),all=self.summary(rows))
    def command(self, cmd, body):
        if cmd=='emergency':
            self.emergency_request.set()  # Visible even while an MT5 send is in flight.
        with self.lock:
            now = self.clock()
            if self.store.command_seen(str(body.get('id','')),now):
                return dict(ok=True,duplicate=True)
            if cmd=='emergency':
                self.s['emergency']=True
                self.latch('EMERGENCY получен',True)
            elif cmd in ('pause','disable'):
                self.s['paused']=True
                if cmd=='disable': self.s['auto']=False
                self.s['generation']+=1; self.save()
            elif cmd=='close':
                self.latch('Закрыть собственную кампанию')
                self.s['emergency']=True; self.save()
            elif cmd=='reset':
                self.connect()
                if self.positions() or self.orders():
                    raise Blocked('Сначала необходимо подтвердить отсутствие позиций/ордеров бота')
                if self.s['daily_latch']==day_id(now):
                    raise Blocked('Дневной стоп нельзя снять в тот же торговый день')
                self.s.update(emergency=False,recovery=False,daily_latch='',pending=None,auto=False,paused=True,campaign=None)
                self.emergency_request.clear(); self.s['generation']+=1; self.save()
            elif cmd=='profile':
                if self.s['auto'] or self.s['campaign'] or self.positions():
                    raise Blocked('Менять профиль можно только без активной кампании и AUTO')
                fee = finite(body.get('fee_per_lot',-1),'комиссия')
                maximum = int(body.get('max_positions',5))
                symbol = str(body.get('symbol','EUR/USD'))
                if fee<0 or fee>100 or maximum<1 or maximum>5 or symbol not in SYMBOLS:
                    raise Blocked('Некорректный профиль')
                self.s.update(fee_per_lot=fee,max_positions=maximum,symbol=symbol)
                self.s['generation']+=1; self.save()
            elif cmd in ('enable','play'):
                if body.get('generation')!=self.s['generation'] or now-self.heartbeat>20:
                    raise Blocked('Состояние изменилось/связь устарела: повторите действие после сверки')
                self.connect(); self.positions(); self.history(force=True)
                if self.s['emergency'] or self.s['recovery'] or self.s['daily_latch'] or self.s['pending']:
                    raise Blocked('Аварийная/дневная блокировка; PLAY не снимает её')
                if cmd=='play' and not self.s['auto']:
                    raise Blocked('Сначала явно включите AUTO в приложении')
                self.fee()
                if self.s['symbol']!='EUR/USD':
                    raise Blocked('RC: торговля только EUR/USD; остальные инструменты — наблюдение')
                if self.own and not self.s['campaign']:
                    raise Blocked('Есть неучтённые позиции')
                self.s.update(auto=True,paused=False); self.s['generation']+=1; self.save()
            else:
                raise Blocked('Неизвестная команда')
            self.event('COMMAND',cmd)
            self.publish('Команда: '+cmd,sum(float(p.profit)+float(p.swap) for p in self.own))
            return dict(ok=True,generation=self.s['generation'])

def create_app(engine, token):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH']=8192
    @app.before_request
    def auth():
        supplied = request.headers.get('Authorization','')
        if not hmac.compare_digest(supplied,'Bearer '+token):
            return jsonify(ok=False,message='Требуется ключ Bridge V11'),401
    @app.get('/v11/state')
    def state():
        with engine.lock:
            engine.heartbeat=engine.clock()
            return jsonify(engine.snapshot)
    @app.get('/v11/history')
    def history():
        with engine.lock:
            limit=min(500,max(1,int(request.args.get('limit',200))))
            offset=max(0,int(request.args.get('offset',0)))
            rows=list(reversed(engine.history_rows))
            return jsonify(ok=True,history_time=engine.history_time,rows=rows[offset:offset+limit],total=len(rows),events=engine.store.events())
    @app.post('/v11/command/<cmd>')
    def command(cmd):
        try:
            data=request.get_json(silent=True) or {}
            return jsonify(engine.command(cmd,data))
        except (Blocked,ValueError,TypeError) as e:
            return jsonify(ok=False,message=str(e)),409
    return app

def main():
    parser=argparse.ArgumentParser(description='FXM1 V11 — DEMO only, trusted LAN')
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--state-dir',default=str(Path(__file__).with_name('state')))
    args=parser.parse_args()
    import MetaTrader5 as mt5
    directory=Path(args.state_dir); directory.mkdir(parents=True,exist_ok=True)
    token_file=directory/'bridge-token.txt'
    if not token_file.exists():
        token_file.write_text(secrets.token_urlsafe(24),encoding='utf-8')
        try: token_file.chmod(0o600)
        except OSError: pass
    token=token_file.read_text(encoding='utf-8').strip()
    if len(token)<20: raise SystemExit('Ключ Bridge повреждён')
    engine=Engine(mt5,directory/'campaign.sqlite3')
    def run():
        while True:
            try: engine.step()
            except Exception: logging.exception('Runtime failure; AUTO remains inhibited')
            time.sleep(0.5)
    threading.Thread(target=run,name='mt5-campaign',daemon=True).start()
    try: ip=socket.gethostbyname(socket.gethostname())
    except OSError: ip='PC_IP'
    print(f'FXM1 {VERSION} | DEMO ONLY | REAL BLOCKED | AUTO OFF',flush=True)
    print(f'Адрес: http://{ip}:{args.port}',flush=True)
    print(f'Ключ подключения: {token}',flush=True)
    print('Только доверенная локальная сеть. Не открывайте порт в Интернет.',flush=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    create_app(engine,token).run(host=args.host,port=args.port,debug=False,threaded=True,use_reloader=False)

if __name__=='__main__':
    main()
