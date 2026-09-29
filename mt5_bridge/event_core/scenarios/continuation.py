"""Prospective micro-pullback observations for a confirmed, favorable campaign.

Ephemeral observation only: restart, pause and feed gap require a new sequence.
Execution/risk/position counts are exclusively owned by Engine and plan_order.
"""
import copy
from ..model import PROFILES


class Continuation:
    def __init__(self):self.reset()
    def reset(self):
        self.key=None;self.previous=None;self.peak=None;self.trough=None
        self.stage='PROGRESS';self.peak_msc=0;self.emitted=False
        self.reason='Добавление: ждём новое движение, откат и микропробой'

    def observe(self,campaign,source,q,now,a,mode):
        if not campaign or not source or not campaign.get('confirmed'):
            self.reset();return None
        key=(campaign['id'],tuple(campaign.get('events',[])))
        if key!=self.key:
            self.reset();self.key=key
        previous=self.previous
        self.previous=q
        if previous is None:
            self.peak=q.bid;self.peak_msc=q.time_msc;return None
        if q.time_msc<=previous.time_msc or q.time_msc-previous.time_msc>10000:
            if q.time_msc!=previous.time_msc:
                self.reset();self.key=key;self.previous=q;self.peak=q.bid;self.peak_msc=q.time_msc
            return None
        if self.emitted:return None
        side=campaign['side'];last=campaign['last_entry'];profile=PROFILES[mode]
        target=source.get('target');invalidation=campaign['invalidation']
        if source.get('status') in ('FAILED','EXPIRED','TARGET_REACHED') or now>source['expires_at'] or (q.bid-invalidation)*side<=0 or (target and (q.bid-target)*side>=0):
            self.stage='BLOCKED';self.reason='Добавление: исходный сценарий завершён или отменён';return None
        if (q.bid-last)*side<=0:
            self.peak=q.bid;self.peak_msc=q.time_msc;self.trough=None;self.stage='PROGRESS'
            self.reason='Добавление: цена должна быть лучше последнего входа; усреднение запрещено';return None
        if self.stage=='BLOCKED':return None
        if self.stage=='PROGRESS':
            if (q.bid-self.peak)*side>0:self.peak=q.bid;self.peak_msc=q.time_msc
            self.reason='Добавление: ждём благоприятное движение и новый откат'
            if (self.peak-last)*side>=profile.add_step_atr*a and (self.peak-q.bid)*side>=profile.pullback_atr*a:
                self.trough=q.bid;self.stage='PULLBACK'
                self.reason='Добавление: откат наблюдался; ждём возобновление движения'
            return None
        if self.stage=='PULLBACK':
            if (q.bid-self.trough)*side<0:self.trough=q.bid
            if (q.bid-previous.bid)*side>0:
                self.stage='MICRO';self.reason=f'Добавление: ждём новый микропробой {self.peak:.5f}'
            return None
        # Frozen extreme predates the pullback and resumption; never infer crossing retroactively.
        if (previous.bid-self.peak)*side<=0<(q.bid-self.peak)*side:
            if (q.bid-self.peak)*side>.25*a:
                self.peak=q.bid;self.peak_msc=q.time_msc;self.trough=None;self.stage='PROGRESS'
                self.reason='Добавление: микропробой пропущен; ждём новую независимую последовательность';return None
            targets=[(source.get('target1'),source.get('target1_source')),(source.get('target2'),source.get('target2_source'))]
            targets=[(p,k) for p,k in targets if p is not None and (p-(q.ask if side>0 else q.bid))*side>.10*a]
            if not targets:
                self.reason='Добавление: до исходной цели нет места для нового входа';return None
            self.emitted=True
            s=copy.deepcopy(source)
            ident=campaign['id']+'|ADD|'+str(self.peak_msc)+'|'+str(q.time_msc)
            stop=max(invalidation,self.trough-.10*a) if side>0 else min(invalidation,self.trough+.10*a)
            s.update(scenario_id=ident,scenario_version=1,parent_scenario_id=campaign.get('scenario_id'),
                type='PULLBACK_RESUME',title='Продолжение кампании: новый откат и микропробой',
                status='CONFIRMED',stage='CONFIRMED',created_at=now,updated_at=now,confirmed_at=now,
                trigger=self.peak,activation=self.peak,initial_activation=self.peak,
                boundary=dict(price=self.peak,t0=now,slope=0.),invalidation=stop,
                target1=targets[0][0],target1_source=targets[0][1],
                target2=targets[1][0] if len(targets)>1 else None,target2_source=targets[1][1] if len(targets)>1 else None,
                target=targets[-1][0],target_source=targets[-1][1],target1_reached=False,
                sent=False,entry_ready=True,event_id=ident,mark_at_confirmation=q.bid if side>0 else q.ask,
                mfe=0.,mae=0.,addition=True,observed_events=[
                    dict(event='MICRO_EXTREME',time_msc=self.peak_msc,price=self.peak),
                    dict(event='PULLBACK',price=self.trough),dict(event='CONFIRMED',time=now,time_msc=q.time_msc,price=q.bid)],
                reason='Новый откат завершился микропробоем; проверяются прибыль, риск и маржа')
            s['path']=[dict(price=q.bid,anchor='LIVE',label='LIVE',phase='LIVE',observed=True)]
            for i,(price,kind) in enumerate(targets):s['path'].append(dict(price=price,anchor=kind,label='T'+str(i+1),phase='TRADE',observed=False))
            self.reason=s['reason'];return s
        if (q.bid-self.trough)*side<0:
            self.trough=q.bid;self.stage='PULLBACK';self.reason='Добавление: откат углубился; ждём новую реакцию'
        return None

    def status(self):return dict(stage=self.stage,reason=self.reason,micro_trigger=self.peak)
