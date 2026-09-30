package com.openai.fxm1;

import android.app.*;
import android.os.*;
import android.view.*;
import android.graphics.drawable.GradientDrawable;
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
    static String role(JSONObject scenario,int fallback){
        String name=scenario.optString("name",fallback==0?"PRIMARY":"ALT"+fallback);
        if(name.startsWith("OPTION"))return "ВАРИАНТ "+name.substring(6);
        return "PRIMARY".equals(name)?"MAIN":name;
    }
    static String stage(String s){switch(s){
        case "WATCHING":return "Наблюдение";case "BREAK_SEEN":return "Выход наблюдался";
        case "RETEST_SEEN":return "Ретест наблюдался";case "RETURN_SEEN":return "Возврат внутрь наблюдался";
        case "TOUCH_SEEN":return "Зона проверена";case "CONFIRMED":return "Подтверждён";
        case "FAILED":return "Отменён";case "EXPIRED":return "Срок истёк";
        case "TARGET_REACHED":return "Цель достигнута";default:return s;}}
    static String marketIdentity(JSONObject s){
        JSONObject cfg=s.optJSONObject("config");
        String identity=s.optString("market_scope",s.optString("snapshot_id",cfg==null?"live":cfg.optString("symbol")))+"|"
            +s.optString("market_history_generation","UNVERIFIED")+"|"+(cfg==null?s.optString("timeframe","M5"):cfg.optString("timeframe","M5"));
        JSONObject raw=rawChart(s);
        return raw==null?identity:identity+"|"+(cfg==null?"":cfg.optString("symbol"))+"|CHART|"+raw.optString("scope")+"|"
            +raw.optString("symbol")+"|"+raw.optString("timeframe")+"|"+raw.optString("clock")+"|"+raw.optString("status");
    }
    private static JSONObject rawChart(JSONObject s){
        JSONObject raw=s.optJSONObject("chart_market");return raw!=null&&raw.optBoolean("read_only")?raw:null;
    }
    private static String symbolKey(String value){return value.replace("/","").trim().toUpperCase(Locale.ROOT);}
    private static boolean sameChartMarket(JSONObject s,JSONObject raw){
        JSONObject cfg=s.optJSONObject("config");
        if(s.has("market_scope")&&!s.optString("market_scope").equals(raw.optString("scope")))return false;
        return cfg==null||(symbolKey(cfg.optString("symbol")).equals(symbolKey(raw.optString("symbol")))
            &&cfg.optString("timeframe","M5").equals(raw.optString("timeframe")));
    }
    static String rawChartLabel(JSONObject f){return "UNVERIFIED_TIME".equals(f.optString("chart_status"))
        ?"Свечи MT5 · время не подтверждено":"Свечи MT5 · данные не подтверждены";}
    static String chartClockLabel(JSONObject f){
        int offset=f.optInt("chart_offset_minutes",0);
        return offset==0?"Время MT5 без коррекции":"Время UTC · коррекция MT5 "+String.format(Locale.US,"%+d",offset)+" мин";
    }
    public static String headline(JSONObject f){
        if(f!=null&&f.optBoolean("client_offline"))return "ПОСЛЕДНЯЯ КАРТА · КЭШ · НЕТ СВЯЗИ С BRIDGE";
        if(f==null||f.optInt("map_version")<2)return "КАРТА: ожидаем профиль / данные Bridge";
        if(f.optBoolean("stale"))return "ПОСЛЕДНЯЯ КАРТА · данные устарели, вход запрещён";
        if("TIED".equals(f.optString("selection_status")))return "Равнозначные гипотезы — предпочтение не определено";
        JSONArray rows=f.optJSONArray("scenarios");
        if(f.optInt("map_version")>=3){
            JSONObject s=rows==null?null:rows.optJSONObject(0);
            return s==null?"WAIT · нет ясной структуры":s.optString("title")+" · "+side(s)+" · оценка "+Math.round(s.optDouble("quality_score"))+"/100 — не вероятность";
        }
        int direction=f.optInt("side");return direction==0?"WAIT · нет ясного сценария":"ОСНОВНОЙ "+(direction>0?"BUY":"SELL")+" · вес модели "+Math.round(f.optDouble("confidence")*100)+"/100";
    }
    /** Execution belongs to the active trade profile, never the independent chart viewer. */
    public static String executionRequirement(JSONObject state){
        if(state==null)return "";
        JSONObject cfg=state.optJSONObject("config"),f=state.optJSONObject("forecast");
        if(cfg==null||f==null||!"SCALP".equals(cfg.optString("mode"))||!"M1".equals(cfg.optString("timeframe")))return "";
        if(f.has("timeframe")&&!"M1".equals(f.optString("timeframe")))return "";
        JSONObject setup=f.optJSONObject("execution_setup");
        if(setup==null||!"SCALP_MICRO_V1".equals(setup.optString("engine"))||!"M1".equals(setup.optString("timeframe")))return "";
        boolean offline=state.optBoolean("client_offline")||f.optBoolean("client_offline");
        boolean stale=f.optBoolean("stale")||(state.has("quote_fresh")&&!state.optBoolean("quote_fresh"));
        String stage;
        switch(setup.optString("stage")){
            case "WAIT_CONTEXT":stage="Ожидание контекста";break;
            case "PROGRESS":stage="Ожидание движения в плюс";break;
            case "PULLBACK":stage="Откат наблюдался · ожидание возобновления и микропробоя";break;
            case "MICRO":stage="Ожидание micro-trigger";break;
            case "CONFIRMED":stage=offline||stale||f.optBoolean("archive")?
                "Сохранённое подтверждение · текущий вход не подтверждён":"Сигнал подтверждён · исполнение проверяет Bridge";break;
            case "BLOCKED":stage="Вход заблокирован";break;
            default:return "";
        }
        StringBuilder out=new StringBuilder();
        if(offline)out.append("КЭШ · НЕТ СВЯЗИ С BRIDGE\n");
        else if(f.optBoolean("archive"))out.append("СОХРАНЁННЫЙ СНИМОК · НЕ LIVE\n");
        else if(stale)out.append("ДАННЫЕ УСТАРЕЛИ · вход запрещён\n");
        out.append("БЫСТРЫЙ SCALP · ТОРГОВЛЯ M1");
        if(setup.optBoolean("addition"))out.append(" · ДОБАВЛЕНИЕ");
        out.append("\n").append(stage);
        String reason=setup.optString("reason","").trim();if(!reason.isEmpty())out.append("\n").append(reason);
        double trigger=setup.optDouble("trigger",Double.NaN),invalidation=setup.optDouble("invalidation",Double.NaN);
        int side=setup.optInt("side");
        if(Double.isFinite(trigger)&&trigger>0&&side!=0)out.append("\nУровень проверки ").append(side>0?"BUY: выше ":"SELL: ниже ").append(px(trigger));
        if(Double.isFinite(invalidation)&&invalidation>0)out.append("\nОтмена: ").append(px(invalidation));
        return out.toString();
    }
    public static String levels(JSONObject state){
        JSONObject f=state.optJSONObject("forecast");boolean valid=f!=null&&f.optInt("map_version")>=2;
        String requirement=executionRequirement(state);
        if(!valid&&state.optJSONObject("campaign")==null)return requirement;
        StringBuilder out=new StringBuilder(requirement);JSONArray rows=valid?f.optJSONArray("scenarios"):null;boolean v3=valid&&f.optInt("map_version")>=3;
        if(!requirement.isEmpty())out.append("\n\n");
        if(requirement.isEmpty()&&state.optBoolean("client_offline"))out.append("КЭШ · НЕТ СВЯЗИ С BRIDGE\nПоказаны последние полученные данные; текущее состояние кампании неизвестно.\n");
        if(valid)out.append(f.optBoolean("archive")?"ГИПОТЕЗЫ ИЗ СНИМКА · НЕ LIVE":f.optBoolean("client_offline")?"ПОСЛЕДНИЕ ГИПОТЕЗЫ · КЭШ":f.optBoolean("stale")?"ПОСЛЕДНИЕ ГИПОТЕЗЫ · ДАННЫЕ УСТАРЕЛИ":"ТЕКУЩИЕ ГИПОТЕЗЫ · LIVE");
        if(valid&&!v3){JSONObject lv=f.optJSONObject("entry_levels");for(String side:new String[]{"BUY","SELL"}){
            JSONObject l=lv==null?null:lv.optJSONObject(side);if(l!=null)out.append("\n").append(side).append(side.equals("BUY")?" выше ":" ниже ").append(px(l.optDouble("trigger")));}}
        if(rows!=null)for(int i=0;i<Math.min(v3?4:2,rows.length());i++){
            JSONObject r=rows.optJSONObject(i);if(r==null)continue;
            if(out.length()>0)out.append("\n\n");out.append(role(r,i)).append(" · ").append(side(r));
            if(v3)out.append(" · ").append(r.optString("title")).append("\nЭтап: ").append(stage(r.optString("stage")))
                .append("\nСледующее событие: ").append(r.optString("next_event",r.optString("reason")));
            double trigger=r.optDouble("event_level",r.optDouble("activation",0));
            if(r.optInt("side")!=0)out.append("\nУровень проверки: ").append(px(trigger));
            double initial=r.optDouble("initial_activation",Double.NaN),current=r.optDouble("activation",Double.NaN);
            if(Double.isFinite(initial)&&Double.isFinite(current)&&Math.abs(initial-current)>=.000005)
                out.append("\nГраница сейчас: ").append(px(current)).append(" · при создании: ").append(px(initial));
            double t1=r.optDouble("target1",r.optDouble("target",Double.NaN)),t2=r.optDouble("target2",Double.NaN);
            if(Double.isFinite(t1)&&t1>0)out.append("\nT1: ").append(px(t1));
            if(Double.isFinite(t2)&&t2>0)out.append(" · T2: ").append(px(t2));
            double cancel=r.optDouble("invalidation",0);if(cancel>0)out.append("\nОтмена: ").append(px(cancel));
            if(v3&&r.optInt("side")!=0)out.append("\nЦель: ").append(source(r.optString("target1_source")));
        }
        String campaign=EventClient.campaignSummary(state);if(!campaign.isEmpty())out.append("\n\n").append(campaign);
        appendEntryScenario(out,state.optJSONObject("campaign"));
        if("RECONCILING".equals(state.optString("campaign_state")))out.append("\n\nПозиций MT5 нет. Завершается сверка прежней кампании.");
        JSONObject cfg=state.optJSONObject("config"),next=state.optJSONObject("pending_config");
        if(cfg!=null)out.append("\n\nЛот в Bridge: ").append(lot(cfg)).append(" · ").append(cfg.optString("volume_mode","RISK_CAP"));
        if(next!=null)out.append("\nСледующая кампания: ").append(lot(next)).append(" lot (после сверки текущей)");
        return out.toString();
    }
    private static String lot(JSONObject config){
        double value=config.optDouble("lot_cap",Double.NaN);
        return Double.isFinite(value)&&value>0?Double.toString(value):"—";
    }
    private static String recorded(JSONObject source,String key){
        return source==null||source.isNull(key)?"":source.optString(key,"");
    }
    private static void appendEntryScenario(StringBuilder out,JSONObject campaign){
        if(campaign==null)return;
        JSONObject frozen=campaign.optJSONObject("forecast_at_entry");
        String id=recorded(campaign,"scenario_id"),version=recorded(campaign,"scenario_version"),snapshot=recorded(campaign,"snapshot_id");
        if(id.isEmpty())id=recorded(frozen,"entry_scenario_id");
        if(version.isEmpty())version=recorded(frozen,"entry_scenario_version");
        if(snapshot.isEmpty())snapshot=recorded(frozen,"snapshot_id");
        if(out.length()>0)out.append("\n\n");
        out.append("СЦЕНАРИЙ ВХОДА · СОХРАНЁННЫЙ")
            .append("\nID: ").append(id.isEmpty()?"не записан":id)
            .append("\nВерсия: ").append(version.isEmpty()?"не записана":version)
            .append("\nСнимок: ").append(snapshot.isEmpty()?"не записан":snapshot);
        JSONObject entry=null;JSONArray rows=frozen==null?null:frozen.optJSONArray("scenarios");
        if(!id.isEmpty()&&rows!=null)for(int i=0;i<rows.length();i++){
            JSONObject row=rows.optJSONObject(i);if(row==null||!id.equals(recorded(row,"scenario_id")))continue;
            String rowVersion=recorded(row,"scenario_version");
            if(!version.isEmpty()&&!rowVersion.isEmpty()&&!version.equals(rowVersion))continue;
            entry=row;break;
        }
        if(entry==null){out.append("\nИсходная карта входа недоступна; текущие гипотезы её не заменяют.");return;}
        out.append("\n").append(side(entry)).append(" · ").append(entry.optString("title",entry.optString("type")))
            .append("\nЭтап при входе: ").append(stage(entry.optString("stage",entry.optString("status"))));
        double t1=entry.optDouble("target1",entry.optDouble("target",Double.NaN)),t2=entry.optDouble("target2",Double.NaN);
        if(Double.isFinite(t1)&&t1>0)out.append("\nT1 при входе: ").append(px(t1));
        if(Double.isFinite(t2)&&t2>0)out.append(" · T2: ").append(px(t2));
        double invalidation=entry.optDouble("invalidation",Double.NaN);
        if(Double.isFinite(invalidation)&&invalidation>0)out.append("\nОтмена при входе: ").append(px(invalidation));
    }
    private static String source(String s){switch(s){case "HISTORICAL_LEVEL":case "CONFIRMED_STRUCTURE":return "исторический уровень";case "CHANNEL_BOUNDARY":return "граница / середина диапазона";case "POLE_PROJECTION":return "проекция измеренного импульса";default:return "геометрическая проекция, не обещание цены";}}
    public static String explanation(JSONObject state){
        JSONObject f=state.optJSONObject("forecast"),cfg=state.optJSONObject("config");
        if(state.optBoolean("client_offline")||(f!=null&&f.optBoolean("client_offline")))return "Телефон потерял связь с Bridge. Показан последний полученный снимок; текущие котировки, гипотезы и состояние кампании неизвестны. AUTO в Bridge может продолжать работу самостоятельно. После восстановления связи данные обновятся.";
        if(f==null||f.optInt("map_version")<2){
            if(!state.optBoolean("quote_fresh",false))return "Нет свежих данных. История сохраняется; новые входы запрещены. Проверьте время последнего тика и связь MT5. Это само по себе не означает старый профиль.";
            return "Карта ожидает профиль SCENARIO_V2. Действующий профиль: "+(cfg==null?"неизвестен":cfg.optString("engine_mode"))+". Существующая кампания сверяется отдельно.";
        }
        return "Фигура и её границы строятся по уже доступной истории. Каждая ветка имеет собственные события подтверждения и отмены."
            +"\nСерый пунктир — подготовка до подтверждения входа. Цветная линия — условный путь к целям после подтверждения; цвет обозначает ветку, а не наклон каждого отрезка. Это не факт исполнения сделки."
            +"\nТекущие гипотезы LIVE пересчитываются. Сценарий входа кампании показан отдельно по ID, версии и сохранённому снимку; этап «Наблюдение» текущей ветки не описывает уже выполненный вход."
            +"\nРетест не обязателен для прямого пробоя и обязателен для сценария ретеста. Старые снимки без этапов сохраняют исходный цвет ветки."
            +"\nОценки не являются вероятностями и не складываются в 100. T2 показывается только при наличии основания."
            +"\nАрхив хранит исходные снимки. Просмотр истории и выбор ветки не меняют работу AUTO. REAL в этой сборке заблокирован.";
    }
    private static void error(Activity a,Exception e){if(!a.isFinishing())new AlertDialog.Builder(a).setMessage(String.valueOf(e.getMessage())).setPositiveButton("OK",null).show();}
    private static Button button(Activity a,LinearLayout row,String label,Runnable click){
        float d=a.getResources().getDisplayMetrics().density;
        Button b=new Button(a);b.setText(label);b.setTextSize(11);b.setTextColor(0xffd0b5ff);
        b.setMinWidth(0);b.setMinimumWidth(0);b.setPadding((int)(10*d),0,(int)(10*d),0);
        GradientDrawable bg=new GradientDrawable();bg.setColor(0xff191329);bg.setCornerRadius(8*d);bg.setStroke((int)Math.max(1,d),0xff914dff);b.setBackground(bg);
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-2,(int)(42*d));lp.setMargins((int)(3*d),(int)(3*d),(int)(3*d),(int)(3*d));row.addView(b,lp);
        b.setOnClickListener(v->click.run());return b;
    }
    public static void attachControls(Activity a,SparklineView chart){
        ViewGroup parent=(ViewGroup)chart.getParent();if(parent==null)return;
        TimeframeViewer viewer=new TimeframeViewer(a);chart.setTag(viewer);
        parent.addView(viewer.bind(chart),parent.indexOfChild(chart));
        parent.addView(controls(a,chart,false),parent.indexOfChild(chart)+1);
    }
    private static TimeframeViewer viewer(Activity a){
        View chart=a.findViewById(R.id.sparklineView);return chart!=null&&chart.getTag() instanceof TimeframeViewer?(TimeframeViewer)chart.getTag():null;
    }
    static void setActive(Activity a,boolean active){TimeframeViewer v=viewer(a);if(v!=null)v.setActive(active);}
    static void release(Activity a){TimeframeViewer v=viewer(a);if(v!=null)v.close();}
    static void updateLive(SparklineView chart,JSONObject state){
        if(chart.getTag() instanceof TimeframeViewer)((TimeframeViewer)chart.getTag()).update(state);else populate(chart,state);
    }
    private static View controls(Activity a,SparklineView chart,boolean archive){
        LinearLayout pinned=new LinearLayout(a);pinned.setOrientation(LinearLayout.HORIZONTAL);
        Button follow=button(a,pinned,archive?"К СНИМКУ":"LIVE",chart::goLive);follow.setTag("scenario_follow");
        HorizontalScrollView scroll=new HorizontalScrollView(a);LinearLayout row=new LinearLayout(a);row.setOrientation(LinearLayout.HORIZONTAL);scroll.addView(row);
        pinned.addView(scroll,new LinearLayout.LayoutParams(0,-2,1));
        button(a,row,"◀",()->chart.panHistory(12));button(a,row,"▶",()->chart.panHistory(-12));
        button(a,row,"−",()->chart.zoomHistory(.8));button(a,row,"+",()->chart.zoomHistory(1.25));
        Button branches=button(a,row,"ВЕТКИ",()->choose(a,chart));branches.setTag("scenario_branches");
        if(!archive){Button history=button(a,row,"ЕЩЁ ИСТОРИЯ",()->older(a,chart));history.setTag("scenario_history");Button archiveButton=button(a,row,"АРХИВ ВХОДА",()->archiveList(a,null));archiveButton.setTag("scenario_archive");}
        return pinned;
    }
    private static void updateControls(SparklineView chart){
        if(!(chart.getParent() instanceof ViewGroup))return;ViewGroup parent=(ViewGroup)chart.getParent();
        Button follow=parent.findViewWithTag("scenario_follow"),branches=parent.findViewWithTag("scenario_branches"),history=parent.findViewWithTag("scenario_history");
        boolean raw=chart.isUnverifiedMarket();
        if(follow!=null)follow.setText(raw?"К ПОСЛЕДНИМ":chart.displayedForecast().optBoolean("archive")?"К СНИМКУ":"LIVE");
        if(branches!=null)branches.setEnabled(!raw);if(history!=null)history.setEnabled(!raw);
    }
    private static void choose(Activity a,SparklineView chart){
        JSONArray rows=chart.scenarioChoices();if(rows.length()==0){Toast.makeText(a,"Нет действующих сценариев",Toast.LENGTH_SHORT).show();return;}
        String[] labels=new String[rows.length()];boolean[] checks=new boolean[rows.length()];
        Set<String> shown=new HashSet<>();JSONArray selected=chart.displayedForecast().optJSONArray("scenarios");
        if(selected!=null)for(int i=0;i<selected.length();i++)shown.add(selected.optJSONObject(i).optString("scenario_id",selected.optJSONObject(i).optString("name",""+i)));
        for(int i=0;i<rows.length();i++){JSONObject s=rows.optJSONObject(i);String key=s.optString("scenario_id",s.optString("name",""+i));
            labels[i]=role(s,i)+" · "+side(s)+" · "+s.optString("title",s.optString("type","сценарий"));checks[i]=shown.contains(key);}
        new AlertDialog.Builder(a).setTitle("До 2 веток на карте · не команда на сделку").setMultiChoiceItems(labels,checks,(d,i,on)->{
                int count=0;for(boolean checked:checks)if(checked)count++;
                if(on&&count>2){checks[i]=false;((AlertDialog)d).getListView().setItemChecked(i,false);Toast.makeText(a,"Одновременно до двух веток. Снимите одну из выбранных.",Toast.LENGTH_SHORT).show();}
                else checks[i]=on;
            })
            .setNegativeButton("ОТМЕНА",null).setPositiveButton("ПОКАЗАТЬ",(d,w)->{Set<String> ids=new LinkedHashSet<>();for(int i=0;i<checks.length;i++)if(checks[i]){
                JSONObject s=rows.optJSONObject(i);ids.add(s.optString("scenario_id",s.optString("name",""+i)));}chart.selectScenarios(ids);}).show();
    }
    static String historyPath(SparklineView chart){
        return "/ec/history?tf="+chart.historyFrame()+"&limit=1000&before="+chart.oldestTime();
    }
    static boolean historyResponseMatches(SparklineView chart,String identity,JSONObject response){
        return !chart.isUnverifiedMarket()&&identity.equals(chart.marketIdentity())&&response.optBoolean("cache_verified",false)
            &&!chart.historyClock().isEmpty()&&chart.historyClock().equals(response.optString("clock"))
            &&chart.historyScope().equals(response.optString("scope"))&&chart.historyFrame().equals(response.optString("tf"));
    }
    private static void older(Activity a,SparklineView chart){
        if(chart.isUnverifiedMarket())return;
        String identity=chart.marketIdentity(),source=EventClient.base(),path=historyPath(chart);
        io.execute(()->{try{JSONObject r=EventClient.http("GET",source+path,null);
            a.runOnUiThread(()->{if(a.isFinishing()||!source.equals(EventClient.base())||!historyResponseMatches(chart,identity,r))return;
                JSONArray rows=r.optJSONArray("bars");chart.prependHistory(rows);
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
                new AlertDialog.Builder(a).setTitle("Архив торгового периода · не LIVE").setItems(labels,(d,pos)->{
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
    public static void populate(SparklineView chart,JSONObject s){
        JSONObject d=s.optJSONObject("decision"),cfg=s.optJSONObject("config");chart.setMarketIdentity(marketIdentity(s));
        chart.setHistoryContext(s.optString("market_scope"),cfg==null?s.optString("timeframe","M5"):cfg.optString("timeframe","M5"),s.optString("market_history_generation"));
        JSONObject raw=rawChart(s);
        if(raw!=null){
            boolean matches=sameChartMarket(s,raw);JSONObject display=new JSONObject();
            try{display.put("chart_read_only",true).put("chart_status",raw.optString("status"))
                .put("chart_reason",matches?raw.optString("reason"):"Свечи не соответствуют выбранному инструменту, счёту или периоду; ожидаем данные MT5.")
                .put("chart_offset_minutes",raw.optInt("offset_minutes",raw.optInt("chart_offset_minutes",raw.optInt("clock_offset_minutes",0))))
                .put("client_offline",s.optBoolean("client_offline"));}catch(JSONException ignored){}
            chart.setMarket(matches?raw.optJSONArray("bars"):new JSONArray(),null,null,null,"CHART_ONLY",
                matches?raw.optJSONObject("live_bar"):null,null,display);
        }else chart.setMarket(s.optJSONArray("bars"),d==null?null:d.optJSONArray("levels"),s.optJSONArray("positions"),
                d==null?null:d.optJSONArray("structure"),"SCENARIO_V2",s.optJSONObject("live_bar"),s.optJSONArray("live_structure"),s.optJSONObject("forecast"));
        updateControls(chart);
    }
    private static String chartTitle(JSONObject s){
        JSONObject raw=rawChart(s);
        if(raw!=null)return s.optBoolean("client_offline")?"СВЕЧИ MT5 · КЭШ · НЕТ СВЯЗИ":"СВЕЧИ MT5 · ТОЛЬКО ПРОСМОТР";
        return s.optBoolean("client_offline")?"КАРТА · КЭШ · НЕТ СВЯЗИ":"СЦЕНАРИИ · LIVE / ИСТОРИЯ";
    }
    private static void open(Activity a,JSONObject snapshot){
        if(a.isFinishing())return;
        Dialog dialog=new Dialog(a);LinearLayout box=new LinearLayout(a);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(12,12,12,12);box.setBackgroundColor(0xff141125);
        TextView title=new TextView(a);title.setText(snapshot==null?chartTitle(EventClient.state()):"ИСХОДНЫЙ ПРОГНОЗ · НЕ LIVE");title.setTextColor(0xffdddded);title.setTextSize(16);box.addView(title);
        SparklineView chart=new SparklineView(a);chart.setArchive(snapshot!=null);
        TimeframeViewer viewer=snapshot==null?viewer(a):null;
        if(viewer!=null)box.addView(viewer.bind(chart));
        box.addView(chart,new LinearLayout.LayoutParams(-1,0,1));box.addView(controls(a,chart,snapshot!=null));
        Button close=new Button(a);close.setText("ЗАКРЫТЬ КАРТУ");box.addView(close);close.setOnClickListener(v->dialog.dismiss());
        dialog.setContentView(box);dialog.show();if(dialog.getWindow()!=null)dialog.getWindow().setLayout(-1,-1);
        if(snapshot!=null){
            JSONObject f=snapshot.optJSONObject("forecast");
            String recordedClock=f==null?"":f.optString("history_clock");
            if(recordedClock.isEmpty())title.setText("АРХИВ · ВРЕМЯ СВЕЧЕЙ НЕ ПРОВЕРЕНО · НЕ LIVE");
            else if(!recordedClock.equals(EventClient.state().optString("market_history_generation")))
                title.setText("АРХИВ · ДРУГАЯ НАСТРОЙКА ВРЕМЕНИ · НЕ LIVE");
            populate(chart,snapshot);return;
        }
        if(viewer!=null){viewer.update(EventClient.state());dialog.setOnDismissListener(d->viewer.unbind(chart));return;}
        Handler handler=new Handler(Looper.getMainLooper());Runnable update=new Runnable(){public void run(){if(!dialog.isShowing())return;JSONObject state=EventClient.state();title.setText(chartTitle(state));populate(chart,state);handler.postDelayed(this,1000);}};
        dialog.setOnDismissListener(d->handler.removeCallbacks(update));handler.post(update);
    }
}
