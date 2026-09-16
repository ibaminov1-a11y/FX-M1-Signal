package com.openai.fxm1;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class R3PresentationTest {
 @Test public void bridgeImpulsePathAppearsInCachedContext() throws Exception {
  Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
  EventClient.init(context);
  EventClient.prefs().edit().clear().putBoolean("ec1_migrated",true).commit();
  long now=System.currentTimeMillis();
  JSONObject state=new JSONObject()
   .put("account_age",0)
   .put("account",new JSONObject().put("balance",100000).put("equity",100000).put("type","DEMO").put("currency","USD"))
   .put("config",new JSONObject().put("symbol","EUR/USD").put("timeframe","M5").put("mode","NORMAL"))
   .put("decision",new JSONObject().put("signal","BUY").put("phase","ENTRY_READY").put("path","IMPULSE").put("reason","R3 test impulse"))
   .put("quote",new JSONObject().put("bid",1.1).put("ask",1.1001).put("time_msc",now))
   .put("risk",new JSONObject().put("allowed",true).put("blocks",new JSONArray()))
   .put("all_positions",new JSONArray()).put("auto",true).put("paused",false)
   .put("analysis_time",now/1000.0).put("history_ok",false).put("execution","test");
  EventClient.cache(state);
  String rendered=EventClient.prefs().getString("state_context","");
  assertTrue(rendered,rendered.contains("Путь: Импульс"));
  assertTrue(rendered,rendered.contains("Этап: Вход подтверждён"));
 }
}
