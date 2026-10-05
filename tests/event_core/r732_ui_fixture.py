"""Test-only HTTP presentation of actual PatternCatalog numeric output.

Baseline account/transport remain the production Engine with a fake broker. Only
synthetic chart observations are injected; no production code knows about fixtures.
"""
import copy,time
from flask import request,jsonify
from export_r732_chart_fixtures import state_for
from pattern_fixtures_r732 import VARIANTS

def install(app,engine):
 selection={}
 @app.before_request
 def clear_on_reset():
  if request.path=='/test/reset':selection.clear()
 @app.post('/test/r732-pattern')
 def choose():
  data=request.get_json(silent=True) or {};i=int(data.get('index',0))
  if i<0 or i>19:return jsonify(error='invalid fixture'),400
  family,variant=VARIANTS[17 if i==19 else i]
  selection.clear();selection.update(index=i,forming=i==19,variant=data.get('view','live'))
  selection['state']=state_for(family,variant,forming=i==19,observed_now=time.time())
  if data.get('position'):
   from event_core.risk import Plan
   with engine.lock:
    engine.broker._positions=[];price=selection['state']['live_bar']['close'];engine.broker.bid=price;engine.broker.ask=price+.00001
    p=Plan(1,'EURUSD',.01,price-.0002,price-.001,price-.0002,price-.001,.8,.8,.1,'r732-ui-test')
    engine.broker.send(p,'R732 synthetic position');pos=engine.broker._positions[-1];pos['profit']=2.5
    selection['positions']=copy.deepcopy(engine.broker.positions())
  return jsonify(ok=True,synthetic=True)
 @app.after_request
 def chart_response(response):
  if not selection or request.path!='/ec/state' or response.status_code!=200:return response
  s=response.get_json();numeric=copy.deepcopy(selection['state']);cfg=s.get('config',{});cfg.update(numeric.pop('config'))
  s.update(numeric);s['config']=cfg;s['server_time']=time.time();s['analysis_time']=time.time();s['market_time']=time.time()
  s['account_age']=0;s['auto']=False;s['paused']=True;s['chart_market']=None;s['snapshot_age']=0
  s['quote']={'time_msc':int(time.time()*1000),'bid':numeric['live_bar']['close'],'ask':numeric['live_bar']['close']+.00001}
  s['forecast']['execution_setup']={'mode':'NORMAL','timeframe':'M5','stage':'WAIT_CONTEXT','side':0,'reason':'Фигура наблюдается; вход не подтверждён'}
  s['decision'].update(phase='SEARCH',reason='Геометрия и вход проверяются отдельно',path='SCENARIO_V2')
  if 'positions' in selection:s['positions']=copy.deepcopy(selection['positions'])
  view=selection['variant']
  if view=='empty':s['forecast']['pattern_chart']['patterns']=[];s['forecast']['pattern_chart']['branches']=[];s['forecast']['selected_pattern_id']=''
  if view=='stale':s['quote_fresh']=False;s['forecast']['stale']=True
  if view=='offline':s['client_offline']=True;s['forecast']['client_offline']=True
  response.set_data(app.json.dumps(s));response.content_type='application/json';return response
