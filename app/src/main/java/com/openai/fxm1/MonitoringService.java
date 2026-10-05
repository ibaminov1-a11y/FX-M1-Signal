package com.openai.fxm1;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.graphics.Color;
import android.os.*;
import org.json.JSONObject;
import java.util.concurrent.*;

/** Foreground client only. The independent Bridge owns every trading decision. */
public class MonitoringService extends Service {
    public static final String ACTION_START="com.openai.fxm1.action.START_MONITORING";
    public static final String ACTION_STOP="com.openai.fxm1.action.STOP_MONITORING";
    public static final String ACTION_EMERGENCY="com.openai.fxm1.action.EMERGENCY_STOP";
    public static final String ACTION_EMERGENCY_CONFIRMED="com.openai.fxm1.action.EMERGENCY_CONFIRMED";
    public static final String ACTION_REFRESH="com.openai.fxm1.action.REFRESH_MONITORING";
    public static final String ACTION_STOP_ALL="com.openai.fxm1.action.STOP_ALL";
    public static final String ACTION_POWER_OFF="com.openai.fxm1.action.POWER_OFF_BACKGROUND";
    private static final int ID=4101;
    private static final String CHANNEL="fx_monitor_controls_v73";
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService io=Executors.newSingleThreadExecutor();
    private final ExecutorService emergencyIo=Executors.newSingleThreadExecutor();
    private boolean running=false,busy=false,emergencyInFlight=false;
    private SharedPreferences prefs(){return getSharedPreferences("fxm1",MODE_PRIVATE);}
    private final Runnable tick=new Runnable(){public void run(){if(!running)return;if(prefs().getBoolean("ec_emergency_pending",false))issueEmergency();if(!busy){busy=true;io.execute(()->{
        try{EventClient.poll();}
        catch(Exception e){EventClient.offline(e);}finally{handler.post(()->{busy=false;notifyState();if(running)handler.postDelayed(tick,1000);});}
    });}else handler.postDelayed(this,1000);}};
    @Override public void onCreate(){super.onCreate();EventClient.init(this);NotificationChannel c=new NotificationChannel(CHANNEL,"FX M1 Bot · мониторинг",NotificationManager.IMPORTANCE_HIGH);c.setSound(null,null);c.enableVibration(false);getSystemService(NotificationManager.class).createNotificationChannel(c);}
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        String action=intent==null?ACTION_START:intent.getAction();
        if(ACTION_STOP.equals(action)||ACTION_POWER_OFF.equals(action)){
            running=false;prefs().edit().putBoolean("bg_running",false).apply();handler.removeCallbacks(tick);
            stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();return START_NOT_STICKY;
        }
        running=true;
        if(!notifyState()){
            running=false;prefs().edit().putBoolean("bg_running",false).apply();
            stopSelf(startId);return START_NOT_STICKY;
        }
        // Consumers may stop immediately after observing this acknowledgement.
        // Publish it only after Android has completed foreground promotion.
        prefs().edit().putBoolean("bg_running",true).putLong("monitor_stopped_ms",0).apply();
        if(ACTION_EMERGENCY_CONFIRMED.equals(action)||ACTION_STOP_ALL.equals(action))emergency();
        // Monitoring and refresh are read-only. Only an explicit profile choice configures Bridge.
        handler.removeCallbacks(tick);handler.post(tick);return START_STICKY;
    }
    private void emergency(){prefs().edit().putBoolean("v108_emergency_latched",true).putBoolean("ec_emergency_pending",true)
        .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).putString("ec_message","Аварийная блокировка телефона сохранена; ожидается Bridge").commit();
        try{if(!prefs().contains("ec_emergency_request"))EventClient.beginEmergency();}
        catch(Exception e){prefs().edit().putString("ec_message",String.valueOf(e.getMessage())).apply();}
        issueEmergency();notifyState();}
    private void issueEmergency(){
        if(emergencyInFlight)return;
        final EventClient.CommandRequest request;
        try{request=EventClient.pendingEmergency();}catch(Exception e){prefs().edit().putString("ec_message",String.valueOf(e.getMessage())).apply();return;}
        emergencyInFlight=true;
        emergencyIo.execute(()->{try{JSONObject r=EventClient.sendCommand(request);
            prefs().edit().putString("ec_message",r.optString("message")).apply();}
            catch(Exception e){prefs().edit().putString("ec_message",String.valueOf(e.getMessage())).apply();}
            finally{handler.post(()->{emergencyInFlight=false;notifyState();});}});
    }
    private boolean notifyState(){if(!running)return false;JSONObject s=EventClient.state(),d=s.optJSONObject("decision"),cfg=s.optJSONObject("config"),fc=s.optJSONObject("forecast");
        String signal=d==null?"WAIT":d.optString("signal","WAIT");
        String symbol=cfg==null?"MT5":cfg.optString("symbol","MT5");
        String engine=cfg==null?"COMPUTE V1":cfg.optString("engine_mode","COMPUTE_V1");
        boolean emergency=prefs().getBoolean("v108_emergency_latched",false)||s.optBoolean("emergency",false);
        String state=emergency?(prefs().getBoolean("ec_emergency_pending",false)?"EMERGENCY · ожидается Bridge":"EMERGENCY"):
            s.optBoolean("client_offline",false)?"КЭШ · нет связи с Bridge":s.optBoolean("auto",false)&&!s.optBoolean("paused",true)?"AUTO ON":"AUTO OFF";
        String confidence="";
        if(fc!=null&&fc.optInt("side",0)!=0)confidence=" · "+(fc.optInt("side")>0?"BUY ":"SELL ")+"вес "+Math.round(fc.optDouble("confidence",0)*100);
        String timeframe=cfg==null?"M5":cfg.optString("timeframe","M5");
        String mode=cfg==null?EventClient.mode():cfg.optString("mode","NORMAL");
        String core=symbol+" · "+timeframe+" · "+mode+" · "+engine+" · "+signal+confidence;
        String detail=prefs().getString("ec_message",s.optString("execution","Подключение к Bridge"));
        PendingIntent open=PendingIntent.getActivity(this,100,new Intent(this,MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification.BigTextStyle style=new Notification.BigTextStyle().bigText(core+"\n"+detail);
        Notification.Builder b=new Notification.Builder(this,CHANNEL).setSmallIcon(R.drawable.ic_stat_fx).setColor(0xff914dff)
            .setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false).setContentTitle("FX M1 · "+state)
            .setContentText(core).setSubText("Информационное уведомление").setContentIntent(open)
            .setVisibility(Notification.VISIBILITY_PUBLIC).setStyle(style);
        if(Build.VERSION.SDK_INT>=31)b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        try{if(Build.VERSION.SDK_INT>=34)startForeground(ID,b.build(),ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);else startForeground(ID,b.build());}
        catch(Exception e){prefs().edit().putString("ec_message","Уведомление: "+e.getMessage()).apply();return false;}
        return true;
    }
    @Override public IBinder onBind(Intent i){return null;}
    @Override public void onDestroy(){running=false;prefs().edit().putBoolean("bg_running",false).apply();handler.removeCallbacksAndMessages(null);io.shutdownNow();emergencyIo.shutdown();super.onDestroy();}
}
