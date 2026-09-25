package com.openai.fxm1;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.os.ParcelFileDescriptor;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import static org.junit.Assert.*;

/** Render actual Android Canvas at phone size; fixtures never connect to MT5. */
@RunWith(AndroidJUnit4.class)
public class ScenarioMapUiTest {
    private final Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
    private JSONArray bars()throws Exception{
        JSONArray result=new JSONArray();
        for(int i=0;i<28;i++){
            double o=1.1000+i*.00002,c=o+(i%3==0?-.000012:.000016);
            result.put(new JSONObject().put("time",1800000000L+i*300)
                .put("open",o).put("close",c).put("high",Math.max(o,c)+.000035)
                .put("low",Math.min(o,c)-.000035));
        }
        return result;
    }
    private JSONObject levels()throws Exception{
        return new JSONObject().put("BUY",new JSONObject().put("trigger",1.10070).put("invalidation",1.10020))
            .put("SELL",new JSONObject().put("trigger",1.10030).put("invalidation",1.10080));
    }
    private JSONObject forecast(int side)throws Exception{
        return new JSONObject().put("map_version",2).put("available",true).put("side",side)
            .put("live_price",1.10062).put("support",1.10020).put("resistance",1.10085)
            .put("entry_levels",levels()).put("scenarios",new JSONArray())
            .put("model_weight_kind","UNCALIBRATED_SCORE").put("path_time_kind","ILLUSTRATIVE_NOT_ETA")
            .put("range_weight",.11).put("range_probability",.11);
    }
    private JSONArray path(double first,double retest,double target)throws Exception{
        return new JSONArray().put(new JSONObject().put("minutes",0).put("price",1.10062).put("uncertainty",0))
            .put(new JSONObject().put("minutes",4).put("price",first).put("uncertainty",.00004))
            .put(new JSONObject().put("minutes",9).put("price",retest).put("uncertainty",.00006))
            .put(new JSONObject().put("minutes",15).put("price",target).put("uncertainty",.00008));
    }
    private static class Render {Bitmap bitmap;String description;int width,height;}
    private Render render(JSONObject forecast)throws Exception{
        JSONArray history=bars();
        JSONObject live=new JSONObject().put("time",1800000000L+28*300).put("open",1.10056)
            .put("high",1.10064).put("low",1.10054).put("close",1.10058);
        Render out=new Render();
        float density=context.getResources().getDisplayMetrics().density;
        out.width=Math.round(360*density);out.height=Math.round(220*density);
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            SparklineView chart=new SparklineView(context);chart.layout(0,0,out.width,out.height);
            chart.setMarket(history,new JSONArray(),new JSONArray(),new JSONArray(),"COMPUTE",live,new JSONArray(),forecast);
            out.bitmap=Bitmap.createBitmap(out.width,out.height,Bitmap.Config.ARGB_8888);
            Canvas canvas=new Canvas(out.bitmap);canvas.drawColor(0xff181126);chart.draw(canvas);
            out.description=chart.getContentDescription()==null?null:chart.getContentDescription().toString();
        });
        return out;
    }
    private int pixels(Render image,int color){
        int[] values=new int[image.width*image.height];image.bitmap.getPixels(values,0,image.width,0,0,image.width,image.height);
        int count=0;for(int y=0;y<image.height;y++)for(int x=image.width/2;x<image.width;x++)if(values[y*image.width+x]==color)count++;
        return count;
    }
    private void save(Render image,String name)throws Exception{
        File file=new File(context.getExternalFilesDir(null),name+".png");
        try(FileOutputStream out=new FileOutputStream(file)){image.bitmap.compress(Bitmap.CompressFormat.PNG,100,out);}
        String command="mkdir -p /sdcard/Download/ec1-qa; cp "+file.getAbsolutePath()+" /sdcard/Download/ec1-qa/"+name+".png";
        try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);
            InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] buffer=new byte[4096];while(in.read(buffer)!=-1){}}
    }
    @Test public void unclearMapShowsSharedEntryLevelsWithoutFakePaths()throws Exception{
        Render image=render(forecast(0));
        try{
            assertNotNull("Map must expose actual levels to accessibility",image.description);
            assertTrue(image.description,image.description.contains("WAIT"));
            assertTrue(image.description,image.description.contains("BUY 1.10070"));
            assertTrue(image.description,image.description.contains("SELL 1.10030"));
            assertTrue("Shared entry levels must be visibly drawn on the right",pixels(image,0xff879bb4)>30);
            assertEquals("No synthetic alternative branch during WAIT",0,pixels(image,0xffffc857));
            save(image,"scenario-wait");
        }finally{image.bitmap.recycle();}
    }
    @Test public void mapExplainsWeightsAndKeepsActiveInvalidationSeparate()throws Exception{
        JSONObject f=forecast(1).put("up_probability",.67).put("down_probability",.22)
            .put("scenarios",new JSONArray()
                .put(new JSONObject().put("name","PRIMARY").put("side",1).put("probability",.67).put("model_weight",.67)
                    .put("activation",1.10070).put("invalidation",1.10020).put("target",1.10105)
                    .put("target_source","MEASURED_RANGE_EXTENSION").put("path",path(1.10082,1.10070,1.10105)))
                .put(new JSONObject().put("name","ALTERNATIVE").put("side",-1).put("probability",.22).put("model_weight",.22)
                    .put("activation",1.10030).put("invalidation",1.10080).put("target",1.10005)
                    .put("target_source","CONFIRMED_STRUCTURE").put("path",path(1.10022,1.10030,1.10005))))
            .put("active_scenario",new JSONObject().put("side",1).put("entry",1.10065).put("invalidation",1.10040))
            .put("reversal_status",new JSONObject().put("status","WAITING_CLOSE").put("side",-1));
        Render image=render(f);
        try{
            assertNotNull(image.description);
            assertTrue(image.description,image.description.contains("не вероятность"));
            assertTrue(image.description,image.description.contains("Активный BUY"));
            assertTrue(image.description,image.description.contains("1.10040"));
            assertTrue(image.description,image.description.contains("WAITING_CLOSE"));
            assertTrue("Primary branch must remain prominent",pixels(image,0xff42d67a)>25);
            assertTrue("Opposite alternative must be separate",pixels(image,0xffffc857)>20);
            assertTrue("Active invalidation must be visibly marked",pixels(image,0xffffb04d)>20);
            save(image,"scenario-active-reversal");
        }finally{image.bitmap.recycle();}
    }
    @Test public void summaryUsesWeightsAndActualReversalStage()throws Exception{
        EventClient.init(context);
        JSONObject reversal=new JSONObject().put("status","WAITING_SIGNAL").put("side",-1);
        JSONObject state=new JSONObject().put("account",new JSONObject().put("balance",100).put("equity",100).put("type","DEMO"))
            .put("forecast",forecast(1).put("up_probability",.67).put("down_probability",.22))
            .put("reversal_status",reversal).put("pending_reversal",reversal);
        EventClient.cache(state);
        String text=EventClient.prefs().getString("state_forecast_text","");
        assertTrue(text,text.contains("не вероятность"));
        assertFalse(text,text.contains("67%"));
        String explanation=EventClient.prefs().getString("state_context","");
        assertTrue(explanation,explanation.contains("WAITING_SIGNAL"));
        assertFalse(explanation,explanation.contains("закрываем текущую сторону"));
        state.remove("pending_reversal");
        state.put("reversal_status",new JSONObject().put("status","CANCELLED").put("reason","USER_PAUSE"));
        EventClient.cache(state);
        assertTrue(EventClient.prefs().getString("state_context","").contains("USER_PAUSE"));
    }

}
