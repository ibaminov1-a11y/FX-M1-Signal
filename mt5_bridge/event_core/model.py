from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal
import math

class Blocked(ValueError):
    """A deliberate inhibition, not permission to substitute unsafe defaults."""


def number(value, label='number', *, positive=False):
    x = float(value)
    if not math.isfinite(x) or (positive and x <= 0):
        raise Blocked(f'Некорректное значение: {label}')
    return x


@dataclass(frozen=True)
class Bar:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0

    def __post_init__(self):
        if self.time < 0:
            raise Blocked('Некорректное время свечи')
        for x in (self.open, self.high, self.low, self.close):
            number(x, 'OHLC', positive=True)
        if not (self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high):
            raise Blocked('Некорректная свеча OHLC')


@dataclass(frozen=True)
class Quote:
    time_msc: int
    bid: float
    ask: float

    def validate(self, now: float, max_age=10.0):
        number(self.bid, 'Bid', positive=True)
        number(self.ask, 'Ask', positive=True)
        if self.ask < self.bid or self.time_msc <= 0:
            raise Blocked('Некорректная котировка MT5')
        age = now - self.time_msc / 1000
        if age > max_age or age < -2:
            raise Blocked('Котировка MT5 устарела или часы расходятся')
        return self

    @property
    def spread(self):
        return self.ask-self.bid


@dataclass(frozen=True)
class Profile:
    name: str
    pullback_atr: float
    no_chase_atr: float
    add_step_atr: float
    setup_bars: int
    progress_bars: int
    protect_at_r: float
    giveback_fraction: float


PROFILES = {
    'NORMAL': Profile('NORMAL', .35, .65, .60, 3, 12, 1.5, .50),
    'SCALP': Profile('SCALP', .20, .30, .30, 4, 4, 1.0, .35),
}
# Parameters are fixed research hypotheses, not fitted performance claims.
TF_SECONDS = {'M1': 60, 'M5': 300, 'M10': 600, 'M15': 900,
              'H1': 3600, 'H4': 14400, 'D1': 86400, 'W1': 604800, 'MN1': 2592000}


@dataclass
class Config:
    symbol: str = 'EUR/USD'
    timeframe: str = 'M5'
    mode: str = 'NORMAL'
    risk_pct: float = .25
    daily_loss_pct: float = 3.0
    drawdown_pct: float = 5.0
    loss_streak: int = 3
    fee_per_lot: float | None = None
    lot_cap: float = .01
    # Legacy compatibility fields. EC1-R2 always sizes campaigns from the actual MT5
    # balance/equity; these values no longer cap or replace the live account base.
    test_capital: float = 0.0
    absolute_risk_cap: float = 0.0
    margin_fraction: float = .30
    spread_pips: float = 3.0
    slippage_ticks: int = 3
    cooldown_sec: int = 600
    dynamic_adds: bool = True
    optional_position_limit: int = 0
    max_orders_per_minute: int = 6
    technical_position_fuse: int = 128
    session_filter: bool = False
    allowed_sessions: str = 'LONDON,NEW_YORK'
    approved: bool = False

    def validate(self):
        if self.mode not in PROFILES or self.timeframe not in TF_SECONDS:
            raise Blocked('Неизвестный режим или таймфрейм')
        if not self.symbol or len(self.symbol) > 32:
            raise Blocked('Некорректный инструмент')
        for name in ('risk_pct','lot_cap','margin_fraction','spread_pips'):
            number(getattr(self,name),name,positive=True)
        number(self.test_capital, 'test_capital')
        number(self.absolute_risk_cap, 'absolute_risk_cap')
        if self.test_capital < 0 or self.absolute_risk_cap < 0 or self.risk_pct > 1 or self.margin_fraction > .5:
            raise Blocked('Профиль превышает пределы DEMO-испытаний')
        if self.daily_loss_pct>5 or self.drawdown_pct>10:
            raise Blocked('Дневной лимит/просадка превышают пределы DEMO-профиля')
        if self.loss_streak < 1 or self.loss_streak > 10:
            raise Blocked('Некорректный предел серии убытков')
        if not 0 <= self.optional_position_limit <= 128:
            raise Blocked('Некорректный предел позиций')
        if self.fee_per_lot is not None and number(self.fee_per_lot, 'commission') < 0:
            raise Blocked('Комиссия не может быть отрицательной')
        if not 1 <= self.max_orders_per_minute <= 12 or not 1 <= self.technical_position_fuse <= 128:
            raise Blocked('Нельзя убрать технический предохранитель ордеров')
        if not 1 <= self.slippage_ticks <= 100 or not 0 <= self.cooldown_sec <= 86400:
            raise Blocked('Некорректные параметры исполнения')
        return self

    def base(self, account):
        # Campaign sizing is based on the actual MT5 account only. Historical V10/manual
        # trades may affect the live balance/equity, but there is no artificial $100 base.
        equity = number(account['equity'], 'equity', positive=True)
        balance = number(account['balance'], 'balance', positive=True)
        return min(balance, equity)

    def budget(self, account):
        # One campaign receives the selected percentage of current usable account equity.
        # The legacy absolute dollar cap is intentionally ignored in EC1-R2.
        return self.base(account)*self.risk_pct/100


