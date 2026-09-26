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
import static org.junit.Assert.*;

/** Reproduce the user's update with old campaign state, through the actual AUTO button. */
@RunWith(AndroidJUnit4.class)
public class ScenarioUpgradeUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context;UiDevice device;
    void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    void shell(String cmd)throws Exception{
        try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);
            InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] b=new byte[4096];while(in.read(b)!=-1){}}
    }
    void shot(String name)throws Exception{shell("mkdir -p /sdcard/Download/ec1-qa");shell("screencap -p /sdcard/Download/ec1-qa/"+name+".png");}
    @Before public void setup()throws Exception{
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(600);device.wakeUp();device.pressHome();
        shell("pm grant "+context.getPackageName()+" android.permission.POST_NOTIFICATIONS");
        context.getSharedPreferences("fxm1",Context.MODE_PRIVATE).edit().clear()
            .putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","upgrade-ui-client-1234").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).commit();
        EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();
        rule.launchActivity(new Intent());
    }
    @After public void cleanup()throws Exception{context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(500);}
    @Test public void legacyProjectionCannotReappearDuringAnUpgrade()throws Exception{
        JSONArray bars=new JSONArray();for(int i=0;i<20;i++){
            double o=1.1000+i*.00005;bars.put(new JSONObject().put("time",1800000000+i*300)
                .put("open",o).put("close",o+.00003).put("high",o+.00005).put("low",o-.00002));
        }
        JSONObject old=new JSONObject().put("side",1).put("candidate_side",1).put("up_probability",.67)
            .put("projection",new JSONArray()
                .put(new JSONObject().put("minutes",5).put("center",1.1012).put("high",1.1013).put("low",1.1011))
                .put(new JSONObject().put("minutes",10).put("center",1.1014).put("high",1.1015).put("low",1.1013))
                .put(new JSONObject().put("minutes",15).put("center",1.1016).put("high",1.1017).put("low",1.1015)));
        final Bitmap[] image={null};
        ui(()->{SparklineView view=new SparklineView(context);view.layout(0,0,1000,850);
            view.setMarket(bars,new JSONArray(),new JSONArray(),new JSONArray(),"TRIGGER",null,null,old);
            image[0]=Bitmap.createBitmap(1000,850,Bitmap.Config.ARGB_8888);view.draw(new Canvas(image[0]));});
        int green=0;for(int y=0;y<850;y++)for(int x=700;x<930;x++)if(image[0].getPixel(x,y)==0xff42d67a)green++;
        image[0].recycle();assertEquals("Legacy +5/+10/+15 forecast must never return",0,green);
    }
    @Test public void actualAutoButtonAcceptsOldCampaignThenActivatesStructuralMap()throws Exception{
        EventClient.http("POST",EventClient.base()+"/test/legacy-upgrade",new JSONObject());EventClient.poll();Thread.sleep(1600);
        JSONObject initial=EventClient.poll();assertEquals("LEGACY",initial.getJSONObject("config").getString("engine_mode"));
        assertEquals(0,initial.getJSONArray("positions").length());assertNotNull(initial.optJSONObject("campaign"));
        ui(()->rule.getActivity().findViewById(R.id.autoTradingSwitch).performClick());
        UiObject2 button=device.wait(Until.findObject(By.res("android","button1")),10000);assertNotNull("DEMO confirmation",button);button.click();
        JSONObject s=null;long end=SystemClock.elapsedRealtime()+10000;
        while(SystemClock.elapsedRealtime()<end){s=EventClient.poll();if(s.optBoolean("auto"))break;Thread.sleep(200);}
        shot("r42-auto-wait");
        assertTrue("AUTO intent must be accepted; existing campaign only inhibits entries",s.optBoolean("auto"));
        assertFalse(s.getJSONObject("entry_gate").optBoolean("allowed"));
        assertNotNull(s.optJSONObject("pending_config"));
        assertEquals("RECONCILING",s.optString("campaign_state"));
        assertFalse("No misleading open SELL at zero positions",EventClient.prefs().getString("state_context","").contains("Открытая кампания: SELL"));
        EventClient.http("POST",EventClient.base()+"/test/legacy-finish",new JSONObject());
        end=SystemClock.elapsedRealtime()+10000;
        while(SystemClock.elapsedRealtime()<end){s=EventClient.poll();if("SCENARIO_V2".equals(s.getJSONObject("config").optString("engine_mode")))break;Thread.sleep(200);}
        assertEquals("SCENARIO_V2",s.getJSONObject("config").optString("engine_mode"));
        assertTrue(s.optBoolean("auto"));assertNull(s.optJSONObject("campaign"));
        assertEquals(3,s.getJSONObject("forecast").optInt("map_version"));
        Thread.sleep(1800);
        ui(()->{
            MainActivity a=rule.getActivity();SparklineView chart=a.findViewById(R.id.sparklineView);
            assertTrue("Map must be tall, not an old sparkline",chart.getHeight()/context.getResources().getDisplayMetrics().density>=360);
            assertTrue(chart.getContentDescription().toString().contains("T1"));
            String levels=((TextView)a.findViewById(R.id.levelsText)).getText().toString();
            assertTrue(levels,levels.contains("T1:"));
            assertFalse(((TextView)a.findViewById(R.id.confidenceText)).getText().toString().contains("%"));
            chart.performClick();
        });
        assertTrue(device.wait(Until.hasObject(By.text("ЗАКРЫТЬ КАРТУ")),8000));
        Thread.sleep(500);shot("r42-fullscreen-map");
        device.findObject(By.text("ЗАКРЫТЬ КАРТУ")).click();
    }
}
