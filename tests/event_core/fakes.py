import sys,time,math,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'mt5_bridge'))
from event_core.model import Bar,Quote
from event_core.mt5_adapter import MAGIC


def wave(end=1800000000,count=96,tf=300,trend=0.00003):
    end=end//tf*tf
    bars=[]
    for i in range(count):
        c=1.1+i*trend+math.sin(i*math.pi/4)*.00035
        o=c-.00005
        bars.append(Bar(end-(count-i)*tf,o,max(o,c)+.00004,min(o,c)-.00004,c,10))
    return bars


class FakeBroker:
    magic=MAGIC
    def __init__(self,clock):
        self.clock=clock;self._positions=[];self._orders=[];self.deals=[];self.sent=[];self.closed=[]
        self.balance=100000.;self.bid=1.103;self.ask=self.bid+.00001;self.demo=True
        self.margin_mode='HEDGING';self.trade_allowed=True;self.history_failure=False
        self.quote_age=0;self.result='FILLED';self.visible=True;self.next_id=100
        self.bar_data=wave(int(clock()));self.ctx_data=wave(int(clock()),tf=900)
        self.info=dict(name='EURUSD',point=.00001,digits=5,tick_size=.00001,stops_level=1,
                       freeze_level=0,volume_min=.01,volume_step=.01,volume_max=100,
                       filling_mode=2,trade_exemode=2)

    def connect(self): pass
    def account(self):
        pnl=sum(p['side']*( (self.bid if p['side']==1 else self.ask)-p['price_open'])*p['volume']*100000 for p in self._positions)
        return dict(key='123@DEMO',login=123,type='DEMO' if self.demo else 'REAL',
                    currency='USD',margin_mode=self.margin_mode,balance=self.balance,equity=self.balance+pnl,
                    margin_free=self.balance+pnl,trade_allowed=self.trade_allowed)
    def symbol(self,symbol): return dict(self.info,name=symbol.replace('/',''))
    def quote(self,symbol):return Quote(int((self.clock()-self.quote_age)*1000),self.bid,self.ask)
    def bars(self,symbol,tf):return self.bar_data if tf=='M5' else self.ctx_data
    def positions(self):
        rows=copy.deepcopy(self._positions)
        for p in rows:p['profit']=self.calc_profit(p['side'],p['symbol'],p['volume'],p['price_open'],self.bid if p['side']==1 else self.ask)
        return rows
    def orders(self):return copy.deepcopy(self._orders)
    def history(self,now):
        if self.history_failure:raise ValueError('fixture history unavailable')
        return copy.deepcopy(self.deals)
    def calc_profit(self,side,symbol,volume,entry,exit):return side*(exit-entry)*volume*100000
    def calc_margin(self,side,symbol,volume,price):return volume*10
    def send(self,p,comment):
        self.sent.append(p)
        if self.result=='REJECTED':return dict(status='REJECTED',reason='test reject')
        self.next_id+=1;t=self.next_id
        if self.visible:
            self._positions.append(dict(ticket=t,identifier=t,magic=MAGIC,symbol=p.symbol,side=p.side,
                volume=p.volume,price_open=p.entry,price_current=p.entry,sl=p.stop,tp=0.,profit=0.,swap=0.,time=int(self.clock()),comment=comment))
            self.deals.append(dict(ticket=t*10,position_id=t,magic=MAGIC,symbol=p.symbol,comment=comment,
                type=0 if p.side==1 else 1,entry=0,time_msc=int(self.clock()*1000),volume=p.volume,
                profit=0.,commission=0.,swap=0.,fee=0.))
        return dict(status=self.result,retcode=10009,deal=t*10,ticket=t,price=p.entry,volume=p.volume,reason='test')
    def close_position(self,p):
        net=self.calc_profit(p['side'],p['symbol'],p['volume'],p['price_open'],self.bid if p['side']==1 else self.ask)
        self.balance+=net;self.closed.append(p['ticket'])
        self._positions=[x for x in self._positions if x['ticket']!=p['ticket']]
        self.deals.append(dict(ticket=p['ticket']*10+1,position_id=p['identifier'],magic=p['magic'],symbol=p['symbol'],comment='EC1 exit',
            type=1 if p['side']==1 else 0,entry=1,time_msc=int(self.clock()*1000),volume=p['volume'],profit=net,commission=0.,swap=0.,fee=0.))
        return dict(status='FILLED',retcode=10009,reason='test close')
    def cancel(self,o):self._orders=[x for x in self._orders if x['ticket']!=o['ticket']]
    def modify(self,p,stop):
        for row in self._positions:
            if row['ticket']==p['ticket']:row['sl']=stop
