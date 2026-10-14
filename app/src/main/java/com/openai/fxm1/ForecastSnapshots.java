package com.openai.fxm1;

import android.content.SharedPreferences;
import org.json.*;
import java.util.*;

/** Bounded, view-only history. Never rewrites an issued price/time or touches trading preferences. */
final class ForecastSnapshots {
    static final int LIMIT=24;
    private final SharedPreferences prefs;
    private String scope="",selected="",lastInput="",persisted="",storageKey="";
    private JSONArray rows=new JSONArray();
    ForecastSnapshots(SharedPreferences prefs){this.prefs=prefs;}
    private String key(){return storageKey;}
    void scope(String value){
        if(!scope.equals(value)){scope=value;storageKey="forecast-snapshots-v1-"+ChartDisplayState.key(scope);persisted="";lastInput="";}
        if(value.isEmpty()){rows=new JSONArray();selected="";return;}
        String text=prefs.getString(key(),"{}");if(text.equals(persisted))return;
        persisted=text;rows=new JSONArray();selected="";
        try{JSONObject saved=new JSONObject(text);JSONArray r=saved.optJSONArray("rows");
            if(r!=null&&r.length()<=LIMIT)rows=r;selected=saved.optString("selected");
        }catch(JSONException ignored){/* Damaged display cache is not trading state. */}
    }
    static String symbol(String s){return s.replace("/","").trim().toUpperCase(Locale.ROOT);}
    static boolean compatible(JSONObject f,JSONObject p){
        if(f==null||p==null||f.optBoolean("chart_read_only")||f.optBoolean("chart_forecast_rejected"))return false;
        String frame=f.optString("chart_timeframe",f.optString("timeframe"));
        if(frame.isEmpty()||!frame.equals(p.optString("timeframe"))||!frame.equals(f.optString("timeframe",frame)))return false;
        if(!f.optString("chart_symbol").isEmpty()&&!symbol(f.optString("chart_symbol")).equals(symbol(p.optString("symbol"))))return false;
        if(!f.optString("chart_scope").isEmpty()){
            String expected=f.optString("chart_scope")+"|"+p.optString("symbol")+"|"+f.optString("chart_mode")+"|"+frame+"|"+p.optString("model");
            if(!expected.equals(p.optString("scope")))return false;
        }
        return valid(p);
    }
    static boolean valid(JSONObject p){
        if(p==null||!p.optBoolean("available")||p.optString("snapshot_id").isEmpty()||p.optString("model").isEmpty()
            ||p.optString("scope").isEmpty()||p.optString("symbol").isEmpty())return false;
        double issued=p.optDouble("issued_at",Double.NaN),origin=p.optDouble("origin",Double.NaN);
        if(!Double.isFinite(issued)||issued<=0||!Double.isFinite(origin)||origin<=0)return false;
        JSONArray a=p.optJSONArray("projection");if(a==null||a.length()==0||a.length()>32)return false;
        double previous=issued;
        for(int i=0;i<a.length();i++){
            JSONObject x=a.optJSONObject(i);if(x==null)return false;
            double t=x.optDouble("time",Double.NaN),v=x.optDouble("center",Double.NaN),lo=x.optDouble("low",Double.NaN),hi=x.optDouble("high",Double.NaN);
            if(!Double.isFinite(t)||t<=previous||!Double.isFinite(v)||!Double.isFinite(lo)||!Double.isFinite(hi)||lo<=0||lo>v||v>hi)return false;
            if(x.has("minutes")&&Math.abs(t-issued-x.optDouble("minutes")*60)>2)return false;
            previous=t;
        }
        return true;
    }
    void observe(JSONObject f){
        JSONObject p=f==null?null:f.optJSONObject("price_forecast");
        if(scope.isEmpty()||!compatible(f,p)||!f.optBoolean("available",true)||f.optBoolean("stale")||f.optBoolean("client_offline")||f.optBoolean("archive"))return;
        double asof=f.optDouble("data_asof",Double.NaN),issued=p.optDouble("issued_at");
        if(!Double.isFinite(asof)||asof<issued-2||asof>=end(p))return;
        String raw=p.toString();if(raw.equals(lastInput))return;lastInput=raw;
        String id=p.optString("snapshot_id");
        for(int i=0;i<rows.length();i++)if(id.equals(rows.optJSONObject(i).optString("snapshot_id")))return; // First observation is immutable.
        rows.put(copy(p));
        ArrayList<JSONObject> sorted=new ArrayList<>();for(int i=0;i<rows.length();i++)sorted.add(rows.optJSONObject(i));
        sorted.sort(Comparator.comparingDouble(x->-x.optDouble("issued_at")));
        while(sorted.size()>LIMIT){int last=sorted.size()-1;if(selected.equals(sorted.get(last).optString("snapshot_id")))last--;sorted.remove(last);}
        rows=new JSONArray(sorted);save();
    }
    private void save(){if(scope.isEmpty())return;try{persisted=new JSONObject().put("rows",rows).put("selected",selected).toString();prefs.edit().putString(key(),persisted).apply();}catch(JSONException e){throw new IllegalStateException(e);}}
    JSONObject selected(JSONObject f){for(int i=0;i<rows.length();i++){JSONObject p=rows.optJSONObject(i);if(selected.equals(p.optString("snapshot_id"))&&compatible(f,p)&&f.optDouble("data_asof",p.optDouble("issued_at"))>=p.optDouble("issued_at")-2)return copy(p);}return null;}
    void selectFirst(JSONObject f){if(selected.isEmpty())latest(f);}
    boolean latest(JSONObject f){JSONArray available=choices(f);return available.length()>0&&select(available.optJSONObject(0).optString("snapshot_id"),f);}
    boolean select(String id,JSONObject f){for(int i=0;i<rows.length();i++){JSONObject p=rows.optJSONObject(i);if(id.equals(p.optString("snapshot_id"))&&compatible(f,p)){selected=id;save();return true;}}return false;}
    JSONArray choices(JSONObject f){JSONArray out=new JSONArray();for(int i=0;i<rows.length();i++){JSONObject p=rows.optJSONObject(i);if(compatible(f,p))out.put(copy(p));}return out;}
    static JSONObject copy(JSONObject p){try{return new JSONObject(p.toString());}catch(JSONException e){throw new IllegalArgumentException(e);}}
    static double end(JSONObject p){JSONArray a=p.optJSONArray("projection");return a.optJSONObject(a.length()-1).optDouble("time");}
    static String stamp(double seconds){java.text.SimpleDateFormat fmt=new java.text.SimpleDateFormat("dd.MM HH:mm:ss",Locale.US);fmt.setTimeZone(TimeZone.getTimeZone("UTC"));return fmt.format(new Date((long)(seconds*1000)))+" UTC";}
    static String status(JSONObject f,JSONObject p){
        if(p==null){JSONObject raw=f.optJSONObject("price_forecast");String reason=f.optString("chart_reason");
            if(reason.isEmpty()&&raw!=null&&!raw.optBoolean("available"))reason=raw.optString("reason");
            if(reason.isEmpty())reason="нет пригодного расчёта для выбранного счёта, инструмента и периода";
            return "Ценовой прогноз недоступен: "+reason;}
        if(f.optBoolean("stale")||f.optBoolean("client_offline")||!f.optBoolean("available",true))return "Сохранённый расчёт; нет свежих данных";
        if(f.optBoolean("archive"))return "Архивный расчёт; не LIVE";
        if(f.optDouble("data_asof")>=end(p))return "Горизонт прогноза завершён; сравнение с фактом";
        return "Зафиксирован по времени; свечи MT5 обновляются";
    }
    static String description(JSONObject f){
        JSONObject p=f.optBoolean("forecast_snapshot_selected")?f.optJSONObject("price_forecast"):null;
        if(p==null)return status(f,null)+". Линия не выдумывается; торговля не изменена.";
        StringBuilder s=new StringBuilder("ЦЕНОВОЙ ПРОГНОЗ · ").append(p.optString("symbol")).append(" ").append(p.optString("timeframe"))
            .append("\nВыпущен: ").append(stamp(p.optDouble("issued_at"))).append("\n").append(status(f,p));
        JSONArray a=p.optJSONArray("projection");for(int i=0;i<a.length();i++){JSONObject x=a.optJSONObject(i);
            s.append("\n").append(stamp(x.optDouble("time"))).append(": ").append(SparklineView.priceText(f,x.optDouble("center")));
        }
        s.append("\nНеизменённый расчёт; фактические свечи используют ту же шкалу времени. Отрезки соединяют рассчитанные точки; промежуточные тики не предсказаны. Не разрешает вход, не гарантирует совпадение. Текущие причины WAIT и уровни сделки — в разделе СЦЕНАРИИ.");
        return s.toString();
    }
}
