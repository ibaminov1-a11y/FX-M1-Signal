from pathlib import Path
import re, sys, shutil, datetime

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / f"_V9_2_BACKUP_{STAMP}"

def fail(msg):
    print("ERROR:", msg)
    sys.exit(1)

def read(p):
    if not p.exists():
        fail(f"Не найден файл: {p}")
    return p.read_text(encoding="utf-8")

def write(p, s):
    p.write_text(s, encoding="utf-8", newline="\n")

def backup(p):
    dst = BACKUP / p.relative_to(ROOT)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)

def need_replace(text, old, new, label):
    n = text.count(old)
    if n != 1:
        fail(f"{label}: ожидалось 1 совпадение, найдено {n}")
    print("OK:", label)
    return text.replace(old, new, 1)

bridge = ROOT / "mt5_bridge" / "bridge_v9_2.py"
monitor = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "MonitoringService.java"
feature = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "FeatureEngine.java"
main = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "MainActivity.java"
gradle = ROOT / "app" / "build.gradle"

for p in (bridge, monitor, feature, main, gradle):
    backup(p)

s = read(bridge)
if 'BRIDGE_VERSION = "9.2"' not in s:
    fail("bridge_v9_2.py не выглядит как V9.2")
s = s.replace('BRIDGE_VERSION = "9.2"', 'BRIDGE_VERSION = "9.3"', 1)

old = '''        early_probe = quality >= 45 and m1_bias and favourable and not chase
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
'''
new = '''        confirmed = favourable and (
            micro_break or
            (cm.get('stage') == 'RESUME' and rejection)
        )
        if not confirmed:
            return False, 'WAIT_MT5_ENTRY', {
                'stage': cm.get('stage','BIAS'),'quality':quality,'m1_bias':bool(m1_bias),
                'favourable':bool(favourable),'micro_break':bool(micro_break),'chase':bool(chase)
            }

        cm.update(stage='ENTRY', entry_trigger_at=now, trigger_price=cur)
        return True, ('MICRO_BREAK' if micro_break else 'PULLBACK_RESUME'), {
            'stage':'ENTRY','side':side,'quality':quality,'micro_break':bool(micro_break)
        }
'''
s = need_replace(s, old, new, "SCALP first-entry trigger")

old = '''    spacing = max(atr * max(0.10, safe_float(data.get('campaign_spacing_atr'), 0.14)),
                  spread * 1.8, point * 6)

    if progress < spacing:
        return False, 'WAIT_PROGRESS', {'stage':'CONFIRM','basket_pnl':basket_pnl,'progress':progress,'spacing':spacing}
'''
new = '''    spacing = max(atr * max(0.05, safe_float(data.get('campaign_spacing_atr'), 0.07)),
                  spread * 1.20, point * 4)

    if progress < spacing:
        return False, 'WAIT_PROGRESS', {'stage':'CONFIRM','basket_pnl':basket_pnl,'progress':progress,'spacing':spacing}
'''
s = need_replace(s, old, new, "SCALP campaign spacing")

old = '''    if not (favourable and micro_break):
        return False, 'ADD_WAIT_MICRO_BREAK', {'stage':'ADD_CONFIRM','micro_break':bool(micro_break)}
    if now - float(cm.get('last_add_at', 0.0)) < 1.5:
        return False, 'DEBOUNCE', {'stage':'ADD_CONFIRM'}
'''
new = '''    continuation = favourable and (micro_break or cm.get('stage') == 'ADD_REJECTION')
    if not continuation:
        return False, 'ADD_WAIT_CONTINUATION', {
            'stage':'ADD_CONFIRM','micro_break':bool(micro_break),'rejection':bool(rejection)
        }
    if now - float(cm.get('last_add_at', 0.0)) < 0.75:
        return False, 'DEBOUNCE', {'stage':'ADD_CONFIRM'}
'''
s = need_replace(s, old, new, "SCALP structural scale-in")

marker = "@app.post('/position-action')"
if marker not in s:
    fail("Не найден /position-action")