@dataclass
class Setup:
    id: str
    side: int
    kind: str
    phase: str
    born: int
    expires: int
    invalidation: float
    level: float
    extreme: float
    pullback: float = 0
    trigger: float = 0
    trigger_bar: int = 0
    armed_msc: int = 0
    last_bid: float = 0
    seen_safe_side: bool = False
    last_bar: int = 0


@dataclass(frozen=True)
class Decision:
    signal: str = 'WAIT'
    phase: str = 'SEARCH'
    reason: str = 'Ожидаем сценарий'
    event_id: str = ''
    side: int = 0
    stop: float = 0
    trigger: float = 0
    invalidation: float = 0
    atr: float = 0
    event_time: int = 0
    levels: tuple = ()
    path: str = 'SEARCH'
    structure: tuple = ()

    def json(self):
        return asdict(self)


def ordered(bars: list[Bar]):
    if any(a.time >= b.time for a,b in zip(bars,bars[1:])):
        raise Blocked('Свечи не упорядочены или содержат повторы')
    return bars


def atr(bars: list[Bar], period=14):
    if len(bars) < period+1:
        raise Blocked('Недостаточно закрытых свечей для ATR')
    ranges = [max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close))
              for a,b in zip(bars[:-1], bars[1:])]
    result = sum(ranges[-period:])/period
    return number(result, 'ATR', positive=True)


def pivots(bars: list[Bar], width=2):
    """Confirmed pivots with deterministic plateau handling.

    A pivot becomes usable only after `width` bars on its right are closed. Equal-price
    plateaus are common in MT5 data; choosing the right-most member avoids losing the
    level while still producing one deterministic point without future leakage.
    """
    result=[]
    for i in range(width,len(bars)-width):
        b=bars[i]
        left=bars[i-width:i]
        right=bars[i+1:i+width+1]
        window=left+right
        high=max([b.high]+[x.high for x in window])
        low=min([b.low]+[x.low for x in window])
        if b.high==high and any(b.high>x.high for x in window) and not any(x.high==b.high for x in right):
            result.append({'kind':'H','time':b.time,'price':b.high,'known_at':bars[i+width].time})
        if b.low==low and any(b.low<x.low for x in window) and not any(x.low==b.low for x in right):
            result.append({'kind':'L','time':b.time,'price':b.low,'known_at':bars[i+width].time})
    return result


def direction(points):
    highs=[p for p in points if p['kind']=='H']
    lows=[p for p in points if p['kind']=='L']
    if len(highs)<2 or len(lows)<2:
        return 0
    if highs[-1]['price']>highs[-2]['price'] and lows[-1]['price']>lows[-2]['price']:
        return 1
    if highs[-1]['price']<highs[-2]['price'] and lows[-1]['price']<lows[-2]['price']:
        return -1
    return 0


def swing_labels(bars: list[Bar]):
    """Label only confirmed pivots; labels never depend on the forming candle."""
    last_high=None;last_low=None;result=[]
    for point in pivots(bars):
        label=point['kind']
        if point['kind']=='H':
            label='H' if last_high is None else ('HH' if point['price']>last_high else 'LH')
            last_high=point['price']
        else:
            label='L' if last_low is None else ('HL' if point['price']>last_low else 'LL')
            last_low=point['price']
        result.append({**point,'label':label})
    return tuple(result)


def live_structure(bars: list[Bar], live_bar: Bar | None):
    """Presentation-only provisional zigzag.

    Confirmed pivots remain untouched and are the only pivots used by Strategy.
    This overlay extends the last confirmed pivot to the current leg so the UI
    does not wait two more M5 closes before showing what price is doing now.
    """
    confirmed=list(swing_labels(bars))
    if not confirmed or live_bar is None:
        return ()
    anchor=confirmed[-1]
    tail=[b for b in bars if b.time>anchor['time']]
    tail.append(live_bar)
    out=[{**anchor,'provisional':False}]
    if anchor['kind']=='L':
        candidate=max(tail,key=lambda b:b.high)
        previous=[x for x in confirmed if x['kind']=='H']
        price=candidate.high
        label='H?' if not previous else ('HH?' if price>previous[-1]['price'] else 'LH?')
        kind='H'
    else:
        candidate=min(tail,key=lambda b:b.low)
        previous=[x for x in confirmed if x['kind']=='L']
        price=candidate.low
        label='L?' if not previous else ('HL?' if price>previous[-1]['price'] else 'LL?')
        kind='L'
    out.append({'kind':kind,'time':candidate.time,'price':price,'label':label,'provisional':True})
    if live_bar.time!=candidate.time or abs(live_bar.close-price)>1e-12:
        out.append({'kind':'LIVE','time':live_bar.time,'price':live_bar.close,
                    'label':'LIVE','provisional':True})
    return tuple(out)


def context_direction(bars: list[Bar]):
    return direction(pivots(bars))
