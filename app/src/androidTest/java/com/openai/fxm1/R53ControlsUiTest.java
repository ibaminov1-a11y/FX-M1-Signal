package com.openai.fxm1;

import android.app.NotificationManager;
import android.content.*;
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
import java.io.*;
import java.lang.reflect.Method;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

/** Real Android controls -> authenticated HTTP -> production Engine + fake MT5. */
@RunWith(AndroidJUnit4.class)
public class R53ControlsUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context; SharedPreferences prefs; UiDevice device;
    final int[] liveFields={R.id.statusText,R.id.marketStatusText,R.id.marketSessionText,R.id.confidenceText,
        R.id.signalAgeText,R.id.levelsText,R.id.contextText,R.id.whyWaitText,R.id.componentScoresText,
        R.id.autoStatusText,R.id.accountText,R.id.positionsText,R.id.priceCompareText,R.id.smartStatusText,
        R.id.statsText,R.id.signalHistoryText,R.id.tradeHistoryText,R.id.serverStatusText,R.id.journalText};
    void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    void shell(String command)throws Exception {
        try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);
            InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] bytes=new byte[4096];while(in.read(bytes)!=-1){}}
    }
    void await(BooleanSupplier condition,String label)throws Exception {
        long end=SystemClock.elapsedRealtime()+15000;
        while(SystemClock.elapsedRealtime()<end){if(condition.getAsBoolean())return;Thread.sleep(100);}
        fail(label);
    }
    String text(int id){final String[] result={""};ui(()->result[0]=((TextView)rule.getActivity().findViewById(id)).getText().toString());return result[0];}
    void press(int id){ui(()->assertTrue(rule.getActivity().findViewById(id).performClick()));}
    void click(String label){UiObject2 view=device.wait(Until.findObject(By.text(label)),7000);assertNotNull(label,view);view.click();}
    void sync()throws Exception {
        Method method=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");method.setAccessible(true);
        ui(()->{try{method.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}});
    }
    JSONObject state()throws Exception{return EventClient.http("GET",EventClient.base()+"/ec/state",null);}
    void fixture(JSONObject data)throws Exception{EventClient.http("POST",EventClient.base()+"/test/r53-state",data);EventClient.poll();sync();}
    void scene(String family)throws Exception{EventClient.http("POST",EventClient.base()+"/test/r5-market",new JSONObject().put("family",family));EventClient.poll();sync();}
    @Before public void setup()throws Exception {
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.wakeUp();device.pressHome();
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(400);
        if(Build.VERSION.SDK_INT>=33)shell("pm grant "+context.getPackageName()+" android.permission.POST_NOTIFICATIONS");
        prefs=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);
        prefs.edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r53-controls-client").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();
        rule.launchActivity(new Intent());InstrumentationRegistry.getInstrumentation().waitForIdleSync();
    }
    @After public void stop()throws Exception{context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(400);}

    @Test public void scalpSelectionReachesBridgeAndSurvivesActivityRecreation()throws Exception {
        press(R.id.signalModeSpinner);click("SCALP");
        await(()->prefs.getInt("signal_mode_pos",0)==1,"SCALP choice persisted");
        press(R.id.analyzeButton);
        await(()->"SCALP".equals(EventClient.state().optJSONObject("config").optString("mode")),"Selected SCALP must reach actual Bridge config");
        assertEquals("SCALP",state().getJSONObject("config").getString("mode"));
        assertEquals("M5",state().getJSONObject("config").getString("timeframe"));
        await(()->{for(android.service.notification.StatusBarNotification notification:context.getSystemService(NotificationManager.class).getActiveNotifications())
            if(String.valueOf(notification.getNotification().extras.getCharSequence("android.text")).contains("SCALP"))return true;return false;},"Information-only notification must identify active SCALP mode");
        ui(()->rule.getActivity().recreate());Thread.sleep(500);
        ui(()->{Spinner mode=rule.getActivity().findViewById(R.id.signalModeSpinner);assertEquals("SCALP",mode.getSelectedItem().toString());
            Spinner tf=rule.getActivity().findViewById(R.id.entryTimeframeSpinner);assertEquals("M5",tf.getSelectedItem().toString());
            assertFalse("Scenario V2 only supports M5; unsupported frames must not be selectable",tf.isEnabled());});
        press(R.id.signalModeSpinner);click("NORMAL");
        await(()->"NORMAL".equals(EventClient.state().optJSONObject("config").optString("mode")),"Switching back must reconfigure Bridge");
    }

    @Test public void lockedBridgeProfileSynchronizesSavedModeWithoutCreatingADeferredChange()throws Exception {
        JSONObject cfg=EventClient.config().put("mode","SCALP");
        EventClient.command("configure",new JSONObject().put("config",cfg));
        EventClient.command("approve_profile",new JSONObject().put("confirmation","APPROVE_DEMO_RISK"));
        // Deliberately bypass the phone's desired profile: emulate AUTO enabled by another client.
        EventClient.http("POST",EventClient.base()+"/ec/command/enable",EventClient.envelope(new JSONObject().put("confirmation","ENABLE_DEMO").put("allow_wait",true)));
        prefs.edit().putInt("signal_mode_pos",0).commit();
        EventClient.configure(); // Service startup configures before its first periodic poll.
        EventClient.poll();sync();
        assertTrue("Starting phone monitoring must preserve active Bridge AUTO",state().getBoolean("auto"));
        assertFalse(state().getBoolean("paused"));
        assertEquals("Active remote mode must become the saved phone mode",1,prefs.getInt("signal_mode_pos",-1));
        ui(()->{Spinner mode=rule.getActivity().findViewById(R.id.signalModeSpinner);assertFalse(mode.isEnabled());assertEquals("SCALP",mode.getSelectedItem().toString());});
        EventClient.command("disable",new JSONObject());EventClient.poll();sync();
        assertFalse("Unlocking must not queue the phone's stale NORMAL profile",EventClient.needsConfigure(EventClient.state()));
        assertTrue(state().isNull("pending_config"));
    }

    @Test public void autoConfirmationPauseAndMonitoringStopHaveDistinctEffects()throws Exception {
        press(R.id.autoTradingSwitch);click("Отмена");assertFalse(state().getBoolean("auto"));
        press(R.id.autoTradingSwitch);click("Подтвердить DEMO");
        await(()->EventClient.state().optBoolean("auto",false),"DEMO AUTO enabled");
        await(()->text(R.id.autoStatusText).contains("AUTO включён"),"AUTO indicator confirms Bridge");
        press(R.id.analyzeButton);await(()->!prefs.getBoolean("bg_running",true),"phone monitoring stopped");
        assertTrue("Stopping phone monitoring must preserve independent Bridge AUTO",state().getBoolean("auto"));
        press(R.id.autoTradingSwitch);
        await(()->!EventClient.state().optBoolean("auto",true)&&EventClient.state().optBoolean("paused",false),"AUTO switch explicitly pauses new entries");
    }

    @Test public void emergencyNeedsDoubleTapAndSuccessfulSettingsResetClearsBothLatches()throws Exception {
        press(R.id.emergencyStopButton);assertFalse("First tap is confirmation only",state().getBoolean("emergency"));
        ui(()->{assertTrue(rule.getActivity().findViewById(R.id.emergencyStopButton).performClick());
            assertTrue("Emergency retry must be durable before Android starts the service",prefs.getBoolean("ec_emergency_pending",false));});
        await(()->EventClient.state().optBoolean("emergency",false),"Emergency acknowledged by Bridge");
        assertTrue(prefs.getBoolean("v108_emergency_latched",false));
        press(R.id.smartFeaturesButton);click("СНЯТЬ БЛОКИРОВКУ ПОСЛЕ СВЕРКИ");
        await(()->!prefs.getBoolean("v108_emergency_latched",true)&&!EventClient.state().optBoolean("emergency",true),"Successful explicit reset must clear Bridge and phone emergency latches");
        assertFalse(prefs.getBoolean("ec_emergency_pending",true));click("ОТМЕНА");
        await(()->!text(R.id.autoStatusText).contains("EMERGENCY"),"Reset releases visible emergency block");
    }

    @Test public void failedResetPreservesEmergencyLatch()throws Exception {
        prefs.edit().putBoolean("v108_emergency_latched",true).putString("ec_token","invalid-token").commit();
        try{EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));fail("Invalid credentials must be rejected");}
        catch(IOException expected){assertTrue(prefs.getBoolean("v108_emergency_latched",false));}
    }

    @Test public void selectedRealModeStaysBlockedEvenWhileMt5IsStillDemo()throws Exception {
        press(R.id.smartFeaturesButton);click("РЕАЛЬНЫЙ СЧЁТ");click("СОХРАНИТЬ");
        assertTrue(device.wait(Until.hasObject(By.text("Режим сохранён")),5000));click("OK");
        assertEquals("REAL",prefs.getString("target_trade_mode",""));
        await(()->!prefs.getBoolean("ec_mode_pause_pending",true),"Changing account profile explicitly pauses Bridge");
        press(R.id.autoTradingSwitch);
        assertTrue("The selected REAL profile must be blocked before any DEMO enable prompt",device.wait(Until.hasObject(By.text("Выбран REAL")),5000));
        click("OK");
        JSONArray commands=EventClient.http("GET",EventClient.base()+"/test/r53-command-audit",null).getJSONArray("commands");
        boolean paused=false;
        for(int i=0;i<commands.length();i++){String cmd=commands.getJSONObject(i).getString("command");
            paused|="pause".equals(cmd);assertFalse("No real or demo order authorization from blocked REAL control",cmd.equals("enable")||cmd.equals("arm_real"));}
        assertTrue(paused);assertFalse(state().getBoolean("auto"));
    }

    @Test public void symbolRiskAndLotControlsReachTheActualConfiguration()throws Exception {
        press(R.id.analyzeButton);await(()->prefs.getBoolean("bg_running",false),"monitoring started");
        press(R.id.symbolSpinner);click("GBP/USD");
        await(()->"GBP/USD".equals(EventClient.state().optJSONObject("config").optString("symbol")),"symbol applied by Bridge");
        press(R.id.riskSpinner);click("0.50%");
        await(()->EventClient.state().optJSONObject("config").optDouble("risk_pct")==.5,"campaign risk applied by Bridge");
        press(R.id.maxPositionsSpinner);click("0.05");
        await(()->EventClient.state().optJSONObject("config").optDouble("lot_cap")==.05,"selected fixed lot applied by Bridge");
        assertEquals(.05,state().getJSONObject("config").getDouble("probe_lot_cap"),1e-9);
        ui(()->assertFalse("Legacy drift control is explicitly unavailable",rule.getActivity().findViewById(R.id.maxDriftSpinner).isEnabled()));
    }

    @Test public void offlineRefreshDisablesControlsAndRecoveryRefreshRestoresThem()throws Exception {
        EventClient.offline(new IOException("r53 simulated phone disconnect"));sync();
        assertTrue(text(R.id.serverStatusText),text(R.id.serverStatusText).contains("OFFLINE"));
        assertTrue(text(R.id.autoStatusText).contains("Связь потеряна"));
        ui(()->assertFalse(((Switch)rule.getActivity().findViewById(R.id.autoTradingSwitch)).isEnabled()));
        EventClient.poll();sync();
        assertTrue(text(R.id.serverStatusText).contains("MT5: CONNECTED"));
        ui(()->assertTrue(((Switch)rule.getActivity().findViewById(R.id.autoTradingSwitch)).isEnabled()));
    }

    @Test public void missingQuoteReplacesPreviouslyDisplayedPriceWithUnavailableMarker()throws Exception {
        EventClient.poll();sync();
        JSONObject unavailable=new JSONObject(EventClient.state().toString()).put("quote",new JSONObject());
        EventClient.cache(unavailable);sync();
        assertTrue(text(R.id.priceCompareText),text(R.id.priceCompareText).contains("MT5 Bid/Ask: — / —"));
        assertFalse(text(R.id.priceCompareText).contains("NaN"));
    }

    @Test public void destroyedMonitoringServiceClearsItsRunningIndicator()throws Exception {
        press(R.id.analyzeButton);await(()->prefs.getBoolean("bg_running",false),"service started");
        context.stopService(new Intent(context,MonitoringService.class));
        await(()->!prefs.getBoolean("bg_running",true),"Destroyed service must not leave monitoring marked as running");
        await(()->text(R.id.analyzeButton).contains("ЗАПУСТИТЬ"),"start button must reflect stopped service");
    }

    @Test public void allNineteenLiveFieldsRenderRealChangingBridgeData()throws Exception {
        scene("TRIANGLE");
        fixture(new JSONObject().put("balance",12345.67).put("bid",1.10456).put("completed_trade",true).put("manual_position",true));
        await(()->text(R.id.statsText).contains("1")&&text(R.id.tradeHistoryText).contains("EURUSD"),"Actual ledger reaches statistics and trade history");
        assertTrue(text(R.id.accountText).contains("12345.67"));
        assertTrue(text(R.id.priceCompareText).contains("1.10456"));
        assertTrue(text(R.id.positionsText).contains("Открытые позиции: 1"));
        assertTrue(text(R.id.statusText).contains("EUR/USD · M5"));
        assertEquals(ScenarioUi.headline(EventClient.state().optJSONObject("forecast")),text(R.id.confidenceText));
        assertTrue(text(R.id.levelsText).length()>10);
        assertEquals(prefs.getString("state_context",""),text(R.id.contextText));
        assertTrue(text(R.id.whyWaitText).contains(prefs.getString("state_why","")));
        assertTrue(text(R.id.componentScoresText).contains(prefs.getString("state_components","")));
        assertTrue(text(R.id.smartStatusText).contains("Источник: MT5"));
        assertTrue(text(R.id.autoStatusText).contains("AUTO выключен"));
        assertTrue(text(R.id.signalHistoryText).contains("EUR/USD"));
        assertTrue(text(R.id.serverStatusText).contains("MT5: CONNECTED"));
        assertTrue(prefs.getLong("state_last_attempt_ms",0)>0);
        assertTrue(text(R.id.signalAgeText).contains("последний анализ"));
        for(int id:liveFields)assertFalse(context.getResources().getResourceEntryName(id)+" must not be empty",text(id).trim().isEmpty());
        String previous=context.getResources().getResourceEntryName(R.id.marketStatusText);
        ui(()->{((TextView)rule.getActivity().findViewById(R.id.marketStatusText)).setText("STALE SESSION");
            ((TextView)rule.getActivity().findViewById(R.id.marketSessionText)).setText("STALE SESSION");});
        fixture(new JSONObject().put("balance",22345.67).put("bid",1.10678));
        assertTrue(text(R.id.accountText).contains("22345.67"));assertTrue(text(R.id.priceCompareText).contains("1.10678"));
        assertFalse(previous,text(R.id.marketStatusText).contains("STALE SESSION"));
        assertFalse(text(R.id.marketSessionText).contains("STALE SESSION"));
    }

    @Test public void navigationDetailsAndSettingsButtonsOpenTheirDestinations()throws Exception {
        for(int id:new int[]{R.id.navPositions,R.id.navSignals,R.id.navSettings}){
            press(id);await(()->{final boolean[] scrolled={false};ui(()->scrolled[0]=((ScrollView)rule.getActivity().findViewById(R.id.rootLayout)).getScrollY()>0);return scrolled[0];},"Navigation scrolls");
        }
        press(R.id.navOverview);await(()->{final int[] y={1};ui(()->y[0]=((ScrollView)rule.getActivity().findViewById(R.id.rootLayout)).getScrollY());return y[0]==0;},"Overview returns to top");
        press(R.id.liveDetailsButton);assertTrue(device.wait(Until.hasObject(By.text("ПОЛНЫЕ ДАННЫЕ СИГНАЛА")),5000));device.pressBack();
        press(R.id.navJournal);assertTrue(device.wait(Until.hasObject(By.text("Торговый журнал · подробно")),5000));click("ЗАКРЫТЬ");
        press(R.id.moneyHistoryButton);assertTrue(device.wait(Until.hasObject(By.text("Деньги / история MT5")),5000));click("ЗАКРЫТЬ");
        press(R.id.smartFeaturesButton);assertTrue(device.wait(Until.hasObject(By.text("Умные функции")),5000));click("ОТМЕНА");
        press(R.id.serverCheckButton);assertTrue(device.wait(Until.hasObject(By.text("Адрес MT5 Bridge")),5000));click("ОТМЕНА");
        press(R.id.saveKeyButton);ui(()->{EditText key=rule.getActivity().findViewById(R.id.apiKeyInput);assertEquals(View.VISIBLE,key.getVisibility());});
        press(R.id.saveKeyButton);assertEquals("ci-fixture-token-not-for-real-trading",prefs.getString("ec_token",""));
        fixture(new JSONObject().put("manual_position",true));press(R.id.managePositionsButton);
        assertTrue(device.wait(Until.hasObject(By.text("Позиции MT5")),5000));click("ЗАКРЫТЬ");
        press(R.id.closeAllButton);assertTrue(device.wait(Until.hasObject(By.text("Закрыть всю кампанию бота?")),5000));click("Отмена");
        assertEquals("Cancelling close must preserve manual positions",1,state().getJSONArray("all_positions").length());
    }
}
