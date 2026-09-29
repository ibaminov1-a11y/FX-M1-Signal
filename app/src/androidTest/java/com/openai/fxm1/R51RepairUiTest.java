package com.openai.fxm1;

import android.app.*;
import android.content.*;
import android.os.*;
import android.graphics.*;
import android.widget.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class R51RepairUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context;
    void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    @Before public void setup()throws Exception{
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(200);
        context.getSharedPreferences("fxm1",Context.MODE_PRIVATE).edit().clear()
            .putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r51-repair-ui-1234").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();
    }
    @After public void stop(){context.stopService(new Intent(context,MonitoringService.class));}
    void shot(String name)throws Exception{
        for(String cmd:new String[]{"mkdir -p /sdcard/Download/ec1-qa","screencap -p /sdcard/Download/ec1-qa/"+name+".png"})
            try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);
                InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] b=new byte[4096];while(in.read(b)!=-1){}}
    }
    @Test public void legacyCatalogueIsRemovedWithoutChangingChosenSymbolOrLot()throws Exception{
        StringBuilder catalogue=new StringBuilder("A|AA|AAA");for(int i=0;i<1500;i++)catalogue.append("|AA").append(i);
        EventClient.prefs().edit().putString("mt5_symbols_cache",catalogue.toString())
            .putString("custom_symbols","US100|EURUSD.a").putString("selected_symbol","EURUSD.a").putString("ec_lot_cap","0.37").commit();
        rule.launchActivity(new Intent());Thread.sleep(600);
        ui(()->{
            Spinner s=rule.getActivity().findViewById(R.id.symbolSpinner);
            assertTrue("A broker catalogue must not replace the watchlist",s.getCount()<=25);
            assertEquals("EURUSD.a",s.getSelectedItem().toString());
            assertEquals("0.37",EventClient.prefs().getString("ec_lot_cap",""));
            assertEquals("EUR/USD",s.getItemAtPosition(0).toString());
        });
    }
    @Test public void liveCatalogueSyncDoesNotReplaceTheWatchlist()throws Exception{
        rule.launchActivity(new Intent());Thread.sleep(500);JSONArray catalogue=new JSONArray();
        for(int i=0;i<3000;i++)catalogue.put("AAA"+i);catalogue.put("EURUSD");catalogue.put("USDJPY");
        Method m=MainActivity.class.getDeclaredMethod("syncBrokerSymbols",JSONArray.class);m.setAccessible(true);
        ui(()->{try{
            Spinner s=rule.getActivity().findViewById(R.id.symbolSpinner);String selected=s.getSelectedItem().toString();
            m.invoke(rule.getActivity(),catalogue);
            assertTrue("Reconnect must not install thousands of symbols",s.getCount()<=25);
            assertEquals(selected,s.getSelectedItem().toString());
        }catch(Exception e){throw new AssertionError(e);}});
    }
    JSONObject forecast()throws Exception{
        JSONArray routes=new JSONArray();
        for(int i=0;i<4;i++)routes.put(new JSONObject().put("scenario_id","s"+i).put("name","OPTION"+(i+1))
            .put("side",i%2==0?1:-1).put("type","DIRECT_BREAKOUT").put("title","Треугольник: прямой пробой")
            .put("stage","WATCHING").put("activation",1.1004).put("target1",1.1010).put("target",1.1010)
            .put("quality_score",65).put("next_event","Ждём новый пробой вверх 1.10040"));
        return new JSONObject().put("map_version",3).put("selection_status","TIED").put("scenarios",routes);
    }
    @Test public void tiedForecastIsNotLabelledMainAndMissingT2IsNotFabricated()throws Exception{
        JSONObject f=forecast();String text=ScenarioUi.headline(f);
        assertTrue(text,text.toLowerCase(Locale.ROOT).contains("равнознач"));
        String levels=ScenarioUi.levels(new JSONObject().put("forecast",f));
        assertFalse(levels,levels.contains("MAIN"));assertFalse(levels,levels.contains("WATCHING"));
        assertFalse(SparklineView.mapDescription(f).contains("T2 1.10100"));
    }
    @Test public void compactChartShowsNoMoreThanTwoSelectedPaths()throws Exception{
        JSONObject f=forecast();
        ui(()->{SparklineView chart=new SparklineView(context);chart.setMarket(new JSONArray(),null,null,null,"SCENARIO_V2",null,null,f);
            chart.selectScenarios(new LinkedHashSet<>(Arrays.asList("s0","s1","s2","s3")));
            assertEquals(2,chart.displayedForecast().optJSONArray("scenarios").length());});
    }
    JSONArray bars(long start)throws Exception{
        JSONArray a=new JSONArray();for(int i=0;i<50;i++)a.put(new JSONObject().put("time",start+i*300)
            .put("open",1.1).put("high",1.101).put("low",1.099).put("close",1.1005));return a;
    }
    @Test public void historyGenerationClearsTheOldViewportInsteadOfMergingShiftedCandles()throws Exception{
        JSONObject a=new JSONObject().put("market_scope","EURUSD").put("market_history_generation","OLD")
            .put("bars",bars(1799999905L));
        JSONObject b=new JSONObject().put("market_scope","EURUSD").put("market_history_generation","UTC_NATIVE_R51")
            .put("bars",bars(1800000000L));
        Method populate=ScenarioUi.class.getDeclaredMethod("populate",SparklineView.class,JSONObject.class);populate.setAccessible(true);
        ui(()->{try{SparklineView chart=new SparklineView(context);populate.invoke(null,chart,a);populate.invoke(null,chart,b);
            assertEquals(1800000000L,chart.oldestTime());
        }catch(Exception e){throw new AssertionError(e);}});
    }
    @Test public void denseAnnotationPlacementNeverOverlapsOrEscapesBounds()throws Exception{
        Class<?> cls;
        try{cls=Class.forName("com.openai.fxm1.ChartLabelPlacer");}catch(ClassNotFoundException e){fail("Shared route/level label placement is missing");return;}
        Method place=cls.getDeclaredMethod("place",List.class,RectF.class,float.class,float.class,float.class,float.class);place.setAccessible(true);
        List<RectF> used=new ArrayList<>();RectF bounds=new RectF(100,50,280,380);int count=0;
        for(int i=0;i<24;i++){
            RectF box=(RectF)place.invoke(null,used,bounds,115f,160f,125f,12f);
            if(box==null)continue;
            assertTrue(bounds.contains(box));for(RectF earlier:used)assertFalse(RectF.intersects(box,earlier));
            used.add(box);count++;
        }
        assertTrue("Do not solve overlap by hiding all labels",count>=12);
    }
    @Test public void repairedWatchlistAndMapAreCapturedFromRunningActivity()throws Exception{
        rule.launchActivity(new Intent());Thread.sleep(600);
        ui(()->rule.getActivity().findViewById(R.id.symbolSpinner).performClick());Thread.sleep(300);shot("r51-instruments");
        UiDevice device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.pressBack();
        EventClient.http("POST",EventClient.base()+"/test/r5-market",new JSONObject().put("family","TRIANGLE"));EventClient.poll();
        ui(()->ScenarioUi.enlarge(rule.getActivity()));
        assertTrue(device.wait(Until.hasObject(By.text("ЗАКРЫТЬ КАРТУ")),5000));Thread.sleep(700);shot("r51-fullscreen-map");
        assertNotNull(device.findObject(By.text("LIVE")));device.findObject(By.text("ЗАКРЫТЬ КАРТУ")).click();
    }
}
