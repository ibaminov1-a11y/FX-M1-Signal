package com.openai.fxm1;
import android.content.*;
import android.os.*;
import android.widget.TextView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.io.*;
import java.lang.reflect.*;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class V108RepairTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context;SharedPreferences p;UiDevice device;
    void shell(String cmd)throws Exception {
        try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);
            InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] b=new byte[4096];while(in.read(b)!=-1){}}
    }
    void onMain(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    void await(BooleanSupplier test,String reason)throws Exception {long end=SystemClock.elapsedRealtime()+25000;while(SystemClock.elapsedRealtime()<end){if(test.getAsBoolean())return;Thread.sleep(150);}fail(reason);}
    void capture(String name)throws Exception {shell("mkdir -p /sdcard/Download/v108-qa");shell("screencap -p /sdcard/Download/v108-qa/"+name+".png");}
    void click(String label)throws Exception {
        for(int n=0;n<3;n++)try{UiObject2 v=device.wait(Until.findObject(By.text(label)),10000);assertNotNull(label,v);v.click();return;}catch(StaleObjectException e){if(n==2)throw e;Thread.sleep(100);}
    }
    @Before public void prepare()throws Exception {
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.wakeUp();device.pressHome();
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(700);
        shell("pm grant "+context.getPackageName()+" android.permission.POST_NOTIFICATIONS");
        p=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);p.edit().clear().commit();FeatureEngine.ensureDefaults(p);
        p.edit().putString("apikey","QA-invalid-never-orders").putString("server_url","http://10.0.2.2:8000")
            .putBoolean("v800_tf_migrated",true).putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1)
            .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).commit();
        rule.launchActivity(new Intent());
    }
    @After public void finish(){context.stopService(new Intent(context,MonitoringService.class));}
    @Test public void qualityExplainsExactExistingFormula()throws Exception {
        final Throwable[] error={null};onMain(()->{try{
            MonitoringService service=new MonitoringService();Method calc=MonitoringService.class.getDeclaredMethod("setupQualityAdaptive",String.class,int.class,int.class,int.class,int.class,int.class,int.class);calc.setAccessible(true);
            for(String candidate:new String[]{"WAIT","BUY","SELL"})for(int h2=-1;h2<=1;h2++)for(int h1=-1;h1<=1;h1++)for(int e=-1;e<=1;e++)for(int f=-1;f<=1;f++)for(int st=-1;st<=1;st++)for(int br=-2;br<=2;br++)for(int pat=-2;pat<=2;pat++){
                int q=(Integer)calc.invoke(service,candidate,h2,h1,e,f,st,br);if(!"WAIT".equals(candidate))q=Math.min(100,q+Math.max(0,pat*("BUY".equals(candidate)?1:-1))*5);
                String text=V10Repair.qualityDetails(candidate,h2,h1,e,f,st,br,pat);assertTrue(text,text.contains("→ "+q+"/100"));
            }
        }catch(Throwable e){error[0]=e;}});if(error[0]!=null)throw new AssertionError(error[0]);
    }
    @Test public void signalIsNotExecutionAndBothBlocksVisible()throws Exception {
        p.edit().putBoolean("session_filter_enabled",true).putString("allowed_sessions","NONE").commit();
        V10Repair.record(p,"BLOCKED","Сессия ASIA запрещена","EUR/USD","M5");
        V10Repair.saveRisk(p,new JSONObject().put("allowed",false).put("blocks",new JSONArray().put("LOSS_STREAK")).put("consecutive_losses",3).put("streak_limit",3));
        String text=V10Repair.display(p,"EUR/USD","M5","SELL — сценарий анализа подтверждён");
        assertTrue(text.contains("Запрос не отправлен"));assertTrue(text.contains("Серия убытков 3/3"));assertTrue(text.contains("Сессия ASIA"));assertFalse(text.contains("SELL открыт"));
        assertFalse(V10Repair.sessionAllowed("LONDON,NEW_YORK","ASIA"));assertFalse(V10Repair.sessionAllowed("NOT_ASIA","ASIA"));assertTrue(V10Repair.sessionAllowed("LONDON,NEW_YORK","LONDON+NEW_YORK"));
    }
    @Test public void confirmedOnlyAfterActualFillRetcode()throws Exception {
        V10Repair.response(p,new JSONObject().put("accepted",true).put("queued",true),"EUR/USD","M5");assertNotEquals("CONFIRMED",p.getString("execution_stage",""));
        V10Repair.response(p,new JSONObject().put("accepted",true).put("retcode",10009).put("ticket",77).put("deal",88),"EUR/USD","M5");assertEquals("CONFIRMED",p.getString("execution_stage",""));
        V10Repair.failure(p,new Exception("HTTP 409: {\"accepted\":false,\"message\":\"RISK BLOCK: LOSS_STREAK\"}"),"EUR/USD","M5");assertEquals("REJECTED",p.getString("execution_stage",""));
        V10Repair.failure(p,new java.net.SocketTimeoutException("timeout"),"EUR/USD","M5");assertEquals("UNKNOWN",p.getString("execution_stage",""));
    }
    @Test public void legacyUiBalanceAndDiagnosticsRemain()throws Exception {
        Method unavailablePrice=MainActivity.class.getDeclaredMethod("fmt",double.class);unavailablePrice.setAccessible(true);assertEquals("—",unavailablePrice.invoke(rule.getActivity(),Double.NaN));

        p.edit().putBoolean("server_verified",true).putBoolean("mt5_connected_snapshot",true).putString("mt5_account_type_snapshot","DEMO")
            .putLong("mt5_balance_bits",Double.doubleToLongBits(99868.35)).putLong("mt5_equity_bits",Double.doubleToLongBits(99868.35))
            .putString("bridge_version_snapshot","10.0").putString("state_symbol","EUR/USD").putString("state_tf","M5")
            .putString("state_signal","SELL").putInt("state_quality",100).putString("state_why","SELL — сценарий анализа подтверждён")
            .putLong("state_entry_bits",Double.doubleToLongBits(1.16049)).putLong("state_sl_bits",Double.doubleToLongBits(1.16099)).commit();
        V10Repair.record(p,"BLOCKED","Сессия ASIA запрещена","EUR/USD","M5");V10Repair.fetchRisk(p,"http://10.0.2.2:8000");
        await(()->((TextView)rule.getActivity().findViewById(R.id.accountText)).getText().toString().contains("99868.35"),"Actual MT5 balance remains visible");
        onMain(()->{assertNotNull(rule.getActivity().findViewById(R.id.moneyHistoryButton));assertNotNull(rule.getActivity().findViewById(R.id.maxPositionsSpinner));});capture("01-legacy-ui");
        UiScrollable scroll=new UiScrollable(new UiSelector().scrollable(true));scroll.scrollIntoView(new UiSelector().resourceId(context.getPackageName()+":id/whyWaitText"));device.swipe(device.getDisplayWidth()/2,device.getDisplayHeight()*4/5,device.getDisplayWidth()/2,device.getDisplayHeight()/3,35);capture("02-execution-status");
    }
    @Test public void notificationActionsAndEmergencyLatch()throws Exception {
        onMain(()->context.startForegroundService(new Intent(context,MonitoringService.class).setAction(MonitoringService.ACTION_START)));
        await(()->p.getBoolean("bg_running",false),"Monitoring service running");device.openNotification();
        UiObject2 pause=device.wait(Until.findObject(By.text("PAUSE")),10000);
        if(pause==null){UiObject2 expand=device.findObject(By.res("android","expand_button"));if(expand!=null)expand.click();}
        assertNotNull(device.wait(Until.findObject(By.text("PAUSE")),10000));capture("03-notification");
        click("PAUSE");await(()->p.getBoolean("trading_paused",false),"PAUSE handled");
        click("PLAY");await(()->!p.getBoolean("trading_paused",true),"PLAY resumes ordinary pause");assertFalse(p.getBoolean("auto_trading",false));
        click("EMERGENCY STOP");Thread.sleep(200);click("EMERGENCY STOP");await(()->p.getBoolean("emergency_latched_v108",false),"Emergency latch");
        assertFalse(p.getBoolean("auto_user_enabled",true));assertFalse(p.getBoolean("auto_trading",true));
        device.pressBack();await(()->!p.getBoolean("bg_running",true),"Emergency finished");context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(700);
        onMain(()->rule.getActivity().startForegroundService(new Intent(context,MonitoringService.class).setAction(MonitoringService.ACTION_START)));
        await(()->p.getBoolean("bg_running",false),"Restarted monitor");device.openNotification();click("PLAY");Thread.sleep(500);
        assertTrue(p.getBoolean("emergency_latched_v108",false));assertFalse(p.getBoolean("auto_trading",true));capture("04-emergency-stays");
    }
}
