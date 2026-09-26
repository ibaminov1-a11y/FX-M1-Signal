package com.openai.fxm1;
import android.content.Context;
import android.graphics.*;
import android.util.AttributeSet;
import android.view.*;
import org.json.*;
import java.util.*;

/** Read-only chart; touch gestures alter only the viewport, never the trading engine. */
public class SparklineView extends View {
    private final ChartViewport viewport=new ChartViewport();
    private JSONArray positions=new JSONArray(),structure=new JSONArray(),liveStructure=new JSONArray();
    private JSONObject liveBar=null,forecast=new JSONObject();
    private String identity="";
    private final LinkedHashSet<String> selected=new LinkedHashSet<>();
    private boolean customSelection=false,archive=false,panning=false;
    private float downX,downY,lastX;
    private ScaleGestureDetector scale;
    public SparklineView(Context c){super(c);init(c);}
    public SparklineView(Context c,AttributeSet a){super(c,a);init(c);}
    public SparklineView(Context c,AttributeSet a,int s){super(c,a,s);init(c);}
    private void init(Context c){
        setClickable(true);scale=new ScaleGestureDetector(c,new ScaleGestureDetector.SimpleOnScaleGestureListener(){
            public boolean onScale(ScaleGestureDetector d){viewport.zoom(d.getScaleFactor());invalidate();return true;}
        });
    }
    public void setSignal(String ignored){}
    public void setValues(List<Double> ignored){}
    public void setMarketIdentity(String key){if(!identity.equals(key)){identity=key;viewport.clear();selected.clear();customSelection=false;}}
    public String marketIdentity(){return identity;}
    public void panHistory(int bars){viewport.pan(bars);updateDescription();invalidate();}
    public long historyRightTime(){return viewport.edge();}
    public long oldestTime(){return viewport.oldest();}
    public boolean isFollowingLive(){return viewport.live();}
    public void goLive(){viewport.follow();updateDescription();invalidate();}
    public void zoomHistory(double factor){viewport.zoom(factor);invalidate();}
    public void prependHistory(JSONArray older){viewport.merge(older);invalidate();}
    public void setArchive(boolean value){archive=value;invalidate();}
    public JSONArray scenarioChoices(){JSONArray r=forecast.optJSONArray("scenarios");return r==null?new JSONArray():r;}
    public void selectScenarios(Set<String> ids){selected.clear();selected.addAll(ids);customSelection=true;invalidate();}
    private static String key(JSONObject s,int i){return s.optString("scenario_id",s.optString("name",""+i));}
    public JSONObject displayedForecast(){
        try{
            JSONObject f=new JSONObject(forecast.toString());JSONArray all=scenarioChoices(),out=new JSONArray();
            for(int i=0;i<all.length();i++){JSONObject s=all.optJSONObject(i);if(s==null)continue;
                if(customSelection?selected.contains(key(s,i)):i<2)out.put(s);
            }
            // A new structural identity does not inherit an unrelated old selection.
            if(customSelection&&out.length()==0&&all.length()>0){customSelection=false;for(int i=0;i<Math.min(2,all.length());i++)out.put(all.get(i));}
            f.put("scenarios",out).put("history_only",!viewport.live()).put("archive",archive);
            if(!viewport.live())f.put("scenarios",new JSONArray());
            return f;
        }catch(Exception e){return new JSONObject();}
    }
    private void updateDescription(){setContentDescription((archive?"Архивный снимок. ":!viewport.live()?"Просмотр истории. ":"")+mapDescription(forecast));}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p){
        JSONObject s=EventClient.state(),d=s.optJSONObject("decision");
        setMarket(b,l,p,d==null?null:d.optJSONArray("structure"),"SCENARIO_V2",s.optJSONObject("live_bar"),s.optJSONArray("live_structure"),s.optJSONObject("forecast"));
    }
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String path){setMarket(b,l,p,s,path,null,null,null);}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String path,JSONObject lb,JSONArray ls){setMarket(b,l,p,s,path,lb,ls,null);}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String path,JSONObject lb,JSONArray ls,JSONObject f){
        viewport.merge(b);positions=p==null?new JSONArray():p;structure=s==null?new JSONArray():s;
        liveBar=lb;liveStructure=ls==null?new JSONArray():ls;forecast=f==null?new JSONObject():f;updateDescription();invalidate();
    }
    @Override public boolean onTouchEvent(MotionEvent e){
        scale.onTouchEvent(e);
        if(e.getPointerCount()>1){getParent().requestDisallowInterceptTouchEvent(true);panning=true;return true;}
        switch(e.getActionMasked()){
            case MotionEvent.ACTION_DOWN: downX=lastX=e.getX();downY=e.getY();panning=false;return true;
            case MotionEvent.ACTION_MOVE:
                float dx=e.getX()-downX,dy=e.getY()-downY;
                if(!panning&&Math.abs(dx)>16&&Math.abs(dx)>Math.abs(dy)){panning=true;getParent().requestDisallowInterceptTouchEvent(true);}
                if(panning&&!scale.isInProgress()){
                    float unit=Math.max(3,getWidth()*.45f/viewport.visible());int n=(int)((e.getX()-lastX)/unit);
                    if(n!=0){panHistory(n);lastX=e.getX();}
                }return true;
            case MotionEvent.ACTION_UP:
                if(!panning&&Math.abs(e.getY()-downY)<16)performClick();
                getParent().requestDisallowInterceptTouchEvent(false);return true;
            case MotionEvent.ACTION_CANCEL: panning=false;return true;
        }return true;
    }
    @Override public boolean performClick(){super.performClick();return true;}
    @Override protected void onDraw(Canvas c){
        super.onDraw(c);JSONArray bars=viewport.window();
        if(bars.length()<2){Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);p.setTextSize(14*getResources().getDisplayMetrics().density);p.setColor(0xffb0aac7);c.drawText("Ожидаем реальные свечи MT5",12,50,p);return;}
        JSONObject f=displayedForecast();
        ScenarioMapRenderer.draw(c,getWidth(),getHeight(),getResources().getDisplayMetrics().density,bars,structure,
            viewport.live()?liveBar:null,viewport.live()?liveStructure:new JSONArray(),f,viewport.live()?positions:new JSONArray());
    }
    private static String priceText(double value){return String.format(Locale.US,"%.5f",value);}
    public static String mapDescription(JSONObject f){
        if(f==null||f.optInt("map_version",0)<2)return "График MT5. Старый прогноз отключён; ожидаем карту нового движка.";
        StringBuilder text=new StringBuilder("Карта сценариев. Веса модели — не вероятность успеха. Время условно.");
        if(!hasScenarioMap(f))text.append(" WAIT — нет ясного сценария.");
        JSONObject entries=f.optJSONObject("entry_levels");
        if(entries!=null)for(String side:new String[]{"BUY","SELL"}){
            JSONObject level=entries.optJSONObject(side);if(level==null)continue;
            text.append(" ").append(side).append(" ").append(priceText(level.optDouble("trigger")))
                .append("; отмена ").append(priceText(level.optDouble("invalidation"))).append(".");
        }
        JSONArray scenarios=f.optJSONArray("scenarios");
        if(scenarios!=null)for(int i=0;i<scenarios.length();i++){
            JSONObject v=scenarios.optJSONObject(i);if(v==null)continue;
            text.append(" ").append(v.optInt("side")>0?"BUY":"SELL").append(" цель ")
                .append(priceText(v.optDouble("target"))).append(" ").append(v.optString("target_source")).append(".")
                .append(" T1 ").append(priceText(v.optDouble("target1",v.optDouble("target"))))
                .append(" T2 ").append(priceText(v.optDouble("target2",v.optDouble("target"))));
        }
        text.append(" LIVE ").append(priceText(f.optDouble("live_price"))).append(".");
        JSONObject active=f.optJSONObject("active_scenario"),reversal=f.optJSONObject("reversal_status");
        if(active!=null)text.append(" Активный ").append(active.optInt("side")>0?"BUY":"SELL")
            .append("; отмена ").append(priceText(active.optDouble("invalidation"))).append(".");
        if(reversal!=null)text.append(" Разворот: ").append(reversal.optString("status","WAIT"))
            .append(" ").append(reversal.optString("reason","")).append(".");
        return text.toString();
    }
    public static boolean shouldDrawProjection(JSONObject f){
        if(f==null)return false;
        int side=f.optInt("side",0),candidate=f.optInt("candidate_side",0);
        return side!=0||candidate!=0;
    }
    public static String forecastLabel(JSONObject f){
        if(f==null)return "NO EDGE";
        int side=f.optInt("side",0),candidate=f.optInt("candidate_side",0);
        long pct=Math.round(f.optDouble(side>0||candidate>0?"up_probability":"down_probability",0)*100);
        if(side>0)return "BUY "+pct+"%";
        if(side<0)return "SELL "+pct+"%";
        if(candidate>0)return "EARLY BUY "+pct+"%";
        if(candidate<0)return "EARLY SELL "+pct+"%";
        return "NO EDGE";
    }
    public static boolean hasScenarioMap(JSONObject f){
        JSONArray s=f==null?null:f.optJSONArray("scenarios");
        return s!=null&&s.length()>0;
    }

}
