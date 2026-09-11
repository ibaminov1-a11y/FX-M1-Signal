from __future__ import annotations
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from datetime import datetime, timezone, timedelta
from .model import Config, Quote, Decision, Blocked, number

LOCAL_DAY = timezone(timedelta(hours=5))


def money(deal):
    return sum(number(deal.get(k,0), k) for k in ('profit','commission','swap','fee'))


def day_start(now):
    t=datetime.fromtimestamp(now, LOCAL_DAY)
    return t.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()


def ledger(deals, open_positions=()):
    """Group by position, include opening expenses; never count partial exits as new trades."""
    groups={}
    for d in sorted(deals, key=lambda x:(x['time_msc'],x['ticket'])):
        if d.get('type') not in (0,1):
            continue
        key=int(d['position_id'])
        if not key:
            continue
        g=groups.setdefault(key,dict(position_id=key,net=0.,opened=0.,closed=0.,time=0,
            time_msc=0,last_ticket=0,open_time=0,side='',symbol=d['symbol'],magic=d.get('magic',0)))
        g['net']+=money(d)
        if d['entry']==0:
            g['opened']+=d['volume']
            if not g['open_time']:
                g['open_time']=d['time_msc']/1000;g['side']='BUY' if d['type']==0 else 'SELL'
        elif d['entry'] in (1,3):
            g['closed']+=d['volume'];g['time']=d['time_msc']/1000
            g['time_msc']=d['time_msc'];g['last_ticket']=d['ticket']
        else:
            raise Blocked('История содержит netting/reversal, нужен DEMO hedging')
    live={int(p.get('identifier',p['ticket'])) for p in open_positions}
    rows=[]
    for key,g in groups.items():
        if key not in live and g['closed']>0 and g['opened']<=0:
            raise Blocked('Неполная история: отсутствует открытие закрытой позиции')
        if key not in live and g['opened']>0 and g['closed']>=g['opened']-1e-8:
            g['volume']=g['opened'];rows.append(g)
    return sorted(rows,key=lambda x:(x['time_msc'],x['last_ticket']))


def summary(rows):
    net=[float(x['net']) for x in rows]
    return dict(profit=sum(x for x in net if x>0),loss=sum(x for x in net if x<0),
                net=sum(net),count=len(net),wins=sum(x>0 for x in net))


def risk_state(account, positions, deals, cfg: Config, now: float, ack=(0,0), daily_latch=''):
    cfg.validate()
    if account.get('type')!='DEMO':
        raise Blocked('REAL запрещён: нужен DEMO-счёт')
    if account.get('margin_mode')!='HEDGING':
        raise Blocked('Для отдельных ступеней нужен DEMO hedging')
    if not account.get('trade_allowed'):
        raise Blocked('Торговля отключена в MT5')
    base=cfg.base(account)
    rows=ledger(deals,positions)
    series=[r for r in rows if (r['time_msc'],r['last_ticket'])>tuple(ack)]
    streak=0
    for r in reversed(series):
        if r['net']<0:streak+=1
        else:break
    # Calendar-day costs include entry commissions, not only realized exits.
    closed_today=sum(money(d) for d in deals if d.get('type') in (0,1) and d['time_msc']/1000>=day_start(now))
    floating=number(account['equity'],'equity')-number(account['balance'],'balance')
    day_loss=max(0,-(closed_today+floating))
    dd=max(0,-floating)
    day=datetime.fromtimestamp(now,LOCAL_DAY).date().isoformat()
    blocks=[]
    if day_loss>=base*cfg.daily_loss_pct/100 or daily_latch==day: blocks.append('DAILY_LOSS')
    if dd>=base*cfg.drawdown_pct/100: blocks.append('DRAWDOWN')
    if streak>=cfg.loss_streak: blocks.append('LOSS_STREAK')
    return dict(allowed=not blocks,blocks=blocks,daily_pl=closed_today,floating=floating,
        daily_loss_pct=day_loss/base*100,drawdown_pct=dd/base*100,consecutive_losses=streak,
        ack_supported=True,can_acknowledge=blocks==['LOSS_STREAK'],
        last_closing_ticket=rows[-1]['last_ticket'] if rows else 0,
        last_closing_time_msc=rows[-1]['time_msc'] if rows else 0,
        last_closing_time=rows[-1]['time'] if rows else 0,
        base=base,campaign_budget=cfg.budget(account),day=day)


@dataclass(frozen=True)
class Plan:
    side: int
    symbol: str
    volume: float
    entry: float
    stop: float
    adverse_entry: float
    adverse_stop: float
    risk: float
    total_risk: float
    margin: float
    event_id: str


def quantize(value,step,up=False):
    d=Decimal(str(value));s=Decimal(str(step))
    return float((d/s).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*s)


