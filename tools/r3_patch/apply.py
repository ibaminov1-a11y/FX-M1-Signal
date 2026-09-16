from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

# EventClient: human-readable R3 path and cached context.
ep=ROOT/'app/src/main/java/com/openai/fxm1/EventClient.java'
event=ep.read_text(encoding='utf-8')
old_phase='''    public static String phaseName(String phase){switch(phase){case "SEARCH":return "Поиск";case "PULLBACK":return "Ожидание отката";case "TRIGGER":return "Ожидание подтверждения";case "ENTRY_READY":return "Вход подтверждён";case "HOLD":return "Сопровождение";case "CANCELLED":return "Сценарий отменён";case "DATA_BLOCK":return "Нет пригодных данных";default:return phase;}}\n'''
new_phase=old_phase+'''    public static String pathName(String path){switch(path){case "IMPULSE":return "Импульс";case "CONTINUATION":return "Продолжение";case "PULLBACK":return "Откат";case "TRIGGER":return "Триггер";case "HOLD":return "Сопровождение";case "SEARCH":return "Поиск";default:return path==null||path.isEmpty()?"Поиск":path;}}\n'''
if event.count(old_phase)!=1: raise SystemExit('EventClient phaseName block not unique')
event=event.replace(old_phase,new_phase,1)
old_state='''        String phase=d.optString("phase","SEARCH");String why=d.optString("reason","Ждём MT5");\n        JSONObject campaign=s.optJSONObject("campaign");\n        if(campaign!=null){sig=campaign.optInt("side",0)>0?"BUY":"SELL";phase="HOLD";}\n'''
new_state='''        String phase=d.optString("phase","SEARCH");String path=d.optString("path","SEARCH");String why=d.optString("reason","Ждём MT5");\n        JSONObject campaign=s.optJSONObject("campaign");\n        if(campaign!=null){sig=campaign.optInt("side",0)>0?"BUY":"SELL";phase="HOLD";path="HOLD";}\n'''
if event.count(old_state)!=1: raise SystemExit('EventClient decision state block not unique')
event=event.replace(old_state,new_state,1)
old_context='''        StringBuilder context=new StringBuilder("Вход: ").append(tf).append(" · Режим: ").append(cfg.optString("mode","NORMAL"))\n            .append("\\nЭтап: ").append(phaseName(phase)).append("\\n").append(why)\n            .append("\\nРешение и исполнение: данные MT5");\n'''
new_context='''        StringBuilder context=new StringBuilder("Вход: ").append(tf).append(" · Режим: ").append(cfg.optString("mode","NORMAL"))\n            .append("\\nЭтап: ").append(phaseName(phase))\n            .append("\\nПуть: ").append(pathName(path)).append("\\n").append(why)\n            .append("\\nРешение и исполнение: данные MT5");\n'''
if event.count(old_context)!=1: raise SystemExit('EventClient context block not unique')
event=event.replace(old_context,new_context,1)
ep.write_text(event,encoding='utf-8')

# MainActivity: feed Bridge-computed R3 overlays into the chart.
mp=ROOT/'app/src/main/java/com/openai/fxm1/MainActivity.java'
main=mp.read_text(encoding='utf-8')
old_restore='''    private void restoreSparklineFromPrefs(String signal) {\n        if(sparklineView==null)return;\n        JSONObject s=EventClient.state(),d=s.optJSONObject("decision");\n        sparklineView.setMarket(s.optJSONArray("bars"),d==null?null:d.optJSONArray("levels"),s.optJSONArray("positions"));\n        sparklineView.setSignal(signal);\n    }\n'''
new_restore='''    private void restoreSparklineFromPrefs(String signal) {\n        if(sparklineView==null)return;\n        JSONObject s=EventClient.state(),d=s.optJSONObject("decision");\n        JSONArray levels=d==null?null:d.optJSONArray("levels");\n        JSONArray structure=d==null?null:d.optJSONArray("structure");\n        String path=d==null?"SEARCH":d.optString("path","SEARCH");\n        sparklineView.setMarket(s.optJSONArray("bars"),levels,s.optJSONArray("positions"),structure,path);\n        sparklineView.setSignal(signal);\n    }\n'''
if main.count(old_restore)!=1: raise SystemExit('MainActivity restoreSparkline block not unique')
mp.write_text(main.replace(old_restore,new_restore,1),encoding='utf-8')

