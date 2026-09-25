"""Prospective structural levels shared by decisions and their visual explanation.

Paths are conditional hypotheses, not future candles or calibrated probabilities.
Time coordinates only space the drawing; they are not predicted arrival times.
"""
from __future__ import annotations

import math


def entry_levels(m1, a, spread):
    """Compute once per observed closed-M1 frame, before a crossing is eligible."""
    pad = max(a * .02, spread * 1.2)
    prior = m1[-5:-1]
    buy = max(x.high for x in prior) + pad
    sell = min(x.low for x in prior) - pad
    return {
        'BUY': {'trigger': buy, 'invalidation': min(min(x.low for x in m1[-7:]) - pad,
                                                   buy - .30 * a)},
        'SELL': {'trigger': sell, 'invalidation': max(max(x.high for x in m1[-7:]) + pad,
                                                     sell + .30 * a + spread)},
    }


def build_map(current, a, side, up, down, range_weight, levels, points, bars):
    recent = bars[-12:]
    lows = [p['price'] for p in points if p['kind'] == 'L']
    highs = [p['price'] for p in points if p['kind'] == 'H']
    support = next((p for p in reversed(lows) if p < current), min(x.low for x in recent))
    resistance = next((p for p in reversed(highs) if p > current), max(x.high for x in recent))
    measured_range = max(max(x.high for x in recent) - min(x.low for x in recent),
                         levels['BUY']['trigger'] - levels['SELL']['trigger'], a)
    result = dict(
        map_version=2, live_price=current, support=support, resistance=resistance,
        entry_levels={key: dict(value) for key, value in levels.items()},
        model_weight_kind='UNCALIBRATED_SCORE', path_time_kind='ILLUSTRATIVE_NOT_ETA',
        uncertainty_kind='ATR_SCALE_NOT_CONFIDENCE_INTERVAL',
        range_weight=round(range_weight, 4), scenarios=[],
    )
    if side not in (-1, 1):
        return result
    for name, scenario_side in (('PRIMARY', side), ('ALTERNATIVE', -side)):
        key = 'BUY' if scenario_side == 1 else 'SELL'
        activation = levels[key]['trigger']
        invalidation = levels[key]['invalidation']
        reference = max(current, activation) if scenario_side == 1 else min(current, activation)
        candidates = [p for p in (highs if scenario_side == 1 else lows)
                      if (p - reference) * scenario_side > a * .02]
        if candidates:
            target = min(candidates) if scenario_side == 1 else max(candidates)
            target_source = 'CONFIRMED_STRUCTURE'
        else:
            # A labelled measured-range extension, anchored to the trigger. Never
            # imply that an unobserved target or future time is confirmed structure.
            steps = max(1, math.floor((current - activation) * scenario_side / measured_range) + 1)
            target = activation + scenario_side * measured_range * steps
            target_source = 'MEASURED_RANGE_EXTENSION'
        first_leg = activation + (target - activation) * .35
        weight = round(up if scenario_side == 1 else down, 4)
        result['scenarios'].append(dict(
            name=name, side=scenario_side, probability=weight, model_weight=weight,
            activation=activation, invalidation=invalidation, target=target,
            target_source=target_source, condition='FRESH_CROSS_AND_ENTRY_GATES',
            path=[dict(minutes=0, price=current, anchor='LIVE'),
                  dict(minutes=4, price=first_leg, anchor='MEASURED_BREAK_LEG'),
                  dict(minutes=9, price=activation, anchor='TRIGGER_RETEST'),
                  dict(minutes=15, price=target, anchor=target_source)],
        ))
        for point in result['scenarios'][-1]['path']:
            point['uncertainty'] = a * .30 * math.sqrt(point['minutes'] / 5)
    return result
