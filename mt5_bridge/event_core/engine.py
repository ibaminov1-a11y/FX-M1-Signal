from __future__ import annotations
from dataclasses import asdict, fields, replace
import copy, hashlib, math, threading, time
from .model import Bar, Config, Decision, Blocked, PROFILES, TF_SECONDS, atr, pivots, number, ordered, live_structure, validate_bar_history, bar_close_time
from .strategy import Strategy
from .compute_core import ComputeCore, make_compute
from .risk import risk_state, plan_order, ledger, summary, quantize, day_start, estimate_roundtrip_fee_per_lot, symbol_key, exit_evidence, realized_net
from .mt5_adapter import MAGIC
from .observers import ForecastObservers, CONTEXT, PUBLIC_TIMEFRAMES

# Broker/server candle clocks can cross the M5 boundary slightly before the PC clock.
# The forming M5 stays isolated from confirmed-pivot history; larger future jumps remain blocked.
LIVE_M5_CLOCK_SKEW_SEC=60
MARKET_CLOCK_VERSION='UTC_NATIVE_R51'


class Engine:
    """Single serialized campaign owner. UI never supplies a BUY/SELL command."""
    def __init__(self,broker,store,clock=time.time):
        self.broker=broker;self.store=store;self.clock=clock;self.lock=threading.RLock()
        saved=store.load('engine',{})
        self.broker_clock_identity=broker.clock_identity() if hasattr(broker,'clock_identity') else MARKET_CLOCK_VERSION
        prior_clock=saved.get('broker_clock_identity',MARKET_CLOCK_VERSION)
        if prior_clock!=self.broker_clock_identity:
            if saved.get('campaign') or store.pending():
                raise Blocked('Смена часов MT5 допустима только без сохранённой кампании и неизвестного исполнения')
            broker.connect()
            if broker.positions() or broker.orders():
                raise Blocked('Смена часов MT5 допустима только без открытых позиций и заявок')
            # Observation times are meaningful only within their original clock policy.
            saved['compute']={};saved['strategy']={}
        self.config=Config(**saved.get('config',{})).validate()
        self.account_key=saved.get('account_key','')
        self.history_model_version=saved.get('history_model_version','UNVERIFIED')
        self.loaded_legacy_scenarios=bool(saved.get('compute',{}).get('scenarios')) and self.history_model_version!=MARKET_CLOCK_VERSION
        self.history_migration={}
        self.quote_diagnostics={}
        self.chart_market=None;self.last_chart_attempt=-1.
        self.real_armed=False
        # Ephemeral by design: never resurrect a reversal after Bridge restart.
        self.pending_reversal=None
        self.reversal_status={}
        self.pending_config=copy.deepcopy(saved.get('pending_config'))
        if self.pending_config:
            self.pending_config['approved']=False  # A restart never restores consent to trade.
        self.campaign_history_cache={}
        self.reconcile_detail=''

        self.effective_fee_per_lot=None;self.fee_source='UNRESOLVED';self.fee_profile_key=''
        self.campaign=saved.get('campaign')
        self.emergency=bool(saved.get('emergency',False))
        self.recovery=bool(saved.get('recovery',False))
        self.daily_latch=saved.get('daily_latch','')
        self.ack=saved.get('ack',[0,0]);self.last_exit=float(saved.get('last_exit',0))
        self.auto=False;self.paused=True;self.heartbeat=0.
        self.exit_pending=bool(saved.get('exit_pending',False))
        self.strategy=Strategy(self.config,saved.get('strategy'))
        self.compute=make_compute(self.config,saved.get('compute'))
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
        self._history_loaded=set();self._history_fingerprint={}
        self.analysis_time=0.;self.decision=Decision();self.execution='AUTO выключен: только анализ'
        self.forecast={};self.forecast_side=0;self.forecast_since=0.
        self.rate_times=[];self.next_close=0.;self.last_persist=0.;self.last_audit_key=None
        self.observers=ForecastObservers()
        self.save()

    def save(self):
        self.store.save('engine',dict(config=asdict(self.config),account_key=self.account_key,
            campaign=self.campaign,emergency=self.emergency,recovery=self.recovery,
            daily_latch=self.daily_latch,ack=self.ack,last_exit=self.last_exit,
            exit_pending=self.exit_pending,pending_config=self.pending_config,
            history_model_version=self.history_model_version,
            broker_clock_identity=self.broker_clock_identity,
            strategy=self.strategy.state(),compute=self.compute.state()))

    def _consume_event(self,event_id):
        if self.config.engine_mode in ('COMPUTE_V1','SCENARIO_V2'):self.compute.consume(event_id)
        else:self.strategy.consume(event_id)

    def market_scope(self):
        scope=(self.account_key or 'UNBOUND')+'|'+symbol_key(self.config.symbol)
        if self.broker_clock_identity!=MARKET_CLOCK_VERSION:
            scope+='|'+self.broker_clock_identity
        return scope

    def _evaluate_compute(self,now):
        extra={}
        if self.config.engine_mode=='SCENARIO_V2':
            extra['clock_generation']=self.broker_clock_identity
            extra['market_scope']=self.market_scope()
            extra['context']=self.context
            extra['context_tf']=CONTEXT[self.config.timeframe]
            extra['campaign']=self.campaign if (self.auto and not self.paused and not self.emergency
                and not self.recovery and not self.exit_pending and not self.pending_config
                and (self.config.dynamic_adds or self.config.runtime_model=='R7' or (self.config.mode=='SCALP' and self.config.timeframe=='M1'))
                and self._owned()) else None
        return self.compute.evaluate(self.bars,self.m1,self.m15,self.h1,self.live_bar,self.quote,now,
            self.campaign['side'] if self.campaign else 0,**extra)

    def _archive_scenarios(self,now):
        if self.config.engine_mode!='SCENARIO_V2':return
        price_forecast=self.forecast.get('price_forecast',{})
        if price_forecast.get('available'):
            self.store.save_price_forecast(price_forecast)
            self.store.settle_price_forecasts(price_forecast['scope'],self.quote,now)
        for snapshot in self.compute.pending_snapshots:
            self.store.save_scenario_snapshot(self.market_scope(),snapshot,now)
        self.compute.pending_snapshots.clear()
        for event in self.compute.events:self.store.event('SCENARIO_EVENT',event,event['time'])
        self.compute.events.clear()

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
        prior_volumes={int(p.get('identifier',p['ticket'])):float(p['volume']) for p in self._owned()}
        current_volumes={int(p.get('identifier',p['ticket'])):float(p['volume']) for p in current_positions if p['magic']==MAGIC}
        volume_decreased=any(current_volumes.get(pid,0)<volume-1e-8 for pid,volume in prior_volumes.items())
        self.account=a;self.account_time=now;self.positions=current_positions;self.orders=current_orders
        if self.account_key and a['key']!=self.account_key:
            # The account snapshot now identifies the newly selected MT5 account.
            # Never publish the bound account's money/history under that identity.
            # Keep campaign-specific reconciliation data for a return to its account.
            self.deals=[];self.rows=[];self.history_ok=False;self.history_time=0.
            self.history_error='Счёт MT5 изменён; история текущего счёта не подтверждена'
            self.risk={'allowed':False,'blocks':['ACCOUNT_CHANGED'],'message':self.history_error}
            self.auto=False;self.paused=True;self.recovery=True;self.real_armed=False;self.save()
            raise Blocked('Счёт MT5 изменён; привяжите текущий счёт в настройках EventCore')
        if not self.account_key:self.account_key=a['key'];self.save()
        if a['type'] not in ('DEMO','REAL') or a['margin_mode']!='HEDGING' or a['currency']!='USD':
            self.auto=False;self.paused=True;self.real_armed=False
            raise Blocked('Поддерживаются USD DEMO/REAL hedging; contest/netting/другая валюта пока запрещены')
        flat_campaign=bool(self.campaign and not self._owned() and not self._owned_orders() and not self.store.pending())
        history_interval=1.0 if self.exit_pending or flat_campaign or self._campaign_volume_pending() else 10.0
        if volume_decreased or not self.history_time or now-self.history_time>=history_interval:
            self._refresh_history(now)
        self._resolve_fee_profile()
        self._refresh_risk(now)

    def _refresh_history(self,now):
        try:
            self.deals=self.broker.history(now)
            self._campaign_history()
            self.history_time=now;self.history_ok=True;self.history_error=''
        except Exception as exc:
            self.history_ok=False;self.history_time=now;self.history_error=str(exc)

    def _campaign_volume_pending(self):
        """A current position snapshot is not proof of the money on missing volume."""
        if not self.campaign:return False
        ids={int(pid) for pid in self.campaign.get('position_ids',[])}
        expected={pid:0. for pid in ids};opened=set()
        for d in self.deals:
            pid=int(d.get('position_id',0))
            if pid not in ids or d.get('type') not in (0,1):continue
            if d.get('entry')==0:
                expected[pid]+=float(d['volume']);opened.add(pid)
            elif d.get('entry') in (1,3):expected[pid]-=float(d['volume'])
        live={int(p.get('identifier',p['ticket'])):float(p['volume']) for p in self._owned()}
        return bool(ids-opened or any(abs(expected[pid]-live.get(pid,0))>1e-8 for pid in ids))

    def _campaign_history(self):
        # Date-range history can miss a close when broker time is ahead of PC time.
        # Fetch the actual position ID; never delete a campaign just because positions=0.
        if not self.campaign_history_cache and not hasattr(self.broker,'history_position'):return
        merged={int(d['ticket']):d for d in self.deals}
        merged.update(self.campaign_history_cache)
        self.reconcile_detail=''
        if self.campaign and hasattr(self.broker,'history_position'):
            live={int(p.get('identifier',p['ticket'])):float(p['volume']) for p in self._owned()}
            for pid in self.campaign.get('position_ids',[]):
                relevant=[d for d in merged.values() if int(d.get('position_id',0))==int(pid)]
                opened=sum(float(d['volume']) for d in relevant if d.get('entry')==0)
                closed=sum(float(d['volume']) for d in relevant if d.get('entry') in (1,3))
                if opened>0 and abs(opened-closed-live.get(int(pid),0))<=1e-8:continue
                try:
                    rows=self.broker.history_position(int(pid))
                    if rows is None:raise Blocked('MT5 не вернул историю позиции')
                    for d in rows:
                        if int(d.get('position_id',0))==int(pid):
                            self.campaign_history_cache[int(d['ticket'])]=d
                            merged[int(d['ticket'])]=d
                except Exception as exc:
                    self.reconcile_detail='История позиции #'+str(pid)+': '+str(exc)
        self.deals=sorted(merged.values(),key=lambda d:(d['time_msc'],d['ticket']))

    def _apply_pending_config(self,now):
        if not self.pending_config or self._has_exit_targets() or not self.history_ok:return False
        new=Config(**self.pending_config).validate()
        if new.account_mode!=self.account.get('type'):return False
        keep_auto=self.auto and new.approved and not self.emergency and not self.recovery
        self.config=new;self.pending_config=None
        self.chart_market=None;self.last_chart_attempt=-1.
        self.strategy=Strategy(new);self.compute=make_compute(new)
        self.bars=[];self.context=[];self.m1=[];self.m15=[];self.h1=[];self.live_bar=None
        self.quote=None;self.info={};self.quote_ready=False;self.last_market_attempt=-1.
        self.last_bars_at=0.;self.bar_errors=[];self.market_errors=[]
        self.forecast={};self.decision=Decision();self.analysis_time=0.
        self.auto=bool(keep_auto)
        if not keep_auto:self.paused=True
        self._resolve_fee_profile();self._refresh_risk(now)
        self.store.event('PROFILE_APPLIED',dict(engine_mode=new.engine_mode,auto=self.auto),now)
        self.save();return True

    def _entry_gate(self):
        blocks=[]
        if getattr(self,'entry_inhibited',lambda:False)():blocks.append('CONTROL_PENDING')
        if self.emergency:blocks.append('EMERGENCY')
        if self.recovery or self.store.pending():blocks.append('RECOVERY')
        if not self.auto:blocks.append('AUTO_OFF')
        elif self.paused:blocks.append('PAUSE')
        if self.pending_config:blocks.append('PROFILE_PENDING')
        if self.exit_pending:blocks.append('CLOSING')
        if self.campaign and (not self._owned() or self._campaign_volume_pending()):blocks.append('RECONCILING')
        if not self.history_ok or self.clock()-self.history_time>15:blocks.append('HISTORY_WAIT')
        if not self.risk.get('allowed',False):blocks.append('RISK_WAIT')
        if self.market_errors or not self.quote_ready:blocks.append('MARKET_WAIT')
        labels={'CONTROL_PENDING':'принята остановка; ждём применения управления','EMERGENCY':'аварийная блокировка','RECOVERY':'сверка неизвестного исполнения',
            'AUTO_OFF':'AUTO выключен','PAUSE':'пауза','PROFILE_PENDING':'новый профиль ждёт завершения прежней кампании',
            'CLOSING':'ждём подтверждения закрытия MT5','RECONCILING':'сверяем объём кампании и закрытые сделки в истории MT5',
            'HISTORY_WAIT':'ожидаем историю MT5','RISK_WAIT':'проверка риска не разрешает вход',
            'MARKET_WAIT':'ожидаем свежие рыночные данные'}
        return dict(allowed=not blocks,blocks=blocks,
            reason='; '.join(labels[b] for b in blocks) if blocks else 'ожидание нового подтверждённого входа')

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
            self.campaign['realized']=realized_net(d for d in self.deals if d.get('position_id') in ids)
            if not owned and not self._owned_orders() and not self.store.pending():
                closed_ids={row['position_id'] for row in ledger(self.deals,self.positions)}
                if not ids.issubset(closed_ids):
                    self.history_time=0.
                    self.execution='Позиций EC1 нет; ожидается подтверждение закрытия в истории MT5'
                    return False
                self.campaign['end']=self.clock()
                self.campaign['net']=sum(d['profit']+d.get('swap',0)+d.get('commission',0)+d.get('fee',0)
                    for d in self.deals if d.get('position_id') in ids)
                self.campaign['broker_exit']=exit_evidence(d for d in self.deals if d.get('position_id') in ids)
                self.campaign['broker_exit_recorded_at']=self.clock()
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
        if hasattr(self.compute,'suspend'):self.compute.suspend()
        setup=self.strategy.setup
        if setup:
            setup.seen_safe_side=False
            setup.armed_msc=max(setup.armed_msc,int(now*1000))

    def _prepare_market_history(self,now):
        result=self.store.ensure_market_clock(self.market_scope(),MARKET_CLOCK_VERSION,now)
        if result['changed'] or self.loaded_legacy_scenarios:
            self.history_migration=result
            self._history_loaded.clear();self._history_fingerprint.clear();self.last_market_attempt=-1.
            self.bars=[];self.m1=[];self.m15=[];self.h1=[];self.context=[];self.live_bar=None
            # Do not change any live campaign, stop, monetary record or intent.
            if result['quarantined'] or self.loaded_legacy_scenarios:
                self._cancel_reversal('Обновление непроверенной рыночной истории',now)
                self.strategy.clear()
                consumed=self.compute.state().get('consumed',[])
                self.compute=make_compute(self.config,{'consumed':consumed})
                self.forecast={};self.decision=Decision()
            self.history_model_version=MARKET_CLOCK_VERSION;self.loaded_legacy_scenarios=False
            self.store.event('MARKET_CACHE_MIGRATION',dict(scope=self.market_scope(),**result),now)
            self.save()

    def _refresh_market(self,now):
        self.observers.sync(self)
        self.market_errors=[];self.quote_ready=False
        try:
            self.info=self.broker.symbol(self.config.symbol)
        except Exception as exc:
            self.market_errors=['Инструмент MT5 недоступен: '+str(exc)]
            self.chart_market=None
            return
        symbol=self.info['name']
        try:
            self.quote=self.broker.quote(symbol)
            self.quote.validate(now)
            self.quote_ready=True
        except Exception as exc:
            self.market_errors.append('Нет пригодной свежей котировки: '+str(exc))
        if hasattr(self.broker,'quote_diagnostics'):
            self.quote_diagnostics=self.broker.quote_diagnostics(symbol)
        if not self.quote_ready:
            # A stale/first tick cannot establish a candle clock or contaminate SQLite.
            self._refresh_chart_market(now)
            return
        self._prepare_market_history(now)
        if self.last_market_attempt<0 or now-self.last_market_attempt>=1:
            self.last_market_attempt=now;self.bar_errors=[]
            layers=(('bars',self.config.timeframe),('context',CONTEXT[self.config.timeframe]))
            scenario=self.config.engine_mode=='SCENARIO_V2'
            if scenario:
                layers=(('bars',self.config.timeframe),('m1','M1'),('m15','M15'),('h1','H1'),
                        ('context',CONTEXT[self.config.timeframe]))
            elif self.config.timeframe=='M5':
                layers=(('m1','M1'),('bars','M5'),('m15','M15'),('h1','H1'))
            loaded={}
            for attr,tf in layers:
                try:
                    if tf in loaded:
                        setattr(self,attr,loaded[tf])
                        continue
                    history_key=(self.market_scope(),tf)
                    if history_key not in self._history_loaded and hasattr(self.broker,'history_bars'):
                        values=list(self.broker.history_bars(symbol,tf,1200))
                    else:
                        values=list(self.broker.bars(symbol,tf))
                    if not values:
                        raise Blocked('MT5 вернул пустую историю '+tf)
                    validate_bar_history(values,tf,now)
                    fingerprint=tuple((b.time,b.open,b.high,b.low,b.close,b.volume,b.clock_offset_seconds) for b in values)
                    if self._history_fingerprint.get(history_key)!=fingerprint:
                        self.store.save_bars(self.market_scope(),tf,values,now)
                        self._history_fingerprint[history_key]=fingerprint
                    if self.config.engine_mode=='SCENARIO_V2':
                        values=[Bar(**row) for row in self.store.read_bars(self.market_scope(),tf,limit=1200)]
                    validate_bar_history(values,tf,now)
                    setattr(self,attr,values)
                    loaded[tf]=values
                    self._history_loaded.add(history_key)
                    self.observers.remember(tf,values,now)
                except Exception as exc:
                    error='История '+tf+' не обновлена: '+str(exc)
                    self.bar_errors.append(error)
                    self.observers.remember(tf,[],now,error)
            if scenario or self.config.timeframe=='M5':
                if not scenario:self.context=self.m15
                live_tf=self.config.timeframe
                try:
                    live=self.broker.current_bar(symbol,live_tf)
                    if live.time>now+LIVE_M5_CLOCK_SKEW_SEC:
                        raise Blocked('MT5 вернул текущую '+live_tf+' свечу из будущего')
                    if self.bars and live.time<=self.bars[-1].time:
                        raise Blocked('Текущая '+live_tf+' свеча не следует за закрытой историей')
                    self.live_bar=live
                except Exception as exc:
                    self.live_bar=None
                    self.bar_errors.append('Текущая '+live_tf+' свеча не обновлена: '+str(exc))
            else:
                self.m1=[];self.m15=[];self.h1=[];self.live_bar=None
            if not self.bar_errors:
                self.last_bars_at=now;self.market_time=now
        self.market_errors.extend(self.bar_errors)
        ctf=CONTEXT[self.config.timeframe]
        if not self.bars or not self.context:
            self.market_errors.append('Нет полной истории рабочего и старшего таймфреймов')
        elif now-bar_close_time(self.context[-1].time,ctf,self.context[-1].clock_offset_seconds)>TF_SECONDS[ctf]*1.5:
            self.market_errors.append('Контекст старшего таймфрейма устарел')
        if self.bars:
            tf=TF_SECONDS[self.config.timeframe]
            if now-bar_close_time(self.bars[-1].time,self.config.timeframe,self.bars[-1].clock_offset_seconds)>tf*1.5:
                self.market_errors.append('Закрытые свечи MT5 исторические; для входа нужны новые данные')
        if self.market_errors:self._refresh_chart_market(now)
        else:self.chart_market=None

    def _refresh_chart_market(self,now):
        """Keep display candles available while all execution gates stay closed."""
        if not hasattr(self.broker,'chart_snapshot'):
            self.chart_market=None;return
        symbol=self.info.get('name',self.config.symbol)
        identity=(self.market_scope(),symbol,self.config.timeframe)
        previous=self.chart_market or {}
        same=(previous.get('scope'),previous.get('symbol'),previous.get('timeframe'))==identity
        if same and 0<=now-self.last_chart_attempt<1:return
        self.last_chart_attempt=now
        reason='; '.join(self.market_errors)
        q=self.quote
        bad_clock=q is not None and now-q.time_msc/1000 < -2
        view=dict(scope=identity[0],symbol=symbol,timeframe=self.config.timeframe,
            read_only=True,clock='MT5_RAW',status='UNVERIFIED_TIME' if bad_clock else 'UNVERIFIED',
            reason=reason,received_at=now,bars=[],live_bar=None)
        try:
            raw=self.broker.chart_snapshot(symbol,self.config.timeframe,1200)
            view['clock_identity']=raw.get('clock_identity',self.broker_clock_identity)
            view['offset_minutes']=raw.get('offset_minutes',0)
            view['bars']=[asdict(b) for b in raw['bars']]
            view['live_bar']=asdict(raw['live_bar']) if raw.get('live_bar') else None
        except Exception as exc:
            # Never borrow another instrument's candles or pretend a failed read succeeded.
            view['reason']+='; График MT5 не обновлён: '+str(exc)
        self.chart_market=view

    def refresh_view(self):
        """Force data reads for pull-to-refresh, without running order dispatch.

        The autonomous worker owns signal transitions and execution. This path
        neither resumes it nor turns a UI gesture into an extra trading cycle.
        """
        with self.lock:
            now=self.clock();self.history_time=0.;self.last_market_attempt=-1.;self.last_chart_attempt=-1.
            self._refresh(now)
            self._refresh_market(now)
            result=self.snapshot()
            errors=list(self.market_errors)
            if not self.history_ok:errors.append('История сделок не обновлена: '+self.history_error)
            if self.market_errors:
                result['decision']=Decision(phase='DATA_BLOCK',reason='; '.join(self.market_errors)).json()
                result['forecast'].update(stale=True,available=False,reason='; '.join(self.market_errors))
            result.update(refresh_time=now,refresh_errors=errors)
            return result

    def _reversal_enabled(self):
        # This feature is a DEMO continuation, never an implicit permission for REAL.
        return bool(self.config.engine_mode in ('COMPUTE_V1','SCENARIO_V2') and self.auto and not self.paused
                    and not self.emergency and not self.recovery and not self.store.pending()
                    and self.account.get('type')=='DEMO' and self.config.account_mode=='DEMO'
                    and self.history_ok and self.risk.get('allowed',False))

    def _cancel_reversal(self,reason,now):
        if self.pending_reversal is None:return
        self.reversal_status=dict(self.pending_reversal,status='CANCELLED',reason=reason,updated=now)
        self.store.event('REVERSAL_CANCELLED',self.reversal_status,now)
        self.pending_reversal=None

    def _queue_reversal(self,now,decision=None):
        if (self.pending_reversal or not self.campaign or self.exit_pending
                or not self._reversal_enabled()):return
        side=-self.campaign['side']
        confirmed=bool(decision is not None and decision.phase=='ENTRY_READY'
                       and decision.side==side and decision.signal in ('BUY','SELL'))
        self.pending_reversal=dict(side=side,from_side=self.campaign['side'],created=now,
            expires=now+20.0,source_campaign=self.campaign['id'],account_key=self.account_key,
            symbol=self.campaign['symbol'],source_event=decision.event_id if confirmed else '',
            signal='BUY' if side==1 else 'SELL',confirmed=confirmed,status='WAITING_CLOSE')
        self.reversal_status=copy.deepcopy(self.pending_reversal)
        self.store.event('REVERSAL_QUEUED',self.pending_reversal,now)

    def _update_reversal(self,decision,now):
        pr=self.pending_reversal
        if pr is None:return
        if not self._reversal_enabled():
            self._cancel_reversal('AUTO/профиль/проверка риска больше не разрешают разворот',now);return
        if now>float(pr['expires']):
            self._cancel_reversal('Срок подтверждения разворота истёк',now);return
        current_symbol=self.info.get('name',self.config.symbol)
        if pr['account_key']!=self.account_key or symbol_key(pr['symbol'])!=symbol_key(current_symbol):
            self._cancel_reversal('Счёт или инструмент изменился',now);return
        if decision is None or not self.quote_ready or self.market_errors:
            self._cancel_reversal('Нет свежего подтверждения рынка',now);return
        ready=bool(decision.phase=='ENTRY_READY' and decision.signal in ('BUY','SELL')
                   and decision.side==int(pr['side']))
        if pr['confirmed'] and (not ready or decision.event_id!=pr['source_event']):
            self._cancel_reversal('Подтверждённый противоположный вход больше не актуален',now);return
        if not pr['confirmed'] and decision.phase=='ENTRY_READY' and decision.side==pr['from_side']:
            self._cancel_reversal('Первоначальное направление восстановилось',now);return
        if ready and not pr['confirmed']:
            pr['confirmed']=True;pr['source_event']=decision.event_id
            self.store.event('REVERSAL_CONFIRMED',pr,now)
        pr['status']=('WAITING_CLOSE' if self.campaign or self.exit_pending or self._owned()
                      or self._owned_orders() else 'READY' if ready else 'WAITING_SIGNAL')
        self.reversal_status=copy.deepcopy(pr)

    def _close_campaign(self,reason,code='EXIT'):
        if not self._has_exit_targets():
            self.exit_pending=False
            self.execution=self._idle_status()
            self.save()
            return
        if code=='SCENARIO_INVALIDATED':self._queue_reversal(self.clock())
        if self.campaign and not self.campaign.get('exit_reason'):
            self.campaign.update(exit_reason=reason,exit_code=code,exit_requested_at=self.clock())
            self.store.event('EXIT_REQUESTED',dict(campaign=self.campaign['id'],reason=reason,code=code),self.clock())
        if self.campaign:reason=self.campaign.get('exit_reason',reason)
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
            try:result=self.broker.close_position(p)
            except Blocked as exc:result=dict(status='REJECTED',reason=str(exc))
            except Exception as exc:result=dict(status='UNKNOWN',reason=str(exc))
            self.store.event('CLOSE_RESPONSE',dict(ticket=p['ticket'],result=result),now)
            if result['status']!='FILLED':
                self.execution='Закрытие пока не подтверждено: '+result.get('reason','')
                if result['status']=='UNKNOWN':
                    self.recovery=True;self.auto=False;self.paused=True
                    self._cancel_reversal('Закрытие MT5 имеет неизвестный результат',now)
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
            self._close_campaign('слом уровня отмены сценария','SCENARIO_INVALIDATED');return True
        plan=c.get('forecast_at_entry',{})
        if plan.get('execution_policy')=='STABLE_V1':
            target=plan.get('entry_target1');expires=plan.get('plan_expires')
            if target and (mark-float(target))*side>=0:
                self._close_campaign('достигнута исходная целевая зона','PLAN_TARGET');return True
            if expires and now>float(expires):
                self._close_campaign('срок исходного плана завершён','PLAN_EXPIRED');return True
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
        inbox=self.__dict__.get('control_inbox')
        if inbox:inbox.drain()
        with self.lock:
            now=self.clock()
            try:
                self._refresh(now)
                just_closed=self._reconcile()
                profile_changed=self._apply_pending_config(now)
                exit_cycle=bool(just_closed or self.emergency or self.exit_pending)
                if self.emergency or self.exit_pending:
                    try:
                        self._close_campaign('Emergency' if self.emergency else 'ожидаем завершения')
                    except Exception as exc:
                        self.execution='Закрытие EC1 пока не подтверждено: '+str(exc)
                self._refresh_market(now)
                if self.config.entry_model not in ('STABLE_V1','PINNED_V1'):self._refresh_observers(now)
                compute_decision=None
                if not self.market_errors and self.quote_ready:
                    try:
                        if self.config.engine_mode in ('COMPUTE_V1','SCENARIO_V2'):
                            compute_decision=self._evaluate_compute(now)
                            self.forecast=copy.deepcopy(compute_decision.forecast)
                            self._archive_scenarios(now)
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
                if self.config.engine_mode=='SCENARIO_V2' and compute_decision is None:
                    cached=copy.deepcopy(getattr(self.compute,'last_forecast',{}))
                    if cached:
                        cached.update(stale=True,available=False,reason='Нет свежего расчёта; сохранённая карта не разрешает вход')
                        self.forecast=cached
                self._update_reversal(compute_decision,now)
                if (not exit_cycle and self.campaign and compute_decision is not None and
                    compute_decision.phase=='ENTRY_READY' and compute_decision.side in (-1,1) and
                    compute_decision.side!=self.campaign['side']):
                    self._queue_reversal(now,compute_decision)
                if exit_cycle:
                    # Track live prices during a valid close, but never submit an order here.
                    if not self.pending_reversal:self._suspend_trigger(now)
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
                if self.config.engine_mode in ('COMPUTE_V1','SCENARIO_V2'):
                    d=compute_decision if compute_decision is not None else self._evaluate_compute(now)
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
                    if self.config.engine_mode in ('COMPUTE_V1','SCENARIO_V2'):
                        self._queue_reversal(now,d)
                    elif d.event_id:
                        self._consume_event(d.event_id);self.save()
                    self._close_campaign('подтверждён разворот '+d.signal+' против текущей '+old+' кампании',
                                         'OPPOSITE_CONFIRMED')
                    return self.snapshot()
                if not self.auto or self.paused:self.execution=self._idle_status()
                elif self.pending_config:self.execution='AUTO включён · '+self._entry_gate()['reason']
                elif self.recovery:self.execution='Нужна сверка неизвестного исполнения; новые входы запрещены'
                elif not self.risk.get('allowed',False):self.execution=self._idle_status()
                elif not self._session_allowed(now):self.execution='Текущая сессия не разрешена выбранным фильтром'
                elif d.signal=='WAIT':
                    self.execution=d.reason if self.config.engine_mode in ('COMPUTE_V1','SCENARIO_V2') else (
                        ('LIVE forecast '+('BUY' if int(self.forecast.get('side',0) or 0)==1 else 'SELL')+
                         f" {float(self.forecast.get('confidence',0) or 0)*100:.0f}%; вход ещё не готов")
                        if int(self.forecast.get('side',0) or 0) else 'Нет нового подтверждённого входа; ордер не отправлен')
                else:
                    try:self._entry(d,now)
                    except Blocked as exc:
                        self.store.event('ENTRY_BLOCKED',dict(event_id=d.event_id,reason=str(exc),
                            addition=bool(self.campaign),mode=self.config.mode),now)
                        if self.config.entry_model in ('STABLE_V1','PINNED_V1'):
                            self.execution='Вход пока не исполнен: '+str(exc)
                            self.decision=replace(d,signal='WAIT',phase='ENTRY_BLOCKED',reason=str(exc))
                        else:raise
            except Exception as e:
                self._cancel_reversal('Ошибка проверки данных/исполнения: '+str(e),now)
                self._suspend_trigger(now)
                self.execution=str(e)+'\n'+self._idle_status()
                if self.exit_pending:
                    self.execution+='\nВыход собственных позиций EC1 ещё не завершён'
                detail=str(e)
                if self.bars:
                    detail+='\nПоказаны последние доступные закрытые свечи MT5; это не свежий торговый сигнал'
                self.decision=Decision(phase='DATA_BLOCK',reason=detail)
            if self.config.entry_model in ('STABLE_V1','PINNED_V1'):
                try:self._refresh_observers(self.clock())
                except Exception as exc:self.store.event('OBSERVER_ERROR',dict(reason=str(exc)),self.clock())
            return self.snapshot()

    def _entry(self,d,now):
        if getattr(self,'entry_inhibited',lambda:False)():raise Blocked('Принята остановка; новые заявки запрещены')
        if self.pending_config:raise Blocked('Новый профиль ожидает подтверждённого завершения кампании')
        if self.emergency or self.exit_pending or self.recovery or self.store.pending():
            raise Blocked('Вход заблокирован состоянием кампании')
        if self.store.has_intent(d.event_id):raise Blocked('Повтор торгового события запрещён')
        if self.config.entry_model=='PINNED_V1':
            root=self.campaign.get('scenario_id') if self.campaign else self.compute.commitment.ident
            expected=d.forecast.get('entry_parent_scenario_id') if self.campaign else d.forecast.get('entry_scenario_id')
            if not root or root!=expected:raise Blocked('Событие не относится к закреплённому плану исполнения')
        if self._owned_orders():raise Blocked('Предыдущий запрос ещё не завершён')
        if any(p['magic']!=MAGIC for p in self.positions) or any(o['magic']!=MAGIC for o in self.orders):
            raise Blocked('Есть ручные/старые позиции или ордера: сначала завершите их отдельно')
        reversal_ok=bool(self._reversal_enabled() and not self.campaign and self.pending_reversal and
                         not self._owned() and now<=float(self.pending_reversal.get('expires',0)) and
                         self.pending_reversal.get('confirmed',False) and
                         self.pending_reversal.get('source_event')==d.event_id and
                         self.pending_reversal.get('account_key')==self.account_key and
                         int(self.pending_reversal.get('side',0))==d.side)
        if now-self.last_exit<self.config.cooldown_sec and not reversal_ok:
            raise Blocked('Пауза после завершения кампании')
        self.rate_times=[t for t in self.rate_times if now-t<60]
        if len(self.rate_times)>=self.config.max_orders_per_minute:raise Blocked('Предохранитель частоты заявок')
        self.positions=self.broker.positions();self.orders=self.broker.orders();account=self.broker.account()
        if account['key']!=self.account_key:raise Blocked('Счёт изменился перед отправкой')
        self.account=account
        if account.get('type')=='REAL' and not self.real_armed:raise Blocked('REAL не вооружён: сначала ARM REAL')
        if (self._owned_orders() or (not self.campaign and self._owned()) or
            any(p['magic']!=MAGIC for p in self.positions) or any(o['magic']!=MAGIC for o in self.orders)):
            raise Blocked('Экспозиция изменилась перед отправкой')
        if self.campaign:
            # A leg can close between the regular history poll and this addition.
            # Reconcile its money and volume before evaluating net profit or risk.
            self._refresh_history(now)
            if not self.history_ok:raise Blocked('История кампании не обновлена: '+self.history_error)
            self._reconcile()
            if not self.campaign or self._campaign_volume_pending():
                raise Blocked('Добавление ждёт сверки объёма кампании в истории MT5')
        self._refresh_risk(now)
        if not self.risk.get('allowed'):raise Blocked('Проверка риска не разрешила отправку')
        q=self.broker.quote(self.info['name']);q.validate(now)
        no_chase=PROFILES[self.config.mode].no_chase_atr
        if self.config.engine_mode in ('COMPUTE_V1','SCENARIO_V2'):no_chase=min(no_chase,self.compute.MAX_CHASE_ATR)
        if (q.bid-d.trigger)*d.side<=0 or abs(q.bid-d.trigger)>no_chase*d.atr:
            raise Blocked('Котировка уже вышла из допустимой зоны входа')
        if self.config.engine_mode=='SCENARIO_V2' and d.forecast.get('entry_target1') is not None:
            target=number(d.forecast['entry_target1'],'scenario target',positive=True)
            if (target-(q.ask if d.side>0 else q.bid))*d.side<=0:
                raise Blocked('Исполнимая цена уже за ближайшей целью сценария; вход отменён')
        exec_cfg=self._execution_config()
        p=plan_order(self.broker,exec_cfg,account,self.info,q,d,self._owned(),self.campaign,now)
        if hasattr(self.broker,'preflight'):self.broker.preflight(p,exec_cfg)
        # Broker preflight calls may block. Recheck wall-clock freshness/expiry,
        # not merely the timestamp captured at the beginning of this engine step.
        send_now=self.clock()
        q.validate(send_now)
        if getattr(self,'entry_inhibited',lambda:False)():raise Blocked('Принята остановка во время проверки; заявка не отправлена')
        if reversal_ok and send_now>float(self.pending_reversal['expires']):
            raise Blocked('Срок разворота истёк во время проверки исполнения')
        if d.forecast.get('entry_expires') and send_now>float(d.forecast['entry_expires']):raise Blocked('Срок подтверждения истёк; заявка не отправлена')
        new_campaign=not self.campaign
        if new_campaign:
            self.campaign=dict(id=d.event_id,side=d.side,mode=self.config.mode,timeframe=self.config.timeframe,
                symbol=self.info['name'],started=now,budget=exec_cfg.budget(account),initial_risk=p.risk,
                last_entry=p.entry,best_price=p.entry,last_progress=now,invalidation=d.invalidation,
                add_step_atr=PROFILES[self.config.mode].add_step_atr,peak=0.,position_ids=[],realized=0.,events=[],
                entry_class=d.entry_class if d.entry_class!='NONE' else 'CONFIRMED',
                confirmed=d.entry_class!='PROBE',confirmed_at=(now if d.entry_class!='PROBE' else 0.),
                entry_trigger=d.trigger,initial_invalidation=d.invalidation,
                forecast_at_entry=copy.deepcopy(d.forecast),
                scenario_id=d.forecast.get('entry_scenario_id'),scenario_version=d.forecast.get('entry_scenario_version'),
                scenario_type=d.forecast.get('entry_type'),snapshot_id=d.forecast.get('snapshot_id'),
                requested_volume=self.config.lot_cap,volume_mode=self.config.volume_mode)
        if new_campaign and self.config.engine_mode=='SCENARIO_V2':
            key=d.forecast.get('snapshot_id')
            if key:
                self.store.save_scenario_snapshot(self.market_scope(),dict(snapshot_id=key,
                    forecast=copy.deepcopy(d.forecast),bars=[asdict(b) for b in self.bars[-120:]],
                    symbol=self.config.symbol,timeframe=self.config.timeframe,data_asof=now,
                    entry_scenario_id=d.forecast.get('entry_scenario_id')),now)
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
            if reversal_ok:
                self.reversal_status=dict(self.pending_reversal,status='OPENED',updated=now)
                self.store.event('REVERSAL_OPENED',self.reversal_status,now)
                self.pending_reversal=None
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

    def _check_control_receipt(self,data):
        deadline=data.get('_receipt_expires',0)
        if deadline and self.clock()>float(deadline):
            raise Blocked('Срок отложенной команды истёк; подтвердите текущий выбор заново')
        account=data.get('_receipt_account')
        if deadline and account and self.account.get('key')!=account:
            raise Blocked('Счёт изменился во время применения команды')

    def command(self,command,data=None):
        with self.lock:
            data=data or {};now=self.clock();key=str(data.get('command_id',''))
            if len(key)<8 or len(key)>128:raise Blocked('Нужен уникальный идентификатор команды')
            prior=self.store.command_result(key)
            if prior is not None:return prior
            self._check_control_receipt(data)
            if command in ('emergency','pause','disable','close'):
                self._cancel_reversal('Команда пользователя: '+command,now)
                self._suspend_trigger(now)
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
                # Account adoption changes the namespace immediately. No candle,
                # tick or calculated scenario from the prior binding may be
                # relabelled as this account before the worker reads its market.
                self.bars=[];self.context=[];self.m1=[];self.m15=[];self.h1=[];self.live_bar=None
                self.quote=None;self.info={};self.quote_ready=False;self.quote_diagnostics={}
                self.last_market_attempt=-1.;self.last_bars_at=0.;self.market_time=0.;self.bar_errors=[]
                self.market_errors=['Новый счёт привязан; ожидаем свежие рыночные данные MT5']
                self.forecast={};self.forecast_side=0;self.forecast_since=0.;self.analysis_time=0.
                self.decision=Decision(phase='DATA_BLOCK',reason=self.market_errors[0]);self.last_audit_key=None
                self.observers=ForecastObservers()
                self.chart_market=None;self.last_chart_attempt=-1.
                self.campaign_history_cache={};self.pending_config=None
                self.recovery=False;self.real_armed=False;self.auto=False;self.paused=True;self.pending_reversal=None
                self.ack=[0,0];self.daily_latch='';self.deals=[];self.history_time=0.;self.history_ok=False;self.history_error='История ещё не получена'
                self.config=replace(self.config,account_mode=a['type'],approved=False,fee_per_lot=None)
                self.strategy=Strategy(self.config);self.compute=make_compute(self.config)
                self.strategy.clear();self.compute.clear();self.save()
                message='Текущий MT5 счёт привязан: '+a['type']+'. AUTO выключен'
            elif command=='configure':
                permitted={f.name for f in fields(Config)}-{'approved','technical_position_fuse','max_orders_per_minute'}
                supplied=data.get('config',{})
                if not isinstance(supplied,dict) or set(supplied)-permitted:raise Blocked('Неизвестное поле профиля')
                new=Config(**{**asdict(self.config),**supplied}).validate()
                if self.account and self.account.get('type') in ('DEMO','REAL') and new.account_mode!=self.account.get('type'):
                    raise Blocked('Режим профиля не совпадает с текущим MT5 счётом')
                busy=self._has_exit_targets()
                if busy and data.get('allow_deferred') is True:
                    existing=Config(**self.pending_config) if self.pending_config else None
                    if existing is None or replace(existing,approved=False)!=replace(new,approved=False):
                        carry_consent=bool(data.get('accept_pending_profile') and data.get('preserve_auto')
                            and self.auto and not self.paused and not self.emergency and not self.recovery
                            and self.config.approved and new.account_mode==self.config.account_mode=='DEMO')
                        self.pending_config=asdict(replace(new,approved=carry_consent))
                        self._cancel_reversal('Ожидается смена профиля',now)
                        self.store.event('PROFILE_QUEUED',dict(engine_mode=new.engine_mode),now)
                    self.save()
                    message='Профиль принят. Применится после подтверждённого завершения текущей кампании; AUTO включается отдельно'
                else:
                    if self.campaign or self._owned() or self._owned_orders() or self.store.pending():
                        raise Blocked('Профиль фиксирован до завершения кампании')
                    keep_auto=bool(data.get('preserve_auto') and data.get('accept_pending_profile') and self.auto
                        and not self.paused and not self.emergency and not self.recovery and self.config.approved
                        and new.account_mode==self.config.account_mode=='DEMO')
                    new.approved=keep_auto;self.auto=keep_auto;self.paused=not keep_auto;self.real_armed=False;self.pending_reversal=None
                    self.pending_config=None
                    self.config=new;self.strategy=Strategy(new);self.compute=make_compute(new);self.bars=[];self.context=[];self.last_bars_at=0
                    self.chart_market=None;self.last_chart_attempt=-1.
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
                self._check_control_receipt(data)
                if self.emergency:raise Blocked('AUTO заблокирован: EMERGENCY. Выполните явную сверку DEMO')
                if self.exit_pending and not data.get('allow_wait',False):raise Blocked('AUTO временно заблокирован: ожидается подтверждение закрытия кампании в MT5')
                if self.store.pending():raise Blocked('AUTO временно заблокирован: ожидается подтверждение торгового запроса MT5')
                if self.recovery:raise Blocked('AUTO заблокирован: требуется сверка неизвестного исполнения MT5')
                actual=self.account.get('type','UNKNOWN')
                if data.get('allow_wait',False) and actual!='DEMO':raise Blocked('AUTO с внутренним ожиданием доступен только DEMO')
                if self.config.account_mode!=actual:raise Blocked('Режим профиля не совпадает с текущим MT5 счётом')
                if (command=='enable' and actual=='DEMO' and data.get('allow_wait') is True
                        and data.get('accept_pending_profile') is True and data.get('confirmation')=='ENABLE_DEMO'
                        and 'config' in data):
                    supplied=data['config']
                    permitted={f.name for f in fields(Config)}-{'approved','technical_position_fuse','max_orders_per_minute'}
                    if not isinstance(supplied,dict) or set(supplied)-permitted:raise Blocked('Неизвестное поле профиля')
                    requested=Config(**{**asdict(self.config),**supplied}).validate()
                    if requested.account_mode!='DEMO':raise Blocked('Профиль AUTO должен быть DEMO')
                    if replace(requested,approved=False)==replace(self.config,approved=False):
                        self.config.approved=True
                    else:
                        self.pending_config=asdict(replace(requested,approved=True))
                        # Existing positions keep their frozen budget/SL; pending profile prevents adds.
                        self.config.approved=True
                if not self.config.approved:raise Blocked('Сначала подтвердите профиль '+actual)
                if actual=='REAL' and not self.real_armed:raise Blocked('REAL не вооружён: сначала ARM REAL')
                if not self.risk.get('allowed') and not data.get('allow_wait',False):raise Blocked('Риск не разрешён: '+','.join(self.risk.get('blocks',[])))
                if command=='play' and not self.auto:raise Blocked('PLAY снимает паузу, но не включает AUTO после отключения')
                expected='ENABLE_REAL' if actual=='REAL' else 'ENABLE_DEMO'
                if command=='enable' and data.get('confirmation')!=expected:raise Blocked('Нужно явное разрешение AUTO '+actual)
                if self.pending_config and data.get('accept_pending_profile') is True:
                    pending=Config(**self.pending_config).validate()
                    if pending.account_mode!=actual:raise Blocked('Режим ожидающего профиля не совпадает с MT5')
                    self.pending_config=asdict(replace(pending,approved=True))
                self._suspend_trigger(now)
                self.auto=True;self.paused=False;self.heartbeat=now;self.save()
                message='AUTO '+actual+' включён · '+self._entry_gate()['reason']
            elif command=='reset':
                self._refresh(now);self._reconcile()
                self._check_control_receipt(data)
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

    def _refresh_observers(self,now,budget=2):
        self.observers.refresh(self,now,budget)

    def forecast_snapshot(self,tf):
        with self.lock:
            if tf not in PUBLIC_TIMEFRAMES and tf!=self.config.timeframe:
                raise Blocked('Неизвестный таймфрейм прогноза')
            return self.observers.frame(self,tf,self.clock())

    def snapshot(self):
        from . import VERSION, PROTOCOL, BUILD, REVISION
        with self.lock:
            q=self.quote;now=self.clock();owned=self._owned()
            display_forecast=copy.deepcopy(self.forecast)
            # The analogue price model remains archived/evaluated as research data,
            # but the live trading chart is structural Scenario Map only. In WAIT
            # it must not paint a synthetic future trajectory.
            display_forecast['show_price_forecast']=False
            if self.campaign:
                c=self.campaign
                display_forecast['active_scenario']=dict(side=c['side'],entry=c['last_entry'],
                    trigger=c.get('entry_trigger',0),invalidation=c['invalidation'],
                    initial_invalidation=c.get('initial_invalidation',c['invalidation']))
                display_forecast['active_trade_plan']=dict(scenario_id=c.get('scenario_id'),snapshot_id=c.get('snapshot_id'),
                    side=c['side'],entry=c['last_entry'],invalidation=c['invalidation'],requested_volume=c.get('requested_volume'))
            display_forecast['reversal_status']=copy.deepcopy(self.reversal_status)
            timeframes,timeframe_context=self.observers.overview(self,now)
            return copy.deepcopy(dict(protocol=PROTOCOL,bridge_version=VERSION,bridge_build=BUILD,runtime_revision=REVISION,server_time=now,
                market_history_generation=self.broker_clock_identity,history_migration=self.history_migration,
                quote_diagnostics=self.quote_diagnostics,
                chart_market=self.chart_market,
                timeframes=timeframes,timeframe_context=timeframe_context,
                analysis_time=self.analysis_time,account=self.account,account_age=now-self.account_time,config=asdict(self.config),auto=self.auto,paused=self.paused,
                market_time=self.market_time,market_errors=list(self.market_errors),quote_fresh=self.quote_ready and q is not None and -2<=now-q.time_msc/1000<=10,
                risk_scope='MT5_ACCOUNT',foreign_positions=sum(p.get('magic')!=MAGIC for p in self.positions),
                emergency=self.emergency,recovery=self.recovery,exit_pending=self.exit_pending,real_armed=self.real_armed,
                pending_reversal=copy.deepcopy(self.pending_reversal),
                pending_config=copy.deepcopy(self.pending_config),entry_gate=self._entry_gate(),
                campaign_state=('OPEN' if owned else 'RECONCILING' if self.campaign else 'NONE'),
                campaign_progress=dict(open_positions=len(owned),confirmed_entries=len(self.campaign.get('events',[])) if self.campaign else 0,
                    max_positions=min(self.config.technical_position_fuse,self.config.optional_position_limit or 128,10 if self.config.entry_model=='PINNED_V1' else 128),
                    next_stage=(len(self.campaign.get('events',[]))+1) if self.campaign else 1,
                    next_event=(display_forecast.get('addition') or display_forecast.get('execution_setup') or {}).get('reason','Нет нового события'),
                    execution=self.execution,risk_rechecked_on_event=True),
                reconcile_detail=self.reconcile_detail,
                decision=self.decision.json(),execution=self.execution,risk=self.risk,
                forecast=display_forecast,auto_requested=self.auto,entry_allowed=self._entry_gate()['allowed'],
                market_scope=self.market_scope(),instrument=copy.deepcopy(self.info),
                capabilities=dict(minimum_client='R5' if self.config.engine_mode=='SCENARIO_V2' else 'R4',
                    history=True,scenario_archive=True,selected_lot=True,real_execution=False),
                reversal_status=copy.deepcopy(self.reversal_status),
                fee_profile=dict(fee_per_lot=self.effective_fee_per_lot,source=self.fee_source,key=self.fee_profile_key),
                quote=asdict(q) if q else None,bars=[asdict(b) for b in self.bars[-1200:]],
                live_bar=asdict(self.live_bar) if self.live_bar else None,
                live_structure=list(live_structure(self.bars,self.live_bar)),
                context_time=self.context[-1].time if self.context else 0,
                positions=owned,all_positions=self.positions,campaign=self.campaign,
                history_ok=self.history_ok and now-self.history_time<15,history_time=self.history_time,
                history_error=self.history_error,all=summary(self.rows),
                today=summary([r for r in self.rows if r['time']>=day_start(now)])))
