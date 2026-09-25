package com.openai.fxm1;

import android.graphics.*;
import org.json.*;
import java.util.*;

/** Draws only Bridge-supplied conditional routes. Never invents prices or trades. */
final class ScenarioMapRenderer {
    private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Canvas c;
    private final float d,w,h,left,right,split,top,bottom;
    private double low=Double.POSITIVE_INFINITY,high=Double.NEGATIVE_INFINITY;
    private static final int GREEN=0xff42d67a,RED=0xffff4857,ALT=0xffffc857,MUTED=0xffaaa7bf;
    private ScenarioMapRenderer(Canvas c,int width,int height,float density){
        this.c=c;d=density;w=width;h=height;left=8*d;right=w-58*d;
        split=left+(right-left)*.42f;top=55*d;bottom=h-41*d;
    }
    static void draw(Canvas canvas,int width,int height,float density,JSONArray bars,JSONArray structure,
                     JSONObject live,JSONObject f,JSONArray positions){
        new ScenarioMapRenderer(canvas,width,height,density).draw(bars,structure,live,f,positions);
    }
    private float y(double v){return top+(float)((high-v)/(high-low))*(bottom-top);}
    private void bound(double v){if(Double.isFinite(v)&&v>0){low=Math.min(low,v);high=Math.max(high,v);}}
    private static String price(double v){return String.format(Locale.US,"%.5f",v);}
    private void text(String s,float x,float y,int color,float size){
        p.setPathEffect(null);p.setStyle(Paint.Style.FILL);p.setColor(color);p.setTextSize(size*d);
        c.drawText(s,x,y,p);
    }
    private void line(float x1,float y1,float x2,float y2,int color,float width,boolean dash){
        p.setStyle(Paint.Style.STROKE);p.setColor(color);p.setStrokeWidth(width*d);
        p.setPathEffect(dash?new DashPathEffect(new float[]{5*d,4*d},0):null);
        c.drawLine(x1,y1,x2,y2,p);p.setPathEffect(null);p.setStyle(Paint.Style.FILL);
    }
    private final ArrayList<Float> labelRows=new ArrayList<>();
    private void level(double v,String label,int color){
        if(!Double.isFinite(v)||v<=0)return;
        float yy=y(v);line(left,yy,right,yy,color,.7f,true);
        if(label.isEmpty())return;
        float labelY=yy-4*d;
        for(int n=0;n<12;n++){
            boolean clear=true;for(float used:labelRows)if(Math.abs(labelY-used)<12*d){clear=false;break;}
            if(clear)break;labelY+=12*d;
        }
        labelY=Math.max(top+12*d,Math.min(bottom-4*d,labelY));labelRows.add(labelY);
        p.setTextSize(9*d);float tw=p.measureText(label);
        p.setColor(0xeb141125);c.drawRect(split+4*d,labelY-10*d,Math.min(right,split+10*d+tw),labelY+2*d,p);
        text(label,split+7*d,labelY,color,9);
    }
    private void draw(JSONArray bars,JSONArray structure,JSONObject live,JSONObject f,JSONArray positions){
        JSONArray routes=f.optJSONArray("scenarios");JSONObject levels=f.optJSONObject("entry_levels"),active=f.optJSONObject("active_scenario");
        int start=Math.max(0,bars.length()-24);
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b!=null){bound(b.optDouble("low"));bound(b.optDouble("high"));}}
        if(live!=null){bound(live.optDouble("low"));bound(live.optDouble("high"));}
        double current=f.optDouble("live_price",Double.NaN);bound(current);
        if(levels!=null)for(String name:new String[]{"BUY","SELL"}){
            JSONObject l=levels.optJSONObject(name);if(l!=null){bound(l.optDouble("trigger"));bound(l.optDouble("invalidation"));}}
        if(active!=null){bound(active.optDouble("entry"));bound(active.optDouble("invalidation"));}
        bound(f.optDouble("support"));bound(f.optDouble("resistance"));
        if(routes!=null)for(int i=0;i<routes.length();i++){
            JSONArray path=routes.optJSONObject(i).optJSONArray("path");if(path==null)continue;
            for(int j=0;j<path.length();j++){JSONObject point=path.optJSONObject(j);if(point!=null){
                double v=point.optDouble("price"),u=Math.max(0,point.optDouble("uncertainty",0));bound(v-u);bound(v+u);}}}
        if(!Double.isFinite(low)||!Double.isFinite(high)||high<=low||bottom<=top||right<=split)return;
        double margin=(high-low)*.10;low-=margin;high+=margin;
        int primarySide=f.optInt("side");
        if(routes!=null&&routes.length()>0){
            JSONObject a=routes.optJSONObject(0),b=routes.optJSONObject(1);
            text("ОСНОВНОЙ "+(primarySide>0?"BUY":"SELL")+" · вес "+Math.round(a.optDouble("model_weight",a.optDouble("probability"))*100),left,16*d,primarySide>0?GREEN:RED,11);
            if(b!=null)text("АЛЬТЕРНАТИВА "+(b.optInt("side")>0?"BUY":"SELL")+" · вес "+Math.round(b.optDouble("model_weight",b.optDouble("probability"))*100),left,33*d,ALT,10);
        }else text("WAIT · нет подтверждённого сценария",left,19*d,MUTED,11);
        text("RANGE: вес "+Math.round(f.optDouble("range_weight")*100),split,47*d,MUTED,9);
        text("ИСТОРИЯ MT5",left,47*d,MUTED,9);
        for(int i=0;i<5;i++){
            float yy=top+(bottom-top)*i/4;line(left,yy,right,yy,0xff312b43,.6f,false);
            text(price(high-(high-low)*i/4),right+4*d,yy+3*d,MUTED,9);
        }
        line(split,top,split,bottom,0xff756b89,.8f,true);
        int count=bars.length()-start+(live==null?0:1);float step=(split-left-9*d)/Math.max(1,count);
        HashMap<Long,Float> xs=new HashMap<>();
        for(int i=start;i<bars.length();i++){
            JSONObject b=bars.optJSONObject(i);if(b==null)continue;
            float xx=left+step*(i-start+.5f);xs.put(b.optLong("time"),xx);candle(b,xx,step*.30f);
        }
        if(live!=null)candle(live,left+step*(count-.5f),step*.30f);
        float px=Float.NaN,py=Float.NaN;
        for(int i=0;i<structure.length();i++){
            JSONObject s=structure.optJSONObject(i);if(s==null)continue;Float xx=xs.get(s.optLong("time"));if(xx==null)continue;
            float yy=y(s.optDouble("price"));
            if(Float.isFinite(px))line(px,py,xx,yy,0xffbcb6d0,.8f,false);
            if(i>=structure.length()-4)text(s.optString("label"),xx,yy-5*d,0xffbcb6d0,9);
            px=xx;py=yy;
        }
        // Price levels are actual Bridge values. Labels are separated vertically, not prices.
        level(f.optDouble("resistance"),"Сопротивление "+price(f.optDouble("resistance")),0xffbf7582);
        level(f.optDouble("support"),"Поддержка "+price(f.optDouble("support")),0xff76af94);
        if(levels!=null){
            for(String side:new String[]{"BUY","SELL"}){
                JSONObject l=levels.optJSONObject(side);if(l!=null)level(l.optDouble("trigger"),side+(side.equals("BUY")?" > ":" < ")+price(l.optDouble("trigger")),0xff879bb4);
            }
        }
        if(routes!=null&&routes.length()>0){
            JSONObject first=routes.optJSONObject(0);
            double cancel=first.optDouble("invalidation",Double.NaN);
            if(active==null||Math.abs(active.optDouble("invalidation")-cancel)>1e-9)
                level(cancel,"Отмена "+(first.optInt("side")>0?"BUY ":"SELL ")+price(cancel),0xffc39cda);
        }
        if(active!=null)level(active.optDouble("invalidation"),"Активный "+(active.optInt("side")>0?"BUY":"SELL")+": отмена",0xffffb04d);
        if(routes!=null)for(int i=Math.min(1,routes.length()-1);i>=0;i--)route(routes.optJSONObject(i),i==0,current);
        if(Double.isFinite(current)){
            p.setColor(0xffeeeeff);c.drawCircle(split,y(current),3*d,p);
            text("LIVE",split-29*d,y(current)-6*d,0xffeeeeff,10);
        }
        text("Будущие ветки — условия, не готовые свечи",left,h-25*d,MUTED,9);
        text("Веса — не вероятность · нажми для полного экрана",left,h-10*d,MUTED,8.5f);
    }
    private void candle(JSONObject b,float x,float half){
        double o=b.optDouble("open"),cl=b.optDouble("close");int col=cl>=o?GREEN:RED;
        line(x,y(b.optDouble("high")),x,y(b.optDouble("low")),col,.8f,false);
        p.setColor(col);c.drawRect(x-Math.max(.7f*d,half),Math.min(y(o),y(cl)),x+Math.max(.7f*d,half),Math.max(Math.min(y(o),y(cl))+d,Math.max(y(o),y(cl))),p);
    }
    private void route(JSONObject r,boolean primary,double current){
        if(r==null)return;JSONArray points=r.optJSONArray("path");if(points==null||points.length()<2)return;
        int color=primary?(r.optInt("side")>0?GREEN:RED):ALT;
        float end=right-7*d,span=end-split;
        Path band=new Path();
        for(int i=0;i<points.length();i++){
            JSONObject q=points.optJSONObject(i);float x=split+span*q.optInt("minutes")/15f;
            float yy=y(q.optDouble("price")+q.optDouble("uncertainty",0));if(i==0)band.moveTo(x,yy);else band.lineTo(x,yy);
        }
        for(int i=points.length()-1;i>=0;i--){JSONObject q=points.optJSONObject(i);band.lineTo(split+span*q.optInt("minutes")/15f,y(q.optDouble("price")-q.optDouble("uncertainty",0)));}
        band.close();p.setColor(Color.argb(14,Color.red(color),Color.green(color),Color.blue(color)));c.drawPath(band,p);
        float px=split,py=y(current);
        for(int i=1;i<points.length();i++){
            JSONObject q=points.optJSONObject(i);float x=split+span*q.optInt("minutes")/15f,yy=y(q.optDouble("price"));
            line(px,py,x,yy,color,primary?2.6f:1.9f,!primary);
            if(i==points.length()-1){
                double angle=Math.atan2(yy-py,x-px);float size=8*d;
                line(x,yy,x-size*(float)Math.cos(angle-.55),yy-size*(float)Math.sin(angle-.55),color,2,false);
                line(x,yy,x-size*(float)Math.cos(angle+.55),yy-size*(float)Math.sin(angle+.55),color,2,false);
            }
            String label=q.optString("label",i==points.length()-1?"T2":"");
            if(!label.isEmpty()&&!label.equals("Пробой")){
                String tag=(primary?"":"ALT ")+label;
                text(tag,Math.min(x+3*d,right-40*d),Math.max(top+11*d,Math.min(bottom-3*d,yy+(primary?-7*d:13*d))),color,10);
            }
            px=x;py=yy;
        }
    }
}
