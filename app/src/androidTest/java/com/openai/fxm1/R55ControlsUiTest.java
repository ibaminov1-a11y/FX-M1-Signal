package com.openai.fxm1;

import android.content.*;
import android.os.SystemClock;
import android.widget.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.lang.reflect.Method;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

/** Explicit profile choices must work independently of phone monitoring and quote readiness. */
@RunWith(AndroidJUnit4.class)
public class R55ControlsUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context; SharedPreferences prefs; UiDevice device;
    void ui(Runnable action){InstrumentationRegistry.getInstrumentation().runOnMainSync(action);}
    void await(BooleanSupplier condition,String message)throws Exception {
        long end=SystemClock.elapsedRealtime()+15000;
        while(SystemClock.elapsedRealtime()<end){if(condition.getAsBoolean())return;Thread.sleep(100);}
        fail(message);
    }
    JSONObject state()throws Exception{return EventClient.http("GET",EventClient.base()+"/ec/state",null);}
    void sync()throws Exception {
        Method method=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");method.setAccessible(true);
        ui(()->{try{method.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}});
    }
    void select(int id,String choice)throws Exception {
        ui(()->{Spinner spinner=rule.getActivity().findViewById(id);assertTrue("Profile selector must be usable",spinner.isEnabled());
            spinner.requestRectangleOnScreen(new android.graphics.Rect(0,0,spinner.getWidth(),spinner.getHeight()),true);
            assertTrue(spinner.performClick());});
        UiObject2 row=device.wait(Until.findObject(By.text(choice)),5000);assertNotNull(choice,row);row.click();
    }
    void prime(boolean campaign)throws Exception {
        EventClient.http("POST",EventClient.base()+"/test/r55-controls",new JSONObject().put("auto",true).put("campaign",campaign).put("quote_future",true));
        EventClient.poll();sync();
    }
    @Before public void setup()throws Exception {
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.wakeUp();device.pressHome();
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(300);
        prefs=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);
        prefs.edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r55-controls-client").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();
        rule.launchActivity(new Intent());InstrumentationRegistry.getInstrumentation().waitForIdleSync();
    }
    @After public void stop(){context.stopService(new Intent(context,MonitoringService.class));}

    @Test public void armedAutoWithInvalidQuoteKeepsAllProfileSelectorsUsable()throws Exception {
        prime(false);assertTrue(state().getBoolean("auto"));assertTrue(state().isNull("campaign"));
        ui(()->{for(int id:new int[]{R.id.symbolSpinner,R.id.entryTimeframeSpinner,R.id.signalModeSpinner,R.id.riskSpinner})
            assertTrue("AUTO without campaign must not disable profile controls: "+id,rule.getActivity().findViewById(id).isEnabled());});
    }
    @Test public void symbolAndModeChangesReachArmedBridgeWhilePhoneMonitoringIsStopped()throws Exception {
        prime(false);assertFalse(prefs.getBoolean("bg_running",false));
        select(R.id.symbolSpinner,"GBP/USD");
        await(()->"GBP/USD".equals(EventClient.state().optJSONObject("config").optString("symbol")),"Explicit symbol must reach Bridge without monitoring");
        select(R.id.signalModeSpinner,"SCALP");
        await(()->"SCALP".equals(EventClient.state().optJSONObject("config").optString("mode")),"Explicit SCALP must reach Bridge");
        JSONObject active=state();assertTrue(active.getBoolean("auto"));assertFalse(active.getBoolean("paused"));
        EventClient.poll();sync();assertEquals("GBP/USD",prefs.getString("selected_symbol",""));assertEquals(1,prefs.getInt("signal_mode_pos",-1));
        assertFalse(prefs.getBoolean("bg_running",false));
    }
    @Test public void selectedEntryTimeframeReachesTheBridgeProfile()throws Exception {
        prime(false);select(R.id.entryTimeframeSpinner,"M15");
        await(()->"M15".equals(EventClient.state().optJSONObject("config").optString("timeframe")),"M15 selection must reach actual Bridge profile");
        assertEquals("M15",EventClient.config().getString("timeframe"));assertTrue(state().getBoolean("auto"));
    }
    @Test public void campaignKeepsActiveProfileAndShowsDeferredChoiceAcrossPolls()throws Exception {
        prime(true);JSONObject before=state().getJSONObject("config");String campaignId=state().getJSONObject("campaign").getString("id");
        select(R.id.signalModeSpinner,"SCALP");
        await(()->EventClient.state().optJSONObject("pending_config")!=null,"Campaign choice must be queued");
        EventClient.poll();sync();JSONObject after=state();
        assertEquals(before.getString("mode"),after.getJSONObject("config").getString("mode"));
        assertEquals(campaignId,after.getJSONObject("campaign").getString("id"));
        assertEquals("SCALP",after.getJSONObject("pending_config").getString("mode"));
        ui(()->assertEquals("SCALP",((Spinner)rule.getActivity().findViewById(R.id.signalModeSpinner)).getSelectedItem().toString()));
        String screen=EventClient.prefs().getString("state_context","");assertTrue("Deferred profile must be visible",screen.contains("После кампании"));
    }
    @Test public void refreshingWithArmedAutoDoesNotIssueCommandsOrEraseChoice()throws Exception {
        prime(false);select(R.id.signalModeSpinner,"SCALP");
        await(()->"SCALP".equals(EventClient.state().optJSONObject("config").optString("mode")),"Explicit choice applied before refresh");
        int before=EventClient.http("GET",EventClient.base()+"/test/r53-command-audit",null).getJSONArray("commands").length();
        EventClient.refreshAll();sync();
        assertEquals(before,EventClient.http("GET",EventClient.base()+"/test/r53-command-audit",null).getJSONArray("commands").length());
        assertEquals("SCALP",state().getJSONObject("config").getString("mode"));assertTrue(state().getBoolean("auto"));
    }
}
