package com.openai.fxm1;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Native tests against the shipped public chart API; no MT5 or order requests. */
@RunWith(AndroidJUnit4.class)
public class R74ForecastRegressionTest {
    static final long T=1800000000L;
    static JSONObject frame(long issued,String id)throws Exception {
        JSONArray points=new JSONArray();
        for(int minutes:new int[]{5,10,15,30,60}) {
            double value=1.1000+minutes*.00001;
            points.put(new JSONObject().put("minutes",minutes).put("time",issued+minutes*60)
                .put("center",value).put("low",value-.0001).put("high",value+.0001).put("sample_count",12));
        }
        JSONObject price=new JSONObject().put("available",true).put("snapshot_id",id).put("issued_at",issued)
            .put("origin",1.1000).put("symbol","EURUSD").put("timeframe","M5").put("mode","NORMAL")
            .put("model","ANALOG_R7_1").put("scope","test|EURUSD|NORMAL|M5|ANALOG_R7_1")
            .put("projection",points).put("calibrated",false);
        return new JSONObject().put("map_version",3).put("available",true).put("timeframe","M5")
            .put("chart_symbol","EURUSD").put("chart_timeframe","M5").put("chart_scope","test")
            .put("chart_mode","NORMAL").put("chart_history_clock","clock-A").put("data_asof",issued+1)
            .put("live_price",1.1000).put("scenarios",new JSONArray()).put("price_forecast",price);
    }
    static JSONArray bars()throws Exception {
        JSONArray result=new JSONArray();
        for(int i=0;i<20;i++)result.put(new JSONObject().put("time",T-(20-i)*300)
            .put("open",1.0996+i*.00002).put("close",1.0997+i*.00002)
            .put("low",1.0995+i*.00002).put("high",1.0998+i*.00002));
        return result;
    }
    static SparklineView chart(Context c,JSONArray bars,JSONObject frame){
        SparklineView v=new SparklineView(c);v.setMarketIdentity("forecast-test-"+java.util.UUID.randomUUID());
        v.setMarket(bars,null,null,null,"SCENARIO_V2",null,null,frame);return v;
    }
    @Test public void forecastButtonEnablesDedicatedMode()throws Exception {
        JSONObject f=frame(T,"first");JSONArray b=bars();Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            SparklineView v=chart(c,b,f);v.showPriceForecast(true);
            assertEquals("FORECAST_BUTTON_IS_STILL_PATTERNS","FORECAST",v.displayedForecast().optString("chart_display_mode"));
        });
    }
    @Test public void explicitForecastModeDoesNotRejectValidPricePoints()throws Exception {
        JSONObject f=frame(T,"first").put("chart_display_mode","FORECAST").put("show_price_forecast",true);
        assertNotNull("EXPLICIT_FORECAST_IS_HIDDEN",PriceForecastPlot.visible(f));
    }
    @Test public void newQuoteCannotReplaceSelectedIssuedForecast()throws Exception {
        JSONObject first=frame(T,"first"),next=frame(T+60,"next");JSONArray b=bars();
        Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            SparklineView v=chart(c,b,first);v.showPriceForecast(true);
            v.setMarket(b,null,null,null,"SCENARIO_V2",null,null,next);
            assertEquals("ISSUED_FORECAST_WAS_REWRITTEN","first",v.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id"));
        });
    }
}
