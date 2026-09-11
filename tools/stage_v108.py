"""CI-only source staging. Never distributed or run on the user's PC."""
from pathlib import Path
import hashlib, subprocess
r=Path.cwd();j=r/'app/src/main/java/com/openai/fxm1'
def replace(path,old,new,count=1):
    text=path.read_text(encoding='utf-8')
    if text.count(old)!=count:raise RuntimeError(f'{path}: source anchor mismatch: {old[:80]}')
    path.write_text(text.replace(old,new),encoding='utf-8')
main=j/'MainActivity.java';svc=j/'MonitoringService.java'
for path,sha in [(main,'20f845ecab5d08dc84ae0f366f96455e43dbe842'),(svc,'3cde2bc70df41ea391b2757ff6aa465414f9bd46')]:
    data=path.read_bytes();assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==sha
for path,structure in [(main,'structure'),(svc,'effectiveStructureV10')]:
    s=path.read_text();a=s.index('        int htfScore =');b=s.index('\n\n        ArrayList<String> whyParts',a)
    s=s[:a]+f'        String components = SignalScore.describe(candidateSignalV10, sHigher2, sHigher1, sEntry, sFast, {structure}, breakout, patternV10);'+s[b:]
    s=s.replace('why = signal + " открыт: направление ТФ согласовано; структура/фильтр разрешили вход; качество " + quality + "/100";', 'why = "Сигнал анализа " + signal + ": условия анализа выполнены; качество " + quality + "/100. Это не подтверждение открытия позиции.";')
    path.write_text(s)
replace(main,'boolean versionMatch = appVersionName().equals(bridgeVersion);','boolean versionMatch = ExecutionFeedback.bridgeCompatible(bridgeVersion);')
replace(svc,'FeatureEngine.appVersionName(this).equals(h.optString("bridge_version", "—"))','ExecutionFeedback.bridgeCompatible(h.optString("bridge_version", "—"))')
replace(main,'("WAIT".equals(signal) ? "ПОЧЕМУ WAIT: " : "ПОЧЕМУ ВХОД: ") + (why == null || why.isEmpty() ? "—" : why)','("WAIT".equals(signal) ? "ПОЧЕМУ WAIT: " : "СИГНАЛ АНАЛИЗА: ") + (why == null || why.isEmpty() ? "—" : why) + ExecutionFeedback.render(p, symbol, tf)')
replace(main,'("WAIT".equals(a.signal) ? "ПОЧЕМУ WAIT: " : "ПОЧЕМУ ВХОД: ") + a.why','("WAIT".equals(a.signal) ? "ПОЧЕМУ WAIT: " : "СИГНАЛ АНАЛИЗА: ") + a.why + ExecutionFeedback.render(localPrefs, a.symbol, selectedEntryTimeframe())')
replace(main,'boolean autoSaved = p.getBoolean("auto_user_enabled", p.getBoolean("auto_trading", false)) && mt5 && targetAllowed;','boolean autoSaved = !p.getBoolean("v108_emergency_latched", false) && p.getBoolean("auto_user_enabled", p.getBoolean("auto_trading", false)) && mt5 && targetAllowed;')
replace(main,'            if (isChecked) {\n                if (!serverConnected','''            if (isChecked) {
                if (prefs.getBoolean("v108_emergency_latched", false)) {
                    forceAutoOff(null);
                    new AlertDialog.Builder(this).setTitle("Аварийная блокировка")
                        .setMessage("Сначала проверьте позиции в MT5. Снять блокировку? AUTO останется выключенным; для торговли потребуется отдельное включение.")
                        .setNegativeButton("Оставить блокировку", null)
                        .setPositiveButton("Снять блокировку", (d,w)->prefs.edit().putBoolean("v108_emergency_latched",false).apply()).show();
                    return;
                }
                if (!serverConnected''')
replace(main,'        FeatureEngine.ensureDefaults(prefs);','''        FeatureEngine.ensureDefaults(prefs);
        if (!prefs.getBoolean("v108_initial_review",false)) prefs.edit().putBoolean("v108_initial_review",true)
            .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).apply();''')
