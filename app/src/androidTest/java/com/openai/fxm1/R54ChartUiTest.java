package com.openai.fxm1;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Rect;
import android.os.ParcelFileDescriptor;
import android.view.View;
import android.widget.ScrollView;
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

/** Raw terminal rows remain visible without becoming verified market or prediction data. */
@RunWith(AndroidJUnit4.class)
public class R54ChartUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    private final Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
    private final float density=context.getResources().getDisplayMetrics().density;
    private static final long VERIFIED_START=1800000000L,RAW_START=1800010800L;
    private static final String REASON="Время котировки MT5 в будущем: FUTURE 10797s";
    private static final int GREEN=0xff42d67a,RED=0xffff4857;
    private void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    private JSONArray bars(long start)throws Exception{
        JSONArray rows=new JSONArray();
        for(int i=0;i<50;i++)rows.put(new JSONObject().put("time",start+i*300)
            .put("open",1.1000).put("close",1.1005).put("low",1.0990).put("high",1.1010));
        return rows;
    }
    private JSONObject forecast()throws Exception{
        JSONObject scenario=new JSONObject().put("scenario_id","verified-sell").put("side",-1).put("name","PRIMARY")
            .put("stage","CONFIRMED").put("title","Проверенный сценарий")
            .put("path",new JSONArray().put(new JSONObject().put("price",1.1000).put("phase","LIVE"))
                .put(new JSONObject().put("price",1.0992).put("phase","TRADE").put("label","T1")));
        return new JSONObject().put("map_version",3).put("side",-1).put("live_price",1.1000)
            .put("scenarios",new JSONArray().put(scenario))
            .put("entry_levels",new JSONObject().put("SELL",new JSONObject().put("trigger",1.0995)))
            .put("active_scenario",new JSONObject().put("side",-1).put("invalidation",1.1010));
    }
    private JSONObject verified()throws Exception{
        return new JSONObject().put("market_scope","EURUSD|M5").put("market_history_generation","UTC_NATIVE_R51")
            .put("config",new JSONObject().put("symbol","EURUSD").put("timeframe","M5"))
            .put("bars",bars(VERIFIED_START)).put("forecast",forecast());
    }
    private JSONObject blocked()throws Exception{
        // A cached verified map deliberately coexists: it must never overlay the raw terminal clock.
        return verified().put("chart_market",new JSONObject().put("bars",bars(RAW_START))
            .put("live_bar",new JSONObject().put("time",RAW_START+15000).put("open",1.1000)
                .put("close",1.1005).put("low",1.0990).put("high",1.1010))
            .put("symbol","EURUSD").put("timeframe","M5").put("scope","EURUSD|M5")
            .put("read_only",true).put("status","UNVERIFIED_TIME").put("reason",REASON)
            .put("received_at",1800000000L).put("clock","MT5_RAW"));
    }
    private void populate(SparklineView chart,JSONObject state){
        try{Method method=ScenarioUi.class.getDeclaredMethod("populate",SparklineView.class,JSONObject.class);
            method.setAccessible(true);method.invoke(null,chart,state);
        }catch(Exception e){throw new AssertionError(e);}
    }
    private Bitmap render(SparklineView chart){
        int width=Math.round(360*density),height=Math.round(420*density);chart.layout(0,0,width,height);
        Bitmap result=Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888);
        Canvas canvas=new Canvas(result);canvas.drawColor(0xff141125);chart.draw(canvas);return result;
    }
    private int pixels(Bitmap image,int color,int left,int right){
        int found=0;
        for(int y=Math.round(95*density);y<Math.round(345*density);y++)
            for(int x=Math.round(left*density);x<Math.round(right*density);x++)
                if(image.getPixel(x,y)==color)found++;
        return found;
    }
    private void shell(String command)throws Exception{
        try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);
            InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] data=new byte[4096];while(in.read(data)!=-1){}}
    }
    private void save(Bitmap bitmap,String name)throws Exception{
        File file=new File(context.getExternalFilesDir(null),name+".png");
        try(FileOutputStream out=new FileOutputStream(file)){assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG,100,out));}
        shell("mkdir -p /sdcard/Download/ec1-qa");shell("cp "+file.getAbsolutePath()+" /sdcard/Download/ec1-qa/"+name+".png");
    }
    @Test public void blockedClockRendersRealCandlesWithoutTradingPaths()throws Exception{
        JSONObject state=blocked();String originalForecast=state.getJSONObject("forecast").toString();Bitmap[] bitmap={null};
        ui(()->{
            SparklineView chart=new SparklineView(context);populate(chart,state);
            String text=String.valueOf(chart.getContentDescription());
            assertTrue("Raw chart must disclose its unverified clock: "+text,text.contains("время не подтверждено"));
            assertTrue("The reason must survive to the visible chart description",text.contains("FUTURE 10797s"));
            assertFalse(text,text.contains("Текущие гипотезы LIVE"));
            assertEquals("Keep actual raw timestamps without an invented correction",RAW_START,chart.oldestTime());
            JSONObject shown=chart.displayedForecast();
            assertEquals(0,chart.scenarioChoices().length());assertEquals(0,shown.optJSONArray("scenarios").length());
            assertNull(shown.optJSONObject("entry_levels"));assertNull(shown.optJSONObject("active_scenario"));
            assertFalse(SparklineView.shouldDrawProjection(shown));
            bitmap[0]=render(chart);
            assertTrue("Actual candle bodies and wicks must be visible",pixels(bitmap[0],GREEN,15,130)>60);
            assertTrue("Raw history occupies the chart instead of leaving a prediction panel",pixels(bitmap[0],GREEN,160,280)>60);
            assertEquals("No cached SELL prediction is drawn over raw time",0,pixels(bitmap[0],RED,145,280));
        });
        try{assertEquals("Display-only selection must not mutate the cached forecast",originalForecast,state.getJSONObject("forecast").toString());
            save(bitmap[0],"r54-unverified-candles");}finally{if(bitmap[0]!=null)bitmap[0].recycle();}
    }
    @Test public void rawHistoryCannotMergeVerifiedRowsAndRecoveryRestoresVerifiedMap()throws Exception{
        JSONObject good=verified(),raw=blocked();JSONArray extra=bars(VERIFIED_START-15000);
        ui(()->{
            SparklineView chart=new SparklineView(context);populate(chart,good);chart.panHistory(15);
            String verifiedIdentity=chart.marketIdentity();populate(chart,raw);
            assertNotEquals("Clock domains require distinct viewport identities",verifiedIdentity,chart.marketIdentity());
            assertEquals(RAW_START,chart.oldestTime());assertTrue(chart.isFollowingLive());
            chart.prependHistory(extra);
            assertEquals("Verified archive rows must never merge with raw terminal timestamps",RAW_START,chart.oldestTime());
            chart.panHistory(12);populate(chart,raw);assertFalse("Updates preserve inspection of the same raw clock",chart.isFollowingLive());
            populate(chart,good);
            assertEquals(verifiedIdentity,chart.marketIdentity());assertEquals(VERIFIED_START,chart.oldestTime());
            assertEquals(VERIFIED_START+49*300,chart.historyRightTime());assertTrue(chart.isFollowingLive());
            assertEquals(1,chart.scenarioChoices().length());
            assertFalse(String.valueOf(chart.getContentDescription()).contains("не подтверждено"));
        });
    }
    @Test public void cachedRawChartRemainsExplicitlyOffline()throws Exception{
        JSONObject state=blocked().put("client_offline",true);
        ui(()->{
            SparklineView chart=new SparklineView(context);populate(chart,state);
            String text=String.valueOf(chart.getContentDescription());
            assertTrue(text,text.contains("время не подтверждено"));
            assertTrue(text,text.contains("НЕТ СВЯЗИ")||text.contains("потерял связь"));
            assertFalse(text,text.contains("Текущие гипотезы LIVE"));
        });
    }
    private void fixture()throws Exception{
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(200);
        context.getSharedPreferences("fxm1",Context.MODE_PRIVATE).edit().clear()
            .putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r54-chart-ui-1234").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());
        EventClient.http("POST",EventClient.base()+"/test/r54-future-time",new JSONObject());EventClient.poll();
    }
    private void screenshot(String name)throws Exception{
        shell("mkdir -p /sdcard/Download/ec1-qa");shell("screencap -p /sdcard/Download/ec1-qa/"+name+".png");
    }
    @Test public void futureTerminalCandlesReachEmbeddedAndFullscreenViews()throws Exception{
        fixture();try{
            JSONObject received=EventClient.state();JSONObject market=received.optJSONObject("chart_market");
            assertNotNull("Fixture must supply raw terminal data while the trading clock is blocked",market);
            assertTrue(market.getJSONArray("bars").length()>10);
            rule.launchActivity(new Intent());UiDevice device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
            ui(()->{
                SparklineView chart=rule.getActivity().findViewById(R.id.sparklineView);
                ScrollView root=rule.getActivity().findViewById(R.id.rootLayout);Rect bounds=new Rect();
                chart.getDrawingRect(bounds);root.offsetDescendantRectToMyCoords(chart,bounds);
                root.scrollTo(0,Math.max(0,bounds.top-Math.round(35*density)));
            });
            assertTrue("Embedded chart must explain blocked clock",device.wait(Until.hasObject(By.descContains("не подтвержден")),7000));
            screenshot("r54-future-time-embedded");
            ui(()->ScenarioUi.enlarge(rule.getActivity()));
            assertTrue(device.wait(Until.hasObject(By.text("ЗАКРЫТЬ КАРТУ")),5000));
            assertTrue(device.wait(Until.hasObject(By.descContains("не подтвержден")),5000));Thread.sleep(300);
            screenshot("r54-future-time-fullscreen");
            device.findObject(By.text("ЗАКРЫТЬ КАРТУ")).click();
            EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());
            EventClient.http("POST",EventClient.base()+"/test/r5-market",new JSONObject().put("family","TRIANGLE"));EventClient.poll();
            ui(()->ScenarioUi.enlarge(rule.getActivity()));
            assertTrue(device.wait(Until.hasObject(By.descContains("Текущие гипотезы LIVE")),7000));
            screenshot("r54-chart-clock-recovered");
            device.findObject(By.text("ЗАКРЫТЬ КАРТУ")).click();
        }finally{context.stopService(new Intent(context,MonitoringService.class));}
    }
}
