package com.openai.fxm1;

import android.content.*;
import android.graphics.Point;
import android.os.*;
import android.view.View;
import android.view.MotionEvent;
import android.view.Window;
import android.widget.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.lang.reflect.InvocationTargetException;
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
    void shell(String command)throws Exception {
        try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);
            InputStream input=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] buffer=new byte[1024];while(input.read(buffer)!=-1){}}
    }
    void shot(String name)throws Exception {
        shell("mkdir -p /sdcard/Download/ec1-qa");
        shell("screencap -p /sdcard/Download/ec1-qa/"+name+".png");
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
    String gestureState(){
        LiveScrollView root=rule.getActivity().findViewById(R.id.rootLayout);
        StringBuilder value=new StringBuilder("scrollY=").append(root.getScrollY()).append(" enabled=").append(root.isEnabled())
            .append(" shown=").append(root.isShown()).append(" focused=").append(rule.getActivity().hasWindowFocus());
        for(String name:new String[]{"pullEligible","pulling","refreshing"})try{
            Field field=LiveScrollView.class.getDeclaredField(name);field.setAccessible(true);value.append(' ').append(name).append('=').append(field.get(root));
        }catch(Exception e){value.append(" reflection=").append(e.getClass().getSimpleName());}
        return value.toString();
    }
    void tracedPull(String name)throws Exception {
        final int[] received={0};
        ui(()->{
            Window window=rule.getActivity().getWindow();Window.Callback original=window.getCallback();
            window.setCallback((Window.Callback)Proxy.newProxyInstance(Window.Callback.class.getClassLoader(),new Class[]{Window.Callback.class},(proxy,method,args)->{
                MotionEvent event="dispatchTouchEvent".equals(method.getName())?(MotionEvent)args[0]:null;
                if(event!=null){received[0]++;android.util.Log.i("R54GestureTrace",name+" BEFORE action="+event.getActionMasked()+" x="+event.getX()+" y="+event.getY()+" "+gestureState());}
                try{
                    Object result=method.invoke(original,args);
                    if(event!=null)android.util.Log.i("R54GestureTrace",name+" AFTER action="+event.getActionMasked()+" "+gestureState());
                    return result;
                }catch(InvocationTargetException e){throw e.getCause();}
            }));
            android.util.Log.i("R54GestureTrace",name+" BEFORE SCREENSHOT "+gestureState());
        });
        shot(name+"-before");pull();
        ui(()->android.util.Log.i("R54GestureTrace",name+" AFTER PULL ActivityTouchEvents="+received[0]+" "+gestureState()));
        shot(name+"-after");
    }
    void assertReadOnly(){assertEquals("A pull must never issue configure, pause, enable or position commands",0,audit().optJSONArray("commands").length());}
    void startMonitoring()throws Exception {
        if(Build.VERSION.SDK_INT>=33)shell("pm grant "+context.getPackageName()+" android.permission.POST_NOTIFICATIONS");
        ui(()->rule.getActivity().findViewById(R.id.analyzeButton).performClick());
        await(()->prefs.getBoolean("bg_running",false)&&prefs.getBoolean("server_verified",false),"Monitoring must start");
        // The foreground service's initial heads-up notification covers the pull origin.
        // Open and close the real shade so the following gesture reaches the app.
        assertTrue(device.openNotification());
        assertTrue("Monitoring notification is visible",device.wait(Until.hasObject(By.pkg("com.android.systemui").textContains("FX M1")),5000));
        assertTrue(device.pressBack());
        await(()->{final boolean[] focused={false};ui(()->focused[0]=rule.getActivity().hasWindowFocus());return focused[0];},"App regains focus after closing notification shade");
        // A non-focusable heads-up can remain pinned after the shade closes.
        // Wait for that observed overlay itself, not merely for app focus.
        assertTrue("Monitoring heads-up must clear the pull origin",device.wait(Until.gone(By.pkg("com.android.systemui").textContains("FX M1")),10000));
        assertTrue(device.wait(Until.hasObject(By.res(context.getPackageName(),"refreshStatusText")),5000));
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
        shot("r54-refresh-success");
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
        fixture(new JSONObject().put("account_balance",53210.0));
        Field field=MainActivity.class.getDeclaredField("executor");field.setAccessible(true);
        ExecutorService queue=(ExecutorService)field.get(rule.getActivity());
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        queue.submit(()->{entered.countDown();try{release.await(22,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}});
        assertTrue(entered.await(5,TimeUnit.SECONDS));
        try{
            pull();await(this::loading,"Refresh must immediately expose visible progress");shot("r54-refresh-loading");
            pull();pull();
            assertTrue("Loading must survive duplicate gestures while the request is pending",loading());
            assertEquals("Held IO queue cannot complete the refresh during native gestures",0,audit().optInt("refresh_requests"));
        }finally{release.countDown();}
        await(()->!loading()&&refreshStatus().contains("Обновлено"),"One request must complete and remove progress");
        queue.submit(()->{}).get(5,TimeUnit.SECONDS);
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
        // This case checks an unsuperseded failure. R56's foreground chart now
        // reads /ec/state even with monitoring off; a newer successful read must
        // legitimately keep server_verified=true (covered by the concurrent case).
        // Stop that reader and drain pre-existing money work before the outage.
        Field money=MainActivity.class.getDeclaredField("lastMoneyRefreshMs");money.setAccessible(true);
        ui(()->{ScenarioUi.setActive(rule.getActivity(),false);
            try{money.setLong(rule.getActivity(),System.currentTimeMillis()+60000);}catch(Exception e){throw new AssertionError(e);}});
        Field worker=MainActivity.class.getDeclaredField("executor");worker.setAccessible(true);
        ((ExecutorService)worker.get(rule.getActivity())).submit(()->{}).get(8,TimeUnit.SECONDS);
        EventClient.poll();assertTrue("Fresh baseline before the isolated outage",prefs.getBoolean("server_verified",false));
        fixture(new JSONObject().put("fail",true));pull();
        await(()->!loading()&&refreshStatus().contains("Не удалось"),"HTTP failure must show an error and stop loading");
        assertFalse("A failed request cannot confirm cached data as fresh",prefs.getBoolean("server_verified",true));
        fixture(new JSONObject().put("fail",false).put("delay_ms",5000));top();pull();
        await(this::loading,"Timeout path starts visible progress");
        await(()->!loading()&&refreshStatus().contains("Не удалось"),"Transport timeout must always clear progress");
        assertFalse("A timed-out request cannot confirm cached data as fresh",prefs.getBoolean("server_verified",true));
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
        startMonitoring();fixture(new JSONObject().put("journal_delay_ms",2800));top();tracedPull("r54-monitor-journal");
        await(()->audit().optInt("refresh_requests")>=1,"Monitoring-mode pull must reach the forced refresh endpoint");
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

    @Test public void changedSourceRejectsOldRefreshWithoutInvalidatingNewSnapshot()throws Exception {
        // Keep the ledger audit specific to the interrupted full refresh; the
        // new chart's state-only foreground reads remain active throughout.
        Field money=MainActivity.class.getDeclaredField("lastMoneyRefreshMs");money.setAccessible(true);
        ui(()->{try{money.setLong(rule.getActivity(),System.currentTimeMillis()+60000);}catch(Exception e){throw new AssertionError(e);}});
        Field worker=MainActivity.class.getDeclaredField("executor");worker.setAccessible(true);
        ((ExecutorService)worker.get(rule.getActivity())).submit(()->{}).get(8,TimeUnit.SECONDS);
        fixture(new JSONObject().put("delay_ms",1600).put("account_balance",54321.0));pull();
        await(()->audit().optInt("refresh_requests")==1,"Old-source read started");
        String previousSource=EventClient.base();
        prefs.edit().putString("server_url","http://localhost:8765").commit();
        try{
            // A real accepted new connection must remain usable for foreground reads.
            // Supersede the old delayed fixture operation before changing broker data.
            fixture(new JSONObject().put("marker","new-connection"));
            EventClient.http("POST",EventClient.base()+"/test/r53-state",new JSONObject().put("balance",61234.0));
            EventClient.poll();
            assertEquals("New source delivered its actual account",61234.0,EventClient.state().getJSONObject("account").getDouble("balance"),.001);
            await(()->!loading()&&refreshStatus().contains("Не удалось"),"Changing connection cancels publication from the old source");
            assertEquals("Old connection cannot overwrite new connection data",61234.0,EventClient.state().getJSONObject("account").getDouble("balance"),.001);
            assertTrue("Old-source cancellation must not disconnect the newer source",prefs.getBoolean("server_verified",false));
            assertTrue(text(R.id.accountText).contains("61234.00"));
        }finally{prefs.edit().putString("server_url",previousSource).commit();}
        assertEquals("No old-refresh follow-up may mix in the new connection",0,audit().optInt("ledger_requests"));assertReadOnly();
    }

    @Test public void oldManualFailureDoesNotDisconnectSuccessfulConcurrentPolling()throws Exception {
        startMonitoring();fixture(new JSONObject().put("delay_ms",5000));top();tracedPull("r54-monitor-timeout");
        await(()->audit().optInt("refresh_requests")>=1,"Monitoring-mode pull must reach the forced refresh endpoint");
        await(()->!loading()&&refreshStatus().contains("Не удалось"),"Slow forced read times out");
        assertTrue("A failed older manual read cannot invalidate newer successful monitoring polls",prefs.getBoolean("server_verified",false));
        assertTrue(text(R.id.serverStatusText).contains("MT5: CONNECTED"));
    }
}
