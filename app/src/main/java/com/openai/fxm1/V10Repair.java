package com.openai.fxm1;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Presentation and explicit recovery. This class never sends orders. */
public final class V10Repair {
    private V10Repair() {}
    public static String qualityDetails(String candidate,int h2,int h1,int entry,int fast,int structure,int breakout,int pattern) {
        if ("WAIT".equals(candidate)) {
            int alignment=Math.abs(h2+h1+entry+fast)*7, st=structure!=0?5:0, br=breakout!=0?8:0;
            int raw=25+alignment+st+br;
            return "Без направления: база 25 + согласование "+alignment+" + структура "+st+" + пробой "+br+
                " = "+raw+"; предел 59 → "+Math.min(59,raw)+"/100. Не вероятность прибыли.";
        }
        int d="BUY".equals(candidate)?1:-1;
        int a=h2==d?8:0,b=h1==d?8:0,c=entry==d?8:0,e=fast==d?4:0,f=structure==d?5:0;
        int g=breakout==2*d?7:breakout==d?4:0,p=Math.max(0,pattern*d)*5;
        int raw=60+a+b+c+e+f+g+p;
        return "Сценарий "+candidate+": база 60 + старший ТФ "+a+" + средний ТФ "+b+" + вход "+c+
            " + быстрый ТФ "+e+" + структура "+f+" + пробой "+g+" + паттерн "+p+
            " = "+raw+"; предел 100 → "+Math.min(100,raw)+"/100. Подтверждение входа — отдельно. Не вероятность прибыли.";
    }
    public static boolean sessionAllowed(String allowed,String current) {
        if(allowed==null||current==null)return false;
        for(String c:current.split("\\+"))for(String a:allowed.split(","))
            if(!a.trim().isEmpty()&&a.trim().equals(c.trim()))return true;
        return false;
    }
    public static String sessionBlock(SharedPreferences p) {
        if(!p.getBoolean("session_filter_enabled",false))return "";
        String now=FeatureEngine.currentSession(),allowed=p.getString("allowed_sessions","LONDON,NEW_YORK");
        return sessionAllowed(allowed,now)?"":"Сессия "+now+" запрещена фильтром. Разрешены: "+allowed;
    }
    public static void record(SharedPreferences p,String stage,String detail,String symbol,String tf) {
        p.edit().putString("execution_stage",stage).putString("execution_detail",detail)
            .putString("execution_symbol",symbol).putString("execution_tf",tf)
            .putLong("execution_stamp",System.currentTimeMillis()).apply();
    }
    public static void response(SharedPreferences p,JSONObject r,String symbol,String tf) {
        int code=r.optInt("retcode",0);
        boolean filled=r.optBoolean("accepted",false)&&(code==10009||code==10010)&&
            (r.optLong("deal",0)>0||r.optLong("ticket",0)>0);
        String detail=filled?(code==10010?"MT5 подтвердил частичное исполнение":"MT5 подтвердил исполнение")+
            " · ордер #"+r.optLong("ticket",0)+" · сделка #"+r.optLong("deal",0)
            :r.optString("message","Подтверждения исполнения MT5 нет");
        record(p,filled?"CONFIRMED":r.optBoolean("pending_approval",false)?"PENDING":"REJECTED",detail,symbol,tf);
        if(r.optJSONObject("risk_state")!=null)saveRisk(p,r.optJSONObject("risk_state"));
    }
    public static void failure(SharedPreferences p,Exception e,String symbol,String tf) {
        String m=e.getMessage()==null?e.getClass().getSimpleName():e.getMessage();int start=m.indexOf('{');
        if(m.startsWith("HTTP ")&&start>=0)try{
            JSONObject r=new JSONObject(m.substring(start));
            if(r.has("accepted")&&!r.optBoolean("accepted",true)){response(p,r,symbol,tf);return;}
        }catch(Exception ignored){}
        record(p,"UNKNOWN",m,symbol,tf);
    }
    public static void saveRisk(SharedPreferences p,JSONObject r) {
        p.edit().putString("risk_state_json",r.toString()).putLong("risk_checked_ms",System.currentTimeMillis())
            .putString("risk_snapshot",r.optBoolean("allowed",false)?"RISK OK":riskText(r)).apply();
    }
    public static void fetchRisk(SharedPreferences p,String base) {
        if(base.isEmpty())return;
        try {saveRisk(p,FeatureEngine.httpJson("GET",base+"/risk-state?daily_loss_limit_pct="+p.getFloat("daily_loss_limit_pct",3f)+
            "&max_drawdown_pct="+p.getFloat("max_drawdown_pct",5f)+"&max_consecutive_losses="+p.getInt("max_consecutive_losses",3),null));}
        catch(Exception e){try{saveRisk(p,new JSONObject().put("allowed",false).put("blocks",new JSONArray().put("RISK_UNAVAILABLE"))
            .put("message",e.getMessage()==null?"Нет ответа Bridge":e.getMessage()));}catch(Exception ignored){}}
    }
    public static String riskText(JSONObject r) {
        JSONArray blocks=r.optJSONArray("blocks");StringBuilder b=new StringBuilder();
        if(blocks!=null)for(int i=0;i<blocks.length();i++){
            if(b.length()>0)b.append("; ");String k=blocks.optString(i);
            if("LOSS_STREAK".equals(k))b.append("Серия убытков ").append(r.optInt("consecutive_losses",0)).append("/").append(r.optInt("streak_limit",3)).append(" · проверка в настройках");
            else if("DAILY_LOSS".equals(k))b.append("Дневной лимит убытка");
            else if("DRAWDOWN".equals(k))b.append("Лимит просадки");
            else b.append(k);
        }
        if(!r.optString("message","").isEmpty())b.append(b.length()>0?" · ":"").append(r.optString("message"));
        return b.length()==0?(r.optBoolean("allowed",false)?"Ограничения риска не сработали":"Риск ещё не подтверждён"):b.toString();
    }
    public static String display(SharedPreferences p,String symbol,String tf,String why) {
        StringBuilder b=new StringBuilder("АНАЛИЗ: ").append(why==null||why.isEmpty()?"Нет свежего анализа":why);
        boolean relevant=symbol.equals(p.getString("execution_symbol",""))&&tf.equals(p.getString("execution_tf",""));
        String stage=relevant?p.getString("execution_stage",""):"",detail=relevant?p.getString("execution_detail",""):"Для этих параметров запрос ещё не отправлялся";
        String label="CONFIRMED".equals(stage)?"Последнее подтверждение MT5":"SENT".equals(stage)?"Ожидается ответ Bridge":
            "UNKNOWN".equals(stage)?"Результат неизвестен — проверьте MT5":"REJECTED".equals(stage)?"Исполнение не подтверждено Bridge":"PENDING".equals(stage)?"Требуется подтверждение пользователя":"Запрос не отправлен";
        b.append("\n\nИСПОЛНЕНИЕ: ").append(label).append("\n").append(detail);
        long stamp=p.getLong("execution_stamp",0L);
        if(relevant&&stamp>0)b.append(" · ").append(new SimpleDateFormat("HH:mm:ss",Locale.US).format(new Date(stamp)));
        if(p.getBoolean("emergency_latched_v108",false))b.append("\nEMERGENCY: AUTO заблокирован до явного разрешения");
        else if(p.getBoolean("trading_paused",false)||p.getBoolean("bg_paused",false))b.append("\nPAUSE: новые входы запрещены");
        else if(!p.getBoolean("auto_trading",false))b.append("\nAUTO выключен");
        String session=sessionBlock(p);if(!session.isEmpty())b.append("\n").append(session);
        try{
            JSONObject r=new JSONObject(p.getString("risk_state_json","{}"));
            if(!r.optBoolean("allowed",false))b.append("\nРИСК: ").append(riskText(r));
            long checked=p.getLong("risk_checked_ms",0L);
            if(checked==0||System.currentTimeMillis()-checked>90000)b.append("\nПроверка риска устарела или ещё не выполнена");
        }catch(Exception e){b.append("\nНет подтверждённого состояния риска");}
        return b.toString();
    }
    public static void addRecoveryButton(Activity a,LinearLayout box,SharedPreferences p,Runnable autoOff) {
        TextView button=new TextView(a);button.setText("ПРОВЕРИТЬ БЛОКИРОВКУ РИСКА");button.setTextColor(Color.rgb(145,77,255));
        button.setTextSize(14);button.setPadding(0,24,0,24);box.addView(button);
        button.setOnClickListener(v->{
            if(p.getBoolean("auto_trading",false)||p.getBoolean("auto_user_enabled",false)){
                new AlertDialog.Builder(a).setTitle("Сначала выключите AUTO").setMessage("Выключите AUTO, дождитесь завершения текущего запроса и нажмите снова. MT5 и Bridge оставьте запущенными.").setPositiveButton("Понятно",null).show();return;
            }
            String base=p.getString("server_url","").trim().replaceAll("/+$","");if(base.isEmpty())return;
            button.setEnabled(false);
            new Thread(()->{try{
                JSONObject limits=new JSONObject().put("daily_loss_limit_pct",p.getFloat("daily_loss_limit_pct",3f))
                    .put("max_drawdown_pct",p.getFloat("max_drawdown_pct",5f)).put("max_consecutive_losses",p.getInt("max_consecutive_losses",3));
                JSONObject review=FeatureEngine.httpJson("POST",base+"/risk-review",limits);
                a.runOnUiThread(()->{button.setEnabled(true);new AlertDialog.Builder(a).setTitle("Просмотр серии убытков · DEMO")
                    .setMessage(review.optString("message")+"\n\nИстория и денежный убыток не удаляются. Дневной лимит и просадка не сбрасываются. AUTO останется выключенным.")
                    .setNegativeButton("Отмена",null).setPositiveButton("Подтвердить просмотр",(d,w)->{
                        autoOff.run();p.edit().remove("pending_trade_json").apply();button.setEnabled(false);
                        new Thread(()->{try{
                            JSONObject r=FeatureEngine.httpJson("POST",base+"/risk-ack",new JSONObject().put("token",review.optString("token")).put("confirm",true));fetchRisk(p,base);
                            a.runOnUiThread(()->{autoOff.run();button.setEnabled(true);new AlertDialog.Builder(a).setTitle("Проверка завершена").setMessage(r.optString("message")+"\nДля продолжения отдельно включите AUTO. Фильтр сессии остаётся действующим.").setPositiveButton("Понятно",null).show();});
                        }catch(Exception e){a.runOnUiThread(()->{autoOff.run();button.setEnabled(true);error(a,e);});}},"risk-ack").start();
                    }).show();});
            }catch(Exception e){a.runOnUiThread(()->{button.setEnabled(true);error(a,e);});}},"risk-review").start();
        });
    }
    private static void error(Activity a,Exception e){new AlertDialog.Builder(a).setTitle("Блокировка не изменена").setMessage(e.getMessage()).setPositiveButton("Понятно",null).show();}
}
