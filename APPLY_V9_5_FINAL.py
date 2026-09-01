from pathlib import Path
import sys, re, shutil, datetime, py_compile

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
for c in (ROOT, ROOT.parent, ROOT.parent.parent):
    if (c / "app").is_dir() and (c / "mt5_bridge").is_dir():
        ROOT = c
        break

STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / f"_V9_5_BACKUP_{STAMP}"

bridge = ROOT / "mt5_bridge" / "bridge_v9_4.py"
monitor = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "MonitoringService.java"
feature = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "FeatureEngine.java"
main = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "MainActivity.java"
gradle = ROOT / "app" / "build.gradle"

targets = [bridge, monitor, feature, main, gradle]

def fail(msg):
    print("ERROR:", msg)
    print("Backup:", BACKUP)
    sys.exit(1)

def read(p):
    if not p.exists():
        fail("Не найден файл: " + str(p))
    return p.read_text(encoding="utf-8")

def write(p, s):
    p.write_text(s, encoding="utf-8", newline="\n")

def backup(p):
    dst = BACKUP / p.relative_to(ROOT)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)

def replace_regex_once(s, pattern, repl, label, flags=re.S):
    out, n = re.subn(pattern, repl, s, count=1, flags=flags)
    if n != 1:
        fail(f"{label}: совпадений {n}")
    print("OK:", label)
    return out

for p in targets:
    backup(p)

s = read(bridge)
if 'BRIDGE_VERSION = "9.4"' not in s:
    fail("bridge_v9_4.py не содержит BRIDGE_VERSION 9.4")
s = s.replace('BRIDGE_VERSION = "9.4"', 'BRIDGE_VERSION = "9.5"', 1)

anchor = "_SCALP_CAMPAIGN_META = {}"
if anchor in s and "_SCALP_REENTRY_LOCK" not in s:
    s = s.replace(anchor, anchor + "\n_SCALP_REENTRY_LOCK = {}        # (symbol,side) -> unix time", 1)

