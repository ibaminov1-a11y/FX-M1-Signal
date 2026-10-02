package com.openai.fxm1;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Actual Canvas and transport envelopes; no market orders. */
@RunWith(AndroidJUnit4.class)
public class R7ReleaseUiTest {
    private final Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
    static final long T=1800000000L;
    static JSONObject priceForecast()throws Exception{
        JSONArray points=new JSONArray();int i=0;
        for(int minutes:new int[]{5,10,15,30,60}){
            double center=1.1060+(++i)*.00008;
            points.put(new JSONObject().put("minutes",minutes).put("time",T+minutes*60)
                .put("center",center).put("low",center-.00008).put("high",center+.00008).put("sample_count",12));
        }
        return new JSONObject().put("available",true).put("model","ANALOG_R7").put("symbol","EURUSD").put("timeframe","M5")
            .put("scope","test|EURUSD|NORMAL|M5").put("snapshot_id","immutable-price-snapshot")
            .put("issued_at",T).put("origin",1.1060).put("calibrated",false).put("projection",points);
    }
    static JSONObject forecast()throws Exception{
        return new JSONObject().put("map_version",3).put("runtime_model","R7").put("available",true).put("side",0)
            .put("timeframe","M5").put("live_price",1.1060).put("data_asof",T+1).put("selection_status","NONE")
            .put("support",1.1053).put("resistance",1.1064).put("scenarios",new JSONArray()).put("price_forecast",priceForecast());
    }
    static JSONArray bars()throws Exception{
        JSONArray bars=new JSONArray();
        for(int i=0;i<48;i++){
            double price=1.1055+i*.00001;
            bars.put(new JSONObject().put("time",T-(48-i)*300).put("open",price).put("close",price+.00001)
                .put("low",price-.00004).put("high",price+.00005));
        }
        return bars;
    }
    @Test public void priceForecastIsVisibleWhileEntryWaits()throws Exception{
        final JSONObject f=forecast();final JSONArray history=bars();final String[] description={null};final Bitmap[] image={null};
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            SparklineView chart=new SparklineView(context);chart.layout(0,0,1080,660);
            chart.setMarket(history,new JSONArray(),new JSONArray(),new JSONArray(),"SCENARIO_V2",null,new JSONArray(),f);
            image[0]=Bitmap.createBitmap(1080,660,Bitmap.Config.ARGB_8888);chart.draw(new Canvas(image[0]));
            description[0]=String.valueOf(chart.getContentDescription());
        });
        try{
            assertTrue("WAIT hid the independent price forecast: "+description[0],description[0].contains("ЦЕНОВОЙ ПРОГНОЗ"));
            assertTrue(description[0],description[0].contains("5 мин"));assertTrue(description[0],description[0].contains("60 мин"));
            int blue=0;for(int y=0;y<660;y++)for(int x=540;x<1080;x++)if(image[0].getPixel(x,y)==0xff62b6ff)blue++;
            assertTrue("Future path must actually be drawn on Android Canvas",blue>30);
            java.io.File output=new java.io.File(context.getExternalFilesDir(null),"r7-wait-price-forecast.png");
            try(java.io.FileOutputStream stream=new java.io.FileOutputStream(output)){image[0].compress(Bitmap.CompressFormat.PNG,100,stream);}
            androidx.test.uiautomator.UiDevice.getInstance(InstrumentationRegistry.getInstrumentation()).executeShellCommand("mkdir -p /sdcard/Download/ec1-qa; cp "+output.getAbsolutePath()+" /sdcard/Download/ec1-qa/r7-wait-price-forecast.png");
        }finally{image[0].recycle();}
    }
    @Test public void commandEnvelopeCapturesProfileBeforeViewChanges()throws Exception{
        EventClient.init(context);EventClient.prefs().edit().clear().putString("ec_client_id","r7-native-test").commit();
        JSONObject s=new JSONObject().put("profile_id","profile-A").put("profiles",new JSONArray())
            .put("capabilities",new JSONObject().put("profile_registry",true))
            .put("config",new JSONObject().put("symbol","EURUSD").put("timeframe","M5").put("mode","NORMAL"));
        EventClient.cache(s);JSONObject envelope=EventClient.envelope(new JSONObject());
        EventClient.cache(new JSONObject(s.toString()).put("profile_id","profile-B"));
        assertEquals("profile-A",envelope.optString("profile_id"));
        assertFalse("Creating a command must not imply AUTO consent",envelope.has("confirmation"));
    }
    @Test public void wrongFrameHistoryAndExpiredForecastAreNotDrawn()throws Exception{
        JSONObject f=forecast();assertNotNull(PriceForecastPlot.visible(f));
        assertNull(PriceForecastPlot.visible(new JSONObject(f.toString()).put("timeframe","M15")));
        assertNull(PriceForecastPlot.visible(new JSONObject(f.toString()).put("history_only",true)));
        assertNull(PriceForecastPlot.visible(new JSONObject(f.toString()).put("data_asof",T+3601)));
        assertNull(PriceForecastPlot.visible(new JSONObject(f.toString()).put("chart_read_only",true)));
        assertNull(PriceForecastPlot.visible(new JSONObject(f.toString()).put("show_price_forecast",false)));
    }
    @Test public void explicitProfileIsNotReplacedAndMissingProfileFailsClosed()throws Exception{
        EventClient.init(context);EventClient.cache(new JSONObject().put("profile_id","B").put("capabilities",new JSONObject().put("profile_registry",true)));
        assertEquals("A",EventClient.envelope(new JSONObject().put("profile_id","A")).getString("profile_id"));
        EventClient.cache(new JSONObject().put("capabilities",new JSONObject().put("profile_registry",true)));
        try{EventClient.envelope(new JSONObject());fail("Missing profile accepted");}catch(java.io.IOException expected){}
    }
}
