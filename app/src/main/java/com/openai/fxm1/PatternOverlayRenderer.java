package com.openai.fxm1;

import android.graphics.*;
import org.json.*;
import java.util.*;

/** Observed geometry only. Conditional routes are rendered separately. */
final class PatternOverlayRenderer {
    private PatternOverlayRenderer(){}
    static String label(String role){switch(role){
        case "LEFT_SHOULDER":return "Левое плечо";case "HEAD":return "Голова";case "RIGHT_SHOULDER":return "Правое плечо";
        case "NECK":return "Шея";case "NECKLINE":return "Линия шеи";case "POLE":return "Флагшток";
        case "POLE_START":return "Начало импульса";case "POLE_END":return "Вершина импульса";
        case "TOUCH_HIGH":return "Касание H";case "TOUCH_LOW":return "Касание L";
        case "UPPER":return "Верхняя граница";case "LOWER":return "Нижняя граница";
        default:if(role.startsWith("TOP"))return "Вершина "+role.replace("TOP","").replace("_","");
            if(role.startsWith("BOTTOM"))return "Дно "+role.replace("BOTTOM","").replace("_","");return role;}}
    static void draw(Canvas canvas,PatternChartModel model,ChartTransform tx,String selectedId){draw(canvas,model,tx,selectedId,new ArrayList<RectF>());}
    static void draw(Canvas c,PatternChartModel model,ChartTransform tx,String id,List<RectF> occupied){
        JSONObject pattern=model.selected(id);if(pattern==null)return;
        RectF area=tx.plotBounds();float d=tx.density;
        if(area.width()<16*d||area.height()<30*d)return;
        int color=model.stale?0xffaaa7bf:"FORMING".equals(pattern.optString("geometry_state"))?0xffffbe65:0xffd8baff;
        Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);p.setStrokeWidth(1.6f*d);p.setColor(color);p.setStyle(Paint.Style.STROKE);
        JSONArray segments=pattern.optJSONArray("segments");int save=c.save();c.clipRect(area);
        for(int i=0;i<segments.length();i++){
            JSONObject s=segments.optJSONObject(i);p.setPathEffect(s.optBoolean("provisional")?new DashPathEffect(new float[]{5*d,4*d},0):null);
            p.setStrokeWidth(("POLE".equals(s.optString("role"))?2.8f:1.6f)*d);
            c.drawLine(tx.x(s.optLong("from_time")),tx.y(s.optDouble("from_price")),tx.x(s.optLong("to_time")),tx.y(s.optDouble("to_price")),p);
        }
        JSONArray anchors=pattern.optJSONArray("anchors");p.setPathEffect(null);
        for(int i=0;i<anchors.length();i++){JSONObject a=anchors.optJSONObject(i);p.setStyle(a.optBoolean("provisional")?Paint.Style.STROKE:Paint.Style.FILL);
            c.drawCircle(tx.x(a.optLong("time")),tx.y(a.optDouble("price")),2.8f*d,p);}
        c.restoreToCount(save);p.setStyle(Paint.Style.FILL);
        ArrayList<RectF> used=new ArrayList<>(occupied);
        add(c,p,used,area,pattern.optString("title"),area.left+3*d,area.top+2*d,color,10*d);
        add(c,p,used,area,PatternChartModel.stage(pattern.optString("geometry_state"))+(model.stale?" · СНИМОК":""),area.left+3*d,area.top+17*d,color,9*d);
        int hidden=0;
        // Named landmarks take precedence over secondary touches.
        for(int i=0;i<anchors.length();i++){
            JSONObject a=anchors.optJSONObject(i);String role=a.optString("role");
            if(role.startsWith("POLE_")||role.equals("NECK"))continue;
            float x=tx.x(a.optLong("time")),y=tx.y(a.optDouble("price"));
            if(!area.contains(x,y)){hidden++;continue;}
            String text=label(role)+(a.optBoolean("provisional")?"?":"");
            if(!add(c,p,used,area,text,x-25*d,y-14*d,color,8.5f*d))hidden++;
        }
        for(int i=0;i<segments.length();i++){
            JSONObject s=segments.optJSONObject(i);String role=s.optString("role");if(!role.equals("NECKLINE")&&!role.equals("POLE"))continue;
            float x=(tx.x(s.optLong("from_time"))+tx.x(s.optLong("to_time")))/2,y=(tx.y(s.optDouble("from_price"))+tx.y(s.optDouble("to_price")))/2;
            if(!add(c,p,used,area,label(role),x,y-10*d,color,9*d))hidden++;
        }
        if(hidden>0)add(c,p,used,area,"Вне окна / подробнее: "+hidden,area.left+3*d,area.bottom-15*d,0xffaaa7bf,8*d);
        occupied.addAll(used.subList(occupied.size(),used.size()));
    }
    private static boolean add(Canvas c,Paint p,List<RectF> used,RectF area,String text,float x,float y,int color,float size){
        p.setTextSize(size);p.setPathEffect(null);p.setStyle(Paint.Style.FILL);float pad=2;
        // Titles are bounded in length; compact down only to a readable minimum.
        while(p.measureText(text)+2*pad>area.width()&&p.getTextSize()>size*.76f)p.setTextSize(p.getTextSize()-.5f);
        float width=p.measureText(text)+2*pad,height=p.descent()-p.ascent()+2*pad;
        RectF box=ChartLabelPlacer.place(used,area,x,y,width,height);if(box==null)return false;
        p.setColor(0xe8141125);c.drawRoundRect(box,2,2,p);p.setColor(color);
        c.drawText(text,box.left+pad,box.top+pad-p.ascent(),p);used.add(box);return true;
    }
}
