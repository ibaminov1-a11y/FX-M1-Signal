"""One serialized execution owner with separately persisted broker-symbol profiles.

Each Engine is an isolated state machine; only this coordinator steps them. The
shared broker and SQLite store are accessed under one reentrant lock. HTTP view
selection is request-local and never enables trading.
"""
from __future__ import annotations
import contextvars,copy,hashlib,threading,time
from dataclasses import asdict,fields
from .engine import Engine
from .model import Config,Blocked,number
from .mt5_adapter import MAGIC
from .risk import symbol_key

class ProfileStore:
    def __init__(self,store,profile_id,symbol,legacy=False):
        self.root=store;self.profile_id=profile_id;self.symbol=symbol;self.legacy=legacy
    def __getattr__(self,name):return getattr(self.root,name)
    def _key(self,key):
        if key=='engine':return 'engine' if self.legacy else 'profile:'+self.profile_id+':engine'
        return key
    def load(self,key,default=None):return self.root.load(self._key(key),default)
    def save(self,key,value):return self.root.save(self._key(key),value)
    def pending(self):
        return [p for p in self.root.pending() if p['body'].get('profile_id')==self.profile_id or
                (not p['body'].get('profile_id') and (self.legacy or symbol_key(p['body'].get('plan',{}).get('symbol',''))==symbol_key(self.symbol)))]
    def intent(self,key,status,body):return self.root.intent(key,status,dict(body,profile_id=self.profile_id))
    def event(self,kind,body,now=None):return self.root.event(kind,dict(body,profile_id=self.profile_id),now)

class ProfileBroker:
    def __init__(self,owner,symbol):self.owner=owner;self.name=symbol
    def __getattr__(self,name):return getattr(self.owner.broker,name)
    def resolved(self):return self.owner.broker.symbol(self.name)['name']
    def positions(self):return [p for p in self.owner.broker.positions() if symbol_key(p['symbol'])==symbol_key(self.resolved())]
    def orders(self):return [p for p in self.owner.broker.orders() if symbol_key(p['symbol'])==symbol_key(self.resolved())]
    def preflight(self,plan,cfg):
        # Per-campaign sizing already ran; recheck aggregate exposure immediately
        # before SENDING is persisted. Unknown outcomes cannot be retried elsewhere.
        if self.owner.store.pending():raise Blocked('Есть неизвестное исполнение на счёте; ждём сверку')
        a=self.owner.broker.account()
        if a['type']!='DEMO':raise Blocked('R7: REAL выключен')
        if any(e.emergency for e in self.owner.engines.values()):raise Blocked('EMERGENCY счёта')
        budget=number(self.owner.account_budget(a,cfg),'account budget',positive=True)
        total=number(plan.risk,'planned risk')+sum(max(0,-number(e.campaign.get('realized',0),'realized loss')) for e in self.owner.engines.values() if e.campaign)
        margin=number(plan.margin,'planned margin')
        for p in self.owner.broker.positions():
            if float(p.get('sl',0))<=0:raise Blocked('На счёте есть позиция без подтверждённого SL')
            info=self.owner.broker.symbol(p['symbol']);q=self.owner.broker.quote(p['symbol']);q.validate(self.owner.clock())
            reserve=max(q.spread,cfg.slippage_ticks*info['tick_size'])
            value=-number(self.owner.broker.calc_profit(p['side'],p['symbol'],p['volume'],p['price_open'],p['sl']-p['side']*reserve),'aggregate stop P/L')
            fees=max(float(e.effective_fee_per_lot or 0) for e in self.owner.engines.values())
            total+=max(0,value)+fees*p['volume']
            margin+=number(self.owner.broker.calc_margin(p['side'],p['symbol'],p['volume'],p['price_open']),'aggregate margin')
        if total>budget+1e-7:raise Blocked(f'Общий риск счёта {total:.2f} USD > бюджет {budget:.2f} USD')
        if margin>cfg.base(a)*cfg.margin_fraction:raise Blocked('Общая маржа профилей превышает выбранный предел')
        if self.owner.broker.orders():raise Blocked('На счёте ожидается исполнение ордера; новая заявка не отправлена')