entry_v95 = r'''
def _scalp_entry_state(symbol, side, tick, info, snap, state, basket):
    # V9.5 final SCALP timing.
    # Intent is BIAS only:
    # WAIT_PULLBACK -> PULLBACK -> REJECTION -> RESUME -> MICRO_BREAK -> ENTRY.
    now = time.time()
    data = state.get('data') or {}
    quality = int(data.get('quality') or 0)

    _remember_tick(symbol, tick)
    q = [x for x in list(_SCALP_TICKS.get(symbol, ())) if now - x[0] <= 16.0]
    if len(q) < 10:
        return False, 'WARMUP', {'stage':'WARMUP','ticks':len(q)}

    mids = [(x[1] + x[2]) * 0.5 for x in q]
    cur = mids[-1]
    point = max(float(getattr(info, 'point', 0.0) or 0.0), 1e-9)
    spread = max(0.0, float(tick.ask) - float(tick.bid))
    atr = max(float(snap.get('atr') or 0.0), point * 10.0, spread * 2.0)
    cm = _SCALP_CAMPAIGN_META.setdefault((symbol, side), {})

    recent = mids[-min(40, len(mids)):]
    short = mids[-min(12, len(mids)):]
    hi, lo = max(recent), min(recent)
    short_hi, short_lo = max(short), min(short)
    rng = max(hi - lo, point)
    short_rng = max(short_hi - short_lo, point)
    k = min(6, len(mids) - 1)
    fast_move = cur - mids[-1-k]

    near_high = (hi - cur) <= max(rng * 0.12, spread * 1.5, point * 4)
    near_low = (cur - lo) <= max(rng * 0.12, spread * 1.5, point * 4)

    if side == 'BUY':
        favourable = fast_move > max(point, spread * 0.18)
        counter = fast_move < -max(point * 0.8, spread * 0.15)
        chase = favourable and near_high
        pullback_depth = max(0.0, hi - cur)
        pullback_ok = counter or pullback_depth >= max(atr * 0.06, spread * 1.10, point * 3)
        rejection = favourable and cur >= short_lo + short_rng * 0.52
        micro_break = cur >= max(short[:-1]) + max(point * 0.5, spread * 0.10)
    else:
        favourable = fast_move < -max(point, spread * 0.18)
        counter = fast_move > max(point * 0.8, spread * 0.15)
        chase = favourable and near_low
        pullback_depth = max(0.0, cur - lo)
        pullback_ok = counter or pullback_depth >= max(atr * 0.06, spread * 1.10, point * 3)
        rejection = favourable and cur <= short_hi - short_rng * 0.52
        micro_break = cur <= min(short[:-1]) - max(point * 0.5, spread * 0.10)

    if not basket:
        lock_until = float(_SCALP_REENTRY_LOCK.get((symbol, side), 0.0))
        if now < lock_until:
            return False, 'REENTRY_LOCK', {'stage':'REENTRY_LOCK','left':round(lock_until-now,2)}

        stage = cm.get('stage', 'BIAS')

        if stage in ('BIAS','WARMUP','ENTRY','SCALE_IN','PROTECT'):
            cm['stage'] = 'WAIT_PULLBACK'
            return False, ('CHASE_BLOCK_WAIT_PULLBACK' if chase else 'WAIT_PULLBACK'), {
                'stage':'WAIT_PULLBACK','side':side,'quality':quality,'chase':bool(chase)
            }

        if stage == 'WAIT_PULLBACK':
            if not pullback_ok:
                return False, 'WAIT_PULLBACK', {
                    'stage':'WAIT_PULLBACK','pullback_depth_atr':pullback_depth/max(atr,1e-12)
                }
            cm.update(stage='PULLBACK', pullback_at=now, pullback_price=cur)
            return False, 'PULLBACK_FOUND', {'stage':'PULLBACK'}

        if stage == 'PULLBACK':
            if not rejection:
                return False, 'WAIT_REJECTION', {'stage':'PULLBACK'}
            cm.update(stage='REJECTION', rejection_at=now, rejection_price=cur)
            return False, 'REJECTION_FOUND', {'stage':'REJECTION'}

        if stage == 'REJECTION':
            if not favourable:
                return False, 'WAIT_RESUME', {'stage':'REJECTION'}
            cm.update(stage='RESUME', resume_at=now)
            return False, 'RESUME_FOUND', {'stage':'RESUME'}

        if stage == 'RESUME':
            if not (favourable and micro_break):
                return False, 'WAIT_MICRO_BREAK', {
                    'stage':'RESUME','favourable':bool(favourable),'micro_break':bool(micro_break)
                }
            cm.update(stage='ENTRY', entry_trigger_at=now, trigger_price=cur)
            return True, 'MICRO_BREAK', {
                'stage':'ENTRY','side':side,'quality':quality,'micro_break':True
            }

        cm['stage'] = 'WAIT_PULLBACK'
        return False, 'WAIT_PULLBACK', {'stage':'WAIT_PULLBACK'}

    basket_pnl = sum(float(p.profit) + float(getattr(p, 'swap', 0.0) or 0.0) for p in basket)
    if basket_pnl <= 0.20:
        return False, 'NO_ADD_RED_OR_FLAT_BASKET', {'stage':'PROTECT','basket_pnl':basket_pnl}

    entries = [float(p.price_open) for p in basket]
    best_entry = max(entries) if side == 'BUY' else min(entries)
    px = float(tick.ask if side == 'BUY' else tick.bid)
    progress = px - best_entry if side == 'BUY' else best_entry - px

    spacing = max(
        atr * max(0.04, safe_float(data.get('campaign_spacing_atr'), 0.06)),
        spread * 1.10,
        point * 4
    )

    if progress < spacing:
        return False, 'WAIT_PROGRESS', {
            'stage':'CONFIRM','basket_pnl':basket_pnl,'progress':progress,'spacing':spacing
        }

    if chase:
        cm['stage'] = 'ADD_WAIT_PULLBACK'
        return False, 'ADD_CHASE_BLOCK', {'stage':'ADD_WAIT_PULLBACK','basket_pnl':basket_pnl}

    if cm.get('stage') == 'ADD_WAIT_PULLBACK':
        if not pullback_ok:
            return False, 'ADD_WAIT_PULLBACK', {'stage':'ADD_WAIT_PULLBACK'}
        cm['stage'] = 'ADD_PULLBACK'
        return False, 'ADD_PULLBACK_FOUND', {'stage':'ADD_PULLBACK'}

    if cm.get('stage') == 'ADD_PULLBACK':
        if not rejection:
            return False, 'ADD_WAIT_REJECTION', {'stage':'ADD_PULLBACK'}
        cm['stage'] = 'ADD_REJECTION'
        return False, 'ADD_REJECTION_FOUND', {'stage':'ADD_REJECTION'}

    if not (favourable and micro_break):
        return False, 'ADD_WAIT_MICRO_BREAK', {
            'stage':'ADD_CONFIRM','micro_break':bool(micro_break),'basket_pnl':basket_pnl
        }

    if now - float(cm.get('last_add_at', 0.0)) < 0.75:
        return False, 'DEBOUNCE', {'stage':'ADD_CONFIRM'}

    cm['last_add_at'] = now
    cm['stage'] = 'SCALE_IN'
    return True, 'SCALE_IN', {
        'stage':'SCALE_IN','basket_pnl':basket_pnl,'progress':progress,'spacing':spacing
    }


'''