# SparklineView: keep real MT5 candles, add deterministic confirmed swing overlays.
sp=ROOT/'app/src/main/java/com/openai/fxm1/SparklineView.java'
sp.write_text(r'''package com.openai.fxm1;
import android.content.Context;
import android.graphics.*;
import android.util.AttributeSet;
import android.view.View;
import org.json.*;
import java.util.*;

/** Japanese candles and decision levels from the SAME MT5 snapshot used by the engine. */
public class SparklineView extends View {
    private JSONArray bars=new JSONArray(),levels=new JSONArray(),positions=new JSONArray(),structure=new JSONArray();
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private String signal="WAIT",path="SEARCH";
    public SparklineView(Context c){super(c);}
    public SparklineView(Context c,AttributeSet a){super(c,a);}
    public SparklineView(Context c,AttributeSet a,int s){super(c,a,s);}
    public void setSignal(String s){signal=s;invalidate();}
    public void setValues(List<Double> ignored){/* The legacy decorative interpolation is intentionally not used. */}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p){setMarket(b,l,p,new JSONArray(),"SEARCH");}
    public void setMarket(JSONArray b,JSONArray l,JSONArray p,JSONArray s,String currentPath){
        bars=b==null?new JSONArray():b;levels=l==null?new JSONArray():l;positions=p==null?new JSONArray():p;
        structure=s==null?new JSONArray():s;path=currentPath==null||currentPath.isEmpty()?"SEARCH":currentPath;invalidate();
    }
    private float dp(float x){return x*getResources().getDisplayMetrics().density;}
    private float y(double value,double min,double max,float top,float h){return top+(float)((max-value)/(max-min))*h;}
    private float xForTime(long time,int start,float left,float step){
        for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b!=null&&b.optLong("time")==time)return left+step*(i-start+.5f);}
        return Float.NaN;
    }
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
        // R3 structure comes from confirmed EventCore pivots only. Never extrapolate past the last known point.
        paint.setColor(0xff914dff);paint.setStrokeWidth(dp(1.4f));paint.setTextSize(dp(9));
        float previousX=Float.NaN,previousY=Float.NaN;
        for(int i=0;i<structure.length();i++){JSONObject s=structure.optJSONObject(i);if(s==null)continue;
            long t=s.optLong("time");double price=s.optDouble("price",Double.NaN);float x=xForTime(t,start,left,step);
            if(Float.isNaN(x)||!Double.isFinite(price)||price<min||price>max)continue;
            float yy=y(price,min,max,top,height);
            if(!Float.isNaN(previousX))c.drawLine(previousX,previousY,x,yy,paint);
            String kind=s.optString("kind","");if(!kind.isEmpty())c.drawText(kind,x+dp(2),Math.max(top+dp(10),yy-dp(3)),paint);
            previousX=x;previousY=yy;
        }
        for(int i=0;i<levels.length();i++){JSONObject l=levels.optJSONObject(i);if(l==null)continue;double v=l.optDouble("price");if(v<min||v>max)continue;
            String kind=l.optString("kind");paint.setColor("invalidation".equals(kind)?0xffff4857:"trigger".equals(kind)?0xff42d67a:0xff914dff);
            float yy=y(v,min,max,top,height);paint.setStrokeWidth(dp(1));c.drawLine(left,yy,left+width,yy,paint);
            c.drawText("invalidation".equals(kind)?"Отмена":"trigger".equals(kind)?"Триггер":"Уровень",left+dp(3),Math.max(top+dp(9),yy-dp(3)),paint);
        }
        for(int i=0;i<positions.length();i++){JSONObject p=positions.optJSONObject(i);if(p==null)continue;double v=p.optDouble("price_open");if(v<min||v>max)continue;
            paint.setColor(p.optInt("side",1)>0?0xff42d67a:0xffff4857);float yy=y(v,min,max,top,height);c.drawLine(left,yy,left+width,yy,paint);
        }
        paint.setColor(0xff914dff);paint.setTextSize(dp(10));c.drawText("R3 · "+EventClient.pathName(path),left+dp(3),top+dp(11),paint);
        paint.setColor(0xffb0aac7);paint.setTextSize(dp(10));
        long t=bars.optJSONObject(bars.length()-1).optLong("time");
        c.drawText("MT5 · закрытая свеча "+new java.text.SimpleDateFormat("HH:mm",Locale.US).format(new Date(t*1000)),left,getHeight()-dp(5),paint);
    }
}
''',encoding='utf-8')
