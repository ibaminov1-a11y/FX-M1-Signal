from pathlib import Path

p=Path('app/src/main/java/com/openai/fxm1/MainActivity.java')
s=p.read_text(encoding='utf-8')
old='''        autoTradingSwitch.setOnCheckedChangeListener((buttonView,isChecked)->{
            if(suppressAutoSwitch)return;
            if(!isChecked){eventCommand("disable",new JSONObject());return;}
            suppressAutoSwitch=true;autoTradingSwitch.setChecked(false);suppressAutoSwitch=false;
            if(prefs.getBoolean("v108_emergency_latched",false)){
                new AlertDialog.Builder(this).setTitle("Аварийная блокировка")
                    .setMessage("PLAY и AUTO не снимают Emergency. Выполните явную сверку в настройках.")
                    .setPositiveButton("OK",null).show();return;
            }
            new AlertDialog.Builder(this).setTitle("Разрешить AUTO только на DEMO?")
                .setMessage("Источник — MT5. Первый вход после отката и нового триггера. Добавления только в плюс и в пределах общего риска текущей кампании.\\n\\nРиск кампании рассчитывается от фактического Balance/Equity MT5 по выбранному проценту. Старые V10 и ручные сделки не блокируют EC1. Комиссию укажите в настройках.")
                .setNegativeButton("Отмена",null).setPositiveButton("Подтвердить DEMO",(d,w)->executor.execute(()->{
                    try{EventClient.configure();EventClient.command("approve_profile",new JSONObject().put("confirmation","APPROVE_DEMO_RISK"));
                        JSONObject out=EventClient.command("enable",new JSONObject().put("confirmation","ENABLE_DEMO"));EventClient.poll();
                        runOnUiThread(()->{addJournal(out.optString("message"));startUnifiedMonitoringService();});
                    }catch(Exception e){runOnUiThread(()->new AlertDialog.Builder(this).setTitle("AUTO не включён").setMessage(safeMessage(e)).setPositiveButton("OK",null).show());}
                })).show();
        });
'''
new='''        // Remote AUTO state is owned by Bridge. Programmatic/system restoration of the
        // Android Switch must NEVER become a trading command; only an actual user click can.
        autoTradingSwitch.setOnClickListener(v->{
            if(suppressAutoSwitch)return;
            boolean isChecked=autoTradingSwitch.isChecked();
            if(!serverConnected||!mt5Connected){
                suppressAutoSwitch=true;
                autoTradingSwitch.setChecked(prefs.getBoolean("auto_trading",false));
                suppressAutoSwitch=false;
                Toast.makeText(this,"Нет свежей связи с Bridge · AUTO на Bridge не изменён",Toast.LENGTH_LONG).show();
                return;
            }
            if(!isChecked){eventCommand("disable",new JSONObject());return;}
            suppressAutoSwitch=true;autoTradingSwitch.setChecked(false);suppressAutoSwitch=false;
            if(prefs.getBoolean("v108_emergency_latched",false)){
                new AlertDialog.Builder(this).setTitle("Аварийная блокировка")
                    .setMessage("PLAY и AUTO не снимают Emergency. Выполните явную сверку в настройках.")
                    .setPositiveButton("OK",null).show();return;
            }
            new AlertDialog.Builder(this).setTitle("Разрешить AUTO только на DEMO?")
                .setMessage("Источник — MT5. Первый вход после отката и нового триггера. Добавления только в плюс и в пределах общего риска текущей кампании.\\n\\nРиск кампании рассчитывается от фактического Balance/Equity MT5 по выбранному проценту. Старые V10 и ручные сделки не блокируют EC1. Комиссию укажите в настройках.")
                .setNegativeButton("Отмена",null).setPositiveButton("Подтвердить DEMO",(d,w)->executor.execute(()->{
                    try{EventClient.configure();EventClient.command("approve_profile",new JSONObject().put("confirmation","APPROVE_DEMO_RISK"));
                        JSONObject out=EventClient.command("enable",new JSONObject().put("confirmation","ENABLE_DEMO"));EventClient.poll();
                        runOnUiThread(()->{addJournal(out.optString("message"));startUnifiedMonitoringService();});
                    }catch(Exception e){runOnUiThread(()->new AlertDialog.Builder(this).setTitle("AUTO не включён").setMessage(safeMessage(e)).setPositiveButton("OK",null).show());}
                })).show();
        });
'''
if old not in s:
    raise SystemExit('AUTO switch listener source pattern not found')
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
