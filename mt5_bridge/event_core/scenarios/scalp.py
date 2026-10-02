"""Forward-only SCALP M1 observations. Never sends orders or sets risk limits.

Thresholds are research assumptions in M1 ATR units, not fitted probabilities.
Only fresh quotes can establish the advance, pullback and subsequent crossing.
"""
import hashlib
from ..model import PROFILES, bar_close_time, direction, pivots, atr, TF_SECONDS


class ScalpMicro:
    ENGINE='SCALP_MICRO_V1'

    def __init__(self,config=None):
        self.adaptive=bool(config and config.runtime_model=='R7')
        self.timeframe=config.timeframe if self.adaptive else 'M1'
        self.mode=config.mode if self.adaptive else 'SCALP'
        self.lifetime=max(240, min(86400, TF_SECONDS[self.timeframe]*(4 if self.mode=='SCALP' else 12))) if self.adaptive else 240
        self.work=[]
        self.reset()

    def reset(self,reason='SCALP M1: ждём согласованный контекст M5/M15'):
        self.key=None;self.previous=None;self.origin=None;self.peak=None;self.trough=None
        self.started=0.;self.peak_msc=0;self.side=0;self.stage='WAIT_CONTEXT'
        self.reason=reason;self.current=None;self.addition=False

    def status(self):
        return dict(engine=self.ENGINE,timeframe=self.timeframe,mode=self.mode,stage=self.stage,side=self.side,
                    trigger=self.peak if self.stage in ('PULLBACK','MICRO','CONFIRMED') else None,
                    invalidation=self.current.get('invalidation') if self.current else None,
                    reason=self.reason.replace('SCALP M1',self.mode+' '+self.timeframe),addition=self.addition)

    def _context(self,m5,m15,now):
        if self.adaptive:
            # Here m5 is the SELECTED working frame, not a hard-coded M5 series.
            self.work=list(m5)
            if len(m5)<24:return 0
            age=now-bar_close_time(m5[-1].time,self.timeframe,m5[-1].clock_offset_seconds)
            if not -1<=age<=TF_SECONDS[self.timeframe]*1.5:return 0
            structural=direction(pivots(m5))
            if structural:return structural
            move=m5[-1].close-m5[-8].close
            return 1 if move>.35*atr(m5) else -1 if move<-.35*atr(m5) else 0
        signs=[]
        for rows,tf in ((m5,'M5'),(m15,'M15')):
            if len(rows)<24:return 0
            age=now-bar_close_time(rows[-1].time,tf,rows[-1].clock_offset_seconds)
            if not -1<=age<=({'M5':300,'M15':900}[tf]*1.5):return 0
            signs.append(direction(pivots(rows)))
        if signs[0] and signs[1] and signs[0]!=signs[1]:return 0
        return signs[0] or signs[1]

    def _begin(self,q,now,key,side,origin,addition):
        self.reset();self.key=key;self.side=side;self.previous=q
        self.origin=origin;self.peak=q.bid;self.peak_msc=q.time_msc
        self.started=now;self.stage='PROGRESS';self.addition=addition
        self.reason='SCALP M1: ждём новое движение и локальный откат'

    def observe(self,symbol,m5,m15,q,now,a,campaign=None,source=None,campaign_side=0,allow_adds=True):
        side=self._context(m5,m15,now)
        if not side:
            self.reset();return None
        if campaign_side and not campaign:
            self.reset('SCALP M1: новая заявка не разрешена состоянием текущей кампании')
            self.stage='BLOCKED';return None
        opposite_id=campaign['id'] if campaign and side!=campaign['side'] else ''
        if opposite_id:
            # A new opposite confirmation is an exit request through Engine's
            # existing close-before-reverse path, never an overlapping hedge.
            campaign=None;source=None
        addition=bool(campaign)
        if addition:
            if not allow_adds:
                self.reset('SCALP M1: добавления выключены');self.stage='BLOCKED';return None
            if (not campaign.get('confirmed') or side!=campaign['side'] or not source or
                source.get('status') in ('FAILED','EXPIRED','TARGET_REACHED') or now>source['expires_at']):
                self.reset('SCALP M1: добавление запрещено — контекст или исходный сценарий не подтверждён')
                self.stage='BLOCKED';return None
            if (q.bid-campaign['invalidation'])*side<=0:
                self.reset('SCALP M1: нарушен уровень отмены кампании');self.stage='BLOCKED';return None
        key=(symbol,side,campaign['id'] if campaign else opposite_id,tuple(campaign.get('events',())) if campaign else ())
        if key!=self.key or self.previous is None:
            self._begin(q,now,key,side,campaign['last_entry'] if campaign else q.bid,addition)
            return None
        # Lifecycle runs first. A blocked order must not leave a terminal,
        # consumed or no-longer-executable confirmation armed indefinitely.
        if self.stage=='CONFIRMED' and (not self.current or not self.current.get('entry_ready')):
            self._begin(q,now,key,side,campaign['last_entry'] if campaign else q.bid,addition)
            self.reason='SCALP M1: прежнее подтверждение завершено; ждём новое движение и откат'
            return None
        prev=self.previous
        if q.time_msc<=prev.time_msc:
            if q.time_msc<prev.time_msc:self.reset('SCALP M1: время котировки вернулось назад')
            return None
        if q.time_msc-prev.time_msc>10000 or now-self.started>self.lifetime:
            self._begin(q,now,key,side,campaign['last_entry'] if campaign else q.bid,addition)
            return None
        self.previous=q
        if self.stage=='CONFIRMED':return None
        if (q.bid-self.origin)*side<=0:
            self._begin(q,now,key,side,campaign['last_entry'] if campaign else q.bid,addition)
            return None
        p=PROFILES[self.mode]
        if self.stage=='PROGRESS':
            if (q.bid-self.peak)*side>0:self.peak=q.bid;self.peak_msc=q.time_msc
            if (self.peak-self.origin)*side>=p.add_step_atr*a and (self.peak-q.bid)*side>=p.pullback_atr*a:
                self.trough=q.bid;self.stage='PULLBACK'
            else:return None
        elif (q.bid-self.trough)*side<0:
            self.trough=q.bid;self.stage='PULLBACK'
        elif (q.bid-prev.bid)*side>0:
            self.stage='MICRO'
        self.current=self._scenario(symbol,q,now,a,source)
        self.reason=f'SCALP M1: откат наблюдался; ждём микропробой {"вверх" if side>0 else "вниз"} {self.peak:.5f}'
        if self.stage=='MICRO' and (prev.bid-self.peak)*side<=0<(q.bid-self.peak)*side:
            if (q.bid-self.peak)*side>.25*a:
                self._begin(q,now,key,side,campaign['last_entry'] if campaign else q.bid,addition)
                self.reason='SCALP M1: микропробой пропущен; ждём новую последовательность';return None
            s=self.current
            price=q.ask if side>0 else q.bid
            if (s['target1']-price)*side<=.10*a:
                self._begin(q,now,key,side,campaign['last_entry'] if campaign else q.bid,addition)
                self.reason='SCALP M1: до исходной цели недостаточно места';return None
            self.stage='CONFIRMED';self.reason='SCALP M1: свежий микропробой подтверждён; проверяются прибыль, риск и исполнение'
            s.update(status='CONFIRMED',stage='CONFIRMED',entry_ready=True,confirmed_at=now,
                     event_id=s['scenario_id']+'|'+str(q.time_msc),mark_at_confirmation=q.bid if side>0 else q.ask,
                     reason=self.reason)
            s['observed_events'].append(dict(event='CONFIRMED',time=now,time_msc=q.time_msc,price=q.bid))
            return s
        return None

    def _scenario(self,symbol,q,now,a,source):
        side=self.side;stop=self.trough-side*.10*a
        if self.adaptive:
            # Stop beyond observed pullback, with an explicit spread/ATR floor.
            pad=max(.10*a,2*q.spread)
            stop=self.trough-side*pad
            if self.mode=='NORMAL' and self.work:
                structural=min(b.low for b in self.work[-3:])-.05*a if side>0 else max(b.high for b in self.work[-3:])+.05*a
                stop=min(stop,structural) if side>0 else max(stop,structural)
        boundary=dict(price=self.peak,t0=self.peak_msc/1000,slope=0.)
        # Fixed measurable extension of the observed local impulse, not a price/time forecast.
        target=self.peak+side*max(abs(self.peak-self.origin),2*abs(self.peak-stop))
        target_kind='MICRO_IMPULSE_EXTENSION'
        if source:
            targets=[(source.get(k),source.get(k+'_source')) for k in ('target1','target2')]
            targets=[(x,k) for x,k in targets if x is not None and (x-(q.ask if side>0 else q.bid))*side>.10*a]
            target,target_kind=targets[0] if targets else (source['target'],source.get('target_source'))
        identity=hashlib.sha256(repr((self.key,self.started,self.peak_msc)).encode()).hexdigest()[:24]
        ident=(self.mode+'_'+self.timeframe if self.adaptive else 'SCALP_M1')+'|'+identity
        upper=max(self.peak,self.trough);lower=min(self.peak,self.trough)
        pattern=dict(pattern_id=ident,family='MICRO_STRUCTURE',variant='PULLBACK',symbol=symbol,timeframe=self.timeframe,
                     anchors=[],upper=dict(boundary,price=upper),lower=dict(boundary,price=lower),
                     started_at=self.started,formed_at=self.started,available_at=self.started,quality=1.,atr=a,
                     measurements=dict(width=upper-lower,duration=now-self.started,pole=None))
        return dict(scenario_id=ident,scenario_version=1,parent_scenario_id=source.get('scenario_id') if source else None,
            type='PULLBACK_RESUME',family='MICRO_STRUCTURE',title=self.mode+' '+self.timeframe+': локальный откат и микропробой',
            side=side,outside_side=side,status='WATCHING',stage=self.stage,created_at=self.started,updated_at=now,
            expires_at=min(self.started+self.lifetime,source['expires_at']) if source else self.started+self.lifetime,
            activation=self.peak,initial_activation=self.peak,trigger=self.peak,boundary=boundary,
            invalidation=stop,target1=target,target2=None,target=target,target1_source=target_kind,
            target2_source=None,target_source=target_kind,target1_reached=False,pattern=pattern,
            geometry_score=1.,quality_score=0.,model_weight=0.,calibrated_probability=None,
            entry_ready=False,event_id='',sent=False,mfe=0.,mae=0.,micro=True,addition=self.addition,
            confirmation_policy='OBSERVED_EVENT_AND_MICRO',reason=self.reason,
            observed_events=[dict(event='MICRO_EXTREME',time_msc=self.peak_msc,price=self.peak),
                             dict(event='PULLBACK',time=now,price=self.trough)],
            path=[dict(price=q.bid,anchor='LIVE',label='LIVE',observed=True),
                  dict(price=self.peak,anchor='MICRO_CONFIRM',label='Микропробой?',observed=False),
                  dict(price=target,anchor=target_kind,label='T1',observed=False)])

    def preview(self):
        if self.current and self.current['status'] not in ('FAILED','EXPIRED','TARGET_REACHED'):
            return self.current
        return None
