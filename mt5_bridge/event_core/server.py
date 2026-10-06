from __future__ import annotations
from dataclasses import asdict
from contextlib import contextmanager
import argparse, hmac, json, logging, secrets, socket, threading, time, uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from flask import Flask, jsonify, request
from . import VERSION, PROTOCOL, BUILD, REVISION
from .engine import Engine
from .model import Blocked, TF_SECONDS
from .mt5_adapter import MT5Broker, MAGIC
from .store import Store, ProcessLock
from .risk import summary
from .clock_setup import load_clock_policy
from .runtime_view import RuntimeViews


def configure_runtime_log(directory,token,logger=None):
    class RedactedFormatter(logging.Formatter):
        def format(self,record):
            value=super().format(record)
            return value.replace(token,'[REDACTED]') if token else value
    handler=RotatingFileHandler(Path(directory)/'bridge-runtime.log',maxBytes=2*1024*1024,backupCount=3,encoding='utf-8')
    handler.setFormatter(RedactedFormatter('%(asctime)s %(levelname)s %(message)s'))
    (logger or logging.getLogger()).addHandler(handler)
    return handler


def create_app(engine,token):
    app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=16384
    views=RuntimeViews(engine);app.config['runtime_views']=views
    class Busy(Blocked):pass
    @contextmanager
    def admission():
        if not engine.lock.acquire(timeout=.25):
            raise Busy('Bridge занят обработкой MT5. Команда/запрос не приняты; повторите после обновления статуса.')
        try:yield
        finally:engine.lock.release()
    @app.errorhandler(Busy)
    def busy(e):return jsonify(ok=False,accepted=False,server_connected=True,runtime_busy=True,message=str(e)),503
    @app.before_request
    def auth():
        if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+token):
            return jsonify(ok=False,message='Введите ключ EventCore из окна Bridge. Старый Twelve Data key не подходит.'),401
        if hasattr(engine,'select_request'):
            body=request.get_json(silent=True) if request.method!='GET' else {}
            engine.select_request(request.args.get('profile_id') or (body or {}).get('profile_id'))
        if (engine.config.engine_mode=='SCENARIO_V2' and request.headers.get('X-FXM1-Client')!='R51'
                and (request.path=='/ec/state' or request.path in ('/ec/command/configure','/ec/command/enable','/ec/command/play'))):
            return jsonify(ok=False,message='Для Scenario V2 обновите APK и Bridge до R5.1. Аварийное закрытие и пауза доступны.'),426
        if request.method!='GET' and not request.is_json:
            return jsonify(ok=False,message='Требуется JSON-команда'),415

    @app.errorhandler(Blocked)
    def blocked(e):return jsonify(ok=False,message=str(e)),409
    @app.errorhandler(ValueError)
    def malformed(e):return jsonify(ok=False,message='Некорректные параметры: '+str(e)),400
    @app.errorhandler(404)
    def missing(e):return jsonify(ok=False,message='Этот старый endpoint не исполняет сделки. Нужен APK EventCore.'),404

    def control_metadata(result):
        # All state publication paths must advertise the same control protocol.
        # Otherwise an explicit refresh makes the phone fall back to legacy 503s.
        result.setdefault('capabilities',{})['queued_controls']=True
        result['control_queue']=app.config['command_inbox'].summary()
        return result
    def snap():
        result=views.read()
        if result is None:raise Busy('Профиль ещё не опубликован; повторите получение состояния.')
        return control_metadata(result)
    def healthy(s):return bool(s['account']) and s.get('account_age',999)<10

    @app.get('/ec/state')
    def state():
        if request.args.get('refresh')=='1':
            with admission():
                result=engine.refresh_view();views.remember(result)
                return jsonify(control_metadata(result))
        return jsonify(snap())

    @app.get('/ec/forecast')
    def forecast():
        with admission():return jsonify(engine.forecast_snapshot(request.args.get('tf',engine.config.timeframe)))

    @app.get('/ec/price-forecasts')
    def price_forecasts():
        # Read-only: a GET neither recalculates forecasts nor executes the engine.
        with admission():
            tf=request.args.get('tf',engine.config.timeframe)
            view=engine.forecast_snapshot(tf)
            price=view.get('forecast',{}).get('price_forecast',{})
            scope=price.get('scope','')
            return jsonify(ok=True,available=bool(scope),timeframe=tf,
                snapshots=engine.store.price_forecasts(scope,request.args.get('limit',100,type=int)) if scope else [],
                report=engine.store.price_forecast_report(scope) if scope else {},read_only=True)

    @app.get('/ec/history')
    def chart_history():
        with admission():
            tf=request.args.get('tf',engine.config.timeframe)
            if tf not in TF_SECONDS:raise Blocked('Неизвестный таймфрейм истории')
            before=request.args.get('before',type=int);limit=max(1,min(request.args.get('limit',1000,type=int),2000))
            ready=engine.store.market_clock_ready(engine.market_scope())
            rows=engine.store.read_bars(engine.market_scope(),tf,before,limit) if ready else []
            return jsonify(ok=True,scope=engine.market_scope(),tf=tf,bars=rows,clock=engine.broker_clock_identity,cache_verified=ready,
                next_before=rows[0]['time'] if rows else None,has_more=len(rows)==limit,read_only=True)

    @app.get('/ec/scenarios')
    def scenario_history():
        with admission():
            limit=max(1,min(request.args.get('limit',30,type=int),100))
            before=request.args.get('before',type=float);key=request.args.get('id')
            snapshots=engine.store.scenario_snapshots(engine.market_scope(),before,limit,key)
            if key is None:
                snapshots=[dict(snapshot_id=x['snapshot_id'],recorded_at=x['recorded_at'],
                    symbol=x.get('symbol'),timeframe=x.get('timeframe'),
                    title=next(iter(x.get('forecast',{}).get('scenarios',[])),{}).get('title','Нет ясной фигуры')) for x in snapshots]
            return jsonify(ok=True,snapshots=snapshots,next_before=snapshots[-1]['recorded_at'] if snapshots else None,
                           has_more=len(snapshots)==limit,read_only=True)

    @app.get('/health')
    def health():
        s=snap();a=s['account'];pos=s['all_positions']
        return jsonify(ok=healthy(s),server_connected=True,runtime_busy=s.get('runtime_busy',False),snapshot_age=s.get('snapshot_age',0),
            protocol=PROTOCOL,bridge_version=VERSION,bridge_build=BUILD,real_trading_enabled=s.get('real_armed',False),
            mt5_connected=healthy(s),account_type=a.get('type','UNKNOWN'),account_key=a.get('key',''),currency=a.get('currency','USD'),
            balance=a.get('balance'),equity=a.get('equity'),positions=len(pos),
            floating_pl=sum(p['profit']+p.get('swap',0) for p in pos),message=s['execution'])

    @app.get('/quote')
    def quote():
        with admission():
            info=engine.broker.symbol(request.args.get('symbol',engine.config.symbol))
            q=engine.broker.quote(info['name']);q.validate(engine.clock())
            return jsonify(ok=True,bid=q.bid,ask=q.ask,symbol=info['name'],time=q.time_msc/1000,
                source='MT5',account_type=engine.account.get('type','UNKNOWN'))

    @app.get('/positions')
    def positions():
        s=snap()
        if not healthy(s):raise Blocked('Нет свежих данных о позициях MT5')
        pos=[dict(p,side='BUY' if p['side']==1 else 'SELL',owned=p['magic']==MAGIC) for p in s['all_positions']]
        return jsonify(ok=True,count=len(pos),positions=pos,
            floating_pl=sum(p['profit']+p.get('swap',0) for p in pos),currency=s['account'].get('currency','USD'))

    @app.get('/trade-ledger')
    @app.get('/trade-log')
    def history():
        with admission():
            s=snap()
            if not s['history_ok']:raise Blocked('История MT5 не обновлена: '+s['history_error'])
            limit=min(5000,max(1,int(request.args.get('limit',1000))))
            offset=max(0,int(request.args.get('offset',0)))
            grouped={}
            for deal in engine.deals:grouped.setdefault(deal.get('position_id'),[]).append(deal)
            trades=[]
            for r in reversed(engine.rows):
                deals=grouped.get(r['position_id'],[])
                ins=[d for d in deals if d['entry']==0];outs=[d for d in deals if d['entry'] in (1,3)]
                entry=sum(d.get('price',0)*d['volume'] for d in ins)/r['opened']
                exit=sum(d.get('price',0)*d['volume'] for d in outs)/r['closed']
                detail=r.get('broker_exit',{})
                last_exit=max(outs,key=lambda d:(d['time_msc'],d['ticket'])) if outs else {}
                raw_comment=last_exit.get('comment','')
                # R5.7 already displays close_comment in detailed money/history.
                # Preserve the unmodified broker comment alongside the readable evidence.
                close_text='MT5: '+detail.get('text','Причина не получена от MT5')
                if raw_comment:close_text+='; комментарий: '+raw_comment
                trades.append(dict(position_id=r['position_id'],symbol=r['symbol'],side=r['side'],volume=r['volume'],
                    entry_time=int(r['open_time']),exit_time=int(r['time']),entry_price=entry,exit_price=exit,
                    duration_sec=int(r['time']-r['open_time']),net_pl=r['net'],
                    gross_pl=sum(d['profit'] for d in deals),commission=sum(d.get('commission',0)+d.get('fee',0) for d in deals),
                    swap=sum(d.get('swap',0) for d in deals),close_comment=close_text,
                    broker_close_comment=raw_comment,broker_exit=detail))
            return jsonify(ok=True,trades=trades[offset:offset+limit],total=len(trades),summary=s['all'],today=s['today'],
                           history_time=s['history_time'],account_key=s['account'].get('key',''),timezone='UTC+5')

    @app.get('/risk-state')
    def risk():
        with admission():
            engine._refresh(engine.clock())
            return jsonify(engine.risk)

    def sequence(data,cmd):
        client=str(data.get('client_id',''));seq=data.get('sequence')
        if not 8<=len(client)<=128 or not isinstance(seq,int) or isinstance(seq,bool) or seq<1:
            raise Blocked('Требуется идентификатор клиента и порядок команд')
        seen=engine.store.load('clients',{})
        last=int(seen.get(client,0))
        if seq<=last and not engine.store.command_result(str(data.get('command_id',''))):
            if cmd not in ('pause','disable','emergency','close'):
                raise Blocked('Устаревшая управляющая команда отклонена')
        seen[client]=max(seq,last);engine.store.save('clients',seen)

    from .command_inbox import CommandInbox
    app.config['command_inbox']=CommandInbox(engine,sequence,views)

    @app.get('/ec/commands/<command_id>')
    def command_status(command_id):
        return jsonify(app.config['command_inbox'].status(command_id))

    @app.post('/ec/command/<cmd>')
    def command(cmd):
        data=request.get_json(silent=False)
        if not isinstance(data,dict):raise Blocked('Ожидался объект команды')
        if request.headers.get('X-FXM1-Control')=='queued-v1':
            receipt=app.config['command_inbox'].receive(cmd,data)
            return jsonify(receipt),200 if receipt['command_status'] in ('APPLIED','REJECTED','EXPIRED','CANCELLED') else 202
        with admission():
            sequence(data,cmd)
            result=engine.command(cmd,data);views.publish()
            return jsonify(dict(result,accepted=True))

    @app.get('/ec/journal')
    @app.get('/journal')
    def journal():
        with admission():return jsonify(ok=True,events=engine.store.events(min(1000,int(request.args.get('limit',100)))))

    @app.get('/stats')
    def stats():
        s=snap();a=s['all'];n=a['count']
        return jsonify(ok=s['history_ok'],stats=dict(closed_trades=n,win_rate=a['wins']*100/n if n else 0,
            net_profit=a['net'],daily_realized_pl=s['today']['net'],consecutive_losses=s['risk'].get('consecutive_losses',0)))

    @app.get('/symbols')
    def symbols():
        with admission():
            names=engine.broker.symbols() if hasattr(engine.broker,'symbols') else [engine.config.symbol]
            return jsonify(ok=True,symbols=names,count=len(names),source='MT5')

    @app.post('/signal')
    @app.post('/scalp-intent')
    @app.post('/manage-positions')
    def obsolete():
        return jsonify(ok=False,accepted=False,message='Старый торговый модуль отключён. Решения принимает EventCore.'),410

    return app


