"""Conditional event sequences. No target/retest is treated as already observed."""
from __future__ import annotations
import copy
import math
from .structure import value, causal_points

TERMINAL={'FAILED','EXPIRED','TARGET_REACHED'}
TITLES={
    'DIRECT_BREAKOUT':'Прямой пробой', 'BREAKOUT_RETEST':'Пробой с ретестом',
    'PULLBACK_RESUME':'Коррекция перед продолжением', 'FALSE_BREAK_RETURN':'Ложный выход и возврат',
    'RANGE_ROTATION':'Отбой внутри диапазона', 'CHANNEL_REJECTION':'Отбой от канала',
    'STRUCTURE_REVERSAL':'Подтверждение разворота структуры', 'COMPRESSION_WAIT':'Сжатие / ожидание выхода'}
FAMILY_TITLES={'TRIANGLE':'Треугольник','FLAG':'Флаг','PENNANT':'Вымпел','CHANNEL':'Канал',
              'RANGE':'Диапазон','WEDGE':'Клин','BROADENING':'Расширение',
              'MULTI_EXTREME':'Вершины / основания','HEAD_SHOULDERS':'Голова и плечи'}
NEXT={'WATCHING':'ждём новое событие у границы','BREAK_SEEN':'пробой наблюдался; ждём продолжение',
      'RETEST_SEEN':'ретест наблюдался; ждём новый микропробой','TOUCH_SEEN':'зона проверена; ждём реакцию',
      'RETURN_SEEN':'цена вернулась внутрь; ждём подтверждение отказа','CONFIRMED':'вход подтверждён',
      'FAILED':'условие отмены выполнено','EXPIRED':'время ожидания истекло','TARGET_REACHED':'цель достигнута'}


def _targets(p,bars,side,activation,a,rotation=False):
    if rotation:
        opposite=value(p['upper' if side>0 else 'lower'],bars[-1].time+300)
        near=(activation+opposite)/2
        return near,opposite,'CHANNEL_BOUNDARY','CHANNEL_BOUNDARY'
    points=causal_points(bars,p['timeframe'])
    eligible=sorted({x['price'] for x in points if x['kind']==('H' if side>0 else 'L')
                     and (x['price']-activation)*side>.25*a},reverse=side<0)
    if eligible:return eligible[0],eligible[1] if len(eligible)>1 else None,'HISTORICAL_LEVEL','HISTORICAL_LEVEL' if len(eligible)>1 else None
    pole=p['measurements'].get('pole')
    height=pole['height'] if pole and pole['side']==side else p['measurements']['width']
    return activation+side*height,None,'POLE_PROJECTION' if pole and pole['side']==side else 'PATTERN_MEASURED_MOVE',None


