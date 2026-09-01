
from pathlib import Path
import re, sys, shutil, datetime

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / f"_V9_1_BACKUP_{STAMP}"

def fail(msg):
    print("ERROR:", msg)
    sys.exit(1)

def read(p):
    if not p.exists():
        fail(f"Не найден файл: {p}")
    return p.read_text(encoding="utf-8")

def write(p, s):
    p.write_text(s, encoding="utf-8", newline="\n")

def backup_file(p):
    rel = p.relative_to(ROOT)
    dst = BACKUP / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)

def replace_once(text, pattern, repl, label, flags=re.S):
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        fail(f"Не удалось применить блок: {label} (совпадений {n})")
    print("OK:", label)
    return new

bridge = ROOT / "mt5_bridge" / "bridge_v9_1.py"
monitor = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "MonitoringService.java"
feature = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "FeatureEngine.java"
main = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "MainActivity.java"
gradle = ROOT / "app" / "build.gradle"

for p in [bridge, monitor, feature, main, gradle]:
    backup_file(p)

s = read(bridge)
s = re.sub(r'BRIDGE_VERSION\s*=\s*"9\.1"', 'BRIDGE_VERSION = "9.2"', s, count=1)

entry_v92 = r"""
def _scalp_entry_state(symbol, side, tick, info, snap, state, basket):
    now = time.time()
    data = state.get('data') or {}
    quality = int(data.get('quality') or 0)
    _remember_tick(symbol, tick)
    q = [x for x in list(_SCALP_TICKS.get(symbol, ())) if now - x[0] <= 14.0]
    if len(q) < 10:
        return False, 'WARMUP', {'stage': 'WARMUP', 'ticks': len(q)}

    mids = [(x[1] + x[2]) * 0.5 for x in q]
    cur = mids[-1]
    point = max(float(getattr(info, 'point', 0.0) or 0.0), 1e-9)
    spread = max(0.0, float(tick.ask) - float(tick.bid))
    atr = max(float(snap.get('atr') or 0.0), point * 10.0, spread * 2.0)
    cm = _SCALP_CAMPAIGN_META.setdefault((symbol, side), {})

    recent = mids[-min(36, len(mids)):]
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
        pullback_ok = counter or pullback_depth >= max(atr * 0.07, spread * 1.2, point * 3)
        rejection = favourable and cur >= short_lo + short_rng * 0.52
        micro_break = cur >= max(short[:-1]) + max(point * 0.5, spread * 0.10)
        m1_bias = (snap['last_close'] >= snap['last_open']) or (snap['last_close'] > snap['prev_close'])
    else:
        favourable = fast_move < -max(point, spread * 0.18)
        counter = fast_move > max(point * 0.8, spread * 0.15)
        chase = favourable and near_low
        pullback_depth = max(0.0, cur - lo)
        pullback_ok = counter or pullback_depth >= max(atr * 0.07, spread * 1.2, point * 3)
        rejection = favourable and cur <= short_hi - short_rng * 0.52
        micro_break = cur <= min(short[:-1]) - max(point * 0.5, spread * 0.10)
        m1_bias = (snap['last_close'] <= snap['last_open']) or (snap['last_close'] < snap['prev_close'])

    stage = cm.get('stage', 'BIAS')

    if not basket:
        if chase and stage not in ('PULLBACK', 'REJECTION', 'RESUME'):
            cm.update(stage='WAIT_PULLBACK', chase_at=now, chase_price=cur)
            return False, 'CHASE_BLOCK_WAIT_PULLBACK', {'stage':'WAIT_PULLBACK','side':side,'quality':quality}

        if stage == 'WAIT_PULLBACK':
            if pullback_ok:
                cm.update(stage='PULLBACK', pullback_at=now, pullback_price=cur)
            else:
                return False, 'WAIT_PULLBACK', {'stage':'WAIT_PULLBACK','pullback_depth_atr':pullback_depth/atr}

        if cm.get('stage') == 'PULLBACK':
            if rejection:
                cm.update(stage='REJECTION', rejection_at=now, rejection_price=cur)
            else:
                return False, 'WAIT_REJECTION', {'stage':'PULLBACK','favourable':bool(favourable)}

        if cm.get('stage') == 'REJECTION':
            if not favourable:
                return False, 'WAIT_RESUME', {'stage':'REJECTION'}
            cm['stage'] = 'RESUME'

        early_probe = quality >= 45 and m1_bias and favourable and not chase
        confirmed = favourable and (micro_break or (cm.get('stage') == 'RESUME' and rejection))
        if not (confirmed or early_probe):
            cm['stage'] = 'BIAS'
            return False, 'WAIT_MT5_ENTRY', {
                'stage':'BIAS','quality':quality,'m1_bias':bool(m1_bias),
                'favourable':bool(favourable),'micro_break':bool(micro_break),'chase':bool(chase)
            }

        cm.update(stage='ENTRY', entry_trigger_at=now, trigger_price=cur)
        return True, ('MICRO_BREAK' if micro_break else 'EARLY_RESUME'), {
            'stage':'ENTRY','side':side,'quality':quality,'micro_break':bool(micro_break)
        }

    basket_pnl = sum(float(p.profit) + float(getattr(p, 'swap', 0.0) or 0.0) for p in basket)
    if basket_pnl <= 0.0:
        return False, 'NO_ADD_RED_BASKET', {'stage':'PROTECT','basket_pnl':basket_pnl}

    entries = [float(p.price_open) for p in basket]
    best_entry = max(entries) if side == 'BUY' else min(entries)
    px = float(tick.ask if side == 'BUY' else tick.bid)
    progress = px - best_entry if side == 'BUY' else best_entry - px
    spacing = max(atr * max(0.10, safe_float(data.get('campaign_spacing_atr'), 0.14)),
                  spread * 1.8, point * 6)

    if progress < spacing:
        return False, 'WAIT_PROGRESS', {'stage':'CONFIRM','basket_pnl':basket_pnl,'progress':progress,'spacing':spacing}
    if chase:
        cm['stage'] = 'ADD_WAIT_PULLBACK'
        return False, 'ADD_CHASE_BLOCK', {'stage':'ADD_WAIT_PULLBACK','basket_pnl':basket_pnl}
    if cm.get('stage') == 'ADD_WAIT_PULLBACK':
        if pullback_ok:
            cm['stage'] = 'ADD_PULLBACK'
        else:
            return False, 'ADD_WAIT_PULLBACK', {'stage':'ADD_WAIT_PULLBACK'}
    if cm.get('stage') == 'ADD_PULLBACK':
        if rejection:
            cm['stage'] = 'ADD_REJECTION'
        else:
            return False, 'ADD_WAIT_REJECTION', {'stage':'ADD_PULLBACK'}
    if not (favourable and micro_break):
        return False, 'ADD_WAIT_MICRO_BREAK', {'stage':'ADD_CONFIRM','micro_break':bool(micro_break)}
    if now - float(cm.get('last_add_at', 0.0)) < 1.5:
        return False, 'DEBOUNCE', {'stage':'ADD_CONFIRM'}

    return True, 'SCALE_IN', {
        'stage':'SCALE_IN','basket_pnl':basket_pnl,'progress':progress,'spacing':spacing
    }

"""
s = replace_once(s, r'def _scalp_entry_state\(symbol, side, tick, info, snap, state, basket\):.*?(?=def scalp_autonomous_once\(\):)', entry_v92,
                 "Bridge: anti-chase BUY/SELL")

