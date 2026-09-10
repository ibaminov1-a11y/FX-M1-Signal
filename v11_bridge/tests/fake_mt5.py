from types import SimpleNamespace as N
import time

class Clock:
    def __init__(self,now=1789045205.0): self.now=now
    def __call__(self): return self.now
    def advance(self,n): self.now+=n

class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO=0
    ACCOUNT_TRADE_MODE_REAL=2
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING=2
    ORDER_TYPE_BUY=0
    ORDER_TYPE_SELL=1
    DEAL_ENTRY_IN=0
    DEAL_ENTRY_OUT=1
    DEAL_ENTRY_OUT_BY=3
    ORDER_FILLING_FOK=0
    ORDER_FILLING_IOC=1
    ORDER_FILLING_RETURN=2
    ORDER_TIME_GTC=0
    TRADE_ACTION_DEAL=1
    TRADE_ACTION_SLTP=6
    TRADE_ACTION_REMOVE=8
    TRADE_RETCODE_DONE=10009
    TRADE_RETCODE_DONE_PARTIAL=10010
    TIMEFRAME_M1=1
    TIMEFRAME_M5=5
    TIMEFRAME_M15=15
    TIMEFRAME_H1=60
    SYMBOL_TRADE_EXECUTION_MARKET=2
    def __init__(self,clock=None):
        self.clock=clock or time.time
        self.ai=N(trade_mode=0,trade_allowed=True,currency='USD',margin_mode=2,login=123,server='Fixture-Demo',balance=100000.,equity=100000.,margin_free=100000.)
        self.info=N(name='EURUSD',currency_base='EUR',currency_profit='USD',point=.00001,trade_tick_size=.00001,
                    volume_min=.01,volume_step=.01,volume_max=100.,trade_stops_level=0,trade_freeze_level=0,
                    filling_mode=3,trade_exemode=2)
        self.bid,self.ask=1.10000,1.10001
        self.tick_age=0
        self.ps=[];self.os=[];self.deals=[];self.sent=[];self.next_ticket=100
        self.history_failure=False;self.positions_failure=False;self.calc_failure=False
        self.send_mode='ok';self.margin_override=None
    def initialize(self):return True
    def account_info(self):return self.ai
    def terminal_info(self):return N(connected=True,trade_allowed=True,tradeapi_disabled=False)
    def symbol_info(self,s):return self.info if s=='EURUSD' else None
    def symbols_get(self):return (self.info,)
    def symbol_select(self,s,v):return s=='EURUSD'
    def symbol_info_tick(self,s):return N(bid=self.bid,ask=self.ask,time=int(self.clock()-self.tick_age),time_msc=int((self.clock()-self.tick_age)*1000))
    def positions_get(self,ticket=None):
        if self.positions_failure:return None
        for p in self.ps:
            end=self.bid if p.type==0 else self.ask
            p.profit=(end-p.price_open)*(1 if p.type==0 else -1)*p.volume*100000
        return tuple(p for p in self.ps if ticket is None or p.ticket==ticket)
    def orders_get(self):return tuple(self.os)
    def history_deals_get(self,a,b):return None if self.history_failure else tuple(self.deals)
    def order_calc_profit(self,kind,symbol,volume,start,end):
        return None if self.calc_failure else (end-start)*(1 if kind==0 else -1)*volume*100000
    def order_calc_margin(self,kind,symbol,volume,price):return self.margin_override if self.margin_override is not None else volume*100000*price/1000
    def order_check(self,r):return N(retcode=0,comment='checked')
    def deal(self,position,entry,kind,volume,price,profit=0,magic=720072,commission=0,comment=''):
        self.next_ticket+=1
        d=N(ticket=self.next_ticket,position_id=position,time=int(self.clock()),entry=entry,type=kind,
            symbol='EURUSD',volume=volume,price=price,profit=profit,commission=commission,swap=0,fee=0,magic=magic,comment=comment)
        self.deals.append(d);return d
    def order_send(self,r):
        self.sent.append(dict(r))
        if self.send_mode=='reject':return N(retcode=10030,comment='reject')
        if r['action']==8:
            self.os=[o for o in self.os if o.ticket!=r['order']]
        elif r['action']==6:
            for p in self.ps:
                if p.ticket==r['position']:p.sl=r['sl']
        elif r.get('position'):
            p=next((p for p in self.ps if p.ticket==r['position']),None)
            if p:
                v=min(p.volume,r['volume'])
                profit=self.order_calc_profit(p.type,p.symbol,v,p.price_open,r['price'])
                self.deal(p.identifier,1,r['type'],v,r['price'],profit,p.magic,comment=r.get('comment',''))
                p.volume-=v
                if p.volume<1e-9:self.ps.remove(p)
        else:
            self.next_ticket+=1;ticket=self.next_ticket
            v=r['volume']*(.5 if self.send_mode=='partial' else 1)
            self.ps.append(N(ticket=ticket,identifier=ticket,symbol=r['symbol'],type=r['type'],volume=v,
                price_open=r['price'],sl=r['sl'],tp=0.,profit=0.,swap=0.,magic=r['magic'],time=int(self.clock()),time_msc=int(self.clock()*1000)))
            self.deal(ticket,0,r['type'],v,r['price'],magic=r['magic'],comment=r.get('comment',''))
        if self.send_mode=='ambiguous':return None
        return N(retcode=10010 if self.send_mode=='partial' else 10009,comment='done')
    def copy_rates_from_pos(self,s,tf,start,count):
        seconds=tf*60;end=int(self.clock())//seconds*seconds
        return [dict(time=end-(count-i)*seconds,open=1.09900+i*.000002,high=1.09903+i*.000002,
                     low=1.09898+i*.000002,close=1.09902+i*.000002) for i in range(count)]
