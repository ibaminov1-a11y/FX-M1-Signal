from pathlib import Path
import sys, shutil, re, datetime, py_compile

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_OUT = ROOT / f"_BRIDGE_V9_3_FIX_BACKUP_{STAMP}"

def fail(msg):
    print("ERROR:", msg)
    sys.exit(1)

# Restore a clean V9.2 Bridge from the newest V9.2 backup created before V9.3 touched it.
candidates = sorted(
    [p for p in ROOT.glob("_V9_2_BACKUP_*") if (p / "mt5_bridge" / "bridge_v9_2.py").exists()],
    key=lambda p: p.stat().st_mtime,
    reverse=True
)
if not candidates:
    fail("Не найден чистый _V9_2_BACKUP_*/mt5_bridge/bridge_v9_2.py")

src = candidates[0] / "mt5_bridge" / "bridge_v9_2.py"
dst = ROOT / "mt5_bridge" / "bridge_v9_3.py"
current = ROOT / "mt5_bridge" / "bridge_v9_3.py"

BACKUP_OUT.mkdir(parents=True, exist_ok=True)
if current.exists():
    shutil.copy2(current, BACKUP_OUT / "bridge_v9_3_broken.py")

s = src.read_text(encoding="utf-8")
print("SOURCE:", src)

# Version.
s, n = re.subn(r'BRIDGE_VERSION\s*=\s*"9\.2"', 'BRIDGE_VERSION = "9.3"', s, count=1)
if n != 1:
    fail("Не удалось заменить BRIDGE_VERSION 9.2 -> 9.3")

# Replace the ENTIRE entry-state function, not fragments.
start = s.find("def _scalp_entry_state(")
if start < 0:
    fail("Не найдена функция _scalp_entry_state")
next_def = s.find("\ndef ", start + 10)
next_app = s.find("\n@app.", start + 10)
ends = [x for x in (next_def, next_app) if x > start]
if not ends:
    fail("Не найден конец _scalp_entry_state")
end = min(ends)

