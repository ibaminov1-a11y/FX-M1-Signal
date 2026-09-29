package com.openai.fxm1;

import android.content.*;
import android.graphics.Point;
import android.os.*;
import android.view.View;
import android.widget.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.lang.reflect.Field;
import java.io.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

/** Real Android gestures -> read-only refresh -> production Bridge/fixture broker. */
@RunWith(AndroidJUnit4.class)
public class R54RefreshUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context; SharedPreferences prefs; UiDevice device;
    void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    void await(BooleanSupplier condition,String label)throws Exception {
        long end=SystemClock.elapsedRealtime()+15000;
        while(SystemClock.elapsedRealtime()<end){if(condition.getAsBoolean())return;Thread.sleep(80);}
        fail(label);
    }
    JSONObject audit(){try{return EventClient.http("GET",EventClient.base()+"/test/r54-refresh-audit",null);}
        catch(Exception e){throw new AssertionError(e);}}
    void fixture(JSONObject value)throws Exception{EventClient.http("POST",EventClient.base()+"/test/r54-refresh",value);}
    String text(int id){final String[] value={""};ui(()->value[0]=((TextView)rule.getActivity().findViewById(id)).getText().toString());return value[0];}
    int id(String name){return context.getResources().getIdentifier(name,"id",context.getPackageName());}
    String refreshStatus(){int id=id("refreshStatusText");return id==0?"":text(id);}
    boolean loading(){final boolean[] value={false};ui(()->{View progress=rule.getActivity().findViewById(id("refreshProgress"));value[0]=progress!=null&&progress.getVisibility()==View.VISIBLE;});return value[0];}
    int[] origin(){final int[] value=new int[2];ui(()->rule.getActivity().findViewById(R.id.rootLayout).getLocationOnScreen(value));return value;}
    int dp(int value){return Math.round(value*context.getResources().getDisplayMetrics().density);}
    void top()throws Exception{ui(()->((ScrollView)rule.getActivity().findViewById(R.id.rootLayout)).scrollTo(0,0));InstrumentationRegistry.getInstrumentation().waitForIdleSync();Thread.sleep(100);}
    void pull(){int[] p=origin();int x=device.getDisplayWidth()/2,y=p[1]+dp(76);assertTrue(device.swipe(x,y,x,y+dp(220),36));}
    void assertReadOnly(){assertEquals("A pull must never issue configure, pause, enable or position commands",0,audit().optJSONArray("commands").length());}
    void startMonitoring()throws Exception {
        if(Build.VERSION.SDK_INT>=33){
            try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(
                    "pm grant "+context.getPackageName()+" android.permission.POST_NOTIFICATIONS");
                InputStream input=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] buffer=new byte[1024];while(input.read(buffer)!=-1){}}
        }
        ui(()->rule.getActivity().findViewById(R.id.analyzeButton).performClick());
        await(()->prefs.getBoolean("bg_running",false)&&prefs.getBoolean("server_verified",false),"Monitoring must start");
        Thread.sleep(800);
    }
    @Before public void setup()throws Exception {
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.wakeUp();device.pressHome();
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(400);
        prefs=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);
        prefs.edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r54-refresh-client").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();
        rule.launchActivity(new Intent());InstrumentationRegistry.getInstrumentation().waitForIdleSync();Thread.sleep(500);top();
    }
    @After public void stop(){context.stopService(new Intent(context,MonitoringService.class));}

    @Test public void downwardSwipeRefreshesWholeScreenWhileMonitoringIsStoppedWithoutCommands()throws Exception {
        EventClient.http("POST",EventClient.base()+"/test/r53-state",new JSONObject().put("manual_position",true).put("completed_trade",true));
        fixture(new JSONObject().put("account_balance",54321.0).put("delay_ms",800).put("marker","r54-fresh"));
        int oldLedger=audit().optInt("ledger_requests"),oldJournal=audit().optInt("events_requests");
        // A refresh may read data but cannot consume a pending command from the normal poll path.
        prefs.edit().putBoolean("ec_mode_pause_pending",true).commit();pull();
        await(()->audit().optInt("refresh_requests")==1,"Downward swipe from top must request a full Bridge refresh");
        await(()->text(R.id.accountText).contains("54321.00"),"Manual refresh must repaint the fresh account without starting monitoring");
        await(()->!loading()&&refreshStatus().contains("Обновлено"),"Refresh must finish with visible success");
        assertTrue(text(R.id.positionsText),text(R.id.positionsText).contains("Открытые позиции: 1"));
        assertTrue("Both recent and full trade history must be read",audit().optInt("ledger_requests")>=oldLedger+2);
        assertTrue("Bridge event journal must be read",audit().optInt("events_requests")>oldJournal);
        assertTrue("Fresh Bridge journal must repaint on the screen",text(R.id.journalText).contains("r54-fresh"));
        assertFalse("Pull must not start monitoring",prefs.getBoolean("bg_running",false));
        assertFalse("Pull must not enable AUTO",EventClient.state().optBoolean("auto",false));
        assertTrue("Read-only refresh must leave pending explicit command to normal poll",prefs.getBoolean("ec_mode_pause_pending",false));
        assertReadOnly();
    }

    @Test public void repeatedPullsCoalesceWhileVisibleProgressIsRunning()throws Exception {
        fixture(new JSONObject().put("account_balance",53210.0).put("delay_ms",2200));pull();
        await(this::loading,"Refresh must immediately expose visible progress");pull();pull();
        assertTrue("Loading must survive duplicate gestures",loading());
        await(()->!loading()&&refreshStatus().contains("Обновлено"),"One request must complete and remove progress");
        assertEquals("Repeated pulls during one request must coalesce",1,audit().optInt("refresh_requests"));assertReadOnly();
    }

    @Test public void shortHorizontalMultitouchAndScrolledGesturesDoNotRefresh()throws Exception {
        fixture(new JSONObject());int[] p=origin();int x=device.getDisplayWidth()/2,y=p[1]+dp(76);
        assertTrue(device.swipe(x,y,x,y+dp(20),20));
        assertTrue(device.swipe(x-dp(70),y,x+dp(70),y+dp(3),30));
        UiObject root=device.findObject(new UiSelector().resourceId(context.getPackageName()+":id/rootLayout"));
        assertTrue(root.performTwoPointerGesture(new Point(x-dp(35),y),new Point(x+dp(35),y),
            new Point(x-dp(55),y+dp(150)),new Point(x+dp(55),y+dp(150)),30));
        ui(()->((ScrollView)rule.getActivity().findViewById(R.id.rootLayout)).scrollTo(0,dp(600)));
        InstrumentationRegistry.getInstrumentation().waitForIdleSync();pull();Thread.sleep(500);
        assertEquals("Only a deliberate single-finger vertical pull starting at top may refresh",0,audit().optInt("refresh_requests"));assertReadOnly();
    }

    @Test public void failedAndTimedOutRefreshesClearProgressAndRecoveryShowsFreshSuccess()throws Exception {
        fixture(new JSONObject().put("fail",true));pull();
        await(()->!loading()&&refreshStatus().contains("Не удалось"),"HTTP failure must show an error and stop loading");
        assertFalse("A failed request cannot confirm cached data as fresh",prefs.getBoolean("server_verified",true));
        fixture(new JSONObject().put("fail",false).put("delay_ms",5000));top();pull();
        await(this::loading,"Timeout path starts visible progress");
        await(()->!loading()&&refreshStatus().contains("Не удалось"),"Transport timeout must always clear progress");
        fixture(new JSONObject().put("delay_ms",0).put("account_balance",52109.0));top();pull();
        await(()->!loading()&&refreshStatus().contains("Обновлено")&&text(R.id.accountText).contains("52109.00"),"Next pull must recover and show only fresh success");assertReadOnly();
    }

    @Test public void partialHistoryFailureIsVisibleWithoutDiscardingFreshAccount()throws Exception {
        EventClient.http("POST",EventClient.base()+"/test/r53-state",new JSONObject().put("history_failure",true));
        fixture(new JSONObject().put("account_balance",51098.0));pull();
        await(()->!loading()&&refreshStatus().contains("Частично"),"Incomplete snapshot must report partial refresh rather than success");
        assertTrue("Available account data still repaints",text(R.id.accountText).contains("51098.00"));assertReadOnly();
    }

    @Test public void finishingDuringRefreshDoesNotDeliverToDestroyedActivity()throws Exception {
        fixture(new JSONObject().put("delay_ms",1800));pull();await(this::loading,"Request started");
        rule.finishActivity();Thread.sleep(2200);
        assertEquals(1,audit().optInt("refresh_requests"));assertReadOnly();
    }

    @Test public void busyClientQueueHasBoundedLoadingAndDoesNotSendCancelledRefreshLater()throws Exception {
        fixture(new JSONObject().put("account_balance",50987.0));
        Field field=MainActivity.class.getDeclaredField("executor");field.setAccessible(true);
        ExecutorService queue=(ExecutorService)field.get(rule.getActivity());
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        queue.submit(()->{entered.countDown();try{release.await(22,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}});
        assertTrue(entered.await(5,TimeUnit.SECONDS));
        try{
            pull();await(this::loading,"Queued request exposes loading immediately");
            long end=SystemClock.elapsedRealtime()+18000;
            while(loading()&&SystemClock.elapsedRealtime()<end)Thread.sleep(80);
            assertFalse("Loading must have an overall deadline even before transport starts",loading());
            assertTrue(refreshStatus(),refreshStatus().contains("Не удалось"));
        }finally{release.countDown();}
        Thread.sleep(400);assertEquals("Timed-out queued refresh cannot later become a stale success",0,audit().optInt("refresh_requests"));
        top();pull();await(()->!loading()&&refreshStatus().contains("Обновлено")&&text(R.id.accountText).contains("50987.00"),"A new pull recovers after the cancelled task");
        assertReadOnly();
    }

    @Test public void slowRefreshDoesNotBlockMonitoringOrEmergencyAndCannotOverwriteNewState()throws Exception {
        startMonitoring();fixture(new JSONObject().put("journal_delay_ms",2800));top();pull();
        await(()->audit().optInt("events_requests")==1,"Manual refresh reached the delayed journal");
        long previous=prefs.getLong("ec_received_elapsed",0),deadline=SystemClock.elapsedRealtime()+1500;
        while(prefs.getLong("ec_received_elapsed",0)<=previous&&SystemClock.elapsedRealtime()<deadline)Thread.sleep(50);
        assertTrue("A regular monitoring poll must complete while journal refresh is still pending",prefs.getLong("ec_received_elapsed",0)>previous);
        assertTrue("Manual request still waits on its slow auxiliary read",loading());
        ui(()->{rule.getActivity().findViewById(R.id.emergencyStopButton).performClick();rule.getActivity().findViewById(R.id.emergencyStopButton).performClick();});
        deadline=SystemClock.elapsedRealtime()+1500;boolean sent=false;
        while(SystemClock.elapsedRealtime()<deadline){
            JSONArray commands=audit().optJSONArray("commands");
            for(int i=0;i<commands.length();i++)sent|="emergency".equals(commands.optJSONObject(i).optString("command"));
            if(sent)break;Thread.sleep(50);
        }
        assertTrue("Emergency must reach Bridge without waiting for the manual refresh batch",sent);
        await(()->!loading(),"Manual refresh eventually completes");
        assertTrue("An older manual snapshot cannot erase the newer emergency acknowledgement",EventClient.state().optBoolean("emergency",false));
    }

    @Test public void changedCredentialsRejectOldRefreshWithoutInvalidatingNewSnapshot()throws Exception {
        fixture(new JSONObject().put("delay_ms",1600).put("account_balance",54321.0));pull();
        await(()->audit().optInt("refresh_requests")==1,"Old-source read started");
        JSONObject replacement=new JSONObject(EventClient.state().toString());replacement.getJSONObject("account").put("balance",61234.0);
        prefs.edit().putString("ec_token","replacement-connection-token").commit();
        EventClient.cache(replacement); // A newer connection has already delivered its own snapshot.
        try{
            await(()->!loading()&&refreshStatus().contains("Не удалось"),"Changing connection cancels publication from the old source");
            assertEquals("Old connection cannot overwrite new connection data",61234.0,EventClient.state().getJSONObject("account").getDouble("balance"),.001);
            assertTrue("Old-source cancellation must not disconnect the newer source",prefs.getBoolean("server_verified",false));
            assertTrue(text(R.id.accountText).contains("61234.00"));
        }finally{prefs.edit().putString("ec_token","ci-fixture-token-not-for-real-trading").commit();}
        assertEquals("No follow-up request may mix in credentials from the new connection",0,audit().optInt("ledger_requests"));assertReadOnly();
    }

    @Test public void oldManualFailureDoesNotDisconnectSuccessfulConcurrentPolling()throws Exception {
        startMonitoring();fixture(new JSONObject().put("delay_ms",5000));top();pull();
        await(()->!loading()&&refreshStatus().contains("Не удалось"),"Slow forced read times out");
        assertTrue("A failed older manual read cannot invalidate newer successful monitoring polls",prefs.getBoolean("server_verified",false));
        assertTrue(text(R.id.serverStatusText).contains("MT5: CONNECTED"));
    }
}
