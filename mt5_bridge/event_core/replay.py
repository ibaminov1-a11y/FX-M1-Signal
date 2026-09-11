"""Forward-only replay of the SAME Engine. Research only; never imports MT5 or sends real orders.
CSV: time_msc,bid,ask. Metadata: symbol,contract_size,margin_per_lot,point,digits,
 tick_size,stops_level,volume_min,volume_step,volume_max,currency_profit='USD'.
Margin is a fixed conservative input, not a reconstruction of historic broker tiers.
"""
from __future__ import annotations
import argparse,csv,json,tempfile,uuid,copy
from pathlib import Path
from dataclasses import asdict
from .model import Bar,Quote,Config,Blocked,TF_SECONDS,number
from .engine import Engine,CONTEXT
from .store import Store
from .mt5_adapter import MAGIC

class ReplayBroker:
    magic=MAGIC
    def __init__(self,meta,config,balance,latency_ms=200,slippage_ticks=3):
        if meta.get('currency_profit')!='USD':raise Blocked('Replay EC1 требует currency_profit=USD; историческая конверсия не подменяется текущей')
        self.meta=meta;self.cfg=config;self.now=0.;self.q=None;self.balance=number(balance,'balance',positive=True)
        self._positions=[];self._deals=[];self._pending=[];self.next_id=1000;self.max_open=0;self.sent=0;self.rejected=0
        self.latency=latency_ms;self.slip=slippage_ticks*meta['tick_size'];self.barsets={};self.current={}
        self.contract=number(meta['contract_size'],'contract_size',positive=True)
        for tf in dict.fromkeys((config.timeframe,CONTEXT[config.timeframe])):
            if tf=='MN1':raise Blocked('Replay EC1: календарные месяцы не моделируются как 30 дней')
            self.barsets[tf]=[]
    def connect(self):pass
    def symbol(self,name):return dict(self.meta,name=self.meta['symbol'],freeze_level=self.meta.get('freeze_level',0),filling_mode=2,trade_exemode=2)
    def account(self):
        ps=self.positions();eq=self.balance+sum(p['profit'] for p in ps);margin=sum(self.calc_margin(p['side'],p['symbol'],p['volume'],p['price_open']) for p in ps)
        return dict(key='REPLAY@LOCAL',login=1,type='DEMO',margin_mode='HEDGING',currency='USD',balance=self.balance,equity=eq,margin_free=eq-margin,trade_allowed=True)
    def quote(self,s):return self.q
    def bars(self,s,tf):return self.barsets[tf][-240:]
    def history(self,now):return copy.deepcopy(self._deals)
    def positions(self):
        out=copy.deepcopy(self._positions)
        for p in out:p['profit']=self.calc_profit(p['side'],p['symbol'],p['volume'],p['price_open'],self.q.bid if p['side']==1 else self.q.ask)
        return out
    def orders(self):return [dict(ticket=p['ticket'],magic=MAGIC,symbol=p['plan'].symbol,comment=p['comment']) for p in self._pending]
    def calc_profit(self,side,symbol,vol,entry,exit):return side*(exit-entry)*vol*self.contract
    def calc_margin(self,side,symbol,vol,price):return number(self.meta['margin_per_lot'],'margin_per_lot',positive=True)*vol
    def _deal(self,p,entry,price,profit=0):
        fee=self.cfg.fee_per_lot*p['volume']/2
        self.balance+=profit-fee
        self._deals.append(dict(ticket=len(self._deals)+1,time_msc=self.q.time_msc,position_id=p['identifier'],entry=entry,
            type=(0 if p['side']==1 else 1) if entry==0 else (1 if p['side']==1 else 0),magic=MAGIC,symbol=p['symbol'],
            comment=p['comment'] if entry==0 else 'EC1 exit',volume=p['volume'],price=price,profit=profit,swap=0.,commission=-fee,fee=0.))
    def _fill(self,p,comment,ticket):
        price=(self.q.ask if p.side==1 else self.q.bid)+p.side*self.slip
        if (price-p.stop)*p.side<=0:
            self.rejected+=1;return dict(status='REJECTED',reason='Stop crossed before delayed fill')
        pos=dict(ticket=ticket,identifier=ticket,magic=MAGIC,symbol=p.symbol,side=p.side,volume=p.volume,
            price_open=price,price_current=price,sl=p.stop,tp=0.,profit=0.,swap=0.,time=int(self.now),comment=comment)
        self._positions.append(pos);self.max_open=max(self.max_open,len(self._positions));self._deal(pos,0,price)
        return dict(status='FILLED',ticket=ticket,price=price,volume=p.volume,reason='replay fill')
    def send(self,plan,comment):
        self.sent+=1;self.next_id+=1
        if self.latency:
            self._pending.append(dict(ticket=self.next_id,plan=plan,comment=comment,due=self.q.time_msc+self.latency))
            return dict(status='UNKNOWN',reason='replay latency, positive evidence required')
        return self._fill(plan,comment,self.next_id)
    def close_position(self,p):
        price=(self.q.bid if p['side']==1 else self.q.ask)-p['side']*self.slip
        profit=self.calc_profit(p['side'],p['symbol'],p['volume'],p['price_open'],price)
        self._deal(p,1,price,profit);self._positions=[x for x in self._positions if x['ticket']!=p['ticket']]
        return dict(status='FILLED',ticket=p['ticket'],reason='replay close')
    def cancel(self,o):self._pending=[x for x in self._pending if x['ticket']!=o['ticket']]
    def modify(self,p,stop):
        for row in self._positions:
            if row['ticket']==p['ticket'] and (stop-row['sl'])*row['side']>0:row['sl']=stop
    def advance(self,q):
        if self.q and q.time_msc<self.q.time_msc:raise Blocked('Replay ticks not chronological')
        q.validate(q.time_msc/1000);self.q=q;self.now=q.time_msc/1000
        for tf,rows in self.barsets.items():
            sec=TF_SECONDS[tf];bucket=int(self.now)//sec*sec;b=self.current.get(tf)
            if b is None or b['time']!=bucket:
                if b is not None:rows.append(Bar(**b))
                self.current[tf]=dict(time=bucket,open=q.bid,high=q.bid,low=q.bid,close=q.bid,volume=1)
            else:b['high']=max(b['high'],q.bid);b['low']=min(b['low'],q.bid);b['close']=q.bid;b['volume']+=1
        # Broker-side stops are evaluated before app decisions, including gap slippage.
        for p in list(self._positions):
            mark=q.bid if p['side']==1 else q.ask
            if (mark-p['sl'])*p['side']<=0:self.close_position(p)
        for task in list(self._pending):
            if q.time_msc>=task['due']:
                self._pending.remove(task);self._fill(task['plan'],task['comment'],task['ticket'])