live_endpoint = r'''
@app.get('/live-state')
def live_state_v93():
    raw = request.args.get('symbol','')
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        symbol = resolve_symbol(raw) if raw else None
        tick = mt5.symbol_info_tick(symbol) if symbol else None
        positions = mt5.positions_get() or []
        pp = [position_payload(p) for p in positions]
        intent = None
        st = _SCALP_INTENTS.get(symbol) if symbol else None
        if st:
            side = st.get('side')
            basket = _scalp_positions(symbol, side)
            cm = _SCALP_CAMPAIGN_META.get((symbol,side),{})
            stage = cm.get('stage','BIAS')
            stage_score = {
                'BIAS':30,'WAIT_PULLBACK':38,'PULLBACK':52,'REJECTION':68,'RESUME':80,
                'ENTRY':95,'CONFIRM':72,'ADD_WAIT_PULLBACK':55,'ADD_PULLBACK':66,
                'ADD_REJECTION':80,'ADD_CONFIRM':88,'SCALE_IN':94,'PROTECT':45
            }
            api_q = int(st.get('quality') or 0)
            live_q = max(0,min(100,int(round(stage_score.get(stage,45)*0.70 + api_q*0.30))))
            bp = sum(float(p.profit)+float(getattr(p,'swap',0.0) or 0.0) for p in basket)
            intent = {
                'side':side,'api_quality':api_q,'live_entry_quality':live_q,
                'stage':stage,'positions':len(basket),'basket_pnl':bp,
                'basket_peak':float(_SCALP_BASKET_PEAK.get((symbol,side),bp)),
                'max_positions':max(1,min(int((st.get('data') or {}).get('max_positions') or 10),10))
            }

        latest = None
        deals = history_deals(2)
        outs = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)]
        if outs:
            d = outs[-1]
            net = float(d.profit)+float(d.commission)+float(d.swap)+float(getattr(d,'fee',0.0) or 0.0)
            latest = {
                'deal_id':int(d.ticket),'position_id':int(d.position_id),'time':int(d.time),
                'symbol':d.symbol,'volume':float(d.volume),'price':float(d.price),
                'net_pl':net,'profit':float(d.profit),'commission':float(d.commission),
                'swap':float(d.swap),'comment':str(getattr(d,'comment','') or '')
            }

        return jsonify(
            ok=True, bridge_version=BRIDGE_VERSION, server_time_ms=int(time.time()*1000),
            account_type=account_type_name(account), balance=float(account.balance),
            equity=float(account.equity), currency=account.currency,
            positions=len(pp), floating_pl=sum(x['profit']+x.get('swap',0.0) for x in pp),
            bid=float(tick.bid) if tick else None, ask=float(tick.ask) if tick else None,
            symbol=symbol, scalp=intent, last_closed=latest
        )


'''
s = s.replace(marker, live_endpoint + marker, 1)
write(bridge, s)

m = read(monitor)
old = "private final ExecutorService executor = Executors.newSingleThreadExecutor();"
new = old + "\n    private final ExecutorService liveExecutor = Executors.newSingleThreadExecutor();"
m = need_replace(m, old, new, "separate LIVE executor")

watchdog = "    // Keeps the foreground association and notification alive even on long H4/D1/W1/MN1 intervals."
if watchdog not in m:
    fail("Не найден notificationWatchdog")
live_loop = r'''    // V9.3 LIVE MT5 LOOP: independent from Twelve Data/API cadence.
    private final Runnable liveMt5Runnable = new Runnable() {
        @Override
        public void run() {
            if (!running) return;
            liveExecutor.execute(() -> {
                try {
                    refreshMt5Snapshot();
                    manageOpenPositions();
                    refreshLiveScalpState();
                } catch (Exception ignored) { }
            });
            handler.postDelayed(this, 1000L);
        }
    };

'''
m = m.replace(watchdog, live_loop + watchdog, 1)

old = '''        handler.removeCallbacks(notificationWatchdog);
        handler.postDelayed(notificationWatchdog, 15000L);
'''
new = '''        handler.removeCallbacks(notificationWatchdog);
        handler.postDelayed(notificationWatchdog, 15000L);
        handler.removeCallbacks(liveMt5Runnable);
        handler.post(liveMt5Runnable);
'''
m = need_replace(m, old, new, "start LIVE MT5 loop")

old = '''        handler.removeCallbacks(tick);
        handler.removeCallbacks(notificationWatchdog);
'''
new = '''        handler.removeCallbacks(tick);
        handler.removeCallbacks(notificationWatchdog);
        handler.removeCallbacks(liveMt5Runnable);
'''
m = need_replace(m, old, new, "stop LIVE MT5 loop")

old = '''                refreshMt5Snapshot();
                manageOpenPositions();
                updateWatchlistRadar(key, tf);
'''
new = '''                updateWatchlistRadar(key, tf);
'''
m = need_replace(m, old, new, "decouple MT5 from API cycle")

m = m.replace('if ("SCALP".equals(mode) && maxPos <= 3) maxPos = 8;',
              'if ("SCALP".equals(mode) && maxPos <= 3) maxPos = 10;', 1)
m = m.replace('payload.put("campaign_spacing_atr", 0.12);',
              'payload.put("campaign_spacing_atr", 0.07);', 1)

refresh_marker = "    private void refreshMt5Snapshot() {"
if refresh_marker not in m:
    fail("Не найден refreshMt5Snapshot")
