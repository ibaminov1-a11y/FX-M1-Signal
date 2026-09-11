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
    'NORMAL': Profile('NORMAL', .35, .65, .60, 8, 12, 1.5, .50),
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
    # 0 means actual account equity. A non-zero value is a separate simulation base,
    # never a substitute for the MT5 balance displayed to the user.
    test_capital: float = 100.0
    absolute_risk_cap: float = .50
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
        for name in ('risk_pct','daily_loss_pct','drawdown_pct','lot_cap','absolute_risk_cap',
                     'margin_fraction','spread_pips'):
            number(getattr(self,name),name,positive=True)
        number(self.test_capital, 'test_capital')
        if self.test_capital < 0 or self.risk_pct > 1 or self.margin_fraction > .5:
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
        equity = number(account['equity'], 'equity', positive=True)
        balance = number(account['balance'], 'balance', positive=True)
        return min(balance, equity, self.test_capital if self.test_capital else balance)

    def budget(self, account):
        return min(self.absolute_risk_cap, self.base(account)*self.risk_pct/100)


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
    """A pivot is available only after `width` bars to its right have closed."""
    result=[]
    for i in range(width,len(bars)-width):
        b=bars[i]; window=bars[i-width:i]+bars[i+1:i+width+1]
        if all(b.high>x.high for x in window):
            result.append({'kind':'H','time':b.time,'price':b.high,'known_at':bars[i+width].time})
        if all(b.low<x.low for x in window):
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