fixed_func = "\ndef _scalp_entry_state(symbol, side, tick, info, snap, state, basket):\n    now = time.time()\n    data = state.get('data') or {}\n    quality = int(data.get('quality') or 0)\n    _remember_tick(symbol, tick)\n    q = [x for x in list(_SCALP_TICKS.get(symbol, ())) if now - x[0] <= 14.0]\n    if len(q) < 10:\n        return False, 'WARMUP', {'stage': 'WARMUP', 'ticks': len(q)}\n\n    mids = [(x[1] + x[2]) * 0.5 for x in q]\n    cur = mids[-1]\n    point = max(float(getattr(info, 'point', 0.0) or 0.0), 1e-9)\n    spread = max(0.0, float(tick.ask) - float(tick.bid))\n    atr = max(float(snap.get('atr') or 0.0), point * 10.0, spread * 2.0)\n    cm = _SCALP_CAMPAIGN_META.setdefault((symbol, side), {})\n\n    recent = mids[-min(36, len(mids)):]\n    short = mids[-min(12, len(mids)):]\n    hi, lo = max(recent), min(recent)\n    short_hi, short_lo = max(short), min(short)\n    rng = max(hi - lo, point)\n    short_rng = max(short_hi - short_lo, point)\n    k = min(6, len(mids) - 1)\n    fast_move = cur - mids[-1-k]\n\n    near_high = (hi - cur) <= max(rng * 0.12, spread * 1.5, point * 4)\n    near_low = (cur - lo) <= max(rng * 0.12, spread * 1.5, point * 4)\n\n    if side == 'BUY':\n        favourable = fast_move > max(point, spread * 0.18)\n        counter = fast_move < -max(point * 0.8, spread * 0.15)\n        chase = favourable and near_high\n        pullback_depth = max(0.0, hi - cur)\n        pullback_ok = counter or pullback_depth >= max(atr * 0.07, spread * 1.2, point * 3)\n        rejection = favourable and cur >= short_lo + short_rng * 0.52\n        micro_break = cur >= max(short[:-1]) + max(point * 0.5, spread * 0.10)\n        m1_bias = (snap['last_close'] >= snap['last_open']) or (snap['last_close'] > snap['prev_close'])\n    else:\n        favourable = fast_move < -max(point, spread * 0.18)\n        counter = fast_move > max(point * 0.8, spread * 0.15)\n        chase = favourable and near_low\n        pullback_depth = max(0.0, cur - lo)\n        pullback_ok = counter or pullback_depth >= max(atr * 0.07, spread * 1.2, point * 3)\n        rejection = favourable and cur <= short_hi - short_rng * 0.52\n        micro_break = cur <= min(short[:-1]) - max(point * 0.5, spread * 0.10)\n        m1_bias = (snap['last_close'] <= snap['last_open']) or (snap['last_close'] < snap['prev_close'])\n\n    stage = cm.get('stage', 'BIAS')\n\n    # FIRST ENTRY: direction may come from SCALP intent even when GLOBAL=WAIT,\n    # but final execution still needs live MT5 timing. No weak early-probe.\n    if not basket:\n        if chase and stage not in ('PULLBACK', 'REJECTION', 'RESUME'):\n            cm.update(stage='WAIT_PULLBACK', chase_at=now, chase_price=cur)\n            return False, 'CHASE_BLOCK_WAIT_PULLBACK', {\n                'stage':'WAIT_PULLBACK','side':side,'quality':quality\n            }\n\n        if stage == 'WAIT_PULLBACK':\n            if pullback_ok:\n                cm.update(stage='PULLBACK', pullback_at=now, pullback_price=cur)\n            else:\n                return False, 'WAIT_PULLBACK', {\n                    'stage':'WAIT_PULLBACK','pullback_depth_atr':pullback_depth/atr\n                }\n\n        if cm.get('stage') == 'PULLBACK':\n            if rejection:\n                cm.update(stage='REJECTION', rejection_at=now, rejection_price=cur)\n            else:\n                return False, 'WAIT_REJECTION', {\n                    'stage':'PULLBACK','favourable':bool(favourable)\n                }\n\n        if cm.get('stage') == 'REJECTION':\n            if not favourable:\n                return False, 'WAIT_RESUME', {'stage':'REJECTION'}\n            cm['stage'] = 'RESUME'\n\n        confirmed = favourable and (\n            micro_break or\n            (cm.get('stage') == 'RESUME' and rejection)\n        )\n        if not confirmed:\n            return False, 'WAIT_MT5_ENTRY', {\n                'stage':cm.get('stage','BIAS'),\n                'quality':quality,\n                'm1_bias':bool(m1_bias),\n                'favourable':bool(favourable),\n                'micro_break':bool(micro_break),\n                'chase':bool(chase)\n            }\n\n        cm.update(stage='ENTRY', entry_trigger_at=now, trigger_price=cur)\n        return True, ('MICRO_BREAK' if micro_break else 'PULLBACK_RESUME'), {\n            'stage':'ENTRY','side':side,'quality':quality,'micro_break':bool(micro_break)\n        }\n\n    # SCALE-IN: only pyramid a profitable campaign. Never average down.\n    basket_pnl = sum(\n        float(p.profit) + float(getattr(p, 'swap', 0.0) or 0.0)\n        for p in basket\n    )\n    if basket_pnl <= 0.02:\n        return False, 'NO_ADD_RED_BASKET', {\n            'stage':'PROTECT','basket_pnl':basket_pnl\n        }\n\n    entries = [float(p.price_open) for p in basket]\n    best_entry = max(entries) if side == 'BUY' else min(entries)\n    px = float(tick.ask if side == 'BUY' else tick.bid)\n    progress = px - best_entry if side == 'BUY' else best_entry - px\n    spacing = max(\n        atr * max(0.05, safe_float(data.get('campaign_spacing_atr'), 0.07)),\n        spread * 1.20,\n        point * 4\n    )\n\n    if progress < spacing:\n        return False, 'WAIT_PROGRESS', {\n            'stage':'CONFIRM','basket_pnl':basket_pnl,\n            'progress':progress,'spacing':spacing\n        }\n\n    if chase and cm.get('stage') not in ('ADD_PULLBACK', 'ADD_REJECTION'):\n        cm['stage'] = 'ADD_WAIT_PULLBACK'\n        return False, 'ADD_CHASE_BLOCK', {\n            'stage':'ADD_WAIT_PULLBACK','basket_pnl':basket_pnl\n        }\n\n    if cm.get('stage') == 'ADD_WAIT_PULLBACK':\n        if pullback_ok:\n            cm['stage'] = 'ADD_PULLBACK'\n        else:\n            return False, 'ADD_WAIT_PULLBACK', {\n                'stage':'ADD_WAIT_PULLBACK','basket_pnl':basket_pnl\n            }\n\n    if cm.get('stage') == 'ADD_PULLBACK':\n        if rejection:\n            cm['stage'] = 'ADD_REJECTION'\n        else:\n            return False, 'ADD_WAIT_REJECTION', {\n                'stage':'ADD_PULLBACK','basket_pnl':basket_pnl\n            }\n\n    continuation = favourable and (\n        micro_break or cm.get('stage') == 'ADD_REJECTION'\n    )\n    if not continuation:\n        return False, 'ADD_WAIT_CONTINUATION', {\n            'stage':'ADD_CONFIRM',\n            'micro_break':bool(micro_break),\n            'rejection':bool(rejection),\n            'basket_pnl':basket_pnl\n        }\n\n    if now - float(cm.get('last_add_at', 0.0)) < 0.75:\n        return False, 'DEBOUNCE', {'stage':'ADD_CONFIRM'}\n\n    cm['last_add_at'] = now\n    cm['stage'] = 'SCALE_IN'\n    return True, 'SCALE_IN', {\n        'stage':'SCALE_IN','basket_pnl':basket_pnl,\n        'progress':progress,'spacing':spacing\n    }\n".lstrip("\n")
s = s[:start] + fixed_func.rstrip() + "\n\n" + s[end+1:]

