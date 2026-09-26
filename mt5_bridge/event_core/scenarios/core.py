"""Explainable pattern -> event sequence -> candidate decision.

This calculator cannot send orders. Engine remains the single execution owner.
Snapshot identity changes with input; archived snapshots change only on meaningful
structural/event transitions and never replace previously saved expectations.
"""
from __future__ import annotations
import copy
import hashlib
import json
from ..model import Config, Decision, atr, ordered, pivots, direction, swing_labels, TF_SECONDS
from .structure import detect_patterns, value, FAMILIES
from .lifecycle import create_scenarios, advance, remaining_path, TERMINAL, NEXT


class ScenarioCore:
    MAX_CHASE_ATR=.25
    VERSION='SCENARIO_V2.1'
    def __init__(self,config:Config,saved=None):
        self.config=config;saved=saved or {}
        self.scenarios=copy.deepcopy(saved.get('scenarios',{}))
        self.known=set(saved.get('known',[]));self.consumed=set(saved.get('consumed',[]))
        self.previous_quote=None;self.frame=None;self.snapshots={};self.archive_key=None
        self.pending_snapshots=[];self.events=[];self.last_forecast={}
        # Observation evidence is not an executable order after process restart.
        for s in self.scenarios.values():
            s['entry_ready']=False
            if s['status'] not in TERMINAL and not s.get('sent'):
                s['status']='WATCHING';s['stage']='WATCHING';s['event_id']=''
                s['reason']='Bridge перезапущен; требуется новое наблюдаемое событие'
    def state(self):
        return dict(scenarios=copy.deepcopy(self.scenarios),known=sorted(self.known)[-8192:],consumed=sorted(self.consumed)[-4096:])
    def clear(self):
        self.suspend()
    def suspend(self):
        self.previous_quote=None
        for s in self.scenarios.values():
            s['entry_ready']=False
            if s['status'] not in TERMINAL and not s.get('sent') and s['stage']!='WATCHING':
                s['status']='EXPIRED';s['stage']='EXPIRED';s['reason']='Наблюдение прервано; старый вход отменён'

    def consume(self,event_id):
        if not event_id:return
        selected=next((s for s in self.scenarios.values() if s.get('event_id')==event_id),None)
        self.consumed.add(event_id)
        if selected:
            for s in self.scenarios.values():
                if s['status']=='CONFIRMED' and s['side']==selected['side'] and abs(s['trigger']-selected['trigger'])<=selected['pattern']['atr']*.10:
                    s['sent']=True;s['entry_ready']=False
                    if s['event_id']:self.consumed.add(s['event_id'])
        if len(self.consumed)>4096:self.consumed=set(sorted(self.consumed)[-4096:])
    def _rank(self,rows,m15,h1,now,q,a):
        contexts=[direction(pivots(b)) if len(b)>12 else 0 for b in (m15,h1)]
        progress={'WATCHING':.10,'BREAK_SEEN':.45,'TOUCH_SEEN':.60,'RETURN_SEEN':.70,'RETEST_SEEN':.75,'CONFIRMED':1.}
        for s in rows:
            side=s['side'];reversal=s['type'] in ('FALSE_BREAK_RETURN','STRUCTURE_REVERSAL')
            alignment=sum(1 if x==side else .5 if x==0 else 0 for x in contexts)/2 if side else .5
            if reversal:alignment=max(.5,alignment)  # Old trend opposition alone cannot veto a confirmed reversal structure.
            freshness=max(0.,1-(now-s['created_at'])/max(1,s['expires_at']-s['created_at']))
            parts=dict(geometry=s['geometry_score'],context=alignment,event=progress.get(s['stage'],0),freshness=freshness)
            score=35*parts['geometry']+25*parts['context']+25*parts['event']+15*parts['freshness']
            s['score_components']=parts;s['quality_score']=round(score,2);s['model_weight']=round(score/100,4)
        rows.sort(key=lambda s:(s['quality_score'],s['created_at'],s['scenario_id']),reverse=True)
        unique=[]
        for s in rows:
            # Same event family and same price zone is one explanation, not extra votes.
            if any(x['type']==s['type'] and x['side']==s['side'] and abs(x['activation']-s['activation'])<=.15*a for x in unique):continue
            unique.append(s)
        selected=[]
        for s in unique:
            if any(x['type']==s['type'] and x['side']==s['side'] for x in selected):continue
            selected.append(s)
            if len(selected)==4:break
        return selected,unique
    def evaluate(self,bars,m1,m15,h1,live_bar,q,now,campaign_side=0):
        q.validate(now);ordered(bars)
        if self.config.timeframe!='M5' or len(bars)<24 or len(m1)<2 or live_bar is None:
            return Decision(phase='DATA_BLOCK',reason='Scenario V2: ожидаем закрытые M1/M5 и LIVE',path='SCENARIO_V2')
        span=TF_SECONDS[self.config.timeframe]
        if bars[-1].time+span>now+1:raise ValueError('Будущая незакрытая свеча в Scenario V2')
        a=atr(bars);frame=(bars[-1].time,bars[-1].high,bars[-1].low,bars[-1].close)
        if frame!=self.frame:
            for p in detect_patterns(bars,self.config.symbol,self.config.timeframe):
                for s in create_scenarios(p,bars,a,q.bid,now):
                    key=s['scenario_id']
                    if key not in self.known:
                        self.scenarios[key]=s;self.known.add(key)
                        self.events.append(dict(scenario_id=key,type=s['type'],side=s['side'],status='WATCHING',stage='WATCHING',reason=s['title'],time=now))
            self.frame=frame
        prev=self.previous_quote
        # Identical quotes do not arm/confirm anything. Missing/rewound time resets observation.
        if prev is not None and (q.time_msc<prev.time_msc or q.time_msc-prev.time_msc>10000):
            self.suspend();prev=None
        for s in self.scenarios.values():
            before=(s['status'],s['stage'])
            advance(s,q,prev,now,a,m1)
            if before!=(s['status'],s['stage']):
                self.events.append(dict(scenario_id=s['scenario_id'],type=s['type'],side=s['side'],
                    status=s['status'],stage=s['stage'],reason=s['reason'],time=now))
        self.previous_quote=q
        active=[s for s in self.scenarios.values() if s['status'] not in TERMINAL]
        selected,ranked=self._rank(active,m15,h1,now,q,a)
        routes=[]
        for i,s in enumerate(selected):
            item=copy.deepcopy(s);item['name']='PRIMARY' if i==0 else 'ALT'+str(i)
            item['path']=remaining_path(s,q.bid);item['activation']=value(s['boundary'],now)
            item['next_event']=NEXT.get(s['stage'],s['reason']);routes.append(item)
        recent=bars[-24:]
        support=min(b.low for b in recent);resistance=max(b.high for b in recent)
        if routes:
            p=routes[0]['pattern'];support=value(p['lower'],now);resistance=value(p['upper'],now)
        entries=dict(BUY=dict(trigger=resistance+.04*a,invalidation=support-.10*a),
                     SELL=dict(trigger=support-.04*a,invalidation=resistance+.10*a))
        sigdata=[q.time_msc,q.bid,q.ask,frame,[(s['scenario_id'],s['status'],s['stage']) for s in selected]]
        snapshot=hashlib.sha256(json.dumps(sigdata,sort_keys=True).encode()).hexdigest()[:24]
        forecast=dict(map_version=3,available=True,engine=self.VERSION,side=routes[0]['side'] if routes else 0,
            confidence=routes[0]['model_weight'] if routes else 0.,live_price=q.bid,data_asof=q.time_msc/1000,
            snapshot_id=snapshot,support=support,resistance=resistance,entry_levels=entries,
            scenarios=routes,selection=[s['scenario_id'] for s in selected],candidate_count=len(ranked),
            model_weight_kind='UNCALIBRATED_SCORE',path_time_kind='EVENT_STAGES_NOT_ETA',
            uncertainty_kind='ATR_SCALE_NOT_CONFIDENCE_INTERVAL',range_weight=0.,projection=[],
            capabilities=dict(structural_families=list(FAMILIES),independent_event_paths=True,
                immutable_snapshots=True,live_and_history=True,wave_module=False),
            score_version='35G+25C+25E+15R-v1',regime=routes[0]['family'] if routes else 'NO_CLEAR_SCENARIO',
            reason=routes[0]['reason'] if routes else 'Нет ясной подтверждённой геометрии — только уровни и WAIT')
        archive_key=(frame,tuple(sorted((s['scenario_id'],s['status'],s['stage']) for s in self.scenarios.values())))
        if archive_key!=self.archive_key:
            frozen=dict(snapshot_id=snapshot,forecast=copy.deepcopy(forecast),bars=[b.__dict__.copy() for b in bars[-120:]],
                        scenario_states=[dict(scenario_id=s['scenario_id'],type=s['type'],status=s['status'],stage=s['stage']) for s in self.scenarios.values()],
                        symbol=self.config.symbol,timeframe=self.config.timeframe,data_asof=now)
            self.snapshots[snapshot]=frozen;self.pending_snapshots.append(frozen);self.archive_key=archive_key
            if len(self.snapshots)>64:self.snapshots.pop(next(iter(self.snapshots)))
        self.last_forecast=copy.deepcopy(forecast)
        # Retain audit records in Store; bounded in-memory index prevents indefinite growth.
        if len(self.scenarios)>192:
            closed=sorted((s for s in self.scenarios.values() if s['status'] in TERMINAL),key=lambda x:x['created_at'])
            for s in closed[:len(self.scenarios)-192]:self.scenarios.pop(s['scenario_id'],None)
        ready=[s for s in ranked if s['entry_ready'] and s['event_id'] not in self.consumed]
        for s in ready:
            side=s['side'];trigger=s['trigger'];stop=s['invalidation']
            if (q.bid-trigger)*side<=0 or abs(q.bid-trigger)>.25*a:continue
            # A high score never waives a fresh spread/no-chase/risk check in Engine.
            forecast['entry_scenario_id']=s['scenario_id'];forecast['entry_scenario_version']=s['scenario_version']
            forecast['entry_type']=s['type']
            levels=({'kind':'trigger','price':trigger},{'kind':'invalidation','price':stop})
            return Decision('BUY' if side>0 else 'SELL','ENTRY_READY',s['title']+' — события подтверждены',
                s['event_id'],side,stop,trigger,stop,a,q.time_msc,levels,path='SCENARIO_V2',
                structure=swing_labels(bars),forecast=forecast,entry_class='CONFIRMED')
        reason=(routes[0]['title']+'; '+routes[0]['next_event']) if routes else forecast['reason']
        return Decision(reason=reason,atr=a,path='SCENARIO_V2',structure=swing_labels(bars),forecast=forecast)
