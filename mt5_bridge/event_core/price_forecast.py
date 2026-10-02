"""Read-only, causal price estimates, independent from any trading decision.

Historical analogue returns are a research model, not calibrated probabilities.
A forecast is immutable for its observation minute. Its empirical band is not a
confidence guarantee. No broker calls, position sizing or entry permissions here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from .model import TF_SECONDS, Quote, atr, bar_close_time, validate_bar_history


class PriceForecaster:
    MODEL = 'ANALOG_R7_1'
    WINDOW = 6
    MIN_SAMPLES = 8
    MAX_SAMPLES = 24
    HORIZONS = (5, 10, 15, 30, 60)

    def __init__(self):
        self._key = None
        self._cached = None

    @staticmethod
    def _quantile(values, fraction):
        rows = sorted(values)
        position = (len(rows)-1)*fraction
        lo = int(position)
        hi = min(lo+1, len(rows)-1)
        return rows[lo]+(rows[hi]-rows[lo])*(position-lo)

    def update(self, bars, q: Quote, now, *, symbol, timeframe, mode, scope):
        identity = '|'.join((scope, symbol, mode, timeframe, self.MODEL))
        empty = dict(available=False, model=self.MODEL, calibrated=False,
                     symbol=symbol, timeframe=timeframe, mode=mode, scope=identity,
                     projection=[], reason='', uncertainty_kind='EMPIRICAL_ANALOG_SPREAD',
                     direction=0, unavailable_horizons=[])
        try:
            q.validate(now)
            if timeframe not in TF_SECONDS or timeframe == 'MN1':
                raise ValueError('Ценовой прогноз для календарного периода ещё не проверен')
            rows = list(bars)[-1200:]
            if len(rows) < 48:
                raise ValueError('Для независимого прогноза нужно не менее 48 закрытых свечей')
            validate_bar_history(rows, timeframe, now)
            span = TF_SECONDS[timeframe]
            closed = [bar_close_time(b.time, timeframe, b.clock_offset_seconds) for b in rows]
            if closed[-1] > now or now-closed[-1] > span*1.5:
                raise ValueError('Закрытая история прогноза не соответствует текущему времени')
            volatility = atr(rows)
            if not math.isfinite(volatility) or volatility <= 0:
                raise ValueError('Не удалось определить масштаб ценового движения')
            minute = q.time_msc//60000
            # Include all source OHLC: corrected historical data yields a new snapshot.
            source_hash = hashlib.sha256(repr([(b.time,b.open,b.high,b.low,b.close)
                                               for b in rows]).encode()).hexdigest()
            key = (identity, minute, source_hash)
            if key == self._key:
                return copy.deepcopy(self._cached)
            query_start = rows[-self.WINDOW].time
            closes = [b.close for b in rows]
            scales = [max(rows[i].high-rows[i].low, volatility*.1) for i in range(len(rows))]
            def features(i):
                scale = max(sum(scales[i-self.WINDOW+1:i+1])/self.WINDOW, volatility*.1)
                return [(closes[j]-closes[j-1])/scale for j in range(i-self.WINDOW+1,i+1)],scale
            current_features, current_scale = features(len(rows)-1)
            native_minutes = span//60
            horizons = self.HORIZONS if native_minutes <= 60 else tuple(native_minutes*x for x in (1,2,3))
            by_time = {t:i for i,t in enumerate(closed)}
            points=[]; unavailable=[]
            for minutes in horizons:
                seconds = minutes*60
                if seconds % span:
                    unavailable.append(minutes); continue
                candidates=[]
                for i in range(self.WINDOW, len(rows)-self.WINDOW):
                    end = by_time.get(closed[i]+seconds)
                    if end is None or closed[end] > query_start:
                        continue
                    # A market/data gap is not the requested elapsed-time outcome.
                    if any(closed[j]-closed[j-1]!=span for j in range(i-self.WINDOW+1,end+1)):
                        continue
                    vector, scale = features(i)
                    distance = sum((a-b)**2 for a,b in zip(vector,current_features))
                    candidates.append((distance,i,end,(closes[end]-closes[i])/scale))
                # Greedy disjoint outcome windows limit duplicate evidence from nearby matches.
                chosen=[]
                for candidate in sorted(candidates):
                    _,i,end,_ = candidate
                    if any(not (end <= other[1] or i >= other[2]) for other in chosen):
                        continue
                    chosen.append(candidate)
                    if len(chosen) == self.MAX_SAMPLES:break
                if len(chosen) < self.MIN_SAMPLES:
                    unavailable.append(minutes);continue
                outcomes = [q.bid+x[3]*current_scale for x in chosen]
                if not all(math.isfinite(x) and x>0 for x in outcomes):
                    unavailable.append(minutes);continue
                points.append(dict(minutes=minutes,time=q.time_msc/1000+seconds,
                    center=self._quantile(outcomes,.5),low=self._quantile(outcomes,.2),
                    high=self._quantile(outcomes,.8),sample_count=len(chosen),
                    latest_training_outcome=max(closed[x[2]] for x in chosen)))
            if not points:
                raise ValueError('Недостаточно неперекрывающихся исторических примеров для выбранного периода')
            change = points[0]['center']-q.bid
            neutral = max(q.spread, volatility*.05)
            result = dict(empty,available=True,issued_at=q.time_msc/1000,origin=q.bid,
                query_window_start=query_start,source_last_close=closed[-1],source_hash=source_hash,
                projection=points,unavailable_horizons=unavailable,
                direction=1 if change>neutral else -1 if change<-neutral else 0,
                neutral_price_distance=neutral,
                reason='Исследовательский ценовой прогноз; не разрешение на сделку',
                baseline='LAST_OBSERVED_PRICE',sample_policy='DISJOINT_OUTCOMES_BEFORE_QUERY')
            result['snapshot_id']=hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False).encode()).hexdigest()[:32]
            self._key=key;self._cached=copy.deepcopy(result)
            return result
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as exc:
            self._key=None;self._cached=None
            return dict(empty, reason=str(exc))
