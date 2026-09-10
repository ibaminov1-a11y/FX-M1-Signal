package com.openai.fxm1;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
import android.widget.RemoteViews;
import org.json.JSONObject;
import java.util.UUID;
import java.util.concurrent.*;

public class V11Service extends Service {
    public static final String UPDATE="com.openai.fxm1.V11_UPDATE";
    static final String CHANNEL="fxm1_v11_controls";
    static final int NOTIFICATION=11001;
    private final ScheduledExecutorService polling=Executors.newSingleThreadScheduledExecutor();
    private final ExecutorService commands=Executors.newSingleThreadExecutor();
    private final Handler main=new Handler(Looper.getMainLooper());
    private volatile boolean started=false;
    private long confirmUntil=0;
    private long lastHistory=0;
    private String lastNotice="";
    private long lastNoticeMs=0;
    @Override public void onCreate() {
        super.onCreate();
        NotificationManager nm=getSystemService(NotificationManager.class);
        NotificationChannel c=new NotificationChannel(CHANNEL,"Управление FX M1",NotificationManager.IMPORTANCE_LOW);
        c.setDescription("PLAY, PAUSE и аварийная остановка DEMO-бота"); c.setShowBadge(false);
        c.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC); nm.createNotificationChannel(c);
        nm.cancel(4101); nm.cancel(4102); nm.cancel(4103);
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        if(!started) {
            started=true;
            Notification n=notification();
            if(Build.VERSION.SDK_INT>=34) startForeground(NOTIFICATION,n,ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            else startForeground(NOTIFICATION,n);
            polling.scheduleWithFixedDelay(this::poll,0,2,TimeUnit.SECONDS);
        }
        String action=intent==null?"START":intent.getAction();
        if("EMERGENCY".equals(action)) {
            long now=SystemClock.elapsedRealtime();
            if(now<=confirmUntil) emergency();
            else {
                confirmUntil=now+2500;
                V11Api.prefs(this).edit().putString("command_message","EMERGENCY: нажмите ещё раз за 2,5 сек").apply();
                notifyNow();
                main.postDelayed(()-> { if(SystemClock.elapsedRealtime()>confirmUntil) { confirmUntil=0; notifyNow(); } },2700);
            }
        } else if("EMERGENCY_CONFIRMED".equals(action)) emergency();
        else if("PLAY".equals(action)) enqueue("play",new JSONObject());
        else if("PAUSE".equals(action)) enqueue("pause",new JSONObject());
        else if("COMMAND".equals(action) && intent!=null) {
            try { enqueue(intent.getStringExtra("command"),new JSONObject(intent.getStringExtra("body"))); }
            catch(Exception e) { message(V11Api.error(e)); }
        }
        return START_STICKY;
    }
    private void emergency() {
        confirmUntil=0;
        String id=UUID.randomUUID().toString();
        V11Api.prefs(this).edit().putBoolean("local_emergency",true).putString("pending_emergency",id)
                .putString("command_message","EMERGENCY: отправка; закрытие ещё не подтверждено").commit();
        notifyNow(); commands.execute(this::sendEmergency);
    }
    private void sendEmergency() {
        String id=V11Api.prefs(this).getString("pending_emergency","");
        if(id.isEmpty()) return;
        try {
            JSONObject b=new JSONObject(); b.put("id",id);
            V11Api.request(this,"POST","/v11/command/emergency",b);
            V11Api.prefs(this).edit().putString("pending_emergency","")
                    .putString("command_message","Emergency принят Bridge; проверяем закрытие").apply();
        } catch(Exception e) { message("EMERGENCY не подтверждён: "+V11Api.error(e)); }
    }
    private void enqueue(String cmd,JSONObject b) {
        final long created=SystemClock.elapsedRealtime();
        final long generation=V11Api.state(this).optLong("generation",-1);
        commands.execute(()-> {
            try {
                boolean localStop=V11Api.prefs(this).getBoolean("local_emergency",false);
                if(("play".equals(cmd)||"enable".equals(cmd)) && (localStop||SystemClock.elapsedRealtime()-created>5000))
                    throw new Exception("Входы заблокированы или команда устарела");
                b.put("id",UUID.randomUUID().toString()); b.put("generation",generation);
                JSONObject state=V11Api.state(this);
                double server=state.optDouble("server_time",0);
                long received=V11Api.prefs(this).getLong("received_elapsed",0);
                b.put("expires",server+(SystemClock.elapsedRealtime()-received)/1000.0+8);
                V11Api.request(this,"POST","/v11/command/"+cmd,b);
                if("reset".equals(cmd)) V11Api.prefs(this).edit().putBoolean("local_emergency",false).putString("pending_emergency","").commit();
                message("Команда принята: "+cmd);
                lastHistory=0;
            } catch(Exception e) { message(V11Api.error(e)); }
        });
    }
    private void poll() {
        try {
            if(!V11Api.prefs(this).getString("pending_emergency","").isEmpty()) {
                sendEmergency();
                if(!V11Api.prefs(this).getString("pending_emergency","").isEmpty()) { notifyNow(); return; }
            }
            JSONObject s=V11Api.request(this,"GET","/v11/state",null);
            V11Api.prefs(this).edit().putString("state",s.toString()).putBoolean("online",true)
                    .putLong("received_elapsed",SystemClock.elapsedRealtime()).putLong("received_wall",System.currentTimeMillis())
                    .putString("network_error","").apply();
            if(s.optBoolean("emergency",false)) V11Api.prefs(this).edit().putBoolean("local_emergency",true).apply();
            long now=SystemClock.elapsedRealtime();
            if(now-lastHistory>5000) {
                try {
                    JSONObject history=V11Api.request(this,"GET","/v11/history?limit=200",null);
                    V11Api.prefs(this).edit().putString("history",history.toString()).apply(); lastHistory=now;
                } catch(Exception e) { V11Api.prefs(this).edit().putString("history_error",V11Api.error(e)).apply(); }
            }
        } catch(Exception e) {
            V11Api.prefs(this).edit().putBoolean("online",false).putString("network_error",V11Api.error(e)).apply();
        }
        sendBroadcast(new Intent(UPDATE).setPackage(getPackageName())); notifyNow();
    }
    private void message(String m) {
        V11Api.prefs(this).edit().putString("command_message",m).apply();
        sendBroadcast(new Intent(UPDATE).setPackage(getPackageName())); notifyNow();
    }
    private PendingIntent action(String a,int request) {
        Intent i=new Intent(this,V11Service.class).setAction(a);
        return PendingIntent.getForegroundService(this,request,i,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
    }
    Notification notification() {
        JSONObject s=V11Api.state(this);
        boolean online=V11Api.prefs(this).getBoolean("online",false);
        boolean emergency=V11Api.prefs(this).getBoolean("local_emergency",false)||s.optBoolean("emergency",false);
        String status=emergency?"EMERGENCY":(!online?"НЕТ СВЯЗИ":(!s.optBoolean("auto",false)?"AUTO OFF":s.optBoolean("paused",true)?"PAUSE":"PLAY"));
        String subtitle=s.optString("symbol","EUR/USD")+" · DEMO · "+status;
        if(confirmUntil>SystemClock.elapsedRealtime()) subtitle="EMERGENCY: нажмите ещё раз за 2,5 сек";
        String reason=online?s.optString("reason","Ожидание MT5"):V11Api.prefs(this).getString("network_error","Настройте Bridge V11");
        RemoteViews compact=new RemoteViews(getPackageName(),R.layout.v11_notification_compact);
        RemoteViews expanded=new RemoteViews(getPackageName(),R.layout.v11_notification_expanded);
        PendingIntent play=action("PLAY",1101),pause=action("PAUSE",1102),stop=action("EMERGENCY",1103);
        for(RemoteViews v:new RemoteViews[]{compact,expanded}) {
            v.setTextViewText(R.id.n_status,subtitle);
            v.setOnClickPendingIntent(R.id.n_play,play); v.setOnClickPendingIntent(R.id.n_pause,pause); v.setOnClickPendingIntent(R.id.n_stop,stop);
        }
        expanded.setTextViewText(R.id.n_reason,V11Activity.colorizeSides(reason));
        Intent open=new Intent(this,V11Activity.class).setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent openPi=PendingIntent.getActivity(this,1100,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this,CHANNEL).setSmallIcon(R.drawable.ic_stat_fx)
                .setColor(V11Activity.BLUE).setContentTitle("FX M1 · V11").setContentText(subtitle).setContentIntent(openPi)
                .setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false).setCategory(Notification.CATEGORY_SERVICE)
                .setVisibility(Notification.VISIBILITY_PUBLIC).setStyle(new Notification.DecoratedCustomViewStyle())
                .setCustomContentView(compact).setCustomBigContentView(expanded).build();
    }
    private void notifyNow() {
        main.post(()-> {
            if(!started) return;
            JSONObject s=V11Api.state(this);
            String signature=s.optString("reason")+s.optString("auto")+s.optString("paused")+s.optString("emergency")+
                    V11Api.prefs(this).getBoolean("online",false)+V11Api.prefs(this).getBoolean("local_emergency",false)+confirmUntil+
                    V11Api.prefs(this).getString("network_error","");
            long now=SystemClock.elapsedRealtime();
            if(signature.equals(lastNotice)&&now-lastNoticeMs<15000) return;
            getSystemService(NotificationManager.class).notify(NOTIFICATION,notification()); lastNotice=signature; lastNoticeMs=now;
        });
    }
    @Override public void onDestroy() {
        started=false; polling.shutdownNow(); commands.shutdownNow(); main.removeCallbacksAndMessages(null);
        V11Api.prefs(this).edit().putBoolean("online",false).apply();
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent i) { return null; }
}