class Portfolio:
    def __init__(self,broker,store,clock=time.time,entry_model=None):
        self.broker=broker;self.store=store;self.clock=clock;self.lock=threading.RLock();self.entry_model=entry_model
        self._all_positions=[];self._positions_time=0.;self._positions_error='Позиции MT5 ещё не получены'
        self._positions_account_key=''
        self.engines={};self.meta={};self._view=contextvars.ContextVar('r7_profile_view',default=None)
        saved=store.load('r7_profiles')
        if saved:
            self.meta=saved['profiles'];self.default_id=saved['selected']
        else:
            old=store.load('engine',{});cfg=Config(**old.get('config',{}))
            # Canonical binding is rechecked by the broker before any order.
            name=symbol_key(cfg.symbol);ident=self._id(name)
            self.meta={ident:dict(symbol=name,legacy=True)};self.default_id=ident
        for ident,meta in self.meta.items():self._load(ident,meta)
        self._save()
    @staticmethod
    def _id(symbol):return 'p-'+hashlib.sha256(symbol_key(symbol).encode()).hexdigest()[:16]
    @property
    def profile_id(self):return self._view.get() or self.default_id
    def __getattr__(self,name):return getattr(self.engines[self.profile_id],name)
    def select_request(self,ident):
        if ident and ident not in self.engines:raise Blocked('Профиль не найден; обновите список инструментов')
        self._view.set(ident or self.default_id)
    def _load(self,ident,meta,cfg=None):
        ps=ProfileStore(self.store,ident,meta['symbol'],meta.get('legacy',False))
        old=ps.load('engine',{})
        values=old.get('config',{}) if cfg is None else cfg
        values=dict(values,runtime_model='R7',engine_mode='SCENARIO_V2')
        if self.entry_model:values['entry_model']=self.entry_model
        old=dict(old,config=asdict(Config(**values).validate()));ps.save('engine',old)
        e=Engine(ProfileBroker(self,meta['symbol']),ps,self.clock);e.lock=self.lock
        self.engines[ident]=e
        inbox=self.__dict__.get('control_inbox')
        if inbox:e.entry_inhibited=lambda ident=ident:inbox.inhibited(ident)
    def _save(self):self.store.save('r7_profiles',dict(selected=self.default_id,profiles=self.meta))
    def account_budget(self,account,cfg=None):
        # One explicit account envelope: largest configured per-campaign percent,
        # NOT that percent for each simultaneous instrument. Displayed in state.
        pct=max([e.config.risk_pct for e in self.engines.values()]+([cfg.risk_pct] if cfg else []))
        return min(account['equity'],account['balance'])*pct/100
    def snapshot(self):
        with self.lock:
            return self._snapshot(self.profile_id)
    def _snapshot(self,ident):
        s=self.engines[ident].snapshot();s['profile_id']=ident
        s.setdefault('capabilities',{})['profile_registry']=True
        s['profiles']=[dict(profile_id=k,symbol=self.meta[k]['symbol'],config=asdict(e.config),auto=e.auto,
            paused=e.paused,campaign=copy.deepcopy(e.campaign),execution=e.execution) for k,e in self.engines.items()]
        if s.get('account'):s['account_risk_budget']=self.account_budget(s['account'])
        same_account=bool(self._positions_account_key and self._positions_account_key==s.get('account',{}).get('key'))
        s['all_positions']=copy.deepcopy(self._all_positions) if same_account else []
        s['positions_age']=max(0.,self.clock()-self._positions_time)
        s['positions_ok']=same_account and not self._positions_error and s['positions_age']<10
        s['positions_error']=self._positions_error if same_account else 'Позиции текущего счёта ещё не подтверждены'
        s['foreign_positions']=sum(p.get('magic')!=MAGIC for p in s['all_positions'])
        if not s['positions_ok']:s['account_age']=max(10.,s['account_age'])
        return s
    def view_snapshots(self):
        with self.lock:return [self._snapshot(ident) for ident in self.engines]
    def _refresh_positions(self):
        # Only the serialized runtime calls MT5. HTTP snapshots never perform I/O.
        try:
            account_key=self.broker.account()['key']
            positions=self.broker.positions()
            if self.broker.account()['key']!=account_key:raise Blocked('Счёт изменён во время получения позиций')
            self._all_positions=copy.deepcopy(positions);self._positions_time=self.clock();self._positions_error=''
            self._positions_account_key=account_key
        except Exception as exc:self._positions_error=str(exc)
    def refresh_view(self):
        with self.lock:
            result=self.engines[self.profile_id].refresh_view()
            self._refresh_positions()
            result.update({k:v for k,v in self.snapshot().items() if k in ('profiles','profile_id','capabilities','all_positions','account_risk_budget',
                'positions_ok','positions_age','positions_error','foreign_positions','account_age')})
            return result
    def step(self):
        with self.lock:
            for ident,e in list(self.engines.items()):
                inbox=self.__dict__.get('control_inbox')
                if inbox:inbox.drain()
                try:e.step()
                except Exception:
                    e.auto=False;e.paused=True;e.recovery=True;e.save()
                    raise
            self._refresh_positions()
            return self.snapshot()
    def command(self,cmd,data=None):
        data=dict(data or {})
        with self.lock:
            ident=data.get('profile_id') or self.profile_id
            if ident not in self.engines:raise Blocked('Профиль команды не найден')
            if cmd=='arm_real':raise Blocked('R7: торговля REAL выключена')
            if cmd=='emergency':
                result=None
                for k,e in self.engines.items():
                    body=dict(data,command_id=data.get('command_id','')+'|'+k)
                    result=e.command(cmd,body)
                return dict(result,profile_id=ident)
            if cmd=='configure':
                values=data.get('config',{})
                if not isinstance(values,dict):raise Blocked('Профиль должен быть объектом')
                requested=values.get('symbol',self.engines[ident].config.symbol)
                canonical=self.broker.symbol(requested)['name'];target=self._id(canonical)
                # Keep the migrated symbol ID when the broker resolves a suffix.
                target=next((k for k,m in self.meta.items() if symbol_key(self.broker.symbol(self.engines[k].config.symbol)['name'])==symbol_key(canonical)),target)
                if target not in self.engines:
                    cfg=asdict(Config(symbol=requested,engine_mode='SCENARIO_V2',runtime_model='R7'))
                    cfg.update(values);cfg['approved']=False;cfg['runtime_model']='R7'
                    Config(**cfg).validate()
                    self.meta[target]=dict(symbol=canonical,legacy=False)
                    self._load(target,self.meta[target],cfg)
                # A new view does not inherit AUTO consent. Same-symbol changes
                # preserve the old campaign and use Engine's deferred configuration.
                cross=target!=ident
                e=self.engines[target]
                values=dict(values,runtime_model='R7')
                if self.entry_model:values['entry_model']=self.entry_model
                permitted={f.name for f in fields(Config)}-{'approved','technical_position_fuse','max_orders_per_minute'}
                unchanged=not (set(values)-permitted) and all(
                    symbol_key(v)==symbol_key(e.config.symbol) if k=='symbol' else getattr(e.config,k)==v
                    for k,v in values.items())
                e._check_control_receipt(data)
                if cross and unchanged:
                    # Merely returning to an already configured instrument must
                    # not reset observers, pause its campaign, or grant consent.
                    result=dict(ok=True,message='Выбран сохранённый профиль; торговое состояние не изменено',
                        auto=e.auto,paused=e.paused,emergency=e.emergency,real_armed=e.real_armed)
                    self.store.event('PROFILE_VIEW',dict(profile_id=target),self.clock())
                else:
                    if cross:data.update(preserve_auto=False,accept_pending_profile=False)
                    result=e.command(cmd,dict(data,config=values))
                self.default_id=target;self._view.set(target);self._save()
                return dict(result,profile_id=target)
            if cmd=='enable' and 'config' in data:
                if symbol_key(data['config'].get('symbol',''))!=symbol_key(self.engines[ident].config.symbol):
                    raise Blocked('Выбран другой инструмент; сначала сохраните его профиль')
            result=self.engines[ident].command(cmd,data)
            return dict(result,profile_id=ident)
