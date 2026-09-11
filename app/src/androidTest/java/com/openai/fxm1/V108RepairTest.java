package com.openai.fxm1;

import android.app.*;
import android.content.*;
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
import java.net.*;
import java.lang.reflect.*;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class V108RepairTest {
 @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
 Context context;SharedPreferences p;UiDevice device;
 @BeforeClass public static void fakeNetwork(){
  URL.setURLStreamHandlerFactory(protocol->("http".equals(protocol)||"https".equals(protocol))?new URLStreamHandler(){
   @Override protected URLConnection openConnection(URL u){return new HttpURLConnection(u){
    public void disconnect(){} public boolean usingProxy(){return false;} public void connect(){}
    public OutputStream getOutputStream(){return new ByteArrayOutputStream();}
    public int getResponseCode(){return 200;}
    public InputStream getInputStream(){return new ByteArrayInputStream(Fixture.body(url).getBytes(java.nio.charset.StandardCharsets.UTF_8));}
   };}
  }:null);
 }
 @Before public void prepare() throws Exception {
  context=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
  device.wakeUp();device.pressHome();context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(500);
  shell("pm grant "+context.getPackageName()+" android.permission.POST_NOTIFICATIONS");
  p=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);p.edit().clear().putBoolean("v108_initial_review",true)
   .putBoolean("v800_tf_migrated",true).putString("apikey","test-local-only").putString("server_url","http://fixture.invalid:8000")
   .putBoolean("server_verified",true).putBoolean("mt5_connected_snapshot",true).putBoolean("bridge_version_match_snapshot",true)
   .putString("mt5_account_type_snapshot","DEMO").putString("mt5_currency_snapshot","USD").putString("bridge_version_snapshot","10.0")
   .putLong("mt5_balance_bits",Double.doubleToLongBits(99868.35)).putLong("mt5_equity_bits",Double.doubleToLongBits(99868.35))
   .putInt("maxpos_pos",9).commit();
  rule.launchActivity(new Intent());
 }
 void shell(String command)throws Exception{
  try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] a=new byte[4096];while(in.read(a)!=-1){}}
 }
 void await(BooleanSupplier f,String label)throws Exception{long end=SystemClock.elapsedRealtime()+20000;while(SystemClock.elapsedRealtime()<end){if(f.getAsBoolean())return;Thread.sleep(150);}fail(label);}
 void main(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
 void screenshot(String name)throws Exception{shell("mkdir -p /sdcard/Download/v108-qa");shell("screencap -p /sdcard/Download/v108-qa/"+name+".png");}
 void click(String label)throws Exception{for(int i=0;i<3;i++){try{UiObject2 b=device.wait(Until.findObject(By.text(label)),6000);assertNotNull(label,b);b.click();return;}catch(StaleObjectException e){if(i==2)throw e;Thread.sleep(60);}}}
 @Test public void a_originalAccountHistoryAndControlsPreserved()throws Exception{
  main(()->{
   MainActivity a=rule.getActivity();assertNotNull(a.findViewById(R.id.symbolSpinner));assertNotNull(a.findViewById(R.id.entryTimeframeSpinner));
   assertNotNull(a.findViewById(R.id.moneyHistoryButton));assertNotNull(a.findViewById(R.id.autoTradingSwitch));
   TextView account=a.findViewById(R.id.accountText);assertTrue(account.getText().toString().contains("99868.35"));
   assertEquals("10.8",FeatureEngine.appVersionName(a));
  });screenshot("01-main");
  main(()->rule.getActivity().findViewById(R.id.moneyHistoryButton).performClick());Thread.sleep(600);screenshot("02-money");
 }
 @Test public void b_scoreBreakdownMatchesAll25515Inputs() {
  int count=0;
  for(String signal:new String[]{"BUY","SELL","WAIT"})for(int h2=-1;h2<=1;h2++)for(int h1=-1;h1<=1;h1++)
   for(int entry=-1;entry<=1;entry++)for(int fast=-1;fast<=1;fast++)for(int structure=-1;structure<=1;structure++)
   for(int breakout=-2;breakout<=2;breakout++)for(int pattern=-3;pattern<=3;pattern++){
    int legacy;if("WAIT".equals(signal))legacy=Math.min(59,25+Math.abs(h2+h1+entry+fast)*7+(structure!=0?5:0)+(breakout!=0?8:0));
    else{int d="BUY".equals(signal)?1:-1;int q=60+(h2==d?8:0)+(h1==d?8:0)+(entry==d?8:0)+(fast==d?4:0)+(structure==d?5:0)+(breakout==d*2?7:breakout==d?4:0);legacy=Math.min(100,Math.min(100,q)+Math.max(0,pattern*d)*5);}
    assertEquals(legacy,SignalScore.score(signal,h2,h1,entry,fast,structure,breakout,pattern));
    assertTrue(SignalScore.describe(signal,h2,h1,entry,fast,structure,breakout,pattern).contains("Итого: "+legacy+"/100"));count++;
   }
  assertEquals(25515,count);
 }
 @Test public void c_executionNeedsConfirmedFillAndShowsRisk()throws Exception{
  assertEquals("UNCONFIRMED",ExecutionFeedback.responseStage(new JSONObject().put("accepted",true)));
  assertEquals("REJECTED",ExecutionFeedback.responseStage(new JSONObject().put("accepted",false).put("retcode",10009).put("ticket",3)));
  assertEquals("FILLED",ExecutionFeedback.responseStage(new JSONObject().put("accepted",true).put("retcode",10009).put("ticket",3)));
  assertEquals("CONFIRMATION",ExecutionFeedback.responseStage(new JSONObject().put("pending_approval",true)));
  p.edit().putBoolean("auto_trading",true).putString("risk_snapshot","RISK BLOCK: [LOSS_STREAK]").putLong("smart_snapshot_ms",System.currentTimeMillis()).commit();
  ExecutionFeedback.record(p,"EUR/USD","M5","BLOCKED","Сессия ASIA запрещена; ордер не отправлен");
  String text=ExecutionFeedback.render(p,"EUR/USD","M5");assertTrue(text.contains("Сессия ASIA"));assertTrue(text.contains("серия убытков"));assertFalse(text.contains("SELL открыт"));
  assertTrue(ExecutionFeedback.bridgeCompatible("10.0"));assertFalse(ExecutionFeedback.bridgeCompatible("11.0"));
 }
 @Test public void d_nativeNotificationButtonsAndEmergencyRestart()throws Exception{
  main(()->rule.getActivity().findViewById(R.id.analyzeButton).performClick());await(()->p.getBoolean("bg_running",false),"monitoring start");
  device.openNotification();assertTrue(device.wait(Until.hasObject(By.text("PAUSE")),10000));screenshot("03-notification");
  click("PAUSE");await(()->p.getBoolean("trading_paused",false),"pause action");
  click("PLAY");await(()->!p.getBoolean("trading_paused",true),"play action");
  click("EMERGENCY STOP");Thread.sleep(150);click("EMERGENCY STOP");
  await(()->p.getBoolean("v108_emergency_latched",false),"emergency latch");await(()->!p.getBoolean("bg_running",true),"stop monitoring");
  assertFalse(p.getBoolean("auto_user_enabled",true));assertFalse(p.getBoolean("auto_trading",true));
  device.pressBack();
  main(()->context.startService(new Intent(context,MonitoringService.class).setAction(MonitoringService.ACTION_RESUME)));
  Thread.sleep(400);assertTrue(p.getBoolean("v108_emergency_latched",false));assertFalse(p.getBoolean("auto_trading",true));
  context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(200);
  main(()->context.startService(new Intent(context,MonitoringService.class).setAction(MonitoringService.ACTION_RESUME)));
  Thread.sleep(400);assertTrue(p.getBoolean("v108_emergency_latched",false));assertFalse(p.getBoolean("auto_trading",true));screenshot("04-emergency");
 }
 @After public void cleanup()throws Exception{p.edit().putBoolean("bg_running",false).commit();context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(200);}
 static class Fixture {
  static String body(URL url){try{
   String path=url.getPath();JSONObject j=new JSONObject().put("ok",true).put("accepted",false).put("message","Test fixture; no orders sent");
   if(path.contains("time_series")){JSONArray bars=new JSONArray();for(int i=150;i>=1;i--){double c=1.1605+Math.sin(i*.28)*.00015;bars.put(new JSONObject().put("open",c-.00002).put("high",c+.00008).put("low",c-.00007).put("close",c));}return new JSONObject().put("values",bars).toString();}
   if(path.endsWith("health"))return j.put("mt5_connected",true).put("account_type","DEMO").put("bridge_version","10.0").put("real_trading_enabled",false).put("balance",99868.35).put("equity",99868.35).put("currency","USD").put("positions",0).put("floating_pl",0).toString();
   if(path.endsWith("quote"))return j.put("bid",1.16051).put("ask",1.16052).toString();
   if(path.endsWith("risk-state"))return j.put("allowed",false).put("blocks",new JSONArray().put("LOSS_STREAK")).put("consecutive_losses",3).toString();
   if(path.endsWith("positions"))return j.put("positions",new JSONArray()).put("floating_pl",0).toString();
   if(path.endsWith("trade-ledger"))return j.put("trades",new JSONArray()).put("summary",new JSONObject()).toString();
   return j.toString();
  }catch(Exception e){throw new RuntimeException(e);}}
 }
}
