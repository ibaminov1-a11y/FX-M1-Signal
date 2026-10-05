"""Explainable pattern -> event sequence -> candidate decision.

This calculator cannot send orders. Engine remains the single execution owner.
Snapshot identity changes with input; archived snapshots change only on meaningful
structural/event transitions and never replace previously saved expectations.
"""
from __future__ import annotations
import copy
import hashlib
import json
from ..model import Config, Decision, atr, ordered, pivots, direction, swing_labels, TF_SECONDS, bar_close_time
from .structure import detect_patterns, value, FAMILIES, live_geometry_valid
from .continuation import Continuation
from .scalp import ScalpMicro
from ..price_forecast import PriceForecaster
from .pattern_view import PatternCatalog, display_outcome
from .lifecycle import create_scenarios, advance, remaining_path, TERMINAL, NEXT, next_requirement


class ScenarioCore:
    MAX_CHASE_ATR=.25
    VERSION='SCENARIO_V2.2'
    def __init__(self,config:Config,saved=None):
        self.config=config;saved=saved or {}
        self.scenarios=copy.deepcopy(saved.get('scenarios',{}))
        self.known=set(saved.get('known',[]));self.consumed=set(saved.get('consumed',[]))
        self.previous_quote=None;self.frame=None;self.snapshots={};self.archive_key=None
        self.pending_snapshots=[];self.events=[];self.last_forecast={}
        self.continuation=Continuation()
        self.micro=ScalpMicro(config)
        self.price_forecaster=PriceForecaster()
        self.pattern_catalog=PatternCatalog()
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
        self.continuation.reset()
        self.micro.reset()
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
    def _rank(self,rows,m15,h1,now,q,a,context=None):
        contexts=[direction(pivots(b)) if len(b)>12 else 0 for b in ((m15,h1) if context is None else (context,))]
        progress={'WATCHING':.10,'BREAK_SEEN':.45,'TOUCH_SEEN':.60,'RETURN_SEEN':.70,'RETEST_SEEN':.75,'CONFIRMED':1.}
        for s in rows:
            side=s['side'];reversal=s['type'] in ('FALSE_BREAK_RETURN','STRUCTURE_REVERSAL')
            alignment=sum(1 if x==side else .5 if x==0 else 0 for x in contexts)/len(contexts) if side else .5
            if reversal:alignment=max(.5,alignment)  # Old trend opposition alone cannot veto a confirmed reversal structure.
            freshness=max(0.,1-(now-s['created_at'])/max(1,s['expires_at']-s['created_at']))
            parts=dict(geometry=s['geometry_score'],context=alignment,event=progress.get(s['stage'],0),freshness=freshness)
            score=35*parts['geometry']+25*parts['context']+25*parts['event']+15*parts['freshness']
            s['score_components']=parts;s['quality_score']=round(score,2);s['model_weight']=round(score/100,4)
        # Keep ordering deterministic for display, but never claim a primary on a score tie.
        rows.sort(key=lambda s:(-s['quality_score'],-s['created_at'],s['type'],s['side'],s['scenario_id']))
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
    def evaluate(self,bars,m1,m15,h1,live_bar,q,now,campaign_side=0,campaign=None,context=None,context_tf=None,clock_generation='UTC_NATIVE_R51',market_scope=''):
        q.validate(now);ordered(bars)
        if self.config.timeframe not in TF_SECONDS or len(bars)<24 or len(m1)<2 or live_bar is None:
            return Decision(phase='DATA_BLOCK',reason=f'Scenario V2: ожидаем закрытые M1/{self.config.timeframe} и LIVE',path='SCENARIO_V2')
        if bar_close_time(bars[-1].time,self.config.timeframe,bars[-1].clock_offset_seconds)>now+1:raise ValueError('Будущая незакрытая свеча в Scenario V2')
        a=atr(bars);frame=(bars[-1].time,bars[-1].high,bars[-1].low,bars[-1].close)
        normal=self.config.mode=='NORMAL'
        if frame!=self.frame:
            for p in detect_patterns(bars,self.config.symbol,self.config.timeframe,require_live_geometry=normal):
                if normal and not live_geometry_valid(p,q.time_msc/1000.0):continue
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
            advance(s,q,prev,now,a,m1,validate_geometry=normal)
            if before!=(s['status'],s['stage']):
                self.events.append(dict(scenario_id=s['scenario_id'],type=s['type'],side=s['side'],
                    status=s['status'],stage=s['stage'],reason=s['reason'],time=now,retirement_code=s.get('retirement_code','')))
        self.previous_quote=q
        source=self.scenarios.get(campaign.get('scenario_id')) if campaign else None
        r7=self.config.runtime_model=='R7'
        fast=r7 or (self.config.mode=='SCALP' and self.config.timeframe=='M1')
        addition=(self.micro.observe(self.config.symbol,bars if r7 else context or [],context if r7 else m15,q,now,a,campaign,source,campaign_side,self.config.dynamic_adds)
                  if fast else self.continuation.observe(campaign,source,q,now,a,self.config.mode))
        if addition:
            self.scenarios[addition['scenario_id']]=addition;self.known.add(addition['scenario_id'])
            self.events.append(dict(scenario_id=addition['scenario_id'],type=addition['type'],side=addition['side'],
                status='CONFIRMED',stage='CONFIRMED',reason=addition['reason'],time=now))
        active=[s for s in self.scenarios.values() if s['status'] not in TERMINAL]
        preview=self.micro.preview() if fast else None
        if preview and not any(s['scenario_id']==preview['scenario_id'] for s in active):active.append(preview)
        selected,ranked=self._rank(active,m15,h1,now,q,a,context=None if self.config.timeframe=='M5' else context)
        if normal:
            # Keep execution candidates ranked independently of presentation (HF1).
            # A sent trade or its micro-add can outlive its historical trendlines;
            # show the frozen active trade plan, not an inverted old figure.
            visible=[s for s in active if live_geometry_valid(s['pattern'],q.time_msc/1000.0)]
            selected,_=self._rank(visible,m15,h1,now,q,a,context=None if self.config.timeframe=='M5' else context)
        if preview:selected=[preview]+[s for s in selected if s['scenario_id']!=preview['scenario_id']][:3]
        tied=len(selected)>1 and int(selected[0]['quality_score']+.5)==int(selected[1]['quality_score']+.5)
        if preview:tied=False
        selection_status='TIED' if tied else 'PREFERRED' if selected else 'NONE'
        price_time=q.time_msc/1000.0
        routes=[]
        for i,s in enumerate(selected):
            item=copy.deepcopy(s);item['name']=('OPTION'+str(i+1)) if tied else ('PRIMARY' if i==0 else 'ALT'+str(i))
            item['path']=remaining_path(s,q.bid,price_time);item['activation']=value(s['boundary'],price_time)
            requirement=next_requirement(s,q.bid,price_time,a)
            item['required_event']=requirement['code'];item['event_level']=requirement['level']
            item['next_event']=requirement['text'];item['initial_activation']=s.get('initial_activation',s['activation'])
            item['boundary_asof']=price_time
            item['display_outcome']=display_outcome(s,bars,self.config.timeframe,price_time)
            routes.append(item)
        recent=bars[-24:]
        support=min(b.low for b in recent);resistance=max(b.high for b in recent)
        if routes:
            p=routes[0]['pattern'];support=value(p['lower'],price_time);resistance=value(p['upper'],price_time)
        entries=dict(BUY=dict(trigger=resistance+.04*a,invalidation=support-.10*a),
                     SELL=dict(trigger=support-.04*a,invalidation=resistance+.10*a))
        sigdata=[q.time_msc,q.bid,q.ask,frame,[(s['scenario_id'],s['status'],s['stage']) for s in selected]]
        snapshot=hashlib.sha256(json.dumps(sigdata,sort_keys=True).encode()).hexdigest()[:24]
        forecast=dict(map_version=3,available=True,timeframe=self.config.timeframe,engine=self.VERSION,side=routes[0]['side'] if routes and not tied else 0,
            selection_status=selection_status,selection_reason='Равнозначные гипотезы — предпочтение не определено' if tied else '',
            primary_scenario_id=routes[0]['scenario_id'] if routes and not tied else None,
            history_clock=clock_generation,boundary_asof=price_time,context_timeframe=context_tf,
            confidence=routes[0]['model_weight'] if routes else 0.,live_price=q.bid,data_asof=q.time_msc/1000,
            addition=self.continuation.status() if campaign else None,
            snapshot_id=snapshot,support=support,resistance=resistance,entry_levels=entries,
            scenarios=routes,selection=[s['scenario_id'] for s in selected],candidate_count=len(ranked),
            model_weight_kind='UNCALIBRATED_SCORE',path_time_kind='EVENT_STAGES_NOT_ETA',
            uncertainty_kind='ATR_SCALE_NOT_CONFIDENCE_INTERVAL',range_weight=0.,projection=[],
            capabilities=dict(structural_families=list(FAMILIES),independent_event_paths=True,
                immutable_snapshots=True,live_and_history=True,wave_module=False),
            score_version='35G+25C+25E+15R-v1',regime=routes[0]['family'] if routes else 'NO_CLEAR_SCENARIO',
            reason=routes[0]['reason'] if routes else 'Нет ясной подтверждённой геометрии — только уровни и WAIT')
        forecast['price_forecast']=self.price_forecaster.update(bars,q,now,
            symbol=self.config.symbol,timeframe=self.config.timeframe,mode=self.config.mode,
            scope=market_scope or clock_generation)
        if fast:
            forecast['execution_setup']=self.micro.status()
            forecast['addition']=self.micro.status() if campaign else None
        forecast['pattern_chart']=self.pattern_catalog.update(bars,live_bar,
            symbol=self.config.symbol,timeframe=self.config.timeframe,mode=self.config.mode,
            scope=market_scope or clock_generation,clock_generation=clock_generation,now=price_time,scenarios=self.scenarios)
        patterns=forecast['pattern_chart'].get('patterns',[])
        # Record emergence/confirmation/retirement, not a database copy on each
        # changing provisional price. Entry snapshots remain frozen separately.
        geometry_key=tuple((p['view_id'],p['geometry_state']) for p in patterns)
        archive_key=(frame,tuple(sorted((s['scenario_id'],s['status'],s['stage']) for s in self.scenarios.values())),geometry_key)
        if archive_key!=self.archive_key:
            start=min((p['start_at'] for p in patterns),default=bars[-min(120,len(bars))].time)
            archive_bars=[b for b in bars[-1200:] if b.time>=min(start,bars[-min(120,len(bars))].time)]
            frozen=dict(snapshot_id=snapshot,forecast=copy.deepcopy(forecast),bars=[b.__dict__.copy() for b in archive_bars],
                        scenario_states=[dict(scenario_id=s['scenario_id'],type=s['type'],status=s['status'],stage=s['stage']) for s in self.scenarios.values()],
                        symbol=self.config.symbol,timeframe=self.config.timeframe,data_asof=now)
            self.snapshots[snapshot]=frozen;self.pending_snapshots.append(frozen);self.archive_key=archive_key
            if len(self.snapshots)>64:self.snapshots.pop(next(iter(self.snapshots)))
        self.last_forecast=copy.deepcopy(forecast)
        # Retain audit records in Store; bounded in-memory index prevents indefinite growth.
        if len(self.scenarios)>192:
            closed=sorted((s for s in self.scenarios.values() if s['status'] in TERMINAL),key=lambda x:x['created_at'])
            for s in closed[:len(self.scenarios)-192]:self.scenarios.pop(s['scenario_id'],None)
        # Display deduplication must not hide a confirmed NORMAL entry behind
        # a higher-ranked waiting/used hypothesis. _rank sorted active in place;
        # keep that order and leave both SCALP paths and execution guards intact.
        execution_pool=active if self.config.mode=='NORMAL' else ranked
        ready=[s for s in execution_pool if s['entry_ready'] and s['event_id'] not in self.consumed]
        if fast and (not r7 or self.config.mode=='SCALP'):
            ready=[s for s in self.scenarios.values() if s.get('micro') and s['entry_ready']
                   and s['event_id'] not in self.consumed and preview is s and self.micro.stage=='CONFIRMED']
        for s in ready:
            side=s['side'];trigger=s['trigger'];stop=s['invalidation']
            if (q.bid-trigger)*side<=0 or abs(q.bid-trigger)>.25*a:continue
            # A high score never waives a fresh spread/no-chase/risk check in Engine.
            forecast['entry_scenario_id']=s['scenario_id'];forecast['entry_scenario_version']=s['scenario_version']
            forecast['entry_type']=s['type']
            forecast['entry_target1']=s.get('target1')
            levels=({'kind':'trigger','price':trigger},{'kind':'invalidation','price':stop})
            return Decision('BUY' if side>0 else 'SELL','ENTRY_READY',s['title']+' — события подтверждены',
                s['event_id'],side,stop,trigger,stop,a,q.time_msc,levels,path='SCENARIO_V2',
                structure=swing_labels(bars),forecast=forecast,entry_class='CONFIRMED')
        reason=(('Равнозначные гипотезы; ' if tied else '')+routes[0]['title']+'; '+routes[0]['next_event']) if routes else forecast['reason']
        if campaign:reason=self.continuation.reason+'; '+reason
        if fast:reason=self.micro.reason.replace('SCALP M1',self.config.mode+' '+self.config.timeframe)
        return Decision(reason=reason,atr=a,path='SCENARIO_V2',structure=swing_labels(bars),forecast=forecast)