replace(svc,'        if (ACTION_RESUME.equals(action)) {\n            paused = false;','''        if (ACTION_RESUME.equals(action)) {
            if (prefs().getBoolean("v108_emergency_latched",false)) {
                prefs().edit().putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false)
                    .putString("bg_status","EMERGENCY · PLAY не снимает блокировку").apply();
                return START_NOT_STICKY;
            }
            paused = false;''')
replace(svc,'        p.edit()\n                .putBoolean("auto_user_enabled", false)','        p.edit()\n                .putBoolean("v108_emergency_latched", true)\n                .putBoolean("auto_user_enabled", false)')
replace(main,'    private void executeEmergencyStop() {\n        forceAutoOff(','    private void executeEmergencyStop() {\n        getSharedPreferences("fxm1",MODE_PRIVATE).edit().putBoolean("v108_emergency_latched",true).commit();\n        forceAutoOff(')
replace(svc,'        if (!isForexMarketOpen()) {\n            p.edit().putString("bg_status",','''        ExecutionFeedback.record(p,a.symbol,tf,"CHECKING","Проверка допуска; ордер не отправлен");
        if (!isForexMarketOpen()) {
            ExecutionFeedback.record(p,a.symbol,tf,"BLOCKED","Рынок закрыт; ордер не отправлен");
            p.edit().putString("bg_status",''')
replace(svc,'        if (paused || p.getBoolean("trading_paused", false)) return;\n        if (!p.getBoolean("auto_trading", false)) return;','''        if (p.getBoolean("v108_emergency_latched",false)) { ExecutionFeedback.record(p,a.symbol,tf,"BLOCKED","EMERGENCY; ордер не отправлен"); return; }
        if (paused || p.getBoolean("trading_paused", false)) { ExecutionFeedback.record(p,a.symbol,tf,"PAUSED","PAUSE; ордер не отправлен"); return; }
        if (!p.getBoolean("auto_trading", false)) { ExecutionFeedback.record(p,a.symbol,tf,"OFF","AUTO выключен; ордер не отправлен"); return; }''')
replace(svc,'        if (!p.getBoolean("bridge_version_match_snapshot", false)) {','''        if (!p.getBoolean("bridge_version_match_snapshot", false)) {
            ExecutionFeedback.record(p,a.symbol,tf,"BLOCKED","Требуется совместимый Bridge V10.0; ордер не отправлен");''')
replace(svc,'        } else if ("WAIT".equals(tradeSignal)) {','''        } else if ("WAIT".equals(tradeSignal)) {
            ExecutionFeedback.record(p,a.symbol,tf,"WAIT","Нет подтверждённого входа; ордер не отправлен");''')
replace(svc,'            if (!sessionAllowed) {','''            if (!sessionAllowed) {
                ExecutionFeedback.record(p,a.symbol,tf,"BLOCKED","Сессия "+session+" запрещена фильтром (разрешены: "+allowed+"); ордер не отправлен");''')
replace(svc,'        if (base.isEmpty()) return;\n\n        try {\n            JSONObject health','''        if (base.isEmpty()) { ExecutionFeedback.record(p,a.symbol,tf,"BLOCKED","Не задан сервер; ордер не отправлен"); return; }

        try {
            JSONObject health''')
replace(svc,'            if (!health.optBoolean("ok", false) || !health.optBoolean("mt5_connected", false)) return;','''            if (!health.optBoolean("ok", false) || !health.optBoolean("mt5_connected", false)) {
                ExecutionFeedback.record(p,a.symbol,tf,"BLOCKED","MT5 не подключён; ордер не отправлен"); return;
            }''')