s = s.replace("'scalp_campaign_single_arm_usd': 0.05,", "'scalp_campaign_single_arm_usd': 0.90,")
s = s.replace("'scalp_basket_peak_giveback_pct': 15.0,", "'scalp_basket_peak_giveback_pct': 28.0,")
s = s.replace("'scalp_basket_peak_min_giveback_usd': 0.02,", "'scalp_basket_peak_min_giveback_usd': 0.25,")

green_repl = r"""campaign_enabled = bool(cfg.get('scalp_campaign_enabled', True))
        campaign_multi = ticket in campaign_multi_tickets
        single_arm = max(0.60, safe_float(cfg.get('scalp_campaign_single_arm_usd'), 0.90))
        giveback_pct = max(15.0, min(safe_float(cfg.get('scalp_single_peak_giveback_pct'), 30.0), 65.0)) / 100.0
        min_giveback = max(0.15, safe_float(cfg.get('scalp_single_peak_min_giveback_usd'), 0.25))
        green_capture_armed = peak >= single_arm
        if bool(cfg.get('scalp_peak_lock_enabled', True)) and green_capture_armed and not campaign_multi:
            giveback = max(min_giveback, peak * giveback_pct)
            reversed_from_peak = pnl_usd <= peak - giveback
            if reversed_from_peak and pnl_usd > 0.0:
                ok, close_res = close_position_internal(p, comment='FXM1 PROFIT LOCK')
                if ok:
                    print(f"PROFIT_LOCK closed ticket={ticket} arm={single_arm:.2f} peak={peak:.4f} current={pnl_usd:.4f}")
                    _SCALP_PEAK_PNL.pop(ticket, None)
                    _SCALP_LAST_PNL.pop(ticket, None)
                    continue
            _SCALP_LAST_PNL[ticket] = pnl_usd
        else:
            _SCALP_LAST_PNL[ticket] = pnl_usd"""
s = replace_once(
    s,
    r"campaign_enabled = bool\(cfg\.get\('scalp_campaign_enabled', True\)\).*?_SCALP_LAST_PNL\[ticket\] = pnl_usd",
    green_repl,
    "Bridge: tiny GREEN_CAPTURE removed"
)

