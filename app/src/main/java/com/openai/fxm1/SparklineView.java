package com.openai.fxm1;
import android.content.Context;
import android.graphics.*;
import android.util.AttributeSet;
import android.view.View;
import org.json.*;
import java.util.*;

/** Japanese candles and decision levels from the SAME MT5 snapshot used by the engine. */
public class SparklineView extends View {
    private JSONArray bars=new JSONArray(),levels=new JSONArray(),positions=new JSONArray();
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private String signal="WAIT";
    public SparklineView(Context c){super(c);}
    public SparklineView(Context c,AttributeSet a){super(c,a);}
    public SparklineView(Context c,AttributeSet a,int s){super(c,a,s);}
    public void setSignal(String s){signal=s;invalidate();}
    public void setValues(List<Double> ignored){/* The legacy decorative interpolation is intentionally not used. */}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p){bars=b==null?new JSONArray():b;levels=l==null?new JSONArray():l;positions=p==null?new JSONArray():p;invalidate();}
    private float dp(float x){return x*getResources().getDisplayMetrics().density;}
    private float y(double value,double min,double max,float top,float h){return top+(float)((max-value)/(max-min))*h;}
    @Override protected void onDraw(Canvas c){super.onDraw(c);paint.setStyle(Paint.Style.FILL);paint.setTextSize(dp(11));paint.setColor(0xffb0aac7);
        if(bars.length()<2){c.drawText("Ожидаем закрытые свечи MT5",dp(8),dp(28),paint);return;}
        int start=Math.max(0,bars.length()-48),count=bars.length()-start;double min=Double.MAX_VALUE,max=-Double.MAX_VALUE;
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b==null)continue;min=Math.min(min,b.optDouble("low"));max=Math.max(max,b.optDouble("high"));}
        if(!Double.isFinite(min)||!Double.isFinite(max)||max<=min)return;
        double range=max-min;min-=range*.12;max+=range*.12;
        float left=dp(5),top=dp(16),width=getWidth()-dp(69),height=getHeight()-dp(40),step=width/count;
        if(width<=0||height<=0)return;
        paint.setStrokeWidth(dp(.6f));
        for(int i=0;i<4;i++){float yy=top+height*i/3;paint.setColor(0xff302647);c.drawLine(left,yy,left+width,yy,paint);paint.setColor(0xffb0aac7);c.drawText(String.format(Locale.US,"%.5f",max-(max-min)*i/3),left+width+dp(4),yy+dp(4),paint);}
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b==null)continue;
            double open=b.optDouble("open"),close=b.optDouble("close");float x=left+step*(i-start+.5f);
            paint.setColor(close>=open?0xff42d67a:0xffff4857);paint.setStrokeWidth(dp(1));
            c.drawLine(x,y(b.optDouble("high"),min,max,top,height),x,y(b.optDouble("low"),min,max,top,height),paint);
            float a=y(open,min,max,top,height),z=y(close,min,max,top,height),half=Math.max(dp(.7f),step*.32f);
            c.drawRect(x-half,Math.min(a,z),x+half,Math.max(Math.min(a,z)+dp(1),Math.max(a,z)),paint);
        }
        for(int i=0;i<levels.length();i++){JSONObject l=levels.optJSONObject(i);if(l==null)continue;double v=l.optDouble("price");if(v<min||v>max)continue;
            String kind=l.optString("kind");paint.setColor("invalidation".equals(kind)?0xffff4857:"trigger".equals(kind)?0xff42d67a:0xff914dff);
            float yy=y(v,min,max,top,height);paint.setStrokeWidth(dp(1));c.drawLine(left,yy,left+width,yy,paint);
            c.drawText("invalidation".equals(kind)?"Отмена":"trigger".equals(kind)?"Триггер":"Уровень",left+dp(3),Math.max(top+dp(9),yy-dp(3)),paint);
        }
        for(int i=0;i<positions.length();i++){JSONObject p=positions.optJSONObject(i);if(p==null)continue;double v=p.optDouble("price_open");if(v<min||v>max)continue;
            paint.setColor(p.optInt("side",1)>0?0xff42d67a:0xffff4857);float yy=y(v,min,max,top,height);c.drawLine(left,yy,left+width,yy,paint);
        }
        paint.setColor(0xffb0aac7);paint.setTextSize(dp(10));
        long t=bars.optJSONObject(bars.length()-1).optLong("time");
        c.drawText("MT5 · закрытая свеча "+new java.text.SimpleDateFormat("HH:mm",Locale.US).format(new Date(t*1000)),left,getHeight()-dp(5),paint);
    }
}
