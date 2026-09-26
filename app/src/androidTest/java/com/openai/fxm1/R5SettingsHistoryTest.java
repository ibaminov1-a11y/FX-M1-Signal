package com.openai.fxm1;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.os.*;
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
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class R5SettingsHistoryTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context;UiDevice device;
    void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    @Before public void setup()throws Exception{
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(350);
        context.getSharedPreferences("fxm1",Context.MODE_PRIVATE).edit().clear()
            .putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r5-ui-client-1234").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();
    }
    @After public void stop(){context.stopService(new Intent(context,MonitoringService.class));}
    void shot(String name)throws Exception{
        for(String cmd:new String[]{"mkdir -p /sdcard/Download/ec1-qa","screencap -p /sdcard/Download/ec1-qa/"+name+".png"})
            try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);
                InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] b=new byte[4096];while(in.read(b)!=-1){}}
    }
    @Test public void configTransmitsChosenLotNotHardcoded001()throws Exception{
        EventClient.prefs().edit().putString("ec_lot_cap","0.50").commit();
        JSONObject c=EventClient.config();assertEquals("Chosen lot must reach Bridge",.50,c.getDouble("lot_cap"),1e-9);
        assertEquals(.50,c.getDouble("probe_lot_cap"),1e-9);assertEquals("FIXED",c.optString("volume_mode"));
        assertEquals("SCENARIO_V2",c.optString("engine_mode"));
    }
    @Test public void autoTitleUsesSelectedModeRatherThanActualAccount()throws Exception{
        EventClient.prefs().edit().putString("target_trade_mode","REAL").putString("mt5_account_type_snapshot","DEMO").commit();
        rule.launchActivity(new Intent());Thread.sleep(500);
        ui(()->assertTrue("Selected REAL must appear in AUTO title",((TextView)rule.getActivity().findViewById(R.id.autoTradingSwitch)).getText().toString().contains("REAL")));
    }
    @Test public void lotSelectorHasPresetsAndCustomChoice()throws Exception{
        rule.launchActivity(new Intent());Thread.sleep(500);
        ui(()->{
            Spinner sp=rule.getActivity().findViewById(R.id.maxPositionsSpinner);
            assertTrue("Lot selector needs preset sizes and manual input",sp.getCount()>=6);
            boolean found=false;for(int i=0;i<sp.getCount();i++)if(sp.getItemAtPosition(i).toString().contains("0.50"))found=true;
            assertTrue(found);
        });
    }
    @Test public void manualCommaValueAndInvalidValuesHaveExplicitValidation()throws Exception{
        Class<?> cls;
        try{cls=Class.forName("com.openai.fxm1.TradeSettings");}catch(ClassNotFoundException e){fail("Fixed lot input validator is missing");return;}
        Method parse=cls.getMethod("parseVolume",String.class,JSONObject.class);
        JSONObject limits=new JSONObject().put("volume_min",.01).put("volume_max",100).put("volume_step",.01);
        assertEquals(.37,((Number)parse.invoke(null,"0,37",limits)).doubleValue(),1e-9);
        for(String value:new String[]{"","0","-1","NaN","Infinity","0.015"}){
            boolean rejected=false;try{parse.invoke(null,value,limits);}catch(InvocationTargetException e){rejected=true;}
            assertTrue("Invalid lot must be rejected: "+value,rejected);
        }
    }
    JSONArray bars(int n)throws Exception{
        JSONArray out=new JSONArray();for(int i=0;i<n;i++)out.put(new JSONObject().put("time",1800000000L+i*300)
            .put("open",1.1).put("high",1.11).put("low",1.09).put("close",1.105));return out;
    }
    @Test public void historyViewportStaysAnchoredWhileNewBarsArrive()throws Exception{
        final SparklineView[] view={null};JSONArray old=bars(90),fresh=bars(92);final long[] anchor={0};
        Method pan,edge,live;
        try{pan=SparklineView.class.getMethod("panHistory",int.class);edge=SparklineView.class.getMethod("historyRightTime");live=SparklineView.class.getMethod("isFollowingLive");}
        catch(NoSuchMethodException e){fail("Historical viewport methods are missing");return;}
        ui(()->{try{view[0]=new SparklineView(context);view[0].layout(0,0,1080,1300);
            view[0].setMarket(old,null,null,null,"SCENARIO_V2",null,null,new JSONObject().put("map_version",3));
            pan.invoke(view[0],20);anchor[0]=((Number)edge.invoke(view[0])).longValue();
            view[0].setMarket(fresh,null,null,null,"SCENARIO_V2",null,null,new JSONObject().put("map_version",3));
            assertEquals(anchor[0],((Number)edge.invoke(view[0])).longValue());assertEquals(false,live.invoke(view[0]));
        }catch(Exception e){throw new AssertionError(e);}});
    }
    @Test public void savingSmartSettingsDoesNotResetManualLot()throws Exception{
        EventClient.prefs().edit().putString("ec_lot_cap","0.37").commit();rule.launchActivity(new Intent());Thread.sleep(700);
        ui(()->rule.getActivity().findViewById(R.id.smartFeaturesButton).performClick());
        UiObject2 save=device.wait(Until.findObject(By.text("СОХРАНИТЬ")),5000);assertNotNull(save);save.click();Thread.sleep(700);
        assertEquals("Smart settings must not silently replace a selected lot",.37,Double.parseDouble(EventClient.prefs().getString("ec_lot_cap","")),1e-9);
    }
    @Test public void actualLotSelectionReachesServerConfiguration()throws Exception{
        rule.launchActivity(new Intent());Thread.sleep(600);
        ui(()->((Spinner)rule.getActivity().findViewById(R.id.maxPositionsSpinner)).setSelection(3));
        long end=SystemClock.elapsedRealtime()+8000;JSONObject s=null;
        while(SystemClock.elapsedRealtime()<end){s=EventClient.poll();if(Math.abs(s.getJSONObject("config").optDouble("lot_cap")-.5)<1e-8)break;Thread.sleep(250);}
        assertEquals(.5,s.getJSONObject("config").optDouble("lot_cap"),1e-8);
        assertEquals("FIXED",s.getJSONObject("config").optString("volume_mode"));shot("r5-lot-controls");
    }

    @Test public void actualV2MapSupportsHistoryAndImmutableArchive()throws Exception{
        EventClient.http("POST",EventClient.base()+"/test/r5-market",new JSONObject().put("family","TRIANGLE"));
        JSONObject state=EventClient.poll();assertEquals(3,state.getJSONObject("forecast").getInt("map_version"));
        assertTrue(state.getJSONObject("forecast").getJSONArray("scenarios").length()>1);
        rule.launchActivity(new Intent());Thread.sleep(1600);
        ui(()->rule.getActivity().findViewById(R.id.sparklineView).performClick());
        assertTrue(device.wait(Until.hasObject(By.text("ЗАКРЫТЬ КАРТУ")),5000));Thread.sleep(800);shot("r5-fullscreen-scenarios");
        UiObject2 back=device.findObject(By.text("◀"));assertNotNull(back);back.click();Thread.sleep(500);shot("r5-history-viewport");
        UiObject2 live=device.findObject(By.text("LIVE"));assertNotNull(live);live.click();Thread.sleep(400);
        device.findObject(By.text("ЗАКРЫТЬ КАРТУ")).click();
        JSONObject list=EventClient.http("GET",EventClient.base()+"/ec/scenarios?limit=3",null);
        JSONObject summary=list.getJSONArray("snapshots").getJSONObject(0);
        String id=summary.getString("snapshot_id");
        String before=EventClient.http("GET",EventClient.base()+"/ec/scenarios?id="+id,null).getJSONArray("snapshots").getJSONObject(0).toString();
        Thread.sleep(1000);
        String after=EventClient.http("GET",EventClient.base()+"/ec/scenarios?id="+id,null).getJSONArray("snapshots").getJSONObject(0).toString();
        assertEquals(before,after);
    }
    @Test public void singleBarHistoryDoesNotThrow()throws Exception{
        JSONArray only=bars(1);
        ui(()->{SparklineView chart=new SparklineView(context);
            chart.setMarket(only,null,null,null,"SCENARIO_V2",null,null,null);
            chart.panHistory(12);assertEquals(1800000000L,chart.historyRightTime());
            chart.panHistory(-12);assertEquals(1800000000L,chart.historyRightTime());});
    }
}
