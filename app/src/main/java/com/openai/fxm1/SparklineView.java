package com.openai.fxm1;
import android.content.Context;
import android.graphics.*;
import android.util.AttributeSet;
import android.view.View;
import org.json.*;
import java.util.*;

/** Closed MT5 candles + confirmed structure + presentation-only forming-M5 overlay. */
public class SparklineView extends View {
    private JSONArray bars=new JSONArray(),levels=new JSONArray(),positions=new JSONArray(),structure=new JSONArray(),liveStructure=new JSONArray();
    private JSONObject liveBar=null;
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private String signal="WAIT",path="SEARCH";
    public SparklineView(Context c){super(c);}
    public SparklineView(Context c,AttributeSet a){super(c,a);}
    public SparklineView(Context c,AttributeSet a,int s){super(c,a,s);}
    public void setSignal(String s){signal=s;invalidate();}
    public void setValues(List<Double> ignored){/* Legacy decorative interpolation is intentionally not used. */}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p){
        JSONArray s=null,ls=null;JSONObject lb=null;String r3Path="SEARCH";
        try{
            JSONObject state=EventClient.state(),decision=state.optJSONObject("decision");
            if(decision!=null){s=decision.optJSONArray("structure");r3Path=decision.optString("path","SEARCH");}
            lb=state.optJSONObject("live_bar");ls=state.optJSONArray("live_structure");
        }catch(Exception ignored){}
        setMarket(b,l,p,s,r3Path,lb,ls);
    }
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String r3Path){setMarket(b,l,p,s,r3Path,null,null);}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String r3Path,JSONObject lb,JSONArray ls){
        bars=b==null?new JSONArray():b;levels=l==null?new JSONArray():l;positions=p==null?new JSONArray():p;
        structure=s==null?new JSONArray():s;path=r3Path==null?"SEARCH":r3Path;liveBar=lb;liveStructure=ls==null?new JSONArray():ls;invalidate();
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
    @Override protected void onDraw(Canvas c){
        super.onDraw(c);paint.setStyle(Paint.Style.FILL);paint.setTextSize(dp(11));paint.setColor(0xffb0aac7);
        if(bars.length()<2){c.drawText("Ожидаем закрытые свечи MT5",dp(8),dp(28),paint);return;}
        boolean live=hasLive();int start=Math.max(0,bars.length()-48),closedCount=bars.length()-start,count=closedCount+(live?1:0);double min=Double.MAX_VALUE,max=-Double.MAX_VALUE;
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b==null)continue;min=Math.min(min,b.optDouble("low"));max=Math.max(max,b.optDouble("high"));}
        if(live){min=Math.min(min,liveBar.optDouble("low",min));max=Math.max(max,liveBar.optDouble("high",max));}
        if(!Double.isFinite(min)||!Double.isFinite(max)||max<=min)return;double range=max-min;min-=range*.12;max+=range*.12;
        float left=dp(5),top=dp(16),width=getWidth()-dp(69),height=getHeight()-dp(40),step=width/Math.max(1,count);if(width<=0||height<=0)return;
        paint.setStrokeWidth(dp(.6f));for(int i=0;i<4;i++){float yy=top+height*i/3;paint.setColor(0xff302647);c.drawLine(left,yy,left+width,yy,paint);paint.setColor(0xffb0aac7);c.drawText(String.format(Locale.US,"%.5f",max-(max-min)*i/3),left+width+dp(4),yy+dp(4),paint);}
        HashMap<Long,Float> xs=new HashMap<>();float half=Math.max(dp(.7f),step*.32f);
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b==null)continue;float x=left+step*(i-start+.5f);xs.put(b.optLong("time"),x);candle(c,b,x,half,min,max,top,height,false);}
        if(live){float x=left+step*(closedCount+.5f);xs.put(liveBar.optLong("time"),x);candle(c,liveBar,x,half,min,max,top,height,true);paint.setColor(0xffffb04d);paint.setTextSize(dp(8));c.drawText("LIVE",x-dp(8),top+dp(9),paint);}
        drawStructure(c,structure,xs,min,max,top,height,0xff914dff,false);drawStructure(c,liveStructure,xs,min,max,top,height,0xffffb04d,true);
        for(int i=0;i<levels.length();i++){JSONObject l=levels.optJSONObject(i);if(l==null)continue;double v=l.optDouble("price");if(v<min||v>max)continue;String kind=l.optString("kind");paint.setColor("invalidation".equals(kind)?0xffff4857:"trigger".equals(kind)?0xff42d67a:0xff914dff);float yy=y(v,min,max,top,height);paint.setStrokeWidth(dp(1));c.drawLine(left,yy,left+width,yy,paint);c.drawText("invalidation".equals(kind)?"Отмена":"trigger".equals(kind)?"Триггер":"Уровень",left+dp(3),Math.max(top+dp(9),yy-dp(3)),paint);}
        for(int i=0;i<positions.length();i++){JSONObject p=positions.optJSONObject(i);if(p==null)continue;double v=p.optDouble("price_open");if(v<min||v>max)continue;paint.setColor(p.optInt("side",1)>0?0xff42d67a:0xffff4857);float yy=y(v,min,max,top,height);c.drawLine(left,yy,left+width,yy,paint);}
        paint.setColor(0xffb0aac7);paint.setTextSize(dp(10));long t=bars.optJSONObject(bars.length()-1).optLong("time");c.drawText("MT5 · закрытая свеча "+new java.text.SimpleDateFormat("HH:mm",Locale.US).format(new Date(t*1000))+(live?" · LIVE":""),left,getHeight()-dp(5),paint);
    }
}
