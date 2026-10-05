package com.openai.fxm1;

import android.app.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;

/** Activity-owned, read-only forecast viewer. No configuration or AUTO writes. */
final class TimeframeViewer {
    private final Activity activity;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService reads=Executors.newFixedThreadPool(2);
    private final ArrayList<Surface> surfaces=new ArrayList<>();
    private final HashMap<String,JSONObject> cache=new HashMap<>();
    private final HashMap<String,Long> received=new HashMap<>();
    private JSONObject trade=new JSONObject();
    private String selected="",scope="",failure="",tradeSnapshot="";
    private long serial,lastAttempt,tradeReceived;
    private boolean active,closed,inFlight;
    private Future<?> pending;
    private final Runnable tick=new Runnable(){public void run(){if(!active||closed)return;update(EventClient.state());handler.postDelayed(this,1000);}};
    private static final class Surface {
        final SparklineView chart;final Button chooser;final TextView status,context;
        Surface(SparklineView c,Button b,TextView s,TextView summary){chart=c;chooser=b;status=s;context=summary;}
    }
    TimeframeViewer(Activity activity){this.activity=activity;}
    private static String frame(JSONObject s){JSONObject c=s.optJSONObject("config");return c==null?"M5":c.optString("timeframe","M5");}
    private static String symbolKey(String value){return value.replace("/","").trim().toUpperCase(Locale.ROOT);}
    private static String symbol(JSONObject s){JSONObject c=s.optJSONObject("config");return c==null?"":symbolKey(c.optString("symbol"));}
    private static String account(JSONObject s){JSONObject a=s.optJSONObject("account");return a==null?"":a.optString("key");}
    private static String mode(JSONObject s){JSONObject c=s.optJSONObject("config");return c==null?"":c.optString("mode")+"|"+c.optString("account_mode");}
    private static String context(JSONObject s){return EventClient.base()+"|"+EventClient.prefs().getString("ec_token","")+"|"+account(s)+"|"+symbol(s)+"|"+mode(s)+"|"+frame(s)+"|"+s.optString("market_scope")+"|"+s.optString("market_history_generation");}
    View bind(SparklineView chart){
        LinearLayout box=new LinearLayout(activity);box.setOrientation(LinearLayout.VERTICAL);
        LinearLayout row=new LinearLayout(activity);row.setOrientation(LinearLayout.HORIZONTAL);box.addView(row);
        Button choose=new Button(activity);choose.setTag("scenario_timeframe");choose.setTextSize(12);choose.setTextColor(0xffd0b5ff);
        choose.setContentDescription("Период графика · только просмотр");row.addView(choose,new LinearLayout.LayoutParams(0,-2,1));
        Button overview=new Button(activity);overview.setText("ОБЗОР ТФ");overview.setTextSize(11);overview.setTag("scenario_timeframes");row.addView(overview);
        TextView status=new TextView(activity);status.setTag("scenario_timeframe_status");status.setTextColor(0xffb0aac7);status.setTextSize(11);
        status.setMinLines(4);status.setMaxLines(4);status.setEllipsize(android.text.TextUtils.TruncateAt.END);box.addView(status);
        TextView context=new TextView(activity);context.setTextSize(10);context.setTextColor(0xffb0aac7);context.setMinLines(2);context.setMaxLines(2);
        context.setEllipsize(android.text.TextUtils.TruncateAt.END);box.addView(context);context.setOnClickListener(v->overview.performClick());
        Surface surface=new Surface(chart,choose,status,context);surfaces.add(surface);
        choose.setOnClickListener(v->new AlertDialog.Builder(activity).setTitle("Период графика · только просмотр")
            .setItems(Timeframes.CHOICES,(d,pos)->select(Timeframes.CHOICES[pos])).setNegativeButton("ОТМЕНА",null).show());
        overview.setOnClickListener(v->new AlertDialog.Builder(activity).setTitle("Независимые прогнозы · вход "+frame(trade))
            .setMessage(overview()).setPositiveButton("ЗАКРЫТЬ",null).show());
        status.setOnClickListener(v->new AlertDialog.Builder(activity).setTitle("ГРАФИК "+selected+" · ВХОД "+frame(trade))
            .setMessage(summary(display())+"\n\n"+ScenarioUi.levels(display())).setPositiveButton("ЗАКРЫТЬ",null).show());
        update(EventClient.state());return box;
    }
    void unbind(SparklineView chart){for(int i=surfaces.size()-1;i>=0;i--)if(surfaces.get(i).chart==chart)surfaces.remove(i);}
    void setActive(boolean value){
        active=value;handler.removeCallbacks(tick);
        if(value){handler.post(tick);}else{cancel();}
    }
    void close(){closed=true;setActive(false);reads.shutdownNow();surfaces.clear();cache.clear();received.clear();}
    private void cancel(){serial++;if(pending!=null)pending.cancel(true);pending=null;inFlight=false;}
    private void select(String value){
        if(selected.equals(value))return;
        cancel();selected=value;failure="";lastAttempt=0;
        EventClient.prefs().edit().putString("chart_view_tf",value).apply();
        render();fetch();
    }
    void update(JSONObject state){
        if(closed)return;
        String current=context(state);
        if(!scope.equals(current)){cancel();scope=current;cache.clear();received.clear();failure="";lastAttempt=0;}
        String snapshot=state.optString("server_time")+"|"+state.optString("analysis_time");
        if(!snapshot.equals(tradeSnapshot)){
            tradeSnapshot=snapshot;
            long localAge=Math.max(0,System.currentTimeMillis()-EventClient.prefs().getLong("state_last_update_ms",System.currentTimeMillis()));
            tradeReceived=SystemClock.elapsedRealtime()-localAge;
        }
        trade=state;
        if(selected.isEmpty()){
            String saved=EventClient.prefs().getString("chart_view_tf",frame(state));
            selected=Timeframes.index(saved)>=0?saved:frame(state);
        }
        if(profileWaiting()){cancel();cache.clear();received.clear();}
        render();fetch();
    }
    private boolean profileWaiting(){
        JSONObject cfg=trade.optJSONObject("config");
        return cfg!=null&&trade.optJSONObject("campaign")==null&&trade.optJSONObject("pending_config")==null
            &&(!symbol(trade).equals(symbolKey(EventClient.prefs().getString("selected_symbol","EUR/USD")))||!frame(trade).equals(EventClient.tf()));
    }
    private void fetch(){
        if(!active||closed||inFlight||profileWaiting()||(Timeframes.index(selected)<0&&!selected.equals(frame(trade)))||EventClient.base().isEmpty())return;
        long now=SystemClock.elapsedRealtime();if(now-lastAttempt<2000)return;
        lastAttempt=now;inFlight=true;
        final long request=++serial;final String requested=selected,origin=scope;
        final EventClient.ReadRequest read=EventClient.newReadRequest();
        pending=reads.submit(()->{
            JSONObject response=null;String problem="";
            boolean stateRead=false;
            try{
                JSONObject latest=EventClient.readState(read);stateRead=true;
                response=requested.equals(frame(latest))?latest:EventClient.forecast(read,requested);
            }catch(Exception error){
                problem="Нет связи с прогнозом: "+String.valueOf(error.getMessage());
                if(!stateRead)EventClient.offlineIfCurrent(read,error);
            }
            final JSONObject value=response;final String error=problem;
            handler.post(()->{
                if(closed||!active||request!=serial||!requested.equals(selected)||!origin.equals(scope)||!origin.equals(context(EventClient.state())))return;
                inFlight=false;pending=null;
                if(requested.equals(frame(trade))){
                    failure=value==null?error:"";update(EventClient.state());return;
                }
                if(value!=null&&!matches(value,requested)){
                    cache.remove(requested);received.remove(requested);failure="Данные не соответствуют счёту, инструменту, времени или периоду. Ожидаем новый снимок.";
                }else if(value!=null){cache.put(requested,value);received.put(requested,SystemClock.elapsedRealtime());failure="";}else failure=error;
                render();
            });
        });
    }
    private boolean matches(JSONObject response,String requested){
        return requested.equals(frame(response))&&symbol(trade).equals(symbol(response))&&account(trade).equals(account(response))
            &&!trade.optString("market_scope").isEmpty()&&trade.optString("market_scope").equals(response.optString("market_scope"))
            &&!trade.optString("market_history_generation").isEmpty()&&trade.optString("market_history_generation").equals(response.optString("market_history_generation"))
            &&mode(trade).equals(mode(response))&&frame(trade).equals(response.optString("trade_timeframe"))&&response.optBoolean("view_only");
    }
    private JSONObject display(){
        JSONObject stored=selected.equals(frame(trade))?trade:cache.get(selected);
        try{
            if(stored!=null){JSONObject copy=new JSONObject(stored.toString());
                JSONObject forecast=copy.optJSONObject("forecast");
                if(!selected.equals(frame(trade))&&(!copy.optBoolean("available",true)||(forecast!=null&&!forecast.optBoolean("available",true)))&&forecast!=null)forecast.put("scenarios",new JSONArray());
                long elapsed=SystemClock.elapsedRealtime()-(selected.equals(frame(trade))?tradeReceived:received.getOrDefault(selected,0L));
                double asof=forecast==null?0:forecast.optDouble("data_asof",copy.optDouble("analysis_time",0));
                double age=elapsed/1000.0+Math.max(0,copy.optDouble("snapshot_age",0))+Math.max(0,copy.optDouble("server_time",asof)-asof);
                if(forecast!=null&&(age>10||(copy.has("quote_fresh")&&!copy.optBoolean("quote_fresh"))))forecast.put("stale",true);
                if(!failure.isEmpty()){
                    copy.put("client_offline",true);JSONObject f=copy.optJSONObject("forecast");if(f!=null)f.put("client_offline",true);
                }
                return copy;
            }
            JSONObject copy=new JSONObject().put("config",new JSONObject(trade.optJSONObject("config")==null?"{}":trade.optJSONObject("config").toString()).put("timeframe",selected))
                .put("market_scope",trade.optString("market_scope")).put("market_history_generation",trade.optString("market_history_generation"))
                .put("account",trade.optJSONObject("account")).put("bars",new JSONArray()).put("live_structure",new JSONArray())
                .put("forecast",new JSONObject().put("map_version",3).put("available",false).put("scenarios",new JSONArray()));
            return copy;
        }catch(JSONException ignored){return new JSONObject();}
    }
    private void render(){
        JSONObject value=display();String text=summary(value);
        for(Surface surface:surfaces){
            surface.chooser.setText("ГРАФИК "+selected+" ▾");surface.status.setText(text);
            JSONObject context=trade.optJSONObject("timeframe_context");
            surface.context.setText((trade.optBoolean("client_offline")?"КЭШ · ":tradeIsStale()?"УСТАРЕЛО · ":"")+"КОНТЕКСТ "+frame(trade)+": "+(context==null?"Ожидаем независимые прогнозы":context.optString("summary")));
            if(surface.chart.getParent() instanceof ViewGroup){Button archive=((ViewGroup)surface.chart.getParent()).findViewWithTag("scenario_archive");
                if(archive!=null)archive.setText("АРХИВ ВХОДА "+frame(trade));}
            if(profileWaiting()){
                surface.status.setText("ОЖИДАНИЕ ПРОФИЛЯ "+EventClient.prefs().getString("selected_symbol","")+" · "+EventClient.tf()+"\nГрафик "+selected+" обновится после подтверждения Bridge");
                surface.chart.setMarketIdentity("pending:"+EventClient.prefs().getString("selected_symbol","")+"|"+EventClient.tf());
                surface.chart.setMarket(new JSONArray(),null,null,null,"SCENARIO_V2",null,null,new JSONObject());continue;
            }
            // Clearing an unavailable response must also clear same-frame viewport history.
            JSONObject f=value.optJSONObject("forecast");
            if(!selected.equals(frame(trade))&&(!cache.containsKey(selected)||(f!=null&&!f.optBoolean("available",true))))
                surface.chart.setMarketIdentity("unavailable|"+scope+"|"+selected);
            ScenarioUi.populate(surface.chart,value);
        }
    }
    private static String timestamp(double value){
        if(!Double.isFinite(value)||value<=0)return "—";
        SimpleDateFormat f=new SimpleDateFormat("dd.MM HH:mm:ss",Locale.US);f.setTimeZone(TimeZone.getTimeZone("UTC"));return f.format(new Date((long)(value*1000)))+" UTC";
    }
    private String summary(JSONObject state){
        String owner="ВХОД "+frame(trade)+" · график "+selected+(selected.equals(frame(trade))?" · торговый период":" · только просмотр");
        if("M10".equals(frame(trade)))owner+=" · прежний профиль";
        if(!failure.isEmpty())return owner+"\n"+(cache.containsKey(selected)||selected.equals(frame(trade))?"КЭШ · ":"")+failure;
        if(!selected.equals(frame(trade))&&!cache.containsKey(selected))return owner+"\nЗагрузка независимого прогноза…";
        JSONObject forecast=state.optJSONObject("forecast");
        boolean unavailable=!state.optBoolean("available",true)||(forecast!=null&&!forecast.optBoolean("available",true));
        if(unavailable)return owner+"\nПрогноз недоступен: "+state.optString("reason",forecast==null?"Ожидаем данные":forecast.optString("reason","Ожидаем данные"));
        JSONArray rows=forecast==null?null:forecast.optJSONArray("scenarios");JSONObject first=rows==null?null:rows.optJSONObject(0);
        String title=first==null?"WAIT · нет ясной структуры":first.optString("title")+" · "+ScenarioUi.stage(first.optString("stage"));
        double data=state.optDouble("data_asof",forecast==null?0:forecast.optDouble("data_asof",0));
        JSONObject live=state.optJSONObject("live_bar");if(data<=0&&live!=null)data=live.optDouble("time",0);
        double analysis=state.optDouble("analysis_time",forecast==null?0:forecast.optDouble("analysis_time",0));
        return owner+"\n"+(state.optBoolean("client_offline")?"КЭШ · ":forecast!=null&&forecast.optBoolean("stale")?"УСТАРЕЛО · ":"LIVE · ")+title
            +"\nДанные "+timestamp(data)+" · расчёт "+timestamp(analysis)
            +"\nДалее: "+(first==null?"ожидаем структуру":first.optString("next_event",first.optString("reason")));
    }
    private boolean tradeIsStale(){
        JSONObject f=trade.optJSONObject("forecast");
        double asof=f==null?trade.optDouble("analysis_time",0):f.optDouble("data_asof",trade.optDouble("analysis_time",0));
        return (trade.has("quote_fresh")&&!trade.optBoolean("quote_fresh"))
            ||(SystemClock.elapsedRealtime()-tradeReceived)/1000.0+Math.max(0,trade.optDouble("snapshot_age",0))+Math.max(0,trade.optDouble("server_time",asof)-asof)>10;
    }
    private String overview(){
        JSONArray rows=trade.optJSONArray("timeframes");
        if(rows==null||rows.length()==0)return "Bridge ещё не передал независимые прогнозы по периодам.";
        StringBuilder text=new StringBuilder("Каждый период рассчитан по собственным свечам. Направления дают контекст; условия входа определяет только "+frame(trade)+".\n");
        if(trade.optBoolean("client_offline"))text.append("КЭШ · связь с Bridge потеряна.\n");
        else if(tradeIsStale())text.append("УСТАРЕЛО · ожидаем новый снимок Bridge.\n");
        for(int i=0;i<rows.length();i++){
            JSONObject row=rows.optJSONObject(i);if(row==null)continue;String tf=row.optString("timeframe");int side=row.optInt("side");
            text.append("\n").append(tf).append(frame(trade).equals(tf)?" · ВХОД":"");
            if(!row.optBoolean("available")){text.append(" · недоступен: ").append(row.optString("reason")).append("\n");continue;}
            text.append(" · ").append(side>0?"BUY":side<0?"SELL":"WAIT");
            if(!frame(trade).equals(tf)){
                String alignment=row.optString("alignment");
                text.append("SUPPORTS".equals(alignment)?" · поддерживает вход":"OPPOSES".equals(alignment)?" · против направления входа":" · нейтрально");
            }
            text.append("\n").append(row.optString("title")).append(" · ").append(ScenarioUi.stage(row.optString("stage")))
                .append("\nДалее: ").append(row.optString("next_event",row.optString("reason")))
                .append("\nДанные ").append(timestamp(row.optDouble("data_asof"))).append("\n");
        }
        return text.toString();
    }
}