basket_repl = r"""giveback_pct = max(15.0, min(safe_float(cfg.get('scalp_basket_peak_giveback_pct'), 28.0), 65.0)) / 100.0
                min_giveback = max(0.20, safe_float(cfg.get('scalp_basket_peak_min_giveback_usd'), 0.25))
                campaign_arm = max(1.00, safe_float(cfg.get('scalp_campaign_arm_usd'), 1.25))
                giveback = max(min_giveback, peak * giveback_pct)
                reversed_from_peak = peak >= campaign_arm and gpnl > 0.0 and gpnl <= peak - giveback
                if reversed_from_peak:"""
s = replace_once(
    s,
    r"giveback_pct = max\(5\.0, min\(safe_float\(cfg\.get\('scalp_basket_peak_giveback_pct'\), 18\.0\), 60\.0\)\) / 100\.0.*?if reversed_from_peak or lost_green:",
    basket_repl,
    "Bridge: basket lock requires meaningful profit"
)

s = s.replace(
    "effective_hard = min(limits['hard_loss_usd'], 0.75 if group_size <= 1 else 1.50)",
    "effective_hard = min(limits['hard_loss_usd'], 1.25 if group_size <= 1 else 2.00)"
)

ledger = r"""
@app.get('/trade-ledger')
def trade_ledger_v92():
    days = int(request.args.get('days', '30'))
    limit = min(max(int(request.args.get('limit', '200')), 1), 1000)
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        deals = history_deals(days)
        by_pos = {}
        for d in deals:
            pid = int(getattr(d, 'position_id', 0) or 0)
            if pid > 0:
                by_pos.setdefault(pid, []).append(d)
        rows = []
        for pid, ds in by_pos.items():
            ds.sort(key=lambda x: int(getattr(x, 'time_msc', 0) or int(x.time) * 1000))
            ins = [d for d in ds if d.entry in (mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_INOUT)]
            outs = [d for d in ds if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT)]
            if not ins or not outs:
                continue
            first, last = ins[0], outs[-1]
            vin = sum(float(d.volume) for d in ins)
            vout = sum(float(d.volume) for d in outs)
            entry_price = sum(float(d.price)*float(d.volume) for d in ins)/vin if vin > 0 else float(first.price)
            exit_price = sum(float(d.price)*float(d.volume) for d in outs)/vout if vout > 0 else float(last.price)
            gross = sum(float(d.profit) for d in outs)
            commission = sum(float(d.commission) for d in ds)
            swap = sum(float(d.swap) for d in ds)
            fee = sum(float(getattr(d, 'fee', 0.0) or 0.0) for d in ds)
            rows.append({
                'position_id': pid, 'symbol': first.symbol,
                'side': 'BUY' if int(first.type) == int(mt5.DEAL_TYPE_BUY) else 'SELL',
                'volume': vin, 'entry_time': int(first.time), 'exit_time': int(last.time),
                'duration_sec': max(0, int(last.time)-int(first.time)),
                'entry_price': entry_price, 'exit_price': exit_price,
                'gross_pl': gross, 'commission': commission, 'swap': swap, 'fee': fee,
                'net_pl': gross + commission + swap + fee,
                'open_comment': str(getattr(first,'comment','') or ''),
                'close_comment': str(getattr(last,'comment','') or '')
            })
        rows.sort(key=lambda x: x['exit_time'], reverse=True)
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, count=min(len(rows),limit), trades=rows[:limit])

"""
s = replace_once(s, r"(?=@app\.post\('/position-action'\))", ledger, "Bridge: detailed trade ledger", flags=0)
write(bridge, s)

m = read(monitor)
intent_block = r"""
        // V9.2: GLOBAL signal is not a SCALP blocker.
        int scalpDirectionScore = 0;
        if ("SCALP".equals(mode)) {
            scalpDirectionScore += sHigher2 * 25;
            scalpDirectionScore += sHigher1 * 30;
            scalpDirectionScore += sEntry * 30;
            scalpDirectionScore += sFast * 15;
            scalpDirectionScore += structure * 10;
            scalpDirectionScore = Math.max(-100, Math.min(100, scalpDirectionScore));
        }
        String scalpIntent = executionSignal;
        if ("SCALP".equals(mode)) {
            if (scalpDirectionScore >= 45) scalpIntent = "BUY";
            else if (scalpDirectionScore <= -45) scalpIntent = "SELL";
            else scalpIntent = "WAIT";
        }

"""
m = replace_once(
    m,
    r'\s*// V9\.0: SCALP separates directional intent from the exact execution trigger\..*?(?=\s*double slMult)',
    "\n" + intent_block,
    "Android BG: separate SCALP Direction Score"
)
m = m.replace('payload.put("scalp_campaign_single_arm_usd", 0.05);', 'payload.put("scalp_campaign_single_arm_usd", 0.90);')
m = m.replace('payload.put("scalp_basket_peak_giveback_pct", 15.0);', 'payload.put("scalp_basket_peak_giveback_pct", 28.0);')
m = m.replace('payload.put("scalp_basket_peak_min_giveback_usd", 0.02);', 'payload.put("scalp_basket_peak_min_giveback_usd", 0.25);')
write(monitor, m)

