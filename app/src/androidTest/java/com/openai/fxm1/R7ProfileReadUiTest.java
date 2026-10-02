package com.openai.fxm1;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Scope transitions cannot publish the former instrument into a newer selection. */
@RunWith(AndroidJUnit4.class)
public class R7ProfileReadUiTest {
    private final Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
    private JSONObject state(String id)throws Exception {
        return new JSONObject().put("profile_id",id)
            .put("capabilities",new JSONObject().put("profile_registry",true))
            .put("account",new JSONObject().put("balance",1000).put("equity",1000).put("type","DEMO").put("currency","USD").put("key","test@demo"))
            .put("account_age",0).put("config",new JSONObject().put("symbol","EUR/USD").put("timeframe","M5").put("mode","NORMAL"));
    }
    @Test public void oldProfileFailureDoesNotInvalidateCurrentProfile()throws Exception {
        EventClient.init(context);EventClient.prefs().edit().clear().putString("server_url","http://127.0.0.1:8765").putString("ec_token","test").commit();
        EventClient.cache(state("A"));EventClient.ReadRequest read=EventClient.newReadRequest();
        read.sequence=Long.MAX_VALUE-10;
        EventClient.cache(state("B"));
        EventClient.offlineIfCurrent(read,new java.io.IOException("A is offline"));
        assertTrue("An error for profile A marked profile B offline",EventClient.prefs().getBoolean("server_verified",false));
        assertEquals("B",EventClient.state().optString("profile_id"));
    }
    @Test public void selectingKnownInstrumentRestoresItsOwnFrameModeAndLot()throws Exception {
        EventClient.init(context);EventClient.prefs().edit().clear().commit();
        JSONObject gbp=new JSONObject().put("symbol","GBP/USD").put("timeframe","M15").put("mode","SCALP")
            .put("risk_pct",.5).put("lot_cap",.05).put("account_mode","DEMO");
        JSONObject eur=state("A").put("profiles",new JSONArray().put(new JSONObject().put("profile_id","B").put("symbol","GBPUSD").put("config",gbp)));
        EventClient.cache(eur);
        JSONObject selection=EventClient.rememberProfileSelection("GBP/USD",1,0,0);
        assertEquals("M15",selection.getString("timeframe"));
        assertEquals("SCALP",selection.getString("mode"));
        assertEquals(.05,selection.getDouble("lot_cap"),1e-10);
        assertEquals(.5,selection.getDouble("risk_pct"),1e-10);
        assertFalse("A view choice must not grant trading consent",selection.has("confirmation"));
    }
}
