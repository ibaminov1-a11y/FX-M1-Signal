package com.openai.fxm1;

import android.app.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.Locale;

/** Shared copy for the main card and the enlarged live map. */
public final class ScenarioUi {
    private ScenarioUi(){}
    static String px(double v){return Double.isFinite(v)&&v>0?String.format(Locale.US,"%.5f",v):"—";}
    public static String headline(JSONObject f){
        if(f==null||f.optInt("map_version")<2)return "КАРТА: ожидаем новый профиль / данные Bridge";
        int side=f.optInt("side");
        return side==0?"WAIT · нет ясного сценария":"ОСНОВНОЙ "+(side>0?"BUY":"SELL")+" · вес модели "+Math.round(f.optDouble("confidence")*100)+"/100";
    }
    public static String levels(JSONObject state){
        JSONObject f=state.optJSONObject("forecast");if(f==null||f.optInt("map_version")<2)return "";
        StringBuilder out=new StringBuilder();JSONObject lv=f.optJSONObject("entry_levels");
        for(String side:new String[]{"BUY","SELL"}){
            JSONObject l=lv==null?null:lv.optJSONObject(side);if(l==null)continue;
            if(out.length()>0)out.append("\n");out.append(side).append(side.equals("BUY")?" выше ":" ниже ").append(px(l.optDouble("trigger")));
        }
        JSONArray routes=f.optJSONArray("scenarios");
        if(routes!=null)for(int i=0;i<Math.min(2,routes.length());i++){
            JSONObject r=routes.optJSONObject(i);if(r==null)continue;
            out.append("\n\n").append(i==0?"Основной ":"Альтернативный ").append(r.optInt("side")>0?"BUY":"SELL")
                .append("\nT1: ").append(px(r.optDouble("target1",r.optDouble("target"))))
                .append(" · T2: ").append(px(r.optDouble("target2",r.optDouble("target"))))
                .append("\nОтмена: ").append(px(r.optDouble("invalidation")));
            if("MEASURED_RANGE_EXTENSION".equals(r.optString("target_source")))out.append(" · цель по диапазону");
        }
        String campaign=EventClient.campaignSummary(state);
        if(!campaign.isEmpty())out.append("\n\n").append(campaign);
        if("RECONCILING".equals(state.optString("campaign_state")))out.append("\n\nПозиций MT5 нет. Завершается сверка прежней кампании.");
        return out.toString();
    }
    public static String explanation(JSONObject state){
        JSONObject f=state.optJSONObject("forecast");
        if(f==null||f.optInt("map_version")<2)return "Старый профиль ещё завершает кампанию либо нет свежих данных. Старая прогнозная линия отключена. Новая карта появится после применения профиля COMPUTE_V1.";
        return "Вход — новый пробой показанного уровня и проверка контекста, спреда и риска."
            +"\nОтмена — выход из текущего сценария. Противоположный вход проверяется отдельно после закрытия."
            +"\nT1/T2 — ориентиры сценария, не гарантированные цены исполнения. HH?/HL?/LH? — предполагаемые повороты."
            +"\nВеса не являются измеренной вероятностью; расположение узлов по времени условное.";
    }
    public static void enlarge(Activity activity){
        Dialog dialog=new Dialog(activity);LinearLayout box=new LinearLayout(activity);box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(12,12,12,12);box.setBackgroundColor(0xff141125);
        TextView title=new TextView(activity);title.setText("КАРТА СЦЕНАРИЕВ · LIVE");title.setTextColor(0xffdddded);title.setTextSize(18);box.addView(title);
        SparklineView chart=new SparklineView(activity);box.addView(chart,new LinearLayout.LayoutParams(-1,0,1));
        Button close=new Button(activity);close.setText("ЗАКРЫТЬ КАРТУ");box.addView(close);close.setOnClickListener(v->dialog.dismiss());
        dialog.setContentView(box);dialog.show();Window window=dialog.getWindow();
        if(window!=null)window.setLayout(-1,-1);
        Handler h=new Handler(Looper.getMainLooper());Runnable update=new Runnable(){public void run(){
            if(!dialog.isShowing())return;JSONObject s=EventClient.state(),d=s.optJSONObject("decision");
            chart.setMarket(s.optJSONArray("bars"),d==null?null:d.optJSONArray("levels"),s.optJSONArray("positions"),
                d==null?null:d.optJSONArray("structure"),"COMPUTE",s.optJSONObject("live_bar"),s.optJSONArray("live_structure"),s.optJSONObject("forecast"));
            h.postDelayed(this,1000);
        }};dialog.setOnDismissListener(x->h.removeCallbacks(update));h.post(update);
    }
}