s = replace_regex_once(
    s,
    r'def _scalp_entry_state\(symbol, side, tick, info, snap, state, basket\):.*?(?=def scalp_autonomous_once\(\):)',
    entry_v95,
    "Bridge: full V9.5 entry/pyramiding"
)

s = s.replace("max_positions=max(1,int(data.get('max_positions') or 8))",
              "max_positions=max(1,min(10,int(data.get('max_positions') or 10)))")

s = s.replace("'scalp_campaign_single_arm_usd': 0.05,", "'scalp_campaign_single_arm_usd': 0.90,")
s = s.replace("'scalp_basket_peak_giveback_pct': 15.0,", "'scalp_basket_peak_giveback_pct': 28.0,")
s = s.replace("'scalp_basket_peak_min_giveback_usd': 0.02,", "'scalp_basket_peak_min_giveback_usd': 0.25,")

basket_new = r'''giveback_pct = max(18.0, min(safe_float(cfg.get('scalp_basket_peak_giveback_pct'), 28.0), 65.0)) / 100.0
                min_giveback = max(0.25, safe_float(cfg.get('scalp_basket_peak_min_giveback_usd'), 0.25))
                campaign_arm = max(1.25, safe_float(cfg.get('scalp_campaign_arm_usd'), 1.25))
                giveback = max(min_giveback, peak * giveback_pct)
                reversed_from_peak = peak >= campaign_arm and gpnl > 0.0 and gpnl <= peak - giveback
                if reversed_from_peak:'''


# V9.5 ROBUST: replace complete basket-lock trigger block.
_basket_old = "                giveback_pct = max(5.0, min(safe_float(cfg.get('scalp_basket_peak_giveback_pct'), 18.0), 60.0)) / 100.0\n                min_giveback = max(0.01, safe_float(cfg.get('scalp_basket_peak_min_giveback_usd'), 0.02))\n                giveback = max(min_giveback, peak * giveback_pct)\n                reversed_from_peak = peak > 0.0 and gpnl <= peak - giveback\n                lost_green = peak > 0.0 and gpnl <= 0.0\n                if reversed_from_peak or lost_green:\n"
_basket_new = "                giveback_pct = max(18.0, min(safe_float(cfg.get('scalp_basket_peak_giveback_pct'), 28.0), 65.0)) / 100.0\n                min_giveback = max(0.25, safe_float(cfg.get('scalp_basket_peak_min_giveback_usd'), 0.25))\n                campaign_arm = max(1.25, safe_float(cfg.get('scalp_campaign_arm_usd'), 1.25))\n                giveback = max(min_giveback, peak * giveback_pct)\n                reversed_from_peak = peak >= campaign_arm and gpnl > 0.0 and gpnl <= peak - giveback\n                if reversed_from_peak:\n"
_basket_count = s.count(_basket_old)
if _basket_count != 1:
    fail("Bridge basket-lock exact block: expected 1, found " + str(_basket_count))
