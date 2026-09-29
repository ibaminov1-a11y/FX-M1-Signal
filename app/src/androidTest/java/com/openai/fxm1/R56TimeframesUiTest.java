package com.openai.fxm1;

import android.app.*;
import android.content.*;
import android.graphics.Rect;
import android.os.*;
import android.view.*;
import android.widget.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.io.InputStream;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

/** Real view choices and HTTP reads must never become trading profile commands. */
@RunWith(AndroidJUnit4.class)
public class R56TimeframesUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context; SharedPreferences prefs; UiDevice device;
    void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    void await(BooleanSupplier c,String message)throws Exception{long end=SystemClock.elapsedRealtime()+15000;while(SystemClock.elapsedRealtime()<end){if(c.getAsBoolean())return;Thread.sleep(100);}fail(message);}
    void setupFrames(JSONObject options)throws Exception{EventClient.http("POST",EventClient.base()+"/test/r56-multiframe",options);EventClient.poll();}
    SparklineView chart(){return rule.getActivity().findViewById(R.id.sparklineView);}
    String frame(){final String[] value={""};ui(()->value[0]=chart().historyFrame());return value[0];}
    String scenario(){final String[] value={""};ui(()->{JSONArray rows=chart().scenarioChoices();value[0]=rows.length()==0?"":rows.optJSONObject(0).optString("scenario_id");});return value[0];}
    void select(String tf)throws Exception{
        ui(()->{View chooser=rule.getActivity().getWindow().getDecorView().findViewWithTag("scenario_timeframe");assertNotNull("Independent chart timeframe chooser",chooser);chooser.requestRectangleOnScreen(new Rect(0,0,chooser.getWidth(),chooser.getHeight()),true);assertTrue(chooser.performClick());});
        UiObject2 item=device.wait(Until.findObject(By.text(tf)),4000);assertNotNull("Selectable chart frame "+tf,item);item.click();
    }
    int commands()throws Exception{return EventClient.http("GET",EventClient.base()+"/test/r53-command-audit",null).getJSONArray("commands").length();}
    void shot(String name)throws Exception{InstrumentationRegistry.getInstrumentation().waitForIdleSync();Thread.sleep(250);for(String cmd:new String[]{"mkdir -p /sdcard/Download/ec1-qa","screencap -p /sdcard/Download/ec1-qa/"+name+".png"})try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] b=new byte[4096];while(in.read(b)!=-1){}}}
    void shotFrame(String timeframe)throws Exception{
        ui(()->{ScrollView root=rule.getActivity().findViewById(R.id.rootLayout);Rect bounds=new Rect();chart().getDrawingRect(bounds);
            root.offsetDescendantRectToMyCoords(chart(),bounds);
            root.scrollTo(0,Math.max(0,bounds.top-Math.round(190*context.getResources().getDisplayMetrics().density)));});
        InstrumentationRegistry.getInstrumentation().waitForIdleSync();Thread.sleep(250);
        ui(()->{Button chooser=rule.getActivity().getWindow().getDecorView().findViewWithTag("scenario_timeframe");
            assertEquals("Screenshot contains the requested chart frame",timeframe,chart().historyFrame());
            assertTrue("Screenshot chooser matches its own graph",chooser.getText().toString().contains("ГРАФИК "+timeframe+" "));});
        shot("r56-"+timeframe.toLowerCase()+"-independent");
    }
    @Before public void start()throws Exception{
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.wakeUp();device.pressHome();
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(250);
        prefs=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);prefs.edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765").putString("ec_client_id","r56-ui")
            .putString("target_trade_mode","DEMO").putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());setupFrames(new JSONObject());
        rule.launchActivity(new Intent());InstrumentationRegistry.getInstrumentation().waitForIdleSync();
    }
    @After public void stop(){context.stopService(new Intent(context,MonitoringService.class));if(rule.getActivity()!=null)ui(()->rule.getActivity().finish());}

    @Test public void chartFramesHaveIndependentForecastsWithoutChangingTradeProfile()throws Exception{
        int before=commands();java.util.Set<String> ids=new java.util.HashSet<>();
        for(String tf:new String[]{"M1","M5","M15","M30","H1","H4","D1","W1","MN1"}){
            select(tf);await(()->tf.equals(frame())&&!scenario().isEmpty(),"Own forecast for "+tf);assertTrue("Independent scenario identity "+tf,ids.add(scenario()));
            if(java.util.Arrays.asList("M1","M5","M15","M30","H1").contains(tf))shotFrame(tf);
        }
        assertEquals("M5",EventClient.state().getJSONObject("config").getString("timeframe"));assertEquals("M5",EventClient.config().getString("timeframe"));assertEquals(before,commands());
        ui(()->{TextView status=rule.getActivity().getWindow().getDecorView().findViewWithTag("scenario_timeframe_status");assertTrue(status.getText().toString(),status.getText().toString().contains("M5"));});
    }
    @Test public void enlargedChartSharesViewingFrameAndKeepsHistoryControls()throws Exception{
        select("M30");await(()->"M30".equals(frame())&&!scenario().isEmpty(),"M30 loaded");ui(()->chart().performClick());
        assertTrue(device.wait(Until.hasObject(By.text("ЗАКРЫТЬ КАРТУ")),5000));
        UiObject2 chooser=device.wait(Until.findObject(By.desc("Период графика · только просмотр")),5000);assertNotNull(chooser);chooser.click();
        device.wait(Until.findObject(By.text("H1")),5000).click();
        await(()->"H1".equals(frame())&&!scenario().isEmpty(),"Enlarged selection updates embedded chart");
        UiObject2 left=device.findObject(By.text("◀"));assertNotNull(left);left.click();assertTrue(device.wait(Until.hasObject(By.descStartsWith("Просмотр истории.")),5000));
        device.findObject(By.text("LIVE")).click();assertTrue(device.wait(Until.hasObject(By.descContains("Текущие гипотезы LIVE")),5000));
        shot("r56-h1-enlarged");device.findObject(By.text("ЗАКРЫТЬ КАРТУ")).click();assertEquals("M5",EventClient.config().getString("timeframe"));
    }
    @Test public void delayedOldFrameCannotReplaceNewerSelection()throws Exception{
        setupFrames(new JSONObject().put("delayed_tf","M15").put("delay_ms",1800));select("M15");Thread.sleep(150);select("H1");
        await(()->"H1".equals(frame())&&!scenario().isEmpty(),"Latest H1 selection loaded");String id=scenario();Thread.sleep(2300);assertEquals("H1",frame());assertEquals(id,scenario());
    }
    @Test public void wrongFrameScopeClockOrAccountNeverReachesChart()throws Exception{
        for(String guard:new String[]{"wrong_frame","wrong_scope","wrong_clock","wrong_account"}){
            select("M5");setupFrames(new JSONObject().put(guard,true));select("M30");
            await(()->{final boolean[] rejected={false};ui(()->{TextView status=rule.getActivity().getWindow().getDecorView().findViewWithTag("scenario_timeframe_status");rejected[0]=status!=null&&status.getText().toString().contains("не соответствуют");});return rejected[0];},"Reject mismatched "+guard);
            assertEquals("M30",frame());assertEquals("",scenario());
        }
    }
    @Test public void observerLivePriceUpdatesWhilePhoneMonitoringIsStopped()throws Exception{
        select("M1");await(()->"M1".equals(frame())&&!scenario().isEmpty(),"M1 loaded");final double[] price={0};ui(()->price[0]=chart().displayedForecast().optDouble("live_price"));
        EventClient.http("POST",EventClient.base()+"/test/r56-multiframe",new JSONObject().put("bump",true));await(()->{final boolean[] changed={false};ui(()->changed[0]=Math.abs(chart().displayedForecast().optDouble("live_price")-price[0]-.0002)<.00000001);return changed[0];},"Observer live quote refreshed without service");assertFalse(prefs.getBoolean("bg_running",false));
    }
    @Test public void tradeFrameAndOverviewRecoverWithoutMonitoringOrSendingPendingCommands()throws Exception{
        select("M5");await(()->"M5".equals(frame())&&!scenario().isEmpty(),"Initial active M5 loaded");
        final double[] price={0};ui(()->price[0]=chart().displayedForecast().optDouble("live_price"));
        double priorAnalysis=EventClient.state().getJSONArray("timeframes").getJSONObject(0).getDouble("analysis_time");int before=commands();
        // A prior phone read failed. Financial refresh is gated off; the active
        // chart must recover through its own read-only state refresh.
        prefs.edit().putBoolean("server_verified",false).putBoolean("ec_mode_pause_pending",true).commit();
        EventClient.http("POST",EventClient.base()+"/test/r56-multiframe",new JSONObject().put("bump",true));
        await(()->{final boolean[] changed={false};ui(()->changed[0]=Math.abs(chart().displayedForecast().optDouble("live_price")-price[0]-.0002)<.00000001);return changed[0];},"Active M5 refreshes without MonitoringService or test polling");
        assertTrue("Independent overview refreshed with trade view",EventClient.state().getJSONArray("timeframes").getJSONObject(0).getDouble("analysis_time")>priorAnalysis);
        assertFalse(prefs.getBoolean("bg_running",false));assertTrue("Read-only UI cannot consume pending PAUSE",prefs.getBoolean("ec_mode_pause_pending",false));assertEquals(before,commands());
        ui(()->{TextView status=rule.getActivity().getWindow().getDecorView().findViewWithTag("scenario_timeframe_status");assertTrue(status.getText().toString(),status.getText().toString().contains("LIVE"));});
    }
    @Test public void oldTradeSnapshotNeverClaimsLiveWhileStateRefreshIsUnavailable()throws Exception{
        select("M5");JSONObject old=new JSONObject(EventClient.state().toString());
        old.getJSONObject("forecast").put("data_asof",old.getDouble("server_time")-30).put("stale",false);
        old.put("analysis_time",old.getDouble("server_time")-30);
        prefs.edit().putString("server_url","http://127.0.0.1:8766").commit();EventClient.cache(old);
        try{await(()->{final boolean[] stale={false};ui(()->{TextView status=rule.getActivity().getWindow().getDecorView().findViewWithTag("scenario_timeframe_status");
                stale[0]=chart().displayedForecast().optBoolean("stale")&&status!=null&&!status.getText().toString().contains("LIVE");});return stale[0];},"Old selected-trade snapshot must be stale before a new response arrives");}
        finally{prefs.edit().putString("server_url","http://127.0.0.1:8765").commit();}
    }
    @Test public void unavailableFrameHasReasonAndCannotShowAnotherFramesCandles()throws Exception{
        setupFrames(new JSONObject().put("unavailable_tf","M30"));select("M30");
        await(()->{final boolean[] unavailable={false};ui(()->{TextView status=rule.getActivity().getWindow().getDecorView().findViewWithTag("scenario_timeframe_status");unavailable[0]=status!=null&&status.getText().toString().contains("недоступ");});return unavailable[0];},"Visible unavailable reason");
        assertEquals("M30",frame());assertEquals("",scenario());assertEquals("M5",EventClient.config().getString("timeframe"));
    }
    @Test public void oldNumericEntryPreferencesPreserveTheirNamedFrames()throws Exception{
        String[] old={"M1","M5","M10","M15","H1","H4","D1","W1","MN1"};
        for(int index=0;index<old.length;index++){
            prefs.edit().remove("entry_tf_name").remove("v925_tf_migrated").putBoolean("v800_tf_migrated",true).putInt("entry_tf_pos",index).commit();EventClient.init(context);assertEquals("Saved old index "+index,old[index],EventClient.config().getString("timeframe"));
        }
        ui(()->{Spinner spinner=rule.getActivity().findViewById(R.id.entryTimeframeSpinner);boolean m30=false;for(int i=0;i<spinner.getCount();i++){String tf=spinner.getItemAtPosition(i).toString();assertNotEquals("M10",tf);m30|="M30".equals(tf);}assertTrue("M30 offered as an explicit new trade choice",m30);});
    }

    @Test public void v3AccessibilityUsesScenarioEventInsteadOfGenericEntryTriggers()throws Exception{
        JSONObject forecast=new JSONObject().put("map_version",3).put("available",true).put("live_price",1.101)
            .put("entry_levels",new JSONObject().put("BUY",new JSONObject().put("trigger",8.88888).put("invalidation",7.77777)))
            .put("scenarios",new JSONArray().put(new JSONObject().put("side",-1).put("stage","RETURN_SEEN").put("event_level",1.10042)
                .put("next_event","Возврат в диапазон")));
        ui(()->{SparklineView graph=new SparklineView(context);graph.setMarket(new JSONArray(),null,null,null,"SCENARIO_V2",null,null,forecast);
            String description=graph.getContentDescription().toString();assertFalse(description,description.contains("8.88888"));
            assertTrue(description,description.contains("1.10042")&&description.contains("Возврат в диапазон"));});
    }
    @Test public void changingSourceClearsObserverCacheBeforeDelayedReply()throws Exception{
        select("M1");await(()->"M1".equals(frame())&&!scenario().isEmpty(),"First source M1 ready");
        setupFrames(new JSONObject().put("delayed_tf","M15").put("delay_ms",1800));select("M15");Thread.sleep(150);
        prefs.edit().putString("server_url","http://127.0.0.1:8766").commit();
        try{Thread.sleep(2400);assertEquals("M15",frame());assertEquals("Old source response cannot paint a new connection","",scenario());
            select("M1");Thread.sleep(250);assertEquals("Old source cache cannot paint a new connection","",scenario());}
        finally{prefs.edit().putString("server_url","http://127.0.0.1:8765").commit();}
    }
    @Test public void contentRemainsBelowSystemStatusBarAfterInsets()throws Exception{
        ui(()->{View root=rule.getActivity().findViewById(R.id.rootLayout);View header=rule.getActivity().findViewById(R.id.versionBadgeText);root.scrollTo(0,0);
            WindowInsets insets=root.getRootWindowInsets();assertNotNull(insets);int top=insets.getInsets(WindowInsets.Type.statusBars()).top;int[] location=new int[2];header.getLocationOnScreen(location);assertTrue("Header must remain below status bar",location[1]>=top);});
    }
}
