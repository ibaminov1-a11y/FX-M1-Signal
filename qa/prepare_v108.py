"""CI source transformation, never included in the user package. Idempotent after preparation."""
from pathlib import Path
import hashlib
root=Path('.')
S='app/src/main/java/com/openai/fxm1/MonitoringService.java'
M='app/src/main/java/com/openai/fxm1/MainActivity.java'
B='mt5_bridge/bridge_v10_0.py'
if 'V10Repair.qualityDetails' in Path(S).read_text():
    assert 'V10Repair.qualityDetails' in Path(M).read_text()
    assert 'def risk_ack():' in Path(B).read_text()
    raise SystemExit(0)
for path,sha in [(S,'3cde2bc70df41ea391b2757ff6aa465414f9bd46'),(M,'20f845ecab5d08dc84ae0f366f96455e43dbe842'),(B,'591a0479826af5299b17298e0940f4bb98c25da6')]:
    raw=Path(path).read_bytes()
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==sha,path

def replace(path,old,new,count=1):
    p=Path(path);text=p.read_text();assert text.count(old)==count,(path,old[:80],text.count(old));p.write_text(text.replace(old,new))

for path,structure in [(S,'effectiveStructureV10'),(M,'structure')]:
    p=Path(path);t=p.read_text();start=t.index('        int htfScore =',t.index('int quality = setupQualityAdaptive'));end=t.index('\n\n',t.index('String components =',start))
    t=t[:start]+f'        String components = V10Repair.qualityDetails(candidateSignalV10, sHigher2, sHigher1, sEntry, sFast, {structure}, breakout, patternV10);'+t[end:]
    old='why = signal + " открыт: направление ТФ согласовано; структура/фильтр разрешили вход; качество " + quality + "/100";'
    assert old in t
    t=t.replace(old,'why = signal + " — сценарий анализа подтверждён; исполнение проверяется отдельно. Оценка " + quality + "/100";');p.write_text(t)

replace(S,'        SharedPreferences p = prefs();\n        if (!isForexMarketOpen()) {','''        SharedPreferences p = prefs();
        V10Repair.record(p,"WAIT","Проверяются условия исполнения",a.symbol,tf);
        V10Repair.fetchRisk(p,normalizeUrl(p.getString("server_url","")));
        if (!isForexMarketOpen()) {''')
replace(S,'            p.edit().putString("bg_status", "MARKET CLOSED · торговля заблокирована").apply();','''            V10Repair.record(p,"BLOCKED","Рынок закрыт",a.symbol,tf);
            p.edit().putString("bg_status", "MARKET CLOSED · торговля заблокирована").apply();''')
replace(S,'        if (paused || p.getBoolean("trading_paused", false)) return;\n        if (!p.getBoolean("auto_trading", false)) return;','''        if (p.getBoolean("emergency_latched_v108",false)) { V10Repair.record(p,"BLOCKED","EMERGENCY: AUTO заблокирован",a.symbol,tf); return; }
        if (paused || p.getBoolean("trading_paused", false)) { V10Repair.record(p,"BLOCKED","PAUSE: новые входы запрещены",a.symbol,tf); return; }
        if (!p.getBoolean("auto_trading", false)) { V10Repair.record(p,"BLOCKED","AUTO выключен",a.symbol,tf); return; }''')
replace(S,'        if (!p.getBoolean("bridge_version_match_snapshot", false)) {','''        if (!p.getBoolean("bridge_version_match_snapshot", false)) {
            V10Repair.record(p,"BLOCKED","Версии APP/Bridge несовместимы",a.symbol,tf);''')
replace(S,'        } else if ("WAIT".equals(tradeSignal)) {','''        } else if ("WAIT".equals(tradeSignal)) {
            V10Repair.record(p,"WAIT","Нет подтверждения входа: "+a.why,a.symbol,tf);''')
replace(S,'            if (!sessionAllowed) {','''            if (!sessionAllowed) {
                V10Repair.record(p,"BLOCKED",V10Repair.sessionBlock(p),a.symbol,tf);''')
