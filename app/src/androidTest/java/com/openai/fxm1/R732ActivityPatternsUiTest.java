package com.openai.fxm1;

import android.content.*;
import android.os.*;
import android.view.*;
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

/** Normal HTTP -> EventClient -> actual MainActivity -> chart. Numeric broker fixtures only. */
@RunWith(AndroidJUnit4.class)
public class R732ActivityPatternsUiTest {
 @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
 private Context ctx;private UiDevice device;private static final String BASE="http://127.0.0.1:8765";
 private void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
 private SparklineView chart(){return rule.getActivity().findViewById(R.id.sparklineView);}
 private void shell(String cmd)throws Exception{try(ParcelFileDescriptor f=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);InputStream s=new ParcelFileDescriptor.AutoCloseInputStream(f)){byte[] b=new byte[4096];while(s.read(b)!=-1){}}}
 private void sync()throws Exception{Method m=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");m.setAccessible(true);ui(()->{try{m.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}});InstrumentationRegistry.getInstrumentation().waitForIdleSync();}
 @Before public void start()throws Exception{
  ctx=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.wakeUp();device.pressHome();
  ctx.stopService(new Intent(ctx,MonitoringService.class));
  if(Build.VERSION.SDK_INT>=33)shell("pm grant "+ctx.getPackageName()+" android.permission.POST_NOTIFICATIONS");
  ctx.getSharedPreferences("fxm1",0).edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
   .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url",BASE).putString("ec_client_id","r732-activity")
   .putString("target_trade_mode","DEMO").putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("entry_tf_name","M5").putString("ec_lot_cap","0.01").commit();
  EventClient.init(ctx);EventClient.http("POST",BASE+"/test/reset",new JSONObject());EventClient.poll();rule.launchActivity(new Intent());sync();
 }
 @After public void stop()throws Exception{ctx.stopService(new Intent(ctx,MonitoringService.class));ui(()->rule.getActivity().finish());EventClient.http("POST",BASE+"/test/reset",new JSONObject());}
 private JSONObject scene(int index,String view,boolean position)throws Exception{
  EventClient.http("POST",BASE+"/test/r732-pattern",new JSONObject().put("index",index).put("view",view).put("position",position));
  JSONObject state=EventClient.poll();sync();String id=state.getJSONObject("forecast").optString("selected_pattern_id");
  ui(()->{chart().goLive();if(!id.isEmpty())chart().selectPattern(id);chart().fitSelectedPattern();chart().requestRectangleOnScreen(new android.graphics.Rect(0,0,chart().getWidth(),chart().getHeight()),true);});
  InstrumentationRegistry.getInstrumentation().waitForIdleSync();return state;
 }
 private void shot(String name)throws Exception{
  device.waitForIdle();File dir=new File(ctx.getExternalFilesDir(null),"r732-shots");assertTrue(dir.isDirectory()||dir.mkdirs());File p=new File(dir,name+".png");assertTrue(device.takeScreenshot(p));
  shell("mkdir -p /sdcard/Download/ec1-qa");shell("cp "+p.getAbsolutePath()+" /sdcard/Download/ec1-qa/"+name+".png");
 }
 @Test public void actualActivityShowsAllNineteenNumericPatternsWithoutTrading()throws Exception{
  for(int i=0;i<19;i++){
   JSONObject state=scene(i,"live",false),expected=R732PatternRendererUiTest.pattern(state);assertNotNull(expected);
   final String[] description={""};ui(()->description[0]=chart().getContentDescription().toString());
   assertTrue("Activity hides figure "+i+": "+description[0],description[0].contains(expected.getString("title")));
   final String[] heading={""};ui(()->heading[0]=((android.widget.TextView)rule.getActivity().findViewById(R.id.confidenceText)).getText().toString());
   assertTrue("Heading contradicts figure "+i+": "+heading[0],heading[0].contains(expected.getString("title")));
   assertFalse(chart().displayedForecast().optBoolean("show_price_forecast",true));shot("r732-activity-"+i);
  }
  JSONArray commands=EventClient.http("GET",BASE+"/test/r53-command-audit",null).getJSONArray("commands");
  for(int i=0;i<commands.length();i++){String cmd=commands.getJSONObject(i).getString("command");assertFalse("Viewing must not authorize trades",cmd.equals("enable")||cmd.equals("arm_real"));}
  assertFalse(EventClient.state().optBoolean("auto"));
 }
 @Test public void fullScreenRetainsSelectedHeadAndShoulders()throws Exception{
  JSONObject s=scene(17,"live",false);String title=R732PatternRendererUiTest.pattern(s).getString("title");
  ui(()->assertTrue(chart().performClick()));device.waitForIdle();shot("r732-fullscreen-head-shoulders");
  assertTrue("Fullscreen must preserve selected figure",device.wait(Until.hasObject(By.descContains(title)),5000));device.pressBack();
 }
 @Test public void formingEmptyStaleOfflineAndPositionAreActualActivityScreens()throws Exception{
  scene(19,"live",false);assertTrue(chart().getContentDescription().toString().contains("Формируется"));shot("r732-activity-forming");
  scene(0,"empty",false);assertEquals(0,chart().patternChoices().length());shot("r732-activity-no-figure");
  scene(17,"stale",false);assertTrue(chart().displayedForecast().optBoolean("stale"));shot("r732-activity-stale");
  scene(17,"offline",false);assertTrue(chart().displayedForecast().optBoolean("client_offline"));shot("r732-activity-offline");
  JSONObject s=scene(17,"live",true);assertTrue(s.getJSONArray("positions").length()>0);shot("r732-activity-position");
  ui(()->chart().setArchive(true));shot("r732-activity-archive");ui(()->chart().setArchive(false));
 }
}
