package com.openai.fxm1;

import android.content.*;
import android.graphics.Rect;
import android.os.*;
import android.view.*;
import android.widget.Button;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.io.*;
import java.lang.reflect.Method;
import static org.junit.Assert.*;

/** Real activity/buttons/fullscreen on an explicitly synthetic, non-trading scene. */
@RunWith(AndroidJUnit4.class)
public class R742ForecastActivityTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    private Context ctx;private UiDevice device;
    private void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    private SparklineView chart(){return rule.getActivity().findViewById(R.id.sparklineView);}
    private Button find(View root,String label){if(root instanceof Button&&label.contentEquals(((Button)root).getText()))return (Button)root;
        if(root instanceof ViewGroup)for(int i=0;i<((ViewGroup)root).getChildCount();i++){Button b=find(((ViewGroup)root).getChildAt(i),label);if(b!=null)return b;}return null;}
    private void click(String label){ui(()->{Button b=find(rule.getActivity().getWindow().getDecorView(),label);assertNotNull(label,b);b.requestRectangleOnScreen(new Rect(0,0,b.getWidth(),b.getHeight()),true);assertTrue(b.performClick());});}
    private void shot(String file)throws Exception{
        InstrumentationRegistry.getInstrumentation().waitForIdleSync();device.waitForIdle();
        java.util.concurrent.CountDownLatch frame=new java.util.concurrent.CountDownLatch(1);
        ui(()->chart().postOnAnimation(()->chart().postOnAnimation(frame::countDown)));
        assertTrue(frame.await(5,java.util.concurrent.TimeUnit.SECONDS));
        assertTrue(device.takeScreenshot(new File(ctx.getExternalFilesDir(null),file+".png")));
    }
    @Before public void setup()throws Exception{
        ctx=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.wakeUp();
        ctx.stopService(new Intent(ctx,MonitoringService.class));
        ctx.getSharedPreferences("fxm1",0).edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r742-activity").putString("target_trade_mode","DEMO").putString("selected_symbol","EUR/USD")
            .putInt("entry_tf_pos",1).putString("entry_tf_name","M5").putString("ec_lot_cap","0.01").commit();
        ctx.getSharedPreferences("fxm1_forecast_view_v1",0).edit().clear().commit();
        EventClient.init(ctx);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();rule.launchActivity(new Intent());
        ui(()->ScenarioUi.setActive(rule.getActivity(),false));ctx.stopService(new Intent(ctx,MonitoringService.class));
    }
    @After public void teardown()throws Exception{
        ctx.stopService(new Intent(ctx,MonitoringService.class));ui(()->rule.getActivity().finish());
        EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());
    }
    @Test public void actualForecastButtonSnapshotPickerAndFullscreenUseOriginalLine()throws Exception{
        JSONObject state=new JSONObject(EventClient.state().toString()),f=R742ForecastContractTest.forecast("activity-fixed",R742ForecastContractTest.T,1.106);
        JSONObject cfg=state.getJSONObject("config"),p=f.getJSONObject("price_forecast");String scope=state.getString("market_scope");
        p.put("symbol",cfg.getString("symbol")).put("scope",scope+"|"+cfg.getString("symbol")+"|"+cfg.getString("mode")+"|M5|ANALOG_R7_1");
        state.put("forecast",f).put("bars",R742ForecastContractTest.bars()).put("live_bar",JSONObject.NULL).put("chart_market",JSONObject.NULL)
            .put("quote_fresh",true).put("snapshot_age",0).put("client_offline",false).put("auto",false);
        EventClient.cache(state);
        Method sync=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");sync.setAccessible(true);
        ui(()->{try{sync.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}ScenarioUi.populate(chart(),state);chart().goLive();chart().setChartMode("PATTERNS");chart().requestRectangleOnScreen(new Rect(0,0,chart().getWidth(),chart().getHeight()),true);});
        click("ПРОГНОЗ");assertEquals("FORECAST",chart().displayedForecast().optString("chart_display_mode"));
        assertTrue(chart().getContentDescription().toString(),chart().displayedForecast().optBoolean("forecast_snapshot_selected"));
        shot("r742-activity-forecast");
        click("СНИМКИ");assertTrue(device.wait(Until.hasObject(By.text("Сохранённые расчёты · без изменения торговли")),5000));device.pressBack();
        ui(()->chart().performClick());assertTrue(device.wait(Until.hasObject(By.descContains("ЦЕНОВОЙ ПРОГНОЗ")),5000));shot("r742-activity-fullscreen");device.pressBack();
        click("СВЕЧИ");assertEquals("CANDLES",chart().displayedForecast().optString("chart_display_mode"));
        click("ПРОГНОЗ");assertEquals("activity-fixed",chart().displayedForecast().getJSONObject("price_forecast").getString("snapshot_id"));
        assertFalse(EventClient.state().optBoolean("auto"));
    }
}
