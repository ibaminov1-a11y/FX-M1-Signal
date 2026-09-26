package com.openai.fxm1;
import android.content.*;
import android.widget.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.lang.reflect.Method;
import static org.junit.Assert.*;
@RunWith(AndroidJUnit4.class)
public class R5RedContractUiTest {
 @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
 Context c; UiDevice device;
 void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
 @Before public void setup()throws Exception{
  c=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
  c.stopService(new Intent(c,MonitoringService.class));Thread.sleep(500);device.wakeUp();device.pressHome();
  c.getSharedPreferences("fxm1",Context.MODE_PRIVATE).edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
   .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765").putString("ec_client_id","r5-red-contract-12345")
   .putString("target_trade_mode","DEMO").putString("selected_symbol","EUR/USD").putString("ec_lot_cap","0.50").putInt("entry_tf_pos",1).commit();
  EventClient.init(c);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();rule.launchActivity(new Intent());Thread.sleep(1200);
 }
 @After public void cleanup()throws Exception{c.stopService(new Intent(c,MonitoringService.class));Thread.sleep(300);}
 @Test public void selectedLotReachesConfiguration()throws Exception{
  assertEquals("R5_VOLUME_MISSING",.5,EventClient.config().optDouble("requested_lot",0),1e-9);
 }
 @Test public void targetRealHeaderFollowsSavedSettings()throws Exception{
  ui(()->{try{Method m=MainActivity.class.getDeclaredMethod("showSmartFeaturesDialog");m.setAccessible(true);m.invoke(rule.getActivity());}catch(Exception e){throw new RuntimeException(e);}});
  UiObject2 real=device.wait(Until.findObject(By.text("РЕАЛЬНЫЙ СЧЁТ")),5000);assertNotNull(real);real.click();device.findObject(By.res("android","button1")).click();Thread.sleep(500);
  UiObject2 ok=device.findObject(By.res("android","button1"));if(ok!=null)ok.click();Thread.sleep(1200);
  ui(()->assertTrue("R5_TARGET_LABEL_MISSING",((Switch)rule.getActivity().findViewById(R.id.autoTradingSwitch)).getText().toString().contains("REAL")));
 }
 @Test public void chartHasLiveHistoryNavigation()throws Exception{
  ui(()->rule.getActivity().findViewById(R.id.sparklineView).performClick());
  assertTrue("R5_HISTORY_NAVIGATION_MISSING",device.wait(Until.hasObject(By.text("LIVE")),5000));
 }
}