def replay(csv_path,meta,cfg,capital,latency_ms=0):
    cfg.validate()
    if cfg.fee_per_lot is None:raise Blocked('Replay требует явную комиссию')
    b=ReplayBroker(meta,cfg,capital,latency_ms);seen=0;peak=capital;drawdown=0;phases={}
    with tempfile.TemporaryDirectory() as temp:
        store=Store(Path(temp)/'state.db');e=Engine(b,store,lambda:b.now);e.config=cfg;e.strategy.config=cfg
        e.config.approved=True;e.auto=True;e.paused=False
        with open(csv_path,newline='',encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                q=Quote(int(row['time_msc']),float(row['bid']),float(row['ask']))
                if seen and q.time_msc==b.q.time_msc and q.bid==b.q.bid and q.ask==b.q.ask:continue
                b.advance(q);e.heartbeat=b.now;s=e.step();seen+=1
                phase=s['decision']['phase'];phases[phase]=phases.get(phase,0)+1
                eq=b.account()['equity'];peak=max(peak,eq);drawdown=max(drawdown,peak-eq)
        # Mark open P/L separately, do NOT fabricate a profitable end-of-file exit.
        e.history_time=0;e._refresh(b.now);e._reconcile()
        campaigns=[json.loads(x[0]) for x in store.db.execute('SELECT body FROM campaigns')]
        out=dict(ticks=seen,net_realized=b.balance-capital,open_floating=b.account()['equity']-b.balance,
            max_drawdown=drawdown,completed_campaigns=len(campaigns),campaign_net=[x['net'] for x in campaigns],
            orders=b.sent,max_open_positions=b.max_open,terminal_blocks=e.risk.get('blocks'),recovery=e.recovery,
            phase_ticks=phases,config=asdict(cfg),latency_ms=latency_ms,
            note='Forward replay; fixed margin input, no swaps or news simulator. UNKNOWN execution inhibits new entries exactly as live engine.')
        store.close();return out

def main():
    p=argparse.ArgumentParser(description='Read-only tick replay, no MT5 orders')
    p.add_argument('ticks');p.add_argument('metadata');p.add_argument('--config',required=True);p.add_argument('--capital',type=float,default=100)
    p.add_argument('--latency-ms',type=int,default=0);p.add_argument('--output',default='replay-results.json');a=p.parse_args()
    meta=json.loads(Path(a.metadata).read_text());cfg=json.loads(Path(a.config).read_text())
    results={}
    for adds in (False,True):
        c=Config(**{**cfg,'dynamic_adds':adds})
        results['pyramiding' if adds else 'single']=replay(a.ticks,meta,c,a.capital,a.latency_ms)
    Path(a.output).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
