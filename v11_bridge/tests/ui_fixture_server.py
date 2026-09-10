import sys,time,threading,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bridge_v11 import Engine,create_app
from fake_mt5 import FakeMT5
from flask import jsonify
folder=tempfile.TemporaryDirectory()
mt5=FakeMT5()
engine=Engine(mt5,Path(folder.name)/'ui.sqlite3')
engine.connect();engine.positions();engine.history(True)
engine.s['fee_per_lot']=0.0;engine.save();engine.step()
app=create_app(engine,'fixture-token-1234567890')
@app.post('/test/reset')
def reset():
    with engine.lock:
        engine.s.update(auto=False,paused=True,emergency=False,recovery=False,daily_latch='',campaign=None,pending=None)
        engine.s['generation']+=1;engine.save();engine.emergency_request.clear();engine.step()
        return jsonify(ok=True)
def loop():
    while True:
        engine.step();time.sleep(.5)
threading.Thread(target=loop,daemon=True).start()
app.run(host='0.0.0.0',port=8000,debug=False,use_reloader=False,threaded=True)
