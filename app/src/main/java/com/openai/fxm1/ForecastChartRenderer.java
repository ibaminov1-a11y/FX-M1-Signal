package com.openai.fxm1;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.text.TextUtils;
import org.json.JSONArray;
import org.json.JSONObject;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/** One timestamp/price transform for immutable projections AND factual MT5 candles.
 * No synthetic candles, scenario arrows, filled fan, signal permissions or model changes.
 */
final class ForecastChartRenderer {
    static final int LINE=0xff62b6ff, MUTED=0xffb0aac7, UP=0xff43d18b, DOWN=0xffff526a;
    static final class Geometry {
        final RectF area;final double start,end,low,high;
        Geometry(RectF a,double s,double e,double l,double h){area=a;start=s;end=e;low=l;high=h;}
        float x(double time){return area.left+(float)((time-start)/(end-start))*area.width();}
        float y(double price){return area.bottom-(float)((price-low)/(high-low))*area.height();}
    }
    static int seconds(String tf){switch(tf){case "M1":return 60;case "M5":return 300;case "M15":return 900;case "M30":return 1800;
        case "H1":return 3600;case "H4":return 14400;case "D1":return 86400;case "W1":return 604800;default:return 300;}}
    static String stamp(double seconds){SimpleDateFormat fmt=new SimpleDateFormat("dd.MM HH:mm:ss",Locale.ROOT);fmt.setTimeZone(TimeZone.getTimeZone("UTC"));return fmt.format(new Date((long)(seconds*1000)));}
    private static String hm(double seconds){SimpleDateFormat fmt=new SimpleDateFormat("HH:mm",Locale.ROOT);fmt.setTimeZone(TimeZone.getTimeZone("UTC"));return fmt.format(new Date((long)(seconds*1000)));}
    static double end(JSONObject price){JSONArray rows=price.optJSONArray("projection");return rows.optJSONObject(rows.length()-1).optDouble("time");}
    static String reason(JSONObject f){
        if(f.optBoolean("chart_read_only")||f.optBoolean("chart_forecast_rejected"))return f.optString("chart_reason","Время или инструмент не подтверждены");
        if(f.optBoolean("history_only"))return "Просмотр свечной истории. Нажмите LIVE для сравнения с прогнозом";
        String note=f.optString("forecast_unavailable_reason");if(!note.isEmpty())return note;
        JSONObject p=f.optJSONObject("price_forecast");
        return p==null?"Bridge ещё не прислал ценовой прогноз":p.optString("reason","Нет пригодных точек для выбранного инструмента и периода");
    }
    static String description(JSONObject f){
        JSONObject price=PriceForecastPlot.visible(f);
        if(price==null)return "ЦЕНОВОЙ ПРОГНОЗ НЕДОСТУПЕН: "+reason(f)+". Линия не выдумывается.";
        StringBuilder s=new StringBuilder("ЦЕНОВОЙ ПРОГНОЗ · ").append(price.optString("symbol")).append(" · ").append(price.optString("timeframe"))
            .append("\nРасчёт от ").append(stamp(price.optDouble("issued_at"))).append(" UTC; ID ").append(price.optString("snapshot_id"))
            .append("\nНачальная цена Bid: ").append(SparklineView.priceText(f,price.optDouble("origin")))
            .append(". Время и точки закреплены; обновление котировки их не переносит.");
        if(f.optBoolean("client_offline")||f.optBoolean("stale")||!f.optBoolean("available",true))s.append("\nСОХРАНЁННЫЙ СНИМОК · нет подтверждённых свежих данных. ").append(reason(f));
        if(!f.optString("forecast_unavailable_reason").isEmpty())s.append("\nНовый расчёт: ").append(f.optString("forecast_unavailable_reason"));
        if(!f.optString("forecast_warning").isEmpty())s.append("\n").append(f.optString("forecast_warning"));
        if(f.optDouble("data_asof")>=end(price))s.append("\nГоризонт завершён. Это сравнение с прошлым расчётом, не новый прогноз.");
        if(f.optInt("forecast_newer_count")>0)s.append("\nБолее новых расчётов: ").append(f.optInt("forecast_newer_count")).append(". Они не заменяют выбранный автоматически.");
        JSONArray rows=price.optJSONArray("projection");
        for(int i=0;i<rows.length();i++){JSONObject pt=rows.optJSONObject(i);s.append("\n").append(stamp(pt.optDouble("time"))).append(" UTC · +")
            .append(pt.optInt("minutes")).append(" мин · ").append(SparklineView.priceText(f,pt.optDouble("center")));}
        return s.append("\nЛиния соединяет рассчитанные ориентиры, не предсказывает каждый тик. Свечи — фактические данные MT5; у текущей свечи меняется незакрытая часть.\nИсследовательская модель; точность не гарантирована. Это НЕ сигнал BUY/SELL и не разрешение на сделку.\nНа телефоне сохраняются до 32 полученных расчётов на контекст; выбранный снимок сохраняется при обновлении. Данные до установки и неполученные расчёты не восстанавливаются.").toString();
    }
    static Geometry geometry(int width,int height,float d,JSONObject f,JSONArray bars,JSONObject live,int visibleBars){
        JSONObject price=PriceForecastPlot.visible(f);int span=seconds(f.optString("timeframe"));double start,end;
        if(price!=null){double issued=price.optDouble("issued_at"),duration=end(price)-issued;
            start=issued-Math.max(6.0*span,duration)*Math.max(12,Math.min(5000,visibleBars))/36.0;
            end=end(price)+span*.35; // This coordinate frame does not move with each incoming tick.
        }else{start=bars.length()>0?bars.optJSONObject(0).optDouble("time"):f.optDouble("data_asof")-span*12;
            end=Math.max(start+span,f.optDouble("data_asof",start+span*12))+span;}
        double lo=Double.POSITIVE_INFINITY,hi=Double.NEGATIVE_INFINITY,asof=f.optDouble("data_asof",Double.MAX_VALUE);
        for(int i=0;i<=bars.length();i++){JSONObject b=i==bars.length()?live:bars.optJSONObject(i);
            if(!ChartViewport.validBar(b)||b.optDouble("time")<start||b.optDouble("time")>end||b.optDouble("time")>asof)continue;
            lo=Math.min(lo,b.optDouble("low"));hi=Math.max(hi,b.optDouble("high"));}
        if(price!=null){lo=Math.min(lo,price.optDouble("origin"));hi=Math.max(hi,price.optDouble("origin"));JSONArray pts=price.optJSONArray("projection");
            for(int i=0;i<pts.length();i++){double v=pts.optJSONObject(i).optDouble("center");lo=Math.min(lo,v);hi=Math.max(hi,v);}}
        if(!Double.isFinite(lo)||!Double.isFinite(hi)){lo=0;hi=1;}
        double gap=Math.max(Math.pow(10,-SparklineView.priceDigits(f))*4,hi-lo);lo-=gap*.12;hi+=gap*.12;
        Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);p.setTextSize(9*d);float axis=0;
        for(int i=0;i<5;i++)axis=Math.max(axis,p.measureText(SparklineView.priceText(f,hi-(hi-lo)*i/4)));
        return new Geometry(new RectF(10*d,90*d,width-axis-15*d,height-80*d),start,end,lo,hi);
    }
    static void draw(Canvas c,int width,int height,float d,JSONObject f,JSONArray bars,JSONObject live,int visibleBars){
        Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);JSONObject price=PriceForecastPlot.visible(f);
        Geometry g=geometry(width,height,d,f,bars,live,visibleBars);RectF a=g.area;if(a.width()<=0||a.height()<=0)return;
        text(c,p,"ЦЕНОВОЙ ПРОГНОЗ · "+f.optString("chart_symbol",f.optString("symbol"))+" · "+f.optString("timeframe"),10*d,19*d,13*d,LINE,width-20*d);
        boolean stale=f.optBoolean("client_offline")||f.optBoolean("stale")||!f.optBoolean("available",true);
        if(price!=null){
            text(c,p,"Расчёт "+stamp(price.optDouble("issued_at"))+" UTC",10*d,38*d,10*d,MUTED,width-20*d);
            String status=stale?"СОХРАНЁННЫЙ · свежие данные не подтверждены":f.optDouble("data_asof")>=end(price)?"ГОРИЗОНТ ЗАВЕРШЁН · сравнение с фактом":"ЗАКРЕПЛЁН · точки не переносятся";
            text(c,p,status,10*d,57*d,9.5f*d,stale?0xffffb04d:MUTED,width-20*d);
            text(c,p,f.optInt("forecast_newer_count")>0?"Новых расчётов: "+f.optInt("forecast_newer_count")+" · выбор кнопкой «НОВЫЙ»":"Факт: "+stamp(f.optDouble("data_asof"))+" UTC",10*d,75*d,9*d,MUTED,width-20*d);
        }else{
            text(c,p,"Нет доступной прогнозной линии",10*d,39*d,11*d,0xffffb04d,width-20*d);
            text(c,p,reason(f),10*d,58*d,9*d,MUTED,width-20*d);
            text(c,p,"Полная причина — «ПОДРОБНО». Показаны только свечи.",10*d,76*d,9*d,MUTED,width-20*d);
        }
        for(int i=0;i<5;i++){float yy=a.top+a.height()*i/4;line(c,p,a.left,yy,a.right,yy,0xff312b43,.6f*d);
            text(c,p,SparklineView.priceText(f,g.high-(g.high-g.low)*i/4),a.right+4*d,yy+3*d,9*d,MUTED,width-a.right-4*d);}
        int saved=c.save();c.clipRect(a);
        if(price!=null){Path path=new Path();path.moveTo(g.x(price.optDouble("issued_at")),g.y(price.optDouble("origin")));
            JSONArray rows=price.optJSONArray("projection");for(int i=0;i<rows.length();i++){JSONObject pt=rows.optJSONObject(i);path.lineTo(g.x(pt.optDouble("time")),g.y(pt.optDouble("center")));}
            p.setColor(stale?MUTED:LINE);p.setStrokeWidth(2*d);p.setStyle(Paint.Style.STROKE);c.drawPath(path,p);p.setStyle(Paint.Style.FILL);
            c.drawCircle(g.x(price.optDouble("issued_at")),g.y(price.optDouble("origin")),3*d,p);
            for(int i=0;i<rows.length();i++){JSONObject pt=rows.optJSONObject(i);c.drawCircle(g.x(pt.optDouble("time")),g.y(pt.optDouble("center")),2.5f*d,p);}
            p.setPathEffect(new android.graphics.DashPathEffect(new float[]{5*d,4*d},0));
            line(c,p,g.x(price.optDouble("issued_at")),a.top,g.x(price.optDouble("issued_at")),a.bottom,MUTED,d);p.setPathEffect(null);
        }
        double asof=f.optDouble("data_asof",Double.MAX_VALUE);int span=seconds(f.optString("timeframe"));
        float half=Math.max(.6f*d,Math.min(7*d,(g.x(g.start+span)-g.x(g.start))*.28f));
        for(int i=0;i<=bars.length();i++){JSONObject b=i==bars.length()?live:bars.optJSONObject(i);
            if(!ChartViewport.validBar(b)||b.optDouble("time")<g.start||b.optDouble("time")>g.end||b.optDouble("time")>asof)continue;
            float x=g.x(b.optDouble("time"));int color=b.optDouble("close")>=b.optDouble("open")?UP:DOWN;
            line(c,p,x,g.y(b.optDouble("low")),x,g.y(b.optDouble("high")),color,d);
            p.setColor(color);p.setStyle(Paint.Style.FILL);float y1=g.y(b.optDouble("open")),y2=g.y(b.optDouble("close"));
            c.drawRect(x-half,Math.min(y1,y2),x+half,Math.max(Math.min(y1,y2)+d,Math.max(y1,y2)),p);
        }
        c.restoreToCount(saved);
        // Shared absolute-time ticks: a forecast point and candle at t always use the same x(t).
        p.setTextSize(8*d);for(int i=0;i<4;i++){double t=g.start+(g.end-g.start)*i/3;String label=hm(t);float tw=p.measureText(label);
            text(c,p,label,Math.max(a.left,Math.min(a.right-tw,g.x(t)-tw/2)),a.bottom+15*d,8*d,MUTED,tw+1);}
        text(c,p,"UTC · линия — расчёт · свечи — факт",a.left,a.bottom+34*d,9*d,MUTED,width-20*d);
        text(c,p,"Не сигнал на сделку. Точность не гарантирована.",a.left,a.bottom+52*d,9*d,MUTED,width-20*d);
    }
    private static void line(Canvas c,Paint p,float x1,float y1,float x2,float y2,int color,float width){p.setColor(color);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(width);c.drawLine(x1,y1,x2,y2,p);p.setStyle(Paint.Style.FILL);}
    private static void text(Canvas c,Paint p,String text,float x,float y,float size,int color,float maxWidth){p.setColor(color);p.setTextSize(size);p.setStyle(Paint.Style.FILL);
        c.drawText(TextUtils.ellipsize(text,new android.text.TextPaint(p),Math.max(0,maxWidth),TextUtils.TruncateAt.END).toString(),x,y,p);}
}
