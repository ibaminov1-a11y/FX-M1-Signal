"""Prospective, fixed boundary plans; numerical research rules, not probabilities.

The closed-bar range fixes price levels/targets/expiry once. Live quotes may
confirm or invalidate the plan, never move its goalposts. A restart/feed gap
keeps the explanatory levels but discards all unexecuted entry permission.
"""
from __future__ import annotations
import copy,hashlib,math
from ..model import TF_SECONDS,bar_close_time
from .lifecycle import TERMINAL

class StablePlans:
    VERSION='STABLE_V1'
    def __init__(self,config,saved=None):
        self.config=config;self.previous=None;self.frame=(saved or {}).get('frame')
        self.plans=copy.deepcopy((saved or {}).get('plans',{}));self.event_count=int((saved or {}).get('event_count',0))
        for s in self.plans.values():
            s['entry_ready']=False
            if not s.get('sent') and s['status'] not in TERMINAL:
                s['stage']='WATCHING';s['status']='WATCHING';s['observed_events']=[];s['event_id']=''
                s['reason']='План сохранён; после перезапуска нужна новая проверка зоны'
    def state(self):return dict(plans=copy.deepcopy(self.plans),event_count=self.event_count,frame=self.frame)
    def suspend(self):
        self.previous=None
        for s in self.plans.values():
            s['entry_ready']=False
            if not s.get('sent') and s['status'] not in TERMINAL:
                s.update(stage='WATCHING',status='WATCHING',event_id='',observed_events=[],reason='Наблюдение прервано; ждём новую проверку фиксированной зоны')
    def consume(self,event_id):
        matched=next((s for s in self.plans.values() if s.get('event_id')==event_id),None)
        if not matched:return
        matched['sent']=True;matched['entry_ready']=False
        for s in self.plans.values():
            if s is not matched and not s.get('sent') and s['status'] not in TERMINAL:
                s.update(status='EXPIRED',stage='EXPIRED',entry_ready=False,reason='Исполнена другая ветка; отдельный вход отменён')
    def _prepare(self,bars,q,now,a):
        if len(bars)<24 or not math.isfinite(a) or a<=0:return
        if bar_close_time(bars[-1].time,self.config.timeframe,bars[-1].clock_offset_seconds)>now+1:return
        low=min(b.low for b in bars[-12:]);high=max(b.high for b in bars[-12:]);width=high-low
        if width<max(1.4*a,8*q.spread) or width>12*a:return
        self.frame=bars[-1].time
        duration=min(10800,max(900,TF_SECONDS[self.config.timeframe]*12))
        for side in (1,-1):
            zone=low if side>0 else high;trigger=zone+side*.18*a
            stop=zone-side*max(.30*a,3*q.spread)
            target=(low+high)/2
            if (target-trigger)*side<1.2*abs(trigger-stop):continue
            ident='R74|'+hashlib.sha256(repr((self.config.symbol,self.config.timeframe,self.config.mode,self.frame,side,zone)).encode()).hexdigest()[:20]
            boundary=dict(t0=now,price=trigger,slope=0.)
            pattern=dict(pattern_id=ident,family='MICRO_STRUCTURE',variant='BOUNDARY',symbol=self.config.symbol,timeframe=self.config.timeframe,
                anchors=[],upper=dict(boundary,price=high),lower=dict(boundary,price=low),started_at=bars[-12].time,
                formed_at=now,available_at=now,quality=.70,atr=a,measurements=dict(width=width,duration=12*TF_SECONDS[self.config.timeframe],pole=None))
            title='Возврат от нижней зоны' if side>0 else 'Возврат от верхней зоны'
            self.plans[ident]=dict(scenario_id=ident,scenario_version=1,stable_plan=True,plan_version=self.VERSION,
                family='MICRO_STRUCTURE',type='BOUNDARY_RECLAIM',title=title,side=side,outside_side=side,
                created_at=now,available_at=now,updated_at=now,expires_at=now+duration,
                status='WATCHING',stage='WATCHING',zone=zone,activation=trigger,initial_activation=trigger,trigger=trigger,
                boundary=boundary,invalidation=stop,target1=target,target2=None,target=target,
                target1_source='OBSERVED_RANGE_MIDPOINT',target2_source=None,target_source='OBSERVED_RANGE_MIDPOINT',
                target1_reached=False,pattern=pattern,geometry_score=.70,quality_score=0.,model_weight=0.,calibrated_probability=None,
                entry_ready=False,event_id='',sent=False,mfe=0.,mae=0.,confirmation_policy='TOUCH_RETURN_CONTINUATION',
                observed_events=[],reason='План закреплён; ждём проверку зоны и возврат',
                path=[dict(price=q.bid,anchor='LIVE',label='LIVE',observed=True),
                      dict(price=zone,anchor='TOUCH',label='Проверка зоны?',observed=False),
                      dict(price=trigger,anchor='MICRO_CONFIRM',label='Возврат?',observed=False),
                      dict(price=target,anchor='OBSERVED_RANGE_MIDPOINT',label='T1',observed=False)])
        if len(self.plans)>16:
            for k in list(self.plans)[:-16]:
                if self.plans[k]['status'] in TERMINAL:del self.plans[k]
    def _event(self,s,stage,q,now,reason):
        s.update(stage=stage,updated_at=now,reason=reason)
        s['observed_events'].append(dict(event=stage,time=now,time_msc=q.time_msc,price=q.bid))
        if stage in TERMINAL:s.update(status=stage,entry_ready=False)
    def observe(self,bars,q,now,a,campaign=None):
        q.validate(now)
        active=[s for s in self.plans.values() if s['status'] not in TERMINAL and not s.get('sent')]
        if not active and not campaign and (not self.plans or bars[-1].time!=self.frame):self._prepare(bars,q,now,a)
        prev=self.previous
        if prev and (q.time_msc<prev.time_msc or q.time_msc-prev.time_msc>10000):self.suspend();prev=None
        duplicate=bool(prev and q.time_msc==prev.time_msc)
        if not duplicate:self.previous=q
        emitted=None
        for s in list(self.plans.values()):
            s['entry_ready']=False
            if s['status'] in TERMINAL:continue
            side=s['side'];mark=q.bid if side>0 else q.ask
            fixed_a=s['pattern']['atr']
            if now>s['expires_at']:
                self._event(s,'EXPIRED',q,now,'Срок фиксированного плана истёк');continue
            if (mark-s['invalidation'])*side<=0:
                self._event(s,'FAILED',q,now,'Фиксированный уровень отмены нарушен');continue
            if s['status']=='CONFIRMED':
                if not s['sent'] and now-s['confirmed_at']>5:
                    s.update(status='WATCHING',stage='WATCHING',entry_ready=False,event_id='',reason='Вход не исполнен вовремя; ждём новую проверку прежней зоны')
                    continue
                if (mark-s['target1'])*side>=0:
                    s['target1_reached']=True;self._event(s,'TARGET_REACHED',q,now,'Исходная целевая зона достигнута');continue
                s['entry_ready']=bool(not s['sent'] and prev and not duplicate and now-s['confirmed_at']<=5 and 0<(q.bid-s['trigger'])*side<=.25*fixed_a)
                continue
            if campaign or duplicate:continue
            if s['stage']=='WATCHING':
                if prev and (q.bid-s['zone'])*side<=.08*fixed_a and (q.bid-prev.bid)*side<0:
                    self._event(s,'TOUCH_SEEN',q,now,'Зона проверена; ждём возврат за фиксированный уровень')
                continue
            if not prev:continue
            if s['stage']=='TOUCH_SEEN':
                if (prev.bid-s['trigger'])*side<=0<(q.bid-s['trigger'])*side:
                    s['return_price']=q.bid
                    self._event(s,'RETURN_SEEN',q,now,'Возврат наблюдался; ждём следующий направленный тик')
                continue
            if s['stage']=='RETURN_SEEN':
                if (q.bid-s['trigger'])*side<=0:
                    self._event(s,'TOUCH_SEEN',q,now,'Возврат пока не удержался; уровни плана сохранены')
                elif (q.bid-s['return_price'])*side>=.03*fixed_a and (q.bid-prev.bid)*side>0:
                    distance=(q.bid-s['trigger'])*side
                    if distance>.25*fixed_a:
                        self._event(s,'EXPIRED',q,now,'Вход пропущен; не догоняем цену');continue
                    price=q.ask if side>0 else q.bid
                    if (s['target1']-price)*side<1.0*abs(price-s['invalidation']):
                        self._event(s,'EXPIRED',q,now,'До исходной цели недостаточно пространства после расходов');continue
                    s.update(status='CONFIRMED',confirmed_at=now,event_id=s['scenario_id']+'|'+str(q.time_msc),entry_ready=True,mark_at_confirmation=mark)
                    self._event(s,'CONFIRMED',q,now,'Возврат подтверждён; проверяются риск и исполнение')
                    self.event_count+=1;emitted=s
        return emitted
    def status(self,price=None):
        rows=[s for s in self.plans.values() if s['status'] not in TERMINAL and not s.get('sent')]
        if not rows:return None
        stages={'CONFIRMED':3,'RETURN_SEEN':2,'TOUCH_SEEN':1,'WATCHING':0}
        s=max(rows,key=lambda s:(stages.get(s['stage'],0),-abs((price or s['zone'])-s['zone'])))
        return dict(engine=self.VERSION,mode=self.config.mode,timeframe=self.config.timeframe,stage=s['stage'],side=s['side'],
            plan_id=s['scenario_id'],trigger=s['trigger'],invalidation=s['invalidation'],target1=s['target1'],
            reason=s['title']+': '+s['reason'],created_at=s['created_at'],expires_at=s['expires_at'],fixed_levels=True,
            detected_events=self.event_count,addition=False)
