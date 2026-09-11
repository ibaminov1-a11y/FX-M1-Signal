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
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

/** Native UI + actual HTTP/Flask/Engine, fake MT5. No live market actions. */
@RunWith(AndroidJUnit4.class)
public class EventCoreUiTest {
 @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
 Context context;SharedPreferences p;UiDevice device;
 @Before public void prepare()throws Exception{
  context=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
  context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(600);device.wakeUp();device.pressHome();
  shell("pm grant "+context.getPackageName()+" android.permission.POST_NOTIFICATIONS");
  p=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);p.edit().clear()
   .putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
   .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
   .putString("ec_fee","0").putString("ec_client_id","ci-client-12345678").putString("entry_tf","M5")
   .putString("trading_mode","NORMAL").putLong("mt5_balance_bits",Double.doubleToLongBits(99868.35))
   .putLong("mt5_equity_bits",Double.doubleToLongBits(99868.35)).commit();
  EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();
  rule.launchActivity(new Intent());
 }
 void main(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
 void shell(String command)throws Exception{try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[]b=new byte[4096];while(in.read(b)!=-1){}}}
 void await(BooleanSupplier f,String label)throws Exception{long end=SystemClock.elapsedRealtime()+20000;while(SystemClock.elapsedRealtime()<end){if(f.getAsBoolean())return;Thread.sleep(150);}fail(label);}
 void shot(String name)throws Exception{shell("mkdir -p /sdcard/Download/ec1-qa");shell("screencap -p /sdcard/Download/ec1-qa/"+name+".png");}
 void click(String label)throws Exception{for(int i=0;i<5;i++){try{UiObject2 v=device.wait(Until.findObject(By.text(label)),6000);assertNotNull(label,v);v.click();return;}catch(StaleObjectException e){if(i==4)throw e;Thread.sleep(80);}}}
 @Test public void legacyUiActualBalanceAndModesArePreserved()throws Exception{
  main(()->{MainActivity a=rule.getActivity();assertNotNull(a.findViewById(R.id.symbolSpinner));assertNotNull(a.findViewById(R.id.moneyHistoryButton));
   assertTrue(((TextView)a.findViewById(R.id.accountText)).getText().toString().contains("99868.35"));
   assertEquals("10.9-EC1",FeatureEngine.appVersionName(a));
   Spinner modes=a.findViewById(R.id.signalModeSpinner),tf=a.findViewById(R.id.entryTimeframeSpinner);
   assertNotNull(modes);assertEquals(2,modes.getCount());String before=tf.getSelectedItem().toString();modes.setSelection(1);
   assertEquals(before,tf.getSelectedItem().toString());
  });Thread.sleep(300);shot("01-main");
  main(()->rule.getActivity().findViewById(R.id.moneyHistoryButton).performClick());Thread.sleep(600);shot("02-history");
 }
 @Test public void actualCandlesAreGreenAndRed()throws Exception{
  JSONArray bars=new JSONArray().put(new JSONObject().put("time",1800000000).put("open",1.1).put("high",1.102).put("low",1.099).put("close",1.101))
    .put(new JSONObject().put("time",1800000300).put("open",1.101).put("high",1.102).put("low",1.098).put("close",1.099));
  final Bitmap[] bitmap={null};
  main(()->{SparklineView c=new SparklineView(rule.getActivity());c.layout(0,0,800,500);c.setMarket(bars,new JSONArray(),new JSONArray());
   bitmap[0]=Bitmap.createBitmap(800,500,Bitmap.Config.ARGB_8888);c.draw(new Canvas(bitmap[0]));});
  int green=0,red=0;int[]pixels=new int[800*500];bitmap[0].getPixels(pixels,0,800,0,0,800,500);
  for(int v:pixels){if(v==0xff42d67a)green++;if(v==0xffff4857)red++;}assertTrue(green>100);assertTrue(red>100);
  try(FileOutputStream out=new FileOutputStream(new File(context.getExternalFilesDir(null),"candles.png"))){bitmap[0].compress(Bitmap.CompressFormat.PNG,100,out);}
  shell("mkdir -p /sdcard/Download/ec1-qa");shell("cp "+new File(context.getExternalFilesDir(null),"candles.png")+" /sdcard/Download/ec1-qa/candles.png");bitmap[0].recycle();
 }
 @Test public void notificationsControlActualEngineAndEmergencyPersists()throws Exception{
  main(()->rule.getActivity().findViewById(R.id.analyzeButton).performClick());await(()->p.getBoolean("bg_running",false),"monitoring start");Thread.sleep(800);
  EventClient.configure();EventClient.command("approve_profile",new JSONObject().put("confirmation","APPROVE_DEMO_RISK"));
  EventClient.command("enable",new JSONObject().put("confirmation","ENABLE_DEMO"));EventClient.poll();
  device.openNotification();assertTrue(device.wait(Until.hasObject(By.text("PAUSE")),10000));shot("03-notification");
  click("PAUSE");await(()->p.getBoolean("trading_paused",false),"server PAUSE reflected");
  click("PLAY");await(()->!p.getBoolean("trading_paused",true),"server PLAY reflected");
  click("EMERGENCY STOP");Thread.sleep(200);click("EMERGENCY STOP");await(()->p.getBoolean("v108_emergency_latched",false),"local latch");
  await(()->EventClient.state().optBoolean("emergency",false),"server emergency latch");
  click("PLAY");Thread.sleep(600);assertFalse(p.getBoolean("auto_trading",true));
  context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(500);
  device.pressBack();main(()->context.startForegroundService(new Intent(context,MonitoringService.class).setAction(MonitoringService.ACTION_RESUME)));
  Thread.sleep(1000);assertTrue(p.getBoolean("v108_emergency_latched",false));assertFalse(p.getBoolean("auto_trading",true));shot("04-emergency");
 }
 @After public void cleanup()throws Exception{context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(500);}
}
