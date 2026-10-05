"""CI fixture only: actual Engine/Flask with a fake broker. Never imports MetaTrader5."""
import calendar,sys,tempfile,threading,time,uuid
from dataclasses import replace
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'mt5_bridge'),str(Path(__file__).resolve().parent)]
from event_core.server import create_app
from event_core.engine import Engine
from event_core.store import Store
from event_core.model import Bar,Blocked,Config,Decision,TF_SECONDS,atr,pivots
from event_core.observers import ForecastObservers,PUBLIC_TIMEFRAMES
from event_core.strategy import Strategy
from event_core.compute_core import ComputeCore
from test_compute_core import market, NOW
from fakes import FakeBroker,wave
from flask import g,jsonify,request

folder=tempfile.TemporaryDirectory();broker=FakeBroker(time.time);broker.balance=99868.35
store=Store(Path(folder.name)/'fixture.db');engine=Engine(broker,store)
app=create_app(engine,'ci-fixture-token-not-for-real-trading')
freeze_until=0.0
normal_broker=broker
r54_refresh_config={}
r54_refresh_audit={'refresh_requests':0,'ledger_requests':0,'events_requests':0}
r56_config={}
r56_read_lock=threading.Lock()
r56_read_hold=dict(armed=False,captured=False,release=threading.Event())


def clear_read_hold(armed=False):
    global r56_read_hold
    with r56_read_lock:
        r56_read_hold['release'].set()
        r56_read_hold=dict(armed=armed,captured=False,release=threading.Event())

def clear_market():
    engine.last_bars_at=0;engine.last_market_attempt=-1.
    engine.bars=[];engine.context=[];engine.m1=[];engine.m15=[];engine.h1=[];engine.live_bar=None
    engine.quote=None;engine.info={};engine.market_time=0.;engine.market_errors=[];engine.bar_errors=[]
    engine.quote_ready=False;engine.analysis_time=0.;engine.decision=Decision()
    engine.chart_market=None;engine.last_chart_attempt=-1.

def reset():
    global freeze_until,broker,r54_refresh_config,r56_config
    clear_read_hold()
    with engine.lock:
        broker=normal_broker;engine.broker=broker
        r54_refresh_config={}
        r56_config={};engine.observers=ForecastObservers()
        r54_refresh_audit.update(refresh_requests=0,ledger_requests=0,events_requests=0)
        freeze_until=0.0
        anchor=int(time.time())
        store.db.executescript('DELETE FROM commands; DELETE FROM intents; DELETE FROM campaigns; DELETE FROM state; DELETE FROM journal;');store.db.commit()
        if hasattr(engine,'_history_loaded'):
            engine._history_loaded.clear();engine._history_fingerprint.clear()
            store.db.executescript('DELETE FROM market_bars; DELETE FROM scenario_snapshots;');store.db.commit()
        broker._positions=[];broker._orders=[];broker.deals=[];broker.sent=[];broker.closed=[];broker.balance=99868.35
        broker.bid=1.103;broker.ask=broker.bid+.00001;broker.quote_age=0;broker.result='FILLED';broker.visible=True
        broker.demo=True;broker.margin_mode='HEDGING';broker.trade_allowed=True;broker.history_failure=False;broker.live_bar_data=None
        engine.config=Config(fee_per_lot=0);engine.campaign=None;engine.emergency=False;engine.recovery=False
        engine.pending_config=None;engine.campaign_history_cache={};engine.pending_reversal=None;engine.reversal_status={}
        engine.compute=ComputeCore(engine.config)
        engine.daily_latch='';engine.auto=False;engine.paused=True;engine.exit_pending=False;engine.ack=[0,0]
        engine.account_key='';engine.history_time=0;engine.history_ok=False;engine.history_error='История ещё не получена';engine.strategy=Strategy(engine.config)
        clear_market();engine.rate_times=[];engine.last_exit=0;engine.next_close=0;engine.last_audit_key=None
        broker.m1_data=wave(anchor,tf=60,trend=.000006)
        broker.bar_data=wave(anchor,tf=300,trend=.00003)
        broker.ctx_data=wave(anchor,tf=900,trend=.00004)
        broker.h1_data=wave(anchor,tf=3600,trend=.00008)
        engine.save();engine.step()
        # Scene changes must update the same nonblocking cache read by the APK.
        # Otherwise a concurrent worker makes GET /ec/state replay the old scene.
        app.config['runtime_views'].publish()

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
def fixture_reset():
    reset();r53_commands.clear();return jsonify(ok=True)