def create_scenarios(p,bars,a,current,now):
    family=p['family'];bias=p.get('bias',0);pad=.04*a
    sides=(bias,) if family in ('MULTI_EXTREME','HEAD_SHOULDERS') else (1,-1)
    specs=[]
    for side in sides:
        direct='STRUCTURE_REVERSAL' if family in ('MULTI_EXTREME','HEAD_SHOULDERS') else 'DIRECT_BREAKOUT'
        specs.extend([(direct,side,side),('BREAKOUT_RETEST',side,side),('FALSE_BREAK_RETURN',-side,side)])
    if family in ('RANGE','BROADENING'):
        specs.extend([('RANGE_ROTATION',1,1),('RANGE_ROTATION',-1,-1)])
    elif family=='CHANNEL':
        specs.append(('CHANNEL_REJECTION',bias,bias))
        specs.append(('PULLBACK_RESUME',bias,bias))
    elif family in ('FLAG','PENNANT') and bias:
        specs.append(('PULLBACK_RESUME',bias,bias))
    if family in ('TRIANGLE','PENNANT','WEDGE','RANGE','BROADENING'):
        specs.append(('COMPRESSION_WAIT',0,0))
    out=[]
    for typ,side,outside in specs:
        rotation=typ in ('RANGE_ROTATION','CHANNEL_REJECTION','PULLBACK_RESUME')
        boundary_key=('lower' if side>0 else 'upper') if rotation else ('upper' if outside>0 else 'lower')
        b=copy.deepcopy(p[boundary_key]);b['price']+=(side if rotation else outside)*pad
        activation=value(b,now)
        invalidation=value(p['lower' if side>0 else 'upper'],now)-side*.10*a if side else 0.
        if typ=='FALSE_BREAK_RETURN':invalidation=activation+outside*.25*a
        t1,t2,src1,src2=_targets(p,bars,side,activation,a,rotation or typ=='FALSE_BREAK_RETURN') if side else (None,None,None,None)
        ident=p['pattern_id']+'|'+typ+'|'+str(side)
        points=[dict(price=current,anchor='LIVE',label='LIVE')]
        if typ=='COMPRESSION_WAIT':points=[]
        elif rotation:
            points += [dict(price=activation,anchor='TOUCH',label='Проверка зоны?'),
                       dict(price=activation+side*.12*a,anchor='MICRO_CONFIRM',label='Реакция?')]
        elif typ=='FALSE_BREAK_RETURN':
            points += [dict(price=activation+outside*.08*a,anchor='BREAK',label='Выход?'),
                       dict(price=activation-outside*.10*a,anchor='RETURN',label='Возврат?')]
        else:
            points.append(dict(price=activation,anchor='TRIGGER',label='Пробой?'))
            if typ=='BREAKOUT_RETEST':
                points += [dict(price=activation+side*.12*a,anchor='BREAK',label='Выход?'),
                           dict(price=activation,anchor='TRIGGER_RETEST',label='Ретест?'),
                           dict(price=activation+side*.12*a,anchor='MICRO_CONFIRM',label='Подтверждение?')]
        if t1 is not None:points.append(dict(price=t1,anchor=src1,label='T1'))
        if t2 is not None:points.append(dict(price=t2,anchor=src2,label='T2'))
        for i,point in enumerate(points):
            point.update(step=i,minutes=15*i/max(1,len(points)-1),uncertainty=.12*a*math.sqrt(i),observed=i==0)
        out.append(dict(scenario_id=ident,scenario_version=1,pattern_id=p['pattern_id'],family=family,
            title=FAMILY_TITLES[family]+': '+TITLES[typ],type=typ,side=side,trade_side=side,terminal_bias=side,
            outside_side=outside,created_at=now,available_at=max(now,p['available_at']),updated_at=now,
            expires_at=now+max(300,min(7200,p['measurements']['duration']*1.5)),
            status='WATCHING',stage='WATCHING',boundary=b,activation=activation,invalidation=invalidation,
            target=t2 or t1,target1=t1,target2=t2,target_source=src2 or src1,target1_source=src1,target2_source=src2,
            path=points,pattern=copy.deepcopy(p),observed_events=[],geometry_score=p['quality'],
            quality_score=0.,model_weight=0.,calibrated_probability=None,entry_ready=False,
            event_id='',trigger=0.,sent=False,mfe=0.,mae=0.,confirmation_policy='OBSERVED_EVENT_AND_MICRO',
            next_event=NEXT['WATCHING'],reason='Структура распознана; условия входа ещё не выполнены'))
    return out


def _event(s,stage,q,now,reason):
    s['stage']=stage;s['updated_at']=now;s['reason']=reason;s['next_event']=NEXT.get(stage,reason)
    s['observed_events'].append(dict(event=stage,time=now,time_msc=q.time_msc,price=q.bid))
    if stage in TERMINAL:s['status']=stage;s['entry_ready']=False


def _cross(prev,q,line,side):
    if prev is None or q.time_msc<=prev.time_msc or side*(q.bid-prev.bid)<=0:return False
    # Compare both prices to the same current boundary as well as the prior boundary.
    # A moving trendline under an unchanged quote is never a price crossing.
    t=q.time_msc/1000;level=value(line,t)
    return side*(prev.bid-value(line,prev.time_msc/1000))<=0 and side*(prev.bid-level)<=0<side*(q.bid-level)


