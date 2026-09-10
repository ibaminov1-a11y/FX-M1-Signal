"""NORMAL Campaign research configuration. Pure, deterministic, no order I/O.
No fallback from missing pivots to a quality score. Prices are MT5 prices only.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import hashlib
import math
from typing import Callable, Sequence

VERSION = '11.0.0-rc1'
PROTOCOL = 11
MAGIC = 720072

class Blocked(RuntimeError):
    """A fail-closed decision, suitable for the user-facing explanation."""

def finite(value: float, name: str, positive: bool = False) -> float:
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise Blocked('Некорректное значение: ' + name)
    return value

@dataclass(frozen=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float

@dataclass(frozen=True)
class Pivot:
    time: int
    confirmed_at: int
    price: float
    high: bool

@dataclass(frozen=True)
class Setup:
    side: int
    setup_id: str
    event_id: str
    event_time: int
    stop: float
    trigger: float
    atr: float
    reason: str
    proof: tuple

    def payload(self):
        return asdict(self)

def checked_bars(rows: Sequence[Candle], seconds: int, now: float, minimum: int) -> list[Candle]:
    # Future/open bars never enter any indicator or pivot calculation.
    out = []
    last = -1
    for c in rows:
        if c.time <= last:
            raise Blocked('Свечи не упорядочены или повторяются')
        last = c.time
        for k in ('open', 'high', 'low', 'close'):
            finite(getattr(c, k), k, True)
        if c.high < max(c.open, c.close, c.low) or c.low > min(c.open, c.close):
            raise Blocked('Некорректная OHLC-свеча')
        if c.time + seconds <= now:
            out.append(c)
    if len(out) < minimum:
        raise Blocked('Недостаточно завершённых свечей')
    if now - (out[-1].time + seconds) > seconds + 15:
        raise Blocked('Свечи MT5 устарели')
    # Intraday holes near the decision cannot silently become a valid retest.
    for a, b in zip(out[-12:], out[-11:]):
        if b.time - a.time != seconds:
            raise Blocked('Разрыв в последних свечах MT5')
    return out

def atr(c: Sequence[Candle], n: int = 14) -> float:
    if len(c) < n + 1:
        raise Blocked('Недостаточно свечей ATR')
    values = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
              for a, b in zip(c[-n-1:-1], c[-n:])]
    return finite(sum(values) / n, 'ATR', True)

def ema(values: Sequence[float], period: int) -> float:
    result = float(values[0])
    alpha = 2.0 / (period + 1)
    for x in values[1:]:
        result += alpha * (x - result)
    return result

def bias(c: Sequence[Candle]) -> int:
    if len(c) < 60:
        return 0
    v = [b.close for b in c]
    fast, slow = ema(v, 20), ema(v, 50)
    slope = fast - ema(v[:-3], 20)
    threshold = atr(c) * 0.05
    if fast > slow + threshold and slope > threshold and v[-1] > fast:
        return 1
    if fast < slow - threshold and slope < -threshold and v[-1] < fast:
        return -1
    return 0

def pivots(c: Sequence[Candle], seconds: int = 300, width: int = 2) -> list[Pivot]:
    points = []
    for i in range(width, len(c) - width):
        neighbors = list(c[i-width:i]) + list(c[i+1:i+width+1])
        is_high = all(c[i].high > x.high for x in neighbors)
        is_low = all(c[i].low < x.low for x in neighbors)
        # An outside candle that is both kinds is ambiguous, not a directional proof.
        if is_high == is_low:
            continue
        p = Pivot(c[i].time, c[i+width].time + seconds,
                  c[i].high if is_high else c[i].low, is_high)
        if points and points[-1].high == p.high:
            if (p.high and p.price > points[-1].price) or (not p.high and p.price < points[-1].price):
                points[-1] = p
        else:
            points.append(p)
    return points

def structure(c: Sequence[Candle]) -> tuple[int, list[Pivot]]:
    p = pivots(c)
    h, l = [x for x in p if x.high][-2:], [x for x in p if not x.high][-2:]
    if len(h) < 2 or len(l) < 2:
        return 0, p
    if h[-1].price > h[-2].price and l[-1].price > l[-2].price:
        return 1, p
    if h[-1].price < h[-2].price and l[-1].price < l[-2].price:
        return -1, p
    return 0, p

def retest_trigger(c: Sequence[Candle], side: int, minimum_time: int, point: float) -> bool:
    """An actual adverse leg BEFORE a resumed break; not merely a green/red candle."""
    if side not in (-1, 1) or len(c) < 20:
        return False
    w = c[-9:]
    last, prev = w[-1], w[-2]
    if last.time < minimum_time:
        return False
    a = atr(c)
    if side == 1:
        peak = max(range(0, 5), key=lambda i: w[i].high)
        trough = min(range(peak + 1, 8), key=lambda i: w[i].low)
        adverse = any(w[i].close < w[i-1].close for i in range(peak + 1, trough + 1))
        depth = w[peak].high - w[trough].low
        return (adverse and depth >= a * 0.35 and last.close > last.open
                and last.close > max(prev.high, w[-3].high) + point
                and last.low >= w[trough].low)
    bottom = min(range(0, 5), key=lambda i: w[i].low)
    crest = max(range(bottom + 1, 8), key=lambda i: w[i].high)
    adverse = any(w[i].close > w[i-1].close for i in range(bottom + 1, crest + 1))
    depth = w[crest].high - w[bottom].low
    return (adverse and depth >= a * 0.35 and last.close < last.open
            and last.close < min(prev.low, w[-3].low) - point
            and last.high <= w[crest].high)

def analyse(symbol: str, h1, m15, m5, m1, now: float, point: float) -> Setup:
    h1 = checked_bars(h1, 3600, now, 60)
    m15 = checked_bars(m15, 900, now, 60)
    m5 = checked_bars(m5, 300, now, 40)
    m1 = checked_bars(m1, 60, now, 20)
    direction, proof = structure(m5)
    if direction == 0:
        raise Blocked('WAIT: подтверждённая Swing/Pivot-структура M5 не сформирована')
    if bias(h1) != direction or bias(m15) != direction:
        raise Blocked('WAIT: контекст H1/M15 не подтверждает направление M5')
    support = [x for x in proof if x.high == (direction < 0)][-1]
    event_time = m1[-1].time + 60
    if now - event_time > 90:
        raise Blocked('WAIT: подтверждение M1 устарело')
    if not retest_trigger(m1, direction, support.confirmed_at, point):
        raise Blocked('WAIT: ждём откат и новый пробой после возобновления')
    a = atr(m5)
    stop = support.price - direction * 0.10 * a
    trigger = m1[-1].close
    if direction * (trigger - stop) <= 0:
        raise Blocked('WAIT: защитный уровень уже нарушен')
    identity = symbol + ':' + str(direction) + ':' + ','.join(str(x.time) for x in proof[-4:])
    setup_id = hashlib.sha256(identity.encode()).hexdigest()[:16]
    event_id = setup_id + ':' + str(event_time)
    return Setup(direction, setup_id, event_id, event_time, stop, trigger, a,
                 'BUY: откат и возобновление подтверждены' if direction > 0 else 'SELL: откат и возобновление подтверждены',
                 tuple(asdict(x) for x in proof[-4:]))

def fresh_quote(bid: float, ask: float, stamp: float, now: float) -> None:
    finite(bid, 'Bid', True); finite(ask, 'Ask', True)
    if ask < bid or stamp > now + 5 or now - stamp > 10:
        raise Blocked('Нет свежей корректной котировки MT5')

def rounded(value: float, step: float, up: bool = False) -> float:
    s = Decimal(str(finite(step, 'шаг', True)))
    d = Decimal(str(finite(value, 'значение'))) / s
    return float(d.to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * s)

def normalize_stop(side: int, stop: float, bid: float, ask: float,
                   point: float, tick_size: float, stops_level: int) -> float:
    distance = max(5, int(stops_level) + 2) * point
    if side == 1:
        return rounded(min(stop, bid - distance), tick_size)
    return rounded(max(stop, ask + distance), tick_size, True)

@dataclass(frozen=True)
class Plan:
    volume: float
    stop: float
    price: float
    planned_loss: float
    margin: float

def plan_order(*, side: int, stop: float, bid: float, ask: float,
               point: float, tick_size: float, stops_level: int,
               minimum: float, step: float, maximum: float, cap: float,
               fee_per_lot: float, equity: float, available_margin: float,
               calc_profit: Callable, calc_margin: Callable) -> Plan:
    for name, x in [('minimum', minimum), ('step', step), ('maximum', maximum), ('equity', equity)]:
        finite(x, name, True)
    if side not in (-1, 1):
        raise Blocked('Неизвестное направление')
    finite(cap, 'бюджет', True)
    if fee_per_lot < 0 or not math.isfinite(fee_per_lot):
        raise Blocked('Неизвестны издержки')
    final_stop = normalize_stop(side, stop, bid, ask, point, tick_size, stops_level)
    price = ask if side == 1 else bid
    # Both sides reserve two spread widths (at least 4 points) for execution variance.
    reserve = max(ask - bid, point * 2) * 2
    worst_entry = price + side * reserve
    worst_exit = final_stop - side * reserve
    def loss(v):
        value = calc_profit(side, v, worst_entry, worst_exit)
        if value is None:
            raise Blocked('MT5 не рассчитал денежный риск')
        return max(0.0, -finite(value, 'расчёт риска')) + v * fee_per_lot
    unit_loss = loss(minimum)
    if unit_loss <= 0:
        raise Blocked('Некорректный расчёт минимального риска')
    max_volume = min(maximum, 0.01, minimum * cap / unit_loss)
    volume = rounded(max_volume, step)
    if volume + 1e-10 < minimum:
        raise Blocked(f'Минимальный лот {minimum:g}: риск ${unit_loss:.2f} > бюджета ${cap:.2f}')
    actual = loss(volume)
    if actual > cap + 1e-8:
        raise Blocked('Расчёт объёма превысил бюджет')
    margin = calc_margin(side, volume, price)
    if margin is None:
        raise Blocked('MT5 не рассчитал маржу')
    margin = finite(margin, 'маржа')
    if margin < 0 or margin > min(equity, available_margin) + 1e-8:
        raise Blocked('Недостаточно расчётной или фактической маржи')
    return Plan(volume, final_stop, price, actual, margin)

def add_allowed(*, count: int, maximum: int, pnl: float, side: int,
                price: float, last_price: float, step_distance: float,
                new_event: bool, closing: bool, paused: bool) -> bool:
    return (0 < count < maximum <= 5 and pnl > 0 and not closing and not paused
            and new_event and side * (price - last_price) >= step_distance)
