from __future__ import annotations
from dataclasses import asdict, fields, replace
import copy, hashlib, math, threading, time
from .model import Config, Decision, Blocked, PROFILES, TF_SECONDS, atr, pivots, number, ordered, live_structure
from .strategy import Strategy
from .compute_core import ComputeCore
from .risk import risk_state, plan_order, ledger, summary, quantize, day_start, estimate_roundtrip_fee_per_lot, symbol_key
from .mt5_adapter import MAGIC

CONTEXT={'M1':'M5','M5':'M15','M10':'H1','M15':'H1','H1':'H4','H4':'D1','D1':'W1','W1':'MN1','MN1':'MN1'}
# Broker/server candle clocks can cross the M5 boundary slightly before the PC clock.
# The forming M5 stays isolated from confirmed-pivot history; larger future jumps remain blocked.
LIVE_M5_CLOCK_SKEW_SEC=60


class Engine:
    """Single serialized campaign owner. UI never supplies a BUY/SELL command."""
    def __init__(self,broker,store,clock=time.time):
        self.broker=broker;self.store=store;self.clock=clock;self.lock=threading.RLock()
        saved=store.load('engine',{})
        self.config=Config(**saved.get('config',{})).validate()
        self.account_key=saved.get('account_key','')
        self.real_armed=False
        # Ephemeral by design: never resurrect a reversal after Bridge restart.
        self.pending_reversal=None
        self.effective_fee_per_lot=None;self.fee_source='UNRESOLVED';self.fee_profile_key=''
        self.campaign=saved.get('campaign')
        self.emergency=bool(saved.get('emergency',False))
        self.recovery=bool(saved.get('recovery',False))
        self.daily_latch=saved.get('daily_latch','')
        self.ack=saved.get('ack',[0,0]);self.last_exit=float(saved.get('last_exit',0))
        self.auto=False;self.paused=True;self.heartbeat=0.
        self.exit_pending=bool(saved.get('exit_pending',False))
        self.strategy=Strategy(self.config,saved.get('strategy'))
        self.compute=ComputeCore(self.config,saved.get('compute'))
        self.strategy.previous_quote=None
        self.compute.previous_quote=None
        if self.strategy.setup:
            self.strategy.setup.seen_safe_side=False
            self.strategy.setup.armed_msc=int(clock()*1000)
        if store.pending(): self.recovery=True
        self.deals=[];self.history_time=0.;self.history_ok=False
        self.history_error='История ещё не получена'
        self.rows=[];self.account={};self.account_time=0.;self.positions=[];self.orders=[]
        self.risk={'allowed':False,'blocks':['HISTORY_UNAVAILABLE']}
        self.last_bars_at=0.;self.bars=[];self.context=[];self.quote=None;self.info={}
        self.m1=[];self.m15=[];self.h1=[];self.live_bar=None
        self.market_time=0.;self.market_errors=[];self.quote_ready=False
        self.last_market_attempt=-1.;self.bar_errors=[]
        self.analysis_time=0.;self.decision=Decision();self.execution='AUTO выключен: только анализ'
        self.forecast={};self.forecast_side=0;self.forecast_since=0.
        self.rate_times=[];self.next_close=0.;self.last_persist=0.;self.last_audit_key=None
        self.save()

    def save(self):
        self.store.save('engine',dict(config=asdict(self.config),account_key=self.account_key,
            campaign=self.campaign,emergency=self.emergency,recovery=self.recovery,
            daily_latch=self.daily_latch,ack=self.ack,last_exit=self.last_exit,
            exit_pending=self.exit_pending,strategy=self.strategy.state(),compute=self.compute.state()))

    def _consume_event(self,event_id):
        if self.config.engine_mode=='COMPUTE_V1':self.compute.consume(event_id)
        else:self.strategy.consume(event_id)

    def _owned(self): return [p for p in self.positions if p['magic']==MAGIC]
    def _owned_orders(self): return [p for p in self.orders if p['magic']==MAGIC]

    def _fee_key(self):
        if not self.account_key:return ''
        return self.account_key+'|'+symbol_key(self.config.symbol)

    def _resolve_fee_profile(self):
        self.fee_profile_key=self._fee_key()
        if not self.account or not self.fee_profile_key:
            self.effective_fee_per_lot=None;self.fee_source='UNRESOLVED';return
        profiles=self.store.load('fee_profiles',{})
        manual=self.config.fee_per_lot
        if self.account.get('type')=='DEMO':
            self.effective_fee_per_lot=float(manual) if manual is not None else 0.0
            self.fee_source='MANUAL' if manual is not None else 'DEMO_DEFAULT_ZERO'
            return
        if manual is not None:
            self.effective_fee_per_lot=float(manual);self.fee_source='MANUAL'
            profiles[self.fee_profile_key]=dict(fee_per_lot=self.effective_fee_per_lot,source='MANUAL',updated=self.clock())
            self.store.save('fee_profiles',profiles);return
        saved=profiles.get(self.fee_profile_key)
        if saved is not None:
            self.effective_fee_per_lot=float(saved['fee_per_lot']);self.fee_source=str(saved.get('source','SAVED'))
            return
        estimate=estimate_roundtrip_fee_per_lot(self.deals,self.config.symbol) if self.history_ok else None
        if estimate is None:
            self.effective_fee_per_lot=None;self.fee_source='UNKNOWN';return
        self.effective_fee_per_lot=float(estimate);self.fee_source='MT5_HISTORY'
        profiles[self.fee_profile_key]=dict(fee_per_lot=self.effective_fee_per_lot,source='MT5_HISTORY',updated=self.clock())
        self.store.save('fee_profiles',profiles)

    def _execution_config(self):
        return replace(self.config,fee_per_lot=self.effective_fee_per_lot)

    def _refresh_risk(self,now):
        try:
            if not self.history_ok or now-self.history_time>15:
                raise Blocked(self.history_error or 'История устарела')
            if self.account.get('type')=='REAL' and self.effective_fee_per_lot is None:
                raise Blocked('Комиссия REAL для этого счёта/инструмента ещё не определена')
            self.risk=risk_state(self.account,self.positions,self.deals,self._execution_config(),now,self.ack,self.daily_latch)
            self.rows=ledger(self.deals,self.positions)
            if 'DAILY_LOSS' in self.risk['blocks']:
                previous=(self.daily_latch,self.auto,self.paused,self.exit_pending)
                self.daily_latch=self.risk['day'];self.auto=False;self.paused=True
                if self._has_exit_targets():
                    self.exit_pending=True
                if previous!=(self.daily_latch,self.auto,self.paused,self.exit_pending):
                    self.save()
        except (Blocked,ValueError,TypeError,KeyError) as e:
            self.risk={'allowed':False,'blocks':['DATA_UNAVAILABLE'],'message':str(e),'ack_supported':True,'can_acknowledge':False}

    def _refresh(self,now):
        self.broker.connect()
        a=self.broker.account();current_positions=self.broker.positions();current_orders=self.broker.orders()
        self.account=a;self.account_time=now;self.positions=current_positions;self.orders=current_orders
        if self.account_key and a['key']!=self.account_key:
            self.auto=False;self.paused=True;self.recovery=True;self.real_armed=False;self.save()
            raise Blocked('Счёт MT5 изменён; привяжите текущий счёт в настройках EventCore')
        if not self.account_key:self.account_key=a['key'];self.save()
        if a['type'] not in ('DEMO','REAL') or a['margin_mode']!='HEDGING' or a['currency']!='USD':
            self.auto=False;self.paused=True;self.real_armed=False
            raise Blocked('Поддерживаются USD DEMO/REAL hedging; contest/netting/другая валюта пока запрещены')
        flat_campaign=bool(self.campaign and not self._owned() and not self._owned_orders() and not self.store.pending())
        history_interval=1.0 if self.exit_pending or flat_campaign else 10.0
        if not self.history_time or now-self.history_time>=history_interval:
            try:
                self.deals=self.broker.history(now);self.history_time=now;self.history_ok=True;self.history_error=''
            except Exception as e:
                self.history_ok=False;self.history_time=now;self.history_error=str(e)
        self._resolve_fee_profile()
        self._refresh_risk(now)

    def _reconcile(self):
        owned=self._owned();pending=self.store.pending()
        for intent in pending:
            comment=intent['body'].get('comment','')
            matching=[p for p in owned if p.get('comment')==comment]
            deals=[d for d in self.deals if d.get('magic')==MAGIC and d.get('comment')==comment and d.get('entry')==0]
            if not self.history_ok: continue
            if matching or deals:
                self.store.intent(intent['id'],'RECONCILED',intent['body'])
                if self.campaign:
                    self.campaign['position_ids']=sorted(set(self.campaign.get('position_ids',[]))|
                        {p['identifier'] for p in matching}|{int(d['position_id']) for d in deals})
                    self.save()
        if self.store.pending():self.recovery=True;self.auto=False;self.paused=True
        if owned and not self.campaign:
            self.recovery=True;self.auto=False;self.paused=True
            self.execution='Есть позиции EC1 без сохранённой кампании: нужна ручная сверка'
        if self.campaign and self.history_ok:
            ids=set(self.campaign.get('position_ids',[]))
            self.campaign['realized']=sum(d['profit']+d.get('swap',0)+d.get('commission',0)+d.get('fee',0)
                for d in self.deals if d.get('position_id') in ids and d.get('entry') in (1,3))
            if not owned and not self._owned_orders() and not self.store.pending():
                closed_ids={row['position_id'] for row in ledger(self.deals,self.positions)}
                if not ids.issubset(closed_ids):
                    self.history_time=0.
                    self.execution='Позиций EC1 нет; ожидается подтверждение закрытия в истории MT5'
                    return False
                self.campaign['end']=self.clock()
                self.campaign['net']=sum(d['profit']+d.get('swap',0)+d.get('commission',0)+d.get('fee',0)
                    for d in self.deals if d.get('position_id') in ids)
                self.store.campaign(self.campaign['id'],self.campaign)
                self.store.event('CAMPAIGN_CLOSED',self.campaign,self.clock())
                self.campaign=None;self.last_exit=self.clock();self.exit_pending=False
                self.strategy.clear()
                if not (self.pending_reversal and self.clock()<=float(self.pending_reversal.get('expires',0))):
                    self.compute.clear()
                self.save()
                return True
        if self.exit_pending and not self._has_exit_targets():
            self.exit_pending=False
            self.execution=self._idle_status()
            self.save()
        return False

    def _has_exit_targets(self):
        return bool(self.campaign or self._owned() or self._owned_orders() or self.store.pending())

    def _idle_status(self):
        if self.emergency:
            return 'EMERGENCY сохранён. Собственных позиций/ордеров EC1 нет; AUTO выключен'
        if self.recovery or self.store.pending():
            return 'Нужна сверка исполнения; новые входы запрещены'
        names={'DAILY_LOSS':'дневной лимит','DRAWDOWN':'просадка',
               'LOSS_STREAK':'серия убытков','DATA_UNAVAILABLE':'нет свежей проверки риска',
               'HISTORY_UNAVAILABLE':'история недоступна'}
        blocks=self.risk.get('blocks',[])
        if blocks:
            message='Новые входы запрещены: '+', '.join(names.get(x,x) for x in blocks)
            if 'base' in self.risk:
                message+=f". Риск всего счёта относительно базы {self.risk['base']:.2f} USD"
                message+=f"; плавающий результат {self.risk.get('floating',0):+.2f} USD"
        else:
            message=('AUTO выключен' if not self.auto else 'PAUSE' if self.paused else 'Новые входы не отправлены')
            message+='; сопровождение сохраняется'
        foreign=sum(p.get('magic')!=MAGIC for p in self.positions)
        foreign_orders=sum(o.get('magic')!=MAGIC for o in self.orders)
        if foreign or foreign_orders:
            message+=f'\nСтарые/ручные позиции: {foreign}, ордера: {foreign_orders}. EC1 ими не управляет'
        return message

    def _suspend_trigger(self,now):
        self.strategy.previous_quote=None
        self.compute.previous_quote=None
        setup=self.strategy.setup
        if setup:
            setup.seen_safe_side=False
            setup.armed_msc=max(setup.armed_msc,int(now*1000))

    def _refresh_market(self,now):
        self.market_errors=[];self.quote_ready=False
        try:
            self.info=self.broker.symbol(self.config.symbol)
        except Exception as exc:
            self.market_errors=['Инструмент MT5 недоступен: '+str(exc)]
            return
        symbol=self.info['name']
        try:
            self.quote=self.broker.quote(symbol)
            self.quote.validate(now)
            self.quote_ready=True
        except Exception as exc:
            self.market_errors.append('Нет пригодной свежей котировки: '+str(exc))
        if self.last_market_attempt<0 or now-self.last_market_attempt>=1:
            self.last_market_attempt=now;self.bar_errors=[]
            layers=(('bars',self.config.timeframe),('context',CONTEXT[self.config.timeframe]))
            if self.config.timeframe=='M5':
                layers=(('m1','M1'),('bars','M5'),('m15','M15'),('h1','H1'))
            for attr,tf in layers:
                try:
                    values=list(self.broker.bars(symbol,tf))
                    if not values:
                        raise Blocked('MT5 вернул пустую историю '+tf)
                    ordered(values)
                    if tf!='MN1' and values[-1].time+TF_SECONDS[tf]>now+1.0:
                        raise Blocked('MT5 вернул незакрытую свечу '+tf)
                    setattr(self,attr,values)
                except Exception as exc:
                    self.bar_errors.append('История '+tf+' не обновлена: '+str(exc))
            if self.config.timeframe=='M5':
                self.context=self.m15
                try:
                    live=self.broker.current_bar(symbol,'M5')
                    if live.time>now+LIVE_M5_CLOCK_SKEW_SEC:
                        raise Blocked('MT5 вернул текущую M5 свечу из будущего')
                    self.live_bar=live
                except Exception as exc:
                    self.live_bar=None
                    self.bar_errors.append('Текущая M5 свеча не обновлена: '+str(exc))
            else:
                self.m1=[];self.m15=[];self.h1=[];self.live_bar=None
            if not self.bar_errors:
                self.last_bars_at=now;self.market_time=now
        self.market_errors.extend(self.bar_errors)
        ctf=CONTEXT[self.config.timeframe]
        if not self.bars or not self.context:
            self.market_errors.append('Нет полной истории рабочего и старшего таймфреймов')
        elif ctf!='MN1' and now-self.context[-1].time>TF_SECONDS[ctf]*2.5:
            self.market_errors.append('Контекст старшего таймфрейма устарел')
        if self.bars and self.config.timeframe!='MN1':
            tf=TF_SECONDS[self.config.timeframe]
            if now-(self.bars[-1].time+tf)>tf*1.5:
                self.market_errors.append('Закрытые свечи MT5 исторические; для входа нужны новые данные')

    def _close_campaign(self,reason):
        if not self._has_exit_targets():
            self.exit_pending=False
            self.execution=self._idle_status()
            self.save()
            return
        self.exit_pending=True;self.auto=False if self.emergency else self.auto
        self.execution='Выход кампании: '+reason;self.save()
        now=self.clock()
        if now<self.next_close:return
        self.next_close=now+2
        for o in self._owned_orders():
            try:self.broker.cancel(o)
            except Exception as e:self.execution='Отмена ордера пока не подтверждена: '+str(e);return
        self.orders=self.broker.orders()
        if self._owned_orders():return
        self.positions=self.broker.positions()
        for p in self._owned():
            result=self.broker.close_position(p)
            self.store.event('CLOSE_RESPONSE',dict(ticket=p['ticket'],result=result),now)
            if result['status']!='FILLED':
                self.execution='Закрытие пока не подтверждено: '+result.get('reason','')
                if result['status']=='UNKNOWN':self.recovery=True;self.auto=False;self.paused=True
                self.save();return
        self.positions=self.broker.positions()
        if not self._owned() and not self._owned_orders():self.execution='Позиции бота закрыты: '+reason+'; ожидается сверка истории'

    def _manage(self,now,price_ready=True):
        owned=self._owned()
        if self.emergency or self.exit_pending:
            self._close_campaign('Emergency' if self.emergency else 'ожидаем завершения');return True
        if not owned:return False
        if not self.campaign:return False
        c=self.campaign;q=self.quote
        side=c['side'];net=sum(p['profit']+p.get('swap',0)-float(self.effective_fee_per_lot or 0)*p['volume'] for p in owned)+c.get('realized',0)
        if c.get('entry_class')=='PROBE' and not c.get('confirmed',False):
            f=self.forecast or {}
            available=bool(f.get('available',('up_probability' in f and 'down_probability' in f)))
            if int(f.get('side',0) or 0)==-side and float(f.get('confidence',0) or 0)>=self.config.forecast_exit_probability and float(f.get('stable_for_sec',0) or 0)>=self.config.forecast_exit_stability_sec:
                self._close_campaign('LIVE forecast устойчиво развернулся против раннего probe');return True
            if available:
                side_prob=float(f.get('up_probability' if side==1 else 'down_probability',0) or 0)
                range_prob=float(f.get('range_probability',0) or 0)
                lost=side_prob<max(.50,self.config.forecast_min_confidence-.05) or range_prob>=.40
                if lost:
                    if not c.get('edge_lost_since'):c['edge_lost_since']=now
                    if net<0 and now-float(c.get('edge_lost_since',now))>=self.config.probe_neutral_exit_sec:
                        self._close_campaign('probe потерял вычислительное преимущество; ранний выход до защитного SL');return True
                else:
                    c['edge_lost_since']=0.
            if now-c.get('started',now)>=self.config.probe_timeout_sec:
                self._close_campaign('probe не получил подтверждения за отведённое время');return True
        c['peak']=max(float(c.get('peak',0)),net)
        if net<=-c['budget'] or any(p['sl']<=0 for p in owned):
            self._close_campaign('превышен риск или отсутствует брокерский SL');return True
        if not price_ready:
            return False
        q.validate(now)
        mark=q.bid if side==1 else q.ask
        if (mark-c['invalidation'])*side<=0:
            self._close_campaign('слом уровня отмены сценария');return True
        profile=PROFILES[c['mode']]
        r=max(c.get('initial_risk',c['budget']),1e-8)
        if c['peak']>=profile.protect_at_r*r and net<c['peak']*(1-profile.giveback_fraction):
            self._close_campaign('защита накопленного результата кампании');return True
        if now-c.get('last_progress',c['started'])>profile.progress_bars*TF_SECONDS[c['timeframe']] and net<.25*r:
            self._close_campaign('движение не получило продолжения за отведённое время');return True
        if (mark-c.get('best_price',c['last_entry']))*side>0:
            c['best_price']=mark;c['last_progress']=now
        if c['peak']>=profile.protect_at_r*r and self.bars and not self.market_errors:
            a=atr(self.bars);pts=pivots(self.bars)
            levels=[p['price'] for p in pts if p['kind']==('L' if side==1 else 'H')]
            candidate=(min(b.low for b in self.bars[-2:])-a*.05 if side==1 else max(b.high for b in self.bars[-2:])+a*.05) if c['mode']=='SCALP' else (levels[-1]-side*a*.05 if levels else c['invalidation'])
            dist=(max(self.info['stops_level'],self.info['freeze_level'])+1)*self.info['point']
            if (mark-candidate)*side>dist:
                candidate=quantize(candidate,self.info['tick_size'],up=side==-1)
                for p in owned:
                    if (candidate-p['sl'])*side>self.info['tick_size']:
                        self.broker.modify(p,candidate)
                self.positions=self.broker.positions()
                if any((p['sl']-candidate)*side<-self.info['tick_size'] for p in self._owned()):
                    raise Blocked('Подтянутый SL ещё не подтверждён: добавления запрещены')
                if (candidate-c['invalidation'])*side>0:c['invalidation']=candidate
        return False

    def _update_forecast(self,now):
        raw=self.strategy.forecast(self.bars,self.m1,self.m15,self.h1,self.live_bar,self.quote,now)
        side=int(raw.get('side',0) or 0);candidate=int(raw.get('candidate_side',0) or 0)
        tracking=side if side in (-1,1) else candidate
        confidence=float(raw.get('confidence',0) or 0);edge=float(raw.get('edge_strength',0) or 0)
        qualified=(side in (-1,1) and confidence>=self.config.forecast_min_confidence) or (
            side==0 and tracking in (-1,1) and confidence>=self.config.early_probe_probability and edge>=self.config.early_probe_edge)
        if qualified:
            if tracking!=self.forecast_side:
                self.forecast_side=tracking;self.forecast_since=now
            stable=max(0.,now-self.forecast_since)
        else:
            self.forecast_side=0;self.forecast_since=now;stable=0.
        raw=dict(raw);raw['stable_for_sec']=round(stable,2)
        self.forecast=raw
        return raw

    def _late_entry_reason(self,d):
        f=self.forecast or {}
        fside=int(f.get('side',0) or 0);confidence=float(f.get('confidence',0) or 0)
        if fside==d.side and (f.get('late_entry') or f.get('exhaustion')):
            return 'Поздний вход заблокирован: цена уже у края/истощения текущего движения; ждём откат и новый micro-break'
        if fside==-d.side and confidence>=self.config.probe_probability:
            return 'Вход заблокирован: LIVE forecast устойчиво против подтверждённого направления'
        return ''

    def _session_allowed(self,now):
        if not self.config.session_filter:return True
        h=time.gmtime(now).tm_hour
        session='ASIA' if h<7 else 'LONDON' if h<12 else 'LONDON+NEW_YORK' if h<16 else 'NEW_YORK' if h<21 else 'ROLLOVER'
        return bool(set(session.split('+'))&set(self.config.allowed_sessions.split(',')))

    def step(self):
        with self.lock:
            now=self.clock()
            try:
                self._refresh(now)
                just_closed=self._reconcile()
                exit_cycle=bool(just_closed or self.emergency or self.exit_pending)
                if self.emergency or self.exit_pending:
                    try:
                        self._close_campaign('Emergency' if self.emergency else 'ожидаем завершения')
                    except Exception as exc:
                        self.execution='Закрытие EC1 пока не подтверждено: '+str(exc)
                self._refresh_market(now)
                compute_decision=None
                if not self.market_errors and self.quote_ready:
                    try:
                        if self.config.engine_mode=='COMPUTE_V1':
                            compute_decision=self.compute.evaluate(
                                self.bars,self.m1,self.m15,self.h1,self.live_bar,self.quote,now,
                                self.campaign['side'] if self.campaign else 0)
                            self.forecast=copy.deepcopy(compute_decision.forecast)
                        else:
                            self._update_forecast(now)
                    except Exception as exc:
                        self.forecast=dict(side=0,confidence=0.,up_probability=.33,down_probability=.33,
                            range_probability=.34,late_entry=False,exhaustion=False,regime='DATA_BLOCK',
                            components={},projection=[],engine=self.config.engine_mode,
                            reason='Вычислительный анализ недоступен: '+str(exc),stable_for_sec=0.)
                        self.forecast_side=0;self.forecast_since=now
                else:
                    self.forecast=dict(side=0,confidence=0.,up_probability=.33,down_probability=.33,
                        range_probability=.34,late_entry=False,exhaustion=False,regime='DATA_BLOCK',
                        components={},projection=[],engine=self.config.engine_mode,
                        reason='Вычислительный анализ ждёт свежие данные',stable_for_sec=0.)
                    self.forecast_side=0;self.forecast_since=now
                if exit_cycle:
                    self._suspend_trigger(now)
                    message=self.execution
                    if self.market_errors:
                        message+='\nВход запрещён: '+'; '.join(self.market_errors)
                    self.decision=Decision(phase='DATA_BLOCK' if self.market_errors else 'SEARCH',reason=message)
                    return self.snapshot()
                if self._manage(now,price_ready=self.quote_ready):
                    return self.snapshot()
                if self.market_errors:
                    raise Blocked('; '.join(self.market_errors))
                q=self.quote;q.validate(now)
                if self.config.engine_mode=='COMPUTE_V1':
                    d=compute_decision if compute_decision is not None else self.compute.evaluate(
                        self.bars,self.m1,self.m15,self.h1,self.live_bar,q,now,
                        self.campaign['side'] if self.campaign else 0)
                    self.forecast=copy.deepcopy(d.forecast)
                    if self.campaign and d.signal in ('BUY','SELL') and d.side==self.campaign['side']:
                        d=replace(d,entry_class='CONFIRMED')
                else:
                    # Observe prospective structural crossings every cycle. The observer
                    # is forward-only: after restart its first quote only arms the detector.
                    live_breakout=self.strategy.live_breakout_probe(
                        self.bars,self.m1,self.m15,self.h1,self.live_bar,q,now,self.forecast)
                    # Confirmed strategy and LIVE forecast are independent layers.
                    core=self.strategy.update(self.bars,self.context,q,now,0,
                        m1=self.m1,m15=self.m15,h1=self.h1,live_bar=self.live_bar)
                    d=replace(core,forecast=copy.deepcopy(self.forecast),
                              entry_class=('CONFIRMED' if core.signal in ('BUY','SELL') and core.phase=='ENTRY_READY' else core.entry_class))
                    # A confirmed opposite event remains an exit signal for an existing campaign.
                    if self.campaign and d.phase=='ENTRY_READY' and d.side in (-1,1) and d.side!=self.campaign['side']:
                        pass
                    elif not self.campaign and d.signal in ('BUY','SELL') and d.phase=='ENTRY_READY':
                        late_reason=self._late_entry_reason(d)
                        if late_reason:
                            if d.event_id:self._consume_event(d.event_id)
                            d=Decision(phase='FORECAST',reason=late_reason,side=d.side,atr=d.atr,
                                levels=d.levels,path='LATE_BLOCK',structure=d.structure,
                                forecast=copy.deepcopy(self.forecast),entry_class='NONE')
                    elif not self.campaign and live_breakout is not None:
                        d=live_breakout
                    elif not self.campaign and d.signal=='WAIT' and d.phase!='DATA_BLOCK':
                        probe=self.strategy.probe_decision(self.bars,self.m1,self.m15,self.h1,self.live_bar,q,now,self.forecast)
                        if probe is not None:d=probe
                self.decision=d;self.analysis_time=now
                if now-self.last_persist>=1:
                    self.save();self.last_persist=now
                key=(self.bars[-1].time,d.phase,d.signal,d.path,int(float(self.forecast.get('confidence',0))*20))
                if key!=self.last_audit_key:
                    self.store.event('ANALYSIS',dict(decision=d.json(),quote=asdict(q),bar=asdict(self.bars[-1]),mode=self.config.mode),now)
                    self.last_audit_key=key
                # Close-and-reverse: never hedge the old campaign. ComputeCore keeps a
                # short-lived reversal candidate, closes first, waits for MT5 flat/history,
                # then may enter the opposite side only if a fresh calculation still agrees.
                if self.campaign and d.phase=='ENTRY_READY' and d.side in (-1,1) and d.side!=self.campaign['side']:
                    old='BUY' if self.campaign['side']==1 else 'SELL'
                    if self.config.engine_mode=='COMPUTE_V1':
                        self.pending_reversal=dict(side=d.side,created=now,expires=now+20.0,
                            source_event=d.event_id,signal=d.signal)
                        self.save()
                    elif d.event_id:
                        self._consume_event(d.event_id);self.save()
                    self._close_campaign('подтверждён разворот '+d.signal+' против текущей '+old+' кампании')
                    return self.snapshot()
                if not self.campaign and self.pending_reversal:
                    pr=self.pending_reversal
                    valid=(now<=float(pr.get('expires',0)) and d.phase=='ENTRY_READY' and
                           d.signal in ('BUY','SELL') and d.side==int(pr.get('side',0)))
                    if not valid:
                        self.pending_reversal=None
                if not self.auto or self.paused:self.execution=self._idle_status()
                elif self.recovery:self.execution='Нужна сверка неизвестного исполнения; новые входы запрещены'
                elif not self.risk.get('allowed',False):self.execution=self._idle_status()
                elif not self._session_allowed(now):self.execution='Текущая сессия не разрешена выбранным фильтром'
                elif d.signal=='WAIT':
                    self.execution=d.reason if self.config.engine_mode=='COMPUTE_V1' else (
                        ('LIVE forecast '+('BUY' if int(self.forecast.get('side',0) or 0)==1 else 'SELL')+
                         f" {float(self.forecast.get('confidence',0) or 0)*100:.0f}%; вход ещё не готов")
                        if int(self.forecast.get('side',0) or 0) else 'Нет нового подтверждённого входа; ордер не отправлен')
                else:
                    try:self._entry(d,now)
                    finally:
                        self._consume_event(d.event_id);self.save()
                if d.event_id:self._consume_event(d.event_id);self.save()
            except Exception as e:
                self._suspend_trigger(now)
                self.execution=str(e)+'\n'+self._idle_status()
                if self.exit_pending:
                    self.execution+='\nВыход собственных позиций EC1 ещё не завершён'
                detail=str(e)
                if self.bars:
                    detail+='\nПоказаны последние доступные закрытые свечи MT5; это не свежий торговый сигнал'
                self.decision=Decision(phase='DATA_BLOCK',reason=detail)
            return self.snapshot()

    def _entry(self,d,now):
        if self.emergency or self.exit_pending or self.recovery or self.store.pending():
            raise Blocked('Вход заблокирован состоянием кампании')
        if self.store.has_intent(d.event_id):raise Blocked('Повтор торгового события запрещён')
        if self._owned_orders():raise Blocked('Предыдущий запрос ещё не завершён')
        if any(p['magic']!=MAGIC for p in self.positions) or any(o['magic']!=MAGIC for o in self.orders):
            raise Blocked('Есть ручные/старые позиции или ордера: сначала завершите их отдельно')
        reversal_ok=bool(self.config.engine_mode=='COMPUTE_V1' and self.pending_reversal and
                         now<=float(self.pending_reversal.get('expires',0)) and
                         int(self.pending_reversal.get('side',0))==d.side)
        if now-self.last_exit<self.config.cooldown_sec and not reversal_ok:
            raise Blocked('Пауза после завершения кампании')
        self.rate_times=[t for t in self.rate_times if now-t<60]
        if len(self.rate_times)>=self.config.max_orders_per_minute:raise Blocked('Предохранитель частоты заявок')
        self.positions=self.broker.positions();self.orders=self.broker.orders();account=self.broker.account()
        if account['key']!=self.account_key:raise Blocked('Счёт изменился перед отправкой')
        self.account=account
        if account.get('type')=='REAL' and not self.real_armed:raise Blocked('REAL не вооружён: сначала ARM REAL')
        if self._owned_orders() or any(p['magic']!=MAGIC for p in self.positions) or any(o['magic']!=MAGIC for o in self.orders):
            raise Blocked('Экспозиция изменилась перед отправкой')
        self._refresh_risk(now)
        if not self.risk.get('allowed'):raise Blocked('Проверка риска не разрешила отправку')
        q=self.broker.quote(self.info['name']);q.validate(now)
        if (q.bid-d.trigger)*d.side<=0 or abs(q.bid-d.trigger)>PROFILES[self.config.mode].no_chase_atr*d.atr:
            raise Blocked('Котировка уже вышла из допустимой зоны входа')
        exec_cfg=self._execution_config()
        p=plan_order(self.broker,exec_cfg,account,self.info,q,d,self._owned(),self.campaign,now)
        new_campaign=not self.campaign
        if new_campaign:
            self.campaign=dict(id=d.event_id,side=d.side,mode=self.config.mode,timeframe=self.config.timeframe,
                symbol=self.info['name'],started=now,budget=exec_cfg.budget(account),initial_risk=p.risk,
                last_entry=p.entry,best_price=p.entry,last_progress=now,invalidation=d.invalidation,
                add_step_atr=PROFILES[self.config.mode].add_step_atr,peak=0.,position_ids=[],realized=0.,events=[],
                entry_class=d.entry_class if d.entry_class!='NONE' else 'CONFIRMED',
                confirmed=d.entry_class!='PROBE',confirmed_at=(now if d.entry_class!='PROBE' else 0.))
        comment='EC1:'+hashlib.sha256(d.event_id.encode()).hexdigest()[:16]
        body=dict(plan=asdict(p),comment=comment,time=now)
        self._consume_event(d.event_id);self.save();self.store.intent(d.event_id,'SENDING',body)
        self.rate_times.append(now)
        try:out=self.broker.send(p,comment)
        except Blocked as e:
            self.store.intent(d.event_id,'REJECTED',dict(body,error=str(e)));raise
        except Exception as e:out=dict(status='UNKNOWN',reason=str(e))
        self.store.event('ORDER_RESPONSE',dict(intent=body,response=out),now)
        if out['status']=='REJECTED':
            self.store.intent(d.event_id,'REJECTED',dict(body,response=out))
            self.execution='MT5 отклонил: '+out.get('reason','');return
        self.store.intent(d.event_id,'UNKNOWN',dict(body,response=out))
        self.positions=self.broker.positions();self.orders=self.broker.orders()
        matches=[x for x in self._owned() if x.get('comment')==comment]
        if out['status']=='FILLED' and matches and not self._owned_orders():
            self.store.intent(d.event_id,'FILLED',dict(body,response=out))
            self.campaign['last_entry']=sum(x['price_open']*x['volume'] for x in matches)/sum(x['volume'] for x in matches)
            self.campaign['position_ids']=sorted(set(self.campaign['position_ids'])|{x['identifier'] for x in matches})
            self.campaign['events'].append(d.event_id)
            if d.entry_class!='PROBE':
                self.campaign['confirmed']=True;self.campaign['entry_class']='CONFIRMED';self.campaign['confirmed_at']=now
            prefix='PROBE ' if d.entry_class=='PROBE' else ''
            if reversal_ok:self.pending_reversal=None
            self.execution='MT5 подтвердил '+prefix+d.signal+': '+', '.join('#'+str(x['ticket']) for x in matches)
            self.save()
            try:
                reserve=max(self.config.slippage_ticks*self.info['tick_size'],q.spread)
                actual=max(0,-float(self.campaign.get('realized',0)))
                for live in self._owned():
                    if live['sl']<=0:raise Blocked('брокер не подтвердил SL')
                    loss=-number(self.broker.calc_profit(live['side'],live['symbol'],live['volume'],
                        live['price_open'],live['sl']-live['side']*reserve),'actual stop risk')
                    actual+=max(0,loss)+float(self.effective_fee_per_lot or 0)*live['volume']
                if sum(x['volume'] for x in matches)>p.volume+1e-8:
                    raise Blocked('подтверждённый объём больше запрошенного')
                if actual>min(self.campaign['budget'],exec_cfg.budget(account))+1e-7:
                    raise Blocked('риск после исполнения превысил бюджет')
                self.campaign['actual_stop_risk']=actual;self.save()
            except Exception as e:
                self.recovery=True;self.auto=False;self.paused=True
                self._close_campaign(str(e))
        else:
            self.recovery=True;self.auto=False;self.paused=True
            self.execution='Результат требует сверки; повторная отправка запрещена';self.save()

    def command(self,command,data=None):
        with self.lock:
            data=data or {};now=self.clock();key=str(data.get('command_id',''))
            if len(key)<8 or len(key)>128:raise Blocked('Нужен уникальный идентификатор команды')
            prior=self.store.command_result(key)
            if prior is not None:return prior
            if command in ('emergency','pause','disable','close'):
                self.pending_reversal=None
                if command=='emergency':self.emergency=True;self.exit_pending=True;self.auto=False;self.paused=True;self.real_armed=False
                elif command=='close':self.exit_pending=True;self.auto=False;self.paused=True
                elif command=='disable':self.auto=False;self.paused=True
                else:self.paused=True
                self.save()
                message='Блокировка сохранена; закрытие проверяется по MT5' if command in ('emergency','close') else 'Новые входы и добавления остановлены; сопровождение продолжается'
            elif command=='adopt_account':
                if data.get('confirmation')!='ADOPT_MT5_ACCOUNT':raise Blocked('Нужно явное подтверждение привязки текущего MT5 счёта')
                self.broker.connect();a=self.broker.account();pos=self.broker.positions();orders=self.broker.orders()
                if self.campaign or self.store.pending():raise Blocked('Нельзя менять счёт при сохранённой кампании/неизвестном исполнении')
                if any(int(p.get('magic',0) or 0)==MAGIC for p in pos) or any(int(o.get('magic',0) or 0)==MAGIC for o in orders):
                    raise Blocked('На текущем счёте уже есть позиции/ордера EC1; нужна ручная сверка')
                if a.get('type') not in ('DEMO','REAL') or a.get('margin_mode')!='HEDGING' or a.get('currency')!='USD':
                    raise Blocked('Можно привязать только USD DEMO/REAL hedging')
                self.account_key=a['key'];self.account=a;self.account_time=now;self.positions=pos;self.orders=orders
                self.recovery=False;self.real_armed=False;self.auto=False;self.paused=True;self.pending_reversal=None
                self.ack=[0,0];self.daily_latch='';self.deals=[];self.history_time=0.;self.history_ok=False;self.history_error='История ещё не получена'
                self.config=replace(self.config,account_mode=a['type'],approved=False,fee_per_lot=None)
                self.strategy=Strategy(self.config);self.compute=ComputeCore(self.config)
                self.strategy.clear();self.compute.clear();self.save()
                message='Текущий MT5 счёт привязан: '+a['type']+'. AUTO выключен'
            elif command=='configure':
                permitted={f.name for f in fields(Config)}-{'approved','technical_position_fuse','max_orders_per_minute'}
                supplied=data.get('config',{})
                if not isinstance(supplied,dict) or set(supplied)-permitted:raise Blocked('Неизвестное поле профиля')
                new=Config(**{**asdict(self.config),**supplied}).validate()
                if self.account and self.account.get('type') in ('DEMO','REAL') and new.account_mode!=self.account.get('type'):
                    raise Blocked('Режим профиля не совпадает с текущим MT5 счётом')
                if self.campaign or self._owned() or self._owned_orders() or self.store.pending():
                    raise Blocked('Профиль фиксирован до завершения кампании')
                new.approved=False;self.auto=False;self.paused=True;self.real_armed=False;self.pending_reversal=None
                self.config=new;self.strategy=Strategy(new);self.compute=ComputeCore(new);self.bars=[];self.context=[];self.last_bars_at=0
                self.m1=[];self.m15=[];self.h1=[];self.live_bar=None
                self.quote=None;self.info={};self.last_market_attempt=-1.;self.bar_errors=[]
                self.market_errors=[];self.market_time=0.;self.quote_ready=False;self.analysis_time=0.
                self.decision=Decision();self.forecast={};self.forecast_side=0;self.forecast_since=0.
                self.save();message='Профиль сохранён. Подтвердите риск; комиссия определяется по режиму счёта'
            elif command=='approve_profile':
                self._refresh(now);actual=self.account.get('type','UNKNOWN')
                expected='APPROVE_REAL_RISK' if actual=='REAL' else 'APPROVE_DEMO_RISK'
                if data.get('confirmation')!=expected:raise Blocked('Нужно явное подтверждение риска '+actual)
                if self.config.account_mode!=actual:raise Blocked('Режим профиля не совпадает с MT5')
                self.config.validate();self._resolve_fee_profile()
                if self.effective_fee_per_lot is None:raise Blocked('Не удалось определить комиссию REAL: укажите один раз или дайте историю сделок по инструменту')
                if self.config.approved:
                    message='Профиль '+actual+' уже подтверждён; состояние AUTO не изменено'
                else:
                    self.config.approved=True;self.auto=False;self.paused=True;self.save()
                    message='Профиль '+actual+' подтверждён; AUTO выключен'
            elif command=='arm_real':
                self._refresh(now)
                if data.get('confirmation')!='ARM_REAL_LIVE':raise Blocked('Нужно явное подтверждение ARM REAL')
                if self.account.get('type')!='REAL' or self.config.account_mode!='REAL':raise Blocked('ARM REAL доступен только на REAL-профиле')
                if self.campaign or self._owned() or self._owned_orders() or self.store.pending():raise Blocked('ARM REAL только при нулевой экспозиции EC1')
                if self.emergency or self.recovery or self.exit_pending:raise Blocked('Сначала снимите блокировки/сверку')
                if not self.config.approved:raise Blocked('Сначала подтвердите REAL-профиль риска')
                if self.effective_fee_per_lot is None:raise Blocked('Комиссия REAL не определена')
                if not self.risk.get('allowed'):raise Blocked('Риск REAL не разрешён: '+','.join(self.risk.get('blocks',[])))
                self.real_armed=True;self.auto=False;self.paused=True
                message='REAL PILOT вооружён до перезапуска Bridge; AUTO пока выключен'
            elif command in ('enable','play'):
                self._refresh(now)
                if self.emergency:raise Blocked('AUTO заблокирован: EMERGENCY. Выполните явную сверку DEMO')
                if self.exit_pending:raise Blocked('AUTO временно заблокирован: ожидается подтверждение закрытия кампании в MT5')
                if self.store.pending():raise Blocked('AUTO временно заблокирован: ожидается подтверждение торгового запроса MT5')
                if self.recovery:raise Blocked('AUTO заблокирован: требуется сверка неизвестного исполнения MT5')
                actual=self.account.get('type','UNKNOWN')
                if self.config.account_mode!=actual:raise Blocked('Режим профиля не совпадает с текущим MT5 счётом')
                if not self.config.approved:raise Blocked('Сначала подтвердите профиль '+actual)
                if actual=='REAL' and not self.real_armed:raise Blocked('REAL не вооружён: сначала ARM REAL')
                if not self.risk.get('allowed'):raise Blocked('Риск не разрешён: '+','.join(self.risk.get('blocks',[])))
                if command=='play' and not self.auto:raise Blocked('PLAY снимает паузу, но не включает AUTO после отключения')
                expected='ENABLE_REAL' if actual=='REAL' else 'ENABLE_DEMO'
                if command=='enable' and data.get('confirmation')!=expected:raise Blocked('Нужно явное разрешение AUTO '+actual)
                self.auto=True;self.paused=False;self.heartbeat=now;self.save();message='AUTO '+actual+' включён; вход только по новому событию'
            elif command=='reset':
                self._refresh(now);self._reconcile()
                actual=self.account.get('type','DEMO');expected='RESET_REAL_FLAT' if actual=='REAL' else 'RESET_DEMO_FLAT'
                if data.get('confirmation')!=expected:raise Blocked('Нужна явная сверка '+actual)
                if self._owned() or self._owned_orders() or self.store.pending():raise Blocked('Есть позиции/ордера или неизвестный запрос: автоматический сброс запрещён')
                if self.risk.get('blocks'):raise Blocked('Сначала разберите блокировки риска')
                self.emergency=False;self.recovery=False;self.exit_pending=False;self.auto=False;self.paused=True;self.real_armed=False;self.pending_reversal=None
                self.strategy.clear();self.compute.clear();self.save();message='Блокировка снята после сверки. AUTO остаётся выключенным'
            elif command=='ack_losses':
                self._refresh(now)
                if data.get('confirmation')!='ACK_LOSS_STREAK_DEMO':raise Blocked('Нужно подтверждение разбора серии')
                if self.positions or self.orders or self.store.pending():raise Blocked('Сначала завершите все позиции и ордера')
                if self.risk.get('blocks')!=['LOSS_STREAK']:raise Blocked('Сброс других защит запрещён')
                if int(data.get('expected_last_deal',0))!=self.risk['last_closing_ticket']:raise Blocked('История изменилась; повторите проверку')
                if now-self.risk['last_closing_time']<max(60,self.config.cooldown_sec):raise Blocked('Пауза после убытка ещё не завершена')
                self.ack=[self.risk['last_closing_time_msc'],self.risk['last_closing_ticket']]
                self.auto=False;self.paused=True;self.save();self._refresh_risk(now)
                message='Серия подтверждена. История сохранена, AUTO выключен'
            else:raise Blocked('Неизвестная команда')
            out=dict(ok=True,message=message,auto=self.auto,paused=self.paused,emergency=self.emergency,real_armed=self.real_armed)
            self.store.event('COMMAND',dict(command=command,result=out),now)
            self.store.command_done(key,out)
            return out

    def snapshot(self):
        from . import VERSION, PROTOCOL, BUILD
        with self.lock:
            q=self.quote;now=self.clock();owned=self._owned()
            return copy.deepcopy(dict(protocol=PROTOCOL,bridge_version=VERSION,bridge_build=BUILD,server_time=now,
                analysis_time=self.analysis_time,account=self.account,account_age=now-self.account_time,config=asdict(self.config),auto=self.auto,paused=self.paused,
                market_time=self.market_time,market_errors=list(self.market_errors),quote_fresh=self.quote_ready and q is not None and -2<=now-q.time_msc/1000<=10,
                risk_scope='MT5_ACCOUNT',foreign_positions=sum(p.get('magic')!=MAGIC for p in self.positions),
                emergency=self.emergency,recovery=self.recovery,exit_pending=self.exit_pending,real_armed=self.real_armed,
                pending_reversal=copy.deepcopy(self.pending_reversal),
                decision=self.decision.json(),execution=self.execution,risk=self.risk,
                forecast=copy.deepcopy(self.forecast),
                fee_profile=dict(fee_per_lot=self.effective_fee_per_lot,source=self.fee_source,key=self.fee_profile_key),
                quote=asdict(q) if q else None,bars=[asdict(b) for b in self.bars[-100:]],
                live_bar=asdict(self.live_bar) if self.live_bar else None,
                live_structure=list(live_structure(self.bars,self.live_bar)) if self.config.timeframe=='M5' else [],
                context_time=self.context[-1].time if self.context else 0,
                positions=owned,all_positions=self.positions,campaign=self.campaign,
                history_ok=self.history_ok and now-self.history_time<15,history_time=self.history_time,
                history_error=self.history_error,all=summary(self.rows),
                today=summary([r for r in self.rows if r['time']>=day_start(now)])))
