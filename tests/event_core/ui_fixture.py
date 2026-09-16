"""CI fixture only: actual Engine/Flask with a fake broker. Never imports MetaTrader5."""
import sys,tempfile,time,uuid
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'mt5_bridge'),str(Path(__file__).resolve().parent)]
from event_core.server import create_app
from event_core.engine import Engine
from event_core.store import Store
from event_core.model import Bar,Config,Decision,atr,pivots
from event_core.strategy import Strategy
from fakes import FakeBroker,wave
from flask import jsonify,request

folder=tempfile.TemporaryDirectory();broker=FakeBroker(time.time);broker.balance=99868.35
store=Store(Path(folder.name)/'fixture.db');engine=Engine(broker,store)
app=create_app(engine,'ci-fixture-token-not-for-real-trading')
freeze_until=0.0

def clear_market():
    engine.last_bars_at=0;engine.last_market_attempt=-1.
    engine.bars=[];engine.context=[];engine.m1=[];engine.m15=[];engine.h1=[];engine.live_bar=None
    engine.quote=None;engine.info={};engine.market_time=0.;engine.market_errors=[];engine.bar_errors=[]
    engine.quote_ready=False;engine.analysis_time=0.;engine.decision=Decision()

def reset():
    global freeze_until
    with engine.lock:
        freeze_until=0.0
        anchor=int(time.time())
        store.db.executescript('DELETE FROM commands; DELETE FROM intents; DELETE FROM campaigns; DELETE FROM state; DELETE FROM journal;');store.db.commit()
        broker._positions=[];broker._orders=[];broker.deals=[];broker.sent=[];broker.closed=[];broker.balance=99868.35
        broker.bid=1.103;broker.ask=broker.bid+.00001;broker.quote_age=0;broker.result='FILLED';broker.visible=True
        broker.demo=True;broker.margin_mode='HEDGING';broker.trade_allowed=True;broker.history_failure=False;broker.live_bar_data=None
        engine.config=Config(fee_per_lot=0);engine.campaign=None;engine.emergency=False;engine.recovery=False
        engine.daily_latch='';engine.auto=False;engine.paused=True;engine.exit_pending=False;engine.ack=[0,0]
        engine.account_key='';engine.history_time=0;engine.history_ok=False;engine.history_error='История ещё не получена';engine.strategy=Strategy(engine.config)
        clear_market();engine.rate_times=[];engine.last_exit=0;engine.next_close=0;engine.last_audit_key=None
        broker.m1_data=wave(anchor,tf=60,trend=.000006)
        broker.bar_data=wave(anchor,tf=300,trend=.00003)
        broker.ctx_data=wave(anchor,tf=900,trend=.00004)
        broker.h1_data=wave(anchor,tf=3600,trend=.00008)
        engine.save();engine.step()

def prime_impulse(side):
    global freeze_until
    with engine.lock:
        side=1 if side>=0 else -1
        anchor=int(time.time())
        bars=wave(anchor,count=96,tf=300,trend=.00003*side)
        a=atr(bars);pts=pivots(bars)
        highs=[p for p in pts if p['kind']=='H'];lows=[p for p in pts if p['kind']=='L']
        if not highs or not lows:raise AssertionError('fixture must contain confirmed pivots')
        level=highs[-1]['price'] if side==1 else lows[-1]['price']
        if side==1:
            open_=level-.10*a;close=open_+.75*a;low=open_-.15*a
            high=max(low+1.05*a,close+.01*a)
        else:
            open_=level+.10*a;close=open_-.75*a;high=open_+.15*a
            low=min(high-1.05*a,close-.01*a)
        live=Bar(anchor//300*300,open_,high,low,close,3)
        m1=wave(anchor,count=96,tf=60,trend=.000006*side);old=m1[-1]
        if side==1:
            m1_close=level+.20*a;m1_open=level+.10*a
        else:
            m1_close=level-.20*a;m1_open=level-.10*a
        m1[-1]=Bar(old.time,m1_open,max(m1_open,m1_close)+.03*a,min(m1_open,m1_close)-.03*a,m1_close,10)
        broker.m1_data=m1;broker.bar_data=bars
        broker.ctx_data=wave(anchor,count=64,tf=900,trend=.00004*side)
        broker.h1_data=wave(anchor,count=64,tf=3600,trend=.00008*side)
        broker.live_bar_data=live;broker.bid=close;broker.ask=close+.00001;broker.quote_age=0
        engine.strategy=Strategy(engine.config);clear_market();engine.rate_times=[];engine.last_audit_key=None
        freeze_until=time.time()+3.0
        state=engine.step()
        if state['decision']['path']!='IMPULSE':raise AssertionError('fixture did not produce IMPULSE: '+str(state['decision']))
        return state

@app.post('/test/reset')
def fixture_reset():reset();return jsonify(ok=True)

@app.post('/test/r3/impulse')
def fixture_r3_impulse():
    data=request.get_json(silent=True) or {};side=-1 if int(data.get('side',1))<0 else 1
    state=prime_impulse(side)
    return jsonify(ok=True,path=state['decision']['path'],structure=state['decision']['structure'])

# Use normal state endpoint and step actual engine periodically.
if __name__=='__main__':
    import threading
    reset()
    def work():
        global freeze_until
        while True:
            with engine.lock:
                if time.time()>=freeze_until:engine.step()
            time.sleep(.2)
    threading.Thread(target=work,daemon=True).start()
    app.run(host='0.0.0.0',port=8765,threaded=True,debug=False,use_reloader=False)
