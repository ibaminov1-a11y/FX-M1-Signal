package com.openai.fxm1;
import android.content.*;
import android.os.*;
import android.text.*;
import android.view.*;
import android.widget.TextView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.UiDevice;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class R75PageUiTest {
 @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
 Context ctx;UiDevice device;final String base="http://127.0.0.1:8765";
 void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
 void sync()throws Exception{Method m=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");m.setAccessible(true);ui(()->{try{m.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}});}
 TextView text(String name)throws Exception{Field f=MainActivity.class.getDeclaredField(name);f.setAccessible(true);return (TextView)f.get(rule.getActivity());}
 @Before public void start()throws Exception{
  ctx=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.wakeUp();device.pressHome();
  ctx.stopService(new Intent(ctx,MonitoringService.class));
  ctx.getSharedPreferences("fxm1",0).edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
   .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url",base).putString("ec_client_id","r75-page")
   .putString("target_trade_mode","DEMO").putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("entry_tf_name","M5").putString("ec_lot_cap","0.01").commit();
  EventClient.init(ctx);EventClient.http("POST",base+"/test/reset",new JSONObject());
  EventClient.http("POST",base+"/test/r732-pattern",new JSONObject().put("index",17).put("view","live").put("position",false));
  EventClient.poll();rule.launchActivity(new Intent());sync();
 }
 @After public void stop()throws Exception{
  ctx.stopService(new Intent(ctx,MonitoringService.class));ui(()->rule.getActivity().finish());
  EventClient.http("POST",base+"/test/reset",new JSONObject());
 }
 @Test public void identicalStateDoesNotReassignPersistentTexts()throws Exception{
  ctx.getSharedPreferences("fxm1",0).edit().putString("ec_journal_snapshot","R75 frozen journal").commit();sync();
  AtomicInteger changes=new AtomicInteger();List<TextView> views=new ArrayList<>();
  for(String name:new String[]{"journalText","levelsText","contextText","componentScoresText","signalText","analyzeButton"})views.add(text(name));
  TextWatcher observer=new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int c,int f){} public void onTextChanged(CharSequence s,int a,int b,int c){changes.incrementAndGet();}public void afterTextChanged(Editable e){}};
  ui(()->{for(TextView v:views)v.addTextChangedListener(observer);});
  try{for(int i=0;i<5;i++)sync();assertEquals("UNCHANGED_PAGE_FORCES_RELAYOUT",0,changes.get());}
  finally{ui(()->{for(TextView v:views)v.removeTextChangedListener(observer);});}
 }
 @Test public void wholePageScrollRecordsFrameTimingWithoutTradingCommands()throws Exception{
  List<Long> frames=Collections.synchronizedList(new ArrayList<>());
  HandlerThread thread=new HandlerThread("r75-frame-observer");thread.start();
  Window.OnFrameMetricsAvailableListener listener=(window,metrics,dropped)->{
   if(metrics.getMetric(FrameMetrics.FIRST_DRAW_FRAME)==0)frames.add(metrics.getMetric(FrameMetrics.TOTAL_DURATION));
  };
  ui(()->rule.getActivity().getWindow().addOnFrameMetricsAvailableListener(listener,new Handler(thread.getLooper())));
  long started=SystemClock.elapsedRealtime();
  try{
   int w=device.getDisplayWidth(),h=device.getDisplayHeight();
   for(int i=0;i<20;i++){
    // Right margin avoids horizontal chart gesture capture; actual vertical page.
    device.swipe(w-16,i%2==0?h*4/5:h/4,w-16,i%2==0?h/4:h*4/5,30);
    if(i%4==0){EventClient.poll();sync();}
   }
  }finally{ui(()->rule.getActivity().getWindow().removeOnFrameMetricsAvailableListener(listener));thread.quitSafely();thread.join(2000);}
  List<Long> sorted=new ArrayList<>(frames);Collections.sort(sorted);assertTrue("No rendered page frames captured",sorted.size()>30);
  long over=0;for(long n:sorted)if(n>16666667L)over++;
  int code=ctx.getPackageManager().getPackageInfo(ctx.getPackageName(),0).versionCode;
  JSONObject report=new JSONObject().put("version_code",code).put("frames",sorted.size()).put("over_16_67_ms",over)
   .put("p50_ms",sorted.get(sorted.size()/2)/1e6).put("p95_ms",sorted.get((int)(sorted.size()*.95))/1e6)
   .put("elapsed_ms",SystemClock.elapsedRealtime()-started).put("synthetic_market",true).put("physical_phone_tested",false);
  File file=new File(ctx.getExternalFilesDir(null),"r75-page-metrics-"+code+".json");try(FileWriter out=new FileWriter(file)){out.write(report.toString(2));}
  device.executeShellCommand("mkdir -p /sdcard/Download/ec1-qa");
  device.executeShellCommand("cp "+file.getAbsolutePath()+" /sdcard/Download/ec1-qa/"+file.getName());
  ui(()->((android.widget.ScrollView)rule.getActivity().findViewById(R.id.rootLayout)).scrollTo(0,0));device.waitForIdle();
  device.takeScreenshot(new File("/sdcard/Download/ec1-qa/r75-page-"+code+".png"));
  assertFalse("Scroll cannot arm AUTO",EventClient.state().optBoolean("auto"));
 }
}
