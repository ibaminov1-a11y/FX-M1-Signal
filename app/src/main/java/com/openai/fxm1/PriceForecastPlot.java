package com.openai.fxm1;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.Locale;

/** A time-scaled forecast, never a BUY/SELL permission or a price-history rewrite. */
final class PriceForecastPlot {
    static final int BLUE=0xff62b6ff, MUTED=0xffaaa7bf;
    private PriceForecastPlot(){}

    static JSONObject visible(JSONObject f){
        if(f==null||f.optBoolean("history_only")||f.optBoolean("chart_read_only")
            ||!f.optBoolean("show_price_forecast",true))return null;
        JSONObject price=f.optJSONObject("price_forecast");
        if(price==null||!price.optBoolean("available"))return null;
        if(!f.optString("timeframe").equals(price.optString("timeframe")))return null;
        double issued=price.optDouble("issued_at",Double.NaN),origin=price.optDouble("origin",Double.NaN);
        JSONArray points=price.optJSONArray("projection");
        if(!Double.isFinite(issued)||issued<=0||!Double.isFinite(origin)||origin<=0||points==null||points.length()==0)return null;
        double previous=issued;
        for(int i=0;i<points.length();i++){
            JSONObject point=points.optJSONObject(i);if(point==null)return null;
            double t=point.optDouble("time",Double.NaN),lo=point.optDouble("low",Double.NaN),
                hi=point.optDouble("high",Double.NaN),v=point.optDouble("center",Double.NaN);
            if(!Double.isFinite(t)||t<=previous||!Double.isFinite(lo)||!Double.isFinite(hi)
                ||!Double.isFinite(v)||lo<=0||lo>v||v>hi)return null;
            previous=t;
        }
        double asof=f.optDouble("data_asof",issued);
        return asof>=previous?null:price;
    }

    static String description(JSONObject f){
        if(f!=null&&!f.optBoolean("show_price_forecast",true))return "";
        JSONObject price=visible(f);
        if(price==null){
            JSONObject raw=f==null?null:f.optJSONObject("price_forecast");
            return raw!=null&&!f.optBoolean("history_only")&&!f.optBoolean("chart_read_only")
                ?" Ценовой прогноз недоступен: "+raw.optString("reason","нет пригодных точек выбранного периода")+".":"";
        }
        boolean old=f.optBoolean("stale")||f.optBoolean("client_offline");
        StringBuilder s=new StringBuilder(old?" СОХРАНЁННЫЙ ЦЕНОВОЙ ПРОГНОЗ; нет свежего расчёта. ":" ЦЕНОВОЙ ПРОГНОЗ: ");
        JSONArray points=price.optJSONArray("projection");
        for(int i=0;i<points.length();i++){
            JSONObject pt=points.optJSONObject(i);if(i>0)s.append("; ");
            s.append(pt.optInt("minutes")).append(" мин: ").append(String.format(Locale.US,"%.5f",pt.optDouble("center")));
        }
        s.append(". Исследовательская модель. Полоса исторических примеров не является гарантией или вероятностью. Не разрешает вход.");
        return s.toString();
    }

    static void draw(Canvas canvas,JSONObject f,JSONObject price,RectF area,double low,double high,float density){
        if(price==null||high<=low||area.width()<=0||area.height()<=0)return;
        JSONArray points=price.optJSONArray("projection");
        double issued=price.optDouble("issued_at"),now=f.optDouble("data_asof",issued),
            end=points.optJSONObject(points.length()-1).optDouble("time");
        if(end<=now)return;
        boolean old=f.optBoolean("stale")||f.optBoolean("client_offline");int color=old?MUTED:BLUE;
        Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);Path band=new Path(),center=new Path();
        float startX=x(issued,now,end,area),startY=y(price.optDouble("origin"),low,high,area);
        band.moveTo(startX,startY);center.moveTo(startX,startY);
        for(int i=0;i<points.length();i++){
            JSONObject point=points.optJSONObject(i);float xx=x(point.optDouble("time"),now,end,area);
            band.lineTo(xx,y(point.optDouble("high"),low,high,area));
            center.lineTo(xx,y(point.optDouble("center"),low,high,area));
        }
        for(int i=points.length()-1;i>=0;i--){JSONObject point=points.optJSONObject(i);
            band.lineTo(x(point.optDouble("time"),now,end,area),y(point.optDouble("low"),low,high,area));}
        band.close();int saved=canvas.save();canvas.clipRect(area);
        p.setStyle(Paint.Style.FILL);p.setColor((color&0xffffff)|0x30000000);canvas.drawPath(band,p);
        p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(2*density);p.setColor(color);canvas.drawPath(center,p);
        p.setStyle(Paint.Style.FILL);
        for(int i=0;i<points.length();i++){JSONObject point=points.optJSONObject(i);
            canvas.drawCircle(x(point.optDouble("time"),now,end,area),y(point.optDouble("center"),low,high,area),2.3f*density,p);}
        canvas.restoreToCount(saved);
        p.setTextSize(8*density);p.setColor(color);float previousRight=area.left;
        for(int i=0;i<points.length();i++){
            JSONObject point=points.optJSONObject(i);String label="+"+point.optInt("minutes")+" мин";
            float width=p.measureText(label),xx=Math.max(area.left,Math.min(area.right-width,x(point.optDouble("time"),now,end,area)-width/2));
            if(xx>=previousRight||i==points.length()-1){canvas.drawText(label,xx,area.bottom+12*density,p);previousRight=xx+width+5*density;}
        }
    }
    private static float x(double t,double now,double end,RectF a){return a.left+(float)((t-now)/(end-now))*a.width();}
    private static float y(double price,double low,double high,RectF a){return a.top+(float)((high-price)/(high-low))*a.height();}
}
