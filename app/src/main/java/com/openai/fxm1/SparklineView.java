package com.openai.fxm1;
import android.content.Context;
import android.graphics.*;
import android.util.AttributeSet;
import android.view.View;
import org.json.*;
import java.util.*;

/** MT5 candles + confirmed/live structure + a separate model forecast zone. */
public class SparklineView extends View {
    private JSONArray bars=new JSONArray(),levels=new JSONArray(),positions=new JSONArray(),structure=new JSONArray(),liveStructure=new JSONArray();
    private JSONObject liveBar=null,forecast=new JSONObject();
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private String signal="WAIT",path="SEARCH";
    private static final int C_FORECAST=0xff5bd6ff;
    public SparklineView(Context c){super(c);}
    public SparklineView(Context c,AttributeSet a){super(c,a);}
    public SparklineView(Context c,AttributeSet a,int s){super(c,a,s);}
    public void setSignal(String s){signal=s;invalidate();}
    public void setValues(List<Double> ignored){}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p){
        JSONArray s=null,ls=null;JSONObject lb=null,fc=null;String r3Path="SEARCH";
        try{JSONObject state=EventClient.state(),decision=state.optJSONObject("decision");
            if(decision!=null){s=decision.optJSONArray("structure");r3Path=decision.optString("path","SEARCH");}
            lb=state.optJSONObject("live_bar");ls=state.optJSONArray("live_structure");fc=state.optJSONObject("forecast");
        }catch(Exception ignored){}
        setMarket(b,l,p,s,r3Path,lb,ls,fc);
    }
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String r3Path){setMarket(b,l,p,s,r3Path,null,null,null);}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String r3Path,JSONObject lb,JSONArray ls){setMarket(b,l,p,s,r3Path,lb,ls,null);}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String r3Path,JSONObject lb,JSONArray ls,JSONObject fc){
        bars=b==null?new JSONArray():b;levels=l==null?new JSONArray():l;positions=p==null?new JSONArray():p;
        structure=s==null?new JSONArray():s;path=r3Path==null?"SEARCH":r3Path;liveBar=lb;
        liveStructure=ls==null?new JSONArray():ls;forecast=fc==null?new JSONObject():fc;
        setContentDescription(mapDescription(forecast));invalidate();
    }
    private boolean detailedMap(){return forecast.optInt("map_version",0)>=2;}
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
    private void scenarioLevel(Canvas c,double value,String label,int color,float left,float right,double min,double max,float top,float height){
        if(!Double.isFinite(value)||value<=0||value<min||value>max)return;
        float yy=y(value,min,max,top,height);paint.setColor(color);paint.setStrokeWidth(dp(.9f));
        paint.setPathEffect(new DashPathEffect(new float[]{dp(4),dp(3)},0));c.drawLine(left,yy,right,yy,paint);
        paint.setPathEffect(null);paint.setTextSize(dp(7.5f));paint.setStyle(Paint.Style.FILL);
        c.drawText(label,left+dp(2),Math.max(top+dp(8),Math.min(top+height-dp(2),yy-dp(3))),paint);
    }
    private static boolean sameLevel(double a,double b){return Double.isFinite(a)&&Double.isFinite(b)&&Math.abs(a-b)<1e-9;}
    private void detailedLevels(Canvas c,float left,float right,double min,double max,float top,float height){
        JSONObject active=forecast.optJSONObject("active_scenario");JSONArray scenarios=forecast.optJSONArray("scenarios");
        JSONObject primary=scenarios==null?null:scenarios.optJSONObject(0);
        double stop=primary==null?Double.NaN:primary.optDouble("invalidation"),activeStop=active==null?Double.NaN:active.optDouble("invalidation");
        double support=forecast.optDouble("support"),resistance=forecast.optDouble("resistance");
        // A shared support/cancel price gets one readable label, not overprinted text.
        scenarioLevel(c,support,sameLevel(support,stop)||sameLevel(support,activeStop)?"":"SUPPORT",0x9942d67a,left,right,min,max,top,height);
        scenarioLevel(c,resistance,sameLevel(resistance,stop)||sameLevel(resistance,activeStop)?"":"RESIST",0x99ff4857,left,right,min,max,top,height);
        JSONObject entries=forecast.optJSONObject("entry_levels");
        if(entries!=null)for(String side:new String[]{"BUY","SELL"}){
            JSONObject v=entries.optJSONObject(side);if(v!=null)scenarioLevel(c,v.optDouble("trigger"),side+" "+priceText(v.optDouble("trigger")),0xff879bb4,left,right,min,max,top,height);
        }
        if(primary!=null)scenarioLevel(c,stop,sameLevel(stop,activeStop)?"":"Отмена "+scenarioSide(primary.optInt("side")),0xffa996b6,left,right,min,max,top,height);
        if(active!=null)scenarioLevel(c,active.optDouble("invalidation"),"Активный "+scenarioSide(active.optInt("side"))+": отмена",0xffffb04d,left,right,min,max,top,height);
    }
    private void detailedHeader(Canvas c,float futureLeft){
        paint.setStyle(Paint.Style.FILL);paint.setPathEffect(null);paint.setFakeBoldText(true);paint.setTextSize(dp(9));
        JSONArray scenarios=forecast.optJSONArray("scenarios");
        if(!hasScenarioMap(forecast)){
            paint.setColor(0xffb0aac7);c.drawText("WAIT · только уровни",futureLeft,dp(13),paint);
        }else for(int i=0;i<Math.min(2,scenarios.length());i++){
            JSONObject v=scenarios.optJSONObject(i);if(v==null)continue;
            paint.setColor(scenarioColor(v.optInt("side"),i==0));
            c.drawText((i==0?"MAIN ":"ALT ")+scenarioSide(v.optInt("side"))+" · вес "+Math.round(v.optDouble("model_weight",v.optDouble("probability",0))*100),futureLeft,dp(13+i*12),paint);
        }
        paint.setFakeBoldText(false);paint.setTextSize(dp(8));paint.setColor(0xffb0aac7);
        c.drawText("RANGE · вес "+Math.round(forecast.optDouble("range_weight",0)*100),futureLeft,dp(37),paint);
        JSONObject reversal=forecast.optJSONObject("reversal_status");
        if(reversal!=null){
            String status=reversal.optString("status","");
            String label="WAITING_CLOSE".equals(status)?"Разворот: закрытие":"WAITING_SIGNAL".equals(status)?"Разворот: ждём сигнал":
                "CANCELLED".equals(status)?"Разворот отменён":"OPENED".equals(status)?"Разворот исполнен":"READY".equals(status)?"Разворот: проверка":"";
            if(!label.isEmpty())c.drawText(label,dp(5),dp(48),paint);
        }
    }
    private void scenarioEnvelope(Canvas c,JSONArray points,int color,float left,float usable,double min,double max,float top,float height){
        if(!detailedMap()||points.length()<2)return;
        Path band=new Path();boolean first=true;
        for(int i=0;i<points.length();i++){
            JSONObject point=points.optJSONObject(i);if(point==null)continue;
            double price=point.optDouble("price",Double.NaN),width=point.optDouble("uncertainty",0);
            if(!Double.isFinite(price)||!Double.isFinite(width)||width<0)return;
            float xx=left+usable*Math.max(0f,Math.min(1f,point.optInt("minutes",0)/15f));
            float yy=y(price+width,min,max,top,height);if(first){band.moveTo(xx,yy);first=false;}else band.lineTo(xx,yy);
        }
        for(int i=points.length()-1;i>=0;i--){JSONObject point=points.optJSONObject(i);if(point==null)continue;
            float xx=left+usable*Math.max(0f,Math.min(1f,point.optInt("minutes",0)/15f));
            band.lineTo(xx,y(point.optDouble("price")-point.optDouble("uncertainty",0),min,max,top,height));}
        band.close();paint.setStyle(Paint.Style.FILL);paint.setPathEffect(null);
        paint.setColor(Color.argb(23,Color.red(color),Color.green(color),Color.blue(color)));c.drawPath(band,paint);
    }
    private boolean hasLive(){return liveBar!=null&&liveBar.length()>0&&liveBar.has("time");}
    private float dp(float x){return x*getResources().getDisplayMetrics().density;}
    private float y(double value,double min,double max,float top,float h){return top+(float)((max-value)/(max-min))*h;}
    private void candle(Canvas c,JSONObject b,float x,float half,double min,double max,float top,float height,boolean live){
        double open=b.optDouble("open"),close=b.optDouble("close");paint.setColor(close>=open?0xff42d67a:0xffff4857);paint.setStrokeWidth(dp(1));paint.setAlpha(live?185:255);
        c.drawLine(x,y(b.optDouble("high"),min,max,top,height),x,y(b.optDouble("low"),min,max,top,height),paint);
        float a=y(open,min,max,top,height),z=y(close,min,max,top,height);c.drawRect(x-half,Math.min(a,z),x+half,Math.max(Math.min(a,z)+dp(1),Math.max(a,z)),paint);paint.setAlpha(255);
    }
    private void drawStructure(Canvas c,JSONArray points,HashMap<Long,Float> xs,double min,double max,float top,float height,int color,boolean provisional){
        float px=Float.NaN,py=Float.NaN;paint.setColor(color);paint.setStrokeWidth(dp(provisional?1.35f:1f));paint.setTextSize(dp(9));paint.setPathEffect(provisional?new DashPathEffect(new float[]{dp(5),dp(3)},0):null);
        for(int i=0;i<points.length();i++){JSONObject s=points.optJSONObject(i);if(s==null)continue;Float x=xs.get(s.optLong("time"));if(x==null)continue;double price=s.optDouble("price",Double.NaN);if(!Double.isFinite(price)||price<min||price>max)continue;float yy=y(price,min,max,top,height);
            paint.setStyle(Paint.Style.STROKE);if(!Float.isNaN(px))c.drawLine(px,py,x,yy,paint);paint.setStyle(Paint.Style.FILL);c.drawCircle(x,yy,dp(provisional?3f:2.5f),paint);
            String label=s.optString("label","");if(!label.isEmpty()&&(!provisional||s.optBoolean("provisional",false)))c.drawText(label,x+dp(3),Math.max(top+dp(9),yy-dp(3)),paint);px=x;py=yy;}
        paint.setPathEffect(null);paint.setStyle(Paint.Style.FILL);
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
    private int forecastColor(){
        int side=forecast.optInt("side",0);if(side==0)side=forecast.optInt("candidate_side",0);
        return side>0?0xff42d67a:side<0?0xffff4857:0xff914dff;
    }
    private String pointProbability(JSONObject p){
        double up=p.optDouble("up_probability",0),down=p.optDouble("down_probability",0),range=p.optDouble("range_probability",0);
        if(up>=down&&up>=range)return "UP "+Math.round(up*100)+"%";
        if(down>=up&&down>=range)return "DN "+Math.round(down*100)+"%";
        return "RG "+Math.round(range*100)+"%";
    }
    public static boolean hasScenarioMap(JSONObject f){
        JSONArray s=f==null?null:f.optJSONArray("scenarios");
        return s!=null&&s.length()>0;
    }
    private int scenarioColor(int side,boolean primary){
        if(!primary)return 0xffffc857;
        return side>0?0xff42d67a:side<0?0xffff4857:0xff914dff;
    }
    private String scenarioSide(int side){return side>0?"BUY":side<0?"SELL":"RANGE";}
    private void drawScenarioMap(Canvas c,JSONArray scenarios,float startX,float startY,float futureLeft,float plotRight,double min,double max,float top,float height){
        if(scenarios==null||scenarios.length()==0)return;
        float usable=Math.max(dp(26),plotRight-futureLeft-dp(4));
        double support=forecast.optDouble("support",Double.NaN),resistance=forecast.optDouble("resistance",Double.NaN);
        paint.setTextSize(dp(8));paint.setStrokeWidth(dp(.7f));paint.setPathEffect(new DashPathEffect(new float[]{dp(4),dp(4)},0));
        if(!detailedMap()&&Double.isFinite(resistance)&&resistance>=min&&resistance<=max){
            paint.setColor(0x99ff4857);float yy=y(resistance,min,max,top,height);c.drawLine(futureLeft,yy,plotRight,yy,paint);c.drawText("RESIST",futureLeft+dp(2),yy-dp(3),paint);
        }
        if(!detailedMap()&&Double.isFinite(support)&&support>=min&&support<=max){
            paint.setColor(0x9942d67a);float yy=y(support,min,max,top,height);c.drawLine(futureLeft,yy,plotRight,yy,paint);c.drawText("SUPPORT",futureLeft+dp(2),yy-dp(3),paint);
        }
        paint.setPathEffect(null);
        for(int s=0;s<Math.min(2,scenarios.length());s++){
            JSONObject scenario=scenarios.optJSONObject(s);if(scenario==null)continue;
            JSONArray pts=scenario.optJSONArray("path");if(pts==null||pts.length()==0)continue;
            boolean primary=s==0;int side=scenario.optInt("side",0),color=scenarioColor(side,primary);
            scenarioEnvelope(c,pts,color,futureLeft,usable,min,max,top,height);
            paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(dp(primary?3.2f:2.0f));paint.setColor(color);
            paint.setPathEffect(primary?null:new DashPathEffect(new float[]{dp(7),dp(4)},0));
            Path path=new Path();path.moveTo(startX,startY);
            for(int i=0;i<pts.length();i++){
                JSONObject p=pts.optJSONObject(i);if(p==null)continue;
                float x=futureLeft+usable*Math.max(0f,Math.min(1f,p.optInt("minutes",0)/15f));
                float yy=y(p.optDouble("price"),min,max,top,height);path.lineTo(x,yy);
            }
            c.drawPath(path,paint);paint.setPathEffect(null);paint.setStyle(Paint.Style.FILL);
            JSONObject last=pts.optJSONObject(pts.length()-1);
            if(last!=null){float x=futureLeft+usable*Math.max(0f,Math.min(1f,last.optInt("minutes",15)/15f));float yy=y(last.optDouble("price"),min,max,top,height);c.drawCircle(x,yy,dp(primary?3.5f:2.8f),paint);}
            if(detailedMap()&&last!=null){
                paint.setTextSize(dp(7.5f));
                String label=("CONFIRMED_STRUCTURE".equals(scenario.optString("target_source"))?"Цель ":"Проекция ")+priceText(scenario.optDouble("target"));
                float yy=y(last.optDouble("price"),min,max,top,height);
                c.drawText(label,Math.max(futureLeft,plotRight-paint.measureText(label)),Math.max(top+dp(8),Math.min(top+height-dp(2),yy+(side>0?-dp(5):dp(11)))),paint);
            }
            long pct=Math.round(scenario.optDouble("probability",0)*100);
            paint.setTextSize(dp(primary?9f:8f));paint.setFakeBoldText(primary);
            if(!detailedMap())c.drawText((primary?"MAIN ":"ALT ")+scenarioSide(side)+" "+pct+"%",futureLeft+dp(2),top+dp(primary?12:25),paint);
            paint.setFakeBoldText(false);
        }
    }
    private void drawForecast(Canvas c,JSONArray projection,float startX,float startY,float futureLeft,float plotRight,double min,double max,float top,float height){
        if(!detailedMap())return; // Never resurrect the old +5/+10/+15 line during upgrade.
        JSONArray scenarios=forecast.optJSONArray("scenarios");
        if(detailedMap()&&!hasScenarioMap(forecast))return;
        if(scenarios!=null&&scenarios.length()>0){drawScenarioMap(c,scenarios,startX,startY,futureLeft,plotRight,min,max,top,height);return;}
        if(projection==null||projection.length()==0||!shouldDrawProjection(forecast))return;
        float usable=Math.max(dp(18),plotRight-futureLeft-dp(5));int n=projection.length(),color=forecastColor();
        Path band=new Path(),upper=new Path(),lower=new Path();
        for(int i=0;i<n;i++){JSONObject p=projection.optJSONObject(i);if(p==null)continue;float x=futureLeft+usable*(i+1f)/n,yy=y(p.optDouble("high"),min,max,top,height);if(i==0){band.moveTo(x,yy);upper.moveTo(x,yy);}else{band.lineTo(x,yy);upper.lineTo(x,yy);}}
        for(int i=n-1;i>=0;i--){JSONObject p=projection.optJSONObject(i);if(p==null)continue;float x=futureLeft+usable*(i+1f)/n,yy=y(p.optDouble("low"),min,max,top,height);band.lineTo(x,yy);}
        for(int i=0;i<n;i++){JSONObject p=projection.optJSONObject(i);if(p==null)continue;float x=futureLeft+usable*(i+1f)/n,yy=y(p.optDouble("low"),min,max,top,height);if(i==0)lower.moveTo(x,yy);else lower.lineTo(x,yy);}
        band.close();paint.setStyle(Paint.Style.FILL);paint.setColor(Color.argb(34,Color.red(color),Color.green(color),Color.blue(color)));paint.setPathEffect(null);c.drawPath(band,paint);
        paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(dp(.8f));paint.setColor(Color.argb(110,Color.red(color),Color.green(color),Color.blue(color)));paint.setPathEffect(new DashPathEffect(new float[]{dp(3),dp(3)},0));c.drawPath(upper,paint);c.drawPath(lower,paint);
        paint.setPathEffect(null);paint.setStrokeWidth(dp(2.8f));paint.setColor(color);
        float px=startX,py=startY;
        for(int i=0;i<n;i++){JSONObject p=projection.optJSONObject(i);if(p==null)continue;float x=futureLeft+usable*(i+1f)/n,yy=y(p.optDouble("center"),min,max,top,height);c.drawLine(px,py,x,yy,paint);px=x;py=yy;}
        paint.setStyle(Paint.Style.FILL);paint.setTextSize(dp(8.2f));paint.setColor(color);
        for(int i=0;i<n;i++){JSONObject p=projection.optJSONObject(i);if(p==null)continue;float x=futureLeft+usable*(i+1f)/n,yy=y(p.optDouble("center"),min,max,top,height);c.drawCircle(x,yy,dp(3.2f),paint);
            c.drawText("+"+p.optInt("minutes")+"m",x-dp(10),Math.min(top+height-dp(14),yy+dp(13)),paint);
            c.drawText(pointProbability(p),x-dp(13),Math.min(top+height-dp(3),yy+dp(23)),paint);}
        long up=Math.round(forecast.optDouble("up_probability",0)*100),down=Math.round(forecast.optDouble("down_probability",0)*100),range=Math.round(forecast.optDouble("range_probability",0)*100);
        String bias=forecastLabel(forecast);
        paint.setTextSize(dp(9));paint.setFakeBoldText(true);c.drawText("MODEL "+bias,futureLeft+dp(2),top+dp(11),paint);paint.setFakeBoldText(false);
        paint.setTextSize(dp(8));c.drawText("UP "+up+"  DN "+down+"  RG "+range,futureLeft+dp(2),top+dp(22),paint);
    }
    @Override protected void onDraw(Canvas c){
        super.onDraw(c);paint.setStyle(Paint.Style.FILL);paint.setTextSize(dp(11));paint.setColor(0xffb0aac7);
        if(bars.length()<2){c.drawText("Ожидаем закрытые свечи MT5",dp(8),dp(28),paint);return;}
        if(detailedMap()){
            ScenarioMapRenderer.draw(c,getWidth(),getHeight(),getResources().getDisplayMetrics().density,bars,structure,liveBar,forecast,positions);
            return;
        }
        boolean live=hasLive();JSONArray projection=forecast.optJSONArray("projection");int start=Math.max(0,bars.length()-48),closedCount=bars.length()-start,count=closedCount+(live?1:0);double min=Double.MAX_VALUE,max=-Double.MAX_VALUE;
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b==null)continue;min=Math.min(min,b.optDouble("low"));max=Math.max(max,b.optDouble("high"));}
        if(live){min=Math.min(min,liveBar.optDouble("low",min));max=Math.max(max,liveBar.optDouble("high",max));}
        if(detailedMap()&&projection!=null)for(int i=0;i<projection.length();i++){JSONObject p=projection.optJSONObject(i);if(p==null)continue;min=Math.min(min,p.optDouble("low",min));max=Math.max(max,p.optDouble("high",max));}
        JSONArray scenarios=forecast.optJSONArray("scenarios");
        if(detailedMap()&&scenarios!=null)for(int i=0;i<scenarios.length();i++){JSONObject s=scenarios.optJSONObject(i);if(s==null)continue;JSONArray ps=s.optJSONArray("path");if(ps==null)continue;for(int j=0;j<ps.length();j++){JSONObject p=ps.optJSONObject(j);if(p==null)continue;double price=p.optDouble("price",Double.NaN);if(Double.isFinite(price)){double uncertainty=detailedMap()?p.optDouble("uncertainty",0):0;
                    if(!Double.isFinite(uncertainty)||uncertainty<0)uncertainty=0;min=Math.min(min,price-uncertainty);max=Math.max(max,price+uncertainty);}}}
        double support=forecast.optDouble("support",Double.NaN),resistance=forecast.optDouble("resistance",Double.NaN);
        if(Double.isFinite(support)){min=Math.min(min,support);max=Math.max(max,support);}if(Double.isFinite(resistance)){min=Math.min(min,resistance);max=Math.max(max,resistance);}
        if(detailedMap()){
            ArrayList<Double> bounds=new ArrayList<>();bounds.add(forecast.optDouble("live_price",Double.NaN));
            JSONObject entries=forecast.optJSONObject("entry_levels"),active=forecast.optJSONObject("active_scenario");
            if(entries!=null)for(String side:new String[]{"BUY","SELL"}){JSONObject e=entries.optJSONObject(side);if(e!=null){bounds.add(e.optDouble("trigger"));bounds.add(e.optDouble("invalidation"));}}
            if(active!=null)bounds.add(active.optDouble("invalidation"));
            for(double v:bounds)if(Double.isFinite(v)&&v>0){min=Math.min(min,v);max=Math.max(max,v);}
        }
        if(!Double.isFinite(min)||!Double.isFinite(max)||max<=min)return;double range=max-min;min-=range*.14;max+=range*.14;
        float left=dp(5),top=dp(detailedMap()?55:16),plotRight=getWidth()-dp(69),fullWidth=plotRight-left,height=getHeight()-dp(detailedMap()?87:40);
        float futureWidth=fullWidth*(detailedMap()?.45f:.38f),historyWidth=fullWidth-futureWidth-dp(7),historyRight=left+historyWidth,futureLeft=historyRight+dp(7),step=historyWidth/Math.max(1,count);
        if(fullWidth<=0||height<=0||historyWidth<=0)return;
        paint.setStrokeWidth(dp(.6f));for(int i=0;i<4;i++){float yy=top+height*i/3;paint.setColor(0xff302647);c.drawLine(left,yy,plotRight,yy,paint);paint.setColor(0xffb0aac7);c.drawText(String.format(Locale.US,"%.5f",max-(max-min)*i/3),plotRight+dp(4),yy+dp(4),paint);}
        paint.setColor(0xff403453);paint.setStrokeWidth(dp(.7f));c.drawLine(futureLeft-dp(3),top,futureLeft-dp(3),top+height,paint);
        HashMap<Long,Float> xs=new HashMap<>();float half=Math.max(dp(.7f),step*.32f),lastX=left,lastY=top+height/2;
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b==null)continue;float x=left+step*(i-start+.5f);xs.put(b.optLong("time"),x);candle(c,b,x,half,min,max,top,height,false);lastX=x;lastY=y(b.optDouble("close"),min,max,top,height);}
        if(live){float x=left+step*(closedCount+.5f);xs.put(liveBar.optLong("time"),x);candle(c,liveBar,x,half,min,max,top,height,true);lastX=x;lastY=y(liveBar.optDouble("close"),min,max,top,height);paint.setColor(0xffffb04d);paint.setTextSize(dp(8));c.drawText("LIVE",x-dp(8),top+dp(9),paint);}
        drawStructure(c,structure,xs,min,max,top,height,0xff914dff,false);drawStructure(c,liveStructure,xs,min,max,top,height,0xffffb04d,true);
        for(int i=0;i<levels.length();i++){JSONObject l=levels.optJSONObject(i);if(l==null)continue;double v=l.optDouble("price");if(v<min||v>max)continue;String kind=l.optString("kind");paint.setColor("invalidation".equals(kind)?0xffff4857:"trigger".equals(kind)?0xff42d67a:0xff914dff);float yy=y(v,min,max,top,height);paint.setStrokeWidth(dp(1));c.drawLine(left,yy,historyRight,yy,paint);c.drawText("invalidation".equals(kind)?"Отмена":"trigger".equals(kind)?"Триггер":"Уровень",left+dp(3),Math.max(top+dp(9),yy-dp(3)),paint);}
        for(int i=0;i<positions.length();i++){JSONObject p=positions.optJSONObject(i);if(p==null)continue;double v=p.optDouble("price_open");if(v<min||v>max)continue;paint.setColor(p.optInt("side",1)>0?0xff42d67a:0xffff4857);float yy=y(v,min,max,top,height);c.drawLine(left,yy,historyRight,yy,paint);}
        if(detailedMap()){
            double quote=forecast.optDouble("live_price",Double.NaN);
            if(Double.isFinite(quote)&&quote>0){lastX=futureLeft;lastY=y(quote,min,max,top,height);}
            detailedHeader(c,futureLeft);
        }
        drawForecast(c,projection,lastX,lastY,futureLeft,plotRight,min,max,top,height);
        if(!detailedMap()){paint.setColor(0xffb0aac7);paint.setTextSize(dp(9));c.drawText("Карта ждёт",futureLeft,top+dp(25),paint);c.drawText("новый профиль",futureLeft,top+dp(39),paint);}
        if(detailedMap()){
            detailedLevels(c,futureLeft,plotRight,min,max,top,height);
            paint.setColor(0xffeeeeff);paint.setStyle(Paint.Style.FILL);c.drawCircle(lastX,lastY,dp(3),paint);
            paint.setTextSize(dp(8));c.drawText("LIVE",Math.max(left,lastX-dp(24)),Math.max(top+dp(8),lastY-dp(5)),paint);
            paint.setColor(0xffb0aac7);paint.setTextSize(dp(8));
            c.drawText("Веса — не вероятность · время и траектории условны",left,getHeight()-dp(16),paint);
        }
        paint.setColor(0xffb0aac7);paint.setTextSize(dp(detailedMap()?8:10));long t=bars.optJSONObject(bars.length()-1).optLong("time");c.drawText("MT5 · закрытая свеча "+new java.text.SimpleDateFormat("HH:mm",Locale.US).format(new Date(t*1000))+(live?" · LIVE":""),left,getHeight()-dp(5),paint);
    }
}
