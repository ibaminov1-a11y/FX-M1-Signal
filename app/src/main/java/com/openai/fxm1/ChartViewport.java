package com.openai.fxm1;
import org.json.*;
import java.util.*;

/** Time-anchored viewport. New candles never shift a manually selected historical edge. */
final class ChartViewport {
    private final TreeMap<Long,JSONObject> history=new TreeMap<>();
    private boolean live=true;
    private long edge=Long.MAX_VALUE;
    private int visible=36;
    void clear(){history.clear();live=true;edge=Long.MAX_VALUE;visible=36;}
    static boolean validBar(JSONObject b){
        if(b==null||b.optLong("time",0)<=0)return false;
        double o=b.optDouble("open",Double.NaN),c=b.optDouble("close",Double.NaN),
            lo=b.optDouble("low",Double.NaN),hi=b.optDouble("high",Double.NaN);
        return Double.isFinite(o)&&Double.isFinite(c)&&Double.isFinite(lo)&&Double.isFinite(hi)
            &&lo>0&&lo<=Math.min(o,c)&&hi>=Math.max(o,c);
    }
    void merge(JSONArray incoming){if(incoming==null)return;for(int i=0;i<incoming.length();i++){
        JSONObject b=incoming.optJSONObject(i);if(validBar(b))history.put(b.optLong("time"),b);
    }}
    JSONArray window(){JSONArray out=new JSONArray();NavigableMap<Long,JSONObject> data=live?history:history.headMap(edge,true);
        ArrayList<JSONObject> rows=new ArrayList<>(data.descendingMap().values());
        for(int i=Math.min(visible,rows.size())-1;i>=0;i--)out.put(rows.get(i));return out;
    }
    void pan(int count){if(history.isEmpty())return;
        ArrayList<Long> keys=new ArrayList<>(history.keySet());long old=live?keys.get(keys.size()-1):edge;
        int index=Collections.binarySearch(keys,old);if(index<0)index=-index-2;
        int next=Math.max(0,Math.min(keys.size()-1,index-count));edge=keys.get(next);live=false;
    }
    void zoom(double scale){if(Double.isFinite(scale)&&scale>0)visible=(int)Math.max(12,Math.min(5000,Math.round(visible/scale)));}
    void fitRange(long first,long last){
        if(history.isEmpty()||first<=0||last<first)return;
        Long start=history.floorKey(first);if(start==null)start=history.firstKey();
        Long end=history.ceilingKey(last);if(end==null)end=history.lastKey();
        visible=Math.max(12,history.subMap(start,true,end,true).size()+2);
        visible=Math.min(5000,visible);live=end.equals(history.lastKey());edge=live?Long.MAX_VALUE:end;
    }
    JSONObject snapshotState(){try{return new JSONObject().put("visibleBars",visible).put("followingLive",live).put("rightEdgeTime",live?0:edge);}
        catch(JSONException e){throw new IllegalStateException(e);}}
    void restoreState(JSONObject s){if(s==null)return;visible=Math.max(12,Math.min(5000,s.optInt("visibleBars",36)));
        live=s.optBoolean("followingLive",true);long saved=s.optLong("rightEdgeTime",0);edge=live||saved<=0?Long.MAX_VALUE:saved;if(saved<=0)live=true;}
    boolean live(){return live;}void follow(){live=true;edge=Long.MAX_VALUE;}
    long edge(){return history.isEmpty()?0:live?history.lastKey():edge;}
    long oldest(){return history.isEmpty()?0:history.firstKey();}
    int visible(){return visible;}
}
