package com.openai.fxm1;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.graphics.Color;
import android.os.*;
import android.widget.RemoteViews;
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
    public static final String ACTION_PAUSE="com.openai.fxm1.action.PAUSE_BACKGROUND";
    public static final String ACTION_RESUME="com.openai.fxm1.action.RESUME_BACKGROUND";
    public static final String ACTION_POWER_OFF="com.openai.fxm1.action.POWER_OFF_BACKGROUND";
    public static final String ACTION_APPROVE_TRADE="com.openai.fxm1.action.APPROVE_TRADE";
    public static final String ACTION_REJECT_TRADE="com.openai.fxm1.action.REJECT_TRADE";
    private static final int ID=4101;
    private static final String CHANNEL="fx_monitor_controls_v73";
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService io=Executors.newSingleThreadExecutor();
    private boolean running=false,busy=false;
    private long confirmUntil=0;
    private SharedPreferences prefs(){return getSharedPreferences("fxm1",MODE_PRIVATE);}
    private final Runnable tick=new Runnable(){public void run(){if(!running)return;if(!busy){busy=true;io.execute(()->{
        try{if(prefs().getBoolean("ec_emergency_pending",false)){EventClient.command("emergency",new JSONObject());prefs().edit().putBoolean("ec_emergency_pending",false).apply();}EventClient.poll();}
        catch(Exception e){EventClient.offline(e);}finally{handler.post(()->{busy=false;notifyState();if(running)handler.postDelayed(tick,1000);});}
    });}else handler.postDelayed(this,1000);}};
    @Override public void onCreate(){super.onCreate();EventClient.init(this);NotificationChannel c=new NotificationChannel(CHANNEL,"FX M1 Bot · мониторинг",NotificationManager.IMPORTANCE_HIGH);c.setSound(null,null);c.enableVibration(false);getSystemService(NotificationManager.class).createNotificationChannel(c);}
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        String action=intent==null?ACTION_START:intent.getAction();
        if(ACTION_STOP.equals(action)||ACTION_POWER_OFF.equals(action)){
            issue("pause",false);running=false;prefs().edit().putBoolean("bg_running",false).apply();handler.removeCallbacks(tick);stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();return START_NOT_STICKY;
        }
        running=true;prefs().edit().putBoolean("bg_running",true).putLong("monitor_stopped_ms",0).apply();notifyState();
        if(ACTION_PAUSE.equals(action))issue("pause",false);
        else if(ACTION_RESUME.equals(action)){
            if(!prefs().getBoolean("v108_emergency_latched",false))issue("play",false);
            else prefs().edit().putString("ec_message","EMERGENCY: PLAY не снимает блокировку").apply();
        } else if(ACTION_EMERGENCY.equals(action)){
            long now=SystemClock.elapsedRealtime();
            if(now<=confirmUntil&&confirmUntil>0){confirmUntil=0;emergency();}
            else{confirmUntil=now+2500;prefs().edit().putString("ec_message","EMERGENCY: нажмите ещё раз в течение 2,5 секунд").apply();notifyState();}
        } else if(ACTION_EMERGENCY_CONFIRMED.equals(action)||ACTION_STOP_ALL.equals(action))emergency();
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
    private PendingIntent action(String action,int code){Intent i=new Intent(this,MonitoringService.class).setAction(action);return PendingIntent.getService(this,code,i,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    private void notifyState(){if(!running)return;JSONObject s=EventClient.state(),d=s.optJSONObject("decision"),cfg=s.optJSONObject("config");
        String signal=d==null?"WAIT":d.optString("signal","WAIT");String core=(cfg==null?"MT5":cfg.optString("symbol")+" · "+cfg.optString("timeframe")+" · "+cfg.optString("mode"))+" · "+signal;
        boolean emergency=prefs().getBoolean("v108_emergency_latched",false);String label=emergency?"EMERGENCY":s.optBoolean("paused",true)?"PAUSE":s.optBoolean("auto",false)?"PLAY":"AUTO OFF";
        String detail=SystemClock.elapsedRealtime()<confirmUntil?"Нажмите EMERGENCY ещё раз для подтверждения":prefs().getString("ec_message",s.optString("execution","Подключение к EventCore"));
        RemoteViews small=new RemoteViews(getPackageName(),R.layout.notification_monitoring_compact),large=new RemoteViews(getPackageName(),R.layout.notification_monitoring_expanded);
        for(RemoteViews r:new RemoteViews[]{small,large}){r.setOnClickPendingIntent(R.id.notifPlay,action(ACTION_RESUME,101));r.setOnClickPendingIntent(R.id.notifPause,action(ACTION_PAUSE,102));r.setOnClickPendingIntent(R.id.notifEmergency,action(ACTION_EMERGENCY,103));}
        large.setTextViewText(R.id.notifCore,core);large.setTextViewText(R.id.notifConnection,detail);
        large.setTextColor(R.id.notifCore,"BUY".equals(signal)?0xff42d67a:"SELL".equals(signal)?0xffff4857:0xffb0aac7);
        PendingIntent open=PendingIntent.getActivity(this,100,new Intent(this,MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b=new Notification.Builder(this,CHANNEL).setSmallIcon(R.drawable.ic_stat_fx).setColor(0xff914dff).setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false)
            .setContentTitle("FX M1 EC1 · "+label).setContentText(core).setContentIntent(open).setVisibility(Notification.VISIBILITY_PUBLIC)
            .setStyle(new Notification.DecoratedCustomViewStyle()).setCustomContentView(small).setCustomBigContentView(large);
        if(Build.VERSION.SDK_INT>=31)b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        try{if(Build.VERSION.SDK_INT>=34)startForeground(ID,b.build(),ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);else startForeground(ID,b.build());}
        catch(Exception e){prefs().edit().putString("ec_message","Уведомление: "+e.getMessage()).apply();}
    }
    @Override public IBinder onBind(Intent i){return null;}
    @Override public void onDestroy(){running=false;handler.removeCallbacksAndMessages(null);io.shutdown();super.onDestroy();}
}
