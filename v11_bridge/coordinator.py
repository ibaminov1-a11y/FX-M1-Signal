"""Single-owner execution coordinator. Exits never depend on history or entry data."""
from __future__ import annotations
from dataclasses import asdict
import json
import uuid
from campaign_core import *
from mt5_session import Session,day_id,SYMBOLS

class Engine(Session):
    def write(self, req):
        ai=self.connect()
        terminal=self.mt5.terminal_info()
        if terminal is None or not getattr(terminal,'trade_allowed',False) or getattr(terminal,'tradeapi_disabled',True) or not getattr(ai,'trade_allowed',False):
            raise Blocked('MT5: алгоритмическая торговля не разрешена')
        return self.mt5.order_send(req)

    def send(self, req):
        self.connect()
        check=self.mt5.order_check(req)
        if check is None or int(check.retcode)!=0:
            raise Blocked('MT5 отклонил проверку ордера: '+str(getattr(check,'comment','нет ответа')))
        result=self.write(req)
        if result is None:
            raise Blocked('Нет подтверждения order_send; повтор открытия запрещён')
        if result.retcode not in (self.mt5.TRADE_RETCODE_DONE,self.mt5.TRADE_RETCODE_DONE_PARTIAL):
            raise Blocked('MT5: '+str(result.retcode)+' '+str(result.comment))
        return result

    def close_own(self):
        self.connect()
        errors=[]
        try: orders=self.orders()
        except Exception as e: orders=[];errors.append(str(e))
        for o in orders:
            try:
                result=self.write(dict(action=self.mt5.TRADE_ACTION_REMOVE,order=int(o.ticket)))
                if result is None or result.retcode!=self.mt5.TRADE_RETCODE_DONE:
                    raise Blocked('Отмена ордера не подтверждена')
            except Exception as e: errors.append(str(e))
        for p in self.positions():
            try:
                q,_=self.quote(p.symbol)
                side=-1 if int(p.type)==0 else 1
                self.send(dict(action=self.mt5.TRADE_ACTION_DEAL,position=int(p.ticket),symbol=p.symbol,
                    volume=float(p.volume),type=self.order_type(side),price=q.ask if side==1 else q.bid,
                    deviation=10,magic=MAGIC,comment='FX11 CLOSE',type_time=self.mt5.ORDER_TIME_GTC,
                    type_filling=self.fill_policy(p.symbol)))
            except Exception as e: errors.append(str(e))
        remaining=self.positions()
        try: remaining_orders=self.orders()
        except Exception as e:
            self.event('CLOSE_PENDING',str(e));return False
        if remaining or remaining_orders:
            self.event('CLOSE_PENDING','; '.join(errors) or 'Частичное исполнение; повтор после сверки')
            return False
        # Execution confirmation does not depend on a functioning history endpoint.
        # Financial reconciliation remains pending, inhibiting the next campaign.
        c=self.s.get('campaign')
        try: self.history(force=True)
        except Exception as e:
            self.money_ok=False;self.money_error=str(e)
            if c: c['closing']=True;c['execution_closed']=True
            self.save();return True
        if c:
            self.s['blocked_setups']=(self.s['blocked_setups']+[c['setup_id']])[-1000:]
            self.event('CAMPAIGN_CLOSED',f"{c['id']} · cash result {self.cash-c['cash_start']:+.4f} USD")
        self.s['campaign'],self.s['pending']=None,None
        self.save()
        return True

    def start_close(self, reason):
        c=self.s['campaign']
        if c and not c.get('closing'):
            c['closing']=True
            self.save()
            self.event('EXIT',reason)

    def trailing(self, c, bars, info, q):
        closed=checked_bars(bars,300,self.clock(),40)
        direction,proof=structure(closed)
        side=c['side']
        if direction==-side:
            self.start_close('Противоположная подтверждённая структура M5');return
        supports=[p for p in proof if p.high==(side<0) and p.confirmed_at>c['opened'] and p.time>c['opened']]
        if self.emergency_request.is_set():
            self.start_close('Emergency во время сопровождения');return
        if not supports: return
        candidate=supports[-1].price-side*atr(closed)*0.10
        if side*(candidate-c['guard'])<=info.point*2: return
        if side*((q.bid if side==1 else q.ask)-candidate)<=0:
            self.start_close('Новая структура уже нарушена');return
        accepted=[]
        for p in self.own:
            if p.symbol!=c['symbol'] or int(p.type)!=(0 if side==1 else 1):
                raise Blocked('Состав кампании требует сверки')
            sl=normalize_stop(side,candidate,q.bid,q.ask,info.point,info.trade_tick_size or info.point,
                              max(info.trade_stops_level,info.trade_freeze_level))
            if side*(sl-p.sl)<=info.point:
                accepted.append(float(p.sl));continue
            r=self.write(dict(action=self.mt5.TRADE_ACTION_SLTP,position=int(p.ticket),symbol=p.symbol,sl=sl,tp=float(p.tp)))
            refreshed=self.mt5.positions_get(ticket=int(p.ticket))
            if r is None or r.retcode!=self.mt5.TRADE_RETCODE_DONE or refreshed is None or (refreshed and abs(refreshed[0].sl-sl)>info.point):
                raise Blocked('Перенос защиты не подтверждён; старый риск сохранён')
            if refreshed: accepted.append(sl)
        if accepted:
            c['guard']=min(accepted) if side==1 else max(accepted)
            self.save();self.event('PROTECT',f"SL {c['guard']:.5f}")
        self.positions()

    def open_event(self, setup, info, q, floating):
        s,c=self.s,self.s['campaign']
        now=self.clock()
        if (not s['auto'] or s['paused'] or s['emergency'] or s['recovery'] or s['daily_latch'] or
                self.emergency_request.is_set() or now-self.heartbeat>20):
            raise Blocked('Новые входы запрещены состоянием управления')
        if s['symbol']!='EUR/USD':
            raise Blocked('Торговый профиль RC допущен только для EUR/USD')
        if setup.event_id in s['consumed'] or setup.setup_id in s['blocked_setups']:
            raise Blocked('WAIT: событие уже обработано; ждём новую структуру')
        if s['pending']:
            raise Blocked('Предыдущий запрос требует сверки; повтор запрещён')
        if self.orders():
            raise Blocked('Есть отложенные ордера бота: требуется сверка')
        if now-setup.event_time>90 or setup.event_time>now+1:
            raise Blocked('Событие входа устарело')
        q,_=self.quote(info.name)
        price=q.ask if setup.side==1 else q.bid
        if setup.side*(price-setup.trigger)<-info.point*2 or abs(price-setup.trigger)>setup.atr*0.35:
            raise Blocked('WAIT: цена ушла от точки подтверждения; не догоняем')
        if q.ask-q.bid>0.00030:
            raise Blocked('Спред EUR/USD превышает 3 пипса')
        net_open=floating-sum(p.volume*self.fee() for p in self.own)
        if c and (setup.side!=c['side'] or not add_allowed(count=len(self.own),maximum=s['max_positions'],pnl=net_open,
                 side=setup.side,price=price,last_price=c['last_price'],step_distance=max(setup.atr*0.25,info.point*5),
                 new_event=True,closing=c['closing'],paused=s['paused'])):
            raise Blocked('ADD WAIT: нужен новый рост прибыльной кампании в пределах лимита')
        planned,future,margin_used=self.risk()
        cap=c.get('risk_cap',.50) if c else max(0,min(100,self.virtual,self.account.equity))*0.005
        daily_left=max(0,min(2,self.s['day_base']*0.02)+(self.virtual-self.s['day_base'])-future)
        budget=min(cap-planned,daily_left)
        if budget<=0: raise Blocked('Общий бюджет риска исчерпан')
        p=plan_order(side=setup.side,stop=setup.stop,bid=q.bid,ask=q.ask,point=info.point,
            tick_size=info.trade_tick_size or info.point,stops_level=info.trade_stops_level,
            minimum=info.volume_min,step=info.volume_step,maximum=info.volume_max,cap=budget,
            fee_per_lot=self.fee(),equity=max(0,min(self.virtual,self.account.equity)-margin_used),available_margin=self.account.margin_free,
            calc_profit=lambda side,v,a,b:self.profit(info.name,side,v,a,b),
            calc_margin=lambda side,v,a:self.mt5.order_calc_margin(self.order_type(side),info.name,v,a))
        if not c:
            c=dict(id=uuid.uuid4().hex[:12],setup_id=setup.setup_id,side=setup.side,symbol=info.name,
                   opened=now,guard=p.stop,last_price=p.price,cash_start=self.cash,closing=False,entries=[],risk_cap=cap)
            s['campaign']=c
        s['consumed']=(s['consumed']+[setup.event_id])[-5000:]
        s['pending']=dict(event=setup.event_id,campaign=c['id'],time=now)
        self.event('ENTRY_PROOF',json.dumps(setup.payload(),ensure_ascii=False))
        self.save()
        if self.emergency_request.is_set():
            self.start_close('Emergency перед отправкой');return
        try:
            self.connect()
            q2,_=self.quote(info.name)
            price2=q2.ask if setup.side==1 else q2.bid
            if abs(price2-p.price)>max(info.point*2,(q.ask-q.bid)):
                raise Blocked('Цена изменилась перед отправкой: вход отменён')
            req=dict(action=self.mt5.TRADE_ACTION_DEAL,symbol=info.name,volume=p.volume,
                type=self.order_type(setup.side),price=price2,sl=p.stop,tp=0.0,deviation=2,
                magic=MAGIC,comment='FX11 '+c['id'],type_time=self.mt5.ORDER_TIME_GTC,type_filling=self.fill_policy(info.name))
            self.send(req)
            positions=self.positions()
            matching=[x for x in positions if x.symbol==info.name and int(x.type)==(0 if setup.side==1 else 1)]
            if not matching:
                raise Blocked('Исполнение получено, но позиция не найдена: требуется сверка')
            newest=max(matching,key=lambda x:(getattr(x,'time_msc',x.time*1000),x.ticket))
            if newest.sl<=0:
                raise Blocked('Не подтверждён брокерский SL после исполнения')
            c['last_price']=float(newest.price_open)
            c['entries'].append(dict(ticket=int(newest.ticket),time=int(newest.time),price=float(newest.price_open),volume=float(newest.volume)))
            s['pending']=None
            if self.orders():
                self.start_close('Остаток заявки после частичного исполнения');self.latch('Требуется отмена остатка ордера')
            self.history(force=True);self.save()
            self.event('OPEN',f"{c['id']} {info.name} {'BUY' if setup.side==1 else 'SELL'} {newest.volume:g} @ {newest.price_open:.5f}")
            after,_,_=self.risk()
            if after>cap+1e-6:
                self.start_close('Риск после исполнения превысил бюджет');self.latch('Превышение риска после исполнения')
        except Exception as e:
            s['recovery']=True
            self.start_close('Неподтверждённое исполнение/защита');self.latch(str(e))
            raise

    def step(self):
        with self.lock:
            now=self.clock()
            try:
                self.connect();self.positions()
                floating=sum(float(p.profit)+float(p.swap) for p in self.own)
                if self.emergency_request.is_set():
                    self.emergency_request.clear();self.latch('Аварийная остановка',True)
                if self.s['emergency']:
                    done=self.close_own()
                    self.publish('EMERGENCY: позиции/ордера закрыты; AUTO заблокирован' if done else 'EMERGENCY: закрытие НЕ подтверждено',sum(float(p.profit)+float(p.swap) for p in self.own))
                    return
                c=self.s['campaign']
                if self.own and not c:
                    self.s['recovery']=True;self.s['auto']=False;self.s['paused']=True;self.save()
                    raise Blocked('Обнаружены прежние/неучтённые позиции бота. Новые входы запрещены')
                management_error=None
                if c:
                    if c['closing']:
                        self.close_own();self.publish('Выход/сверка кампании; вход запрещён',sum(float(p.profit)+float(p.swap) for p in self.own));return
                    if not self.own and not self.s['pending']:
                        self.start_close('Позиции закрыты брокером или вручную')
                        self.close_own();self.publish('Кампания завершена; сверяем историю',0);return
                    known={x['ticket'] for x in c['entries']}
                    if any(p.symbol!=c['symbol'] or int(p.type)!=(0 if c['side']==1 else 1) or int(p.ticket) not in known for p in self.own):
                        self.s['recovery']=True;self.latch('Состав кампании изменён извне')
                        raise Blocked('Состав кампании требует явной сверки')
                    q,_=self.quote(c['symbol'])
                    live=q.bid if c['side']==1 else q.ask
                    if c['side']*(live-c['guard'])<=0:
                        self.start_close('Цена нарушила защитную структуру')
                        self.close_own();self.publish('Выход по структуре',sum(float(p.profit)+float(p.swap) for p in self.own));return
                    info=self.mt5.symbol_info(c['symbol'])
                    if info is None: raise Blocked('Нет спецификации открытой кампании')
                    try: self.trailing(c,self.bars(c['symbol'],'M5',300),info,q)
                    except Blocked as e: management_error=str(e)
                    if c['closing']:
                        self.close_own();self.publish('Выход имеет приоритет',sum(float(p.profit)+float(p.swap) for p in self.own));return
                self.history(force=len(self.own)!=self.last_count)
                self.last_count=len(self.own)
                floating=sum(float(p.profit)+float(p.swap) for p in self.own)
                daily_cap=max(0,min(2,self.s['day_base']*.02))
                if self.virtual-self.s['day_base']<=-daily_cap:
                    if not self.s['daily_latch']:
                        self.s['daily_latch']=day_id(now);self.latch('Дневной порог потерь')
                    self.start_close('Дневной порог потерь')
                    if c: self.close_own()
                    self.publish('Дневной стоп; AUTO заблокирован',sum(float(p.profit)+float(p.swap) for p in self.own));return
                if c:
                    planned,_,_=self.risk()
                    if planned>c.get('risk_cap',.5)+1e-6:
                        self.start_close('Общий риск превышен');self.latch('Общий риск превышен')
                        self.close_own();self.publish('Выход по общему риску',sum(float(p.profit)+float(p.swap) for p in self.own));return
                if management_error: raise Blocked('Сопровождение: '+management_error)
                if self.s['auto'] and now-self.heartbeat>20:
                    self.s['paused']=True;self.save()
                info=self.resolve();q,stamp=self.quote(info.name)
                m5=self.bars(info.name,'M5',300)
                self.snapshot.update(bars=[asdict(x) for x in m5[-60:]],bid=float(q.bid),ask=float(q.ask),quote_time=stamp,setup=None)
                if self.s['recovery']: raise Blocked('Требуется явная сверка без позиций/ордеров')
                if self.s['daily_latch']: raise Blocked('Дневной стоп: новые входы заблокированы')
                try:
                    setup=analyse(info.name,self.bars(info.name,'H1',3600),self.bars(info.name,'M15',900),m5,self.bars(info.name,'M1',60),now,info.point)
                    self.snapshot['setup']=setup.payload();reason=setup.reason
                    if self.s['auto'] and not self.s['paused']:
                        self.open_event(setup,info,q,floating)
                    else: reason+=' · AUTO выключен / PAUSE'
                except Blocked as e: reason=str(e)
                self.publish(reason,sum(float(p.profit)+float(p.swap) for p in self.own))
            except Exception as e:
                reason=str(e) or type(e).__name__
                self.s['paused']=True
                if not isinstance(e,Blocked): self.s['auto']=False
                self.save()
                if reason!=self.last_error: self.event('BLOCK',reason);self.last_error=reason
                self.publish(reason,None,ok=False)

    def command(self, cmd, body):
        if cmd=='emergency':
            self.emergency_request.set()
        with self.lock:
            now=self.clock()
            key=str(body.get('id',''))
            previous=self.store.command_result(key)
            if previous is not None:
                if not previous.get('ok'): raise Blocked(previous['message'])
                return dict(previous,duplicate=True)
            if cmd=='emergency':
                self.s['emergency']=True;self.latch('EMERGENCY получен',True)
            elif cmd in ('pause','disable'):
                self.s['paused']=True
                if cmd=='disable': self.s['auto']=False
                self.s['generation']+=1;self.save()
            elif cmd=='close':
                self.latch('Закрыть собственную кампанию');self.s['emergency']=True;self.save()
            elif cmd=='reset':
                self.connect()
                if self.positions() or self.orders():
                    raise Blocked('Сначала необходимо подтвердить отсутствие позиций/ордеров бота')
                if self.s['daily_latch']==day_id(now):
                    raise Blocked('Дневной стоп нельзя снять в тот же торговый день')
                self.s.update(emergency=False,recovery=False,daily_latch='',pending=None,auto=False,paused=True,campaign=None)
                self.emergency_request.clear();self.s['generation']+=1;self.save()
            elif cmd=='profile':
                if self.s['auto'] or self.s['campaign'] or self.positions():
                    raise Blocked('Менять профиль можно только без активной кампании и AUTO')
                fee=finite(body.get('fee_per_lot',-1),'комиссия')
                maximum=int(body.get('max_positions',5))
                symbol=str(body.get('symbol','EUR/USD'))
                if fee<0 or fee>100 or maximum<1 or maximum>5 or symbol not in SYMBOLS:
                    raise Blocked('Некорректный профиль')
                self.s.update(fee_per_lot=fee,max_positions=maximum,symbol=symbol)
                self.s['generation']+=1;self.save()
            elif cmd in ('enable','play'):
                expires=finite(body.get('expires',0),'срок команды')
                if expires<now or expires>now+15: raise Blocked('Команда входа устарела')
                if body.get('generation')!=self.s['generation'] or now-self.heartbeat>20:
                    raise Blocked('Состояние изменилось/связь устарела: повторите действие после сверки')
                self.connect();self.positions();self.history(force=True)
                if self.s['emergency'] or self.s['recovery'] or self.s['daily_latch'] or self.s['pending']:
                    raise Blocked('Аварийная/дневная блокировка; PLAY не снимает её')
                if cmd=='play' and not self.s['auto']: raise Blocked('Сначала явно включите AUTO в приложении')
                self.fee()
                if self.s['symbol']!='EUR/USD':
                    raise Blocked('RC: торговля только EUR/USD; остальные инструменты — наблюдение')
                if self.own and not self.s['campaign']: raise Blocked('Есть неучтённые позиции')
                self.s.update(auto=True,paused=False);self.s['generation']+=1;self.save()
            else: raise Blocked('Неизвестная команда')
            self.event('COMMAND',cmd)
            self.publish('Команда: '+cmd,sum(float(p.profit)+float(p.swap) for p in self.own))
            result=dict(ok=True,generation=self.s['generation'])
            self.store.remember_command(key,result,now)
            return result
