package com.openai.fxm1;

import android.graphics.*;
import org.json.*;
import java.util.*;

/** Separate informational canvas: one original line and actual candles on a shared UTC axis. */
final class ForecastComparisonPlot {
    static final int LINE=0xff63cbff;
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path=new Path();
    private final RectF area=new RectF();
    private final ArrayList<double[]> candles=new ArrayList<>(),points=new ArrayList<>(),levels=new ArrayList<>();
    private String header="",status="",footer="",empty="",lastQuote="";
    private String[] priceLabels=new String[5],timeLabels=new String[4];
    private double t0,t1,low,high,issued,now,span=300,lastPrice;
    private boolean cached,ready;
    private final DashPathEffect dash=new DashPathEffect(new float[]{8,6},0);
    void prepare(JSONObject f,JSONArray bars,JSONObject live,JSONArray positions){
        candles.clear();points.clear();levels.clear();ready=false;low=Double.POSITIVE_INFINITY;high=Double.NEGATIVE_INFINITY;
        JSONObject p=f.optBoolean("forecast_snapshot_selected")?f.optJSONObject("price_forecast"):null;
        header="ЦЕНОВОЙ ПРОГНОЗ · "+f.optString("chart_symbol")+" "+f.optString("timeframe");
        status=ForecastSnapshots.status(f,p);empty=p==null?status:"";footer="Одна линия расчёта · не сигнал к сделке";
        cached=f.optBoolean("stale")||f.optBoolean("client_offline")||f.optBoolean("archive")||!f.optBoolean("available",true);
        if(p==null)return;
        header=p.optString("symbol")+" "+p.optString("timeframe")+" · расчёт "+ForecastSnapshots.stamp(p.optDouble("issued_at"));
        issued=p.optDouble("issued_at");now=f.optDouble("data_asof",issued);span=seconds(p.optString("timeframe"));
        points.add(new double[]{issued,p.optDouble("origin")});include(p.optDouble("origin"));
        JSONArray projection=p.optJSONArray("projection");for(int i=0;i<projection.length();i++){JSONObject x=projection.optJSONObject(i);points.add(new double[]{x.optDouble("time"),x.optDouble("center")});include(x.optDouble("center"));}
        t0=issued-span*6;t1=Math.max(now,ForecastSnapshots.end(p))+span*.5;
        if(bars!=null)for(int i=0;i<bars.length();i++)addBar(bars.optJSONObject(i));
        if(live!=null&&(candles.isEmpty()||live.optDouble("time")>candles.get(candles.size()-1)[0]))addBar(live);
        if(!candles.isEmpty())t0=Math.min(t0,candles.get(0)[0]);
        // Mark actual positions only, never a planned hypothesis. Do not copy them to historical view.
        if(!f.optBoolean("history_only")&&!f.optBoolean("archive")&&positions!=null)for(int i=0;i<positions.length();i++){
            JSONObject q=positions.optJSONObject(i);if(q==null||!ForecastSnapshots.symbol(q.optString("symbol")).equals(ForecastSnapshots.symbol(p.optString("symbol"))))continue;
            for(String k:new String[]{"price_open","sl"}){double v=q.optDouble(k,0);if(Double.isFinite(v)&&v>0)levels.add(new double[]{v,k.equals("sl")?1:0});}
        }
        lastPrice=f.optDouble("live_price",Double.NaN);lastQuote=SparklineView.priceText(f,lastPrice);
        if(!Double.isFinite(low)||high<low)return;
        double pad=Math.max((high-low)*.1,Math.max(Math.abs(low)*.000005,1e-9));low-=pad;high+=pad;
        for(int i=0;i<5;i++)priceLabels[i]=SparklineView.priceText(f,high-(high-low)*i/4);
        for(int i=0;i<4;i++)timeLabels[i]=clock(t0+(t1-t0)*i/3);
        ready=t1>t0;footer=(now>=ForecastSnapshots.end(p)?"Срок завершён · ":cached?"Кэш · ":"")+"Свечи и прогноз: UTC · не команда на сделку";
    }
    private void include(double x){low=Math.min(low,x);high=Math.max(high,x);}
    private void addBar(JSONObject b){if(!ChartViewport.validBar(b))return;double t=b.optDouble("time");
        // Current-bar high/low are observed extrema, not a forecast or an intrabar path.
        if(t>now)return;double o=b.optDouble("open"),h=b.optDouble("high"),l=b.optDouble("low"),c=b.optDouble("close");
        candles.add(new double[]{t,o,h,l,c});include(l);include(h);
    }
    static double seconds(String tf){switch(tf){case "M1":return 60;case "M5":return 300;case "M10":return 600;case "M15":return 900;case "M30":return 1800;case "H1":return 3600;case "H4":return 14400;case "D1":return 86400;case "W1":return 604800;default:return 300;}}
    static float timeX(double t,double start,double end,float left,float right){return left+(float)((t-start)/(end-start))*(right-left);}
    private float x(double t){return timeX(t,t0,t1,area.left,area.right);}
    private float y(double v){return area.top+(float)((high-v)/(high-low))*area.height();}
    private static String clock(double seconds){java.text.SimpleDateFormat d=new java.text.SimpleDateFormat("HH:mm",Locale.US);d.setTimeZone(TimeZone.getTimeZone("UTC"));return d.format(new Date((long)(seconds*1000)));}
    private void text(Canvas c,String value,float x,float y,float size,int color,float maxWidth){paint.setStyle(Paint.Style.FILL);paint.setColor(color);paint.setTextSize(size);
        int count=paint.breakText(value,true,Math.max(0,maxWidth),null);c.drawText(value,0,count,x,y,paint);}
    void draw(Canvas c,int width,int height,float d){
        area.set(10*d,55*d,width-66*d,height-42*d);c.drawColor(0xff141125);
        text(c,header,10*d,15*d,10*d,0xffdedbea,width-20*d);
        text(c,status,10*d,32*d,9*d,cached?0xffffb04d:0xffaaa7bf,width-20*d);
        if(!ready||area.width()<=0||area.height()<=0){text(c,"Нет пригодного расчёта. Подробности — кнопка ПОДРОБНО.",10*d,68*d,10*d,0xffaaa7bf,width-20*d);return;}
        for(int i=0;i<5;i++){float yy=area.top+area.height()*i/4;paint.setColor(0xff312b43);paint.setStrokeWidth(d*.6f);c.drawLine(area.left,yy,area.right,yy,paint);text(c,priceLabels[i],area.right+4*d,yy+3*d,8*d,0xffaaa7bf,60*d);}
        int clip=c.save();c.clipRect(area);float cw=Math.max(d,Math.min(7*d,(float)(span/(t1-t0))*area.width()*.6f));
        for(double[] b:candles){float xx=x(b[0]+span*.5);paint.setColor(b[4]>=b[1]?0xff64d69c:0xffff7285);paint.setStrokeWidth(d);paint.setStyle(Paint.Style.STROKE);c.drawLine(xx,y(b[2]),xx,y(b[3]),paint);paint.setStyle(Paint.Style.FILL);float top=Math.min(y(b[1]),y(b[4])),bottom=Math.max(top+d,Math.max(y(b[1]),y(b[4])));c.drawRect(xx-cw/2,top,xx+cw/2,bottom,paint);}
        // Both candles and point times use x(t); no future-panel re-anchoring to the latest quote.
        paint.setColor(0xff766788);paint.setStrokeWidth(d);paint.setPathEffect(dash);c.drawLine(x(issued),area.top,x(issued),area.bottom,paint);
        if(now>=t0&&now<=t1){paint.setColor(0xff817c8e);c.drawLine(x(now),area.top,x(now),area.bottom,paint);}
        for(double[] level:levels)if(level[0]>=low&&level[0]<=high){paint.setColor(level[1]==1?0xffffb04d:0xffccccdf);c.drawLine(area.left,y(level[0]),area.right,y(level[0]),paint);}
        paint.setPathEffect(null);path.reset();for(int i=0;i<points.size();i++){double[] p=points.get(i);if(i==0)path.moveTo(x(p[0]),y(p[1]));else path.lineTo(x(p[0]),y(p[1]));}
        paint.setColor(cached?0xffaaa7bf:LINE);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(2*d);c.drawPath(path,paint);paint.setStyle(Paint.Style.FILL);
        for(double[] p:points)c.drawCircle(x(p[0]),y(p[1]),2.8f*d,paint);
        if(Double.isFinite(lastPrice)&&lastPrice>=low&&lastPrice<=high){paint.setColor(0xffeceaf7);c.drawCircle(x(now),y(lastPrice),2*d,paint);}
        c.restoreToCount(clip);
        for(int i=0;i<4;i++){float xx=area.left+area.width()*i/3;float shift=i==3?31*d:0;text(c,timeLabels[i],xx-shift,area.bottom+15*d,8*d,0xffaaa7bf,42*d);}
        text(c,footer,10*d,height-7*d,8*d,0xffaaa7bf,width-20*d);
    }
}
