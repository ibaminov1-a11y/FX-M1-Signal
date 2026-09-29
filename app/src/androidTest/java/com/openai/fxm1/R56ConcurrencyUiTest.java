package com.openai.fxm1;

import android.app.*;
import android.content.*;
import android.os.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.io.InputStream;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

/** Real held HTTP reads and native service readiness expose concurrent publication races. */
@RunWith(AndroidJUnit4.class)
public class R56ConcurrencyUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context;SharedPreferences prefs;
    void ui(Runnable action){InstrumentationRegistry.getInstrumentation().runOnMainSync(action);}
    void await(BooleanSupplier condition,String message)throws Exception{
        long end=SystemClock.elapsedRealtime()+6000;
        while(SystemClock.elapsedRealtime()<end){if(condition.getAsBoolean())return;Thread.sleep(40);}fail(message);
    }
    JSONObject fixture(String method,String path,JSONObject data)throws Exception{return EventClient.http(method,EventClient.base()+path,data);}
    @Before public void setup()throws Exception{
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();context.stopService(new Intent(context,MonitoringService.class));
        prefs=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);
        prefs.edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r56-concurrency").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);fixture("POST","/test/reset",new JSONObject());EventClient.poll();
    }
    @After public void stop(){context.stopService(new Intent(context,MonitoringService.class));if(rule.getActivity()!=null)rule.finishActivity();}
    @Test public void acceptedResetRejectsAnOlderEmergencySnapshotButFreshEmergencyStillLatches()throws Exception{
        EventClient.command("emergency",new JSONObject());EventClient.poll();assertTrue(prefs.getBoolean("v108_emergency_latched",false));
        fixture("POST","/test/r56-read-hold",new JSONObject().put("hold",true));
        ExecutorService reads=Executors.newSingleThreadExecutor();Future<JSONObject> old=reads.submit(EventClient::poll);
        try{
            await(()->{try{return fixture("GET","/test/r56-read-hold",null).optBoolean("captured");}catch(Exception e){throw new AssertionError(e);}},"Pre-reset emergency snapshot is held in transport");
            EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));
            assertFalse("Accepted reset clears local emergency immediately",prefs.getBoolean("v108_emergency_latched",true));
            fixture("POST","/test/r56-read-release",new JSONObject());old.get(4,TimeUnit.SECONDS);
            assertFalse("An older HTTP response cannot restore the cleared emergency latch",prefs.getBoolean("v108_emergency_latched",true));
            EventClient.poll();assertFalse(EventClient.state().optBoolean("emergency",true));assertFalse(prefs.getBoolean("ec_emergency_pending",true));
            EventClient.command("emergency",new JSONObject());EventClient.poll();
            assertTrue("A new real emergency must still latch",prefs.getBoolean("v108_emergency_latched",false));
        }finally{fixture("POST","/test/r56-read-release",new JSONObject());old.cancel(true);reads.shutdownNow();}
    }
    @Test public void acceptedResetRejectsOlderConfigureSnapshotAndPreservesDraft()throws Exception{
        EventClient.configure();
        for(boolean explicit:new boolean[]{false,true}){
            EventClient.command("emergency",new JSONObject());EventClient.poll();
            JSONObject desired=EventClient.rememberProfileSelection("EUR/USD",1,0,0);
            prefs.edit().putString("ec_config_sent","unacknowledged-selection").commit();
            fixture("POST","/test/r56-read-hold",new JSONObject().put("hold",true));
            ExecutorService reads=Executors.newSingleThreadExecutor();Future<?> old=reads.submit(()->{
                if(explicit)EventClient.configureUserSelection(desired);else EventClient.configure();return null;
            });
            try{
                await(()->{try{return fixture("GET","/test/r56-read-hold",null).optBoolean("captured");}catch(Exception e){throw new AssertionError(e);}},"Pre-reset configure snapshot is held in transport");
                EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));
                fixture("POST","/test/r56-read-release",new JSONObject());old.get(4,TimeUnit.SECONDS);
                assertFalse("An older configure response cannot restore the cleared emergency latch",prefs.getBoolean("v108_emergency_latched",true));
                assertTrue("Discarded configure snapshot cannot acknowledge the local draft",EventClient.hasProfileDraft());
                assertEquals("Discarded configure snapshot cannot acknowledge the sent profile","unacknowledged-selection",prefs.getString("ec_config_sent",""));
            }finally{fixture("POST","/test/r56-read-release",new JSONObject());old.cancel(true);reads.shutdownNow();}
        }
    }
    @Test public void rejectedResetPreservesEmergencyLatchAndPendingRetry()throws Exception{
        EventClient.command("emergency",new JSONObject());EventClient.poll();prefs.edit().putBoolean("ec_emergency_pending",true).commit();
        try{EventClient.command("reset",new JSONObject().put("confirmation","INVALID_RESET"));fail("Bridge must reject invalid reset confirmation");}
        catch(java.io.IOException expected){assertTrue(prefs.getBoolean("v108_emergency_latched",false));assertTrue(prefs.getBoolean("ec_emergency_pending",false));}
        assertTrue(EventClient.state().optBoolean("emergency",false));
    }
    @Test public void newerOrdinaryPollDoesNotDiscardAnExplicitProfileSelection()throws Exception{
        EventClient.configure();JSONObject desired=EventClient.rememberProfileSelection("EUR/USD",4,0,0);
        fixture("POST","/test/r56-read-hold",new JSONObject().put("hold",true));
        ExecutorService reads=Executors.newSingleThreadExecutor();Future<?> old=reads.submit(()->{EventClient.configureUserSelection(desired);return null;});
        try{
            await(()->{try{return fixture("GET","/test/r56-read-hold",null).optBoolean("captured");}catch(Exception e){throw new AssertionError(e);}},"Initial configure snapshot is held in transport");
            EventClient.poll();
            fixture("POST","/test/r56-read-release",new JSONObject());old.get(4,TimeUnit.SECONDS);
            JSONObject remote=fixture("GET","/ec/state",null);
            assertEquals("A newer ordinary poll cannot discard an explicit profile selection",desired.optString("timeframe"),remote.getJSONObject("config").optString("timeframe"));
            assertFalse("Accepted configure confirmation acknowledges the selected profile",EventClient.hasProfileDraft());
        }finally{fixture("POST","/test/r56-read-release",new JSONObject());old.cancel(true);reads.shutdownNow();}
    }
    boolean serviceIsForeground(){
        ActivityManager manager=(ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
        for(ActivityManager.RunningServiceInfo service:manager.getRunningServices(Integer.MAX_VALUE))
            if(MonitoringService.class.getName().equals(service.service.getClassName()))return service.foreground;
        return false;
    }
    @Test public void runningFlagIsPublishedOnlyAfterNativeForegroundPromotion()throws Exception{
        if(Build.VERSION.SDK_INT>=33)try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation()
            .executeShellCommand("pm grant "+context.getPackageName()+" android.permission.POST_NOTIFICATIONS");
            InputStream input=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] bytes=new byte[1024];while(input.read(bytes)!=-1){}}
        rule.launchActivity(new Intent());InstrumentationRegistry.getInstrumentation().waitForIdleSync();
        AtomicBoolean observed=new AtomicBoolean(),foregroundAtPublication=new AtomicBoolean();
        SharedPreferences.OnSharedPreferenceChangeListener listener=(p,key)->{
            if("bg_running".equals(key)&&p.getBoolean(key,false)&&!observed.get()){
                foregroundAtPublication.set(serviceIsForeground());observed.set(true);
            }
        };
        prefs.registerOnSharedPreferenceChangeListener(listener);
        try{
            ui(()->assertTrue(rule.getActivity().findViewById(R.id.analyzeButton).performClick()));
            await(observed::get,"Service publishes its running state");
            // Let old builds complete promotion before teardown, so RED is the
            // readiness assertion and not a platform crash from premature stop.
            await(this::serviceIsForeground,"Native service becomes foreground");
            assertTrue("bg_running is an acknowledgement of completed foreground promotion",foregroundAtPublication.get());
        }finally{prefs.unregisterOnSharedPreferenceChangeListener(listener);context.stopService(new Intent(context,MonitoringService.class));}
    }
}
