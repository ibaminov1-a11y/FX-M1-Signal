from pathlib import Path
import sys, shutil, datetime, re, subprocess, py_compile

START = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()

def detect_root(p):
    p = p.resolve()
    for c in [p, p.parent, p.parent.parent]:
        if (c / "app").is_dir() and (c / "mt5_bridge").is_dir():
            return c
    return p

ROOT = detect_root(START)
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
ROLLBACK = ROOT / f"_V9_4_ROLLBACK_{STAMP}"

TARGETS = [
    Path("mt5_bridge/bridge_v9_1.py"),
    Path("app/src/main/java/com/openai/fxm1/MonitoringService.java"),
    Path("app/src/main/java/com/openai/fxm1/FeatureEngine.java"),
    Path("app/src/main/java/com/openai/fxm1/MainActivity.java"),
    Path("app/build.gradle"),
]

def save_current():
    for rel in TARGETS:
        src = ROOT / rel
        if src.exists():
            dst = ROLLBACK / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

def rollback():
    if not ROLLBACK.exists():
        return
    for rel in TARGETS:
        src = ROLLBACK / rel
        if src.exists():
            dst = ROOT / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

def die(msg):
    print("ERROR:", msg)
    rollback()
    sys.exit(1)

def read(p):
    return p.read_text(encoding="utf-8")

def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")

def find_clean_v91():
    candidates = []
    for pat in ("_V9_1_BACKUP_*", "_V9_2_BACKUP_*", "_V9_3_FIX_BACKUP_*"):
        candidates += [p for p in ROOT.glob(pat) if p.is_dir()]
    candidates.append(ROOT)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for c in candidates:
        b = c / "mt5_bridge/bridge_v9_1.py"
        if not b.exists():
            continue
        try:
            py_compile.compile(str(b), doraise=True)
            return c
        except Exception:
            pass
    return None

def source_file(base, rel):
    p = base / rel
    if p.exists():
        return p
    p = ROOT / rel
    if p.exists():
        return p
    raise FileNotFoundError(str(rel))

def replace_once(text, old, new, label):
    if new in text:
        print("OK:", label, "(already)")
        return text
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {n}")
    print("OK:", label)
    return text.replace(old, new, 1)

print("FX M1 BOT V9.4 STABLE")
print("Project:", ROOT)
save_current()

clean = find_clean_v91()
if clean is None:
    die("No compilable V9.1 Bridge found")
print("Clean base:", clean)

try:
    bridge = read(source_file(clean, Path("mt5_bridge/bridge_v9_1.py")))
    monitor = read(source_file(clean, Path("app/src/main/java/com/openai/fxm1/MonitoringService.java")))
    feature = read(source_file(clean, Path("app/src/main/java/com/openai/fxm1/FeatureEngine.java")))
    main = read(source_file(clean, Path("app/src/main/java/com/openai/fxm1/MainActivity.java")))
    gradle = read(source_file(clean, Path("app/build.gradle")))
except Exception as e:
    die(str(e))

bridge, n = re.subn(r'BRIDGE_VERSION\s*=\s*"9\.1"', 'BRIDGE_VERSION = "9.4"', bridge, count=1)
if n != 1:
    die("Bridge version marker 9.1 not found")

bridge = bridge.replace(
    "effective_hard = min(limits['hard_loss_usd'], 0.75 if group_size <= 1 else 1.50)",
    "effective_hard = min(limits['hard_loss_usd'], 1.25 if group_size <= 1 else 2.00)"
)

ledger = r'''
@app.get('/trade-ledger')
def trade_ledger_v94():
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
        wins = sum(1 for x in rows if x['net_pl'] > 0)
        losses = sum(1 for x in rows if x['net_pl'] < 0)
        return jsonify(
            ok=True, bridge_version=BRIDGE_VERSION, count=min(len(rows),limit), trades=rows[:limit],
            summary={
                'net_pl':sum(x['net_pl'] for x in rows),
                'gross_profit':sum(x['net_pl'] for x in rows if x['net_pl'] > 0),
                'gross_loss':sum(x['net_pl'] for x in rows if x['net_pl'] < 0),
                'wins':wins, 'losses':losses,
                'win_rate':(wins*100.0/(wins+losses)) if (wins+losses) else 0.0
            }
        )

'''
if "@app.get('/trade-ledger')" not in bridge:
    marker = "@app.post('/position-action')"
    if marker not in bridge:
        die("Bridge /position-action marker not found")
    bridge = bridge.replace(marker, ledger + marker, 1)
    print("OK: trade ledger")

