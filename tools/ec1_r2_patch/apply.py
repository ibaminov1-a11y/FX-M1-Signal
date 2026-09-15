from pathlib import Path

root = Path(__file__).resolve().parents[2]
main_path = root / 'app/src/main/java/com/openai/fxm1/MainActivity.java'
client_path = root / 'app/src/main/java/com/openai/fxm1/EventClient.java'


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one match, found {count}')
    return text.replace(old, new, 1)


main = main_path.read_text(encoding='utf-8')

main = replace_one(main,
'''        ArrayAdapter<String> maxPosAdapter = darkSpinnerAdapter(
                new String[]{"По риску", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}
        );
        maxPositionsSpinner.setAdapter(maxPosAdapter);
        maxPositionsSpinner.setSelection(prefs.getInt("ec_limit", 0));
''',
'''        // EventCore EC1 uses event-driven pyramiding with one shared campaign budget.
        // There is no strategy-level fixed position count such as 10.
        prefs.edit().putInt("ec_limit", 0).putString("maxpos_label", "По риску").apply();
        ArrayAdapter<String> maxPosAdapter = darkSpinnerAdapter(
                new String[]{"По риску"}
        );
        maxPositionsSpinner.setAdapter(maxPosAdapter);
        maxPositionsSpinner.setSelection(0);
''', 'risk-only spinner')

main = replace_one(main,
'''                prefs.edit().putInt("ec_limit", position).putString("maxpos_label", String.valueOf(maxPositionsSpinner.getSelectedItem())).apply();
''',
'''                prefs.edit().putInt("ec_limit", 0).putString("maxpos_label", "По риску").apply();
''', 'risk-only spinner listener')

main = replace_one(main,
'''            boolean autoSaved = !p.getBoolean("v108_emergency_latched", false) && p.getBoolean("auto_user_enabled", p.getBoolean("auto_trading", false)) && mt5 && targetAllowed;
            autoTradingSwitch.setChecked(autoSaved);
            p.edit().putBoolean("auto_trading", autoSaved).apply();
            suppressAutoSwitch = false;
''',
'''            JSONObject bridgeState = EventClient.state();
            boolean emergency = p.getBoolean("v108_emergency_latched", false) || bridgeState.optBoolean("emergency", false);
            boolean paused = bridgeState.optBoolean("paused", true);
            boolean bridgeAuto = bridgeState.optBoolean("auto", false) && !emergency;
            boolean autoSaved = bridgeAuto && mt5 && targetAllowed;
            autoTradingSwitch.setChecked(autoSaved);
            p.edit().putBoolean("auto_trading", autoSaved).putBoolean("auto_user_enabled", autoSaved).putInt("ec_limit", 0).apply();
            if (autoStatusText != null) {
                autoStatusText.setText(emergency ? "EMERGENCY · AUTO заблокирован" :
                        autoSaved ? "AUTO включён · DEMO ONLY" :
                        paused ? "AUTO выключен · PAUSE" : "AUTO выключен · DEMO ONLY");
                autoStatusText.setTextColor(emergency ? C_RED : autoSaved ? C_GREEN : C_MUTED);
            }
            suppressAutoSwitch = false;
''', 'AUTO snapshot sync')

main = replace_one(main,
'''    private void refreshSmartUi() {
        SharedPreferences p=getSharedPreferences("fxm1",MODE_PRIVATE);JSONObject s=EventClient.state(),cfg=s.optJSONObject("config");
        if(smartStatusText!=null)smartStatusText.setText("Режим: "+(cfg==null?EventClient.mode():cfg.optString("mode"))+" · только DEMO\\nИсточник: MT5\\n"+
            "Наращивание: "+(cfg!=null&&cfg.optBoolean("dynamic_adds")?"по новым подтверждениям и общему риску":"один вход")+
            "\\nСопровождение: независимый Bridge\\n"+ExecutionFeedback.riskText(p.getString("risk_snapshot","не проверен"))+"\\n"+p.getString("ec_message",""));
''',
'''    private String bridgeOperationalText(JSONObject s) {
        SharedPreferences p=getSharedPreferences("fxm1",MODE_PRIVATE);
        boolean emergency=p.getBoolean("v108_emergency_latched",false)||s.optBoolean("emergency",false);
        boolean auto=s.optBoolean("auto",false)&&!emergency;
        boolean paused=s.optBoolean("paused",true);
        if(emergency)return "EMERGENCY: новые входы заблокированы; требуется явная сверка";
        if(auto&&!paused)return "AUTO DEMO включён; новые входы и добавления разрешены только по новому подтверждённому событию";
        if(paused)return "PAUSE: новые входы и добавления остановлены; сопровождение открытой кампании продолжается";
        return "AUTO выключен; новые входы и добавления не отправляются";
    }

    private void refreshSmartUi() {
        SharedPreferences p=getSharedPreferences("fxm1",MODE_PRIVATE);JSONObject s=EventClient.state(),cfg=s.optJSONObject("config");
        p.edit().putInt("ec_limit",0).putString("maxpos_label","По риску").apply();
        if(smartStatusText!=null)smartStatusText.setText("Режим: "+(cfg==null?EventClient.mode():cfg.optString("mode"))+" · только DEMO\\nИсточник: MT5\\n"+
            "Наращивание: "+(cfg!=null&&cfg.optBoolean("dynamic_adds")?"по новым подтверждениям и общему риску":"один вход")+
            "\\nСопровождение: независимый Bridge\\n"+ExecutionFeedback.riskText(p.getString("risk_snapshot","не проверен"))+"\\n"+bridgeOperationalText(s));
''', 'smart status live state')

main = replace_one(main,
'''        p.edit().putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).apply();
        if(was)eventCommand("disable",new JSONObject());
''',
'''        p.edit().putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).apply();
        if(autoStatusText!=null){autoStatusText.setText("AUTO выключен · DEMO ONLY");autoStatusText.setTextColor(C_MUTED);}
        if(was)eventCommand("disable",new JSONObject());
''', 'force auto off label')

main_path.write_text(main, encoding='utf-8')

client = client_path.read_text(encoding='utf-8')
client = replace_one(client,
'''            .put("optional_position_limit",p.getInt("ec_limit",0))
''',
'''            .put("optional_position_limit",0)
''', 'EventClient fixed limit removal')
client_path.write_text(client, encoding='utf-8')