def plan_order(broker, cfg: Config, account, info, q: Quote, d: Decision, positions,
               campaign, now):
    cfg.validate();q.validate(now)
    if not cfg.approved or cfg.fee_per_lot is None:
        raise Blocked('Подтвердите риск и фактическую комиссию в профиле DEMO')
    if d.signal not in ('BUY','SELL') or not d.event_id:
        raise Blocked('Нет нового подтверждённого входа')
    if account.get('type')!='DEMO' or account.get('margin_mode')!='HEDGING':
        raise Blocked('Исполнение только DEMO hedging')
    if not account.get('trade_allowed'):
        raise Blocked('Торговля MT5 выключена')
    symbol=info['name'];point=number(info['point'],'point',positive=True)
    tick=number(info['tick_size'],'tick_size',positive=True)
    pip=point*10 if info['digits'] in (3,5) else point
    if q.spread/pip>cfg.spread_pips:
        raise Blocked('Спред превышает выбранный предел')
    if len(positions)>=cfg.technical_position_fuse:
        raise Blocked('Технический предохранитель: слишком много позиций')
    if cfg.optional_position_limit and len(positions)>=cfg.optional_position_limit:
        raise Blocked('Достигнут выбранный дополнительный лимит позиций')
    number(d.stop,'stop',positive=True);number(d.atr,'ATR',positive=True)
    side=d.side;price=q.ask if side==1 else q.bid
    if side not in (-1,1) or (price-d.stop)*side<=0:
        raise Blocked('Некорректная сторона стопа')
    distance=max(int(info['stops_level'])*point+tick,tick)
    # Final broker-valid stop BEFORE any volume calculation.
    stop=min(d.stop,q.bid-distance) if side==1 else max(d.stop,q.ask+distance)
    stop=quantize(stop,tick,up=side==-1)
    reserve=max(cfg.slippage_ticks*tick,q.spread)
    adverse_entry=price+side*reserve
    adverse_stop=stop-side*reserve
    vmin=number(info['volume_min'],'volume_min',positive=True)
    vmax=number(info['volume_max'],'volume_max',positive=True)
    step=number(info['volume_step'],'volume_step',positive=True)
    budget=float(campaign.get('budget',cfg.budget(account))) if campaign else cfg.budget(account)
    budget=min(budget,cfg.budget(account))
    spent=max(0,-float(campaign.get('realized',0))) if campaign else 0
    running_risk=spent
    net=0.
    for p in positions:
        ps=int(p['side']);psl=number(p['sl'],'existing SL',positive=True)
        if ps!=side or p['symbol']!=symbol:
            raise Blocked('Кампания другого направления/инструмента')
        risk=-number(broker.calc_profit(ps,p['symbol'],p['volume'],p['price_open'],psl-ps*reserve),'position stop P/L')
        running_risk+=max(0,risk)+cfg.fee_per_lot*p['volume']
        net+=number(p['profit'],'floating P/L')+number(p.get('swap',0),'swap')-cfg.fee_per_lot*number(p['volume'],'volume',positive=True)
    if positions:
        if not cfg.dynamic_adds: raise Blocked('Режим одного входа: добавления выключены')
        if net<=0: raise Blocked('Кампания не в чистом плюсе: усреднение запрещено')
        if not campaign: raise Blocked('Нельзя добавлять без сохранённой кампании')
        if (price-campaign['last_entry'])*side<d.atr*campaign['add_step_atr']:
            raise Blocked('Цена не прошла следующий шаг в сторону кампании')
    unit_loss=-number(broker.calc_profit(side,symbol,vmin,adverse_entry,adverse_stop),'planned P/L')/vmin+cfg.fee_per_lot
    if unit_loss<=0: raise Blocked('Не удалось оценить денежный риск стопа')
    available=budget-running_risk
    volume=quantize(min(vmax,cfg.lot_cap,available/unit_loss),step)
    if volume<vmin-1e-10 or volume<=0:
        raise Blocked(f'Минимальный лот {vmin:g} не помещается в остаток риска {max(0,available):.2f} USD')
    risk=unit_loss*volume
    if risk+running_risk>budget+1e-7:
        raise Blocked('Общий риск кампании превышен')
    margin=number(broker.calc_margin(side,symbol,volume,price),'margin')
    if margin<0: raise Blocked('Некорректная маржа')
    existing_margin=sum(number(broker.calc_margin(p['side'],p['symbol'],p['volume'],p['price_open']),'existing margin') for p in positions)
    if margin>number(account['margin_free'],'free margin',positive=True)*.8 or margin+existing_margin>cfg.base(account)*cfg.margin_fraction:
        raise Blocked('Недостаточно маржи в выбранной базе испытаний')
    return Plan(side,symbol,volume,price,stop,adverse_entry,adverse_stop,risk,running_risk+risk,margin,d.event_id)