old_exec = "private final ExecutorService executor = Executors.newSingleThreadExecutor();"
new_exec = old_exec + "\n    private final ExecutorService liveExecutor = Executors.newSingleThreadExecutor();"
try:
    monitor = replace_once(monitor, old_exec, new_exec, "LIVE executor")
except Exception as e:
    die(str(e))

watchdog_marker = "    // Keeps the foreground association and notification alive even on long H4/D1/W1/MN1 intervals."
live_loop = r'''    // V9.4: MT5/UI/position management independent from Twelve Data cadence.
    private final Runnable liveMt5Runnable = new Runnable() {
        @Override
        public void run() {
            if (!running) return;
            liveExecutor.execute(() -> {
                try {
                    refreshMt5Snapshot();
                    manageOpenPositions();
                } catch (Exception ignored) { }
            });
            handler.postDelayed(this, 1000L);
        }
    };

'''
if "private final Runnable liveMt5Runnable" not in monitor:
    if watchdog_marker not in monitor:
        die("MonitoringService watchdog marker not found")
    monitor = monitor.replace(watchdog_marker, live_loop + watchdog_marker, 1)
    print("OK: LIVE MT5 loop")

start_old = '''        handler.removeCallbacks(notificationWatchdog);
        handler.postDelayed(notificationWatchdog, 15000L);
'''
start_new = '''        handler.removeCallbacks(notificationWatchdog);
        handler.postDelayed(notificationWatchdog, 15000L);
        handler.removeCallbacks(liveMt5Runnable);
        handler.post(liveMt5Runnable);
'''
try:
    monitor = replace_once(monitor, start_old, start_new, "start LIVE loop")
except Exception as e:
    die(str(e))

stop_old = '''        handler.removeCallbacks(tick);
        handler.removeCallbacks(notificationWatchdog);
'''
stop_new = '''        handler.removeCallbacks(tick);
        handler.removeCallbacks(notificationWatchdog);
        handler.removeCallbacks(liveMt5Runnable);
'''
nstop = monitor.count(stop_old)
if nstop < 1:
    die("MonitoringService stop blocks not found")
monitor = monitor.replace(stop_old, stop_new)
print("OK: stop LIVE loop", nstop, "places")

slow_block = '''                refreshMt5Snapshot();
                manageOpenPositions();
                updateWatchlistRadar(key, tf);
'''
if slow_block in monitor:
    monitor = monitor.replace(slow_block, '''                updateWatchlistRadar(key, tf);
''', 1)
    print("OK: MT5 decoupled from API cycle")

monitor = monitor.replace('if ("SCALP".equals(mode) && maxPos <= 3) maxPos = 8;',
                          'if ("SCALP".equals(mode) && maxPos <= 3) maxPos = 10;')
monitor = monitor.replace('payload.put("campaign_spacing_atr", 0.12);',
                          'payload.put("campaign_spacing_atr", 0.07);')
monitor = monitor.replace('payload.put("scalp_campaign_single_arm_usd", 0.05);',
                          'payload.put("scalp_campaign_single_arm_usd", 0.90);')
monitor = monitor.replace('payload.put("scalp_basket_peak_giveback_pct", 15.0);',
                          'payload.put("scalp_basket_peak_giveback_pct", 28.0);')
monitor = monitor.replace('payload.put("scalp_basket_peak_min_giveback_usd", 0.02);',
                          'payload.put("scalp_basket_peak_min_giveback_usd", 0.25);')

if "liveExecutor.shutdownNow();" not in monitor:
    monitor = monitor.replace(
        "executor.shutdownNow();\n        super.onDestroy();",
        "executor.shutdownNow();\n        liveExecutor.shutdownNow();\n        super.onDestroy();",
        1
    )

