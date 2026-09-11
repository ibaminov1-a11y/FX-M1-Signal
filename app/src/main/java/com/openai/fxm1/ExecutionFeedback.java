package com.openai.fxm1;

import android.content.SharedPreferences;
import org.json.JSONObject;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Presentation of execution facts, separate from the price analysis and its score. */
public final class ExecutionFeedback {
    private ExecutionFeedback() {}
    public static boolean bridgeCompatible(String version){return EventClient.VERSION.equals(version);}
    public static void record(SharedPreferences p,String symbol,String tf,String stage,String detail){
        p.edit().putString("execution_symbol",symbol).putString("execution_tf",tf)
            .putString("execution_stage",stage).putString("execution_detail",detail)
            .putLong("execution_at",System.currentTimeMillis()).apply();
    }
    public static String responseStage(JSONObject response){
        if(response.optBoolean("pending_approval",false))return "CONFIRMATION";
        int rc=response.optInt("retcode",0);
        boolean filled=response.optBoolean("accepted",false)&&(rc==10009||rc==10010)&&
            (response.optLong("ticket",0)>0||response.optLong("deal",0)>0);
        return filled?"FILLED":response.optBoolean("accepted",false)?"UNCONFIRMED":"REJECTED";
    }
    public static String responseDetail(JSONObject r){
        String stage=responseStage(r);
        if("FILLED".equals(stage))return "MT5 подтвердил исполнение · ордер #"+r.optLong("ticket",0)+" · сделка #"+r.optLong("deal",0);
        if("CONFIRMATION".equals(stage))return "Требуется ручное подтверждение: "+r.optString("message","");
        if("UNCONFIRMED".equals(stage))return "Запрос принят; исполнение пока не подтверждено";
        return "Bridge отклонил запрос: "+r.optString("message","причина не передана");
    }
    public static String riskText(String value){
        if(value==null||value.isEmpty())return "не проверен";
        return value.replace("LOSS_STREAK","серия убытков (учтённая история)")
            .replace("DAILY_LOSS","дневной лимит убытка").replace("DRAWDOWN","лимит просадки")
            .replace("HISTORY_UNAVAILABLE","история MT5 недоступна — новые входы запрещены")
            .replace("RISK BLOCK:","вход запрещён:").replace("RISK OK","разрешён по последней проверке");
    }
    public static String render(SharedPreferences p,String symbol,String tf){
        String mode;
        if(p.getBoolean("v108_emergency_latched",false))mode="EMERGENCY · AUTO заблокирован";
        else if(!p.getBoolean("auto_trading",false))mode="AUTO выключен";
        else if(p.getBoolean("trading_paused",false))mode="PAUSE · новые входы запрещены";
        else mode="AUTO включён; это не подтверждение открытия позиции";
        StringBuilder s=new StringBuilder("\n\nИСПОЛНЕНИЕ: ").append(mode);
        long at=p.getLong("execution_at",0);
        if(at>0&&symbol.equals(p.getString("execution_symbol",""))&&tf.equals(p.getString("execution_tf",""))){
            String when=new SimpleDateFormat("HH:mm:ss",Locale.US).format(new Date(at));
            s.append("\nПоследняя проверка исполнения ").append(when).append(": ").append(p.getString("execution_detail","—"));
        }
        long riskAt=p.getLong("smart_snapshot_ms",0);
        if(riskAt>0){
            s.append("\nКонтроль риска: ").append(riskText(p.getString("risk_snapshot","")));
            if(System.currentTimeMillis()-riskAt>90000)s.append(" (сохранённая проверка; нужна актуализация)");
        }
        return s.toString();
    }
}
