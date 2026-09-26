package com.openai.fxm1;

import android.app.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;
import java.net.URLEncoder;
import java.util.concurrent.*;

/** Presentation only: selecting a scenario never submits a trade. */
public final class ScenarioUi {
    private static final ExecutorService io=Executors.newSingleThreadExecutor();
    private ScenarioUi(){}
    static String px(double v){return Double.isFinite(v)&&v>0?String.format(Locale.US,"%.5f",v):"—";}
    private static String side(JSONObject s){return s.optInt("side")>0?"BUY":s.optInt("side")<0?"SELL":"WAIT";}
    public static String headline(JSONObject f){
        if(f==null||f.optInt("map_version")<2)return "КАРТА: ожидаем профиль / данные Bridge";
        if(f.optBoolean("stale"))return "ПОСЛЕДНЯЯ КАРТА · данные устарели, вход запрещён";
        JSONArray rows=f.optJSONArray("scenarios");
        if(f.optInt("map_version")>=3){
            JSONObject s=rows==null?null:rows.optJSONObject(0);
            return s==null?"WAIT · нет ясной структуры":s.optString("title")+" · "+side(s)+" · оценка "+Math.round(s.optDouble("quality_score"))+"/100 — не вероятность";
        }
        int direction=f.optInt("side");return direction==0?"WAIT · нет ясного сценария":"ОСНОВНОЙ "+(direction>0?"BUY":"SELL")+" · вес модели "+Math.round(f.optDouble("confidence")*100)+"/100";
    }
    public static String levels(JSONObject state){
        JSONObject f=state.optJSONObject("forecast");if(f==null||f.optInt("map_version")<2)return "";
        StringBuilder out=new StringBuilder();JSONArray rows=f.optJSONArray("scenarios");boolean v3=f.optInt("map_version")>=3;
        if(!v3){JSONObject lv=f.optJSONObject("entry_levels");for(String side:new String[]{"BUY","SELL"}){
            JSONObject l=lv==null?null:lv.optJSONObject(side);if(l!=null)out.append(side).append(side.equals("BUY")?" выше ":" ниже ").append(px(l.optDouble("trigger"))).append("\n");}}
        if(rows!=null)for(int i=0;i<Math.min(v3?4:2,rows.length());i++){
            JSONObject r=rows.optJSONObject(i);if(r==null)continue;
            if(out.length()>0)out.append("\n\n");out.append(i==0?"MAIN":"ALT"+i).append(" · ").append(side(r));
            if(v3)out.append(" · ").append(r.optString("title")).append("\nЭтап: ").append(r.optString("stage"))
                .append("\nСледующее событие: ").append(r.optString("next_event",r.optString("reason")));
            double trigger=r.optDouble("trigger",0);if(trigger<=0)trigger=r.optDouble("activation",0);
            if(r.optInt("side")!=0)out.append("\nУровень проверки: ").append(px(trigger));
            double t1=r.optDouble("target1",r.optDouble("target",Double.NaN)),t2=r.optDouble("target2",Double.NaN);
            if(Double.isFinite(t1)&&t1>0)out.append("\nT1: ").append(px(t1));
            if(Double.isFinite(t2)&&t2>0)out.append(" · T2: ").append(px(t2));
            double cancel=r.optDouble("invalidation",0);if(cancel>0)out.append("\nОтмена: ").append(px(cancel));
            if(v3&&r.optInt("side")!=0)out.append("\nЦель: ").append(source(r.optString("target1_source")));
        }
        String campaign=EventClient.campaignSummary(state);if(!campaign.isEmpty())out.append("\n\n").append(campaign);
        if("RECONCILING".equals(state.optString("campaign_state")))out.append("\n\nПозиций MT5 нет. Завершается сверка прежней кампании.");
        JSONObject cfg=state.optJSONObject("config"),next=state.optJSONObject("pending_config");
        if(cfg!=null)out.append("\n\nЛот в Bridge: ").append(cfg.optDouble("lot_cap")).append(" · ").append(cfg.optString("volume_mode","RISK_CAP"));
        if(next!=null)out.append("\nСледующая кампания: ").append(next.optDouble("lot_cap")).append(" lot (после сверки текущей)");
        return out.toString();
    }
    private static String source(String s){switch(s){case "HISTORICAL_LEVEL":case "CONFIRMED_STRUCTURE":return "исторический уровень";case "CHANNEL_BOUNDARY":return "граница / середина диапазона";case "POLE_PROJECTION":return "проекция измеренного импульса";default:return "геометрическая проекция, не обещание цены";}}
    public static String explanation(JSONObject state){
        JSONObject f=state.optJSONObject("forecast"),cfg=state.optJSONObject("config");
        if(f==null||f.optInt("map_version")<2){
            if(!state.optBoolean("quote_fresh",false))return "Нет свежих данных. История сохраняется; новые входы запрещены. Проверьте время последнего тика и связь MT5. Это само по себе не означает старый профиль.";
            return "Карта ожидает профиль SCENARIO_V2. Действующий профиль: "+(cfg==null?"неизвестен":cfg.optString("engine_mode"))+". Существующая кампания сверяется отдельно.";
        }
        return "Фигура и её границы строятся по уже доступной истории. Каждая ветка имеет собственные события подтверждения и отмены."
            +"\nЦветная линия — условная последовательность, а не будущие свечи. Ретест не обязателен для прямого пробоя и обязателен для сценария ретеста."
            +"\nОценки не являются вероятностями и не складываются в 100. T2 показывается только при наличии основания."
            +"\nАрхив хранит исходные снимки. Просмотр истории и выбор ветки не меняют работу AUTO. REAL в этой сборке заблокирован.";
    }
    private static void error(Activity a,Exception e){if(!a.isFinishing())new AlertDialog.Builder(a).setMessage(String.valueOf(e.getMessage())).setPositiveButton("OK",null).show();}
    private static Button button(Activity a,LinearLayout row,String label,Runnable click){Button b=new Button(a);b.setText(label);b.setTextSize(11);b.setTextColor(0xffd0b5ff);row.addView(b,new LinearLayout.LayoutParams(-2,-2));b.setOnClickListener(v->click.run());return b;}
    public static void attachControls(Activity a,SparklineView chart){
        ViewGroup parent=(ViewGroup)chart.getParent();if(parent==null)return;
        parent.addView(controls(a,chart,false),parent.indexOfChild(chart)+1);
    }
    private static View controls(Activity a,SparklineView chart,boolean archive){
        HorizontalScrollView scroll=new HorizontalScrollView(a);LinearLayout row=new LinearLayout(a);row.setOrientation(LinearLayout.HORIZONTAL);scroll.addView(row);
        button(a,row,archive?"К СНИМКУ":"LIVE",chart::goLive);
        button(a,row,"◀",()->chart.panHistory(12));button(a,row,"▶",()->chart.panHistory(-12));
        button(a,row,"−",()->chart.zoomHistory(.8));button(a,row,"+",()->chart.zoomHistory(1.25));
        button(a,row,"ВЕТКИ",()->choose(a,chart));
        if(!archive){button(a,row,"ЕЩЁ ИСТОРИЯ",()->older(a,chart));button(a,row,"АРХИВ ПРОГНОЗОВ",()->archiveList(a,null));}
        return scroll;
    }
    private static void choose(Activity a,SparklineView chart){
        JSONArray rows=chart.scenarioChoices();if(rows.length()==0){Toast.makeText(a,"Нет действующих сценариев",Toast.LENGTH_SHORT).show();return;}
        String[] labels=new String[rows.length()];boolean[] checks=new boolean[rows.length()];
        Set<String> shown=new HashSet<>();JSONArray selected=chart.displayedForecast().optJSONArray("scenarios");
        if(selected!=null)for(int i=0;i<selected.length();i++)shown.add(selected.optJSONObject(i).optString("scenario_id",selected.optJSONObject(i).optString("name",""+i)));
        for(int i=0;i<rows.length();i++){JSONObject s=rows.optJSONObject(i);String key=s.optString("scenario_id",s.optString("name",""+i));
            labels[i]=(i==0?"MAIN":"ALT"+i)+" · "+side(s)+" · "+s.optString("title",s.optString("type","сценарий"));checks[i]=shown.contains(key);}
        new AlertDialog.Builder(a).setTitle("Показать ветки (не команда на сделку)").setMultiChoiceItems(labels,checks,(d,i,on)->checks[i]=on)
            .setNegativeButton("ОТМЕНА",null).setPositiveButton("ПОКАЗАТЬ",(d,w)->{Set<String> ids=new LinkedHashSet<>();for(int i=0;i<checks.length;i++)if(checks[i]){
                JSONObject s=rows.optJSONObject(i);ids.add(s.optString("scenario_id",s.optString("name",""+i)));}chart.selectScenarios(ids);}).show();
    }
    private static void older(Activity a,SparklineView chart){
        long before=chart.oldestTime();String scope=chart.marketIdentity();
        io.execute(()->{try{JSONObject r=EventClient.http("GET",EventClient.base()+"/ec/history?tf=M5&limit=1000&before="+before,null);
            a.runOnUiThread(()->{if(!scope.equals(chart.marketIdentity()))return;JSONArray rows=r.optJSONArray("bars");chart.prependHistory(rows);
                Toast.makeText(a,rows==null||rows.length()==0?"Более ранних свечей в архиве Bridge нет":"Загружено свечей: "+rows.length(),Toast.LENGTH_LONG).show();});
        }catch(Exception e){a.runOnUiThread(()->error(a,e));}});
    }
    private static void archiveList(Activity a,Double before){
        io.execute(()->{try{String suffix=before==null?"":"&before="+before;JSONObject result=EventClient.http("GET",EventClient.base()+"/ec/scenarios?limit=30"+suffix,null);
            JSONArray rows=result.getJSONArray("snapshots");a.runOnUiThread(()->{
                if(a.isFinishing())return;if(rows.length()==0){Toast.makeText(a,"Архив пока пуст. Снимки сохраняются при изменении структуры или этапа.",Toast.LENGTH_LONG).show();return;}
                int n=rows.length();boolean more=result.optBoolean("has_more");String[] labels=new String[n+(more?1:0)];
                for(int i=0;i<n;i++){JSONObject s=rows.optJSONObject(i);labels[i]=new java.text.SimpleDateFormat("dd.MM HH:mm:ss",Locale.US).format(new Date((long)(s.optDouble("recorded_at")*1000)))+" · "+s.optString("title");}
                if(more)labels[n]="РАНЬШЕ…";
                new AlertDialog.Builder(a).setTitle("Неизменяемые снимки · не LIVE").setItems(labels,(d,pos)->{
                    if(pos==n){archiveList(a,result.optDouble("next_before"));return;}
                    String id=rows.optJSONObject(pos).optString("snapshot_id");io.execute(()->{try{
                        JSONObject response=EventClient.http("GET",EventClient.base()+"/ec/scenarios?id="+URLEncoder.encode(id,"UTF-8"),null);
                        JSONObject snapshot=response.getJSONArray("snapshots").getJSONObject(0);a.runOnUiThread(()->open(a,snapshot));
                    }catch(Exception e){a.runOnUiThread(()->error(a,e));}});
                }).setNegativeButton("ЗАКРЫТЬ",null).show();
            });
        }catch(Exception e){a.runOnUiThread(()->error(a,e));}});
    }
    public static void enlarge(Activity a){open(a,null);}
    private static void populate(SparklineView chart,JSONObject s){
        JSONObject d=s.optJSONObject("decision");chart.setMarketIdentity(s.optString("market_scope",s.optString("snapshot_id","live")));
        chart.setMarket(s.optJSONArray("bars"),d==null?null:d.optJSONArray("levels"),s.optJSONArray("positions"),
            d==null?null:d.optJSONArray("structure"),"SCENARIO_V2",s.optJSONObject("live_bar"),s.optJSONArray("live_structure"),s.optJSONObject("forecast"));
    }
    private static void open(Activity a,JSONObject snapshot){
        if(a.isFinishing())return;
        Dialog dialog=new Dialog(a);LinearLayout box=new LinearLayout(a);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(12,12,12,12);box.setBackgroundColor(0xff141125);
        TextView title=new TextView(a);title.setText(snapshot==null?"СЦЕНАРИИ · LIVE / ИСТОРИЯ":"ИСХОДНЫЙ ПРОГНОЗ · НЕ LIVE");title.setTextColor(0xffdddded);title.setTextSize(16);box.addView(title);
        SparklineView chart=new SparklineView(a);chart.setArchive(snapshot!=null);box.addView(chart,new LinearLayout.LayoutParams(-1,0,1));box.addView(controls(a,chart,snapshot!=null));
        Button close=new Button(a);close.setText("ЗАКРЫТЬ КАРТУ");box.addView(close);close.setOnClickListener(v->dialog.dismiss());
        dialog.setContentView(box);dialog.show();if(dialog.getWindow()!=null)dialog.getWindow().setLayout(-1,-1);
        if(snapshot!=null){populate(chart,snapshot);return;}
        Handler handler=new Handler(Looper.getMainLooper());Runnable update=new Runnable(){public void run(){if(!dialog.isShowing())return;populate(chart,EventClient.state());handler.postDelayed(this,1000);}};
        dialog.setOnDismissListener(d->handler.removeCallbacks(update));handler.post(update);
    }
}