p=Path(S);t=p.read_text();a=t.index('            boolean sessionAllowed = false;');b=t.index('            if (!sessionAllowed)',a)
t=t[:a]+'            boolean sessionAllowed = V10Repair.sessionAllowed(allowed, session);\n'+t[b:];p.write_text(t)
replace(S,'        final String base = normalizeUrl(p.getString("server_url", ""));\n        if (base.isEmpty()) return;\n\n        try {\n            JSONObject health','''        final String base = normalizeUrl(p.getString("server_url", ""));
        if (base.isEmpty()) { V10Repair.record(p,"BLOCKED","Адрес Bridge не задан",a.symbol,tf); return; }
        try {
            JSONObject health''')
replace(S,'            if (!health.optBoolean("ok", false) || !health.optBoolean("mt5_connected", false)) return;','''            if (!health.optBoolean("ok", false) || !health.optBoolean("mt5_connected", false)) { V10Repair.record(p,"BLOCKED","MT5 не подключён",a.symbol,tf); return; }''')
replace(S,'            if (!accountAllowed) return;','''            if (!accountAllowed) { V10Repair.record(p,"BLOCKED","Счёт не разрешён для DEMO",a.symbol,tf); return; }''')
replace(S,'            maxPos = 10;','            maxPos = Math.max(1, Math.min(10, maxPos));')
replace(S,'payload.put("risk_pct", basketRiskPct / Math.max(1, maxPos));','payload.put("risk_pct", basketRiskPct / 10.0); // keep the existing V10 tranche risk when lowering max positions')
replace(S,'            JSONObject response = httpJson("POST", base + endpoint, payload);','''            if (!p.getBoolean("auto_trading",false) || p.getBoolean("trading_paused",false) || p.getBoolean("emergency_latched_v108",false)) {
                V10Repair.record(p,"BLOCKED","Команда отменена: AUTO/PAUSE/EMERGENCY изменились",a.symbol,tf); return;
            }
            V10Repair.record(p,"SENT","Ожидание подтверждения Bridge/MT5",a.symbol,tf);
            JSONObject response = httpJson("POST", base + endpoint, payload);
            V10Repair.response(p,response,a.symbol,tf);''')
replace(S,'            FeatureEngine.appendSignalHistory(p, a.symbol, tf, a.signal, a.quality, "ERROR: " + safeMessage(e));','''            V10Repair.failure(p,e,a.symbol,tf);
            FeatureEngine.appendSignalHistory(p, a.symbol, tf, a.signal, a.quality, "ERROR: " + safeMessage(e));''')
replace(S,'                p.edit().putString("risk_stats_snapshot", FeatureEngine.formatStats(st))','                V10Repair.saveRisk(p,rs);\n                p.edit().putString("risk_stats_snapshot", FeatureEngine.formatStats(st))')
replace(S,'rs.optBoolean("allowed", true)','rs.optBoolean("allowed", false)')
replace(S,'        if (ACTION_RESUME.equals(action)) {','''        if (ACTION_RESUME.equals(action)) {
            if (prefs().getBoolean("emergency_latched_v108",false)) {
                prefs().edit().putBoolean("auto_user_enabled",false).putBoolean("auto_trading",false).putString("bg_status","EMERGENCY: PLAY не снимает блокировку").apply();
                updateNotification(currentSymbol(),"EMERGENCY: блокировка сохранена",prefs().getString("state_signal","WAIT"),prefs().getInt("state_quality",-1));
                return START_STICKY;
            }''')
replace(S,'    private void emergencyStop() {\n        SharedPreferences p = prefs();\n        p.edit()','''    private void emergencyStop() {
        SharedPreferences p = prefs();
        p.edit().putBoolean("emergency_latched_v108",true).remove("pending_trade_json")''')
replace(S,'        if (raw == null || raw.trim().isEmpty() || base.isEmpty()) return;','''        if (raw == null || raw.trim().isEmpty() || base.isEmpty() || p.getBoolean("emergency_latched_v108",false)
                || !p.getBoolean("auto_trading",false) || p.getBoolean("trading_paused",false)) return;''')
