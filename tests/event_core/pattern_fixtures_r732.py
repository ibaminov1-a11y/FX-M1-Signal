"""Numeric candles used in both causal tests and native screenshots.

These are synthetic fixtures, never broker history or claims of profitability.
The expected family is not passed to production detection.
"""
from dataclasses import replace
from datetime import datetime, timezone
import calendar
import math
from event_core.model import Bar, TF_SECONDS, bar_close_time
from test_r5_scenarios import lane, pole_pattern, shaped, BASE

VARIANTS = (
    ('TRIANGLE','ASCENDING'), ('TRIANGLE','DESCENDING'), ('TRIANGLE','SYMMETRIC'),
    ('FLAG','BULL'), ('FLAG','BEAR'), ('PENNANT','BULL'), ('PENNANT','BEAR'),
    ('CHANNEL','RISING'), ('CHANNEL','FALLING'), ('RANGE','HORIZONTAL'),
    ('WEDGE','RISING'), ('WEDGE','FALLING'), ('BROADENING','EXPANDING'),
    ('MULTI_EXTREME','DOUBLE_TOP'), ('MULTI_EXTREME','TRIPLE_TOP'),
    ('MULTI_EXTREME','DOUBLE_BOTTOM'), ('MULTI_EXTREME','TRIPLE_BOTTOM'),
    ('HEAD_SHOULDERS','TOP'), ('HEAD_SHOULDERS','INVERSE'),
)
FRAMES=('M1','M5','M15','M30','H1','H4','D1','W1','MN1')
INSTRUMENTS={'EURUSD':(1.1,1.),'USDJPY':(147.,100.),'XAUUSD':(2600.,1500.),'BTCUSD':(65000.,100000.)}

def mirror(bars,center=1.101):
    return [replace(b,open=2*center-b.open,high=2*center-b.low,
                    low=2*center-b.high,close=2*center-b.close) for b in bars]

def triangle(variant):
    if variant=='SYMMETRIC':return lane('TRIANGLE')
    rows=[]
    for i in range(96):
        lo,hi=1.100+i*.000018,1.104
        v=lo+(hi-lo)*(1+math.sin(i*math.pi/6))/2
        rows.append(Bar(BASE+(i-96)*300,v-.000004,v+.000015,v-.000015,v,10))
    return mirror(rows) if variant=='DESCENDING' else rows

def geometry(family,variant):
    if family=='TRIANGLE':return triangle(variant)
    if family in ('FLAG','PENNANT'):return pole_pattern(family,1 if variant=='BULL' else -1)
    if family in ('CHANNEL','WEDGE'):
        b=lane(family);return mirror(b) if variant=='FALLING' else b
    if family in ('RANGE','BROADENING'):return lane(family)
    if family=='HEAD_SHOULDERS':return shaped([1.102,1.100,1.104,1.100,1.102],1 if variant=='TOP' else -1)
    values=[1.102,1.100,1.102] if variant.startswith('DOUBLE') else [1.102,1.100,1.102,1.100,1.102]
    return shaped(values,1 if variant.endswith('TOP') else -1)

def near_miss(family,variant):
    if family in ('TRIANGLE','WEDGE'):return lane('CHANNEL')
    if family=='FLAG':return lane('CHANNEL')
    if family=='PENNANT':return lane('TRIANGLE')
    if family in ('CHANNEL','RANGE'):return lane('BROADENING')
    if family=='BROADENING':return lane('TRIANGLE')
    side=-1 if variant.endswith('BOTTOM') or variant=='INVERSE' else 1
    if family=='HEAD_SHOULDERS':return shaped([1.102,1.100,1.102,1.100,1.102],side)
    return shaped([1.102,1.100,1.105] if variant.startswith('DOUBLE') else [1.102,1.100,1.105,1.100,1.107],side)

def timeframe(bars,tf):
    if tf=='MN1':
        end=2026*12+9
        times=[int(datetime((end-len(bars)+i)//12,(end-len(bars)+i)%12+1,1,tzinfo=timezone.utc).timestamp()) for i in range(len(bars))]
    elif tf=='W1':
        end=int(datetime(2026,10,5,tzinfo=timezone.utc).timestamp())
        times=[end-(len(bars)-i)*604800 for i in range(len(bars))]
    else:
        span=TF_SECONDS[tf];end=BASE//span*span
        times=[end-(len(bars)-i)*span for i in range(len(bars))]
    return [replace(b,time=t) for b,t in zip(bars,times)]

def prices(bars,symbol):
    origin,scale=INSTRUMENTS[symbol]
    def f(p):return origin+(p-1.1)*scale
    return [replace(b,open=f(b.open),high=f(b.high),low=f(b.low),close=f(b.close)) for b in bars]

def fixture(family,variant,tf='M5',symbol='EURUSD',negative=False):
    return prices(timeframe(near_miss(family,variant) if negative else geometry(family,variant),tf),symbol)

def live_after(bars,tf='M5'):
    now=bar_close_time(bars[-1].time,tf,bars[-1].clock_offset_seconds)
    b=bars[-1];c=b.close;distance=max((b.high-b.low)*.05,c*1e-8)
    return Bar(now,c,c+distance,c-distance,c,0,b.clock_offset_seconds),now
