"""CI fixture only: actual Engine/Flask with a fake broker. Never imports MetaTrader5."""
import sys,tempfile,time,uuid
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'mt5_bridge'),str(Path(__file__).resolve().parent)]
from event_core.server import create_app
from event_core.engine import Engine
from event_core.store import Store
from event_core.model import Config
from event_core.strategy import Strategy
from fakes import FakeBroker,wave
from flask import jsonify

folder=tempfile.TemporaryDirectory();broker=FakeBroker(time.time);broker.balance=99868.35
store=Store(Path(folder.name)/'fixture.db');engine=Engine(broker,store)
app=create_app(engine,'ci-fixture-token-not-for-real-trading')
def reset():
    with engine.lock:
        store.db.executescript('DELETE FROM commands; DELETE FROM intents; DELETE FROM campaigns; DELETE FROM state; DELETE FROM journal;');store.db.commit()
        broker._positions=[];broker._orders=[];broker.deals=[];broker.sent=[];broker.balance=99868.35
        engine.config=Config(fee_per_lot=0);engine.campaign=None;engine.emergency=False;engine.recovery=False
        engine.daily_latch='';engine.auto=False;engine.paused=True;engine.exit_pending=False;engine.ack=[0,0]
        engine.account_key='';engine.history_time=0;engine.strategy=Strategy(engine.config)
        engine.last_bars_at=0;engine.bars=[];engine.context=[];engine.rate_times=[];engine.last_exit=0;engine.save()
        broker.bar_data=wave(int(time.time()));broker.ctx_data=wave(int(time.time()),tf=900)
        engine.step()
@app.post('/test/reset')
def fixture_reset():reset();return jsonify(ok=True)
# Use normal state endpoint and step actual engine periodically.
if __name__=='__main__':
    import threading
    reset()
    def work():
        while True:engine.step();time.sleep(.2)
    threading.Thread(target=work,daemon=True).start()
    app.run(host='0.0.0.0',port=8765,threaded=True,debug=False,use_reloader=False)
