from __future__ import annotations
from dataclasses import asdict, fields
import copy, hashlib, math, threading, time
from .model import Config, Decision, Blocked, PROFILES, TF_SECONDS, atr, pivots, number
from .strategy import Strategy
from .risk import risk_state, plan_order, ledger, summary, quantize, day_start
from .mt5_adapter import MAGIC

CONTEXT={'M1':'M5','M5':'M15','M10':'H1','M15':'H1','H1':'H4','H4':'D1','D1':'W1','W1':'MN1','MN1':'MN1'}


class Engine:
    """Single serialized campaign owner. UI never supplies a BUY/SELL command."""
    def __init__(self,broker,store,clock=time.time):
        self.broker=broker;self.store=store;self.clock=clock;self.lock=threading.RLock()
        saved=store.load('engine',{})
        self.config=Config(**saved.get('config',{})).validate()
        self.account_key=saved.get('account_key','')
        self.campaign=saved.get('campaign')
        self.emergency=bool(saved.get('emergency',False))
        self.recovery=bool(saved.get('recovery',False))
        self.daily_latch=saved.get('daily_latch','')
        self.ack=saved.get('ack',[0,0]);self.last_exit=float(saved.get('last_exit',0))
        self.auto=False;self.paused=True;self.heartbeat=0.
        self.exit_pending=bool(saved.get('exit_pending',False))
        self.strategy=Strategy(self.config,saved.get('strategy'))
        self.strategy.previous_quote=None
        if self.strategy.setup:
            self.strategy.setup.seen_safe_side=False
            self.strategy.setup.armed_msc=int(clock()*1000)
        if store.pending(): self.recovery=True
        self.deals=[];self.history_time=0.;self.history_ok=False
        self.history_error='История ещё не получена'
        self.rows=[];self.account={};self.account_time=0.;self.positions=[];self.orders=[]
        self.risk={'allowed':False,'blocks':['HISTORY_UNAVAILABLE']}
        self.last_bars_at=0.;self.bars=[];self.context=[];self.quote=None;self.info={}
        self.analysis_time=0.;self.decision=Decision();self.execution='AUTO выключен: только анализ'
        self.rate_times=[];self.next_close=0.;self.last_persist=0.;self.last_audit_key=None
        self.save()

    def save(self):
        self.store.save('engine',dict(config=asdict(self.config),account_key=self.account_key,
            campaign=self.campaign,emergency=self.emergency,recovery=self.recovery,
            daily_latch=self.daily_latch,ack=self.ack,last_exit=self.last_exit,
            exit_pending=self.exit_pending,strategy=self.strategy.state()))

    def _owned(self): return [p for p in self.positions if p['magic']==MAGIC]
    def _owned_orders(self): return [p for p in self.orders if p['magic']==MAGIC]

    def _refresh_risk(self,now):
        try:
            if not self.history_ok or now-self.history_time>15:
                raise Blocked(self.history_error or 'История устарела')
            self.risk=risk_state(self.account,self.positions,self.deals,self.config,now,self.ack,self.daily_latch)
            self.rows=ledger(self.deals,self.positions)
            if 'DAILY_LOSS' in self.risk['blocks']:
                self.daily_latch=self.risk['day'];self.auto=False;self.paused=True;self.exit_pending=True;self.save()
        except (Blocked,ValueError,TypeError,KeyError) as e:
            self.risk={'allowed':False,'blocks':['DATA_UNAVAILABLE'],'message':str(e),'ack_supported':True,'can_acknowledge':False}

    def _refresh(self,now):
        self.broker.connect()
        a=self.broker.account()
        if self.account_key and a['key']!=self.account_key:
            self.auto=False;self.paused=True;self.recovery=True;self.save()
            raise Blocked('Счёт MT5 изменён; автоматические действия остановлены')
        if not self.account_key:self.account_key=a['key'];self.save()
        self.account=a;self.account_time=now
        self.positions=self.broker.positions();self.orders=self.broker.orders()
        if a['type']!='DEMO' or a['margin_mode']!='HEDGING' or a['currency']!='USD':
            self.auto=False;self.paused=True
            raise Blocked('EC1 исполняет только на USD DEMO hedging')
        if now-self.history_time>=10 or not self.history_time:
            try:
                self.deals=self.broker.history(now);self.history_time=now;self.history_ok=True;self.history_error=''
            except Exception as e:
                self.history_ok=False;self.history_time=now;self.history_error=str(e)
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
        # Unknown requests without positive evidence never become permission to retry.
        if self.store.pending():self.recovery=True;self.auto=False;self.paused=True
        if owned and not self.campaign:
            self.recovery=True;self.auto=False;self.paused=True
            self.execution='Есть позиции EC1 без сохранённой кампании: нужна ручная сверка'
        if self.campaign and self.history_ok:
            ids=set(self.campaign.get('position_ids',[]))
            self.campaign['realized']=sum(d['profit']+d.get('swap',0)+d.get('commission',0)+d.get('fee',0)
                for d in self.deals if d.get('position_id') in ids and d.get('entry') in (1,3))
            if not owned and not self._owned_orders() and not self.store.pending():
                self.campaign['end']=self.clock()
                self.campaign['net']=sum(d['profit']+d.get('swap',0)+d.get('commission',0)+d.get('fee',0)
                    for d in self.deals if d.get('position_id') in ids)
                self.store.campaign(self.campaign['id'],self.campaign)
                self.store.event('CAMPAIGN_CLOSED',self.campaign,self.clock())
                self.campaign=None;self.last_exit=self.clock();self.exit_pending=False
                self.strategy.clear();self.save()
                return True
        return False

    def _close_campaign(self,reason):
        self.exit_pending=True;self.auto=False if self.emergency else self.auto
        self.execution='Выход кампании: '+reason;self.save()
        now=self.clock()
        if now<self.next_close:return
        self.next_close=now+2
        for o in self._owned_orders():
            try:self.broker.cancel(o)
            except Exception as e:self.execution='Отмена ордера пока не подтверждена: '+str(e);return
        # Refresh before each pass. Never close manual or legacy-V10 positions.
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
        if not self._owned() and not self._owned_orders():self.execution='Позиции бота закрыты; ожидается сверка истории'

    def _manage(self,now):
        owned=self._owned()
        if self.emergency or self.exit_pending:
            self._close_campaign('Emergency' if self.emergency else 'ожидаем завершения');return True
        if not owned:return False
        if not self.campaign:return False
        c=self.campaign;q=self.quote
        side=c['side'];net=sum(p['profit']+p.get('swap',0)-float(self.config.fee_per_lot or 0)*p['volume'] for p in owned)+c.get('realized',0)
        c['peak']=max(float(c.get('peak',0)),net)
        if net<=-c['budget'] or any(p['sl']<=0 for p in owned):
            self._close_campaign('превышен риск или отсутствует брокерский SL');return True
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
        # Tighten broker protection only after sufficient progress, and only from closed data.
        if c['peak']>=profile.protect_at_r*r and self.bars:
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
                if self.emergency or self.exit_pending:
                    self._close_campaign('Emergency' if self.emergency else 'ожидаем завершения')
                    return self.snapshot()
                if just_closed:return self.snapshot()
                self.info=self.broker.symbol(self.config.symbol)
                self.quote=self.broker.quote(self.info['name'])
                if self._manage(now):return self.snapshot()
                q=self.quote;q.validate(now)
                if now-self.last_bars_at>=1 or not self.bars:
                    self.bars=self.broker.bars(self.info['name'],self.config.timeframe)
                    self.context=self.broker.bars(self.info['name'],CONTEXT[self.config.timeframe])
                    self.last_bars_at=now
                ctf=CONTEXT[self.config.timeframe]
                if ctf!='MN1' and (not self.context or now-self.context[-1].time>TF_SECONDS[ctf]*2.5):
                    raise Blocked('Контекст старшего таймфрейма устарел')
                d=self.strategy.update(self.bars,self.context,q,now,self.campaign['side'] if self.campaign else 0)
                self.decision=d;self.analysis_time=now
                if now-self.last_persist>=1:
                    self.save();self.last_persist=now
                # Audit bar/phase changes and every entry event; no fake confidence probability.
                key=(self.bars[-1].time,d.phase,d.signal)
                if key!=self.last_audit_key:
                    self.store.event('ANALYSIS',dict(decision=d.json(),quote=asdict(q),bar=asdict(self.bars[-1]),mode=self.config.mode),now)
                    self.last_audit_key=key
                if not self.auto or self.paused:self.execution='AUTO выключен / PAUSE; сопровождение сохраняется'
                elif now-self.heartbeat>30:
                    self.auto=False;self.paused=True;self.execution='Нет связи с телефоном 30 секунд: новые входы остановлены';self.save()
                elif self.recovery:self.execution='Нужна сверка неизвестного исполнения; новые входы запрещены'
                elif not self.risk.get('allowed',False):self.execution='Риск: '+','.join(self.risk.get('blocks',[]))
                elif not self._session_allowed(now):self.execution='Текущая сессия не разрешена выбранным фильтром'
                elif d.signal=='WAIT':self.execution='Нет нового подтверждённого входа; ордер не отправлен'
                else:
                    try:self._entry(d,now)
                    finally:
                        self.strategy.consume(d.event_id);self.save()
                # Entry event is single-use even when it is skipped or rejected. No late entry
                # when AUTO is enabled after a crossing that already happened.
                if d.event_id:self.strategy.consume(d.event_id);self.save()
            except Exception as e:
                self.execution=str(e)
                self.decision=Decision(phase='DATA_BLOCK',reason=str(e))
                # Existing broker stops remain in force. Data failure never becomes an entry.
            return self.snapshot()

    def _entry(self,d,now):
        if self.emergency or self.exit_pending or self.recovery or self.store.pending():
            raise Blocked('Вход заблокирован состоянием кампании')
        if self.store.has_intent(d.event_id):raise Blocked('Повтор торгового события запрещён')
        if self._owned_orders():raise Blocked('Предыдущий запрос ещё не завершён')
        if any(p['magic']!=MAGIC for p in self.positions) or any(o['magic']!=MAGIC for o in self.orders):
            raise Blocked('Есть ручные/старые позиции или ордера: сначала завершите их отдельно')
        if now-self.last_exit<self.config.cooldown_sec:raise Blocked('Пауза после завершения кампании')
        self.rate_times=[t for t in self.rate_times if now-t<60]
        if len(self.rate_times)>=self.config.max_orders_per_minute:raise Blocked('Предохранитель частоты заявок')
        # Re-read tick, account, positions and risk immediately before final plan.
        self.positions=self.broker.positions();self.orders=self.broker.orders();account=self.broker.account()
        if account['key']!=self.account_key:raise Blocked('Счёт изменился перед отправкой')
        self.account=account
        if self._owned_orders() or any(p['magic']!=MAGIC for p in self.positions) or any(o['magic']!=MAGIC for o in self.orders):
            raise Blocked('Экспозиция изменилась перед отправкой')
        self._refresh_risk(now)
        if not self.risk.get('allowed'):raise Blocked('Проверка риска не разрешила отправку')
        q=self.broker.quote(self.info['name']);q.validate(now)
        if (q.bid-d.trigger)*d.side<=0 or abs(q.bid-d.trigger)>PROFILES[self.config.mode].no_chase_atr*d.atr:
            raise Blocked('Котировка уже вышла из допустимой зоны входа')
        p=plan_order(self.broker,self.config,account,self.info,q,d,self._owned(),self.campaign,now)
        if not self.campaign:
            self.campaign=dict(id=d.event_id,side=d.side,mode=self.config.mode,timeframe=self.config.timeframe,
                symbol=self.info['name'],started=now,budget=self.config.budget(account),initial_risk=p.risk,
                last_entry=p.entry,best_price=p.entry,last_progress=now,invalidation=d.invalidation,
                add_step_atr=PROFILES[self.config.mode].add_step_atr,peak=0.,position_ids=[],realized=0.,events=[])
        comment='EC1:'+hashlib.sha256(d.event_id.encode()).hexdigest()[:16]
        body=dict(plan=asdict(p),comment=comment,time=now)
        # Persist SENDING before crossing the process/API boundary.
        self.strategy.consume(d.event_id);self.save();self.store.intent(d.event_id,'SENDING',body)
        self.rate_times.append(now)
        try:out=self.broker.send(p,comment)
        except Blocked as e:
            self.store.intent(d.event_id,'REJECTED',dict(body,error=str(e)));raise
        except Exception as e:out=dict(status='UNKNOWN',reason=str(e))
        self.store.event('ORDER_RESPONSE',dict(intent=body,response=out),now)
        if out['status']=='REJECTED':
            self.store.intent(d.event_id,'REJECTED',dict(body,response=out))
            self.execution='MT5 отклонил: '+out.get('reason','');return
        # A broker response alone is not a confirmed live position.
        self.store.intent(d.event_id,'UNKNOWN',dict(body,response=out))
        self.positions=self.broker.positions();self.orders=self.broker.orders()
        matches=[x for x in self._owned() if x.get('comment')==comment]
        if out['status']=='FILLED' and matches and not self._owned_orders():
            self.store.intent(d.event_id,'FILLED',dict(body,response=out))
            self.campaign['last_entry']=sum(x['price_open']*x['volume'] for x in matches)/sum(x['volume'] for x in matches)
            self.campaign['position_ids']=sorted(set(self.campaign['position_ids'])|{x['identifier'] for x in matches})
            self.campaign['events'].append(d.event_id)
            self.execution='MT5 подтвердил '+d.signal+': '+', '.join('#'+str(x['ticket']) for x in matches)
            self.save()
            # Check accepted SL and actual risk before allowing another stage.
            try:
                reserve=max(self.config.slippage_ticks*self.info['tick_size'],q.spread)
                actual=max(0,-float(self.campaign.get('realized',0)))
                for live in self._owned():
                    if live['sl']<=0:raise Blocked('брокер не подтвердил SL')
                    loss=-number(self.broker.calc_profit(live['side'],live['symbol'],live['volume'],
                        live['price_open'],live['sl']-live['side']*reserve),'actual stop risk')
                    actual+=max(0,loss)+self.config.fee_per_lot*live['volume']
                if sum(x['volume'] for x in matches)>p.volume+1e-8:
                    raise Blocked('подтверждённый объём больше запрошенного')
                if actual>min(self.campaign['budget'],self.config.budget(account))+1e-7:
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
                if command=='emergency':self.emergency=True;self.exit_pending=True;self.auto=False;self.paused=True
                elif command=='close':self.exit_pending=True;self.auto=False;self.paused=True
                elif command=='disable':self.auto=False;self.paused=True
                else:self.paused=True
                self.save()
                message='Блокировка сохранена; закрытие проверяется по MT5' if command in ('emergency','close') else 'Новые входы и добавления остановлены; сопровождение продолжается'
            elif command=='configure':
                permitted={f.name for f in fields(Config)}-{'approved','technical_position_fuse','max_orders_per_minute'}
                supplied=data.get('config',{})
                if not isinstance(supplied,dict) or set(supplied)-permitted:raise Blocked('Неизвестное поле профиля')
                new=Config(**{**asdict(self.config),**supplied}).validate()
                if self.campaign or self._owned() or self._owned_orders() or self.store.pending():
                    raise Blocked('Профиль фиксирован до завершения кампании')
                new.approved=False;self.auto=False;self.paused=True
                self.config=new;self.strategy=Strategy(new);self.bars=[];self.context=[];self.last_bars_at=0
                self.save();message='Профиль сохранён. Подтвердите комиссию и риск; AUTO выключен'
            elif command=='approve_profile':
                if data.get('confirmation')!='APPROVE_DEMO_RISK':raise Blocked('Нужно явное подтверждение риска DEMO')
                self.config.validate()
                if self.config.fee_per_lot is None:raise Blocked('Неизвестная комиссия не считается нулём')
                self.config.approved=True;self.auto=False;self.paused=True;self.save();message='Профиль DEMO подтверждён; AUTO выключен'
            elif command in ('enable','play'):
                self._refresh(now)
                if self.emergency or self.recovery or self.exit_pending or self.store.pending():raise Blocked('Аварийная блокировка/сверка: PLAY не разрешает AUTO')
                if not self.config.approved:raise Blocked('Сначала подтвердите профиль DEMO')
                if not self.risk.get('allowed'):raise Blocked('Риск не разрешён: '+','.join(self.risk.get('blocks',[])))
                if command=='play' and not self.auto:raise Blocked('PLAY снимает паузу, но не включает AUTO после отключения')
                if command=='enable' and data.get('confirmation')!='ENABLE_DEMO':raise Blocked('Нужно явное разрешение AUTO DEMO')
                self.auto=True;self.paused=False;self.heartbeat=now;self.save();message='AUTO DEMO включён; вход только по новому событию'
            elif command=='reset':
                self._refresh(now);self._reconcile()
                if data.get('confirmation')!='RESET_DEMO_FLAT':raise Blocked('Нужна явная сверка DEMO')
                if self._owned() or self._owned_orders() or self.store.pending():raise Blocked('Есть позиции/ордера или неизвестный запрос: автоматический сброс запрещён')
                if self.risk.get('blocks'):raise Blocked('Сначала разберите блокировки риска')
                self.emergency=False;self.recovery=False;self.exit_pending=False;self.auto=False;self.paused=True
                self.strategy.clear();self.save();message='Блокировка снята после сверки. AUTO остаётся выключенным'
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
            out=dict(ok=True,message=message,auto=self.auto,paused=self.paused,emergency=self.emergency)
            self.store.event('COMMAND',dict(command=command,result=out),now)
            self.store.command_done(key,out)
            return out

    def snapshot(self):
        from . import VERSION, PROTOCOL
        with self.lock:
            q=self.quote;now=self.clock();owned=self._owned()
            return copy.deepcopy(dict(protocol=PROTOCOL,bridge_version=VERSION,server_time=now,
                analysis_time=self.analysis_time,account=self.account,account_age=now-self.account_time,config=asdict(self.config),auto=self.auto,paused=self.paused,
                emergency=self.emergency,recovery=self.recovery,exit_pending=self.exit_pending,
                decision=self.decision.json(),execution=self.execution,risk=self.risk,
                quote=asdict(q) if q else None,bars=[asdict(b) for b in self.bars[-100:]],
                context_time=self.context[-1].time if self.context else 0,
                positions=owned,all_positions=self.positions,campaign=self.campaign,
                history_ok=self.history_ok and now-self.history_time<15,history_time=self.history_time,
                history_error=self.history_error,all=summary(self.rows),
                today=summary([r for r in self.rows if r['time']>=day_start(now)])))
