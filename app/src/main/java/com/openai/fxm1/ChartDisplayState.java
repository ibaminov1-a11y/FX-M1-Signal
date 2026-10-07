package com.openai.fxm1;

import android.content.SharedPreferences;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashSet;
import org.json.JSONArray;
import org.json.JSONObject;

/** UI preferences only. No trading config, tokens, orders or account mutations. */
final class ChartDisplayState {
    static final String PATTERNS="PATTERNS", CANDLES="CANDLES";
    String mode=PATTERNS, selectedPatternId="";
    final LinkedHashSet<String> selectedScenarioIds=new LinkedHashSet<>();
    boolean manualViewport=false, followingLive=true;
    int visibleBars=36;
    long rightEdgeTime=0;

    static String key(String scope){
        try {
            byte[] bytes=MessageDigest.getInstance("SHA-256").digest(scope.getBytes(StandardCharsets.UTF_8));
            StringBuilder value=new StringBuilder("chart-v1-");
            for(byte b:bytes){int n=b&255;value.append("0123456789abcdef".charAt(n>>>4)).append("0123456789abcdef".charAt(n&15));}
            return value.toString();
        }catch(java.security.NoSuchAlgorithmException e){throw new IllegalStateException(e);}
    }
    static ChartDisplayState load(SharedPreferences prefs,String scopeKey){
        ChartDisplayState state=new ChartDisplayState();
        if(scopeKey==null||scopeKey.isEmpty())return state;
        try {
            JSONObject data=new JSONObject(prefs.getString(key(scopeKey),"{}"));
            state.mode=CANDLES.equals(data.optString("mode"))?CANDLES:PATTERNS;
            state.selectedPatternId=data.optString("selectedPatternId","");
            JSONArray ids=data.optJSONArray("selectedScenarioIds");
            if(ids!=null)for(int i=0;i<Math.min(2,ids.length());i++){
                String id=ids.optString(i,"");if(!id.isEmpty())state.selectedScenarioIds.add(id);
            }
            state.manualViewport=data.optBoolean("manualViewport");
            state.followingLive=data.optBoolean("followingLive",true);
            state.visibleBars=Math.max(12,Math.min(5000,data.optInt("visibleBars",36)));
            state.rightEdgeTime=Math.max(0,data.optLong("rightEdgeTime",0));
        }catch(Exception ignored){/* A malformed UI preference is not trading state. */}
        return state;
    }
    void save(SharedPreferences prefs,String scopeKey){
        if(scopeKey==null||scopeKey.isEmpty())return;
        try {
            JSONObject data=new JSONObject().put("mode",CANDLES.equals(mode)?CANDLES:PATTERNS)
                .put("selectedPatternId",selectedPatternId).put("selectedScenarioIds",new JSONArray(selectedScenarioIds))
                .put("manualViewport",manualViewport).put("followingLive",followingLive)
                .put("visibleBars",visibleBars).put("rightEdgeTime",rightEdgeTime);
            prefs.edit().putString(key(scopeKey),data.toString()).apply();
        }catch(org.json.JSONException e){throw new IllegalStateException(e);}
    }
}
