package com.openai.fxm1;

import android.content.*;
import android.app.Activity;
import android.os.ParcelFileDescriptor;
import java.io.InputStream;
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry;
import androidx.test.runner.lifecycle.Stage;
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
    MainActivity activity(){
        for(Activity a:ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED))if(a instanceof MainActivity)return (MainActivity)a;
        throw new AssertionError("No resumed MainActivity");
    }
    void shot(String name)throws Exception {
        for(String cmd:new String[]{"mkdir -p /sdcard/Download/ec1-qa","screencap -p /sdcard/Download/ec1-qa/"+name+".png"})
            try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);
                InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] bytes=new byte[4096];while(in.read(bytes)!=-1){}}
    }
    void ui(Runnable action){InstrumentationRegistry.getInstrumentation().runOnMainSync(action);}
    void await(BooleanSupplier condition,String message)throws Exception {
        long end=SystemClock.elapsedRealtime()+15000;
        while(SystemClock.elapsedRealtime()<end){if(condition.getAsBoolean())return;Thread.sleep(100);}
        fail(message);
    }
    JSONObject state()throws Exception{return EventClient.http("GET",EventClient.base()+"/ec/state",null);}
    void sync()throws Exception {
        Method method=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");method.setAccessible(true);
        ui(()->{try{method.invoke(activity());}catch(Exception e){throw new AssertionError(e);}});
    }
    void select(int id,String choice)throws Exception {
        ui(()->{Spinner spinner=activity().findViewById(id);assertTrue("Profile selector must be usable",spinner.isEnabled());
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
    @After public void stop(){context.stopService(new Intent(context,MonitoringService.class));
        ui(()->{for(Activity a:new java.util.ArrayList<>(ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)))
            if(a instanceof MainActivity)a.finish();});}

    @Test public void armedAutoWithInvalidQuoteKeepsAllProfileSelectorsUsable()throws Exception {
        prime(false);assertTrue(state().getBoolean("auto"));assertTrue(state().isNull("campaign"));
        ui(()->{for(int id:new int[]{R.id.symbolSpinner,R.id.entryTimeframeSpinner,R.id.signalModeSpinner,R.id.riskSpinner})
            assertTrue("AUTO without campaign must not disable profile controls: "+id,activity().findViewById(id).isEnabled());});
    }
    @Test public void symbolAndModeChangesReachArmedBridgeWhilePhoneMonitoringIsStopped()throws Exception {
        prime(false);assertFalse(prefs.getBoolean("bg_running",false));
        select(R.id.symbolSpinner,"GBP/USD");
        await(()->"GBP/USD".equals(EventClient.state().optJSONObject("config").optString("symbol")),"Explicit symbol must reach Bridge without monitoring");
        select(R.id.signalModeSpinner,"SCALP");
        await(()->"SCALP".equals(EventClient.state().optJSONObject("config").optString("mode")),"Explicit SCALP must reach Bridge");
        JSONObject active=state();assertTrue(active.getBoolean("auto"));assertFalse(active.getBoolean("paused"));
        EventClient.poll();sync();assertEquals("GBP/USD",prefs.getString("selected_symbol",""));assertEquals(1,prefs.getInt("signal_mode_pos",-1));
        assertFalse(prefs.getBoolean("bg_running",false));shot("r55-auto-profile-selected");
    }
    @Test public void selectedEntryTimeframeReachesTheBridgeProfile()throws Exception {
        prime(false);select(R.id.entryTimeframeSpinner,"M15");
        await(()->"M15".equals(EventClient.state().optJSONObject("config").optString("timeframe")),"M15 selection must reach actual Bridge profile");
        assertEquals("M15",EventClient.config().getString("timeframe"));assertTrue(state().getBoolean("auto"));shot("r55-m15-selected");
    }
    @Test public void campaignKeepsActiveProfileAndShowsDeferredChoiceAcrossPolls()throws Exception {
        prime(true);JSONObject before=state().getJSONObject("config");String campaignId=state().getJSONObject("campaign").getString("id");
        select(R.id.signalModeSpinner,"SCALP");
        await(()->EventClient.state().optJSONObject("pending_config")!=null,"Campaign choice must be queued");
        EventClient.poll();sync();JSONObject after=state();
        assertEquals(before.getString("mode"),after.getJSONObject("config").getString("mode"));
        assertEquals(campaignId,after.getJSONObject("campaign").getString("id"));
        assertEquals("SCALP",after.getJSONObject("pending_config").getString("mode"));
        ui(()->assertEquals("SCALP",((Spinner)activity().findViewById(R.id.signalModeSpinner)).getSelectedItem().toString()));
        String screen=EventClient.prefs().getString("state_context","");assertTrue("Deferred profile must be visible",screen.contains("После кампании"));
        final MainActivity[] old={null};ui(()->{old[0]=activity();old[0].recreate();});
        await(()->{final boolean[] changed={false};ui(()->{for(Activity a:ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED))
            if(a instanceof MainActivity&&a!=old[0])changed[0]=true;});return changed[0];},"Activity recreated");
        ui(()->assertEquals("SCALP",((Spinner)activity().findViewById(R.id.signalModeSpinner)).getSelectedItem().toString()));shot("r55-deferred-profile");
    }
    @Test public void refreshingWithArmedAutoDoesNotIssueCommandsOrEraseChoice()throws Exception {
        prime(false);select(R.id.signalModeSpinner,"SCALP");
        await(()->"SCALP".equals(EventClient.state().optJSONObject("config").optString("mode")),"Explicit choice applied before refresh");
        int before=EventClient.http("GET",EventClient.base()+"/test/r53-command-audit",null).getJSONArray("commands").length();
        EventClient.refreshAll();sync();
        assertEquals(before,EventClient.http("GET",EventClient.base()+"/test/r53-command-audit",null).getJSONArray("commands").length());
        assertEquals("SCALP",state().getJSONObject("config").getString("mode"));assertTrue(state().getBoolean("auto"));
    }
    @Test public void explicitDraftSurvivesPollBeforeItsCommandIsSent()throws Exception {
        prime(false);
        EventClient.rememberProfileSelection("GBP/USD",3,1,1);
        EventClient.poll();EventClient.configure();
        assertEquals("GBP/USD",prefs.getString("selected_symbol",""));
        assertEquals("M15",EventClient.config().getString("timeframe"));
        assertEquals(1,prefs.getInt("signal_mode_pos",-1));assertTrue(EventClient.hasProfileDraft());
        assertEquals("EUR/USD",state().getJSONObject("config").getString("symbol"));
        assertEquals("Passive reads/startup must not send draft configuration",0,EventClient.http("GET",EventClient.base()+"/test/r53-command-audit",null).getJSONArray("commands").length());
    }
    @Test public void twoClosedTradesAgreeInMoneyStatisticsAndTradeJournal()throws Exception {
        for(int i=0;i<2;i++)EventClient.http("POST",EventClient.base()+"/test/r53-state",new JSONObject().put("completed_trade",true));
        EventClient.refreshAll();sync();
        assertEquals(2,state().getJSONObject("all").getInt("count"));
        ui(()->{
            String money=((TextView)activity().findViewById(R.id.positionsText)).getText().toString();
            String stats=((TextView)activity().findViewById(R.id.statsText)).getText().toString();
            String history=((TextView)activity().findViewById(R.id.tradeHistoryText)).getText().toString();
            assertTrue(money,money.contains("+0.60")&&money.contains("2 сдел."));
            assertTrue(stats,stats.contains("Закрытых: 2")&&stats.contains("+0.60"));
            assertEquals("Both trades must appear in journal",2,history.split("NET ",-1).length-1);
        });shot("r55-two-trade-totals");
    }

    @Test public void acceptedEnableClearsMatchingDraftButOlderSnapshotKeepsNewerChoice()throws Exception {
        prime(true);
        EventClient.rememberProfileSelection("EUR/USD",1,1,0);
        assertTrue(EventClient.hasProfileDraft());
        // Reproduce configuration transport failure followed by successful explicit AUTO.
        prefs.edit().putString("ec_token","wrong-token").commit();
        try{EventClient.configureUserSelection();fail("Configuration with wrong credentials must fail");}
        catch(java.io.IOException expected){assertTrue(EventClient.hasProfileDraft());}
        prefs.edit().putString("ec_token","ci-fixture-token-not-for-real-trading").commit();
        EventClient.command("enable",new JSONObject().put("confirmation","ENABLE_DEMO"));
        JSONObject accepted=EventClient.poll();
        assertEquals("SCALP",accepted.getJSONObject("pending_config").getString("mode"));
        assertFalse("Matching server acceptance clears draft even when configure's response was lost",EventClient.hasProfileDraft());
        EventClient.rememberProfileSelection("GBP/USD",3,1,0);
        EventClient.cache(accepted);
        assertTrue("Acceptance of previous selection cannot clear newer unmatched draft",EventClient.hasProfileDraft());
        assertEquals("GBP/USD",prefs.getString("selected_symbol",""));
        assertEquals("M15",EventClient.config().getString("timeframe"));
        EventClient.configureUserSelection();EventClient.poll();
        assertFalse("Matching accepted pending profile releases the newer draft",EventClient.hasProfileDraft());
    }

    @Test public void smartStatusDetailsShowFullCurrentBridgeStateWithoutResizingPreview()throws Exception {
        prime(false);
        final int[] height={0};
        ui(()->{TextView status=activity().findViewById(R.id.smartStatusText);height[0]=status.getHeight();
            assertTrue(((TextView)activity().findViewById(R.id.smartTitleText)).getText().toString().contains("нажмите"));status.performClick();});
        UiObject2 details=device.wait(Until.findObject(By.textStartsWith("Снимок на момент открытия")),5000);
        assertNotNull("Full smart status opens in a reading dialog",details);
        assertTrue(details.getText(),details.getText().contains("AUTO DEMO включён")&&details.getText().contains("REAL-исполнение заблокировано"));
        device.findObject(By.text("ЗАКРЫТЬ")).click();
        EventClient.command("disable",new JSONObject());EventClient.poll();sync();
        ui(()->activity().findViewById(R.id.smartStatusText).performClick());
        details=device.wait(Until.findObject(By.textStartsWith("Снимок на момент открытия")),5000);
        assertNotNull(details);assertTrue(details.getText(),details.getText().contains("PAUSE: новые входы"));
        ui(()->assertEquals("Live preview keeps fixed geometry",height[0],activity().findViewById(R.id.smartStatusText).getHeight()));
        device.findObject(By.text("ЗАКРЫТЬ")).click();
    }

}
