package com.openai.fxm1;

import android.graphics.*;
import org.json.*;
import java.util.*;

/** Price history and detected boundaries are factual; right-hand routes are conditional. */
final class ScenarioMapRenderer {
    private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Canvas c;
    private final float d,w,h,left,right;
    private float split,top,bottom;
    private double low=Double.POSITIVE_INFINITY,high=Double.NEGATIVE_INFINITY;
    private final ArrayList<Float> labelRows=new ArrayList<>();
    private static final int GREEN=0xff42d67a,RED=0xffff4857,ALT=0xffffc857,MUTED=0xffaaa7bf;
    private static final int[] ALTS={ALT,0xff5bd6ff,0xffdd91ff};
    private boolean historical,stale;
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
    private static String price(double v){return String.format(Locale.US,"%.5f",v);}
    private void text(String s,float x,float yy,int color,float size){
        p.setPathEffect(null);p.setStyle(Paint.Style.FILL);p.setColor(color);p.setTextSize(size*d);
        float available=w-x-4*d;
        if(p.measureText(s)>available){while(s.length()>1&&p.measureText(s+"…")>available)s=s.substring(0,s.length()-1);s+="…";}
        c.drawText(s,x,yy,p);
    }
    private void line(float x1,float y1,float x2,float y2,int color,float width,boolean dash){
        p.setStyle(Paint.Style.STROKE);p.setColor(color);p.setStrokeWidth(width*d);
        p.setPathEffect(dash?new DashPathEffect(new float[]{5*d,4*d},0):null);
        c.drawLine(x1,y1,x2,y2,p);p.setPathEffect(null);p.setStyle(Paint.Style.FILL);
    }
    private void level(double v,String label,int color){
        if(!Double.isFinite(v)||v<=0||v<low||v>high)return;
        float yy=y(v);line(left,yy,right,yy,color,.7f,true);
        if(label.isEmpty())return;
        float labelY=yy-4*d;
        for(int n=0;n<12;n++){
            boolean clear=true;for(float used:labelRows)if(Math.abs(labelY-used)<11*d){clear=false;break;}
            if(clear)break;labelY+=11*d;
        }
        labelY=Math.max(top+10*d,Math.min(bottom-4*d,labelY));labelRows.add(labelY);
        p.setTextSize(8*d);float tw=p.measureText(label);
        p.setColor(0xf0141125);c.drawRect(split+3*d,labelY-9*d,Math.min(right,split+9*d+tw),labelY+2*d,p);
        text(label,split+5*d,labelY,color,8);
    }
    private int routeColor(JSONObject s,int i){return stale?MUTED:i==0?(s.optInt("side")>0?GREEN:s.optInt("side")<0?RED:0xffbbbbcf):ALTS[(i-1)%3];}
    private void draw(JSONArray bars,JSONArray structure,JSONObject live,JSONArray liveStructure,JSONObject f,JSONArray positions){
        boolean v3=f.optInt("map_version")>=3,valid=f.optInt("map_version")>=2;
        historical=f.optBoolean("history_only");stale=f.optBoolean("stale");
        JSONArray routes=valid&&!historical?f.optJSONArray("scenarios"):null;
        JSONObject levels=valid&&!historical?f.optJSONObject("entry_levels"):null,active=historical?null:f.optJSONObject("active_scenario");
        int routeCount=routes==null?0:Math.min(4,routes.length());
        top=Math.max(55,routeCount*16+24)*d;bottom=h-42*d;
        split=historical?right:left+(right-left)*.44f;
        for(int i=0;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b!=null){bound(b.optDouble("low"));bound(b.optDouble("high"));}}
        if(live!=null){bound(live.optDouble("low"));bound(live.optDouble("high"));}
        double historyLow=low,historyHigh=high,historyRange=Math.max(1e-8,historyHigh-historyLow);
        double current=historical?Double.NaN:f.optDouble("live_price",live==null?Double.NaN:live.optDouble("close"));bound(current);
        if(levels!=null)for(String name:new String[]{"BUY","SELL"}){
            JSONObject l=levels.optJSONObject(name);if(l!=null){nearBound(l.optDouble("trigger"),historyLow,historyHigh,historyRange);nearBound(l.optDouble("invalidation"),historyLow,historyHigh,historyRange);}}
        if(active!=null){nearBound(active.optDouble("entry"),historyLow,historyHigh,historyRange);nearBound(active.optDouble("invalidation"),historyLow,historyHigh,historyRange);}
        if(routes!=null)for(int i=0;i<routeCount;i++){
            JSONObject r=routes.optJSONObject(i);JSONArray path=r==null?null:r.optJSONArray("path");if(path==null)continue;
            for(int j=0;j<path.length();j++){JSONObject pt=path.optJSONObject(j);if(pt!=null)nearBound(pt.optDouble("price"),historyLow,historyHigh,historyRange);}}
        if(!Double.isFinite(low)||!Double.isFinite(high)||high<=low||bottom<=top||right<=left)return;
        double margin=(high-low)*.10;low-=margin;high+=margin;
        if(historical){text("ИСТОРИЯ · LIVE продолжает работу отдельно",left,18*d,MUTED,10);}
        else if(routeCount==0)text(valid?"WAIT · нет ясной структуры":"Карта ждёт профиль / свежие данные",left,19*d,MUTED,10);
        else for(int i=0;i<routeCount;i++){
            JSONObject r=routes.optJSONObject(i);if(r==null)continue;
            String name=i==0?"MAIN":"ALT"+i;
            String title=v3?r.optString("title",r.optString("type")):((i==0?"ОСНОВНОЙ ":"АЛЬТЕРНАТИВА ")+(r.optInt("side")>0?"BUY":"SELL"));
            long score=Math.round(r.optDouble("quality_score",r.optDouble("model_weight",r.optDouble("probability"))*100));
            text(name+" · "+title+" · "+score+"/100",left,(16+16*i)*d,routeColor(r,i),9.5f);
        }
        text((f.optBoolean("archive")?"СНИМОК ПРОГНОЗА · НЕ LIVE":stale?"ДАННЫЕ УСТАРЕЛИ · ВХОД ЗАПРЕЩЁН":"ИСТОРИЯ MT5"),left,top-7*d,stale?0xffffb04d:MUTED,8);
        for(int i=0;i<5;i++){
            float yy=top+(bottom-top)*i/4;line(left,yy,right,yy,0xff312b43,.6f,false);
            text(price(high-(high-low)*i/4),right+4*d,yy+3*d,MUTED,8.5f);
        }
        if(!historical)line(split,top,split,bottom,0xff756b89,.8f,true);
        int count=bars.length()+(live==null?0:1);float step=(split-left-8*d)/Math.max(1,count);
        HashMap<Long,Float> xs=new HashMap<>();
        long first=bars.optJSONObject(0).optLong("time"),last=bars.optJSONObject(bars.length()-1).optLong("time");
        long interval=bars.length()>1?Math.max(1,last-bars.optJSONObject(bars.length()-2).optLong("time")):300;
        for(int i=0;i<bars.length();i++){
            JSONObject b=bars.optJSONObject(i);if(b==null)continue;
            float xx=left+step*(i+.5f);xs.put(b.optLong("time"),xx);candle(b,xx,step*.30f);
        }
        if(live!=null){float xx=left+step*(count-.5f);xs.put(live.optLong("time"),xx);candle(live,xx,step*.30f);}
        float previousX=Float.NaN,previousY=0;
        if(structure!=null)for(int i=0;i<structure.length();i++){
            JSONObject s=structure.optJSONObject(i);if(s==null)continue;Float xx=xs.get(s.optLong("time"));double v=s.optDouble("price");if(xx==null||v<low||v>high)continue;
            float yy=y(v);if(!Float.isNaN(previousX))line(previousX,previousY,xx,yy,0xff914dff,1f,false);
            p.setColor(0xff914dff);c.drawCircle(xx,yy,2.5f*d,p);
            text(s.optString("label"),xx-4*d,Math.max(top+8*d,yy-5*d),0xff914dff,8);previousX=xx;previousY=yy;
        }
        // Provisional structure describes already observed current-bar extremes,
        // not future route nodes. Hide it when browsing old candles.
        if(!historical&&live!=null&&liveStructure!=null){
            float prevX=Float.NaN,prevY=0;
            for(int i=0;i<liveStructure.length();i++){
                JSONObject s=liveStructure.optJSONObject(i);if(s==null)continue;
                Float xx=xs.get(s.optLong("time"));double v=s.optDouble("price");
                if(xx==null||!Double.isFinite(v)||v<low||v>high)continue;
                float yy=y(v);
                if(!Float.isNaN(prevX))line(prevX,prevY,xx,yy,0xffffb04d,1.2f,true);
                if(s.optBoolean("provisional",false)){
                    p.setColor(0xffffb04d);c.drawCircle(xx,yy,3*d,p);
                    text(s.optString("label"),xx+3*d,Math.max(top+8*d,yy-5*d),0xffffb04d,8);
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
                    long ta=Math.max(first,pat.optLong("started_at",first));long tb=last+interval;
                    float xa=left+step*((ta-first)/(float)interval+.5f),xb=split-3*d;
                    double va=lineValue(line,ta),vb=lineValue(line,tb);
                    int saved=c.save();c.clipRect(left,top,split,bottom);
                    line(xa,y(va),xb,y(vb),i==0?0xffe2dbff:0xff8d879f,1.25f,false);c.restoreToCount(saved);
                }
            }
        }
        if(historical){
            text(new java.text.SimpleDateFormat("dd.MM HH:mm",Locale.US).format(new Date(first*1000))+" — "+new java.text.SimpleDateFormat("dd.MM HH:mm",Locale.US).format(new Date(last*1000)),left,h-24*d,MUTED,9);
            text("Свайп: история · масштаб: − / + · LIVE: вернуться",left,h-9*d,MUTED,8);return;
        }
        if(levels!=null){
            for(String side:new String[]{"BUY","SELL"}){JSONObject l=levels.optJSONObject(side);if(l!=null)level(l.optDouble("trigger"),side+" "+price(l.optDouble("trigger")),0xff879bb4);}
            level(f.optDouble("support"),"Поддержка "+price(f.optDouble("support")),0xff789e8d);
            level(f.optDouble("resistance"),"Сопротивление "+price(f.optDouble("resistance")),0xffae7785);
        }
        if(routeCount>0){JSONObject r=routes.optJSONObject(0);level(r.optDouble("invalidation"),"Отмена "+(r.optInt("side")>0?"BUY ":"SELL ")+price(r.optDouble("invalidation")),0xffa996b6);}
        if(active!=null)level(active.optDouble("invalidation"),"Активный "+(active.optInt("side")>0?"BUY":"SELL")+": отмена",0xffffb04d);
        for(int i=routeCount-1;i>=0;i--)route(routes.optJSONObject(i),i,current);
        if(Double.isFinite(current)){
            p.setColor(0xffeeeeff);c.drawCircle(split,clippedY(current),3*d,p);
            text("LIVE",split-29*d,clippedY(current)-6*d,0xffeeeeff,9);
        }
        text("Гипотезы: события, не готовые свечи и не время прихода",left,h-25*d,MUTED,8);
        text("Оценка — не вероятность · свайп: история · нажми: полный экран",left,h-10*d,MUTED,8);
    }
    private double lineValue(JSONObject l,long t){return l.optDouble("price")+l.optDouble("slope")*(t-l.optDouble("t0"));}
    private void nearBound(double v,double lo,double hi,double range){if(v>=lo-1.2*range&&v<=hi+1.2*range)bound(v);}
    private void candle(JSONObject b,float x,float half){
        double o=b.optDouble("open"),cl=b.optDouble("close");int col=cl>=o?GREEN:RED;
        line(x,y(b.optDouble("high")),x,y(b.optDouble("low")),col,.8f,false);
        p.setColor(col);c.drawRect(x-Math.max(.7f*d,half),Math.min(y(o),y(cl)),x+Math.max(.7f*d,half),Math.max(Math.min(y(o),y(cl))+d,Math.max(y(o),y(cl))),p);
    }
    private void route(JSONObject r,int index,double current){
        if(r==null||!Double.isFinite(current))return;JSONArray pts=r.optJSONArray("path");if(pts==null||pts.length()<2)return;
        int color=routeColor(r,index);float span=right-7*d-split;
        float px=split,py=clippedY(current);
        for(int i=1;i<pts.length();i++){
            JSONObject q=pts.optJSONObject(i);if(q==null)continue;
            float x=split+span*i/(pts.length()-1f),yy=clippedY(q.optDouble("price"));
            line(px,py,x,yy,color,index==0?2.5f:1.8f,index!=0);
            if(i==pts.length()-1){double angle=Math.atan2(yy-py,x-px);float size=7*d;
                line(x,yy,x-size*(float)Math.cos(angle-.55),yy-size*(float)Math.sin(angle-.55),color,2,false);
                line(x,yy,x-size*(float)Math.cos(angle+.55),yy-size*(float)Math.sin(angle+.55),color,2,false);}
            String label=q.optString("label","");if(!label.isEmpty()){
                if(q.optDouble("price")<low||q.optDouble("price")>high)label+=" "+price(q.optDouble("price"));
                if(label.length()>23)label=label.substring(0,22)+"…";
                p.setTextSize(8*d);float tw=p.measureText(label);
                text(label,Math.max(split+3*d,Math.min(x-tw/2,right-tw)),Math.max(top+10*d,Math.min(bottom-3*d,yy+(index==0?-8*d:12*d))),color,8);
            }px=x;py=yy;
        }
    }
}
