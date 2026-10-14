package com.openai.fxm1;

import android.content.Context;
import android.graphics.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.*;
import java.util.*;
import static org.junit.Assert.*;

/** Real chart, preferences and Canvas; all changes here are display-only. */
@RunWith(AndroidJUnit4.class)
public class R742ForecastViewTest {
    private final Context ctx=InstrumentationRegistry.getInstrumentation().getTargetContext();
    private void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    private SparklineView chart(String scope,JSONObject f,JSONArray bars){
        SparklineView c=new SparklineView(ctx);c.setMarketIdentity(scope);c.layout(0,0,1080,690);
        R742ForecastContractTest.feed(c,f,bars);c.showPriceForecast(true);return c;
    }
    private String scope(){return "r742-view-"+UUID.randomUUID();}
    private JSONObject forecast(String id,long t)throws Exception{return R742ForecastContractTest.forecast(id,t,1.106);}
    private JSONArray bars()throws Exception{return R742ForecastContractTest.bars();}
    private static final long T=R742ForecastContractTest.T;
    private void shot(SparklineView c,String name)throws Exception{
        Bitmap b=Bitmap.createBitmap(1080,690,Bitmap.Config.ARGB_8888);c.draw(new Canvas(b));
        try(FileOutputStream out=new FileOutputStream(new File(ctx.getExternalFilesDir(null),name+".png"))){b.compress(Bitmap.CompressFormat.PNG,100,out);}finally{b.recycle();}
    }
    @Test public void explicitForecastRendersOneLineWithoutChangingServerEnvelope()throws Exception {
        JSONObject f=forecast("line",T);JSONArray b=bars();String unchanged=f.toString();
        ui(()->{SparklineView c=chart(scope(),f,b);JSONObject shown=c.displayedForecast();
            assertTrue(shown.optBoolean("forecast_snapshot_selected"));
            assertEquals(0,shown.optJSONArray("scenarios").length());
            Bitmap image=Bitmap.createBitmap(1080,690,Bitmap.Config.ARGB_8888);
            try{c.draw(new Canvas(image));int cyan=0;for(int y=0;y<690;y++)for(int x=0;x<1080;x++)if(image.getPixel(x,y)==ForecastComparisonPlot.LINE)cyan++;
                assertTrue("Forecast line has no native pixels",cyan>50);
                assertEquals("Server input mutated",unchanged,f.toString());
                try{shot(c,"r742-forecast-line");}catch(Exception e){throw new AssertionError(e);}
            }finally{image.recycle();}
        });
    }
    @Test public void chosenSnapshotAndModeSurviveActivityRecreation()throws Exception {
        String key=scope();JSONObject a=forecast("a",T),b=forecast("b",T+60);JSONArray bars=bars();
        ui(()->{SparklineView c=chart(key,a,bars);R742ForecastContractTest.feed(c,b,bars);
            SparklineView recreated=new SparklineView(ctx);recreated.setMarketIdentity(key);R742ForecastContractTest.feed(recreated,b,bars);
            assertEquals("FORECAST",recreated.displayedForecast().optString("chart_display_mode"));
            assertEquals("a",recreated.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id"));
        });
    }
    @Test public void newestSelectionIsExplicitAndOlderRemainsSelectable()throws Exception {
        JSONObject a=forecast("a",T),b=forecast("b",T+60);JSONArray bars=bars();
        ui(()->{SparklineView c=chart(scope(),a,bars);R742ForecastContractTest.feed(c,b,bars);
            assertEquals("a",c.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id"));
            assertEquals(2,c.priceSnapshotChoices().length());assertTrue(c.selectLatestPriceForecast());
            assertEquals("b",c.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id"));
            assertTrue(c.selectPriceSnapshot("a"));assertEquals("a",c.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id"));
            c.showPriceForecast(false);c.showPriceForecast(true);assertEquals("a",c.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id"));
        });
    }
    @Test public void sameIdMutationIsNotAcceptedAsOriginal()throws Exception {
        JSONObject original=forecast("same",T),mutated=forecast("same",T);mutated.getJSONObject("price_forecast").put("origin",1.19999);JSONArray bars=bars();
        ui(()->{SparklineView c=chart(scope(),original,bars);R742ForecastContractTest.feed(c,mutated,bars);
            assertEquals(1.106,c.displayedForecast().optJSONObject("price_forecast").optDouble("origin"),1e-10);
            assertEquals(1,c.priceSnapshotChoices().length());
        });
    }
    @Test public void staleUpdateRetainsOriginalButIsClearlyNotLive()throws Exception {
        JSONObject a=forecast("a",T),stale=forecast("b",T+120).put("client_offline",true).put("stale",true);JSONArray bars=bars();
        ui(()->{SparklineView c=chart(scope(),a,bars);R742ForecastContractTest.feed(c,stale,bars);
            assertEquals("a",c.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id"));
            assertTrue(String.valueOf(c.getContentDescription()).contains("нет свежих данных"));
            assertEquals(1,c.priceSnapshotChoices().length());
            try{shot(c,"r742-forecast-offline");}catch(Exception e){throw new AssertionError(e);}
        });
    }
    @Test public void expiredSnapshotRemainsComparisonNotReissuedForecast()throws Exception {
        JSONObject a=forecast("a",T),later=forecast("b",T+3660);JSONArray bars=bars();
        bars.put(new JSONObject().put("time",T+3300).put("open",1.1061).put("close",1.10604).put("low",1.1059).put("high",1.1063));
        ui(()->{SparklineView c=chart(scope(),a,R7Bars());R742ForecastContractTest.feed(c,later,bars);
            assertEquals(T,c.displayedForecast().optJSONObject("price_forecast").optLong("issued_at"));
            assertTrue(String.valueOf(c.getContentDescription()).contains("завершён"));
            try{shot(c,"r742-forecast-comparison");}catch(Exception e){throw new AssertionError(e);}
        });
    }
    private JSONArray R7Bars(){try{return bars();}catch(Exception e){throw new AssertionError(e);}}
    @Test public void invalidFrameSymbolScopeAndGeometryNeverCreateSnapshot()throws Exception {
        for(String kind:new String[]{"frame","symbol","scope","geometry","clock"}){
            JSONObject f=forecast(kind,T);
            if(kind.equals("frame"))f.getJSONObject("price_forecast").put("timeframe","M15");
            if(kind.equals("symbol"))f.getJSONObject("price_forecast").put("symbol","GBPUSD");
            if(kind.equals("scope"))f.getJSONObject("price_forecast").put("scope","other-account");
            if(kind.equals("geometry"))f.getJSONObject("price_forecast").getJSONArray("projection").getJSONObject(0).put("time",T-1);
            if(kind.equals("clock"))f.put("chart_read_only",true);
            JSONArray bars=bars();ui(()->{SparklineView c=chart(scope(),f,bars);assertFalse(kind,c.displayedForecast().optBoolean("forecast_snapshot_selected"));assertEquals(0,c.priceSnapshotChoices().length());});
        }
    }
    @Test public void accountSwitchAndUnverifiedClockNeverReusePriorSnapshot()throws Exception {
        JSONObject a=forecast("a",T),invalid=forecast("b",T+60).put("chart_read_only",true);JSONArray bars=bars();
        ui(()->{SparklineView c=chart(scope(),a,bars);c.setMarketIdentity(scope()+"|CHART|");R742ForecastContractTest.feed(c,invalid,bars);
            c.showPriceForecast(true);assertFalse(c.displayedForecast().optBoolean("forecast_snapshot_selected"));
        });
    }
    @Test public void controlsNeverAlterTradingPreferencesOrCachedTradingState()throws Exception {
        EventClient.init(ctx);String state=EventClient.state().toString();Map<String,?> prefs=new HashMap<>(EventClient.prefs().getAll());
        JSONObject a=forecast("a",T);JSONArray bars=bars();ui(()->{SparklineView c=chart(scope(),a,bars);
            c.panHistory(4);c.zoomHistory(1.2);c.goLive();c.selectLatestPriceForecast();c.showPriceForecast(false);c.showPriceForecast(true);
            assertEquals(state,EventClient.state().toString());assertEquals(prefs,EventClient.prefs().getAll());
        });
    }
    @Test public void absoluteTimeTransformUsesSamePositionForObservedAndPredictedPrice()throws Exception {
        assertEquals(20,ForecastComparisonPlot.timeX(T,T,T+4500,20,920),0);
        assertEquals(920,ForecastComparisonPlot.timeX(T+4500,T,T+4500,20,920),0);
        assertEquals(400.0/4500*900,ForecastComparisonPlot.timeX(T+400,T,T+4500,20,920)-20,1e-4);
    }
    @Test public void historyIsBoundedAndSelectedForecastIsRetained()throws Exception {
        JSONObject a=forecast("a",T);JSONArray bars=bars();
        ui(()->{SparklineView c=chart(scope(),a,bars);for(int i=1;i<50;i++)try{R742ForecastContractTest.feed(c,forecast("n"+i,T+i*60),bars);}catch(Exception e){throw new AssertionError(e);}
            assertTrue(c.priceSnapshotChoices().length()<=24);assertEquals("a",c.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id"));
        });
    }
}
