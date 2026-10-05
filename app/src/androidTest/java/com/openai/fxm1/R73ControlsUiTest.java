package com.openai.fxm1;

import android.content.*;
import android.os.SystemClock;
import android.widget.Switch;
import android.widget.TextView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.lang.reflect.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

/** Native controls, real HTTP and deliberately held work reproduce R7.3 races. */
@RunWith(AndroidJUnit4.class)
public class R73ControlsUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context; SharedPreferences prefs;
    void ui(Runnable action){InstrumentationRegistry.getInstrumentation().runOnMainSync(action);}
    void await(BooleanSupplier condition,long timeout,String message)throws Exception{
        long end=SystemClock.elapsedRealtime()+timeout;
        while(SystemClock.elapsedRealtime()<end){if(condition.getAsBoolean())return;Thread.sleep(25);}fail(message);
    }
    JSONObject fixture(String method,String path,JSONObject body)throws Exception{return EventClient.http(method,EventClient.base()+path,body);}
    void invoke(String name,Class<?>[] types,Object... values){
        try{Method method=MainActivity.class.getDeclaredMethod(name,types);method.setAccessible(true);method.invoke(rule.getActivity(),values);}
        catch(Exception e){throw new AssertionError(e);}
    }
    void sync(){ui(()->invoke("restoreTradingSnapshotFromPrefs",new Class<?>[]{}));}
    ExecutorService queue(String preferred)throws Exception{
        Field field;try{field=MainActivity.class.getDeclaredField(preferred);}catch(NoSuchFieldException e){field=MainActivity.class.getDeclaredField("executor");}
        field.setAccessible(true);return (ExecutorService)field.get(rule.getActivity());
    }
    void command(String name){ui(()->invoke("eventCommand",new Class<?>[]{String.class,JSONObject.class},name,new JSONObject()));}
    int audit(){try{return fixture("GET","/test/r53-command-audit",null).getJSONArray("commands").length();}catch(Exception e){throw new AssertionError(e);}}
    @Before public void setup()throws Exception{
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();context.stopService(new Intent(context,MonitoringService.class));
        prefs=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);
        prefs.edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r73-controls").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);fixture("POST","/test/reset",new JSONObject());EventClient.poll();
        rule.launchActivity(new Intent());InstrumentationRegistry.getInstrumentation().waitForIdleSync();
    }
    @After public void stop()throws Exception{
        fixture("POST","/test/r56-read-release",new JSONObject());context.stopService(new Intent(context,MonitoringService.class));
        if(rule.getActivity()!=null)rule.finishActivity();
    }
    @Test public void reachableBridgeWithStaleMt5DoesNotBecomePhoneOffline()throws Exception{
        JSONObject snapshot=EventClient.state();snapshot.put("account_age",60);EventClient.cache(snapshot);sync();
        assertTrue("Successful Bridge response proves transport reachability",prefs.getBoolean("server_verified",false));
        assertFalse("Stale MT5 account must stay independently unavailable",prefs.getBoolean("mt5_connected_snapshot",true));
        assertFalse("MT5 unavailability is not phone offline",EventClient.state().optBoolean("client_offline"));
        ui(()->assertTrue(((TextView)rule.getActivity().findViewById(R.id.serverStatusText)).getText().toString().contains("SERVER: CONNECTED")));
    }
    @Test public void commandDoesNotWaitBehindMoneyRead()throws Exception{
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        queue("executor").execute(()->{entered.countDown();try{release.await();}catch(InterruptedException ignored){}});
        assertTrue(entered.await(2,TimeUnit.SECONDS));int before=audit();
        try{command("disable");await(()->audit()>before,1500,"DISABLE must reach Bridge while history work is held");}
        finally{release.countDown();}
    }
    @Test public void queuedCommandCannotMoveToChangedServer()throws Exception{
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        ExecutorService commands=queue("commandExecutor");
        commands.execute(()->{entered.countDown();try{release.await();}catch(InterruptedException ignored){}});
        assertTrue(entered.await(2,TimeUnit.SECONDS));int before=audit();
        try{
            command("disable");prefs.edit().putString("server_url","http://localhost:8765").commit();release.countDown();
            commands.submit(()->{}).get(5,TimeUnit.SECONDS);
            assertEquals("A queued command belongs to the source at the tap; never retarget it",before,audit());
        }finally{release.countDown();prefs.edit().putString("server_url","http://127.0.0.1:8765").commit();}
    }
    @Test public void pendingDisableKeepsConfirmedSwitchAndBlocksDuplicateTap()throws Exception{
        fixture("POST","/test/r55-controls",new JSONObject().put("auto",true).put("campaign",false).put("quote_future",false));EventClient.poll();sync();
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        queue("commandExecutor").execute(()->{entered.countDown();try{release.await();}catch(InterruptedException ignored){}});
        assertTrue(entered.await(2,TimeUnit.SECONDS));
        try{ui(()->{Switch control=rule.getActivity().findViewById(R.id.autoTradingSwitch);assertTrue(control.isChecked());control.performClick();
            assertTrue("Confirmed AUTO stays ON until Bridge acknowledges DISABLE",control.isChecked());
            assertFalse("A pending command cannot be sent twice",control.isEnabled());
            assertTrue(((TextView)rule.getActivity().findViewById(R.id.autoStatusText)).getText().toString().contains("Ожидается"));});}
        finally{release.countDown();}
    }
    @Test public void acceptedDisableRejectsOlderAutoSnapshot()throws Exception{
        fixture("POST","/test/r55-controls",new JSONObject().put("auto",true).put("campaign",false));EventClient.poll();
        fixture("POST","/test/r56-read-hold",new JSONObject().put("hold",true));
        ExecutorService reads=Executors.newSingleThreadExecutor();Future<JSONObject> old=reads.submit(EventClient::poll);
        try{
            await(()->{try{return fixture("GET","/test/r56-read-hold",null).optBoolean("captured");}catch(Exception e){throw new AssertionError(e);}},2500,"AUTO ON snapshot is held");
            EventClient.command("disable",new JSONObject());EventClient.poll();
            fixture("POST","/test/r56-read-release",new JSONObject());old.get(4,TimeUnit.SECONDS);
            assertFalse("Old AUTO ON response cannot replace confirmed disable",EventClient.state().optBoolean("auto",true));
        }finally{fixture("POST","/test/r56-read-release",new JSONObject());old.cancel(true);reads.shutdownNow();}
    }
    @Test public void emergencyReachesBridgeWhileServiceReadIsHeld()throws Exception{
        EventClient.configure();fixture("POST","/test/r56-read-hold",new JSONObject().put("hold",true));
        ui(()->context.startForegroundService(new Intent(context,MonitoringService.class).setAction(MonitoringService.ACTION_START)));
        await(()->{try{return fixture("GET","/test/r56-read-hold",null).optBoolean("captured");}catch(Exception e){throw new AssertionError(e);}},3000,"Service read is held");
        try{
            ui(()->context.startForegroundService(new Intent(context,MonitoringService.class).setAction(MonitoringService.ACTION_EMERGENCY_CONFIRMED)));
            await(()->{try{return fixture("GET","/ec/state",null).optBoolean("emergency");}catch(Exception e){throw new AssertionError(e);}},1500,"Emergency must bypass held poll/configure work");
        }finally{fixture("POST","/test/r56-read-release",new JSONObject());}
    }
    @Test public void offlineFinancialCardExplicitlyLabelsCachedNumbers()throws Exception{
        EventClient.offline(new java.io.IOException("test offline"));sync();
        ui(()->{
            String account=((TextView)rule.getActivity().findViewById(R.id.accountText)).getText().toString();
            String positions=((TextView)rule.getActivity().findViewById(R.id.positionsText)).getText().toString();
            assertTrue("Account snapshot needs cache label: "+account,account.contains("КЭШ"));
            assertTrue("Positions snapshot needs cache label: "+positions,positions.contains("КЭШ"));
        });
    }
}
