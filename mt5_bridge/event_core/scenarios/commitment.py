"""One pre-entry execution contract. Ranking is not a cancellation event.

No broker calls, probabilities or automatic risk changes. Restore keeps the
contract, but never restores an unexecuted entry permission.
"""
from __future__ import annotations
import copy
import math
from .lifecycle import TERMINAL
from .structure import value


class PlanCommitment:
    VERSION='PINNED_V1'
    FIXED=('side','activation','initial_activation','invalidation','target1','target2',
           'target','expires_at','boundary','path')

    def __init__(self,saved=None):
        saved=saved or {}
        self.ident=saved.get('plan_id','')
        self.scope=saved.get('scope','')
        self.original=copy.deepcopy(saved.get('original',{}))
        self.last_end=copy.deepcopy(saved.get('last_end',{}))
        self.committed_at=float(saved.get('committed_at',0))
        self.restoring=bool(self.ident)

    def state(self):
        return copy.deepcopy(dict(plan_id=self.ident,scope=self.scope,original=self.original,
                                  committed_at=self.committed_at,last_end=self.last_end))

    def _end(self,code,reason,now):
        self.last_end=dict(plan_id=self.ident,code=code,reason=reason,time=now,
                           original=copy.deepcopy(self.original))
        self.ident='';self.original={};self.restoring=False

    @staticmethod
    def _eligible(s,q,now):
        if s.get('side') not in (-1,1) or s.get('addition') or s.get('sent'):
            return False
        if s.get('status') in TERMINAL or s.get('status')=='CONFIRMED':return False
        # A false-break stop is not known until its return has been observed.
        if s.get('type')=='FALSE_BREAK_RETURN' and s.get('stage')!='RETURN_SEEN':return False
        side=s['side'];stop=s.get('invalidation');target=s.get('target1')
        if not all(isinstance(x,(int,float)) and math.isfinite(x) and x>0
                   for x in (stop,target,s.get('expires_at'))):return False
        mark=q.bid if side>0 else q.ask
        entry=q.ask if side>0 else q.bid
        return now<s['expires_at'] and (mark-stop)*side>0 and (target-entry)*side>0

    def select(self,rows,q,now,scope,campaign=None):
        if self.scope and self.scope!=scope:
            if self.ident:self._end('SCOPE_CHANGED','Изменились счёт, инструмент или период',now)
            self.scope=scope
            return None
        self.scope=scope
        lookup={s['scenario_id']:s for s in rows}
        if campaign:
            root=campaign.get('scenario_id')
            if root!=self.ident:
                s=lookup.get(root)
                if s is None:return None
                self._bind(s,q,now,scope,freeze=False)
            return lookup.get(self.ident)
        if self.ident:
            s=lookup.get(self.ident)
            if s is None:
                self._end('SOURCE_UNAVAILABLE','Исходный сценарий недоступен; старый вход запрещён',now);return None
            if now>self.original['expires_at']:
                s.update(status='EXPIRED',stage='EXPIRED',entry_ready=False)
                self._end('PLAN_EXPIRED','Срок закреплённого плана истёк',now);return None
            if s.get('status') in TERMINAL:
                self._end(s['status'],s.get('reason','План завершён'),now);return None
            if s.get('sent'):
                self._end('ENTRY_CONSUMED','Результат ранее отправленной заявки сверяется отдельно',now);return None
            # Restore exactly the chosen numerical contract, not a new candidate
            # calculated under the same ID. Event stage/trigger remain causal.
            for key in self.FIXED:
                if key in self.original:s[key]=copy.deepcopy(self.original[key])
            side=s['side'];mark=q.bid if side>0 else q.ask
            if (mark-s['invalidation'])*side<=0:
                s.update(status='FAILED',stage='FAILED',entry_ready=False,reason='Нарушен закреплённый уровень отмены')
                self._end('INVALIDATED',s['reason'],now);return None
            if (mark-s['target1'])*side>=0:
                s.update(status='EXPIRED',stage='EXPIRED',entry_ready=False,reason='Цель пройдена без входа; не догоняем')
                self._end('TARGET_PASSED',s['reason'],now);return None
            if self.restoring:
                s.update(status='WATCHING',stage='WATCHING',entry_ready=False,event_id='',observed_events=[],
                         reason='План сохранён; после перезапуска требуется новое событие')
                self.restoring=False
            return s
        candidates=[s for s in rows if self._eligible(s,q,now)]
        stages={'RETURN_SEEN':4,'RETEST_SEEN':4,'MICRO':3,'PULLBACK':2,'TOUCH_SEEN':2,'BREAK_SEEN':2,'WATCHING':0}
        def priority(s):
            level=s.get('micro_trigger') or s.get('trigger') or s.get('activation',q.bid)
            scale=max(float(s.get('pattern',{}).get('atr',1e-8)),1e-8)
            return (-stages.get(s.get('stage'),0),abs(level-q.bid)/scale,-s.get('quality_score',0),s['scenario_id'])
        if candidates:
            # Proximity is considered ONCE when choosing, not on every quote.
            # A high-ranked remote boundary cannot starve a local setup forever.
            s=min(candidates,key=priority)
            self._bind(s,q,now,scope)
            return s
        return None

    def _bind(self,s,q,now,scope,freeze=True):
        if freeze:
            old=s.get('initial_activation',s.get('activation',0))
            level=value(s['boundary'],q.time_msc/1000) if s.get('boundary') else s.get('activation',0)
            if level:
                s['boundary']=dict(t0=q.time_msc/1000,price=level,slope=0.)
                s['activation']=level;s['initial_activation']=level
                for point in s.get('path',[]):
                    if point.get('anchor') in ('TRIGGER','BREAK','TRIGGER_RETEST','TOUCH','RETURN','MICRO_CONFIRM'):
                        point['price']+=level-old
        s['pinned_plan']=True
        self.ident=s['scenario_id'];self.committed_at=now;self.scope=scope
        self.original=copy.deepcopy(s);self.restoring=False

    def describe(self,source=None):
        result=self.state();result.update(version=1,available=bool(self.ident),
            model=self.VERSION,role='EXECUTION',reason='План закреплён; рейтинг альтернатив его не заменяет')
        if source is not None:
            result.update(stage=source.get('stage','WATCHING'),side=source.get('side',0),
                          trigger=source.get('micro_trigger') or source.get('trigger') or source.get('activation'),
                          invalidation=source.get('invalidation'),target1=source.get('target1'),
                          expires_at=self.original.get('expires_at'),title=source.get('title',''),
                          reason=source.get('reason',result['reason']))
        return result
