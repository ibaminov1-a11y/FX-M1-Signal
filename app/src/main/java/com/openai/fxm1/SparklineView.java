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
        liveStructure=ls==null?new JSONArray():ls;forecast=fc==null?new JSONObject():fc;invalidate();
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
    private void drawForecast(Canvas c,JSONArray projection,float startX,float startY,float futureLeft,float plotRight,double min,double max,float top,float height){
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
        boolean live=hasLive();JSONArray projection=forecast.optJSONArray("projection");int start=Math.max(0,bars.length()-48),closedCount=bars.length()-start,count=closedCount+(live?1:0);double min=Double.MAX_VALUE,max=-Double.MAX_VALUE;
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b==null)continue;min=Math.min(min,b.optDouble("low"));max=Math.max(max,b.optDouble("high"));}
        if(live){min=Math.min(min,liveBar.optDouble("low",min));max=Math.max(max,liveBar.optDouble("high",max));}
        if(projection!=null)for(int i=0;i<projection.length();i++){JSONObject p=projection.optJSONObject(i);if(p==null)continue;min=Math.min(min,p.optDouble("low",min));max=Math.max(max,p.optDouble("high",max));}
        if(!Double.isFinite(min)||!Double.isFinite(max)||max<=min)return;double range=max-min;min-=range*.16;max+=range*.12;
        float left=dp(5),top=dp(16),plotRight=getWidth()-dp(69),fullWidth=plotRight-left,height=getHeight()-dp(40);
        float futureWidth=fullWidth*.30f,historyWidth=fullWidth-futureWidth-dp(7),historyRight=left+historyWidth,futureLeft=historyRight+dp(7),step=historyWidth/Math.max(1,count);
        if(fullWidth<=0||height<=0||historyWidth<=0)return;
        paint.setStrokeWidth(dp(.6f));for(int i=0;i<4;i++){float yy=top+height*i/3;paint.setColor(0xff302647);c.drawLine(left,yy,plotRight,yy,paint);paint.setColor(0xffb0aac7);c.drawText(String.format(Locale.US,"%.5f",max-(max-min)*i/3),plotRight+dp(4),yy+dp(4),paint);}
        paint.setColor(0xff403453);paint.setStrokeWidth(dp(.7f));c.drawLine(futureLeft-dp(3),top,futureLeft-dp(3),top+height,paint);
        HashMap<Long,Float> xs=new HashMap<>();float half=Math.max(dp(.7f),step*.32f),lastX=left,lastY=top+height/2;
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b==null)continue;float x=left+step*(i-start+.5f);xs.put(b.optLong("time"),x);candle(c,b,x,half,min,max,top,height,false);lastX=x;lastY=y(b.optDouble("close"),min,max,top,height);}
        if(live){float x=left+step*(closedCount+.5f);xs.put(liveBar.optLong("time"),x);candle(c,liveBar,x,half,min,max,top,height,true);lastX=x;lastY=y(liveBar.optDouble("close"),min,max,top,height);paint.setColor(0xffffb04d);paint.setTextSize(dp(8));c.drawText("LIVE",x-dp(8),top+dp(9),paint);}
        drawStructure(c,structure,xs,min,max,top,height,0xff914dff,false);drawStructure(c,liveStructure,xs,min,max,top,height,0xffffb04d,true);
        for(int i=0;i<levels.length();i++){JSONObject l=levels.optJSONObject(i);if(l==null)continue;double v=l.optDouble("price");if(v<min||v>max)continue;String kind=l.optString("kind");paint.setColor("invalidation".equals(kind)?0xffff4857:"trigger".equals(kind)?0xff42d67a:0xff914dff);float yy=y(v,min,max,top,height);paint.setStrokeWidth(dp(1));c.drawLine(left,yy,historyRight,yy,paint);c.drawText("invalidation".equals(kind)?"Отмена":"trigger".equals(kind)?"Триггер":"Уровень",left+dp(3),Math.max(top+dp(9),yy-dp(3)),paint);}
        for(int i=0;i<positions.length();i++){JSONObject p=positions.optJSONObject(i);if(p==null)continue;double v=p.optDouble("price_open");if(v<min||v>max)continue;paint.setColor(p.optInt("side",1)>0?0xff42d67a:0xffff4857);float yy=y(v,min,max,top,height);c.drawLine(left,yy,historyRight,yy,paint);}
        drawForecast(c,projection,lastX,lastY,futureLeft,plotRight,min,max,top,height);
        paint.setColor(0xffb0aac7);paint.setTextSize(dp(10));long t=bars.optJSONObject(bars.length()-1).optLong("time");c.drawText("MT5 · закрытая свеча "+new java.text.SimpleDateFormat("HH:mm",Locale.US).format(new Date(t*1000))+(live?" · LIVE":""),left,getHeight()-dp(5),paint);
    }
}
