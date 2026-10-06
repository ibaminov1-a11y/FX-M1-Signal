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
    public static String phaseName(String phase){switch(phase){case "SEARCH":return "Поиск";case "FORECAST":return "Прогноз / поздний вход заблокирован";case "PROBE_READY":return "Ранний probe";case "PULLBACK":return "Ожидание отката";case "TRIGGER":return "Ожидание подтверждения";case "ENTRY_READY":return "Вход подтверждён";case "ENTRY_BLOCKED":return "Вход не исполнен · проверка риска";case "HOLD":return "Сопровождение";case "CANCELLED":return "Сценарий отменён";case "DATA_BLOCK":return "Нет пригодных данных";default:return phase;}}
    public static String pathName(String path){switch(path){case "SCENARIO_V2":return "Scenario Engine V2";case "COMPUTE":return "ComputeCore";case "FORECAST":return "LIVE Forecast";case "LIVE_BREAKOUT":return "Первичный LIVE-пробой";case "LATE_BLOCK":return "Поздний вход заблокирован";case "IMPULSE":return "Импульс";case "CONTINUATION":return "Продолжение";case "PULLBACK":return "Откат";case "TRIGGER":return "Триггер";default:return "Поиск";}}
    public static final String VERSION="10.9-EC1", PROTOCOL="fxm1.event.v1";
    private static Context app;
    // Only preference publication is locked; network reads never block service commands.
    private static final Object STATE_READ_LOCK=new Object();
    private static final Object EMERGENCY_RESET_LOCK=new Object();
    private static long nextReadSequence,lastPublishedRead,lastAuxiliaryRead,lastResetRead,commandGeneration;
    static final class ReadRequest {
        final String source,token;
        String profileId;
        boolean profileTransition=false;
        long sequence;
        final long generation;
        ReadRequest(String source,String token,long sequence){
            this.source=source;this.token=token;this.sequence=sequence;this.generation=commandGeneration;
            this.profileTransition=!source.equals(prefs().getString("ec_state_source",source));
            this.profileId=profileTransition?"":state().optString("profile_id","");
        }
    }
    private static final class ReadFailure extends IOException {
        final ReadRequest read;
        final Exception original;
        ReadFailure(ReadRequest read,Exception original){super(original.getMessage(),original);this.read=read;this.original=original;}
    }
    private static final class BridgeBusy extends IOException {
        BridgeBusy(String message){super(message);}
    }
    static ReadRequest newReadRequest(){
        synchronized(STATE_READ_LOCK){return new ReadRequest(base(),prefs().getString("ec_token",""),lastPublishedRead);}
    }
    private static void requireSameSource(ReadRequest read) throws IOException {
        if(!read.source.equals(base())||!read.token.equals(prefs().getString("ec_token","")))
            throw new IOException("Подключение изменено; повторите обновление");
    }
    static boolean isCurrentSource(ReadRequest read){return read.source.equals(base())&&read.token.equals(prefs().getString("ec_token",""));}
    static JSONObject readSymbols(ReadRequest read) throws Exception {return readHttp(read,"/symbols");}
    static void requireCurrentSelection(ReadRequest read,JSONObject desired) throws Exception {
        synchronized(STATE_READ_LOCK){
            requireActiveRead();requireSameSource(read);
            if(read.generation!=commandGeneration)throw new IOException("Команда отменена более поздним управлением");
            if(desired!=null&&!configMatches(desired,config()))throw new IOException("Выбор изменён; подтвердите текущий профиль");
        }
    }
    private static void startRead(ReadRequest read) throws Exception {
        synchronized(STATE_READ_LOCK){requireActiveRead();requireSameSource(read);read.sequence=++nextReadSequence;}
    }
    private static boolean publishSnapshot(ReadRequest read,JSONObject snapshot) throws Exception {
        synchronized(STATE_READ_LOCK){
            requireActiveRead();requireSameSource(read);
            if(read.sequence<lastPublishedRead||(!read.profileTransition&&!read.profileId.equals(state().optString("profile_id",""))))return false;
            cacheSnapshot(snapshot);lastPublishedRead=read.sequence;return true;
        }
    }
    static void offlineIfCurrent(ReadRequest read,Exception error){
        synchronized(STATE_READ_LOCK){
            if(Thread.currentThread().isInterrupted()||read==null||(!read.profileTransition&&!read.profileId.equals(state().optString("profile_id","")))||read.sequence<lastPublishedRead||!read.source.equals(base())||!read.token.equals(prefs().getString("ec_token","")))return;
            if(error instanceof BridgeBusy){
                JSONObject snapshot=state();long received=prefs().getLong("ec_received_elapsed",0);
                double accountAge=snapshot.optDouble("account_age",999)+(SystemClock.elapsedRealtime()-received)/1000.0;
                prefs().edit().putBoolean("server_verified",true)
                    .putBoolean("mt5_connected_snapshot",read.source.equals(prefs().getString("ec_state_source",read.source))&&prefs().getBoolean("mt5_connected_snapshot",false)&&accountAge<10)
                    .putString("ec_message",error.getMessage()).putString("money_refresh_error","Bridge занят; показан последний снимок").apply();
                return;
            }
            offlineSnapshot(error);lastPublishedRead=read.sequence;
        }
    }
    private EventClient() {}
    public static synchronized void init(Context context) {
        app=context.getApplicationContext();
        SharedPreferences p=prefs();
        Timeframes.migrate(p);
        if(!p.getBoolean("ec1_migrated",false))p.edit().putBoolean("ec1_migrated",true)
            .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false)
            .putBoolean("bg_running",false).putBoolean("server_verified",false)
            .remove("state_symbol").remove("state_tf").remove("state_sparkline").putString("state_signal","WAIT")
            .putString("target_trade_mode",p.getString("target_trade_mode","DEMO")).putInt("ec_limit",0)
            .putString("ec_lot_cap",p.getString("ec_lot_cap","0.01")).apply();
        if(!p.getBoolean("ec1_r2_risk_migrated",false))p.edit().putBoolean("ec1_r2_risk_migrated",true)
            .remove("ec_test_capital").remove("ec_risk_cap").remove("daily_loss_limit_pct")
            .remove("max_drawdown_pct").remove("max_consecutive_losses").apply();
        if(!p.contains("ec_client_id"))p.edit().putString("ec_client_id",UUID.randomUUID().toString()).commit();
    }
    public static SharedPreferences prefs(){if(app==null)throw new IllegalStateException("Client not initialized");return app.getSharedPreferences("fxm1",Context.MODE_PRIVATE);}
    public static String base(){String b=prefs().getString("server_url","").trim();if(!b.isEmpty()&&!b.startsWith("http://")&&!b.startsWith("https://"))b="http://"+b;while(b.endsWith("/"))b=b.substring(0,b.length()-1);return b;}
    public static String tf(){return Timeframes.selected(prefs());}
    public static String mode(){return prefs().getInt("signal_mode_pos",0)==1?"SCALP":"NORMAL";}
    public static JSONObject state(){
        try{
            // This is a presentation copy. Losing phone connectivity neither makes the
            // Bridge's own market data stale nor changes its independent AUTO state.
            JSONObject snapshot=new JSONObject(prefs().getString("ec_state","{}"));
            boolean offline=!prefs().getBoolean("server_verified",false)||!base().equals(prefs().getString("ec_state_source",base()));
            snapshot.put("client_offline",offline);
            JSONObject forecast=snapshot.optJSONObject("forecast");
            if(forecast!=null)forecast.put("client_offline",offline);
            return snapshot;
        }catch(Exception e){return new JSONObject();}
    }
    static String price(JSONObject snapshot,double value){
        if(!Double.isFinite(value)||value<=0)return "—";
        JSONObject instrument=snapshot==null?null:snapshot.optJSONObject("instrument");
        int digits=instrument==null?5:instrument.optInt("digits",5);
        if(digits<0||digits>12)digits=5;
        return String.format(Locale.US,"%."+digits+"f",value);
    }
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
        String minSlText=price(state,minSl),maxSlText=price(state,maxSl);
        String slText=minSlText.equals(maxSlText)?minSlText:minSlText+" … "+maxSlText;
        return "ОТКРЫТАЯ КАМПАНИЯ: "+(side>0?"BUY":side<0?"SELL":"—")+" · "+cls+
            "\nEntry MT5: "+price(state,weighted/volume)+" · "+String.format(Locale.US,"%.2f",volume)+" lot"+
            "\nSL MT5: "+slText+"\nP/L: "+String.format(Locale.US,"%+.2f USD",pl)+
            ((campaign.optJSONObject("forecast_at_entry")!=null&&"STABLE_V1".equals(campaign.optJSONObject("forecast_at_entry").optString("execution_policy")))
                ?"\nВыход: исходная цель "+price(state,campaign.optJSONObject("forecast_at_entry").optDouble("entry_target1"))+" / защитный SL / срок плана"
                :"\nВыход: структура / защитный SL; фиксированный TP не используется");
    }
    public static JSONObject http(String method,String url,JSONObject data) throws Exception {
        return http(method,url,data,base(),prefs().getString("ec_token",""));
    }
    private static JSONObject http(String method,String url,JSONObject data,String source,String token) throws Exception {
        if(source.isEmpty())throw new IOException("Не задан адрес Bridge EventCore");
        URL target=new URL(url);URL origin=new URL(source);
        if(!target.getProtocol().equals(origin.getProtocol())||!target.getHost().equals(origin.getHost())||target.getPort()!=origin.getPort())throw new IOException("Ключ не отправляется другому серверу");
        HttpURLConnection c=(HttpURLConnection)target.openConnection();
        c.setInstanceFollowRedirects(false);c.setConnectTimeout(2500);c.setReadTimeout(3500);c.setRequestMethod(method);
        c.setRequestProperty("Authorization","Bearer "+token);
        c.setRequestProperty("Accept","application/json");
        c.setRequestProperty("X-FXM1-Client","R51");
        if(data!=null&&"queued-v1".equals(data.optString("control_protocol"))&&target.getPath().startsWith("/ec/command/"))
            c.setRequestProperty("X-FXM1-Control","queued-v1");
        try {
            if(data!=null){c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json; charset=UTF-8");try(OutputStream o=c.getOutputStream()){o.write(data.toString().getBytes(StandardCharsets.UTF_8));}}
            int code=c.getResponseCode();InputStream in=code<400?c.getInputStream():c.getErrorStream();
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            if(in!=null)try(InputStream stream=in){byte[] buf=new byte[4096];int n;while((n=stream.read(buf))!=-1){out.write(buf,0,n);if(out.size()>8000000)throw new IOException("Слишком большой ответ Bridge");}}
            JSONObject r=new JSONObject(out.toString("UTF-8"));
            if(code==503&&r.optBoolean("server_connected",false)&&r.optBoolean("runtime_busy",false))
                throw new BridgeBusy(r.optString("message","Bridge занят; повторите обновление"));
            if(code<200||code>=300)throw new IOException(r.optString("message","Bridge HTTP "+code));
            return r;
        }finally{c.disconnect();}
    }
    public static JSONObject envelope(JSONObject body) throws Exception {
        synchronized(STATE_READ_LOCK){
        SharedPreferences p=prefs();long seq=p.getLong("ec_sequence",0)+1;
        if(!p.edit().putLong("ec_sequence",seq).commit())throw new IOException("Нельзя сохранить порядок команд");
        JSONObject b=body==null?new JSONObject():new JSONObject(body.toString());
            JSONObject snapshot=state(),caps=snapshot.optJSONObject("capabilities");
            if(caps!=null&&caps.optBoolean("profile_registry")&&!b.has("profile_id")){
                String id=snapshot.optString("profile_id","");
                if(id.isEmpty())throw new IOException("Профиль команды не определён; обновите состояние Bridge");
                b.put("profile_id",id);
            }
        return b.put("client_id",p.getString("ec_client_id","")).put("sequence",seq).put("command_id",UUID.randomUUID().toString());
        }
    }
    /** Immutable intent captured before entering any worker queue. Never retarget or re-envelope it. */
    static final class CommandRequest {
        final String command,source,token,profileId,payload;
        final long generation;
        final boolean durableEmergency;
        CommandRequest(String command,String source,String token,JSONObject payload,long generation){
            this(command,source,token,payload,generation,false);
        }
        CommandRequest(String command,String source,String token,JSONObject payload,long generation,boolean durableEmergency){
            this.command=command;this.source=source;this.token=token;this.payload=payload.toString();
            this.profileId=payload.optString("profile_id","");this.generation=generation;this.durableEmergency=durableEmergency;
        }
    }
    static CommandRequest prepareCommand(String command,JSONObject body) throws Exception {
        synchronized(STATE_READ_LOCK){
            if(!"emergency".equals(command)&&!base().equals(prefs().getString("ec_state_source",base())))throw new IOException("Обновите состояние нового Bridge перед управлением");
            JSONObject data=body==null?new JSONObject():new JSONObject(body.toString());
            if("enable".equals(command)&&"ENABLE_DEMO".equals(data.optString("confirmation")))
                data.put("allow_wait",true).put("accept_pending_profile",true).put("config",config());
            if("emergency".equals(command)||"disable".equals(command)||"pause".equals(command)||"close".equals(command)||"reset".equals(command))++commandGeneration;
            JSONObject snapshot=state(),caps=snapshot.optJSONObject("capabilities"),account=snapshot.optJSONObject("account");
            if((caps!=null&&caps.optBoolean("queued_controls"))&&Arrays.asList("configure","enable","play","pause","disable","close","emergency","reset").contains(command)){
                data.put("control_protocol","queued-v1");
                if(!data.has("account_key")&&account!=null)data.put("account_key",account.optString("key"));
            }
            JSONObject payload=envelope(data);
            if("emergency".equals(command))payload.remove("profile_id");
            return new CommandRequest(command,base(),prefs().getString("ec_token",""),payload,commandGeneration);
        }
    }
    private static void requireCurrentCommand(CommandRequest request) throws Exception {
        requireActiveRead();
        if(!request.source.equals(base())||!request.token.equals(prefs().getString("ec_token","")))
            throw new IOException("Подключение изменено; прежняя команда отменена");
        if(request.durableEmergency){
            JSONObject saved=new JSONObject(prefs().getString("ec_emergency_request","{}")),payload=saved.optJSONObject("payload");
            if(!prefs().getBoolean("ec_emergency_pending",false)||!prefs().getBoolean("v108_emergency_latched",false)||payload==null
                    ||!payload.optString("command_id").equals(new JSONObject(request.payload).optString("command_id")))
                throw new IOException("Аварийная команда уже подтверждена или отменена сверкой");
        }else if(request.generation!=commandGeneration)throw new IOException("Команда отменена более поздним управлением");
        if(!"emergency".equals(request.command)&&!request.profileId.equals(state().optString("profile_id","")))
            throw new IOException("Профиль изменён; прежняя команда отменена");
        if("enable".equals(request.command)){
            if(prefs().getBoolean("v108_emergency_latched",false)||emergencyUncertainAt(request.source,request.token))throw new IOException("AUTO заблокирован: EMERGENCY");
            JSONObject desired=new JSONObject(request.payload).optJSONObject("config");
            if(desired!=null&&!configMatches(desired,config()))throw new IOException("Выбор изменён; подтвердите AUTO для текущего профиля");
        }
    }
    static JSONObject sendCommand(CommandRequest request) throws Exception {
        if("emergency".equals(request.command)||"reset".equals(request.command)){
            synchronized(EMERGENCY_RESET_LOCK){return sendCommandNow(request);}
        }
        return sendCommandNow(request);
    }
    private static JSONObject sendCommandNow(CommandRequest request) throws Exception {
        synchronized(STATE_READ_LOCK){
            requireCurrentCommand(request);
            if("reset".equals(request.command)&&emergencyUncertainAt(request.source,request.token))
                throw new IOException("EMERGENCY отправлен, но ответ Bridge ещё не подтверждён. Дождитесь подтверждения той же команды перед сверкой.");
            // A transport timeout cannot prove whether Bridge executed the packet.
            // Persist this before transmission; only a same-ID acknowledgement resolves it.
            if(request.durableEmergency&&!prefs().edit().putBoolean("ec_emergency_uncertain",true).commit())
                throw new IOException("Не удалось сохранить состояние аварийной отправки");
        }
        JSONObject result=http("POST",request.source+"/ec/command/"+request.command,new JSONObject(request.payload),request.source,request.token);
        if(result.has("command_status"))result=awaitApplied(request,result);
        synchronized(STATE_READ_LOCK){
            // A response from an old connection or superseded command cannot update this screen or its latches.
            requireCurrentCommand(request);
            lastPublishedRead=++nextReadSequence;
            if(request.durableEmergency){
                JSONObject archive=emergencyArchive();archive.remove(emergencyConnectionKey(request.source,request.token));
                prefs().edit().putBoolean("ec_emergency_pending",false).putBoolean("ec_emergency_uncertain",false)
                    .putString("ec_emergency_archive",archive.toString()).commit();
            }
            if("reset".equals(request.command)){
                JSONObject archive=emergencyArchive(),active=new JSONObject(prefs().getString("ec_emergency_request","{}"));
                if(prefs().getBoolean("ec_emergency_uncertain",false)&&active.has("source")
                        &&(!request.source.equals(active.optString("source"))||!request.token.equals(active.optString("token"))))
                    archive.put(emergencyConnectionKey(active.getString("source"),active.getString("token")),active);
                prefs().edit().putBoolean("v108_emergency_latched",false).putBoolean("ec_emergency_pending",false)
                    .putString("ec_emergency_archive",archive.toString()).remove("ec_emergency_request").remove("ec_emergency_uncertain").commit();
                lastResetRead=lastPublishedRead;
            }
        }
        return result;
    }
    /** Poll the original receipt; never re-send a new order/control identity. */
    private static JSONObject awaitApplied(CommandRequest request,JSONObject response) throws Exception {
        String id=new JSONObject(request.payload).getString("command_id");long deadline=SystemClock.elapsedRealtime()+35000;
        while(true){
            synchronized(STATE_READ_LOCK){requireCurrentCommand(request);}
            if(!id.equals(response.optString("command_id")))throw new IOException("Ответ относится к другой команде; применение не подтверждено");
            String status=response.optString("command_status");
            if("APPLIED".equals(status)&&response.optBoolean("applied")&&response.optBoolean("ok")){
                prefs().edit().putString("ec_command_status","APPLIED").remove("ec_command_pending_id").apply();return response;
            }
            if(!"QUEUED".equals(status)&&!"APPLYING".equals(status)){
                prefs().edit().putString("ec_command_status",status).remove("ec_command_pending_id").apply();
                throw new IOException(response.optString("message","Команда отклонена"));
            }
            prefs().edit().putString("ec_command_pending_id",id).putString("ec_command_status",status)
                .putString("ec_message","Команда принята Bridge; ожидается применение. Настройки ещё не подтверждены.").apply();
            if(SystemClock.elapsedRealtime()>deadline)throw new IOException("Команда получена, но применение пока не подтверждено. Обновите статус; не создавайте повторную заявку.");
            Thread.sleep(250);
            synchronized(STATE_READ_LOCK){requireCurrentCommand(request);}
            response=http("GET",request.source+"/ec/commands/"+URLEncoder.encode(id,"UTF-8"),null,request.source,request.token);
        }
    }
    public static JSONObject command(String cmd,JSONObject body) throws Exception{
        return sendCommand(prepareCommand(cmd,body));
    }
    private static String emergencyConnectionKey(String source,String token){return source+"\n"+token;}
    private static JSONObject emergencyArchive() throws Exception{return new JSONObject(prefs().getString("ec_emergency_archive","{}"));}
    private static boolean emergencyUncertainAt(String source,String token) throws Exception {
        JSONObject active=new JSONObject(prefs().getString("ec_emergency_request","{}"));
        return (prefs().getBoolean("ec_emergency_uncertain",false)&&source.equals(active.optString("source"))&&token.equals(active.optString("token")))
            ||emergencyArchive().has(emergencyConnectionKey(source,token));
    }
    /** Emergency retries reuse one durable ID and the original connection, including after service restart. */
    static CommandRequest pendingEmergency() throws Exception {
        synchronized(STATE_READ_LOCK){
            String saved=prefs().getString("ec_emergency_request","");
            if(!saved.isEmpty()){
                JSONObject value=new JSONObject(saved);
                return new CommandRequest("emergency",value.getString("source"),value.getString("token"),value.getJSONObject("payload"),commandGeneration,true);
            }
            // Older builds persisted only a boolean. Its destination and identity
            // are unknowable, so keep the latch and require a new explicit tap.
            throw new IOException("Аварийная блокировка сохранена; нажмите EMERGENCY для отправки текущему Bridge");
        }
    }
    static CommandRequest beginEmergency() throws Exception {
        synchronized(STATE_READ_LOCK){
            JSONObject archive=emergencyArchive(),active=new JSONObject(prefs().getString("ec_emergency_request","{}"));
            String source=base(),token=prefs().getString("ec_token","");
            if(prefs().getBoolean("ec_emergency_uncertain",false)){
                // Replacing an unacknowledged ID would leave an older packet free
                // to take effect after a later reset. Resolve that same ID first.
                if(source.equals(active.optString("source"))&&token.equals(active.optString("token"))){++commandGeneration;return pendingEmergency();}
                archive.put(emergencyConnectionKey(active.getString("source"),active.getString("token")),active);
            }
            JSONObject prior=archive.optJSONObject(emergencyConnectionKey(source,token));
            if(prior!=null){
                ++commandGeneration;
                if(!prefs().edit().putString("ec_emergency_archive",archive.toString()).putString("ec_emergency_request",prior.toString())
                        .putBoolean("ec_emergency_pending",true).putBoolean("ec_emergency_uncertain",true).putBoolean("v108_emergency_latched",true)
                        .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).commit())throw new IOException("Не удалось восстановить аварийную команду");
                return pendingEmergency();
            }
            CommandRequest prepared=prepareCommand("emergency",new JSONObject());
            CommandRequest request=new CommandRequest(prepared.command,prepared.source,prepared.token,new JSONObject(prepared.payload),prepared.generation,true);
            JSONObject value=new JSONObject().put("source",request.source).put("token",request.token).put("payload",new JSONObject(request.payload));
            if(!prefs().edit().putString("ec_emergency_request",value.toString()).putString("ec_emergency_archive",archive.toString()).putBoolean("ec_emergency_pending",true)
                    .putBoolean("ec_emergency_uncertain",false).putBoolean("v108_emergency_latched",true).putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).commit())
                throw new IOException("Не удалось сохранить аварийную команду");
            return request;
        }
    }
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
        double lot=TradeSettings.parseVolume(p.getString("ec_lot_cap","0.01"),null);
        return new JSONObject().put("symbol",p.getString("selected_symbol","EUR/USD"))
            .put("timeframe",tf()).put("mode",mode()).put("engine_mode","SCENARIO_V2").put("volume_mode","FIXED")
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
        for(String key:new String[]{"symbol","timeframe","mode","engine_mode","volume_mode","account_mode","allowed_sessions"})
            if(!remote.optString(key,"").equals(desired.optString(key,"")))return false;
        for(String key:new String[]{"risk_pct","optional_position_limit","fee_per_lot","lot_cap","probe_lot_cap","spread_pips","max_spread_atr","cooldown_sec"})
            if(!sameNumber(remote,desired,key))return false;
        for(String key:new String[]{"dynamic_adds","session_filter"})
            if(remote.optBoolean(key)!=desired.optBoolean(key))return false;
        return true;
    }
    static boolean selectionMatches(JSONObject desired){try{return configMatches(desired,config());}catch(Exception e){return false;}}
    public static boolean hasProfileDraft(){return prefs().contains("ec_profile_draft");}
    /** Called only from an actual selector change; a poll may never create this draft. */
    public static JSONObject rememberProfileSelection(String symbol,int timeframe,int mode,int risk) throws Exception {
        synchronized(STATE_READ_LOCK){
            JSONObject saved=null,snapshot=state();
            String current=snapshot.optJSONObject("config")==null?"":snapshot.optJSONObject("config").optString("symbol");
            if(!symbol.replace("/","").equalsIgnoreCase(current.replace("/",""))){
                JSONArray profiles=snapshot.optJSONArray("profiles");
                if(profiles!=null)for(int i=0;i<profiles.length();i++){
                    JSONObject item=profiles.optJSONObject(i),cfg=item==null?null:item.optJSONObject("config");
                    if(cfg!=null&&symbol.replace("/","").equalsIgnoreCase(cfg.optString("symbol").replace("/","")))saved=cfg;
                }
            }
            SharedPreferences.Editor choice=prefs().edit().putString("selected_symbol",symbol)
                .putInt("signal_mode_pos",mode).putInt("risk_pos",risk);
            Timeframes.select(choice,timeframe);
            if(saved!=null){
                Timeframes.project(choice,saved.optString("timeframe","M5"));
                choice.putInt("signal_mode_pos","SCALP".equals(saved.optString("mode"))?1:0)
                    .putInt("risk_pos",saved.optDouble("risk_pct",.25)>=1?2:saved.optDouble("risk_pct",.25)>=.5?1:0)
                    .putString("ec_lot_cap",String.valueOf(saved.optDouble("lot_cap",.01)));
            }
            choice.apply();
            JSONObject desired=config();prefs().edit().putString("ec_profile_draft",desired.toString()).apply();return desired;
        }
    }
    public static boolean needsConfigure(JSONObject state) throws Exception {
        if(state==null||state.optBoolean("emergency",false)||hasProfileDraft())return false;
        if(state.optJSONObject("campaign")!=null||state.optJSONObject("pending_config")!=null||state.optBoolean("auto",false)||state.optBoolean("exit_pending",false))return false;
        return !configMatches(state.optJSONObject("config"),config());
    }
    public static void configure() throws Exception { configure(false,null,newReadRequest()); }
    static void configure(ReadRequest read) throws Exception {configure(false,null,read);}
    static void configure(ReadRequest read,JSONObject desired) throws Exception {configure(false,new JSONObject(desired.toString()),read);}
    public static void configureUserSelection() throws Exception { configureUserSelection(config()); }
    public static void configureUserSelection(JSONObject desired) throws Exception { configureUserSelection(newReadRequest(),desired); }
    static void configureUserSelection(ReadRequest read,JSONObject desired) throws Exception {configure(true,new JSONObject(desired.toString()),read);}
    private static void configure(boolean explicit,JSONObject selection,ReadRequest read) throws Exception {
        JSONObject desired=selection==null?config():selection;
        requireCurrentSelection(read,selection);startRead(read);
        JSONObject current=readHttp(read,"/ec/state");
        if(!PROTOCOL.equals(current.optString("protocol")))throw new IOException("Нужен Bridge EventCore EC1; старый Bridge не подходит");
        if(read.profileTransition&&read.profileId.isEmpty()){
            publishSnapshot(read,current);read.profileId=current.optString("profile_id","");read.profileTransition=false;
        }
        if(!explicit&&(hasProfileDraft()||current.optJSONObject("campaign")!=null||current.optJSONObject("pending_config")!=null||current.optBoolean("auto",false))){
            publishSnapshot(read,current);return;
        }
        synchronized(STATE_READ_LOCK){requireSameSource(read);if(read.sequence<lastResetRead)return;requireCurrentSelection(read,selection);}
        JSONObject pending=current.optJSONObject("pending_config");
        if(configMatches(pending==null?current.optJSONObject("config"):pending,desired)){
            finishProfileSelection(read,explicit,desired,current,null);return;
        }
        JSONObject a=current.optJSONObject("account");
        if(a!=null&&!desired.optString("account_mode").equals(a.optString("type")))throw new IOException("Выбран "+desired.optString("account_mode")+", фактический MT5: "+a.optString("type")+". Новые входы остановлены; переключите счёт MT5 отдельно.");
        final CommandRequest request;
        synchronized(STATE_READ_LOCK){
            requireCurrentSelection(read,selection);
            JSONObject body=new JSONObject().put("config",desired).put("allow_deferred",true)
                .put("preserve_auto",explicit).put("accept_pending_profile",explicit).put("profile_id",read.profileId);
            if(a!=null)body.put("account_key",a.optString("key"));
            JSONObject capabilities=current.optJSONObject("capabilities");
            if(capabilities!=null&&capabilities.optBoolean("queued_controls"))body.put("control_protocol","queued-v1");
            request=prepareCommand("configure",body);
        }
        JSONObject result=sendCommand(request);
        requireSameSource(read);
        ReadRequest confirmation=new ReadRequest(read.source,read.token,read.sequence);
        confirmation.profileId=result.optString("profile_id",read.profileId);confirmation.profileTransition=explicit;
        startRead(confirmation);
        JSONObject refreshed=readHttp(confirmation,"/ec/state");
        if(PROTOCOL.equals(refreshed.optString("protocol")))finishProfileSelection(confirmation,explicit,desired,refreshed,result.optString("message"));
    }
    private static void finishProfileSelection(ReadRequest read,boolean explicit,JSONObject desired,JSONObject state,String message) throws Exception {
        synchronized(STATE_READ_LOCK){
            requireActiveRead();requireSameSource(read);if(read.sequence<lastPublishedRead)return;
            JSONObject draft=new JSONObject(prefs().getString("ec_profile_draft","{}"));
            if(explicit&&hasProfileDraft()&&!configMatches(draft,desired))return;
            JSONObject applied=state.optJSONObject("pending_config");if(applied==null)applied=state.optJSONObject("config");
            if(explicit&&configMatches(draft,desired)&&configMatches(applied,desired))prefs().edit().remove("ec_profile_draft").apply();
            publishSnapshot(read,state);
            SharedPreferences.Editor acknowledged=prefs().edit().putString("ec_config_sent",desired.toString());
            if(message!=null)acknowledged.putString("ec_message",message);acknowledged.apply();
        }
    }
    public static String profileLabel(JSONObject config){
        return config==null?"—":config.optString("symbol")+" · "+config.optString("timeframe")+" · "+config.optString("mode");
    }
    public static JSONObject poll() throws Exception {
        prefs().edit().putLong("state_last_attempt_ms",System.currentTimeMillis()).apply();
        ReadRequest read=newReadRequest();
        try{
            startRead(read);JSONObject s=readHttp(read,"/ec/state");
            if(!PROTOCOL.equals(s.optString("protocol")))throw new IOException("Нужен Bridge EventCore EC1; старый Bridge не подходит");
            return publishSnapshot(read,s)?s:state();
        }catch(Exception e){throw new ReadFailure(read,e);}
    }
    private static void requireActiveRead() throws InterruptedIOException {
        if(Thread.currentThread().isInterrupted())throw new InterruptedIOException("Обновление отменено");
    }
    private static JSONObject readHttp(ReadRequest read,String path) throws Exception {
        requireActiveRead();requireSameSource(read);
        String scoped=path;
        if(!read.profileId.isEmpty())scoped+=(path.contains("?")?"&":"?")+"profile_id="+java.net.URLEncoder.encode(read.profileId,"UTF-8");
        JSONObject value=http("GET",read.source+scoped,null,read.source,read.token);
        requireActiveRead();requireSameSource(read);return value;
    }
    /** Foreground view refresh, with no trading side effects. */
    static JSONObject readState(ReadRequest read) throws Exception {
        startRead(read);JSONObject snapshot=readHttp(read,"/ec/state");
        if(!PROTOCOL.equals(snapshot.optString("protocol")))throw new IOException("Нужен Bridge EventCore EC1; старый Bridge не подходит");
        return publishSnapshot(read,snapshot)?snapshot:state();
    }
    static JSONObject forecast(ReadRequest read,String frame) throws Exception {
        if(Timeframes.index(frame)<0)throw new IOException("Недоступный период просмотра");
        return readHttp(read,"/ec/forecast?tf="+frame);
    }
    private static JSONObject refreshPart(ReadRequest read,String path,String label,String required,JSONArray errors) throws Exception {
        requireActiveRead();requireSameSource(read);
        try{
            JSONObject value=readHttp(read,path);
            if(value.optJSONArray(required)==null)throw new IOException("Bridge не вернул данные");
            return value;
        }catch(Exception e){
            requireActiveRead();requireSameSource(read);errors.put(label+": "+String.valueOf(e.getMessage()));return null;
        }
    }
    /** Explicit read-only refresh; neither this path nor polling sends control commands. */
    public static JSONObject refreshAll() throws Exception {
        return refreshAll(newReadRequest());
    }
    static JSONObject refreshAll(ReadRequest read) throws Exception {return refreshSnapshot(read,true);}
    public static JSONObject refreshFinancial() throws Exception {return refreshSnapshot(newReadRequest(),false);}
    static JSONObject refreshFinancial(ReadRequest read) throws Exception {return refreshSnapshot(read,false);}
    private static JSONObject refreshSnapshot(ReadRequest read,boolean full) throws Exception {
            startRead(read);
            prefs().edit().putLong("state_last_attempt_ms",System.currentTimeMillis()).apply();
            JSONObject s=readHttp(read,full?"/ec/state?refresh=1":"/ec/state");
            long snapshotReceived=SystemClock.elapsedRealtime();
            if(!PROTOCOL.equals(s.optString("protocol")))throw new IOException("Нужен Bridge EventCore EC1; старый Bridge не подходит");
            JSONArray errors=s.optJSONArray("refresh_errors");if(errors==null)errors=new JSONArray();
            if(full&&!s.has("refresh_time"))errors.put("Bridge не подтвердил полное обновление; обновите Bridge");
            JSONObject recent=refreshPart(read,"/trade-ledger?days=30&limit=1000","История за 30 дней","trades",errors);
            JSONObject all=refreshPart(read,"/trade-ledger?days=3650&limit=1000","Полная история","trades",errors);
            JSONObject journal=full?refreshPart(read,"/ec/journal?limit=100","Журнал Bridge","events",errors):null;
            requireActiveRead();
            s.put("account_age",s.optDouble("account_age",999)+(SystemClock.elapsedRealtime()-snapshotReceived)/1000.0);
            s.put("refresh_errors",errors);
            synchronized(STATE_READ_LOCK){
            requireActiveRead();requireSameSource(read);
            publishSnapshot(read,s);
            JSONObject current=state(),account=current.optJSONObject("account"),readAccount=s.optJSONObject("account");
            boolean sameAccount=account!=null&&readAccount!=null&&account.optString("key").equals(readAccount.optString("key"));
            if(!sameAccount){errors.put("Счёт MT5 изменился; повторите обновление");return s;}
            if(read.sequence<lastAuxiliaryRead)return s;
            double historyTime=current.optDouble("history_time",0);
            String accountKey=account.optString("key");
            boolean recentCurrent=recent!=null&&recent.optDouble("history_time",0)>=historyTime&&(!recent.has("account_key")||accountKey.equals(recent.optString("account_key")));
            boolean allCurrent=all!=null&&all.optDouble("history_time",0)>=historyTime&&(!all.has("account_key")||accountKey.equals(all.optString("account_key")));
            if((recent!=null&&!recentCurrent)||(all!=null&&!allCurrent))errors.put("История изменилась во время обновления; повторите свайп");
            String currency=prefs().getString("mt5_currency_snapshot","USD");
            SharedPreferences.Editor editor=prefs().edit();
            if(recentCurrent)editor.putString("stats_snapshot",FeatureEngine.formatLedgerStats(recent))
                .putString("trade_log_snapshot",FeatureEngine.formatTradeLog(recent));
            if(allCurrent)editor.putString("trade_log_full_snapshot",FeatureEngine.formatFullTradeHistory(all,currency))
                .putString("money_realized_snapshot",FeatureEngine.formatRealizedMoneySummary(all,currency));
            if(!recentCurrent||!allCurrent)editor.putString("money_refresh_error","История обновлена не полностью");
            if(journal!=null)editor.putString("ec_journal_snapshot",formatJournal(journal.getJSONArray("events")));
            requireActiveRead();requireSameSource(read);editor.apply();lastAuxiliaryRead=read.sequence;return s;
            }
    }
    private static String formatJournal(JSONArray events){
        if(events.length()==0)return "ЖУРНАЛ BRIDGE: пока пусто";
        StringBuilder text=new StringBuilder("ЖУРНАЛ BRIDGE");
        java.text.SimpleDateFormat format=new java.text.SimpleDateFormat("dd.MM HH:mm:ss",Locale.US);
        for(int i=0;i<events.length();i++){
            JSONObject event=events.optJSONObject(i);if(event==null)continue;
            long time=(long)(event.optDouble("time",0)*1000);
            String kind=journalText(event,"kind",40);
            text.append('\n').append(time>0?format.format(new Date(time)):"—").append(" · ").append(kind.isEmpty()?"Событие":kind);
            JSONObject body=event.optJSONObject("body");
            if(body!=null){
                String detail=journalDetail(kind,body);
                if(!detail.isEmpty())text.append(": ").append(detail);
            }
        }
        return text.toString();
    }
    // Journal payloads can contain transport/account metadata. Only named scalar
    // presentation fields are allowed; never stringify arbitrary JSON objects.
    private static String journalText(JSONObject source,String key,int limit){
        Object value=source==null?null:source.opt(key);if(!(value instanceof String))return "";
        String text=((String)value).replaceAll("[\\p{Cntrl}\\s]+"," ").trim();
        String token=app==null?"":prefs().getString("ec_token","");
        if(!token.isEmpty())text=text.replace(token,"[скрыто]");
        text=text.replaceAll("(?i)\\bBearer\\s+[^\\s,;]+","Bearer [скрыто]")
            .replaceAll("(?i)\\b(token|authorization|api[_ -]?key|secret|password)\\s*[:=]\\s*[^\\s,;]+","$1=[скрыто]");
        return text.length()>limit?text.substring(0,limit-1)+"…":text;
    }
    private static String journalReason(JSONObject body){
        for(String key:new String[]{"message","reason","status"}){String value=journalText(body,key,240);if(!value.isEmpty())return value;}
        return "";
    }
    private static String journalDetail(String kind,JSONObject body){
        StringJoiner detail=new StringJoiner(" · ");
        JSONObject decision=body.optJSONObject("decision"),result=body.optJSONObject("result"),config=body.optJSONObject("config");
        JSONObject forecast=decision==null?null:decision.optJSONObject("forecast");
        if(config==null&&result!=null)config=result.optJSONObject("config");
        if("ANALYSIS".equals(kind)&&decision!=null){
            for(String key:new String[]{"signal","phase"}){String value=journalText(decision,key,32);if(!value.isEmpty())detail.add(value);}
        }else if("COMMAND".equals(kind)){
            String command=journalText(body,"command",40);if(!command.isEmpty())detail.add(command);
            if(result!=null){
                if(result.has("ok"))detail.add(result.optBoolean("ok")?"OK":"ОТКЛОНЕНО");
                if(result.has("auto"))detail.add(result.optBoolean("auto")?"AUTO ON":"AUTO OFF");
                if(result.optBoolean("paused"))detail.add("PAUSE");
            }
        }
        if("ANALYSIS".equals(kind)||"COMMAND".equals(kind)){
            String mode=journalText(body,"mode",12);if(mode.isEmpty())mode=journalText(config,"mode",12);
            String frame=journalText(body,"timeframe",12);if(frame.isEmpty())frame=journalText(config,"timeframe",12);
            if(frame.isEmpty())frame=journalText(forecast,"timeframe",12);
            if(!mode.isEmpty()||!frame.isEmpty())detail.add(mode+(mode.isEmpty()||frame.isEmpty()?"":" / ")+frame);
        }
        String reason="ANALYSIS".equals(kind)?journalReason(decision):"COMMAND".equals(kind)?journalReason(result):"";
        if(reason.isEmpty())reason=journalReason(body);if(!reason.isEmpty())detail.add(reason);
        return detail.toString();
    }
    static String moneySummary(JSONObject o){if(o==null)return "—";return String.format(Locale.US,"+%.2f / −%.2f · ИТОГ %+.2f USD · %d сдел.",o.optDouble("profit"),Math.abs(o.optDouble("loss")),o.optDouble("net"),o.optInt("count"));}
    public static void cache(JSONObject s) throws Exception {
        synchronized(STATE_READ_LOCK){cacheSnapshot(s);lastPublishedRead=++nextReadSequence;}
    }
    private static void cacheSnapshot(JSONObject s) throws Exception {
        SharedPreferences p=prefs();JSONObject a=s.optJSONObject("account"),d=s.optJSONObject("decision"),q=s.optJSONObject("quote"),cfg=s.optJSONObject("config"),rs=s.optJSONObject("risk"),fc=s.optJSONObject("forecast");
        if(a==null)a=new JSONObject();if(d==null)d=new JSONObject();if(cfg==null)cfg=new JSONObject();if(rs==null)rs=new JSONObject();if(fc==null)fc=new JSONObject();
        long now=System.currentTimeMillis();boolean connected=!a.isNull("balance")&&a.has("balance")&&s.optDouble("account_age",999)<10;
        boolean latch=s.optBoolean("emergency",false)||p.getBoolean("v108_emergency_latched",false);
        boolean auto=s.optBoolean("auto",false)&&!s.optBoolean("paused",true)&&!latch;
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
        boolean scenarioMap=fc.optInt("map_version",0)>=2||"UNCALIBRATED_SCORE".equals(fc.optString("model_weight_kind"));
        String forecastText=forecastAvailable?
            (scenarioMap?("SCENARIO MAP · веса: BUY "+up+" · SELL "+down+" · RANGE "+range+direction+" · не вероятность успеха"):
            ("LIVE FORECAST: UP "+up+"% · DOWN "+down+"% · RANGE "+range+"% · "+fc.optString("regime","RANGE")+direction)):
            "LIVE FORECAST: ожидаем достаточные данные";
        if(fc.optInt("map_version")>=3)forecastText=ScenarioUi.headlineForState(s);
        if(fc.optBoolean("late_entry",false))forecastText+=" · LATE ENTRY BLOCK";
        if(fc.optBoolean("exhaustion",false))forecastText+=" · EXHAUSTION";
        StringBuilder context=new StringBuilder("Вход: ").append(tf).append(" · Режим: ").append(cfg.optString("mode","NORMAL"))
            .append("\nЭтап: ").append(phaseName(phase)).append("\nПуть: ").append(pathName(path)).append("\n").append(why)
            .append("\n").append(forecastText)
            .append("\nРешение и исполнение: данные MT5");
        if(s.has("account_risk_budget"))context.append("\nОбщий бюджет риска счёта: ").append(String.format(Locale.US,"%.2f USD",s.optDouble("account_risk_budget")));
        if(campaign!=null)context.append("RECONCILING".equals(s.optString("campaign_state"))?
            "\nПозиций MT5 нет; сверяем завершение кампании: ":"\nОткрытая кампания: ").append(campaignSide);
        JSONObject pendingProfile=s.optJSONObject("pending_config");
        if(pendingProfile!=null)context.append("\nПосле кампании: ").append(profileLabel(pendingProfile));
        JSONObject gate=s.optJSONObject("entry_gate");
        if(gate!=null)context.append("\nНовые входы: ").append(gate.optString("reason"));
        JSONObject reversal=s.optJSONObject("reversal_status");
        if(reversal==null||reversal.length()==0)reversal=s.optJSONObject("pending_reversal");
        if(reversal!=null&&reversal.length()>0){
            int rsd=reversal.optInt("side",0);String status=reversal.optString("status","WAITING_CLOSE");
            String detail="WAITING_CLOSE".equals(status)?"проверяем закрытие прежней позиции и историю MT5":
                "WAITING_SIGNAL".equals(status)?"позиция закрыта; ждём подтверждение нового входа":
                "READY".equals(status)?"позиция закрыта; проверяем новый вход перед отправкой":
                "OPENED".equals(status)?"MT5 подтвердил новую позицию":
                "CANCELLED".equals(status)?"разворот отменён; новая заявка по нему не отправляется":"ожидаем проверку Bridge";
            context.append("\nРазворот ").append(status).append(": ").append(detail);
            if(rsd!=0)context.append(" → ").append(rsd>0?"BUY":"SELL");
            String reason=reversal.optString("reason","");if(!reason.isEmpty())context.append(". ").append(reason);
        }
        if(q!=null)context.append("\nВремя котировки: ").append(new java.text.SimpleDateFormat("HH:mm:ss",Locale.US).format(new Date(q.optLong("time_msc"))));
        JSONArray positions=s.optJSONArray("all_positions");int n=positions==null?0:positions.length();double floating=0;
        if(positions!=null)for(int i=0;i<positions.length();i++){JSONObject x=positions.getJSONObject(i);floating+=x.optDouble("profit")+x.optDouble("swap");}
        String risk=rs.optBoolean("allowed",false)?"RISK OK":"RISK BLOCK: "+rs.optJSONArray("blocks");
        SharedPreferences.Editor e=p.edit().putString("ec_state",s.toString()).putLong("ec_received_elapsed",SystemClock.elapsedRealtime())
            .putString("ec_state_source",base())
            .putBoolean("server_verified",true).putBoolean("mt5_connected_snapshot",connected)
            .putBoolean("auto_trading",auto).putBoolean("auto_user_enabled",auto).putBoolean("trading_paused",s.optBoolean("paused",true))
            .putString("bridge_version_snapshot",VERSION).putBoolean("bridge_version_match_snapshot",true).putBoolean("bridge_real_enabled_snapshot",s.optBoolean("real_armed",false))
            .putString("mt5_account_type_snapshot",a.optString("type","UNKNOWN")).putString("mt5_account_key_snapshot",a.optString("key",""))
            .putString("mt5_currency_snapshot",a.optString("currency","USD")).putString("fee_profile_snapshot",s.optJSONObject("fee_profile")==null?"{}":s.optJSONObject("fee_profile").toString())
            .putLong("mt5_balance_bits",Double.doubleToLongBits(a.optDouble("balance",Double.NaN)))
            .putLong("mt5_equity_bits",Double.doubleToLongBits(a.optDouble("equity",Double.NaN)))
            .putInt("mt5_positions_snapshot",n).putLong("mt5_floating_bits",Double.doubleToLongBits(floating))
            .putString("state_symbol",symbol).putString("state_tf",tf).putString("state_signal",sig).putString("state_campaign_side",campaignSide)
            .putString("state_context",context.toString()).putString("state_why",why).putString("state_forecast_text",forecastText)
            .putString("state_components",ScenarioUi.explanation(s))
            .putString("ec_runtime_build",s.optString("bridge_build","неизвестная сборка")+" · "+s.optString("runtime_revision",""))
            .putInt("state_quality",-1).putInt("state_api_count",0).putInt("state_cache_count",0)
            .putLong("state_signal_since_ms",since).putLong("state_last_update_ms",now).putLong("state_last_success_ms",(long)(s.optDouble("analysis_time",0)*1000))
            .putLong("state_entry_bits",Double.doubleToLongBits(q==null?Double.NaN:q.optDouble("bid",Double.NaN)))
            .putLong("state_sl_bits",Double.doubleToLongBits(d.optDouble("stop",0)>0?d.optDouble("stop"):Double.NaN))
            .putLong("state_tp1_bits",Double.doubleToLongBits(Double.NaN)).putLong("state_tp2_bits",Double.doubleToLongBits(Double.NaN))
            .putString("risk_snapshot",risk).putString("risk_detail_json",rs.toString()).putLong("smart_snapshot_ms",now)
            .putString("position_manager_status","Bridge EventCore · "+(campaign==null?"ожидание кампании":"сопровождение "+campaignSide+" · "+cfg.optString("mode")))
            .putString("bg_status",s.optString("execution",why));
        if(!p.getString("mt5_account_key_snapshot","").equals(a.optString("key","")))
            e.remove("trade_log_snapshot").remove("trade_log_full_snapshot").remove("stats_snapshot").remove("money_realized_snapshot");
        if(s.optBoolean("emergency",false))e.putBoolean("v108_emergency_latched",true);
        // Explicit local choices survive in-flight reads. Otherwise show Bridge's next
        // profile when queued, while state_* continues to describe the active campaign.
        JSONObject choice=s.optJSONObject("pending_config");if(choice==null)choice=cfg;
        boolean draftPending=hasProfileDraft();
        if(draftPending&&configMatches(choice,new JSONObject(p.getString("ec_profile_draft","{}")))){
            // A later read can confirm a command whose response was lost, or an
            // explicit AUTO enable that accepted this profile. Never clear a newer choice.
            e.remove("ec_profile_draft");draftPending=false;
        }
        if(!draftPending&&(s.optJSONObject("campaign")!=null||s.optJSONObject("pending_config")!=null||s.optBoolean("auto",false))){
            e.putInt("signal_mode_pos","SCALP".equalsIgnoreCase(choice.optString("mode"))?1:0)
                .putString("selected_symbol",choice.optString("symbol",symbol));
            Timeframes.project(e,choice.optString("timeframe","M5"));
            double riskPct=choice.optDouble("risk_pct",.25);
            e.putInt("risk_pos",riskPct>=1?2:riskPct>=.5?1:0);
        }
        if(s.optBoolean("history_ok",false))e.putString("money_realized_snapshot","Сегодня: "+moneySummary(s.optJSONObject("today"))+"\nВсего: "+moneySummary(s.optJSONObject("all"))).putString("money_refresh_error","");
        else e.putString("money_refresh_error",s.optString("history_error","История не обновлена"));
        String historyKey=phase+"|"+sig+"|"+why;
        boolean changed=!historyKey.equals(p.getString("ec_history_key",""));
        e.putString("ec_history_key",historyKey);e.apply();
        if(changed)FeatureEngine.appendSignalHistory(p,symbol,tf,sig,-1,phaseName(phase)+": "+why);
        ExecutionFeedback.record(p,symbol,tf,phase,s.optString("execution","—"));
    }
    public static void offline(Exception error){
        if(error instanceof ReadFailure){ReadFailure failure=(ReadFailure)error;offlineIfCurrent(failure.read,failure.original);return;}
        offlineSnapshot(error);
    }
    private static void offlineSnapshot(Exception error){prefs().edit().putBoolean("server_verified",false).putBoolean("mt5_connected_snapshot",false)
        .putString("bg_status","Нет связи: "+error.getMessage()).putString("ec_message",String.valueOf(error.getMessage()))
        .putString("risk_snapshot","Нет свежей проверки риска").apply();}
}
