package com.openai.fxm1;

import android.graphics.*;
import org.json.*;
import java.util.*;

/** Price history and detected boundaries are factual; right-hand routes are conditional. */
final class ScenarioMapRenderer {
    private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Canvas c;
    private final float d,w,h,left;
    private float right,split,top,bottom;
    private JSONObject formatting;
    private double low=Double.POSITIVE_INFINITY,high=Double.NEGATIVE_INFINITY;
    private final ArrayList<Annotation> annotations=new ArrayList<>();
    private static final class Annotation {String text;float x,y;int color,priority;
        Annotation(String text,float x,float y,int color,int priority){this.text=text;this.x=x;this.y=y;this.color=color;this.priority=priority;}}
    private boolean tied;
    private static final int GREEN=0xff42d67a,RED=0xffff4857,ALT=0xffffc857,MUTED=0xffaaa7bf;
    private static final int[] ALTS={ALT,0xff5bd6ff,0xffdd91ff};
    private boolean historical,stale,clientOffline,unverified;
    private ScenarioMapRenderer(Canvas c,int width,int height,float density){
        this.c=c;d=density;w=width;h=height;left=8*d;right=w-58*d;
    }
    static void draw(Canvas canvas,int width,int height,float density,JSONArray bars,JSONArray structure,
                     JSONObject live,JSONArray liveStructure,JSONObject f,JSONArray positions){
        new ScenarioMapRenderer(canvas,width,height,density).draw(bars,structure,live,liveStructure,f,positions);
    }
    private float y(double v){return top+(float)((high-v)/(high-low))*(bottom-top);}
    private float clippedY(double v){return Math.max(top,Math.min(bottom,y(v)));}
    private void bound(double v){if(Double.isFinite(v)&&v>0){low=Math.min(low,v);high=Math.max(high,v);}}
    private String price(double v){return SparklineView.priceText(formatting,v);}
    private static String utc(String pattern,long seconds){
        java.text.SimpleDateFormat format=new java.text.SimpleDateFormat(pattern,Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));return format.format(new Date(seconds*1000));
    }
    private String candleTimes(long first,long last){
        String pattern=first/86400==last/86400?"HH:mm":utc("yyyy",first).equals(utc("yyyy",last))?"dd.MM HH:mm":"dd.MM.yy HH:mm";
        return "Свечи "+utc(pattern,first)+" — "+utc(pattern,last)+" UTC";
    }
    private void text(String s,float x,float yy,int color,float size){
        p.setPathEffect(null);p.setStyle(Paint.Style.FILL);p.setColor(color);p.setTextSize(size*d);
        float available=w-x-4*d;
        if(p.measureText(s)>available){while(s.length()>1&&p.measureText(s+"…")>available)s=s.substring(0,s.length()-1);s+="…";}
        c.drawText(s,x,yy,p);
    }
    private void readOnlyHeading(JSONObject f){
        String symbol=f.optString("chart_symbol"),identity=symbol.isEmpty()?"":" · "+symbol+" "+f.optString("chart_timeframe",f.optString("timeframe","—"));
        text(ScenarioUi.rawChartLabel(f)+identity,left,18*d,0xffffb04d,10);
        text(clientOffline?"КЭШ · НЕТ СВЯЗИ С BRIDGE":"ТОЛЬКО ПРОСМОТР · ВХОД ЗАПРЕЩЁН",left,34*d,MUTED,9);
        String remaining=f.optString("chart_reason").replace('\n',' ');p.setTextSize(9*d);
        for(int i=0;i<3&&!remaining.isEmpty();i++){
            int length=p.breakText(remaining,true,w-left-8*d,null);
            if(length<=0)break;
            if(length<remaining.length()&&i<2){int space=remaining.lastIndexOf(' ',length);if(space>0)length=space;}
            String row=remaining.substring(0,length);remaining=remaining.substring(length).trim();
            text(row+(i==2&&!remaining.isEmpty()?"…":""),left,(49+i*12)*d,MUTED,9);
        }
    }
    private void line(float x1,float y1,float x2,float y2,int color,float width,boolean dash){
        p.setStyle(Paint.Style.STROKE);p.setColor(color);p.setStrokeWidth(width*d);
        p.setPathEffect(dash?new DashPathEffect(new float[]{5*d,4*d},0):null);
        c.drawLine(x1,y1,x2,y2,p);p.setPathEffect(null);p.setStyle(Paint.Style.FILL);
    }
    private void annotate(String label,float x,float yy,int color,int priority){
        if(!label.isEmpty())annotations.add(new Annotation(label,x,yy,color,priority));
    }
    private void drawAnnotations(){
        RectF bounds=new RectF((split<right?split:left)+3*d,top+3*d,right-2*d,bottom-3*d);
        ArrayList<RectF> placed=new ArrayList<>();annotations.sort(Comparator.comparingInt(v->v.priority));
        for(Annotation a:annotations){
            p.setTextSize(8*d);String label=a.text;
            while(label.length()>1&&p.measureText(label)+4*d>bounds.width())label=label.substring(0,label.length()-2)+"…";
            float width=p.measureText(label)+4*d;
            RectF box=ChartLabelPlacer.place(placed,bounds,a.x,a.y-9*d,width,11*d);
            if(box==null)continue;placed.add(box);
            p.setStyle(Paint.Style.FILL);p.setColor(0xf5141125);c.drawRoundRect(box,2*d,2*d,p);
            text(label,box.left+2*d,box.top+8*d,a.color,8);
        }
    }
    private void level(double v,String label,int color){
        if(!Double.isFinite(v)||v<=0||v<low||v>high)return;
        float yy=y(v);line(left,yy,right,yy,color,.7f,true);
        int priority=label.startsWith("Активный")?0:label.startsWith("BUY")||label.startsWith("SELL")?1:label.startsWith("Отмена")?2:4;
        annotate(label,split+3*d,yy-4*d,color,priority);
    }
    private float timeX(JSONArray bars,long t,float step){
        for(int i=0;i<bars.length();i++){
            long cur=bars.optJSONObject(i).optLong("time");
            if(cur==t)return left+step*(i+.5f);
            if(cur>t){if(i==0)return left+step*.5f;
                long prev=bars.optJSONObject(i-1).optLong("time");
                return left+step*(i-.5f+(t-prev)/(float)(cur-prev));}
        }
        return split-3*d;
    }
    private int routeColor(JSONObject s,int i){return stale?MUTED:i==0?(s.optInt("side")>0?GREEN:s.optInt("side")<0?RED:0xffbbbbcf):ALTS[(i-1)%3];}
    private void draw(JSONArray bars,JSONArray structure,JSONObject live,JSONArray liveStructure,JSONObject f,JSONArray positions){
        formatting=f;
        unverified=f.optBoolean("chart_read_only");
        boolean plain="CANDLES".equals(f.optString("chart_display_mode"));
        boolean v3=f.optInt("map_version")>=3,valid=!plain&&f.optInt("map_version")>=2&&!unverified&&!f.optBoolean("chart_forecast_rejected");
        historical=f.optBoolean("history_only");clientOffline=f.optBoolean("client_offline");stale=f.optBoolean("stale")||clientOffline;tied="TIED".equals(f.optString("selection_status"));
        JSONArray routes=valid&&!historical?f.optJSONArray("scenarios"):null;
        JSONObject levels=valid&&!v3&&!historical?f.optJSONObject("entry_levels"):null,active=historical||unverified?null:f.optJSONObject("active_scenario");
        // The trading chart is a structural Scenario Map. The independent analogue
        // price forecast is retained by Bridge for research/evaluation, but it must
        // never paint a synthetic future path on the live trading chart.
        int routeCount=routes==null?0:Math.min(2,routes.length());
        top=(unverified?86:Math.max(55,routeCount*16+24+(tied?14:0)))*d;bottom=h-(historical||unverified?42:76)*d;
        for(int i=0;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b!=null){bound(b.optDouble("low"));bound(b.optDouble("high"));}}
        if(live!=null){bound(live.optDouble("low"));bound(live.optDouble("high"));}
        double historyLow=low,historyHigh=high,historyRange=Math.max(1e-8,historyHigh-historyLow);
        double current=historical||unverified?Double.NaN:f.optDouble("live_price",live==null?Double.NaN:live.optDouble("close"));bound(current);
        if(levels!=null)for(String name:new String[]{"BUY","SELL"}){
            JSONObject l=levels.optJSONObject(name);if(l!=null){nearBound(l.optDouble("trigger"),historyLow,historyHigh,historyRange);nearBound(l.optDouble("invalidation"),historyLow,historyHigh,historyRange);}}
        if(active!=null){nearBound(active.optDouble("entry"),historyLow,historyHigh,historyRange);nearBound(active.optDouble("invalidation"),historyLow,historyHigh,historyRange);}
        if(routes!=null)for(int i=0;i<routeCount;i++){
            JSONObject r=routes.optJSONObject(i);JSONArray path=r==null?null:r.optJSONArray("path");if(path==null)continue;
            for(int j=0;j<path.length();j++){JSONObject pt=path.optJSONObject(j);if(pt!=null)nearBound(pt.optDouble("price"),historyLow,historyHigh,historyRange);}}
        boolean showPositions=!historical&&!unverified&&!f.optBoolean("archive");
        if(showPositions&&positions!=null)for(int i=0;i<positions.length();i++){
            JSONObject position=positions.optJSONObject(i);if(!positionMatches(f,position))continue;
            bound(position.optDouble("price_open"));bound(position.optDouble("sl"));
        }
        if(unverified)readOnlyHeading(f);
        if(!Double.isFinite(low)||!Double.isFinite(high)||bottom<=top||right<=left){
            if(unverified)text("Нет доступных свечей MT5",left,top+20*d,MUTED,11);return;
        }
        // A flat or sub-tick market is still real data; give it a readable tick-scale range.
        double minimumSpan=4*Math.pow(10,-SparklineView.priceDigits(f));
        if(high-low<minimumSpan){double center=(high+low)/2;low=Math.max(minimumSpan*.01,center-minimumSpan/2);high=low+minimumSpan;}
        double margin=(high-low)*.10;low-=margin;high+=margin;
        p.setTextSize(8.5f*d);float widest=0;
        for(int i=0;i<5;i++)widest=Math.max(widest,p.measureText(price(high-(high-low)*i/4)));
        right=w-Math.max(58*d,widest+10*d);
        if(right<=left)return;
        boolean futurePanel=!historical&&!unverified&&valid&&routeCount>0;
        // Reserve space only for actual conditional paths. WAIT does not invent
        // a future panel or compress factual candles to make room for a fan.
        split=futurePanel?left+(right-left)*.48f:right;
        if(!unverified){
        if(historical){text(clientOffline?"ИСТОРИЯ · КЭШ · НЕТ СВЯЗИ":"ИСТОРИЯ · LIVE продолжает работу отдельно",left,18*d,MUTED,10);}
        else if(routeCount==0)text(plain?"СВЕЧИ MT5":valid?"NO CLEAR SCENARIO · WAIT":"Карта ждёт профиль / свежие данные",left,19*d,MUTED,10);
        else for(int i=0;i<routeCount;i++){
            JSONObject r=routes.optJSONObject(i);if(r==null)continue;
            String name=ScenarioUi.role(r,i);
            String title=v3?r.optString("title",r.optString("type")):((i==0?"ОСНОВНОЙ ":"АЛЬТЕРНАТИВА ")+(r.optInt("side")>0?"BUY":"SELL"));
            long score=Math.round(r.optDouble("quality_score",r.optDouble("model_weight",r.optDouble("probability"))*100));
            text(name+" · "+title+" · "+score+"/100",left,(16+16*i)*d,routeColor(r,i),9.5f);
        }
        }
        if(tied&&!historical&&!unverified)text("Равнозначные варианты · без предпочтения",left,(16+16*routeCount)*d,MUTED,8);
        String stamp=f.optDouble("data_asof",0)>0?utc("HH:mm:ss",(long)f.optDouble("data_asof"))+" UTC":"—";
        String symbol=f.optString("chart_symbol");
        String identity=symbol.isEmpty()?"":" · "+symbol+" "+f.optString("chart_timeframe",f.optString("timeframe","—"));
        String marketHeading="MT5 · "+f.optString("timeframe","—")+" · "+(symbol.isEmpty()?"":symbol+" · ")+(historical?"история":stamp);
        if(!unverified)text((f.optBoolean("archive")?"СНИМОК ПРОГНОЗА · НЕ LIVE"+identity:clientOffline?"КЭШ · НЕТ СВЯЗИ С BRIDGE"+identity:stale?"ДАННЫЕ УСТАРЕЛИ · ВХОД ЗАПРЕЩЁН"+identity:marketHeading),left,top-7*d,stale?0xffffb04d:MUTED,8);
        for(int i=0;i<5;i++){
            float yy=top+(bottom-top)*i/4;line(left,yy,right,yy,0xff312b43,.6f,false);
            text(price(high-(high-low)*i/4),right+4*d,yy+3*d,MUTED,8.5f);
        }
        if(futurePanel)line(split,top,split,bottom,0xff756b89,.8f,true);
        int count=bars.length()+(live==null?0:1);float step=(split-left-8*d)/Math.max(1,count);
        HashMap<Long,Float> xs=new HashMap<>();
        long first=bars.length()>0?bars.optJSONObject(0).optLong("time"):live.optLong("time"),last=bars.length()>0?bars.optJSONObject(bars.length()-1).optLong("time"):first;
        long interval=bars.length()>1?Math.max(1,last-bars.optJSONObject(bars.length()-2).optLong("time")):300;
        for(int i=0;i<bars.length();i++){
            JSONObject b=bars.optJSONObject(i);if(b==null)continue;
            float xx=left+step*(i+.5f);xs.put(b.optLong("time"),xx);candle(b,xx,step*.30f);
        }
        if(live!=null){float xx=left+step*(count-.5f);xs.put(live.optLong("time"),xx);candle(live,xx,step*.30f);}
        float previousX=Float.NaN,previousY=0;
        if(!unverified&&structure!=null)for(int i=0;i<structure.length();i++){
            JSONObject s=structure.optJSONObject(i);if(s==null)continue;Float xx=xs.get(s.optLong("time"));double v=s.optDouble("price");if(xx==null||v<low||v>high)continue;
            float yy=y(v);if(!Float.isNaN(previousX))line(previousX,previousY,xx,yy,0xff914dff,1f,false);
            p.setColor(0xff914dff);c.drawCircle(xx,yy,2.5f*d,p);
            text(s.optString("label"),xx-4*d,Math.max(top+8*d,yy-5*d),0xff914dff,8);previousX=xx;previousY=yy;
        }
        // Provisional structure describes already observed current-bar extremes,
        // not future route nodes. Hide it when browsing old candles.
        if(!historical&&!unverified&&live!=null&&liveStructure!=null){
            float prevX=Float.NaN,prevY=0;
            for(int i=0;i<liveStructure.length();i++){
                JSONObject s=liveStructure.optJSONObject(i);if(s==null)continue;
                Float xx=xs.get(s.optLong("time"));double v=s.optDouble("price");
                if(xx==null||!Double.isFinite(v)||v<low||v>high)continue;
                float yy=y(v);
                if(!Float.isNaN(prevX))line(prevX,prevY,xx,yy,0xffffb04d,1.2f,true);
                if(s.optBoolean("provisional",false)){
                    p.setColor(0xffffb04d);c.drawCircle(xx,yy,3*d,p);
                    if(!"LIVE".equals(s.optString("label")))text(s.optString("label"),xx+3*d,Math.max(top+8*d,yy-5*d),0xffffb04d,8);
                }
                prevX=xx;prevY=yy;
            }
        }
        if(routes!=null&&v3){
            Set<String> drawn=new HashSet<>();
            for(int i=0;i<routeCount;i++){
                JSONObject s=routes.optJSONObject(i),pat=s==null?null:s.optJSONObject("pattern");if(pat==null||!drawn.add(pat.optString("pattern_id")))continue;
                for(String kind:new String[]{"upper","lower"}){
                    JSONObject line=pat.optJSONObject(kind);if(line==null)continue;
                    long ta=Math.max(first,pat.optLong("started_at",first));long tb=f.optLong("boundary_asof",last+interval);
                    float xa=timeX(bars,ta,step),xb=split-3*d;
                    double va=lineValue(line,ta),vb=lineValue(line,tb);
                    int saved=c.save();c.clipRect(left,top,split,bottom);
                    line(xa,y(va),xb,y(vb),i==0?0xffe2dbff:0xff8d879f,1.25f,false);c.restoreToCount(saved);
                }
            }
        }
        if(unverified){
            java.text.SimpleDateFormat format=new java.text.SimpleDateFormat("dd.MM HH:mm",Locale.US);format.setTimeZone(TimeZone.getTimeZone("UTC"));
            text(format.format(new Date(first*1000))+" — "+format.format(new Date((live==null?last:live.optLong("time"))*1000)),left,h-24*d,MUTED,9);
            text(ScenarioUi.chartClockLabel(f)+" · прогноз скрыт",left,h-9*d,MUTED,8);return;
        }
        if(historical){
            text(candleTimes(first,last),left,h-24*d,MUTED,9);
            text("Свайп: история · масштаб: − / + · LIVE: вернуться",left,h-9*d,MUTED,8);return;
        }
        if(levels!=null){
            for(String side:new String[]{"BUY","SELL"}){JSONObject l=levels.optJSONObject(side);if(l!=null)level(l.optDouble("trigger"),side+" "+price(l.optDouble("trigger")),0xff879bb4);}
        }
        if(valid){
            level(f.optDouble("support"),"Поддержка "+price(f.optDouble("support")),0xff789e8d);
            level(f.optDouble("resistance"),"Сопротивление "+price(f.optDouble("resistance")),0xffae7785);
        }
        if(v3&&routes!=null)for(int i=0;i<routeCount;i++){
            JSONObject route=routes.optJSONObject(i);if(route==null)continue;
            double event=route.optDouble("event_level",Double.NaN);
            if(Double.isFinite(event))level(event,"Проверка "+ScenarioUi.role(route,i)+" "+price(event),0xffc7bbdd);
        }
        if(routeCount>0){JSONObject r=routes.optJSONObject(0);level(r.optDouble("invalidation"),"Отмена "+(r.optInt("side")>0?"BUY ":"SELL ")+price(r.optDouble("invalidation")),0xffa996b6);}
        if(active!=null)level(active.optDouble("invalidation"),"Активный "+(active.optInt("side")>0?"BUY":"SELL")+": отмена",0xffffb04d);
        if(showPositions&&positions!=null)for(int i=0;i<positions.length();i++){
            JSONObject position=positions.optJSONObject(i);if(!positionMatches(f,position))continue;
            String ticket="#"+position.optLong("ticket"),state=stale?"КЭШ ":"";
            positionLevel(position.optDouble("price_open"),state+"MT5 "+ticket+" "+(position.optInt("side")>0?"BUY ":"SELL ")+price(position.optDouble("price_open")));
            positionLevel(position.optDouble("sl"),state+"SL MT5 "+ticket+" "+price(position.optDouble("sl")));
        }
        if(routeCount==0&&futurePanel){
            String wait="NO CLEAR SCENARIO";
            p.setTextSize(9*d);float tw=p.measureText(wait);
            text(wait,Math.max(split+4*d,split+(right-split-tw)/2),top+18*d,MUTED,9);
            text("WAIT · только уровни и фактические свечи",split+5*d,top+34*d,MUTED,8);
        }else{
            for(int i=routeCount-1;i>=0;i--)route(routes.optJSONObject(i),i,current);
        }
        if(Double.isFinite(current)){
            p.setColor(0xffeeeeff);c.drawCircle(split,clippedY(current),3*d,p);
            String marker=f.optBoolean("archive")?"СНИМОК":clientOffline?"КЭШ":stale?"УСТАРЕЛО":"LIVE";
            p.setTextSize(9*d);text(marker,Math.max(left,split-p.measureText(marker)-3*d),clippedY(current)-6*d,0xffeeeeff,9);
        }
        drawAnnotations();
        text(candleTimes(first,live==null?last:live.optLong("time")),left,h-44*d,MUTED,8);
        boolean legacy=false;
        if(routes!=null)for(int i=0;i<routeCount;i++)legacy|=!hasPhaseMeaning(routes.optJSONObject(i));
        text(legacy?"Цвет — условная ветка; этапы входа не размечены":"Серый — до входа · цвет — после, не факт сделки",left,h-26*d,MUTED,8);
        text("Этапы условны · оценка — не вероятность · свайп: история",left,h-11*d,MUTED,8);
    }
    private static String symbolKey(String value){return value.replace("/","").trim().toUpperCase(Locale.ROOT);}
    private static boolean positionMatches(JSONObject f,JSONObject position){
        if(position==null||position.optLong("ticket")<=0||Math.abs(position.optInt("side"))!=1
            ||!Double.isFinite(position.optDouble("volume"))||position.optDouble("volume")<=0
            ||!Double.isFinite(position.optDouble("price_open"))||position.optDouble("price_open")<=0)return false;
        String symbol=symbolKey(position.optString("symbol"));
        return !symbol.isEmpty()&&(symbol.equals(symbolKey(f.optString("chart_symbol")))||symbol.equals(symbolKey(f.optString("chart_broker_symbol"))));
    }
    private void positionLevel(double value,String label){
        if(!Double.isFinite(value)||value<=0||value<low||value>high)return;
        int color=stale?MUTED:0xff70d0e0;float yy=y(value);
        line(left,yy,right,yy,color,1,false);annotate(label,split+3*d,yy-4*d,color,-1);
    }
    private double lineValue(JSONObject l,long t){return l.optDouble("price")+l.optDouble("slope")*(t-l.optDouble("t0"));}
    private void nearBound(double v,double lo,double hi,double range){if(v>=lo-1.2*range&&v<=hi+1.2*range)bound(v);}
    private void candle(JSONObject b,float x,float half){
        double o=b.optDouble("open"),cl=b.optDouble("close");int col=cl>=o?GREEN:RED;
        line(x,y(b.optDouble("high")),x,y(b.optDouble("low")),col,.8f,false);
        p.setColor(col);c.drawRect(x-Math.max(.7f*d,half),Math.min(y(o),y(cl)),x+Math.max(.7f*d,half),Math.max(Math.min(y(o),y(cl))+d,Math.max(y(o),y(cl))),p);
    }
    private static boolean hasPhaseMeaning(JSONObject r){
        JSONArray pts=r==null?null:r.optJSONArray("path");if(pts==null)return false;
        for(int i=1;i<pts.length();i++){
            JSONObject q=pts.optJSONObject(i);if(q==null)continue;
            if(!q.optString("phase").isEmpty()||!q.optString("anchor").isEmpty()
                ||"T1".equals(q.optString("label"))||"T2".equals(q.optString("label")))return true;
        }return false;
    }
    private static boolean preparation(JSONObject r,JSONObject destination){
        String phase=destination.optString("phase");
        if("PREPARATION".equals(phase)||"LIVE".equals(phase))return true;
        if("TRADE".equals(phase))return false;
        // Archived v3 paths identify targets by label/source anchor. Unlabelled v2 paths
        // retain their original branch styling; we cannot invent a confirmation event.
        if(!hasPhaseMeaning(r))return false;
        String label=destination.optString("label"),anchor=destination.optString("anchor");
        return !("T1".equals(label)||"T2".equals(label)||anchor.startsWith("TARGET"));
    }
    private void route(JSONObject r,int index,double current){
        if(r==null||!Double.isFinite(current))return;JSONArray pts=r.optJSONArray("path");if(pts==null||pts.length()<2)return;
        float span=right-7*d-split;
        float px=split,py=clippedY(current);
        for(int i=1;i<pts.length();i++){
            JSONObject q=pts.optJSONObject(i);if(q==null)continue;
            boolean preparing=preparation(r,q);int color=preparing?MUTED:routeColor(r,index);
            float x=split+span*i/(pts.length()-1f),yy=clippedY(q.optDouble("price"));
            line(px,py,x,yy,color,tied?2.1f:index==0?2.5f:1.8f,preparing||tied||index!=0);
            if(preparing&&q.optString("anchor").contains("CONFIRM")){
                p.setStyle(Paint.Style.STROKE);p.setColor(MUTED);p.setStrokeWidth(1.4f*d);
                c.drawCircle(x,yy,3.5f*d,p);p.setStyle(Paint.Style.FILL);
            }
            if(i==pts.length()-1&&!preparing){double angle=Math.atan2(yy-py,x-px);float size=7*d;
                line(x,yy,x-size*(float)Math.cos(angle-.55),yy-size*(float)Math.sin(angle-.55),color,2,false);
                line(x,yy,x-size*(float)Math.cos(angle+.55),yy-size*(float)Math.sin(angle+.55),color,2,false);}
            String label=q.optString("label","");if(!label.isEmpty()){
                if(q.optDouble("price")<low||q.optDouble("price")>high)label+=" "+price(q.optDouble("price"));
                if(label.length()>23)label=label.substring(0,22)+"…";
                p.setTextSize(8*d);float tw=p.measureText(label);
                annotate(label,Math.max(split+3*d,Math.min(x-tw/2,right-tw)),yy+(index==0?-8*d:12*d),color,label.startsWith("T")?2:3);
            }px=x;py=yy;
        }
    }
}