live_reader = r'''    private void refreshLiveScalpState() {
        SharedPreferences p = prefs();
        String base = normalizeUrl(p.getString("server_url", ""));
        if (base.isEmpty()) return;
        try {
            String sym = URLEncoder.encode(currentSymbol(), "UTF-8");
            JSONObject root = httpJson("GET", base + "/live-state?symbol=" + sym, null);
            JSONObject scalp = root.optJSONObject("scalp");
            JSONObject last = root.optJSONObject("last_closed");
            SharedPreferences.Editor e = p.edit()
                    .putLong("live_mt5_update_ms", System.currentTimeMillis())
                    .putLong("mt5_balance_bits", Double.doubleToLongBits(root.optDouble("balance", Double.NaN)))
                    .putLong("mt5_equity_bits", Double.doubleToLongBits(root.optDouble("equity", Double.NaN)))
                    .putInt("mt5_positions_snapshot", root.optInt("positions", 0))
                    .putLong("mt5_floating_bits", Double.doubleToLongBits(root.optDouble("floating_pl", 0.0)));
            if (scalp != null) {
                e.putString("live_scalp_side", scalp.optString("side","WAIT"))
                 .putInt("live_scalp_entry_quality", scalp.optInt("live_entry_quality",0))
                 .putString("live_scalp_stage", scalp.optString("stage","BIAS"))
                 .putInt("live_scalp_positions", scalp.optInt("positions",0))
                 .putInt("live_scalp_max_positions", scalp.optInt("max_positions",10))
                 .putLong("live_scalp_pnl_bits", Double.doubleToLongBits(scalp.optDouble("basket_pnl",0.0)))
                 .putLong("live_scalp_peak_bits", Double.doubleToLongBits(scalp.optDouble("basket_peak",0.0)));
            }
            if (last != null) {
                long deal = last.optLong("deal_id",0);
                long previous = p.getLong("last_money_deal_id",0);
                double net = last.optDouble("net_pl",0.0);
                e.putLong("last_closed_net_bits", Double.doubleToLongBits(net))
                 .putLong("last_closed_time", last.optLong("time",0))
                 .putString("last_closed_symbol", last.optString("symbol",""))
                 .putLong("last_money_deal_id", deal);
                if (deal > 0 && deal != previous) {
                    FeatureEngine.appendSignalHistory(
                            p, last.optString("symbol", currentSymbol()), currentTf(),
                            p.getString("live_scalp_side","SCALP"),
                            p.getInt("state_quality",-1),
                            String.format(Locale.US, "СДЕЛКА ЗАКРЫТА · NET %+.2f USD", net)
                    );
                }
            }
            e.apply();
        } catch (Exception ignored) { }
    }

'''
m = m.replace(refresh_marker, live_reader + refresh_marker, 1)
m = m.replace("executor.shutdownNow();\n        super.onDestroy();",
              "executor.shutdownNow();\n        liveExecutor.shutdownNow();\n        super.onDestroy();", 1)
write(monitor, m)

f = read(feature)
f = f.replace('o.put("scalp_campaign_single_arm_usd", 0.20);',
              'o.put("scalp_campaign_single_arm_usd", 0.90);', 1)
f = f.replace('o.put("scalp_basket_peak_giveback_pct", 25.0);',
              'o.put("scalp_basket_peak_giveback_pct", 28.0);', 1)
f = f.replace('o.put("scalp_basket_peak_min_giveback_usd", 0.03);',
              'o.put("scalp_basket_peak_min_giveback_usd", 0.25);', 1)
write(feature, f)

a = read(main)
a = a.replace(
    'String[] scalpLots = {"AUTO","0.01","0.02","0.05","0.10","0.20","0.50","1.00","10.00"};',
    'String[] scalpLots = {"AUTO","0.01","0.02","0.05","0.10"};', 1)

old = '''                int basketMaxPositions = Integer.parseInt(maxPositions);
                payload.put("risk_pct", basketRiskPct);
                payload.put("max_positions", basketMaxPositions);
                if ("SCALP".equals(selectedSignalMode())) {
'''
new = '''                int basketMaxPositions = Integer.parseInt(maxPositions);
                if ("SCALP".equals(selectedSignalMode()) && basketMaxPositions <= 3) basketMaxPositions = 10;
                payload.put("risk_pct", basketRiskPct);
                payload.put("max_positions", basketMaxPositions);
                if ("SCALP".equals(selectedSignalMode())) {
'''
a = need_replace(a, old, new, "MainActivity SCALP max positions 10")
write(main, a)

g = read(gradle)
g, n = re.subn(r'versionName\s+["\'][^"\']+["\']', 'versionName "9.3"', g, count=1)
if n != 1:
    fail("Не удалось обновить versionName")
g = re.sub(r'versionCode\s+(\d+)', lambda x: f"versionCode {int(x.group(1))+1}", g, count=1)
write(gradle, g)

bridge93 = ROOT / "mt5_bridge" / "bridge_v9_3.py"
write(bridge93, read(bridge))
(ROOT / "mt5_bridge" / "START_BRIDGE_V9_3.bat").write_text(
    '@echo off\ncd /d "%~dp0"\necho Starting FX M1 MT5 Bridge V9.3 LIVE...\n.venv\\Scripts\\python.exe bridge_v9_3.py\npause\n',
    encoding="utf-8"
)

print()
print("FX M1 BOT V9.3 LIVE применена.")
print("Backup:", BACKUP)
print("Bridge:", bridge93)
print("REAL remains blocked unless explicitly enabled on Bridge.")