s = s.replace(_basket_old, _basket_new, 1)
print("OK: Bridge: basket lock exact block replaced")


green_new = r'''campaign_enabled = bool(cfg.get('scalp_campaign_enabled', True))
        campaign_multi = ticket in campaign_multi_tickets
        single_arm = max(0.90, safe_float(cfg.get('scalp_campaign_single_arm_usd'), 0.90))
        giveback_pct = max(20.0, min(safe_float(cfg.get('scalp_single_peak_giveback_pct'), 32.0), 65.0)) / 100.0
        min_giveback = max(0.25, safe_float(cfg.get('scalp_single_peak_min_giveback_usd'), 0.25))
        green_capture_armed = peak >= single_arm
        if bool(cfg.get('scalp_peak_lock_enabled', True)) and green_capture_armed and not campaign_multi:
            giveback = max(min_giveback, peak * giveback_pct)
            reversed_from_peak = pnl_usd <= peak - giveback
            if reversed_from_peak and pnl_usd > 0.0:
                ok, close_res = close_position_internal(p, comment='FXM1 PROFIT LOCK')
                if ok:
                    _SCALP_REENTRY_LOCK[(p.symbol, 'BUY' if p.type == mt5.POSITION_TYPE_BUY else 'SELL')] = time.time() + 2.0
                    print(f"PROFIT_LOCK closed ticket={ticket} arm={single_arm:.2f} peak={peak:.4f} current={pnl_usd:.4f}")
                    _SCALP_PEAK_PNL.pop(ticket, None)
                    _SCALP_LAST_PNL.pop(ticket, None)
                    continue
        _SCALP_LAST_PNL[ticket] = pnl_usd'''


# V9.5 ROBUST: replace the complete old GREEN_CAPTURE block including its else.
_green_old = '        campaign_enabled = bool(cfg.get(\'scalp_campaign_enabled\', True))\n        campaign_multi = ticket in campaign_multi_tickets\n        single_arm = max(0.0, safe_float(cfg.get(\'scalp_campaign_single_arm_usd\'), 0.20))\n        green_capture_armed = peak > 0.0\n        if bool(cfg.get(\'scalp_peak_lock_enabled\', True)) and green_capture_armed and not campaign_multi:\n            prev_pnl = float(_SCALP_LAST_PNL.get(ticket, pnl_usd))\n            # Tiny tolerance avoids reacting to formatting/rounding noise only.\n            eps = 0.005\n            reversed_from_peak = pnl_usd + eps < peak\n            downtick = pnl_usd + eps < prev_pnl\n            # Once we have shown a green P/L, never intentionally let it rotate through zero.\n            lost_green = pnl_usd <= 0.0\n            if reversed_from_peak and (downtick or lost_green):\n                ok, close_res = close_position_internal(p, comment=\'FXM1 GREEN CAP\')\n                if ok:\n                    print(f"GREEN_CAPTURE closed ticket={ticket} peak={peak:.4f} current={pnl_usd:.4f}")\n                    _SCALP_PEAK_PNL.pop(ticket, None)\n                    _SCALP_LAST_PNL.pop(ticket, None)\n                    continue\n                else:\n                    print(f"GREEN_CAPTURE retry ticket={ticket} peak={peak:.4f} current={pnl_usd:.4f} result={close_res}")\n            _SCALP_LAST_PNL[ticket] = pnl_usd\n        else:\n            _SCALP_LAST_PNL[ticket] = pnl_usd\n'
_green_new = '        campaign_enabled = bool(cfg.get(\'scalp_campaign_enabled\', True))\n        campaign_multi = ticket in campaign_multi_tickets\n        single_arm = max(0.90, safe_float(cfg.get(\'scalp_campaign_single_arm_usd\'), 0.90))\n        giveback_pct = max(20.0, min(safe_float(cfg.get(\'scalp_single_peak_giveback_pct\'), 32.0), 65.0)) / 100.0\n        min_giveback = max(0.25, safe_float(cfg.get(\'scalp_single_peak_min_giveback_usd\'), 0.25))\n        green_capture_armed = peak >= single_arm\n        if bool(cfg.get(\'scalp_peak_lock_enabled\', True)) and green_capture_armed and not campaign_multi:\n            giveback = max(min_giveback, peak * giveback_pct)\n            reversed_from_peak = pnl_usd <= peak - giveback\n            if reversed_from_peak and pnl_usd > 0.0:\n                ok, close_res = close_position_internal(p, comment=\'FXM1 PROFIT LOCK\')\n                if ok:\n                    _SCALP_REENTRY_LOCK[(p.symbol, \'BUY\' if p.type == mt5.POSITION_TYPE_BUY else \'SELL\')] = time.time() + 2.0\n                    print(f"PROFIT_LOCK closed ticket={ticket} arm={single_arm:.2f} peak={peak:.4f} current={pnl_usd:.4f}")\n                    _SCALP_PEAK_PNL.pop(ticket, None)\n                    _SCALP_LAST_PNL.pop(ticket, None)\n                    continue\n        _SCALP_LAST_PNL[ticket] = pnl_usd\n'
_green_count = s.count(_green_old)
if _green_count != 1:
    fail("Bridge GREEN_CAPTURE exact block: expected 1, found " + str(_green_count))