def _micro(s,m1,q,a,side):
    rows=[b for b in m1 if b.time+60<=q.time_msc/1000][-2:]
    if not rows:return None
    raw=max(b.high for b in rows) if side>0 else min(b.low for b in rows)
    return max(raw,q.bid+.03*a) if side>0 else min(raw,q.bid-.03*a)


def _confirm(s,q,now,trigger,a):
    side=s['side'];distance=(q.bid-trigger)*side
    if not 0<distance<=.25*a:
        _event(s,'EXPIRED',q,now,'Цена вне зоны входа; не догоняем');return
    s['status']='CONFIRMED';s['confirmed_at']=now;s['trigger']=trigger
    s['event_id']=s['scenario_id']+'|'+str(q.time_msc)
    s['entry_ready']=True;s['mark_at_confirmation']=q.bid if side>0 else q.ask
    _event(s,'CONFIRMED',q,now,'Наблюдаемые события подтвердили вход; проверяется исполнение')


def advance(s,q,prev,now,a,m1):
    s['entry_ready']=False
    if s['status'] in TERMINAL:return
    if now>s['expires_at']:
        _event(s,'EXPIRED',q,now,'Срок исходной гипотезы истёк');return
    side=s['side'];outside=s['outside_side'];typ=s['type'];stage=s['stage']
    boundary=value(s['boundary'],now)
    if s['status']=='CONFIRMED':
        mark=q.bid if side>0 else q.ask;origin=s['mark_at_confirmation']
        s['mfe']=max(s['mfe'],(mark-origin)*side);s['mae']=min(s['mae'],(mark-origin)*side)
        if (mark-s['invalidation'])*side<=0:
            _event(s,'FAILED',q,now,'Выполнено условие отмены сценария');return
        if s['target1'] is not None and (mark-s['target1'])*side>=0 and not s.get('target1_reached'):
            s['target1_reached']=True;s['observed_events'].append(dict(event='T1',time=now,price=mark))
        if s['target'] is not None and (mark-s['target'])*side>=0:
            _event(s,'TARGET_REACHED',q,now,'Целевая зона достигнута');return
        s['entry_ready']=bool(not s['sent'] and prev is not None and now-s['confirmed_at']<=10
                              and 0<(q.bid-s['trigger'])*side<=.25*a)
        return
    if prev is None or q.time_msc<=prev.time_msc:return
    if q.time_msc-prev.time_msc>10000:
        if stage!='WATCHING':_event(s,'EXPIRED',q,now,'Разрыв данных: прежнее подтверждение больше не используется')
        return
    if typ=='COMPRESSION_WAIT':
        p=s['pattern']
        if q.bid>value(p['upper'],now)+.1*a or q.bid<value(p['lower'],now)-.1*a:
            _event(s,'FAILED',q,now,'Сжатие завершилось выходом; проверяется отдельная ветка')
        return
    if typ!='FALSE_BREAK_RETURN' and (q.bid-s['invalidation'])*side<=0:
        _event(s,'FAILED',q,now,'Цена нарушила противоположную опору');return
    if typ in ('DIRECT_BREAKOUT','STRUCTURE_REVERSAL'):
        if stage=='WATCHING' and _cross(prev,q,s['boundary'],side):
            s['break_price']=q.bid;s['break_trigger']=boundary
            _event(s,'BREAK_SEEN',q,now,'Выход наблюдался; требуется ещё один направленный тик')
        elif stage=='BREAK_SEEN':
            if (q.bid-boundary)*side<=0:_event(s,'FAILED',q,now,'Пробой не удержался')
            elif (q.bid-s['break_price'])*side>0:_confirm(s,q,now,s['break_trigger'],a)
    elif typ=='BREAKOUT_RETEST':
        if stage=='WATCHING' and _cross(prev,q,s['boundary'],side):
            s['break_at']=now;s['break_price']=q.bid
            _event(s,'BREAK_SEEN',q,now,'Пробой состоялся; сценарий требует возврата к границе')
        elif stage=='BREAK_SEEN':
            if now-s['break_at']>600:_event(s,'EXPIRED',q,now,'Ретест не состоялся в отведённое окно')
            elif abs(q.bid-boundary)<=.10*a and (q.bid-prev.bid)*side<0:
                micro=_micro(s,m1,q,a,side)
                if micro is not None:
                    s['micro_trigger']=micro;_event(s,'RETEST_SEEN',q,now,'Возврат к границе наблюдался; ждём новый микропробой')
        elif stage=='RETEST_SEEN':
            t=s['micro_trigger']
            if _cross(prev,q,dict(t0=now,price=t,slope=0.),side):_confirm(s,q,now,t,a)
    elif typ=='FALSE_BREAK_RETURN':
        if stage=='WATCHING' and _cross(prev,q,s['boundary'],outside):
            s['false_extreme']=q.bid;s['break_at']=now
            _event(s,'BREAK_SEEN',q,now,'Выход наблюдался; отказ ещё не подтверждён')
        elif stage=='BREAK_SEEN':
            if (q.bid-s['false_extreme'])*outside>0:s['false_extreme']=q.bid
            if (q.bid-boundary)*outside>.65*s['pattern']['measurements']['width']:
                _event(s,'FAILED',q,now,'Выход продолжился; гипотеза ложного пробоя отменена')
            elif (q.bid-boundary)*outside<-.08*a and (q.bid-prev.bid)*outside<0:
                s['micro_trigger']=q.bid+side*.04*a
                s['invalidation']=s['false_extreme']+outside*.10*a
                _event(s,'RETURN_SEEN',q,now,'Возврат внутрь наблюдался; требуется продолжение отказа')
        elif stage=='RETURN_SEEN':
            if (q.bid-s['invalidation'])*side<=0:_event(s,'FAILED',q,now,'Ложный выход не подтверждён')
            elif _cross(prev,q,dict(t0=now,price=s['micro_trigger'],slope=0.),side):
                _confirm(s,q,now,s['micro_trigger'],a)
    else:  # Range/channel rejection and a real pullback before continuation.
        if stage=='WATCHING' and abs(q.bid-boundary)<=.12*a and (q.bid-prev.bid)*side<0:
            micro=_micro(s,m1,q,a,side)
            if micro is not None:
                s['micro_trigger']=micro;_event(s,'TOUCH_SEEN',q,now,'Зона действительно проверена; ждём реакцию и микропробой')
        elif stage=='TOUCH_SEEN' and _cross(prev,q,dict(t0=now,price=s['micro_trigger'],slope=0.),side):
            _confirm(s,q,now,s['micro_trigger'],a)


def remaining_path(s,current):
    """Only unresolved conditional events remain to the right of LIVE."""
    if s['status'] in TERMINAL or s['type']=='COMPRESSION_WAIT':return []
    pts=copy.deepcopy(s['path'])
    if s['status']=='CONFIRMED':pts=[p for p in pts if p.get('label') in ('T1','T2') and not (p.get('label')=='T1' and s.get('target1_reached'))]
    elif s['stage'] in ('RETEST_SEEN','TOUCH_SEEN','RETURN_SEEN'):
        index=next((i for i,p in enumerate(pts) if p['anchor'] in ('TRIGGER_RETEST','TOUCH','RETURN')),0)
        pts=pts[index+1:]
    elif s['stage']=='BREAK_SEEN':
        index=next((i for i,p in enumerate(pts) if p['anchor'] in ('BREAK','TRIGGER')),0)
        pts=pts[index+1:]
    else:pts=pts[1:]
    pts.insert(0,dict(price=current,anchor='LIVE',label='LIVE',uncertainty=0,observed=True))
    for i,p in enumerate(pts):p.update(step=i,minutes=15*i/max(1,len(pts)-1))
    return pts
