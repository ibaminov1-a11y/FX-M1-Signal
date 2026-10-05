"""Causal, read-only chart geometry. It cannot create an execution candidate.

The existing detector supplies confirmed geometry. A single already observed
opposite extreme may complete a provisional drawing under the SAME geometric
checks. Neither predicted pivots nor future OHLC are used. Published dictionaries
are independent snapshots; mutable tracking belongs only to this catalog.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import OrderedDict
from ..model import atr, bar_close_time, live_structure, validate_bar_history, TF_SECONDS, Blocked
from .structure import causal_points, detect_patterns, _lanes, _reversals, value, live_geometry_valid

TITLES = {
    ('TRIANGLE','ASCENDING'):'Восходящий треугольник',
    ('TRIANGLE','DESCENDING'):'Нисходящий треугольник',
    ('TRIANGLE','SYMMETRIC'):'Симметричный треугольник',
    ('FLAG','BULL'):'Бычий флаг', ('FLAG','BEAR'):'Медвежий флаг',
    ('PENNANT','BULL'):'Бычий вымпел', ('PENNANT','BEAR'):'Медвежий вымпел',
    ('CHANNEL','RISING'):'Восходящий канал', ('CHANNEL','FALLING'):'Нисходящий канал',
    ('RANGE','HORIZONTAL'):'Прямоугольник',
    ('WEDGE','RISING'):'Восходящий клин', ('WEDGE','FALLING'):'Нисходящий клин',
    ('BROADENING','EXPANDING'):'Расширяющаяся формация',
    ('MULTI_EXTREME','DOUBLE_TOP'):'Двойная вершина',
    ('MULTI_EXTREME','TRIPLE_TOP'):'Тройная вершина',
    ('MULTI_EXTREME','DOUBLE_BOTTOM'):'Двойное дно',
    ('MULTI_EXTREME','TRIPLE_BOTTOM'):'Тройное дно',
    ('HEAD_SHOULDERS','TOP'):'Голова и плечи',
    ('HEAD_SHOULDERS','INVERSE'):'Перевёрнутые голова и плечи',
}


def _digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=True,allow_nan=False,
                                    separators=(',',':')).encode()).hexdigest()


def _symbol(value):
    return value.replace('/','').strip().upper()


def _provisional_patterns(rows, live, now, symbol, tf):
    points=causal_points(rows,tf)
    if not points or live is None:return []
    # live_structure includes a closing-price marker; it is never a pivot.
    overlay=live_structure(rows,live)
    if not overlay or overlay[0]['time']!=points[-1]['time']:return []
    candidates=[p for p in overlay if p.get('provisional') and p['kind'] in ('H','L')]
    if len(candidates)!=1:return []
    last=candidates[0]
    if last['time']<=points[-1]['time'] or last['time']>now or last['kind']==points[-1]['kind']:return []
    source=rows+[live]
    index=next((i for i,b in enumerate(source) if b.time==last['time']),None)
    if index is None or index==0:return []
    current,previous=source[index],source[index-1]
    # A candle making both a higher high and lower low does not provide their
    # order. Do not invent a swing ordering from that candle's OHLC.
    if current.high>previous.high and current.low<previous.low:return []
    point=dict(last,occurred_at=last['time'],available_at=now,observed_at=now,role=last['kind'])
    explicit=points+[point];a=atr(rows)
    raw=_lanes(rows,explicit,a,symbol,tf,when=now)+_reversals(explicit,a,symbol,tf)
    return [p for p in raw if p['anchors'][-1].get('provisional')
            and p['anchors'][-1]['time']==last['time'] and live_geometry_valid(p,now)]


def _anchor(point,role,rows,tf,now):
    provisional=bool(point.get('provisional'))
    available=None if provisional else point['available_at']
    return dict(time=point['time'],price=point['price'],kind=point['kind'],role=role,
                provisional=provisional,observed_at=min(now,point.get('observed_at',available or now)),
                confirmed_at=available)


def _segment(role,left,right,provisional=False):
    return dict(role=role,from_time=left['time'],from_price=left['price'],
                to_time=right['time'],to_price=right['price'],
                provisional=bool(provisional or left.get('provisional') or right.get('provisional')))


def _drawing(pattern,rows,tf,now,live):
    raw=pattern['anchors'];family=pattern['family'];anchors=[];segments=[]
    n=0;extreme='L' if pattern['variant'].endswith('BOTTOM') or pattern['variant']=='INVERSE' else 'H'
    for point in raw:
        role='TOUCH_HIGH' if point['kind']=='H' else 'TOUCH_LOW'
        if family=='HEAD_SHOULDERS':
            if point['kind']==extreme:
                role=('LEFT_SHOULDER','HEAD','RIGHT_SHOULDER')[n];n+=1
            else:role='NECK'
        elif family=='MULTI_EXTREME':
            if point['kind']==extreme:n+=1;role=('TOP' if extreme=='H' else 'BOTTOM')+str(n)
            else:role='NECK'
        anchors.append(_anchor(point,role,rows,tf,now))
    segments.extend(_segment('STRUCTURE',left,right) for left,right in zip(anchors,anchors[1:]))
    start=anchors[0]['time'];end=min(now,live.time if live is not None else rows[-1].time)
    provisional=any(a['provisional'] for a in anchors)
    if family in ('HEAD_SHOULDERS','MULTI_EXTREME'):
        neck=pattern['lower'] if extreme=='H' else pattern['upper']
        reactions=[a for a in anchors if a['role']=='NECK']
        # The neckline uses observed reactions, including a horizontal single
        # reaction for a double top/bottom. Its extension is a fitted boundary.
        segments.append(_segment('NECKLINE',dict(time=reactions[0]['time'],price=value(neck,reactions[0]['time'])),
                                 dict(time=end,price=value(neck,end))))
    else:
        for side,role in (('upper','UPPER'),('lower','LOWER')):
            line=pattern[side]
            segments.append(_segment(role,dict(time=start,price=value(line,start)),
                                     dict(time=end,price=value(line,end)),provisional))
    pole=pattern['measurements'].get('pole')
    if family in ('FLAG','PENNANT') and pole:
        indexed={b.time:b for b in rows}
        first,last=indexed[pole['start']],indexed[pole['end']]
        pole_anchors=[dict(time=first.time,price=first.open,kind='OPEN',role='POLE_START',provisional=False,
                           observed_at=bar_close_time(first.time,tf,first.clock_offset_seconds),
                           confirmed_at=bar_close_time(first.time,tf,first.clock_offset_seconds)),
                      dict(time=last.time,price=last.close,kind='CLOSE',role='POLE_END',provisional=False,
                           observed_at=bar_close_time(last.time,tf,last.clock_offset_seconds),
                           confirmed_at=bar_close_time(last.time,tf,last.clock_offset_seconds))]
        segments.insert(0,_segment('POLE',*pole_anchors));anchors=pole_anchors+anchors
        start=first.time
    return anchors,segments,start,end


class PatternCatalog:
    MAX_RECORDS=32

    def __init__(self):
        self._identity=None
        self._records=OrderedDict()
        self._closed=None
        self._detected=[]
        self._last_now=0

    def update(self,bars,live_bar,*,symbol,timeframe,mode,scope,clock_generation,now,scenarios):
        identity=(scope,_symbol(symbol),timeframe,mode,clock_generation)
        empty=dict(version=1,scope=scope,symbol=_symbol(symbol),timeframe=timeframe,mode=mode,
                   history_clock=clock_generation,data_asof=now,source_revision='',available=False,
                   reason='',patterns=[],branches=[])
        try:
            if not math.isfinite(now) or now<=0:raise ValueError('Некорректное время наблюдения')
            if timeframe not in TF_SECONDS:raise ValueError('Неизвестный период геометрии')
            rows=list(bars)[-1200:]
            if len(rows)<24:raise ValueError('Для геометрии нужны 24 закрытые свечи')
            validate_bar_history(rows,timeframe,now)
            if bar_close_time(rows[-1].time,timeframe,rows[-1].clock_offset_seconds)>now:
                raise ValueError('История содержит незакрытую свечу')
            if live_bar is not None:
                if live_bar.time<rows[-1].time or live_bar.time>now:
                    raise ValueError('Текущая свеча не соответствует времени наблюдения')
                if live_bar.time==rows[-1].time:live_bar=None
            key=[(b.time,b.open,b.high,b.low,b.close,b.clock_offset_seconds) for b in rows]
            live_key=None if live_bar is None else (live_bar.time,live_bar.open,live_bar.high,live_bar.low,live_bar.close)
            revision=_digest([identity,key,live_key])
            if identity!=self._identity or now<self._last_now:
                self._records.clear();self._closed=None;self._identity=identity
            self._last_now=now
            indexed={r[0]:r for r in key}
            changed=self._closed is not None and any(
                t in indexed and values!=indexed[t] for t,values in self._closed.items())
            if indexed!=self._closed:
                self._detected=detect_patterns(rows,symbol,timeframe,require_live_geometry=True)
                self._closed=indexed
            provisional=_provisional_patterns(rows,live_bar,now,symbol,timeframe)
            linked={}
            source_scenarios=scenarios.values() if isinstance(scenarios,dict) else scenarios
            for s in source_scenarios:
                p=s.get('pattern',{})
                if p.get('pattern_id') and s.get('scenario_id'):
                    linked.setdefault(p['pattern_id'],[]).append(s['scenario_id'])
            found=set();closures=[bar_close_time(b.time,timeframe,b.clock_offset_seconds) for b in rows]
            # Confirmed geometry takes precedence when an identical prefix is also
            # encountered by a provisional path. It is never downgraded to FORMING.
            for pattern in provisional+self._detected:
                pair=(pattern['family'],pattern['variant'])
                if pair not in TITLES:continue
                nodes=pattern['anchors'];is_forming=bool(nodes[-1].get('provisional'))
                prefix=[(a['time'],a['kind'],a['price']) for a in nodes[:-1]]
                view_id=_digest([identity,pair,prefix,nodes[-1]['kind']])[:24]
                prior=self._records.get(view_id)
                if prior and prior['geometry_state']=='DETECTED' and is_forming:continue
                anchors,segments,start,end=_drawing(pattern,rows,timeframe,now,live_bar)
                if not all(math.isfinite(s[k]) and s[k]>0 for s in segments for k in ('from_price','to_price')):continue
                first=prior['first_seen_at'] if prior else now
                confirmed=None if is_forming else (prior.get('confirmed_at') if prior and prior.get('confirmed_at') is not None else max(first,pattern['available_at']))
                record=dict(view_id=view_id,execution_pattern_id=None if is_forming else pattern['pattern_id'],
                    family=pair[0],variant=pair[1],title=TITLES[pair],
                    geometry_state='FORMING' if is_forming else 'DETECTED',first_seen_at=first,
                    confirmed_at=confirmed,updated_at=now,
                    reason='Последний экстремум предварительный; вход не разрешён' if is_forming else 'Геометрия найдена; подтверждение входа проверяется отдельно',
                    anchors=anchors,segments=segments,start_at=start,end_at=end,
                    scenario_ids=[] if is_forming else sorted(set(linked.get(pattern['pattern_id'],[]))),
                    quality_score=round(pattern['quality']*100,2),_geometry=pattern)
                self._records[view_id]=record;found.add(view_id)
            for view_id,record in list(self._records.items()):
                if record['start_at']<rows[0].time:
                    del self._records[view_id];continue
                if view_id in found:continue
                state=record['geometry_state'];geometry=record['_geometry']
                if state in ('INVALIDATED','EXPIRED'):continue
                if changed or not live_geometry_valid(geometry,now):
                    record.update(geometry_state='INVALIDATED',updated_at=now,
                                  reason='Исходная история изменена' if changed else 'Границы фигуры больше не образуют допустимую геометрию')
                elif state=='FORMING':
                    record.update(geometry_state='INVALIDATED',updated_at=now,reason='Предварительная геометрия больше не подтверждается наблюдаемыми точками')
                elif sum(t>geometry['available_at'] for t in closures)>8:
                    record.update(geometry_state='EXPIRED',updated_at=now,reason='Геометрия устарела; новый вход по ней не разрешён')
            ranked=sorted(self._records.values(),key=lambda p:(p['geometry_state'] in ('DETECTED','FORMING'),p['updated_at'],p['quality_score'],p['view_id']),reverse=True)
            self._records=OrderedDict((p['view_id'],p) for p in ranked[:self.MAX_RECORDS])
            public=[{k:copy.deepcopy(v) for k,v in p.items() if not k.startswith('_')} for p in self._records.values()]
            return dict(empty,available=True,source_revision=revision,patterns=public,
                        branches=branch_views(public,scenarios,rows,timeframe,live_bar.close if live_bar else rows[-1].close,now),
                        reason='' if public else 'Подходящая фигура по наблюдаемым точкам не найдена')
        except (ValueError,TypeError,KeyError,IndexError,ArithmeticError,Blocked) as exc:
            return dict(empty,reason=str(exc))


def display_outcome(scenario,bars,timeframe,now):
    """Read-only evidence summary. It never confirms a fill or changes a stage.

    Ordered terminal tick events are stronger evidence than aggregated bars.
    A bar straddling confirmation or both outcome levels cannot establish order.
    SELL targets are ASK-based in the engine: BID-only OHLC cannot prove them.
    """
    def result(status,when=None,source='NONE',reason='Нет наблюдаемого исхода'):
        return dict(status=status,evidence_time=when,source=source,reason=reason,execution_confirmed=False)
    status=scenario.get('status');confirmed=scenario.get('confirmed_at')
    if status=='EXPIRED':return result('EXPIRED',scenario.get('updated_at'),'SCENARIO_STATE',scenario.get('reason','Срок истёк'))
    if not confirmed:
        if status=='FAILED':return result('INVALIDATED',scenario.get('updated_at'),'SCENARIO_STATE',scenario.get('reason','Условие отмены выполнено'))
        return result('PENDING',reason='Ветка ещё не подтверждена; касания цели до входа не считаются результатом')
    events=[e for e in scenario.get('observed_events',[]) if confirmed<=e.get('time',0)<=now
            and e.get('event') in ('TARGET_REACHED','FAILED') and e.get('time_msc')]
    if events:
        first=min(events,key=lambda e:e['time_msc'])
        return result('TARGET_REACHED' if first['event']=='TARGET_REACHED' else 'INVALIDATED',
                      first['time'],'OBSERVED_TICK','Событие записано по наблюдавшейся котировке; не подтверждение сделки')
    if status=='FAILED':return result('INVALIDATED',scenario.get('updated_at'),'SCENARIO_STATE',scenario.get('reason','Ветка отменена'))
    side=scenario.get('side',0);target=scenario.get('target');cancel=scenario.get('invalidation')
    if side not in (-1,1) or not isinstance(cancel,(float,int)) or not math.isfinite(cancel):
        return result('UNKNOWN',reason='Нет проверенных уровней для оценки исхода')
    for bar in sorted(bars,key=lambda b:b.time):
        end=bar_close_time(bar.time,timeframe,bar.clock_offset_seconds)
        if end>now or end<=confirmed:continue
        target_hit=target is not None and (bar.high>=target if side>0 else bar.low<=target)
        cancel_hit=bar.low<=cancel if side>0 else bar.high>=cancel
        if not target_hit and not cancel_hit:continue
        if bar.time<confirmed or (target_hit and cancel_hit):
            return result('UNKNOWN',end,'CLOSED_BID_BAR','OHLC не устанавливает порядок подтверждения, цели и отмены')
        if side<0:
            return result('UNKNOWN',end,'CLOSED_BID_BAR','Для SELL необходимы наблюдения ASK; BID-свеча не доказывает исход исполнения')
        return result('TARGET_REACHED' if target_hit else 'INVALIDATED',end,'CLOSED_BID_BAR',
                      'Уровень наблюдался в закрытой BID-свече после подтверждения; это не подтверждение сделки')
    return result('PENDING')


def branch_views(patterns,scenarios,bars,timeframe,price,now):
    """All branches of displayed confirmed patterns, not only ranked trade picks."""
    from .lifecycle import remaining_path,next_requirement
    by_id={p['execution_pattern_id']:p for p in patterns if p.get('execution_pattern_id')}
    out=[];source=scenarios.values() if isinstance(scenarios,dict) else scenarios
    for s in source:
        pattern=by_id.get(s.get('pattern',{}).get('pattern_id'))
        if pattern is None:continue
        required=next_requirement(s,price,now,s['pattern']['atr'])
        fields=('scenario_id','pattern_id','title','type','side','status','stage','invalidation','target','target1','target2',
                'target1_source','target2_source','quality_score','reason','created_at','confirmed_at','updated_at','expires_at')
        record={k:copy.deepcopy(s[k]) for k in fields if k in s}
        record.update(view_id=pattern['view_id'],read_only=True,path=remaining_path(s,price,now),
                      event_level=required['level'],required_event=required['code'],next_event=required['text'],
                      display_outcome=display_outcome(s,bars,timeframe,now))
        out.append(record)
    return sorted(out,key=lambda s:(s.get('status') in ('FAILED','EXPIRED','TARGET_REACHED'),-s.get('quality_score',0),s['scenario_id']))[:192]