replace(S,'import android.graphics.Color;','import android.graphics.Color;\nimport android.widget.RemoteViews;')
p=Path(S);t=p.read_text();a=t.index('    private Notification buildNotification(');b=t.index('    private void updateNotification(',a)
t=t[:a]+'''    private Notification buildNotification(String title, String text, String signal, int quality) {
        PendingIntent play=serviceActionIntent(ACTION_RESUME,101),pause=serviceActionIntent(ACTION_PAUSE,102),stop=serviceActionIntent(ACTION_EMERGENCY,103);
        String state=prefs().getBoolean("emergency_latched_v108",false)?"EMERGENCY":paused?"PAUSE":prefs().getBoolean("auto_trading",false)?"AUTO":"НАБЛЮДЕНИЕ";
        String line=currentSymbol()+" · "+currentTf()+" · "+signal+(quality>=0?" · "+quality+"/100":"");
        String detail=prefs().getLong("emergency_confirm_until_ms",0)>System.currentTimeMillis()?"EMERGENCY: нажмите ещё раз за 2,5 сек":line;
        Notification.Builder builder=new Notification.Builder(this,CHANNEL_MONITOR)
                .setSmallIcon(R.drawable.ic_stat_fx).setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false)
                .setColor(Color.rgb(145,77,255)).setVisibility(Notification.VISIBILITY_PUBLIC)
                .setCategory(Notification.CATEGORY_SERVICE).setContentTitle("FX M1 Bot · "+state).setContentText(detail)
                .setStyle(new Notification.DecoratedCustomViewStyle())
                .setCustomContentView(notificationView(R.layout.notification_v108_compact,detail,play,pause,stop))
                .setCustomBigContentView(notificationView(R.layout.notification_v108_expanded,detail,play,pause,stop))
                .setContentIntent(openAppIntent());
        if(Build.VERSION.SDK_INT>=31)builder.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        return builder.build();
    }
    private RemoteViews notificationView(int layout,String detail,PendingIntent play,PendingIntent pause,PendingIntent stop) {
        RemoteViews view=new RemoteViews(getPackageName(),layout);
        view.setTextViewText(R.id.v108_notification_text,detail);
        view.setOnClickPendingIntent(R.id.v108_play,play);
        view.setOnClickPendingIntent(R.id.v108_pause,pause);
        view.setOnClickPendingIntent(R.id.v108_stop,stop);
        return view;
    }

'''+t[b:];p.write_text(t)

replace(M,'("WAIT".equals(signal) ? "ПОЧЕМУ WAIT: " : "ПОЧЕМУ ВХОД: ") + (why == null || why.isEmpty() ? "—" : why)','V10Repair.display(p,symbol,tf,why)')
p=Path(M);t=p.read_text().replace('"КОМПОНЕНТЫ КАЧЕСТВА: "','"РАСЧЁТ ОЦЕНКИ: "').replace('"APP V" + appVersionName() + "   •   BRIDGE V"','"APP V" + appVersionName() + " · исправление 10.8   •   BRIDGE V"');p.write_text(t)
replace(M,'boolean autoSaved = p.getBoolean("auto_user_enabled", p.getBoolean("auto_trading", false)) && mt5 && targetAllowed;','boolean autoSaved = p.getBoolean("auto_user_enabled", p.getBoolean("auto_trading", false)) && mt5 && targetAllowed && !p.getBoolean("emergency_latched_v108",false);')
replace(M,'            if (isChecked) {\n                if (!serverConnected','''            if (isChecked) {
                if (prefs.getBoolean("emergency_latched_v108",false)) {
                    forceAutoOff("EMERGENCY: требуется явное разрешение");
                    new AlertDialog.Builder(this).setTitle("Снять аварийную блокировку?")
                        .setMessage("Это не включает AUTO и не сбрасывает лимиты риска. После проверки MT5 включение AUTO выполняется отдельно.")
                        .setNegativeButton("Отмена",null).setPositiveButton("Разрешить проверку",(d,w)->prefs.edit().putBoolean("emergency_latched_v108",false).apply()).show();
                    return;
                }
                if (!serverConnected''')
replace(M,'    private void maybeSendSignalToServer(Analysis a) {','''    private void maybeSendSignalToServer(Analysis a) {
        SharedPreferences guard=getSharedPreferences("fxm1",MODE_PRIVATE);
        if (guard.getBoolean("bg_running",false) || guard.getBoolean("emergency_latched_v108",false) || guard.getBoolean("trading_paused",false)) return;''')
replace(M,'        forceAutoOff("EMERGENCY STOP: AUTO выключен, запрошено закрытие всех позиций.");','''        getSharedPreferences("fxm1",MODE_PRIVATE).edit().putBoolean("emergency_latched_v108",true).remove("pending_trade_json").apply();
        forceAutoOff("EMERGENCY STOP: AUTO выключен, запрошено закрытие всех позиций.");''')
