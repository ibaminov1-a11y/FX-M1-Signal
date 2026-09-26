package com.openai.fxm1;
import org.json.*;
import java.util.*;

/** Time-anchored viewport. New candles never shift a manually selected historical edge. */
final class ChartViewport {
    private final TreeMap<Long,JSONObject> history=new TreeMap<>();
    private boolean live=true;
    private long edge=Long.MAX_VALUE;
    private int visible=36;
    void clear(){history.clear();live=true;edge=Long.MAX_VALUE;}
    void merge(JSONArray incoming){if(incoming==null)return;for(int i=0;i<incoming.length();i++){
        JSONObject b=incoming.optJSONObject(i);if(b!=null&&b.optLong("time",0)>0)history.put(b.optLong("time"),b);
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
    void zoom(double scale){visible=Math.max(12,Math.min(240,(int)Math.round(visible/scale)));}
    boolean live(){return live;}void follow(){live=true;edge=Long.MAX_VALUE;}
    long edge(){return history.isEmpty()?0:live?history.lastKey():edge;}
    long oldest(){return history.isEmpty()?0:history.firstKey();}
    int visible(){return visible;}
}
