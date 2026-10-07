package com.openai.fxm1;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.util.UUID;
import static org.junit.Assert.*;

/** Actual Canvas and received numerical catalog. Never submits trading commands. */
@RunWith(AndroidJUnit4.class)
public class R75ChartContractUiTest {
 static class CountedJson extends JSONObject {
  int serializations=0;
  CountedJson(String s)throws JSONException{super(s);}
  @Override public String toString(){serializations++;return super.toString();}
 }
 private void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
 private SparklineView create(JSONObject s,JSONObject f){
  Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();
  SparklineView v=new SparklineView(c);v.setMarketIdentity("r75-test-"+UUID.randomUUID());v.layout(0,0,1080,660);
  v.setMarket(s.optJSONArray("bars"),new JSONArray(),new JSONArray(),new JSONArray(),"SCENARIO_V2",s.optJSONObject("live_bar"),new JSONArray(),f);return v;
 }
 private JSONObject pinned(JSONObject s)throws Exception {
  JSONObject f=new JSONObject(s.getJSONObject("forecast").toString());
  JSONObject root=new JSONObject().put("scenario_id","fixed-root-75").put("side",1).put("title","Закреплённый BUY")
   .put("status","WATCHING").put("stage","TOUCH_SEEN").put("target1",1.108).put("invalidation",1.099).put("trigger",1.103);
  f.put("execution_plan",new JSONObject().put("available",true).put("model","PINNED_V1").put("plan_id","fixed-root-75").put("side",1).put("title","Закреплённый BUY"));
  f.put("scenarios",new JSONArray().put(root));return f;
 }
 @Test public void repeatedFramesDoNotSerializeTheReceivedForecastAgain()throws Exception {
  JSONObject s=R732PatternRendererUiTest.from(17);CountedJson f=new CountedJson(s.getJSONObject("forecast").toString());
  ui(()->{
   SparklineView v=create(s,f);Bitmap bitmap=Bitmap.createBitmap(1080,660,Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(bitmap);
   try{v.draw(canvas);f.serializations=0;for(int i=0;i<30;i++)v.draw(canvas);
    assertEquals("SCROLL_REPARSES_UNCHANGED_FORECAST",0,f.serializations);
   }finally{bitmap.recycle();}
  });
 }
 @Test public void defaultFigureCannotReplaceThePinnedExecutionRoot()throws Exception {
  JSONObject s=R732PatternRendererUiTest.from(17),f=pinned(s);
  ui(()->{SparklineView v=create(s,f);JSONObject shown=v.displayedForecast();
   JSONObject root=shown.optJSONArray("scenarios").optJSONObject(0);
   assertNotNull("DISPLAY_REPLACED_PINNED_ROOT",root);
   assertEquals("DISPLAY_REPLACED_PINNED_ROOT","fixed-root-75",root.optString("scenario_id"));
   assertEquals("EXECUTION",shown.optString("chart_plan_role"));
   assertTrue(v.getContentDescription().toString().contains("ПЛАН ИСПОЛНЕНИЯ"));
  });
 }
 @Test public void explicitAlternativeIsLabeledAndCannotMutateExecutionPlan()throws Exception {
  JSONObject s=R732PatternRendererUiTest.from(17),f=pinned(s);String frozen=f.getJSONObject("execution_plan").toString();
  String id=R732PatternRendererUiTest.pattern(s).getString("view_id");
  ui(()->{SparklineView v=create(s,f);v.selectPattern(id);JSONObject shown=v.displayedForecast();
   assertEquals("ALTERNATIVE_ROLE_NOT_EXPLICIT","ALTERNATIVE",shown.optString("chart_plan_role"));
   assertEquals(frozen,f.optJSONObject("execution_plan").toString());
   assertTrue(v.getContentDescription().toString().contains("ПРОСМОТР АЛЬТЕРНАТИВЫ"));
  });
 }
 @Test public void returnedPresentationRemainsDetachedAndModeChangesInvalidateCache()throws Exception {
  JSONObject s=R732PatternRendererUiTest.from(17);JSONObject f=s.getJSONObject("forecast");
  ui(()->{SparklineView v=create(s,f);JSONObject first=v.displayedForecast();
   try{first.put("available",false);}catch(JSONException e){throw new AssertionError(e);}
   assertTrue(v.displayedForecast().optBoolean("available",true));
   v.setChartMode("CANDLES");assertEquals("CANDLES",v.displayedForecast().optString("chart_display_mode"));
   v.setChartMode("PATTERNS");assertEquals("PATTERNS",v.displayedForecast().optString("chart_display_mode"));
  });
 }
}