trade_fmt = r'''    public static String formatTradeLog(JSONObject root) {
        JSONArray arr = root == null ? null : root.optJSONArray("trades");
        if (arr == null || arr.length() == 0) return "ТОРГОВЫЙ ЖУРНАЛ: пока пусто";
        StringBuilder sb = new StringBuilder("ТОРГОВЫЙ ЖУРНАЛ · ДЕНЬГИ");
        JSONObject sum = root.optJSONObject("summary");
        if (sum != null) {
            sb.append("\nNET ").append(String.format(Locale.US,"%+.2f USD",sum.optDouble("net_pl",0)))
              .append(" · PROFIT ").append(String.format(Locale.US,"%+.2f",sum.optDouble("gross_profit",0)))
              .append(" · LOSS ").append(String.format(Locale.US,"%+.2f",sum.optDouble("gross_loss",0)))
              .append(" · WIN ").append(String.format(Locale.US,"%.1f%%",sum.optDouble("win_rate",0)));
        }
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
              .append("\nNET ").append(String.format(Locale.US,"%+.2f USD",e.optDouble("net_pl",0)));
            String reason=e.optString("close_comment","");
            if(!reason.isEmpty()) sb.append(" · ").append(reason);
        }
        return sb.toString();
    }

'''
feature, n = re.subn(
    r'    public static String formatTradeLog\(JSONObject root\) \{.*?(?=    public static String formatPositions\()',
    trade_fmt, feature, count=1, flags=re.S
)
if n != 1:
    die("FeatureEngine formatTradeLog block not found")
print("OK: detailed money journal")

feature = feature.replace('o.put("scalp_campaign_single_arm_usd", 0.20);',
                          'o.put("scalp_campaign_single_arm_usd", 0.90);')
feature = feature.replace('o.put("scalp_basket_peak_giveback_pct", 25.0);',
                          'o.put("scalp_basket_peak_giveback_pct", 28.0);')
feature = feature.replace('o.put("scalp_basket_peak_min_giveback_usd", 0.03);',
                          'o.put("scalp_basket_peak_min_giveback_usd", 0.25);')

main = main.replace(
    'JSONObject log = FeatureEngine.httpJson("GET", base + "/trade-log?limit=200", null);',
    'JSONObject log = FeatureEngine.httpJson("GET", base + "/trade-ledger?days=30&limit=200", null);'
)
main = main.replace('СДЕЛКИ MT5 · ДО 200 СОБЫТИЙ',
                    'ТОРГОВЫЙ ЖУРНАЛ MT5 · ДО 200 ЗАКРЫТЫХ СДЕЛОК')
main = main.replace(
    'String[] scalpLots = {"AUTO","0.01","0.02","0.05","0.10","0.20","0.50","1.00","10.00"};',
    'String[] scalpLots = {"AUTO","0.01","0.02","0.05","0.10"};'
)

gradle, n = re.subn(r'versionName\s+["\'][^"\']+["\']', 'versionName "9.4"', gradle, count=1)
if n != 1:
    die("versionName not found")
gradle = re.sub(r'versionCode\s+(\d+)', lambda m: f"versionCode {int(m.group(1))+1}", gradle, count=1)

stage = ROOT / f"_V9_4_STAGE_{STAMP}"
write(stage / "bridge_v9_4.py", bridge)
try:
    py_compile.compile(str(stage / "bridge_v9_4.py"), doraise=True)
    print("OK: bridge_v9_4.py py_compile")
except Exception as e:
    die("Bridge compile failed: " + str(e))

write(ROOT / "mt5_bridge/bridge_v9_4.py", bridge)
write(ROOT / "app/src/main/java/com/openai/fxm1/MonitoringService.java", monitor)
write(ROOT / "app/src/main/java/com/openai/fxm1/FeatureEngine.java", feature)
write(ROOT / "app/src/main/java/com/openai/fxm1/MainActivity.java", main)
write(ROOT / "app/build.gradle", gradle)

write(ROOT / "mt5_bridge/START_BRIDGE_V9_4.bat", '''@echo off
cd /d "%~dp0"
echo Starting FX M1 MT5 Bridge V9.4 STABLE...
.venv\\Scripts\\python.exe bridge_v9_4.py
pause
''')

gradlew = ROOT / "gradlew.bat"
if gradlew.exists():
    print("Building APK...")
    rc = subprocess.call([str(gradlew), "--no-daemon", ":app:assembleDebug"], cwd=str(ROOT))
    if rc != 0:
        die("Android Gradle build failed; rollback completed")
    apk = ROOT / "app/build/outputs/apk/debug/app-debug.apk"
    if apk.exists():
        shutil.copy2(apk, ROOT / "FX-M1-Signal-V9.4-DEMO.apk")
        print("OK: APK created")
else:
    print("WARN: gradlew.bat not found; Android build not run")

print("DONE: V9.4 STABLE")
print("Bridge: mt5_bridge\\START_BRIDGE_V9_4.bat")
print("REAL remains DISABLED by safe default.")
