package com.openai.fxm1;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.SystemClock;
import org.json.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Transport and presentation only. It cannot calculate or send a BUY/SELL order. */
public final class EventClient {
    public static String phaseName(String phase){switch(phase){case "SEARCH":return "Поиск";case "FORECAST":return "Прогноз / поздний вход заблокирован";case "PROBE_READY":return "Ранний probe";case "PULLBACK":return "Ожидание отката";case "TRIGGER":return "Ожидание подтверждения";case "ENTRY_READY":return "Вход подтверждён";case "HOLD":return "Сопровождение";case "CANCELLED":return "Сценарий отменён";case "DATA_BLOCK":return "Нет пригодных данных";default:return phase;}}
    public static String pathName(String path){switch(path){case "COMPUTE":return "ComputeCore";case "FORECAST":return "LIVE Forecast";case "LIVE_BREAKOUT":return "Первичный LIVE-пробой";case "LATE_BLOCK":return "Поздний вход заблокирован";case "IMPULSE":return "Импульс";case "CONTINUATION":return "Продолжение";case "PULLBACK":return "Откат";case "TRIGGER":return "Триггер";default:return "Поиск";}}
    public static final String VERSION="10.9-EC1", PROTOCOL="fxm1.event.v1";
    private static Context app;
    private EventClient() {}
    public static synchronized void init(Context context) {
        app=context.getApplicationContext();
        SharedPreferences p=prefs();
        if(!p.getBoolean("ec1_migrated",false))p.edit().putBoolean("ec1_migrated",true)
            .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false)
            .putBoolean("bg_running",false).putBoolean("server_verified",false)
            .remove("state_symbol").remove("state_tf").remove("state_sparkline").putString("state_signal","WAIT")
            .putString("target_trade_mode","DEMO").putInt("ec_limit",0)
            .putString("ec_lot_cap","0.01").apply();
        if(!p.getBoolean("ec1_r2_risk_migrated",false))p.edit().putBoolean("ec1_r2_risk_migrated",true)
            .remove("ec_test_capital").remove("ec_risk_cap").remove("daily_loss_limit_pct")
            .remove("max_drawdown_pct").remove("max_consecutive_losses").apply();
        if(!p.contains("ec_client_id"))p.edit().putString("ec_client_id",UUID.randomUUID().toString()).commit();
    }
    public static SharedPreferences prefs(){if(app==null)throw new IllegalStateException("Client not initialized");return app.getSharedPreferences("fxm1",Context.MODE_PRIVATE);}
    public static String base(){String b=prefs().getString("server_url","").trim();if(!b.isEmpty()&&!b.startsWith("http://")&&!b.startsWith("https://"))b="http://"+b;while(b.endsWith("/"))b=b.substring(0,b.length()-1);return b;}
    public static String tf(){String[] t={"M1","M5","M10","M15","H1","H4","D1","W1","MN1"};return t[Math.max(0,Math.min(8,prefs().getInt("entry_tf_pos",1)))];}
    public static String mode(){return prefs().getInt("signal_mode_pos",0)==1?"SCALP":"NORMAL";}
    public static JSONObject state(){try{return new JSONObject(prefs().getString("ec_state","{}"));}catch(Exception e){return new JSONObject();}}
    public static String campaignSummary(JSONObject state){
        if(state==null)return "";
        JSONObject campaign=state.optJSONObject("campaign");JSONArray positions=state.optJSONArray("positions");
        if(campaign==null||positions==null||positions.length()==0)return "";
        int side=campaign.optInt("side",0);double volume=0,weighted=0,pl=0,minSl=Double.POSITIVE_INFINITY,maxSl=Double.NEGATIVE_INFINITY;
        for(int i=0;i<positions.length();i++){JSONObject p=positions.optJSONObject(i);if(p==null)continue;
            double v=p.optDouble("volume",0),entry=p.optDouble("price_open",Double.NaN),sl=p.optDouble("sl",Double.NaN);
            volume+=v;if(Double.isFinite(entry))weighted+=entry*v;pl+=p.optDouble("profit",0)+p.optDouble("swap",0);
            if(Double.isFinite(sl)&&sl>0){minSl=Math.min(minSl,sl);maxSl=Math.max(maxSl,sl);}
        }
        if(volume<=0)return "";
        String cls=campaign.optBoolean("confirmed",false)?"CONFIRMED":campaign.optString("entry_class","PROBE");
        String slText=!Double.isFinite(minSl)?"—":Math.abs(maxSl-minSl)<.0000005?String.format(Locale.US,"%.5f",minSl):String.format(Locale.US,"%.5f … %.5f",minSl,maxSl);
        return "ОТКРЫТАЯ КАМПАНИЯ: "+(side>0?"BUY":side<0?"SELL":"—")+" · "+cls+
            "\nEntry MT5: "+String.format(Locale.US,"%.5f",weighted/volume)+" · "+String.format(Locale.US,"%.2f",volume)+" lot"+
            "\nSL MT5: "+slText+"\nP/L: "+String.format(Locale.US,"%+.2f USD",pl)+
            "\nВыход: структура / защитный SL; фиксированный TP не используется";
    }
    public static JSONObject http(String method,String url,JSONObject data) throws Exception {
        if(base().isEmpty())throw new IOException("Не задан адрес Bridge EventCore");
        URL target=new URL(url);URL origin=new URL(base());
        if(!target.getHost().equals(origin.getHost())||target.getPort()!=origin.getPort())throw new IOException("Ключ не отправляется другому серверу");
        HttpURLConnection c=(HttpURLConnection)target.openConnection();
        c.setInstanceFollowRedirects(false);c.setConnectTimeout(2500);c.setReadTimeout(3500);c.setRequestMethod(method);
        c.setRequestProperty("Authorization","Bearer "+prefs().getString("ec_token",""));
        c.setRequestProperty("Accept","application/json");
        try {
            if(data!=null){c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json; charset=UTF-8");try(OutputStream o=c.getOutputStream()){o.write(data.toString().getBytes(StandardCharsets.UTF_8));}}
            int code=c.getResponseCode();InputStream in=code<400?c.getInputStream():c.getErrorStream();
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            if(in!=null)try(InputStream stream=in){byte[] buf=new byte[4096];int n;while((n=stream.read(buf))!=-1){out.write(buf,0,n);if(out.size()>8000000)throw new IOException("Слишком большой ответ Bridge");}}
            JSONObject r=new JSONObject(out.toString("UTF-8"));
            if(code<200||code>=300)throw new IOException(r.optString("message","Bridge HTTP "+code));
            return r;
        }finally{c.disconnect();}
    }
    public static synchronized JSONObject envelope(JSONObject body) throws Exception {
        SharedPreferences p=prefs();long seq=p.getLong("ec_sequence",0)+1;
        if(!p.edit().putLong("ec_sequence",seq).commit())throw new IOException("Нельзя сохранить порядок команд");
        JSONObject b=body==null?new JSONObject():new JSONObject(body.toString());
        return b.put("client_id",p.getString("ec_client_id","")).put("sequence",seq).put("command_id",UUID.randomUUID().toString());
    }
    public static JSONObject command(String cmd,JSONObject body) throws Exception{return http("POST",base()+"/ec/command/"+cmd,envelope(body));}
    public static String accountMode(){
        String target=prefs().getString("target_trade_mode","DEMO").toUpperCase(Locale.US);
        return "REAL".equals(target)?"REAL":"DEMO";
    }
    public static String feePrefKey(){
        String key=prefs().getString("mt5_account_key_snapshot","UNBOUND");
        String symbol=prefs().getString("selected_symbol","EUR/USD");
        return "ec_fee_REAL_"+key+"|"+symbol;
    }
    public static JSONObject config() throws Exception {
        SharedPreferences p=prefs();double[] risks={.25,.5,1};String accountMode=accountMode();
        double risk="REAL".equals(accountMode)?.25:risks[Math.max(0,Math.min(2,p.getInt("risk_pos",0)))];
        String fee="REAL".equals(accountMode)?p.getString(feePrefKey(),"").trim():"0";
        double lot=.01; // R4 keeps execution simple while ComputeCore is being validated.
        return new JSONObject().put("symbol",p.getString("selected_symbol","EUR/USD"))
            .put("timeframe","M5").put("mode","NORMAL").put("engine_mode","COMPUTE_V1")
            .put("account_mode",accountMode).put("risk_pct",risk)
            .put("optional_position_limit",0)
            .put("fee_per_lot",fee.isEmpty()?JSONObject.NULL:Double.parseDouble(fee.replace(',','.')))
            .put("lot_cap",lot).put("probe_lot_cap",lot)
            .put("spread_pips",3.0).put("max_spread_atr",.25)
            .put("cooldown_sec",0).put("dynamic_adds",true)
            .put("session_filter",false).put("allowed_sessions","ASIA,LONDON,NEW_YORK");
    }
    private static boolean sameNumber(JSONObject a,JSONObject b,String key){
        if(a==null||b==null)return false;
        boolean an=a.isNull(key),bn=b.isNull(key);if(an||bn)return an&&bn;
        double x=a.optDouble(key,Double.NaN),y=b.optDouble(key,Double.NaN);
        return Double.isFinite(x)&&Double.isFinite(y)&&Math.abs(x-y)<1e-9;
    }
    private static boolean configMatches(JSONObject remote,JSONObject desired){
        if(remote==null||desired==null)return false;
        for(String key:new String[]{"symbol","timeframe","mode","engine_mode","account_mode","allowed_sessions"})
            if(!remote.optString(key,"").equals(desired.optString(key,"")))return false;
        for(String key:new String[]{"risk_pct","optional_position_limit","fee_per_lot","lot_cap","probe_lot_cap","spread_pips","max_spread_atr","cooldown_sec"})
            if(!sameNumber(remote,desired,key))return false;
        for(String key:new String[]{"dynamic_adds","session_filter"})
            if(remote.optBoolean(key)!=desired.optBoolean(key))return false;
        return true;
    }
    public static boolean needsConfigure(JSONObject state) throws Exception {
        if(state==null||state.optJSONObject("campaign")!=null||state.optBoolean("auto",false)
                ||state.optBoolean("emergency",false)||state.optBoolean("exit_pending",false))return false;
        return !configMatches(state.optJSONObject("config"),config());
    }
    public static void configure() throws Exception {
        JSONObject desired=config();String fingerprint=desired.toString();
        JSONObject current=http("GET",base()+"/ec/state",null);
        if(!PROTOCOL.equals(current.optString("protocol")))throw new IOException("Нужен Bridge EventCore EC1; старый Bridge не подходит");
        if(configMatches(current.optJSONObject("config"),desired)){
            cache(current);prefs().edit().putString("ec_config_sent",fingerprint).apply();return;
        }
        JSONObject result=command("configure",new JSONObject().put("config",desired));
        prefs().edit().putString("ec_config_sent",fingerprint).putString("ec_message",result.optString("message")).apply();
        JSONObject refreshed=http("GET",base()+"/ec/state",null);
        if(PROTOCOL.equals(refreshed.optString("protocol")))cache(refreshed);
    }
    public static JSONObject poll() throws Exception {
        JSONObject s=http("GET",base()+"/ec/state",null);
        if(!PROTOCOL.equals(s.optString("protocol")))throw new IOException("Нужен Bridge EventCore EC1; старый Bridge не подходит");
        cache(s);return s;
    }
    static String moneySummary(JSONObject o){if(o==null)return "—";return String.format(Locale.US,"+%.2f / −%.2f · ИТОГ %+.2f USD · %d сдел.",o.optDouble("profit"),Math.abs(o.optDouble("loss")),o.optDouble("net"),o.optInt("count"));}
    public static void cache(JSONObject s) throws Exception {
        SharedPreferences p=prefs();JSONObject a=s.optJSONObject("account"),d=s.optJSONObject("decision"),q=s.optJSONObject("quote"),cfg=s.optJSONObject("config"),rs=s.optJSONObject("risk"),fc=s.optJSONObject("forecast");
        if(a==null)a=new JSONObject();if(d==null)d=new JSONObject();if(cfg==null)cfg=new JSONObject();if(rs==null)rs=new JSONObject();if(fc==null)fc=new JSONObject();
        long now=System.currentTimeMillis();boolean connected=!a.isNull("balance")&&a.has("balance")&&s.optDouble("account_age",999)<10;
        boolean latch=s.optBoolean("emergency",false)||p.getBoolean("v108_emergency_latched",false);
        boolean auto=s.optBoolean("auto",false)&&!latch;
        String sig=d.optString("signal","WAIT"),symbol=cfg.optString("symbol","EUR/USD"),tf=cfg.optString("timeframe","M5");
        String phase=d.optString("phase","SEARCH"),path=d.optString("path","SEARCH");String why=d.optString("reason","Ждём MT5");
        JSONObject campaign=s.optJSONObject("campaign");
        String campaignSide="";
        if(campaign!=null){int side=campaign.optInt("side",0);campaignSide=side>0?"BUY":side<0?"SELL":"—";}
        long since=sig.equals(p.getString("state_signal","WAIT"))?p.getLong("state_signal_since_ms",now):now;
        if("WAIT".equals(sig))since=0;
        int fside=fc.optInt("side",0),fcandidate=fc.optInt("candidate_side",0);double fconfidence=fc.optDouble("confidence",0);
        boolean forecastAvailable=fc.optBoolean("available",fc.has("up_probability"));
        long up=Math.round(fc.optDouble("up_probability",0)*100),down=Math.round(fc.optDouble("down_probability",0)*100),range=Math.round(fc.optDouble("range_probability",0)*100);
        String direction=fside>0?" · BIAS BUY":fside<0?" · BIAS SELL":fcandidate>0?" · EARLY BUY CANDIDATE":fcandidate<0?" · EARLY SELL CANDIDATE":" · NO EDGE";
        String forecastText=forecastAvailable?
            ("LIVE FORECAST: UP "+up+"% · DOWN "+down+"% · RANGE "+range+"% · "+fc.optString("regime","RANGE")+direction):
            "LIVE FORECAST: ожидаем достаточные данные";
        if(fc.optBoolean("late_entry",false))forecastText+=" · LATE ENTRY BLOCK";
        if(fc.optBoolean("exhaustion",false))forecastText+=" · EXHAUSTION";
        StringBuilder context=new StringBuilder("Вход: ").append(tf).append(" · Режим: ").append(cfg.optString("mode","NORMAL"))
            .append("\nЭтап: ").append(phaseName(phase)).append("\nПуть: ").append(pathName(path)).append("\n").append(why)
            .append("\n").append(forecastText)
            .append("\nРешение и исполнение: данные MT5");
        if(campaign!=null)context.append("\nОткрытая кампания: ").append(campaignSide);
        JSONObject reversal=s.optJSONObject("pending_reversal");
        if(reversal!=null){int rsd=reversal.optInt("side",0);context.append("\nREVERSAL PENDING: закрываем текущую сторону → ").append(rsd>0?"BUY":rsd<0?"SELL":"—");}
        if(q!=null)context.append("\nВремя котировки: ").append(new java.text.SimpleDateFormat("HH:mm:ss",Locale.US).format(new Date(q.optLong("time_msc"))));
        JSONArray positions=s.optJSONArray("all_positions");int n=positions==null?0:positions.length();double floating=0;
        if(positions!=null)for(int i=0;i<positions.length();i++){JSONObject x=positions.getJSONObject(i);floating+=x.optDouble("profit")+x.optDouble("swap");}
        String risk=rs.optBoolean("allowed",false)?"RISK OK":"RISK BLOCK: "+rs.optJSONArray("blocks");
        SharedPreferences.Editor e=p.edit().putString("ec_state",s.toString()).putLong("ec_received_elapsed",SystemClock.elapsedRealtime())
            .putBoolean("server_verified",connected).putBoolean("mt5_connected_snapshot",connected)
            .putBoolean("auto_trading",auto).putBoolean("auto_user_enabled",auto).putBoolean("trading_paused",s.optBoolean("paused",true))
            .putString("bridge_version_snapshot",VERSION).putBoolean("bridge_version_match_snapshot",true).putBoolean("bridge_real_enabled_snapshot",s.optBoolean("real_armed",false))
            .putString("mt5_account_type_snapshot",a.optString("type","UNKNOWN")).putString("mt5_account_key_snapshot",a.optString("key",""))
            .putString("mt5_currency_snapshot",a.optString("currency","USD")).putString("fee_profile_snapshot",s.optJSONObject("fee_profile")==null?"{}":s.optJSONObject("fee_profile").toString())
            .putLong("mt5_balance_bits",Double.doubleToLongBits(a.optDouble("balance",Double.NaN)))
            .putLong("mt5_equity_bits",Double.doubleToLongBits(a.optDouble("equity",Double.NaN)))
            .putInt("mt5_positions_snapshot",n).putLong("mt5_floating_bits",Double.doubleToLongBits(floating))
            .putString("state_symbol",symbol).putString("state_tf",tf).putString("state_signal",sig).putString("state_campaign_side",campaignSide)
            .putString("state_context",context.toString()).putString("state_why",why).putString("state_forecast_text",forecastText)
            .putString("state_components",forecastText+"\nКомпоненты: "+(fc.optJSONObject("components")==null?"{}":fc.optJSONObject("components").toString())+
                "\nСправа на графике — MAIN и ALT сценарии с ключевыми уровнями; это вычислительная карта вариантов, не гарантированный маршрут."+
                "\nComputeCore сам выбирает момент входа. При подтверждённом противоположном сценарии: закрытие текущей стороны → MT5 FLAT → повторная проверка → разворот.")
            .putInt("state_quality",-1).putInt("state_api_count",0).putInt("state_cache_count",0)
            .putLong("state_signal_since_ms",since).putLong("state_last_update_ms",now).putLong("state_last_success_ms",(long)(s.optDouble("analysis_time",0)*1000))
            .putLong("state_entry_bits",Double.doubleToLongBits(q==null?Double.NaN:q.optDouble("bid",Double.NaN)))
            .putLong("state_sl_bits",Double.doubleToLongBits(d.optDouble("stop",0)>0?d.optDouble("stop"):Double.NaN))
            .putLong("state_tp1_bits",Double.doubleToLongBits(Double.NaN)).putLong("state_tp2_bits",Double.doubleToLongBits(Double.NaN))
            .putString("risk_snapshot",risk).putString("risk_detail_json",rs.toString()).putLong("smart_snapshot_ms",now)
            .putString("position_manager_status","Bridge EventCore · "+(campaign==null?"ожидание кампании":"сопровождение "+campaignSide+" · "+cfg.optString("mode")))
            .putString("bg_status",s.optString("execution",why));
        if(s.optBoolean("emergency",false))e.putBoolean("v108_emergency_latched",true);
        if(s.optBoolean("history_ok",false))e.putString("money_realized_snapshot","Сегодня: "+moneySummary(s.optJSONObject("today"))+"\nВсего: "+moneySummary(s.optJSONObject("all"))).putString("money_refresh_error","");
        else e.putString("money_refresh_error",s.optString("history_error","История не обновлена"));
        String historyKey=phase+"|"+sig+"|"+why;
        boolean changed=!historyKey.equals(p.getString("ec_history_key",""));
        e.putString("ec_history_key",historyKey);e.apply();
        if(changed)FeatureEngine.appendSignalHistory(p,symbol,tf,sig,-1,phaseName(phase)+": "+why);
        ExecutionFeedback.record(p,symbol,tf,phase,s.optString("execution","—"));
    }
    public static void offline(Exception error){prefs().edit().putBoolean("server_verified",false).putBoolean("mt5_connected_snapshot",false)
        .putString("bg_status","Нет связи: "+error.getMessage()).putString("ec_message",String.valueOf(error.getMessage()))
        .putString("risk_snapshot","Нет свежей проверки риска").apply();}
}
