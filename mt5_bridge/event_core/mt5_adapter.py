from __future__ import annotations
from datetime import datetime, timezone
import time
from .model import Bar, Quote, Blocked, number, TF_SECONDS, bar_close_time

MAGIC=260911109


def required(value,label):
    if value is None: raise Blocked('MT5 не вернул '+label)
    return value


class MT5Broker:
    """Only this adapter touches MetaTrader5. Caller serializes operations."""
    magic=MAGIC
    def __init__(self,mt5,terminal_path=None,*,clock_account=None,clock_offset_minutes=0):
        self.mt5=mt5;self.terminal_path=terminal_path;self.initialized=False
        if type(clock_offset_minutes) is not int or not -840<=clock_offset_minutes<=840:
            raise Blocked('Смещение часов брокера должно быть целым числом минут от -840 до 840')
        if clock_account is not None and (not isinstance(clock_account,str) or not clock_account.strip()):
            raise Blocked('Нужна точная привязка часов к login@server')
        if clock_offset_minutes and not clock_account:
            raise Blocked('Смещение часов требует точной привязки к login@server')
        self.clock_account=clock_account
        self.clock_offset_minutes=clock_offset_minutes
        # Only an explicit account-bound convention may convert broker wall time.
        # Never infer an offset from tick age, arrival time, or price progression.
        self._tick_seen={}

    def clock_identity(self):
        if not self.clock_offset_minutes:return 'UTC_NATIVE_R51'
        return f'UTC_EXPLICIT_R55:{self.clock_account}:{self.clock_offset_minutes}'

    def _verify_clock_account(self):
        if self.clock_account is None:return
        account=required(self.mt5.account_info(),'счёт для проверки часов')
        if f'{account.login}@{account.server}'!=self.clock_account:
            self._tick_seen.clear()
            raise Blocked('Настройка часов принадлежит другому счёту MT5; коррекция запрещена')

    def _time_seconds(self,raw):
        return int(raw)-self.clock_offset_minutes*60

    def connect(self):
        if not self.initialized:
            ok=self.mt5.initialize(path=self.terminal_path) if self.terminal_path else self.mt5.initialize()
            if not ok: raise Blocked('Не удалось подключиться к MT5: '+str(self.mt5.last_error()))
            self.initialized=True
        info=required(self.mt5.terminal_info(),'состояние терминала')
        if not info.connected:
            self.initialized=False;raise Blocked('Терминал MT5 не подключён к серверу')

    def account(self):
        a=required(self.mt5.account_info(),'счёт');t=required(self.mt5.terminal_info(),'терминал')
        if a.trade_mode==self.mt5.ACCOUNT_TRADE_MODE_DEMO:mode='DEMO'
        elif a.trade_mode==getattr(self.mt5,'ACCOUNT_TRADE_MODE_REAL',2):mode='REAL'
        else:mode='CONTEST'
        hedge='HEDGING' if a.margin_mode==self.mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING else 'NETTING'
        return dict(key=f'{a.login}@{a.server}',login=int(a.login),type=mode,margin_mode=hedge,
            currency=str(a.currency),balance=float(a.balance),equity=float(a.equity),margin_free=float(a.margin_free),
            trade_allowed=bool(a.trade_allowed and a.trade_expert and t.trade_allowed and not getattr(t,'tradeapi_disabled',False)))

    def symbol(self,name):
        compact=name.replace('/','').strip()
        candidates=[compact,name]
        info=None
        for value in dict.fromkeys(candidates):
            info=self.mt5.symbol_info(value)
            if info: break
        if not info:
            raise Blocked(f'Инструмент {compact} не найден; укажите точное имя с суффиксом брокера')
        if not info.visible and not self.mt5.symbol_select(info.name,True):
            raise Blocked('Не удалось включить инструмент в обзоре рынка')
        return dict(name=info.name,point=float(info.point),digits=int(info.digits),
                    tick_size=float(info.trade_tick_size or info.point),stops_level=int(info.trade_stops_level),
                    freeze_level=int(info.trade_freeze_level),volume_min=float(info.volume_min),
                    volume_max=float(info.volume_max),volume_step=float(info.volume_step),
                    filling_mode=int(info.filling_mode),trade_exemode=int(info.trade_exemode))

    def symbols(self,limit=1000):
        # Compatibility endpoint, not a replacement for the user's watchlist.
        # Scan the whole broker catalogue BEFORE filtering; never truncate at A... .
        rows=required(self.mt5.symbols_get(),'список инструментов')
        disabled=getattr(self.mt5,'SYMBOL_TRADE_MODE_DISABLED',0)
        preferred=('EURUSD','GBPUSD','USDJPY','USDCHF','AUDUSD','USDCAD','NZDUSD',
            'EURJPY','GBPJPY','EURGBP','EURCHF','AUDJPY','CADJPY','CHFJPY',
            'GBPCHF','EURAUD','GBPAUD','AUDNZD','NZDJPY','XAUUSD')
        names={str(getattr(row,'name','')).strip() for row in rows
               if int(getattr(row,'trade_mode',disabled))!=disabled}
        out=[]
        for base in preferred:
            exact=sorted(n for n in names if n.replace('/','').upper()==base)
            out.extend(exact)
        return out[:max(1,min(int(limit),len(preferred)*2))]

    def quote(self,symbol):
        self._verify_clock_account()
        t=required(self.mt5.symbol_info_tick(symbol),'котировку')
        self._verify_clock_account()
        raw=int(t.time_msc);normalized=raw-self.clock_offset_minutes*60000
        bid=float(t.bid);ask=float(t.ask)
        mono=time.monotonic();wall=time.time();previous=self._tick_seen.get(symbol)
        age=wall-normalized/1000.0
        fresh=-2.0<=age<=10.0
        confirmed=False
        if previous is not None and fresh and previous['fresh']:
            if raw>previous['raw'] and 0<=mono-previous['changed_mono']<=10.0:
                confirmed=True
            elif raw==previous['raw'] and (bid,ask)==previous['prices']:
                confirmed=previous['confirmed'] and 0<=mono-previous['changed_mono']<=10.0
        changed=previous is None or raw!=previous['raw'] or (bid,ask)!=previous['prices']
        self._tick_seen[symbol]=dict(raw=raw,normalized=normalized,prices=(bid,ask),fresh=fresh,confirmed=confirmed,
            changed_mono=mono if changed else previous['changed_mono'],received_at=wall)
        return Quote(normalized,bid,ask,feed_confirmed=confirmed)

    def _bar_time(self,symbol,raw_seconds):
        """Use the explicit clock policy, independent of quote/PC observations."""
        return self._time_seconds(raw_seconds)

    def quote_diagnostics(self,symbol):
        s=self._tick_seen.get(symbol)
        metadata=dict(clock='UTC_EXPLICIT' if self.clock_offset_minutes else 'UTC_NATIVE',
            clock_identity=self.clock_identity(),clock_account=self.clock_account,
            offset_minutes=self.clock_offset_minutes)
        if s is None:return dict(metadata,feed_confirmed=False)
        return dict(metadata,tick_time_msc=s['normalized'],raw_tick_time_msc=s['raw'],received_at=s['received_at'],
                    raw_age_at_receive_sec=s['received_at']-s['raw']/1000.0,
                    age_at_receive_sec=s['received_at']-s['normalized']/1000.0,feed_confirmed=s['confirmed'])

    def bars(self,symbol,tf,count=240):
        self._verify_clock_account()
        timeframe=getattr(self.mt5,'TIMEFRAME_'+tf,None)
        if timeframe is None: raise Blocked('Таймфрейм MT5 не поддерживается')
        # Request the live bar as well and decide closure from timestamps ourselves.
        # Some terminals/brokers can expose a forming bar while history is synchronising;
        # one such row must never make us discard all already closed history.
        start_pos=1 if tf=='MN1' else 0
        request_count=count if tf=='MN1' else count+2
        rows=self.mt5.copy_rates_from_pos(symbol,timeframe,start_pos,request_count)
        self._verify_clock_account()
        if rows is None:
            raise Blocked('MT5 не вернул историю '+tf+': '+str(self.mt5.last_error()))
        values=[Bar(self._bar_time(symbol,x['time']),float(x['open']),float(x['high']),float(x['low']),float(x['close']),float(x['tick_volume']),
                    clock_offset_seconds=self.clock_offset_minutes*60) for x in rows]
        # Keep native opening timestamps; only certainly closed bars enter strategy data.
        values=list({b.time:b for b in values}.values())
        values.sort(key=lambda b:b.time)
        now=time.time()
        values=[b for b in values if bar_close_time(b.time,tf,b.clock_offset_seconds)<=now+1.0]
        if not values:
            raise Blocked('MT5 не вернул ни одной закрытой свечи '+tf+': '+str(self.mt5.last_error()))
        return values[-count:]

    def history_bars(self,symbol,tf,count=1200):
        return self.bars(symbol,tf,max(1,min(int(count),2000)))

    def chart_snapshot(self,symbol,tf,count=1200):
        """MT5 display only. Never use these rows to validate a trading clock.

        Position zero is the forming candle according to MT5. Read it together
        with its predecessors, using only the explicitly configured time policy.
        The Engine keeps this view out of its analysis and SQLite cache.
        """
        self._verify_clock_account()
        timeframe=getattr(self.mt5,'TIMEFRAME_'+tf,None)
        if timeframe is None:raise Blocked('Таймфрейм MT5 не поддерживается')
        count=max(1,min(int(count),2000))
        rows=self.mt5.copy_rates_from_pos(symbol,timeframe,0,count+1)
        self._verify_clock_account()
        if rows is None or len(rows)==0:
            raise Blocked('MT5 не вернул свечи для графика '+tf+': '+str(self.mt5.last_error()))
        values=[Bar(self._bar_time(symbol,x['time']),float(x['open']),float(x['high']),float(x['low']),float(x['close']),float(x['tick_volume']),
                    clock_offset_seconds=self.clock_offset_minutes*60) for x in rows]
        values=sorted({b.time:b for b in values}.values(),key=lambda b:b.time)
        return dict(bars=values[:-1][-count:],live_bar=values[-1],clock_identity=self.clock_identity(),
                    offset_minutes=self.clock_offset_minutes,raw_live_time=max(int(x['time']) for x in rows))

    def current_bar(self,symbol,tf):
        """Return the currently forming MT5 bar without mixing it into closed history."""
        self._verify_clock_account()
        timeframe=getattr(self.mt5,'TIMEFRAME_'+tf,None)
        if timeframe is None:
            raise Blocked('Таймфрейм MT5 не поддерживается')
        rows=self.mt5.copy_rates_from_pos(symbol,timeframe,0,1)
        self._verify_clock_account()
        if rows is None or len(rows)==0:
            raise Blocked('MT5 не вернул текущую свечу '+tf+': '+str(self.mt5.last_error()))
        x=rows[-1]
        return Bar(self._bar_time(symbol,x['time']),float(x['open']),float(x['high']),float(x['low']),float(x['close']),float(x['tick_volume']),
                   clock_offset_seconds=self.clock_offset_minutes*60)

    def positions(self):
        self._verify_clock_account()
        rows=required(self.mt5.positions_get(),'открытые позиции')
        self._verify_clock_account()
        return [dict(ticket=int(p.ticket),identifier=int(p.identifier),magic=int(p.magic),symbol=p.symbol,
                     side=1 if p.type==self.mt5.POSITION_TYPE_BUY else -1,volume=float(p.volume),
                     price_open=float(p.price_open),price_current=float(p.price_current),sl=float(p.sl),tp=float(p.tp),
                     profit=float(p.profit),swap=float(p.swap),time=self._time_seconds(p.time),raw_time=int(p.time),comment=str(p.comment)) for p in rows]

    def orders(self):
        rows=required(self.mt5.orders_get(),'активные ордера')
        return [dict(ticket=int(o.ticket),magic=int(o.magic),symbol=o.symbol,comment=o.comment) for o in rows]

    def history(self,now):
        self._verify_clock_account()
        # History contains already executed deals, not scheduled future trades.
        # Some brokers stamp these in server wall time. A UTC-now cutoff hides
        # their newest executions. Widen retrieval without shifting identities
        # or treating future market ticks as fresh; time policy is separate.
        start=datetime(1970,1,1,tzinfo=timezone.utc);end=datetime.fromtimestamp(now+86400,timezone.utc)
        rows=required(self.mt5.history_deals_get(start,end),'историю сделок')
        self._verify_clock_account()
        return self._history_rows(rows)

    def history_position(self,position_id):
        self._verify_clock_account()
        pid=int(position_id)
        if pid<=0:raise Blocked('Некорректный ID позиции')
        rows=required(self.mt5.history_deals_get(position=pid),'историю позиции #'+str(pid))
        self._verify_clock_account()
        return self._history_rows(rows)

    def _history_rows(self,rows):
        fields=('ticket','entry','type','position_id','time_msc','volume','profit','commission','swap','fee','magic','symbol','comment','price')
        values=[{k:(getattr(d,k,0) if k not in ('symbol','comment') else str(getattr(d,k,''))) for k in fields} for d in rows]
        for value in values:
            value['raw_time_msc']=int(value['time_msc'])
            value['time_msc']=value['raw_time_msc']-self.clock_offset_minutes*60000
        return values

    def calc_profit(self,side,symbol,volume,entry,exit):
        v=self.mt5.order_calc_profit(self.mt5.ORDER_TYPE_BUY if side==1 else self.mt5.ORDER_TYPE_SELL,symbol,volume,entry,exit)
        return required(v,'расчёт прибыли/риска')

    def calc_margin(self,side,symbol,volume,price):
        v=self.mt5.order_calc_margin(self.mt5.ORDER_TYPE_BUY if side==1 else self.mt5.ORDER_TYPE_SELL,symbol,volume,price)
        return required(v,'расчёт маржи')

    def _demo(self):
        a=self.account()
        if a['type']!='DEMO' or a['margin_mode']!='HEDGING' or not a['trade_allowed']:
            raise Blocked('Отправка запрещена: нужен торгуемый DEMO hedging')
        return a

    def _filling(self,info):
        if info['filling_mode'] & 2: return self.mt5.ORDER_FILLING_IOC
        if info['filling_mode'] & 1: return self.mt5.ORDER_FILLING_FOK
        if info['trade_exemode']!=2: return self.mt5.ORDER_FILLING_RETURN
        raise Blocked('Нет разрешённого fill policy для market execution')

    def _send(self,req):
        self._demo()
        check=required(self.mt5.order_check(req),'order_check')
        if check.retcode!=0: raise Blocked(f'MT5 order_check отклонил: {check.retcode} {check.comment}')
        result=self.mt5.order_send(req)
        if result is None: return dict(status='UNKNOWN',reason='MT5 не подтвердил результат order_send')
        rc=int(result.retcode)
        status='FILLED' if rc in (10009,10010) else 'UNKNOWN' if rc in (10008,10012,10031) else 'REJECTED'
        return dict(status=status,retcode=rc,deal=int(result.deal),ticket=int(result.order),
                    volume=float(result.volume),price=float(result.price),reason=str(result.comment))

    def send(self,plan,comment):
        info=self.symbol(plan.symbol)
        return self._send(dict(action=self.mt5.TRADE_ACTION_DEAL,symbol=plan.symbol,volume=plan.volume,
            type=self.mt5.ORDER_TYPE_BUY if plan.side==1 else self.mt5.ORDER_TYPE_SELL,
            price=plan.entry,sl=plan.stop,tp=0.,deviation=10,magic=MAGIC,comment=comment,
            type_time=self.mt5.ORDER_TIME_GTC,type_filling=self._filling(info)))

    def close_position(self,p):
        self._demo()
        if p['magic']!=MAGIC: raise Blocked('Чужая позиция не закрывается')
        q=self.quote(p['symbol']);i=self.symbol(p['symbol'])
        return self._send(dict(action=self.mt5.TRADE_ACTION_DEAL,position=p['ticket'],symbol=p['symbol'],
            volume=p['volume'],type=self.mt5.ORDER_TYPE_SELL if p['side']==1 else self.mt5.ORDER_TYPE_BUY,
            price=q.bid if p['side']==1 else q.ask,deviation=10,magic=MAGIC,comment='EC1 exit',
            type_time=self.mt5.ORDER_TIME_GTC,type_filling=self._filling(i)))

    def cancel(self,o):
        self._demo()
        if o['magic']!=MAGIC: raise Blocked('Чужой ордер не отменяется')
        r=self.mt5.order_send(dict(action=self.mt5.TRADE_ACTION_REMOVE,order=o['ticket'],magic=MAGIC))
        if r is None or r.retcode!=10009: raise Blocked('Отмена ордера не подтверждена')

    def modify(self,p,stop):
        self._demo()
        if p['magic']!=MAGIC: raise Blocked('Чужой SL не изменяется')
        if p['sl']>0 and (stop-p['sl'])*p['side']<=0: return
        r=self.mt5.order_send(dict(action=self.mt5.TRADE_ACTION_SLTP,position=p['ticket'],symbol=p['symbol'],
                                   sl=stop,tp=p.get('tp',0),magic=MAGIC))
        if r is None or r.retcode not in (10009,10025): raise Blocked('Подтягивание SL не подтверждено')
