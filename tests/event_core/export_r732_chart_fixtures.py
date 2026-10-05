"""Export production catalog outputs for native UI verification; synthetic data only."""
import argparse,json
from dataclasses import asdict,replace
from pathlib import Path
from event_core.model import atr,bar_close_time,TF_SECONDS
from event_core.scenarios.pattern_view import PatternCatalog
from event_core.scenarios.structure import detect_patterns
from event_core.scenarios.lifecycle import create_scenarios
from pattern_fixtures_r732 import fixture,live_after,VARIANTS,FRAMES


def state_for(family,variant,tf='M5',symbol='EURUSD',forming=False,observed_now=None):
    rows=fixture(family,variant,tf,symbol);catalog=PatternCatalog();result=None
    cuts=range(24,len(rows)) if forming else (len(rows),)
    for n in cuts:
        bars=rows[:n]
        if n<len(rows):live=rows[n];now=bar_close_time(live.time,tf)-.001
        else:live,now=live_after(bars,tf)
        if observed_now is not None:
            if tf in ('W1','MN1'):raise ValueError('Live screenshot clock is used only for intraday fixtures')
            shift=int(observed_now)//TF_SECONDS[tf]*TF_SECONDS[tf]-live.time
            bars=[replace(b,time=b.time+shift) for b in bars];live=replace(live,time=live.time+shift);now=observed_now
        scenarios=[]
        for p in detect_patterns(bars,symbol,tf,require_live_geometry=True):
            scenarios.extend(create_scenarios(p,bars,atr(bars),live.close,now))
        view=catalog.update(bars,live,symbol=symbol,timeframe=tf,mode='NORMAL',scope='numeric-ui-demo',
                            clock_generation='UTC_NUMERIC_FIXTURE',now=now,scenarios=scenarios)
        pattern=next((p for p in view['patterns'] if p['family']==family and p['variant']==variant
                      and p['geometry_state']==('FORMING' if forming else 'DETECTED')),None)
        if pattern is None:continue
        f=dict(map_version=3,available=True,symbol=symbol,timeframe=tf,live_price=live.close,data_asof=now,
               history_clock='UTC_NUMERIC_FIXTURE',scenarios=[],pattern_chart=view,show_price_forecast=False,
               selected_pattern_id=pattern['view_id'],chart_display_mode='PATTERNS')
        # Research payload remains present to prove that it cannot replace the pattern view.
        f['price_forecast']=dict(available=True,timeframe=tf,symbol=symbol,model='TEST_RESEARCH',origin=live.close,
            issued_at=now,projection=[dict(time=now+900,minutes=15,center=live.close,low=live.close*.99,high=live.close*1.01)])
        result=dict(config=dict(symbol=symbol,timeframe=tf,mode='NORMAL'),forecast=f,
            bars=[asdict(b) for b in bars],live_bar=asdict(live),market_scope='numeric-ui-demo',
            market_history_generation='UTC_NUMERIC_FIXTURE',quote_fresh=True,
            instrument=dict(name=symbol,digits=5 if symbol=='EURUSD' else 3 if symbol=='USDJPY' else 2),
            decision=dict(signal='WAIT'),positions=[],fixture=dict(family=family,variant=variant,synthetic=True))
        break
    if result is None:raise AssertionError('No real numeric fixture for '+repr((family,variant,tf,symbol,forming)))
    return result


def export(path):
    samples=[state_for(*pair) for pair in VARIANTS]
    samples.append(state_for('HEAD_SHOULDERS','TOP',forming=True))
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(samples,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return len(samples)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('path',nargs='?',default='app/src/androidTest/assets/r732-pattern-fixtures.json')
    print('NATIVE_NUMERIC_FIXTURES',export(p.parse_args().path))
