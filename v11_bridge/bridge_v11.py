"""FX-M1-Signal V11 Bridge. Run beside MT5 on Windows: python bridge_v11.py
DEMO-100, AUTO off. Never imports or enables the V10 engine.
HTTP is for a trusted private LAN only; do not expose this port to the Internet.
"""
from __future__ import annotations
import argparse
import hmac
import logging
from pathlib import Path
import secrets
import socket
import threading
import time
from flask import Flask, jsonify, request
from campaign_core import VERSION, PROTOCOL, Blocked
from mt5_session import day_id
from coordinator import Engine

def create_app(engine, token):
    app=Flask(__name__)
    app.config['MAX_CONTENT_LENGTH']=8192
    @app.before_request
    def auth():
        supplied=request.headers.get('Authorization','')
        if not hmac.compare_digest(supplied,'Bearer '+token):
            return jsonify(ok=False,message='Требуется ключ Bridge V11'),401
    @app.get('/v11/state')
    def state():
        with engine.lock:
            engine.heartbeat=engine.clock()
            value=dict(engine.snapshot)
            if not engine.money_ok:
                value['ok']=False
                value['reason']=value.get('reason','')+' · История не обновлена: '+engine.money_error
            return jsonify(value)
    @app.get('/v11/history')
    def history():
        with engine.lock:
            try:
                limit=min(500,max(1,int(request.args.get('limit',200))))
                offset=max(0,int(request.args.get('offset',0)))
            except ValueError:
                return jsonify(ok=False,message='Некорректная страница истории'),400
            rows=list(reversed(engine.history_rows))
            return jsonify(ok=True,money_ok=engine.money_ok,money_error=engine.money_error,
                history_time=engine.history_time,rows=rows[offset:offset+limit],total=len(rows),events=engine.store.events())
    @app.post('/v11/command/<cmd>')
    def command(cmd):
        try:
            data=request.get_json(silent=True) or {}
            if not isinstance(data,dict): raise Blocked('Ожидался объект команды')
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
    directory=Path(args.state_dir);directory.mkdir(parents=True,exist_ok=True)
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
            except Exception:
                with engine.lock:
                    engine.s['auto']=False;engine.s['paused']=True
                    try: engine.save()
                    except Exception: logging.exception('Cannot persist inhibition')
                logging.exception('Runtime failure; AUTO inhibited')
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
