package com.openai.fxm1;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;import org.junit.*;import org.junit.runner.RunWith;import static org.junit.Assert.*;
@RunWith(AndroidJUnit4.class)
public class R74ForecastWindowTest {
 static final long T=R74ForecastRegressionTest.T;
 private JSONObject frame(long t,String id)throws Exception {JSONObject f=R74ForecastRegressionTest.frame(t,id);f.put("timeframe","M1").put("chart_timeframe","M1");f.getJSONObject("price_forecast").put("timeframe","M1").put("scope","test|EURUSD|NORMAL|M1|ANALOG_R7_1");return f;}
 private JSONArray bars(long end)throws Exception{JSONArray a=new JSONArray();for(long t=T-7200;t<end;t+=60)a.put(new JSONObject().put("time",t).put("open",1.1).put("high",1.1002).put("low",1.0998).put("close",1.1001));return a;}
 @Test public void expiredSelectedForecastRetainsKnownComparisonCandles()throws Exception{
  Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();JSONObject first=frame(T,"first"),late=frame(T+7200,"late");JSONArray initial=bars(T),after=bars(T+7200);
  InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
   SparklineView v=R74ForecastRegressionTest.chart(c,initial,first);v.showPriceForecast(true);v.layout(0,0,1080,1300);
   v.setMarket(after,null,null,null,"SCENARIO_V2",null,null,late);
   R74ForecastHistoryTest.Picture p=new R74ForecastHistoryTest.Picture(1080,1300);v.draw(p);
   assertEquals("first",v.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id"));
   assertTrue("COMPARISON_CANDLES_LOST_BY_ROLLING_WINDOW: "+p.candles,p.candles>=100);p.bitmap.recycle();
  });
 }
 @Test public void explicitNewestReturnsFromCandleBrowsingToComparison()throws Exception{
  Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();JSONObject first=frame(T,"first");JSONArray history=bars(T);
  InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
   SparklineView v=R74ForecastRegressionTest.chart(c,history,first);v.showPriceForecast(true);v.panHistory(5);assertFalse(v.isFollowingLive());
   assertTrue(v.newestForecast());assertNotNull("EXPLICIT_FORECAST_SELECTION_STILL_HIDDEN",PriceForecastPlot.visible(v.displayedForecast()));
  });
 }
}