replace(svc,'            if (!accountAllowed) return;','            if (!accountAllowed) { ExecutionFeedback.record(p,a.symbol,tf,"BLOCKED","Режим счёта не разрешён; ордер не отправлен"); return; }')
replace(svc,'            maxPos = 10;','            maxPos = Math.max(1, Math.min(10, maxPos));')
replace(svc,'            JSONObject response = httpJson("POST", base + endpoint, payload);','''            if (p.getBoolean("v108_emergency_latched",false) || !p.getBoolean("auto_trading",false)
                    || p.getBoolean("trading_paused",false)) {
                ExecutionFeedback.record(p,a.symbol,tf,"BLOCKED","Команда отменена перед отправкой: AUTO/PAUSE/EMERGENCY"); return;
            }
            ExecutionFeedback.record(p,a.symbol,tf,"SENDING","Запрос отправляется; исполнение ещё не подтверждено");
            JSONObject response = httpJson("POST", base + endpoint, payload);
            ExecutionFeedback.record(p,a.symbol,tf,ExecutionFeedback.responseStage(response),ExecutionFeedback.responseDetail(response));''')
replace(svc,'            FeatureEngine.appendSignalHistory(p, a.symbol, tf, a.signal, a.quality, "ERROR: " + safeMessage(e));','''            ExecutionFeedback.record(p,a.symbol,tf,"ERROR","Исполнение не подтверждено: "+safeMessage(e));
            FeatureEngine.appendSignalHistory(p, a.symbol, tf, a.signal, a.quality, "ERROR: " + safeMessage(e));''')
replace(svc,'.putString("risk_snapshot", rs.optBoolean("allowed", true) ? "RISK OK" : "RISK BLOCK: " + rs.optJSONArray("blocks"))','''.putString("risk_snapshot", rs.optBoolean("allowed", false) ? "RISK OK" : "RISK BLOCK: " + rs.optJSONArray("blocks"))
                        .putString("risk_detail_json", rs.toString())''')
replace(svc,'                maybeSendToTradingServer(a, tf, mode);','''                maybeSendToTradingServer(a, tf, mode);
                updateNotification(a.symbol+" · "+tf, prefs().getString("execution_detail",""), a.signal, a.quality);''')
replace(main,'        Switch session = smartSwitch("Фильтр торговых сессий", p.getBoolean("session_filter_enabled", false)); box.addView(session);','''        Switch session = smartSwitch("Фильтр торговых сессий", p.getBoolean("session_filter_enabled", false)); box.addView(session);
        box.addView(smartLabel("Текущая сессия: "+FeatureEngine.currentSession()+". Разрешены: "+p.getString("allowed_sessions","LONDON,NEW_YORK")+". Открытый рынок не отменяет этот фильтр."));''')
replace(main,'        Switch be = smartSwitch("Break-even (перенос SL в цену входа)",','''        box.addView(smartLabel("LOSS_STREAK: серия последних закрытий за 30 дней, а не только за сегодня. Начало новой сессии её не сбрасывает."));
        Button riskReview=new Button(this);riskReview.setText("Проверить блокировку серии убытков");
        riskReview.setOnClickListener(v->reviewLossStreak());box.addView(riskReview);styleOutlineButton(riskReview,C_PURPLE);

        Switch be = smartSwitch("Break-even (перенос SL в цену входа)",''')
replace(main,'    private void refreshSmartUi() {',(r/'tools/v108_review_method.txt').read_text()+'\n    private void refreshSmartUi() {')
s=svc.read_text().replace('import android.graphics.Color;','import android.graphics.Color;\nimport android.widget.RemoteViews;')
a=s.index('    private Notification buildNotification(');b=s.index('    private void updateNotification(',a)
s=s[:a]+(r/'tools/v108_notification_method.txt').read_text()+'\n'+s[b:];svc.write_text(s)
p=r/'mt5_bridge/bridge_v10_0.py';s=p.read_text().replace('import math\n','import math\nimport json\nfrom pathlib import Path\nimport tempfile\n')
a=s.index('def compute_risk_state(');b=s.index('\ndef ',a+5)
s=s[:a]+(r/'tools/v108_risk_methods.txt').read_text()+'\n'+s[b:];p.write_text(s)
print('Staged V10.8 production source changes; CI will commit exact sources before build.')