s = s.replace(_green_old, _green_new, 1)
print("OK: Bridge: complete GREEN_CAPTURE block replaced")


s = s.replace(
    "effective_hard = min(limits['hard_loss_usd'], 0.75 if group_size <= 1 else 1.50)",
    "effective_hard = min(limits['hard_loss_usd'], 1.25 if group_size <= 1 else 2.00)"
)


# Final source audit before compile.
forbidden = [
    "FXM1 GREEN CAP",
    "GREEN_CAPTURE closed",
    "lost_green = peak > 0.0",
    "early_probe =",
]
for marker in forbidden:
    if marker in s:
        fail("V9.5 audit failed; forbidden old marker remains: " + marker)
if "PROFIT_LOCK closed" not in s:
    fail("V9.5 audit failed: PROFIT_LOCK code missing")
if "WAIT_MICRO_BREAK" not in s:
    fail("V9.5 audit failed: mandatory micro-break state missing")
print("OK: V9.5 source audit: old Green Cap / early probe absent")

stage = ROOT / "mt5_bridge" / "_bridge_v9_5_compile_test.py"
write(stage, s)
try:
    py_compile.compile(str(stage), doraise=True)
except Exception as e:
    stage.unlink(missing_ok=True)
    fail("bridge_v9_5 compile failed: " + str(e))
stage.unlink(missing_ok=True)

bridge95 = ROOT / "mt5_bridge" / "bridge_v9_5.py"
write(bridge95, s)
(ROOT / "mt5_bridge" / "START_BRIDGE_V9_5.bat").write_text(
    '@echo off\ncd /d "%~dp0"\necho Starting FX M1 MT5 Bridge V9.5 FINAL...\n.venv\\Scripts\\python.exe bridge_v9_5.py\npause\n',
    encoding="utf-8"
)
print("OK: bridge_v9_5.py py_compile")

m = read(monitor)
direction_block = r'''
        // V9.5: GLOBAL BUY/SELL/WAIT is informational for SCALP.
        // SCALP computes its own BIAS; Bridge owns exact MT5 entry/add/exit timing.
        int scalpDirectionScore = 0;
        if ("SCALP".equals(mode)) {
            scalpDirectionScore += sHigher2 * 20;
            scalpDirectionScore += sHigher1 * 25;
            scalpDirectionScore += sEntry * 30;
            scalpDirectionScore += sFast * 15;
            scalpDirectionScore += structure * 10;
            scalpDirectionScore = Math.max(-100, Math.min(100, scalpDirectionScore));
        }
        String scalpIntent = executionSignal;
        if ("SCALP".equals(mode)) {
            if (scalpDirectionScore >= 40) scalpIntent = "BUY";
            else if (scalpDirectionScore <= -40) scalpIntent = "SELL";
            else scalpIntent = "WAIT";
        }

'''

