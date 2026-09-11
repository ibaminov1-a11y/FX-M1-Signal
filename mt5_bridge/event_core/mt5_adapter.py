from __future__ import annotations
from datetime import datetime, timezone
from .model import Bar, Quote, Blocked, number

MAGIC=260911109


def required(value,label):
    if value is None: raise Blocked('MT5 не вернул '+label)
    return value


class MT5Broker:
    """Only this adapter touches MetaTrader5. Caller serializes operations."""
    magic=MAGIC
    def __init__(self,mt5,terminal_path=None):
        self.mt5=mt5;self.terminal_path=terminal_path;self.initialized=False

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
        mode='DEMO' if a.trade_mode==self.mt5.ACCOUNT_TRADE_MODE_DEMO else 'REAL_OR_CONTEST'
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

    def quote(self,symbol):
        t=required(self.mt5.symbol_info_tick(symbol),'котировку')
        return Quote(int(t.time_msc),float(t.bid),float(t.ask))

    def bars(self,symbol,tf,count=240):
        timeframe=getattr(self.mt5,'TIMEFRAME_'+tf,None)
        if timeframe is None: raise Blocked('Таймфрейм MT5 не поддерживается')
        rows=required(self.mt5.copy_rates_from_pos(symbol,timeframe,1,count),'закрытые свечи '+tf)
        return [Bar(int(x['time']),float(x['open']),float(x['high']),float(x['low']),float(x['close']),float(x['tick_volume'])) for x in rows]

    def positions(self):
        rows=required(self.mt5.positions_get(),'открытые позиции')
        return [dict(ticket=int(p.ticket),identifier=int(p.identifier),magic=int(p.magic),symbol=p.symbol,
                     side=1 if p.type==self.mt5.POSITION_TYPE_BUY else -1,volume=float(p.volume),
                     price_open=float(p.price_open),price_current=float(p.price_current),sl=float(p.sl),tp=float(p.tp),
                     profit=float(p.profit),swap=float(p.swap),time=int(p.time),comment=str(p.comment)) for p in rows]

    def orders(self):
        rows=required(self.mt5.orders_get(),'активные ордера')
        return [dict(ticket=int(o.ticket),magic=int(o.magic),symbol=o.symbol,comment=o.comment) for o in rows]

    def history(self,now):
        start=datetime(1970,1,1,tzinfo=timezone.utc);end=datetime.fromtimestamp(now,timezone.utc)
        rows=required(self.mt5.history_deals_get(start,end),'историю сделок')
        fields=('ticket','entry','type','position_id','time_msc','volume','profit','commission','swap','fee','magic','symbol','comment','price')
        return [{k:(getattr(d,k,0) if k not in ('symbol','comment') else str(getattr(d,k,''))) for k in fields} for d in rows]

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
