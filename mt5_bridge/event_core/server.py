from __future__ import annotations
from dataclasses import asdict
import argparse, hmac, json, logging, secrets, socket, threading, time, uuid
from pathlib import Path
from flask import Flask, jsonify, request
from . import VERSION, PROTOCOL
from .engine import Engine
from .model import Blocked
from .mt5_adapter import MT5Broker, MAGIC
from .store import Store, ProcessLock
from .risk import summary


def create_app(engine,token):
    app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=16384
    @app.before_request
    def auth():
        if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+token):
            return jsonify(ok=False,message='Введите ключ EventCore из окна Bridge. Старый Twelve Data key не подходит.'),401
        if request.method!='GET' and not request.is_json:
            return jsonify(ok=False,message='Требуется JSON-команда'),415

    @app.errorhandler(Blocked)
    def blocked(e):return jsonify(ok=False,message=str(e)),409
    @app.errorhandler(ValueError)
    def malformed(e):return jsonify(ok=False,message='Некорректные параметры: '+str(e)),400
    @app.errorhandler(404)
    def missing(e):return jsonify(ok=False,message='Этот старый endpoint не исполняет сделки. Нужен APK EventCore.'),404

    def snap(): return engine.snapshot()
    def healthy(s):return bool(s['account']) and s.get('account_age',999)<10

    @app.get('/ec/state')
    def state():
        with engine.lock:
            engine.heartbeat=engine.clock()
            return jsonify(snap())

    @app.get('/health')
    def health():
        s=snap();a=s['account'];pos=s['all_positions']
        return jsonify(ok=healthy(s),protocol=PROTOCOL,bridge_version=VERSION,real_trading_enabled=False,
            mt5_connected=healthy(s),account_type=a.get('type','UNKNOWN'),currency=a.get('currency','USD'),
            balance=a.get('balance'),equity=a.get('equity'),positions=len(pos),
            floating_pl=sum(p['profit']+p.get('swap',0) for p in pos),message=s['execution'])

    @app.get('/quote')
    def quote():
        with engine.lock:
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
        with engine.lock:
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
                trades.append(dict(position_id=r['position_id'],symbol=r['symbol'],side=r['side'],volume=r['volume'],
                    entry_time=int(r['open_time']),exit_time=int(r['time']),entry_price=entry,exit_price=exit,
                    duration_sec=int(r['time']-r['open_time']),net_pl=r['net'],
                    gross_pl=sum(d['profit'] for d in deals),commission=sum(d.get('commission',0)+d.get('fee',0) for d in deals),
                    swap=sum(d.get('swap',0) for d in deals),close_comment=outs[-1].get('comment','') if outs else ''))
            return jsonify(ok=True,trades=trades[offset:offset+limit],total=len(trades),summary=s['all'],today=s['today'],
                           history_time=s['history_time'],timezone='UTC+5')

    @app.get('/risk-state')
    def risk():
        with engine.lock:
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

    @app.post('/ec/command/<cmd>')
    def command(cmd):
        data=request.get_json(silent=False)
        if not isinstance(data,dict):raise Blocked('Ожидался объект команды')
        with engine.lock:
            sequence(data,cmd)
            return jsonify(engine.command(cmd,data))

    @app.get('/ec/journal')
    @app.get('/journal')
    def journal():
        with engine.lock:return jsonify(ok=True,events=engine.store.events(min(1000,int(request.args.get('limit',100)))))

    @app.get('/stats')
    def stats():
        s=snap();a=s['all'];n=a['count']
        return jsonify(ok=s['history_ok'],stats=dict(closed_trades=n,win_rate=a['wins']*100/n if n else 0,
            net_profit=a['net'],daily_realized_pl=s['today']['net'],consecutive_losses=s['risk'].get('consecutive_losses',0)))

    @app.get('/symbols')
    def symbols():
        return jsonify(ok=True,symbols=['EURUSD','GBPUSD','USDJPY','USDCHF','AUDUSD','USDCAD','NZDUSD','XAUUSD'])

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
    store=Store(directory/'campaign.sqlite3');engine=Engine(MT5Broker(mt5,args.terminal),store)
    def worker():
        while True:
            try:engine.step()
            except Exception:
                with engine.lock:
                    engine.auto=False;engine.paused=True;engine.recovery=True;engine.save()
                logging.exception('Runtime error; new entries inhibited')
            time.sleep(.5)
    threading.Thread(target=worker,name='event-core',daemon=True).start()
    try:ip=socket.gethostbyname(socket.gethostname())
    except OSError:ip='PC_IP'
    print(f'FX M1 Bridge {VERSION} | DEMO ONLY | AUTO OFF | MT5 source',flush=True)
    print(f'Адрес для телефона: http://{ip}:{args.port}',flush=True)
    print('Ключ Bridge (не публикуйте): '+token,flush=True)
    print('Только доверенная локальная сеть. Не открывать порт в Интернет.',flush=True)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    try:create_app(engine,token).run(host=args.host,port=args.port,threaded=True,use_reloader=False,debug=False)
    finally:lock.close()