replace(M,'        Switch session = smartSwitch("Фильтр торговых сессий", p.getBoolean("session_filter_enabled", false)); box.addView(session);','''        Switch session = smartSwitch("Фильтр торговых сессий", p.getBoolean("session_filter_enabled", false)); box.addView(session);
        box.addView(smartLabel("Разрешённые сессии — изменения только по кнопке СОХРАНИТЬ"));
        String sessions=p.getString("allowed_sessions","LONDON,NEW_YORK");
        Switch asia=smartSwitch("ASIA",V10Repair.sessionAllowed(sessions,"ASIA"));box.addView(asia);
        Switch london=smartSwitch("LONDON",V10Repair.sessionAllowed(sessions,"LONDON"));box.addView(london);
        Switch newYork=smartSwitch("NEW_YORK",V10Repair.sessionAllowed(sessions,"NEW_YORK"));box.addView(newYork);
        V10Repair.addRecoveryButton(this,box,p,()->forceAutoOff("Проверка серии: AUTO остаётся выключенным"));''')
replace(M,'                            .putBoolean("session_filter_enabled", session.isChecked())','''                            .putBoolean("session_filter_enabled", session.isChecked())
                            .putString("allowed_sessions",(asia.isChecked()?"ASIA,":"")+(london.isChecked()?"LONDON,":"")+(newYork.isChecked()?"NEW_YORK":""))''')
# Maintain versionName 10.0 because this generation compares it with Bridge protocol 10.0.
replace('app/build.gradle','versionCode 914','versionCode 915')
replace('app/build.gradle','        versionName "10.0"','        versionName "10.0"\n        testInstrumentationRunner "androidx.test.runner.AndroidJUnitRunner"')
replace('app/build.gradle','dependencies {','''dependencies {
    androidTestImplementation "androidx.test:runner:1.6.2"
    androidTestImplementation "androidx.test:rules:1.6.1"
    androidTestImplementation "androidx.test.ext:junit:1.2.1"
    androidTestImplementation "androidx.test.uiautomator:uiautomator:2.3.0"''')
Path('gradle.properties').write_text('android.useAndroidX=true\n')
for typ,total,info,buttons,font in [('compact',48,16,32,11),('expanded',106,42,48,13)]:
    text=f'<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android" android:layout_width="match_parent" android:layout_height="{total}dp" android:orientation="vertical" android:background="#111227">\n'
    text+=f'<TextView android:id="@+id/v108_notification_text" android:layout_width="match_parent" android:layout_height="{info}dp" android:textColor="#F4F1FF" android:textSize="11sp" android:maxLines="{1 if typ=="compact" else 2}" android:ellipsize="end" android:gravity="center_vertical" />\n'
    text+=f'<LinearLayout android:layout_width="match_parent" android:layout_height="{buttons}dp" android:orientation="horizontal">\n'
    for ident,label,weight,color,bg in [('play','PLAY',1,'#F4F1FF','#4E2599'),('pause','PAUSE',1,'#F4F1FF','#4E2599'),('stop','EMERGENCY STOP',1.6,'#FF4857','#181430')]:
        text+=f'<TextView android:id="@+id/v108_{ident}" android:layout_width="0dp" android:layout_weight="{weight}" android:layout_height="match_parent" android:layout_marginStart="3dp" android:text="{label}" android:contentDescription="{label}" android:gravity="center" android:textColor="{color}" android:textSize="{font}sp" android:background="{bg}" android:maxLines="2" />\n'
    Path(f'app/src/main/res/layout/notification_v108_{typ}.xml').write_text(text+'</LinearLayout></LinearLayout>\n')
p=Path(B);t=p.read_text();a=t.index('def compute_risk_state(');b=t.index('\ndef ',a+5);t=t[:a]+Path('qa/v108_risk_section.txt').read_text()+'\n'+t[b:]
t=t.replace('BRIDGE_VERSION = "10.0"','BRIDGE_VERSION = "10.0"\nBRIDGE_PATCH = "10.8"')
t=t.replace('ALLOW_REAL = os.environ.get("FXM1_ALLOW_REAL", "0").strip().lower() in ("1", "true", "yes", "on")','ALLOW_REAL = False  # This repair distribution remains DEMO only.')
t=t.replace('Set FXM1_ALLOW_REAL=1 only after DEMO validation.','This repair does not permit REAL execution.');p.write_text(t)
print('Prepared V10 source. Must commit this state before building.')
