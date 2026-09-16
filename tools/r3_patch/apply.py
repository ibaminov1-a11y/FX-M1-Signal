from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'mt5_bridge/event_core/model.py'
text=p.read_text(encoding='utf-8')

old="""@dataclass(frozen=True)\nclass Decision:\n    signal: str = 'WAIT'\n    phase: str = 'SEARCH'\n    reason: str = 'Ожидаем сценарий'\n    event_id: str = ''\n    side: int = 0\n    stop: float = 0\n    trigger: float = 0\n    invalidation: float = 0\n    atr: float = 0\n    event_time: int = 0\n    levels: tuple = ()\n\n    def json(self):\n        return asdict(self)\n"""
new="""@dataclass(frozen=True)\nclass Decision:\n    signal: str = 'WAIT'\n    phase: str = 'SEARCH'\n    reason: str = 'Ожидаем сценарий'\n    event_id: str = ''\n    side: int = 0\n    stop: float = 0\n    trigger: float = 0\n    invalidation: float = 0\n    atr: float = 0\n    event_time: int = 0\n    levels: tuple = ()\n    # R3 fields are appended so every old positional Decision(...) call remains valid.\n    path: str = 'SEARCH'\n    structure: tuple = ()\n\n    def json(self):\n        return asdict(self)\n"""
if text.count(old)!=1:
    raise SystemExit('Decision block not found exactly once')
text=text.replace(old,new,1)

old2="""def direction(points):\n    highs=[p for p in points if p['kind']=='H']\n    lows=[p for p in points if p['kind']=='L']\n    if len(highs)<2 or len(lows)<2:\n        return 0\n    if highs[-1]['price']>highs[-2]['price'] and lows[-1]['price']>lows[-2]['price']:\n        return 1\n    if highs[-1]['price']<highs[-2]['price'] and lows[-1]['price']<lows[-2]['price']:\n        return -1\n    return 0\n"""
new2=old2+"""\n\ndef swing_labels(bars: list[Bar]):\n    \"\"\"Return confirmed immutable pivots with HH/HL/LH/LL chart labels.\n\n    The underlying pivot kind is kept in `pivot_kind` so callers never need to infer\n    whether HH/LH is a high or HL/LL is a low from the display label.\n    \"\"\"\n    out=[]\n    previous={'H':None,'L':None}\n    for p in pivots(bars):\n        base=p['kind']; prior=previous[base]; price=p['price']\n        if prior is None or price==prior:\n            label=base\n        elif base=='H':\n            label='HH' if price>prior else 'LH'\n        else:\n            label='HL' if price>prior else 'LL'\n        out.append({**p,'pivot_kind':base,'kind':label})\n        previous[base]=price\n    return out\n\n\ndef context_direction(bars: list[Bar]):\n    \"\"\"Direction from confirmed pivots only; 0 means neutral/insufficient.\"\"\"\n    return direction(pivots(bars))\n"""
if text.count(old2)!=1:
    raise SystemExit('direction block not found exactly once')
text=text.replace(old2,new2,1)
p.write_text(text,encoding='utf-8')