f = read(feature)
f = f.replace('o.put("scalp_campaign_single_arm_usd", 0.20);', 'o.put("scalp_campaign_single_arm_usd", 0.90);')
f = f.replace('o.put("scalp_basket_peak_giveback_pct", 25.0);', 'o.put("scalp_basket_peak_giveback_pct", 28.0);')
f = f.replace('o.put("scalp_basket_peak_min_giveback_usd", 0.03);', 'o.put("scalp_basket_peak_min_giveback_usd", 0.25);')
f = f.replace('o.put("scalp_max_hold_sec", 90);', 'o.put("scalp_max_hold_sec", 180);', 1)

trade_fmt = r"""    public static String formatTradeLog(JSONObject root) {
        JSONArray arr = root == null ? null : root.optJSONArray("trades");
        if (arr == null || arr.length() == 0) return "ТОРГОВЫЙ ЖУРНАЛ: пока пусто";
        StringBuilder sb = new StringBuilder("ТОРГОВЫЙ ЖУРНАЛ · ДЕНЬГИ");
        SimpleDateFormat fmt = new SimpleDateFormat("dd.MM HH:mm:ss", Locale.US);
        for (int i = 0; i < Math.min(arr.length(), 30); i++) {
            JSONObject e = arr.optJSONObject(i);
            if (e == null) continue;
            long a = e.optLong("entry_time",0), b = e.optLong("exit_time",0);
            sb.append("\n\n").append(a>0?fmt.format(new Date(a*1000L)):"—")
              .append(" → ").append(b>0?fmt.format(new Date(b*1000L)):"—")
              .append("\n").append(e.optString("symbol","—")).append(" · ")
              .append(e.optString("side","—")).append(" · ")
              .append(String.format(Locale.US,"%.2f lot",e.optDouble("volume",0)))
              .append("\nEntry ").append(String.format(Locale.US,"%.5f",e.optDouble("entry_price",0)))
              .append(" → Exit ").append(String.format(Locale.US,"%.5f",e.optDouble("exit_price",0)))
              .append(" · ").append(e.optInt("duration_sec",0)).append("s")
              .append("\nGross ").append(String.format(Locale.US,"%+.2f",e.optDouble("gross_pl",0)))
              .append(" · Comm ").append(String.format(Locale.US,"%+.2f",e.optDouble("commission",0)))
              .append(" · Swap ").append(String.format(Locale.US,"%+.2f",e.optDouble("swap",0)))
              .append("\nNET ").append(String.format(Locale.US,"%+.2f",e.optDouble("net_pl",0)));
            String reason=e.optString("close_comment","");
            if(!reason.isEmpty()) sb.append(" · ").append(reason);
        }
        return sb.toString();
    }

"""
f = replace_once(
    f,
    r'    public static String formatTradeLog\(JSONObject root\) \{.*?(?=    public static String formatPositions\()',
    trade_fmt,
    "Android: detailed money journal"
)
write(feature, f)

a = read(main)
a = a.replace(
    'JSONObject log = FeatureEngine.httpJson("GET", base + "/trade-log?limit=200", null);',
    'JSONObject log = FeatureEngine.httpJson("GET", base + "/trade-ledger?days=30&limit=200", null);'
)
a = a.replace('СДЕЛКИ MT5 · ДО 200 СОБЫТИЙ', 'ТОРГОВЫЙ ЖУРНАЛ MT5 · ДО 200 ЗАКРЫТЫХ СДЕЛОК')
write(main, a)

g = read(gradle)
g, n = re.subn(r'versionName\s+["\'][^"\']+["\']', 'versionName "9.2"', g, count=1)
if n != 1:
    fail("Не удалось изменить versionName")
g = re.sub(r'versionCode\s+(\d+)', lambda x: f"versionCode {int(x.group(1))+1}", g, count=1)
write(gradle, g)

bridge92 = ROOT / "mt5_bridge" / "bridge_v9_2.py"
write(bridge92, read(bridge))
(ROOT / "mt5_bridge" / "START_BRIDGE_V9_2.bat").write_text(
    '@echo off\ncd /d "%~dp0"\necho Starting FX M1 MT5 Bridge V9.2...\n.venv\\Scripts\\python.exe bridge_v9_2.py\npause\n',
    encoding="utf-8"
)

print("V9.2 применена.")
print("Backup:", BACKUP)
print("Bridge:", bridge92)