def main():
    p=argparse.ArgumentParser(description='FXM1 EventCore EC1 — DEMO ONLY')
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8000)
    p.add_argument('--terminal',default=None)
    p.add_argument('--state-dir',default=str(Path(__file__).resolve().parents[1]/'event_state'))
    args=p.parse_args()
    import MetaTrader5 as mt5
    directory=Path(args.state_dir);directory.mkdir(parents=True,exist_ok=True)
    lock=ProcessLock(directory/'runtime.lock')
    tokenfile=directory/'bridge-token.txt'
    if not tokenfile.exists():
        tokenfile.write_text(secrets.token_urlsafe(32),encoding='utf-8')
        try:tokenfile.chmod(0o600)
        except OSError:pass
    token=tokenfile.read_text(encoding='utf-8').strip()
    if len(token)<32:raise SystemExit('Ключ Bridge повреждён. Не удаляйте базу состояния.')
    configure_runtime_log(directory,token)
    logging.getLogger().setLevel(logging.INFO)
    logging.info('Bridge %s startup; host=%s port=%s; AUTO OFF; DEMO ONLY',BUILD,args.host,args.port)
    policy=load_clock_policy(directory)
    from .portfolio import Portfolio
    store=Store(directory/'campaign.sqlite3');engine=Portfolio(MT5Broker(mt5,args.terminal,**policy),store,entry_model='STABLE_V1')
    app=create_app(engine,token)
    views=app.config['runtime_views']
    def worker():
        while True:
            try:
                app.config['command_inbox'].drain()
                engine.step()
                app.config['command_inbox'].drain()
                views.publish()
            except Exception:
                with engine.lock:
                    for runtime in engine.engines.values():
                        runtime.auto=False;runtime.paused=True;runtime.recovery=True;runtime.save()
                    views.publish()
                logging.exception('Runtime error; new entries inhibited')
            time.sleep(.5)
    threading.Thread(target=worker,name='event-core',daemon=True).start()
    try:ip=socket.gethostbyname(socket.gethostname())
    except OSError:ip='PC_IP'
    print(f'FX M1 Bridge {BUILD} {REVISION} | DEMO ONLY | AUTO OFF | MT5 source',flush=True)
    print(f'Адрес для телефона: http://{ip}:{args.port}',flush=True)
    print('Ключ Bridge (не публикуйте): '+token,flush=True)
    print('Только доверенная локальная сеть. Не открывать порт в Интернет.',flush=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    try:app.run(host=args.host,port=args.port,threaded=True,use_reloader=False,debug=False)
    finally:lock.close()
