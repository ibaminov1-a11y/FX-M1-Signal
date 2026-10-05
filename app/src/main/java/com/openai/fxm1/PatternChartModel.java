package com.openai.fxm1;

import java.util.*;
import org.json.*;

/** Validated, detached geometry for one market identity. Never an execution plan. */
final class PatternChartModel {
    private final LinkedHashMap<String,JSONObject> patterns=new LinkedHashMap<>();
    private final JSONArray branches=new JSONArray();
    final boolean stale;
    final String reason;
    private PatternChartModel(boolean old,String why){stale=old;reason=why;}
    static String symbol(String s){return s.replace("/","").trim().toUpperCase(Locale.ROOT);}
    static PatternChartModel fromSnapshot(JSONObject state){
        if(state==null)return new PatternChartModel(false,"Нет снимка");
        JSONObject f=state.optJSONObject("forecast"),cfg=state.optJSONObject("config");
        if(f==null)return new PatternChartModel(false,"Нет разметки");
        return parse(f,cfg==null?f.optString("chart_symbol",f.optString("symbol")):cfg.optString("symbol"),
            cfg==null?f.optString("chart_timeframe",f.optString("timeframe")):cfg.optString("timeframe"),
            cfg==null?f.optString("chart_mode"):cfg.optString("mode"),state.optString("market_scope"),
            state.optString("market_history_generation"));
    }
    static PatternChartModel fromForecast(JSONObject f){
        if(f==null)return new PatternChartModel(false,"Нет разметки");
        return parse(f,f.optString("chart_symbol",f.optString("symbol")),f.optString("chart_timeframe",f.optString("timeframe")),
            f.optString("chart_mode"),f.optString("chart_scope"),f.optString("chart_history_clock",f.optString("history_clock")));
    }
    private static PatternChartModel parse(JSONObject f,String symbol,String frame,String mode,String scope,String clock){
        boolean old=f.optBoolean("stale")||f.optBoolean("client_offline")||f.optBoolean("archive");
        PatternChartModel out=new PatternChartModel(old,"Разметка недоступна для выбранных данных");
        JSONObject raw=f.optJSONObject("pattern_chart");
        if(!f.optBoolean("available",true)||raw==null||raw.optInt("version")!=1||!raw.optBoolean("available")||f.optBoolean("chart_read_only")
            ||f.optBoolean("chart_forecast_rejected")||f.optBoolean("history_only")||"CANDLES".equals(f.optString("chart_display_mode")))return out;
        if(!symbol(symbol).equals(symbol(raw.optString("symbol")))||!frame.equals(raw.optString("timeframe"))
            ||!mode.equals(raw.optString("mode"))||scope.isEmpty()||!scope.equals(raw.optString("scope"))
            ||clock.isEmpty()||!clock.equals(raw.optString("history_clock")))return out;
        double asof=f.optDouble("data_asof",Double.NaN),observed=raw.optDouble("data_asof",Double.NaN);
        if(!Double.isFinite(asof)||!Double.isFinite(observed)||observed>asof+1||observed<=0)return out;
        JSONArray rows=raw.optJSONArray("patterns");if(rows==null||rows.length()>32)return out;
        try{
            // Reject the complete overlay on malformed geometry; do not silently
            // replace a selected invalid figure with a different valid figure.
            for(int i=0;i<rows.length();i++)if(!valid(rows.optJSONObject(i),observed))return out;
            for(int i=0;i<rows.length();i++){JSONObject p=new JSONObject(rows.getJSONObject(i).toString());out.patterns.put(p.getString("view_id"),p);}
            JSONArray all=raw.optJSONArray("branches");
            if(all!=null)for(int i=0;i<Math.min(192,all.length());i++){
                JSONObject b=all.optJSONObject(i);if(b==null||!b.optBoolean("read_only"))continue;
                JSONObject p=out.patterns.get(b.optString("view_id"));if(p==null)continue;
                JSONArray ids=p.optJSONArray("scenario_ids");boolean match=false;
                if(ids!=null)for(int j=0;j<ids.length();j++)match|=ids.optString(j).equals(b.optString("scenario_id"));
                if(match)out.branches.put(new JSONObject(b.toString()));
            }
        }catch(JSONException e){return new PatternChartModel(old,"Повреждена разметка");}
        return out;
    }
    private static boolean positive(JSONObject p,String key){double v=p.optDouble(key,Double.NaN);return Double.isFinite(v)&&v>0;}
    private static boolean valid(JSONObject p,double asof){
        if(p==null||p.optString("view_id").isEmpty()||p.optString("title").isEmpty())return false;
        if(!Arrays.asList("FORMING","DETECTED","INVALIDATED","EXPIRED").contains(p.optString("geometry_state")))return false;
        if(!positive(p,"start_at")||!positive(p,"end_at")||p.optDouble("start_at")>p.optDouble("end_at")||p.optDouble("end_at")>asof)return false;
        JSONArray a=p.optJSONArray("anchors"),s=p.optJSONArray("segments");if(a==null||s==null||a.length()<2||a.length()>64||s.length()>64)return false;
        for(int i=0;i<a.length();i++){
            JSONObject x=a.optJSONObject(i);if(x==null||!positive(x,"price")||!positive(x,"time")||x.optDouble("time")>asof
                ||!positive(x,"observed_at")||x.optDouble("observed_at")>asof)return false;
            if(x.optBoolean("provisional")){if(!x.isNull("confirmed_at"))return false;}
            else if(!positive(x,"confirmed_at")||x.optDouble("confirmed_at")>asof)return false;
        }
        for(int i=0;i<s.length();i++){
            JSONObject x=s.optJSONObject(i);if(x==null)return false;
            for(String key:new String[]{"from_time","to_time","from_price","to_price"})if(!positive(x,key))return false;
            if(x.optDouble("from_time")>x.optDouble("to_time")||x.optDouble("to_time")>asof)return false;
        }
        return true;
    }
    int size(){return patterns.size();}
    JSONObject get(String id){JSONObject v=patterns.get(id);try{return v==null?null:new JSONObject(v.toString());}catch(JSONException e){return null;}}
    JSONArray choices(){JSONArray out=new JSONArray();for(String id:patterns.keySet())out.put(get(id));return out;}
    JSONObject selected(String id){if(id!=null&&!id.isEmpty())return get(id);for(JSONObject p:patterns.values())if("DETECTED".equals(p.optString("geometry_state"))||"FORMING".equals(p.optString("geometry_state")))return get(p.optString("view_id"));return patterns.isEmpty()?null:get(patterns.keySet().iterator().next());}
    JSONArray routes(String id){JSONArray out=new JSONArray();for(int i=0;i<branches.length();i++){JSONObject b=branches.optJSONObject(i);if(id.equals(b.optString("view_id"))){try{out.put(new JSONObject(b.toString()));}catch(JSONException ignored){}}}return out;}
    static String stage(String s){switch(s){case "FORMING":return "Формируется";case "DETECTED":return "Геометрия найдена";case "INVALIDATED":return "Отменена";case "EXPIRED":return "Срок истёк";default:return "Нет фигуры";}}
    String description(String id){JSONObject p=selected(id);if(p==null)return id!=null&&!id.isEmpty()?"Выбранная фигура недоступна в текущем снимке.":reason;
        StringBuilder s=new StringBuilder(p.optString("title")+" · "+stage(p.optString("geometry_state"))+". "+p.optString("reason"));
        JSONArray a=p.optJSONArray("anchors");for(int i=0;i<a.length();i++){JSONObject x=a.optJSONObject(i);s.append(" ").append(PatternOverlayRenderer.label(x.optString("role"))).append(x.optBoolean("provisional")?"?":"").append(" ").append(x.optDouble("price")).append(".");}
        return s.toString();}
}