@app.post('/test/r3/impulse')
def fixture_r3_impulse():
    data=request.get_json(silent=True) or {};side=-1 if int(data.get('side',1))<0 else 1
    state=prime_impulse(side)
    return jsonify(ok=True,path=state['decision']['path'],structure=state['decision']['structure'])

# Upgrade fixture: real engine with a legacy campaign whose closing deal is delayed.
legacy_complete=[]
@app.post('/test/legacy-upgrade')
def legacy_upgrade():
    global legacy_complete
    reset()
    with engine.lock:
        engine.config=Config(engine_mode='LEGACY',fee_per_lot=0,approved=True,cooldown_sec=0)
        engine.strategy=Strategy(engine.config);engine.compute=ComputeCore(engine.config)
        engine._refresh(time.time());engine.info=broker.symbol('EURUSD');engine.quote=broker.quote('EURUSD')
        d=Decision('SELL','ENTRY_READY','legacy campaign','old-upgrade',-1,
            1.1034,1.10301,1.1034,.0005,int(time.time()*1000))
        engine._entry(d,time.time())
        broker.close_position(broker._positions[0])
        legacy_complete=list(broker.deals)
        broker.deals=broker.deals[:1]  # Closing history not yet available, positions are already zero.
        engine.history_time=0;engine.save();engine.step()
        return jsonify(ok=True)

@app.post('/test/legacy-finish')
def legacy_finish():
    with engine.lock:
        broker.deals=list(legacy_complete);engine.history_time=0
        prime_r5_market('RANGE')
        engine.last_market_attempt=-1;engine.step()
        return jsonify(ok=True)

