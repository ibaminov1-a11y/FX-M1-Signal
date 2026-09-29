package com.openai.fxm1;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.util.ArrayList;
import java.util.List;
import static org.junit.Assert.*;

/** Inspect actual Canvas output: a waiting hypothesis must not advertise unrelated entries. */
@RunWith(AndroidJUnit4.class)
public class R56ChartSemanticsTest {
    private static class RecordingCanvas extends Canvas {
        final List<String> labels=new ArrayList<>();
        RecordingCanvas(){super(Bitmap.createBitmap(900,1000,Bitmap.Config.ARGB_8888));}
        @Override public void drawText(String text,float x,float y,Paint paint){
            labels.add(text);super.drawText(text,x,y,paint);
        }
    }
    private JSONObject forecast()throws Exception{
        JSONObject route=new JSONObject().put("scenario_id","false-return-m15").put("name","PRIMARY")
            .put("side",-1).put("stage","WATCHING").put("title","Ложный выход и возврат")
            .put("quality_score",64).put("event_level",1.13584).put("invalidation",1.13594)
            .put("path",new JSONArray()
                .put(new JSONObject().put("price",1.13454).put("phase","LIVE"))
                .put(new JSONObject().put("price",1.13584).put("phase","PREPARATION").put("label","Выход?"))
                .put(new JSONObject().put("price",1.13457).put("phase","TRADE").put("label","T1")));
        return new JSONObject().put("map_version",3).put("timeframe","M15").put("live_price",1.13454)
            .put("data_asof",1800000000).put("scenarios",new JSONArray().put(route))
            .put("support",1.13457).put("resistance",1.13583)
            .put("entry_levels",new JSONObject()
                .put("BUY",new JSONObject().put("trigger",1.13584).put("invalidation",1.13440))
                .put("SELL",new JSONObject().put("trigger",1.13456).put("invalidation",1.13594)));
    }
    private List<String> draw(JSONObject forecast)throws Exception{
        JSONArray bars=new JSONArray();
        for(int i=0;i<20;i++)bars.put(new JSONObject().put("time",1799982000L+i*900)
            .put("open",1.1350).put("high",1.1360).put("low",1.1341).put("close",1.1348));
        RecordingCanvas canvas=new RecordingCanvas();
        ScenarioMapRenderer.draw(canvas,900,1000,1f,bars,new JSONArray(),null,new JSONArray(),forecast,new JSONArray());
        return canvas.labels;
    }
    @Test public void falseReturnDoesNotAdvertiseUnrelatedGenericEntryLevels()throws Exception{
        List<String> labels=draw(forecast());
        assertFalse("Generic SELL below support is not this waiting SELL hypothesis's entry: "+labels,
            labels.stream().anyMatch(s->s.startsWith("SELL ")||s.startsWith("BUY ")));
        assertTrue("Actual next event is visible",labels.stream().anyMatch(s->s.contains("1.13584")&&s.contains("Проверка")));
    }
    @Test public void repeatedHypothesisStillDisplaysItsOwnFrameAndNewDataTime()throws Exception{
        JSONObject forecast=forecast();List<String> first=draw(forecast);
        forecast.put("data_asof",1800000060);List<String> second=draw(forecast);
        String a=first.stream().filter(s->s.startsWith("MT5 · M15 · ")).findFirst().orElse("");
        String b=second.stream().filter(s->s.startsWith("MT5 · M15 · ")).findFirst().orElse("");
        assertFalse("Chart must show the actual frame and quote timestamp",a.isEmpty());
        assertNotEquals("A persistent hypothesis still shows advancing data time",a,b);
    }
}
