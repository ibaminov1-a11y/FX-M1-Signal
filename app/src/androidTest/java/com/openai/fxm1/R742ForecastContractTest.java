package com.openai.fxm1;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Calls only APIs that already exist in R7.4: valid RED against the old APK. */
@RunWith(AndroidJUnit4.class)
public class R742ForecastContractTest {
    static final long T=1800000000L;
    static JSONObject forecast(String id,long issued,double origin)throws Exception {
        JSONArray points=new JSONArray();
        for(int minutes:new int[]{5,15,30,60})points.put(new JSONObject().put("minutes",minutes)
            .put("time",issued+minutes*60).put("center",origin+minutes*.000002)
            .put("low",origin+minutes*.000002-.0001).put("high",origin+minutes*.000002+.0001));
        JSONObject p=new JSONObject().put("available",true).put("snapshot_id",id).put("model","ANALOG_R7_1")
            .put("scope","demo@server|EURUSD|EURUSD|NORMAL|M5|ANALOG_R7_1")
            .put("symbol","EURUSD").put("timeframe","M5").put("issued_at",issued).put("origin",origin)
            .put("projection",points).put("calibrated",false);
        return new JSONObject().put("map_version",3).put("available",true).put("timeframe","M5")
            .put("chart_timeframe","M5").put("chart_symbol","EURUSD").put("chart_scope","demo@server|EURUSD")
            .put("chart_mode","NORMAL").put("chart_history_clock","UTC_NATIVE_R51").put("chart_digits",5)
            .put("data_asof",issued+1).put("live_price",origin).put("scenarios",new JSONArray())
            .put("show_price_forecast",false).put("price_forecast",p);
    }
    static JSONArray bars()throws Exception {return R7ReleaseUiTest.bars();}
    static void feed(SparklineView c,JSONObject f,JSONArray b){c.setMarket(b,new JSONArray(),new JSONArray(),new JSONArray(),"SCENARIO_V2",null,new JSONArray(),f);}
    static Context context(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
    @Test public void forecastButtonHasOwnModeNotPatterns()throws Exception {
        JSONObject f=forecast("issued-a",T,1.106);JSONArray b=bars();String before=f.toString();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            SparklineView c=new SparklineView(context());c.setMarketIdentity("r742-button-"+System.nanoTime());feed(c,f,b);
            c.showPriceForecast(true);
            assertEquals("FORECAST_BUTTON_IS_PATTERNS","FORECAST",c.displayedForecast().optString("chart_display_mode"));
            assertEquals("View must never mutate Bridge response",before,f.toString());
            c.showPriceForecast(false);assertEquals("PATTERNS",c.displayedForecast().optString("chart_display_mode"));
        });
    }
    @Test public void issuedForecastCannotBeRewrittenByNextMinute()throws Exception {
        JSONObject first=forecast("issued-a",T,1.106),next=forecast("issued-b",T+60,1.105);JSONArray b=bars();
        String frozen=first.getJSONObject("price_forecast").toString();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            SparklineView c=new SparklineView(context());c.setMarketIdentity("r742-fixed-"+System.nanoTime());feed(c,first,b);c.showPriceForecast(true);feed(c,next,b);
            assertEquals("ORIGINAL_FORECAST_OVERWRITTEN",frozen,c.displayedForecast().optJSONObject("price_forecast").toString());
        });
    }
}