def prime_r5_market(family='TRIANGLE'):
    from dataclasses import replace
    from test_r5_scenarios import lane, pole_pattern, shaped
    now=int(time.time());anchor=now//300*300
    raw=pole_pattern(family) if family in ('FLAG','PENNANT') else lane(family)
    if family=='HEAD_SHOULDERS':raw=shaped([1.102,1.100,1.104,1.100,1.102])
    delta=anchor-int(NOW)
    broker.bar_data=[replace(b,time=b.time+delta) for b in raw]
    broker.ctx_data=[replace(b,time=now//900*900-(len(raw)-i)*900) for i,b in enumerate(raw)]
    broker.h1_data=[replace(b,time=now//3600*3600-(len(raw)-i)*3600) for i,b in enumerate(raw)]
    price=(min(b.low for b in raw[-12:])+max(b.high for b in raw[-12:]))/2
    broker.m1_data=[Bar(now//60*60-(20-i)*60,price,price+.00003,price-.00003,price) for i in range(20)]
    broker.live_bar_data=Bar(anchor,price,price+.00004,price-.00004,price)
    broker.bid=price;broker.ask=price+.00001;broker.quote_age=0
    clear_market()

@app.post('/test/r5-market')
def r5_market():
    from event_core.compute_core import make_compute
    data=request.get_json(silent=True) or {}
    with engine.lock:
        engine.config=Config(engine_mode='SCENARIO_V2',volume_mode='FIXED',lot_cap=.1,probe_lot_cap=.1,fee_per_lot=0,approved=True)
        engine.compute=make_compute(engine.config);engine.auto=False;engine.paused=True
        engine.campaign=None;broker._positions=[];broker._orders=[]
        prime_r5_market(str(data.get('family','TRIANGLE')))
        engine.step()
        app.config['runtime_views'].publish()
        return jsonify(ok=True,forecast=engine.forecast)


class R56Broker(FakeBroker):
    """Native frame data only; forecasts remain the production Engine's work."""
    def __init__(self,clock):
        from test_r5_scenarios import lane
        super().__init__(clock)
        self.balance=99868.35;self.bid=1.101;self.ask=self.bid+.00001
        self.frames={};self.ends={};self.fail=set();now=int(clock())
        source=lane('RANGE')
        for index,tf in enumerate(PUBLIC_TIMEFRAMES):
            end=self.frame_start(tf,now);self.ends[tf]=end;span=TF_SECONDS[tf]
            times=[end-(len(source)-i)*span for i in range(len(source))]
            if tf=='MN1':
                current=time.gmtime(now);month=current.tm_year*12+current.tm_mon-1
                times=[calendar.timegm(((month-len(source)+i)//12,(month-len(source)+i)%12+1,1,0,0,0))
                       for i in range(len(source))]
            offset=index*.00001
            self.frames[tf]=[replace(b,time=t,open=b.open+offset,high=b.high+offset,
                low=b.low+offset,close=b.close+offset) for b,t in zip(source,times)]

    @staticmethod
    def frame_start(tf,now):
        if tf=='MN1':
            current=time.gmtime(now)
            return calendar.timegm((current.tm_year,current.tm_mon,1,0,0,0))
        return int(now)//TF_SECONDS[tf]*TF_SECONDS[tf]

    def bars(self,symbol,tf):
        if tf in self.fail:raise Blocked('Тестовые данные '+tf+' недоступны')
        # The UI suite crosses real minute/hour boundaries. Close only elapsed
        # forming bars; never leave the M1 safety feed frozen during a long test.
        from event_core.model import bar_close_time
        end=self.frame_start(tf,self.clock());offset=PUBLIC_TIMEFRAMES.index(tf)*.00001
        while self.ends[tf]<end:
            started=self.ends[tf]
            self.frames[tf].append(Bar(started,1.101+offset,max(1.1013+offset,self.bid),
                min(1.1007+offset,self.bid),self.bid,1))
            self.ends[tf]=bar_close_time(started,tf,0)
        self.frames[tf]=self.frames[tf][-1200:]
        return list(self.frames[tf])

    def current_bar(self,symbol,tf):
        if tf in self.fail:raise Blocked('Тестовые данные '+tf+' недоступны')
        offset=PUBLIC_TIMEFRAMES.index(tf)*.00001
        return Bar(self.frame_start(tf,self.clock()),1.101+offset,
            max(1.1013+offset,self.bid),min(1.1007+offset,self.bid),self.bid,1)


@app.post('/test/r56-multiframe')
def r56_multiframe():
    global broker,freeze_until,r56_config
    from event_core.compute_core import make_compute
    data=request.get_json(silent=True) or {}
    with engine.lock:
        if not isinstance(broker,R56Broker):
            broker=R56Broker(engine.clock);engine.broker=broker
            engine.config=Config(engine_mode='SCENARIO_V2',timeframe='M5',fee_per_lot=0,approved=True)
            engine.compute=make_compute(engine.config);engine.strategy=Strategy(engine.config)
            engine.observers=ForecastObservers();engine.auto=False;engine.paused=True
            engine.campaign=None;engine.account_key='';engine.history_time=0
            clear_market();r53_commands.clear()
        r56_config=dict(data)
        broker.fail={str(data['unavailable_tf'])} if data.get('unavailable_tf') else set()
        if data.get('bump'):broker.bid+=.0002;broker.ask=broker.bid+.00001
        # Controls may be changed inside the normal one-second observer throttle.
        # Keep each real ScenarioCore; only force its next data observation.
        engine.observers.attempts.clear();engine.observers.series.clear()
        engine.last_market_attempt=-1.;engine.last_bars_at=0
        freeze_until=0.;now=engine.clock()
        engine.step();engine._refresh_observers(now,budget=9)
        return jsonify(ok=True,timeframes=list(PUBLIC_TIMEFRAMES),trade_timeframe=engine.config.timeframe)


@app.before_request
def r56_forecast_delay():
    if request.path=='/ec/forecast':
        g.r56_options=dict(r56_config)
        if request.args.get('tf')==g.r56_options.get('delayed_tf'):
            time.sleep(max(0,min(float(g.r56_options.get('delay_ms',0)),8000))/1000)


@app.after_request
def r56_forecast_faults(response):
    # Happy-path responses are untouched. Identity faults test only UI guards.
    if request.path!='/ec/forecast' or response.status_code!=200:return response
    options=getattr(g,'r56_options',{})
    if not any(options.get(k) for k in ('wrong_frame','wrong_scope','wrong_clock','wrong_account')):return response
    data=response.get_json()
    if options.get('wrong_frame'):
        data['config']['timeframe']='H4' if request.args.get('tf')!='H4' else 'M1'
    if options.get('wrong_scope'):data['market_scope']+='|WRONG_SCOPE'
    if options.get('wrong_clock'):data['market_history_generation']='WRONG_CLOCK'
    if options.get('wrong_account'):data['account']['key']='999@OTHER_DEMO'
    response.set_data(app.json.dumps(data))
    return response


@app.route('/test/r56-read-hold',methods=['GET','POST'])
def r56_read_hold_control():
    if request.method=='POST':
        clear_read_hold(bool((request.get_json(silent=True) or {}).get('hold')))
    with r56_read_lock:
        return jsonify(ok=True,armed=r56_read_hold['armed'],captured=r56_read_hold['captured'],
            ready=r56_read_hold['captured'],released=r56_read_hold['release'].is_set())


@app.post('/test/r56-read-release')
def r56_read_release():
    with r56_read_lock:
        r56_read_hold['armed']=False
        r56_read_hold['release'].set()
    return jsonify(ok=True)


@app.after_request
def r56_hold_completed_state(response):
    # Flask has already built the genuine snapshot and released Engine.lock.
    # Claim exactly one response; all other reads and commands remain free.
    if request.path!='/ec/state' or request.method!='GET' or response.status_code!=200:return response
    with r56_read_lock:
        if not r56_read_hold['armed']:return response
        r56_read_hold['armed']=False;r56_read_hold['captured']=True
        release=r56_read_hold['release']
    release.wait(8)
    release.set()
    return response

# Test-only transport audit and deterministic financial data; never loaded by the shipped Bridge.
r53_commands=[]
@app.before_request
def audit_commands():
    if request.path.startswith('/ec/command/'):
        r53_commands.append(dict(command=request.path.rsplit('/',1)[-1],body=request.get_json(silent=True) or {}))

@app.get('/test/r53-command-audit')
def r53_command_audit():return jsonify(commands=r53_commands)

@app.post('/test/r53-state')
def r53_state():
    from event_core.risk import Plan
    data=request.get_json(silent=True) or {}
    with engine.lock:
        if 'bid' in data:broker.bid=float(data['bid']);broker.ask=broker.bid+.00001
        if 'quote_age' in data:broker.quote_age=float(data['quote_age'])
        if 'history_failure' in data:broker.history_failure=bool(data['history_failure'])
        if data.get('completed_trade'):
            p=Plan(1,'EURUSD',.01,broker.bid-.0003,broker.bid-.001,broker.bid-.0003,broker.bid-.001,.7,.7,.1,'fixture-money')
            broker.send(p,'manual fixture closed')
            position=broker._positions[-1];position['magic']=0;broker.deals[-1]['magic']=0
            broker.close_position(position)
        if data.get('manual_position') and not broker._positions:
            p=Plan(1,'EURUSD',.01,broker.bid-.0001,broker.bid-.001,broker.bid-.0001,broker.bid-.001,.9,.9,.1,'fixture-manual')
            broker.send(p,'manual fixture open')
            broker._positions[-1]['magic']=0;broker.deals[-1]['magic']=0
        if 'balance' in data:broker.balance=float(data['balance'])
        engine.history_time=0;engine.last_market_attempt=-1
        result=engine.step()
        return jsonify(ok=True,state=result)

@app.post('/test/r54-future-time')
def r54_future_time():
    global broker,freeze_until
    from test_r54_market import DisplayTerminalBroker
    reset()
    with engine.lock:
        now=[time.time()]
        broker=DisplayTerminalBroker(now);broker.terminal.tick=now[0]+10797.4
        engine.broker=broker
        engine.config=Config(engine_mode='SCENARIO_V2',approved=True,fee_per_lot=0)
        from event_core.compute_core import make_compute
        engine.compute=make_compute(engine.config)
        clear_market();engine.history_time=0;engine.account_key=''
        freeze_until=time.time()+120
        state=engine.step()
        return jsonify(ok=True,state=state)

@app.post('/test/r55-controls')
def r55_controls():
    global freeze_until
    from event_core.compute_core import make_compute
    data=request.get_json(silent=True) or {}
    reset()
    with engine.lock:
        engine.config=Config(engine_mode='SCENARIO_V2',approved=True,fee_per_lot=0)
        engine.compute=make_compute(engine.config)
        engine._refresh(time.time())
        if data.get('campaign'):
            d=Decision('SELL','ENTRY_READY','active fixture','r55-campaign',-1,
                1.1034,1.10301,1.1034,.0005,int(time.time()*1000))
            engine._entry(d,time.time())
            assert engine.campaign is not None
        broker.quote_age=-10797.7 if data.get('quote_future') else 0
        engine.auto=bool(data.get('auto'));engine.paused=not engine.auto
        clear_market();engine.history_time=0
        freeze_until=time.time()+300
        engine.refresh_view()
        engine.save();r53_commands.clear()
        return jsonify(ok=True,state=engine.snapshot())

@app.post('/test/r54-refresh')
def r54_refresh_setup():
    global r54_refresh_config,freeze_until
    with engine.lock:
        r54_refresh_config=dict(request.get_json(silent=True) or {})
        r54_refresh_audit.update(refresh_requests=0,ledger_requests=0,events_requests=0)
        r53_commands.clear()
        freeze_until=time.time()+120
    return jsonify(ok=True)

@app.get('/test/r54-refresh-audit')
def r54_refresh_stats():
    return jsonify(**r54_refresh_audit,commands=list(r53_commands))

@app.before_request
def r54_refresh_observer():
    if request.path=='/trade-ledger':r54_refresh_audit['ledger_requests']+=1
    if request.path=='/ec/journal':
        r54_refresh_audit['events_requests']+=1
        delay=max(0,min(float(r54_refresh_config.get('journal_delay_ms',0)),8000))/1000
        if delay:time.sleep(delay)
    if request.path=='/ec/state' and request.args.get('refresh')=='1':
        # Capture by value; an old timed-out request must not consume a new fixture.
        data=dict(r54_refresh_config)
        r54_refresh_audit['refresh_requests']+=1
        time.sleep(max(0,min(float(data.get('delay_ms',0)),8000))/1000)
        if data.get('fail'):return jsonify(ok=False,message='fixture refresh unavailable'),503
        with engine.lock:
            if data==r54_refresh_config and 'account_balance' in data:broker.balance=float(data['account_balance'])
            if data==r54_refresh_config and data.get('marker'):
                store.event(str(data['marker']),{'message':str(data['marker'])},time.time())

from r732_ui_fixture import install as install_pattern_fixture
install_pattern_fixture(app,engine)

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
