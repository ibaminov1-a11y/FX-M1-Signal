package com.openai.fxm1;

import android.content.Context;
import android.content.SharedPreferences;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class CampaignSignalUiTest {
    @Test public void openCampaignMustNotOverwriteCurrentAnalysisSignal() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        SharedPreferences p=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);
        p.edit().clear().putBoolean("ec1_migrated",true).commit();
        EventClient.init(context);
        long now=System.currentTimeMillis();
        JSONObject state=new JSONObject()
            .put("account",new JSONObject().put("balance",100000).put("equity",99999).put("type","DEMO").put("currency","USD"))
            .put("account_age",0)
            .put("config",new JSONObject().put("symbol","EUR/USD").put("timeframe","M5").put("mode","NORMAL"))
            .put("decision",new JSONObject().put("signal","BUY").put("phase","ENTRY_READY").put("path","IMPULSE")
                .put("reason","Подтверждён новый BUY").put("stop",1.1520))
            .put("quote",new JSONObject().put("time_msc",now).put("bid",1.1535).put("ask",1.15351))
            .put("risk",new JSONObject().put("allowed",true).put("blocks",new JSONArray()))
            .put("campaign",new JSONObject().put("side",-1).put("mode","NORMAL"))
            .put("auto",true).put("paused",false).put("execution","сопровождение старой SELL кампании")
            .put("history_ok",false);
        EventClient.cache(state);
        assertEquals("BUY",p.getString("state_signal",""));
        String contextText=p.getString("state_context","");
        assertTrue(contextText.contains("Этап: Вход подтверждён"));
        assertTrue(contextText.contains("Открытая кампания: SELL"));
    }
}
