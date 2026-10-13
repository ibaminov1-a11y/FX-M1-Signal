package com.openai.fxm1;

import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Iterator;

/** Bounded, read-only records of forecasts actually received on this phone.
 * Selection is sticky; no account, trading permission, or broker operation lives here.
 */
final class ForecastArchive {
    static final int LIMIT=32, SCOPE_LIMIT=16;
    private final SharedPreferences prefs;
    private final String key;
    private String encoded=null, selected="", warning="";
    private ArrayList<JSONObject> records=new ArrayList<>();
    ForecastArchive(SharedPreferences prefs,String scope){this.prefs=prefs;key="forecast-"+ChartDisplayState.key(scope);load();}
    private void load(){
        String raw=prefs.getString(key,"{}");if(raw.equals(encoded))return;encoded=raw;
        records=new ArrayList<>();selected="";
        try {
            if(raw.length()>262144)return;
            JSONObject root=new JSONObject(raw);selected=root.optString("selected","");
            JSONArray rows=root.optJSONArray("records");
            if(rows!=null)for(int i=0;i<Math.min(rows.length(),LIMIT);i++){
                JSONObject row=rows.optJSONObject(i);if(row!=null&&PriceForecastPlot.validPoints(row))records.add(copy(row));
            }
            if(find(selected)==null)selected=records.isEmpty()?"":records.get(0).optString("snapshot_id");
        }catch(JSONException e){records.clear();selected="";warning="Сохранённый прогноз повреждён; ждём новый расчёт";}
    }
    private JSONObject find(String id){for(JSONObject p:records)if(id.equals(p.optString("snapshot_id")))return p;return null;}
    static JSONObject copy(JSONObject value){try{return new JSONObject(value.toString());}catch(JSONException e){throw new IllegalArgumentException(e);}}
    private static String signature(JSONObject p){
        StringBuilder value=new StringBuilder();
        for(String k:new String[]{"snapshot_id","issued_at","origin","symbol","timeframe","mode","model","scope"})value.append(k).append('=').append(p.optString(k)).append('|');
        JSONArray rows=p.optJSONArray("projection");if(rows!=null)for(int i=0;i<rows.length();i++){
            JSONObject row=rows.optJSONObject(i);for(String k:new String[]{"time","center","low","high","minutes"})value.append(k).append('=').append(row.optString(k)).append('|');
        }return value.toString();
    }
    void receive(JSONObject frame){
        synchronized(ForecastArchive.class){
            load();JSONObject price=PriceForecastPlot.validated(frame);
            if(price==null||!frame.optBoolean("available",true)||frame.optBoolean("client_offline")||frame.optBoolean("stale")||frame.optBoolean("archive"))return;
            String id=price.optString("snapshot_id");if(id.isEmpty()||id.length()>128||price.toString().length()>8192)return;
            JSONObject old=find(id);
            if(old!=null){warning=signature(old).equals(signature(price))?"":"Расчёт с тем же ID изменён; показан сохранённый оригинал";return;}
            warning="";records.add(copy(price));records.sort((a,b)->Double.compare(b.optDouble("issued_at"),a.optDouble("issued_at")));
            if(selected.isEmpty())selected=records.get(0).optString("snapshot_id");
            while(records.size()>LIMIT){int drop=records.size()-1;if(records.get(drop).optString("snapshot_id").equals(selected))drop--;records.remove(drop);}
            save();
        }
    }
    boolean select(String id){synchronized(ForecastArchive.class){load();if(find(id)==null)return false;selected=id;save();return true;}}
    boolean newest(){synchronized(ForecastArchive.class){load();return !records.isEmpty()&&select(records.get(0).optString("snapshot_id"));}}
    JSONObject selected(){synchronized(ForecastArchive.class){load();JSONObject p=find(selected);return p==null?null:copy(p);}}
    JSONArray choices(){synchronized(ForecastArchive.class){load();JSONArray rows=new JSONArray();for(JSONObject p:records)rows.put(copy(p));return rows;}}
    String warning(){return warning;}
    private void save(){
        try {
            JSONObject root=new JSONObject().put("selected",selected).put("records",new JSONArray(records));encoded=root.toString();
            // Only a new issued forecast or explicit user selection writes, never a draw/tick duplicate.
            SharedPreferences.Editor edit=prefs.edit().putString(key,encoded);
            JSONArray index=new JSONArray(prefs.getString("forecast-index","[]")),next=new JSONArray();
            next.put(key);for(int i=0;i<index.length();i++){String k=index.optString(i);if(!k.equals(key)){if(next.length()<SCOPE_LIMIT)next.put(k);else if(k.startsWith("forecast-chart-v1-"))edit.remove(k);}}
            edit.putString("forecast-index",next.toString()).apply();
        }catch(JSONException e){warning="Не удалось сохранить прогноз на телефоне";}
    }
}