# Add LIVE endpoint before position-action if absent.
if "@app.get('/live-state')" not in s:
    marker = "@app.post('/position-action')"
    idx = s.find(marker)
    if idx < 0:
        fail("Не найден /position-action для вставки /live-state")
    endpoint = '\n@app.get(\'/live-state\')\ndef live_state_v93():\n    raw = request.args.get(\'symbol\',\'\')\n    with LOCK:\n        if not ensure_mt5():\n            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503\n\n        account = mt5.account_info()\n        symbol = resolve_symbol(raw) if raw else None\n        tick = mt5.symbol_info_tick(symbol) if symbol else None\n        positions = mt5.positions_get() or []\n        pp = [position_payload(p) for p in positions]\n\n        intent = None\n        st = _SCALP_INTENTS.get(symbol) if symbol else None\n        if st:\n            side = st.get(\'side\')\n            basket = _scalp_positions(symbol, side)\n            cm = _SCALP_CAMPAIGN_META.get((symbol, side), {})\n            stage = cm.get(\'stage\', \'BIAS\')\n            stage_score = {\n                \'BIAS\':30, \'WAIT_PULLBACK\':38, \'PULLBACK\':52,\n                \'REJECTION\':68, \'RESUME\':80, \'ENTRY\':95,\n                \'CONFIRM\':72, \'ADD_WAIT_PULLBACK\':55,\n                \'ADD_PULLBACK\':66, \'ADD_REJECTION\':80,\n                \'ADD_CONFIRM\':88, \'SCALE_IN\':94, \'PROTECT\':45\n            }\n            api_q = int(st.get(\'quality\') or 0)\n            live_q = max(0, min(\n                100,\n                int(round(stage_score.get(stage,45) * 0.70 + api_q * 0.30))\n            ))\n            bp = sum(\n                float(p.profit) + float(getattr(p,\'swap\',0.0) or 0.0)\n                for p in basket\n            )\n            intent = {\n                \'side\':side,\n                \'api_quality\':api_q,\n                \'live_entry_quality\':live_q,\n                \'stage\':stage,\n                \'positions\':len(basket),\n                \'basket_pnl\':bp,\n                \'basket_peak\':float(_SCALP_BASKET_PEAK.get((symbol,side), bp)),\n                \'max_positions\':max(\n                    1,\n                    min(int((st.get(\'data\') or {}).get(\'max_positions\') or 10), 10)\n                )\n            }\n\n        latest = None\n        deals = history_deals(2)\n        outs = [\n            d for d in deals\n            if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)\n        ]\n        if outs:\n            d = outs[-1]\n            net = (\n                float(d.profit) +\n                float(d.commission) +\n                float(d.swap) +\n                float(getattr(d,\'fee\',0.0) or 0.0)\n            )\n            latest = {\n                \'deal_id\':int(d.ticket),\n                \'position_id\':int(d.position_id),\n                \'time\':int(d.time),\n                \'symbol\':d.symbol,\n                \'volume\':float(d.volume),\n                \'price\':float(d.price),\n                \'net_pl\':net,\n                \'profit\':float(d.profit),\n                \'commission\':float(d.commission),\n                \'swap\':float(d.swap),\n                \'comment\':str(getattr(d,\'comment\',\'\') or \'\')\n            }\n\n        return jsonify(\n            ok=True,\n            bridge_version=BRIDGE_VERSION,\n            server_time_ms=int(time.time()*1000),\n            account_type=account_type_name(account),\n            balance=float(account.balance),\n            equity=float(account.equity),\n            currency=account.currency,\n            positions=len(pp),\n            floating_pl=sum(x[\'profit\'] + x.get(\'swap\',0.0) for x in pp),\n            bid=float(tick.bid) if tick else None,\n            ask=float(tick.ask) if tick else None,\n            symbol=symbol,\n            scalp=intent,\n            last_closed=latest\n        )\n'.lstrip("\n")
    s = s[:idx] + endpoint.rstrip() + "\n\n\n" + s[idx:]

# Write to temporary file and COMPILE THE ACTUAL BRIDGE before replacing user's file.
tmp = ROOT / "mt5_bridge" / "_bridge_v9_3_compile_test.py"
tmp.write_text(s, encoding="utf-8", newline="\n")
try:
    py_compile.compile(str(tmp), doraise=True)
except Exception as e:
    print("COMPILE ERROR:", e)
    fail("Исправленный Bridge не прошёл py_compile; основной файл НЕ заменён")

dst.write_text(s, encoding="utf-8", newline="\n")
tmp.unlink(missing_ok=True)

start_bat = ROOT / "mt5_bridge" / "START_BRIDGE_V9_3.bat"
start_bat.write_text(
    '@echo off\ncd /d "%~dp0"\necho Starting FX M1 MT5 Bridge V9.3 LIVE...\n.venv\\Scripts\\python.exe bridge_v9_3.py\npause\n',
    encoding="utf-8"
)

print("OK: bridge_v9_3.py восстановлен из чистой V9.2 и пересобран.")
print("OK: py_compile bridge_v9_3.py")
print("OK: START_BRIDGE_V9_3.bat")
print("Bridge:", dst)
print("REAL safe-default не менялся.")
