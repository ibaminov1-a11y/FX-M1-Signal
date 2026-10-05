package com.openai.fxm1;
import android.content.Context;
import android.content.SharedPreferences;
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
    private String identity="",historyScope="",historyFrame="M5",historyClock="";
    public void setHistoryContext(String scope,String frame,String clock){historyScope=scope;historyFrame=frame;historyClock=clock;}
    public String historyScope(){return historyScope;}
    public String historyFrame(){return historyFrame;}
    public String historyClock(){return historyClock;}
    private final LinkedHashSet<String> selected=new LinkedHashSet<>();
    private boolean customSelection=false,archive=false,panning=false;
    private SharedPreferences chartPrefs;
    private ChartDisplayState transientDisplay=new ChartDisplayState();
    private float downX,downY,lastX;
    private ScaleGestureDetector scale;
    private String viewportPreference="";
    public SparklineView(Context c){super(c);init(c);}
    public SparklineView(Context c,AttributeSet a){super(c,a);init(c);}
    public SparklineView(Context c,AttributeSet a,int s){super(c,a,s);init(c);}
    private void init(Context c){
        chartPrefs=c.getApplicationContext().getSharedPreferences("fxm1_chart_v1",Context.MODE_PRIVATE);
        setClickable(true);scale=new ScaleGestureDetector(c,new ScaleGestureDetector.SimpleOnScaleGestureListener(){
            public boolean onScale(ScaleGestureDetector d){viewport.zoom(d.getScaleFactor());saveViewport();invalidate();return true;}
        });
    }
    public void setSignal(String ignored){}
    public void setValues(List<Double> ignored){}
    public void setMarketIdentity(String key){if(!identity.equals(key)){identity=key;viewport.clear();viewportPreference="";selected.clear();customSelection=false;restoreViewport();}}
    public String marketIdentity(){return identity;}
    public void panHistory(int bars){viewport.pan(bars);saveViewport();updateDescription();invalidate();}
    public long historyRightTime(){return viewport.edge();}
    public long oldestTime(){return viewport.oldest();}
    public boolean isFollowingLive(){return viewport.live();}
    public boolean isUnverifiedMarket(){return forecast.optBoolean("chart_read_only");}
    public void goLive(){viewport.follow();saveViewport();updateDescription();invalidate();}
    public void zoomHistory(double factor){viewport.zoom(factor);saveViewport();invalidate();}
    public void prependHistory(JSONArray older){if(isUnverifiedMarket())return;viewport.merge(older);invalidate();}
    public void setArchive(boolean value){if(archive!=value){archive=value;viewportPreference="";restoreViewport();}updateDescription();invalidate();}
    public void showPriceForecast(boolean ignored){setChartMode(ChartDisplayState.PATTERNS);}
    private String displayScope(){return archive?"archive|"+identity:identity;}
    private ChartDisplayState displayState(){return identity.isEmpty()?transientDisplay:ChartDisplayState.load(chartPrefs,displayScope());}
    private void saveDisplay(ChartDisplayState state){if(identity.isEmpty())transientDisplay=state;else state.save(chartPrefs,displayScope());}
    public void setChartMode(String value){
        if(!ChartDisplayState.PATTERNS.equals(value)&&!ChartDisplayState.CANDLES.equals(value))return;
        ChartDisplayState state=displayState();state.mode=value;saveDisplay(state);updateDescription();invalidate();
    }
    private void saveViewport(){
        ChartDisplayState state=displayState();JSONObject snap=viewport.snapshotState();
        state.visibleBars=snap.optInt("visibleBars",36);state.followingLive=snap.optBoolean("followingLive",true);
        state.rightEdgeTime=snap.optLong("rightEdgeTime");state.manualViewport=true;saveDisplay(state);viewportPreference=snap.toString();
    }
    private void restoreViewport(){
        ChartDisplayState state=displayState();try{JSONObject snap=new JSONObject().put("visibleBars",state.visibleBars).put("followingLive",state.followingLive).put("rightEdgeTime",state.rightEdgeTime);
            if(!snap.toString().equals(viewportPreference)){viewport.restoreState(snap);viewportPreference=snap.toString();}}
        catch(JSONException e){throw new IllegalStateException(e);}
    }
    public JSONObject viewportState(){restoreViewport();return viewport.snapshotState();}
    public JSONArray displayedBars(){restoreViewport();return viewport.window();}
    public JSONArray patternChoices(){return PatternChartModel.fromForecast(forecast).choices();}
    public void selectPattern(String id){ChartDisplayState state=displayState();state.selectedPatternId=id==null?"":id;state.selectedScenarioIds.clear();
        state.mode=ChartDisplayState.PATTERNS;selected.clear();customSelection=false;saveDisplay(state);updateDescription();invalidate();}
    public boolean fitSelectedPattern(){
        JSONObject f=displayedForecast();JSONObject p=PatternChartModel.fromForecast(f).selected(f.optString("selected_pattern_id"));
        if(p==null)return false;boolean complete=viewport.oldest()>0&&viewport.oldest()<=p.optLong("start_at");
        viewport.fitRange(p.optLong("start_at"),p.optLong("end_at"));saveViewport();updateDescription();invalidate();return complete;
    }
    public String patternDetails(){JSONObject f=displayedForecast();PatternChartModel m=PatternChartModel.fromForecast(f);
        String id=f.optString("selected_pattern_id");StringBuilder text=new StringBuilder(m.description(id));
        JSONObject p=m.selected(id);if(p!=null){JSONArray b=m.routes(p.optString("view_id"));
            for(int i=0;i<b.length();i++){JSONObject v=b.optJSONObject(i);text.append("\n\n").append(v.optString("title")).append(" · ").append(ScenarioUi.stage(v.optString("stage")))
                .append("\n").append(v.optString("next_event"));JSONObject outcome=v.optJSONObject("display_outcome");
                if(outcome!=null)text.append("\n").append(outcome.optString("reason"));}}
        return text.toString();
    }
    public JSONArray scenarioChoices(){
        if(forecast.has("pattern_chart")){
            PatternChartModel m=PatternChartModel.fromForecast(forecast);ChartDisplayState state=displayState();
            JSONObject p=m.selected(state.selectedPatternId.isEmpty()?forecast.optString("selected_pattern_id"):state.selectedPatternId);
            return p==null?new JSONArray():m.routes(p.optString("view_id"));}
        JSONArray r=forecast.optJSONArray("scenarios");return r==null?new JSONArray():r;
    }
    public void selectScenarios(Set<String> ids){selected.clear();selected.addAll(ids);customSelection=true;ChartDisplayState state=displayState();state.mode=ChartDisplayState.PATTERNS;state.selectedScenarioIds.clear();state.selectedScenarioIds.addAll(ids);saveDisplay(state);updateDescription();invalidate();}
    private static String key(JSONObject s,int i){return s.optString("scenario_id",s.optString("name",""+i));}
    public JSONObject displayedForecast(){
        try{
            restoreViewport();ChartDisplayState state=displayState();
            selected.clear();selected.addAll(state.selectedScenarioIds);customSelection=!selected.isEmpty();
            JSONObject f=new JSONObject(forecast.toString());
            f.put("history_only",!viewport.live()).put("archive",archive).put("show_price_forecast",false).put("chart_display_mode",state.mode);
            String chosen=state.selectedPatternId.isEmpty()?f.optString("selected_pattern_id"):state.selectedPatternId;
            f.put("selected_pattern_id",chosen);
            PatternChartModel model=PatternChartModel.fromForecast(f);JSONObject pattern=model.selected(chosen);
            JSONArray all=scenarioChoices(),out=new JSONArray();
            if(f.has("pattern_chart")&&ChartDisplayState.PATTERNS.equals(state.mode)){
                if(pattern!=null){f.put("selected_pattern_id",pattern.optString("view_id"));all=model.routes(pattern.optString("view_id"));
                    if(!Arrays.asList("DETECTED").contains(pattern.optString("geometry_state")))all=new JSONArray();}
                else all=new JSONArray();
            }
            for(int i=0;i<all.length();i++){
                JSONObject branch=all.optJSONObject(i);if(branch==null)continue;
                if(Arrays.asList("FAILED","EXPIRED","TARGET_REACHED").contains(branch.optString("status")))continue;
                if(out.length()<2&&(customSelection?selected.contains(key(branch,i)):true))out.put(branch);
            }
            f.put("scenarios",out);
            if(!viewport.live()||ChartDisplayState.CANDLES.equals(state.mode))f.put("scenarios",new JSONArray());
            return f;
        }catch(Exception e){return new JSONObject();}
    }
    private void updateDescription(){setContentDescription((archive?"Архивный снимок. ":!viewport.live()?"Просмотр истории. ":"")+mapDescription(displayedForecast()));}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p){
        JSONObject s=EventClient.state(),d=s.optJSONObject("decision");
        setMarket(b,l,p,d==null?null:d.optJSONArray("structure"),"SCENARIO_V2",s.optJSONObject("live_bar"),s.optJSONArray("live_structure"),s.optJSONObject("forecast"));
    }
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String path){setMarket(b,l,p,s,path,null,null,null);}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String path,JSONObject lb,JSONArray ls){setMarket(b,l,p,s,path,lb,ls,null);}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String path,JSONObject lb,JSONArray ls,JSONObject f){
        if(f!=null&&f.optBoolean("chart_read_only")&&(b==null||b.length()==0))viewport.clear();
        viewport.merge(b);restoreViewport();positions=p==null?new JSONArray():p;structure=s==null?new JSONArray():s;
        liveBar=lb;liveStructure=ls==null?new JSONArray():ls;forecast=f==null?new JSONObject():f;updateDescription();invalidate();
    }
    @Override public boolean onTouchEvent(MotionEvent e){
        scale.onTouchEvent(e);
        if(e.getPointerCount()>1){if(getParent()!=null)getParent().requestDisallowInterceptTouchEvent(true);panning=true;return true;}
        switch(e.getActionMasked()){
            case MotionEvent.ACTION_DOWN: downX=lastX=e.getX();downY=e.getY();panning=false;return true;
            case MotionEvent.ACTION_MOVE:
                float dx=e.getX()-downX,dy=e.getY()-downY;
                if(!panning&&Math.abs(dx)>16&&Math.abs(dx)>Math.abs(dy)){panning=true;if(getParent()!=null)getParent().requestDisallowInterceptTouchEvent(true);}
                if(panning&&!scale.isInProgress()){
                    float unit=Math.max(3,getWidth()*.45f/viewport.visible());int n=(int)((e.getX()-lastX)/unit);
                    if(n!=0){panHistory(n);lastX=e.getX();}
                }return true;
            case MotionEvent.ACTION_UP:
                if(!panning&&Math.abs(e.getY()-downY)<16)performClick();
                if(getParent()!=null)getParent().requestDisallowInterceptTouchEvent(false);return true;
            case MotionEvent.ACTION_CANCEL: panning=false;return true;
        }return true;
    }
    @Override public boolean performClick(){super.performClick();return true;}
    @Override protected void onDraw(Canvas c){
        super.onDraw(c);JSONObject f=displayedForecast();JSONArray bars=viewport.window();JSONObject forming=viewport.live()?liveBar:null;
        if(!ChartViewport.validBar(forming)||(bars.length()>0&&forming.optLong("time")<=bars.optJSONObject(bars.length()-1).optLong("time")))forming=null;
        if(bars.length()==0&&forming!=null){bars=new JSONArray().put(forming);forming=null;}
        if(bars.length()==0&&!isUnverifiedMarket()){Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);p.setTextSize(14*getResources().getDisplayMetrics().density);p.setColor(0xffb0aac7);c.drawText("Ожидаем реальные свечи MT5",12,50,p);return;}
        boolean plain=ChartDisplayState.CANDLES.equals(f.optString("chart_display_mode"));
        ScenarioMapRenderer.draw(c,getWidth(),getHeight(),getResources().getDisplayMetrics().density,bars,plain?new JSONArray():structure,
            forming,viewport.live()&&!plain?liveStructure:new JSONArray(),f,viewport.live()?positions:new JSONArray());
    }
    static int priceDigits(JSONObject f){int digits=f==null?5:f.optInt("chart_digits",5);return digits>=0&&digits<=12?digits:5;}
    static String priceText(JSONObject f,double value){return Double.isFinite(value)&&value>0?String.format(Locale.US,"%."+priceDigits(f)+"f",value):"—";}
    public static String mapDescription(JSONObject f){
        if(f!=null&&f.optBoolean("chart_forecast_rejected"))return f.optString("chart_reason")
            +(f.optBoolean("client_offline")?" КЭШ · нет связи с Bridge.":"");
        if(f!=null&&f.optBoolean("chart_read_only"))return ScenarioUi.rawChartLabel(f)+". "+f.optString("chart_reason")
            +". Только просмотр. "+ScenarioUi.chartClockLabel(f)+"; прогноз и уровни входа скрыты."
            +(f.optBoolean("client_offline")?" КЭШ · НЕТ СВЯЗИ С BRIDGE. Телефон потерял связь; текущие данные неизвестны.":"");
        if(f==null||f.optInt("map_version",0)<2)return "График MT5. Старый прогноз отключён; ожидаем карту нового движка.";
        if(f.optBoolean("history_only"))return f.optBoolean("client_offline")?"История свечей MT5 из кэша. Телефон потерял связь с Bridge; его текущее состояние неизвестно.":"История свечей MT5. Текущие гипотезы скрыты; LIVE продолжает работу отдельно.";
        if(!f.optBoolean("available",true))return "Свечи MT5. Прогноз недоступен: "+f.optString("reason","ожидаем пригодные данные выбранного периода")
            +(f.optBoolean("client_offline")?". КЭШ · нет связи с Bridge.":". Только просмотр.");
        if(ChartDisplayState.CANDLES.equals(f.optString("chart_display_mode")))return "Свечи MT5. Геометрия и условные маршруты скрыты."
            +(f.optBoolean("archive")?" Архивный снимок.":f.optBoolean("client_offline")?" КЭШ · нет связи с Bridge.":f.optBoolean("stale")?" Данные устарели.":" LIVE.");
        StringBuilder text=new StringBuilder("Карта сценариев. Веса модели — не вероятность успеха. Время этапов условно.");
        text.append(PriceForecastPlot.description(f));
        text.append(f.optBoolean("archive")?" Сохранённые гипотезы, не LIVE.":f.optBoolean("client_offline")?" КЭШ: телефон потерял связь с Bridge. Последние полученные гипотезы; AUTO может продолжать работу самостоятельно.":f.optBoolean("stale")?" Последние гипотезы: данные устарели, вход запрещён.":" Текущие гипотезы LIVE.");
        text.append(" Серый пунктир — подготовка до подтверждения входа. Цвет — условный путь к целям после подтверждения, не факт сделки. Цвет обозначает ветку, а не наклон отрезка. Старые ветки без этапов сохраняют исходный цвет.");
        if("TIED".equals(f.optString("selection_status")))text.append(" Равнозначные гипотезы — предпочтение не определено.");
        PatternChartModel model=PatternChartModel.fromForecast(f);
        if(f.has("pattern_chart"))text.append(" ").append(model.description(f.optString("selected_pattern_id")));
        else if(!hasScenarioMap(f))text.append(" WAIT — нет ясного сценария.");
        JSONObject entries=f.optJSONObject("entry_levels");
        if(entries!=null&&f.optInt("map_version")<3)for(String side:new String[]{"BUY","SELL"}){
            JSONObject level=entries.optJSONObject(side);if(level==null)continue;
            text.append(" ").append(side).append(" ").append(priceText(f,level.optDouble("trigger")))
                .append("; отмена ").append(priceText(f,level.optDouble("invalidation"))).append(".");
        }
        JSONArray scenarios=f.optJSONArray("scenarios");
        if(scenarios!=null)for(int i=0;i<scenarios.length();i++){
            JSONObject v=scenarios.optJSONObject(i);if(v==null)continue;
            text.append(" ").append(ScenarioUi.role(v,i)).append(" ").append(v.optInt("side")>0?"BUY":v.optInt("side")<0?"SELL":"WAIT");
            if(!v.optString("stage").isEmpty())text.append("; этап: ").append(ScenarioUi.stage(v.optString("stage")));
            double event=v.optDouble("event_level",Double.NaN);
            if(f.optInt("map_version")>=3&&Double.isFinite(event)&&event>0)text.append("; уровень проверки ").append(priceText(f,event));
            double t1=v.optDouble("target1",v.optDouble("target",Double.NaN)),t2=v.optDouble("target2",Double.NaN);
            if(Double.isFinite(t1)&&t1>0)text.append(" T1 ").append(priceText(f,t1));
            if(Double.isFinite(t2)&&t2>0)text.append(" T2 ").append(priceText(f,t2));
            text.append(". ").append(v.optString("next_event", ""));
        }
        text.append(f.optBoolean("archive")?" Цена снимка ":f.optBoolean("client_offline")?" Последняя цена из кэша ":f.optBoolean("stale")?" Последняя устаревшая цена ":" LIVE ")
            .append(priceText(f,f.optDouble("live_price"))).append(".");
        JSONObject active=f.optJSONObject("active_scenario"),reversal=f.optJSONObject("reversal_status");
        if(active!=null)text.append(" Активный ").append(active.optInt("side")>0?"BUY":"SELL")
            .append("; отмена ").append(priceText(f,active.optDouble("invalidation"))).append(".");
        if(reversal!=null)text.append(" Разворот: ").append(reversal.optString("status","WAIT"))
            .append(" ").append(reversal.optString("reason","")).append(".");
        return text.toString();
    }
    public static boolean shouldDrawProjection(JSONObject f){
        if(f==null||f.optBoolean("chart_read_only"))return false;
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