if "// V9.0: SCALP separates directional intent" in m:
    m = replace_regex_once(
        m,
        r'\s*// V9\.0: SCALP separates directional intent.*?(?=\s*double slMult)',
        "\n" + direction_block,
        "Android: independent SCALP direction"
    )
elif "// V9.2: GLOBAL signal is not a SCALP blocker." in m:
    m = replace_regex_once(
        m,
        r'\s*// V9\.2: GLOBAL signal is not a SCALP blocker\..*?(?=\s*double slMult)',
        "\n" + direction_block,
        "Android: independent SCALP direction"
    )
elif "// V9.5: GLOBAL BUY/SELL/WAIT" not in m:
    fail("MonitoringService: scalpIntent block not found")

m = m.replace('payload.put("campaign_spacing_atr", 0.12);',
              'payload.put("campaign_spacing_atr", 0.06);')
m = m.replace('payload.put("campaign_spacing_atr", 0.07);',
              'payload.put("campaign_spacing_atr", 0.06);')
m = m.replace('payload.put("scalp_campaign_single_arm_usd", 0.05);',
              'payload.put("scalp_campaign_single_arm_usd", 0.90);')
m = m.replace('payload.put("scalp_basket_peak_giveback_pct", 15.0);',
              'payload.put("scalp_basket_peak_giveback_pct", 28.0);')
m = m.replace('payload.put("scalp_basket_peak_min_giveback_usd", 0.02);',
              'payload.put("scalp_basket_peak_min_giveback_usd", 0.25);')
m = m.replace('if ("SCALP".equals(mode) && maxPos <= 3) maxPos = 8;',
              'if ("SCALP".equals(mode) && maxPos <= 3) maxPos = 10;')
write(monitor, m)
print("OK: MonitoringService V9.5")

f = read(feature)
f = f.replace('o.put("scalp_campaign_single_arm_usd", 0.20);',
              'o.put("scalp_campaign_single_arm_usd", 0.90);')
f = f.replace('o.put("scalp_basket_peak_giveback_pct", 25.0);',
              'o.put("scalp_basket_peak_giveback_pct", 28.0);')
f = f.replace('o.put("scalp_basket_peak_min_giveback_usd", 0.03);',
              'o.put("scalp_basket_peak_min_giveback_usd", 0.25);')
f = f.replace('o.put("scalp_max_hold_sec", 90);',
              'o.put("scalp_max_hold_sec", 180);')
write(feature, f)
print("OK: FeatureEngine V9.5")

a = read(main)
lot_new = 'String[] scalpLots = {"AUTO","0.01","0.02","0.03","0.04","0.05","0.06","0.07","0.08","0.09","0.10","0.15","0.20","0.25","0.30","0.40","0.50","0.75","1.00","1.50","2.00","3.00","5.00","10.00","20.00","50.00","100.00"};'
a, n = re.subn(r'String\[\] scalpLots = \{[^;]+\};', lot_new, a, count=1)
if n != 1:
    fail("MainActivity: scalpLots not found")
a = a.replace(
    'new String[]{"1", "2", "3"}',
    'new String[]{"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}'
)
needle = 'int basketMaxPositions = Integer.parseInt(maxPositions);'
replacement = needle + '\n                if ("SCALP".equals(selectedSignalMode()) && basketMaxPositions <= 3) basketMaxPositions = 10;'
if replacement not in a and needle in a:
    a = a.replace(needle, replacement, 1)
write(main, a)
print("OK: MainActivity lots + positions")

g = read(gradle)
g, n = re.subn(r'versionName\s+["\'][^"\']+["\']', 'versionName "9.5"', g, count=1)
if n != 1:
    fail("build.gradle versionName not found")
g = re.sub(r'versionCode\s+(\d+)', lambda x: f"versionCode {int(x.group(1))+1}", g, count=1)
write(gradle, g)

print()
print("============================================")
print("DONE: FX M1 BOT V9.5 FINAL")
print("Bridge compile: OK")
print("Bridge:", bridge95)
print("Start: mt5_bridge\\START_BRIDGE_V9_5.bat")
print("REAL remains DISABLED by safe default.")
print("Backup:", BACKUP)
print("============================================")
