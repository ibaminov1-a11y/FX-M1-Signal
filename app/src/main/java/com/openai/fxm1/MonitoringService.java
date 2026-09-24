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
    private boolean running=false,busy=false;
    private SharedPreferences prefs(){return getSharedPreferences("fxm1",MODE_PRIVATE);}
    private final Runnable tick=new Runnable(){public void run(){if(!running)return;if(!busy){busy=true;io.execute(()->{
        try{if(prefs().getBoolean("ec_emergency_pending",false)){EventClient.command("emergency",new JSONObject());prefs().edit().putBoolean("ec_emergency_pending",false).apply();}JSONObject state=EventClient.poll();if(EventClient.needsConfigure(state))EventClient.configure();}
        catch(Exception e){EventClient.offline(e);}finally{handler.post(()->{busy=false;notifyState();if(running)handler.postDelayed(tick,1000);});}
    });}else handler.postDelayed(this,1000);}};
    @Override public void onCreate(){super.onCreate();EventClient.init(this);NotificationChannel c=new NotificationChannel(CHANNEL,"FX M1 Bot · мониторинг",NotificationManager.IMPORTANCE_HIGH);c.setSound(null,null);c.enableVibration(false);getSystemService(NotificationManager.class).createNotificationChannel(c);}
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        String action=intent==null?ACTION_START:intent.getAction();
        if(ACTION_STOP.equals(action)||ACTION_POWER_OFF.equals(action)){
            running=false;prefs().edit().putBoolean("bg_running",false).apply();handler.removeCallbacks(tick);
            stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();return START_NOT_STICKY;
        }
        running=true;prefs().edit().putBoolean("bg_running",true).putLong("monitor_stopped_ms",0).apply();notifyState();
        if(ACTION_EMERGENCY_CONFIRMED.equals(action)||ACTION_STOP_ALL.equals(action))emergency();
        else if(ACTION_REFRESH.equals(action)||ACTION_START.equals(action))io.execute(()->{
            try{EventClient.configure();}catch(Exception e){prefs().edit().putString("ec_message",String.valueOf(e.getMessage())).apply();}
        });
        handler.removeCallbacks(tick);handler.post(tick);return START_STICKY;
    }
    private void emergency(){prefs().edit().putBoolean("v108_emergency_latched",true).putBoolean("ec_emergency_pending",true)
        .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).putString("ec_message","Аварийная блокировка телефона сохранена; ожидается Bridge").commit();issue("emergency",true);notifyState();}
    private void issue(String command,boolean clearPending){
        final JSONObject envelope;
        try{envelope=EventClient.envelope(new JSONObject());}catch(Exception e){EventClient.offline(e);return;}
        io.execute(()->{try{JSONObject r=EventClient.http("POST",EventClient.base()+"/ec/command/"+command,envelope);
            SharedPreferences.Editor ed=prefs().edit().putString("ec_message",r.optString("message"));if(clearPending)ed.putBoolean("ec_emergency_pending",false);ed.apply();EventClient.poll();}
            catch(Exception e){prefs().edit().putString("ec_message",String.valueOf(e.getMessage())).apply();}
            finally{handler.post(this::notifyState);}});
    }
    private void notifyState(){if(!running)return;JSONObject s=EventClient.state(),d=s.optJSONObject("decision"),cfg=s.optJSONObject("config"),fc=s.optJSONObject("forecast");
        String signal=d==null?"WAIT":d.optString("signal","WAIT");
        String symbol=cfg==null?"MT5":cfg.optString("symbol","MT5");
        String engine=cfg==null?"COMPUTE V1":cfg.optString("engine_mode","COMPUTE_V1");
        boolean emergency=prefs().getBoolean("v108_emergency_latched",false)||s.optBoolean("emergency",false);
        String state=emergency?"EMERGENCY":s.optBoolean("auto",false)&&!s.optBoolean("paused",true)?"AUTO ON":"AUTO OFF";
        String confidence="";
        if(fc!=null&&fc.optInt("side",0)!=0)confidence=" · "+(fc.optInt("side")>0?"BUY ":"SELL ")+Math.round(fc.optDouble("confidence",0)*100)+"%";
        String core=symbol+" · M5 · "+engine+" · "+signal+confidence;
        String detail=prefs().getString("ec_message",s.optString("execution","Подключение к Bridge"));
        PendingIntent open=PendingIntent.getActivity(this,100,new Intent(this,MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification.BigTextStyle style=new Notification.BigTextStyle().bigText(core+"\n"+detail);
        Notification.Builder b=new Notification.Builder(this,CHANNEL).setSmallIcon(R.drawable.ic_stat_fx).setColor(0xff914dff)
            .setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false).setContentTitle("FX M1 · "+state)
            .setContentText(core).setSubText("Информационное уведомление").setContentIntent(open)
            .setVisibility(Notification.VISIBILITY_PUBLIC).setStyle(style);
        if(Build.VERSION.SDK_INT>=31)b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        try{if(Build.VERSION.SDK_INT>=34)startForeground(ID,b.build(),ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);else startForeground(ID,b.build());}
        catch(Exception e){prefs().edit().putString("ec_message","Уведомление: "+e.getMessage()).apply();}
    }
    @Override public IBinder onBind(Intent i){return null;}
    @Override public void onDestroy(){running=false;handler.removeCallbacksAndMessages(null);io.shutdown();super.onDestroy();}
}
