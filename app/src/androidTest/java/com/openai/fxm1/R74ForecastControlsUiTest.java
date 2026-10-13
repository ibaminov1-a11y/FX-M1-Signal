package com.openai.fxm1;
import android.view.*;import android.widget.*;
import androidx.test.rule.ActivityTestRule;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.*;import org.junit.runner.RunWith;import org.json.*;import static org.junit.Assert.*;
@RunWith(AndroidJUnit4.class)
public class R74ForecastControlsUiTest {
 @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class);
 private Button find(View v,String text){if(v instanceof Button&&text.equals(((Button)v).getText().toString()))return (Button)v;
  if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++){Button b=find(g.getChildAt(i),text);if(b!=null)return b;}}return null;}
 @Test public void actualButtonsSelectDistinctModesAndExposeHistory()throws Exception{
  JSONObject f=R74ForecastRegressionTest.frame(R74ForecastRegressionTest.T,"button-first");JSONArray bars=R74ForecastRegressionTest.bars();
  InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
   MainActivity a=rule.getActivity();ScenarioUi.setActive(a,false);SparklineView c=a.findViewById(R.id.sparklineView);
   c.setMarketIdentity("button-test-"+java.util.UUID.randomUUID());c.setMarket(bars,null,null,null,"SCENARIO_V2",null,null,f);
   View root=a.getWindow().getDecorView();Button forecast=find(root,"ПРОГНОЗ"),candles=find(root,"СВЕЧИ"),patterns=find(root,"СЦЕНАРИИ");
   assertNotNull(forecast);assertNotNull(candles);assertNotNull(patterns);
   forecast.performClick();assertEquals("FORECAST",c.displayedForecast().optString("chart_display_mode"));assertNotNull(PriceForecastPlot.visible(c.displayedForecast()));
   assertNotNull(find(root,"ИСТОРИЯ ПРОГНОЗОВ"));assertEquals(View.VISIBLE,((View)find(root,"НОВЫЙ").getParent()).getVisibility());
   candles.performClick();assertEquals("CANDLES",c.displayedForecast().optString("chart_display_mode"));assertNull(PriceForecastPlot.visible(c.displayedForecast()));
   patterns.performClick();assertEquals("PATTERNS",c.displayedForecast().optString("chart_display_mode"));
  });
 }
}
