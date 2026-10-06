package com.openai.fxm1;

import android.content.*;
import android.graphics.*;
import android.os.*;
import android.text.*;
import android.view.*;
import android.widget.*;
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
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.Assert.*;

/** Native user page scroll and repeated repaint of the actual R7.4 screen. */
@RunWith(AndroidJUnit4.class)
public class R741ScrollUiTest {
 @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
 private Context ctx;private UiDevice device;private static final String BASE="http://127.0.0.1:8765";
 private void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
 private void sync(){try{Method m=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");m.setAccessible(true);m.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}}
 private void suspendTimers(){ui(()->{try{for(String name:new String[]{"serviceUiHandler","monitorHandler"}){Field f=MainActivity.class.getDeclaredField(name);f.setAccessible(true);((Handler)f.get(rule.getActivity())).removeCallbacksAndMessages(null);}ScenarioUi.setActive(rule.getActivity(),false);}catch(Exception e){throw new AssertionError(e);}});}
 @Before public void start()throws Exception{
  ctx=InstrumentationRegistry.getInstrumentation().getTargetContext();device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.wakeUp();
  ctx.stopService(new Intent(ctx,MonitoringService.class));
  ctx.getSharedPreferences("fxm1",0).edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
   .putBoolean("ec1_r2_risk_migrated",true).putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url",BASE).putString("ec_client_id","r741-scroll")
   .putString("target_trade_mode","DEMO").putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("entry_tf_name","M5").putString("ec_lot_cap","0.01").commit();
  ctx.getSharedPreferences("fxm1_chart_v1",0).edit().clear().commit();
  EventClient.init(ctx);EventClient.http("POST",BASE+"/test/reset",new JSONObject());
  EventClient.http("POST",BASE+"/test/r732-pattern",new JSONObject().put("index",17).put("view","live").put("position",true));EventClient.poll();
  rule.launchActivity(new Intent());ui(this::sync);InstrumentationRegistry.getInstrumentation().waitForIdleSync();
 }
 @After public void stop()throws Exception{ctx.stopService(new Intent(ctx,MonitoringService.class));if(rule.getActivity()!=null)rule.finishActivity();EventClient.http("POST",BASE+"/test/reset",new JSONObject());}
 static final class CountingForecast extends JSONObject {
  int serializations;
  CountingForecast(String s)throws JSONException{super(s);}
  @Override public String toString(){serializations++;return super.toString();}
 }
 @Test public void redrawDoesNotSerializeUnchangedForecast()throws Exception{
  suspendTimers();final JSONObject state=EventClient.state();
  ui(()->{Bitmap b=Bitmap.createBitmap(700,950,Bitmap.Config.ARGB_8888);try{
   SparklineView chart=new SparklineView(ctx);chart.layout(0,0,700,950);ScenarioUi.populate(chart,state);
   Field f=SparklineView.class.getDeclaredField("forecast");f.setAccessible(true);
   CountingForecast counted=new CountingForecast(((JSONObject)f.get(chart)).toString());
   chart.setMarket(state.optJSONArray("bars"),null,state.optJSONArray("positions"),null,"SCENARIO_V2",state.optJSONObject("live_bar"),null,counted);
   chart.draw(new Canvas(b));counted.serializations=0;
   for(int i=0;i<10;i++)chart.draw(new Canvas(b));
   assertEquals("REPEATED_DRAW_SERIALIZES_FORECAST",0,counted.serializations);
  }catch(Exception e){throw new AssertionError(e);}finally{b.recycle();}});
 }
 @Test public void onePassivePageRefreshUsesOneStateDecode()throws Exception{
  suspendTimers();Field f=EventClient.class.getDeclaredField("app");f.setAccessible(true);Context original=(Context)f.get(null);
  AtomicInteger reads=new AtomicInteger();SharedPreferences real=original.getSharedPreferences("fxm1",0);
  SharedPreferences counted=(SharedPreferences)java.lang.reflect.Proxy.newProxyInstance(SharedPreferences.class.getClassLoader(),new Class<?>[]{SharedPreferences.class},(p,m,args)->{
   if(m.getName().equals("getString")&&args!=null&&"ec_state".equals(args[0])&&Looper.myLooper()==Looper.getMainLooper())reads.incrementAndGet();
   try{return m.invoke(real,args);}catch(InvocationTargetException e){throw e.getCause();}
  });
  Context wrapper=new ContextWrapper(original){@Override public SharedPreferences getSharedPreferences(String name,int mode){return name.equals("fxm1")?counted:super.getSharedPreferences(name,mode);}};
  ui(()->{try{f.set(null,wrapper);reads.set(0);sync();assertEquals("PAGE_REPARSES_STATE_PER_WIDGET",1,reads.get());}catch(IllegalAccessException e){throw new AssertionError(e);}finally{try{f.set(null,original);}catch(Exception e){throw new AssertionError(e);}}});
 }
 @Test public void identicalSnapshotDoesNotReplaceEntryTextTwice()throws Exception{
  suspendTimers();ui(()->{sync();TextView levels=rule.getActivity().findViewById(R.id.levelsText);String before=levels.getText().toString();AtomicInteger writes=new AtomicInteger();
   TextWatcher watcher=new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int count,int after){}public void onTextChanged(CharSequence s,int st,int before,int count){writes.incrementAndGet();}public void afterTextChanged(Editable e){}};
   levels.addTextChangedListener(watcher);try{sync();assertEquals(before,levels.getText().toString());assertEquals("UNCHANGED_PLAN_TEXT_REPLACED_TWICE",0,writes.get());}finally{levels.removeTextChangedListener(watcher);}});
 }
 @Test public void measureWholePageScrollWithLiveUpdates()throws Exception{
  String version=ctx.getPackageManager().getPackageInfo(ctx.getPackageName(),0).versionName;
  List<Long> frames=Collections.synchronizedList(new ArrayList<>());List<Long> uiTimes=Collections.synchronizedList(new ArrayList<>());AtomicInteger dropped=new AtomicInteger(),polls=new AtomicInteger();
  HandlerThread metrics=new HandlerThread("r741-frame-metrics");metrics.start();
  Window.OnFrameMetricsAvailableListener listener=(w,f,n)->{frames.add(f.getMetric(FrameMetrics.TOTAL_DURATION));uiTimes.add(f.getMetric(FrameMetrics.DRAW_DURATION)+f.getMetric(FrameMetrics.LAYOUT_MEASURE_DURATION));dropped.addAndGet(n);};
  ui(()->rule.getActivity().getWindow().addOnFrameMetricsAvailableListener(listener,new Handler(metrics.getLooper())));
  ScheduledExecutorService updates=Executors.newSingleThreadScheduledExecutor();
  updates.scheduleWithFixedDelay(()->{try{EventClient.poll();polls.incrementAndGet();}catch(Exception ignored){}},0,1,TimeUnit.SECONDS);
  int[] ys=new int[2];int[] points=new int[4];
  try{
   ui(()->{LiveScrollView root=rule.getActivity().findViewById(R.id.rootLayout);root.scrollTo(0,300);ys[0]=root.getScrollY();int[] xy=new int[2];root.getLocationOnScreen(xy);points[0]=xy[0]+root.getWidth()-15;points[1]=xy[1]+root.getHeight()*4/5;points[2]=xy[1]+root.getHeight()/4;});
   Thread.sleep(700);frames.clear();uiTimes.clear();
   for(int i=0;i<8;i++){assertTrue(device.swipe(points[0],points[1],points[0],points[2],60));Thread.sleep(120);}
   ui(()->ys[1]=((LiveScrollView)rule.getActivity().findViewById(R.id.rootLayout)).getScrollY());assertTrue("Actual page did not scroll",ys[1]>ys[0]+100);
   for(int i=0;i<8;i++){assertTrue(device.swipe(points[0],points[2],points[0],points[1],60));Thread.sleep(120);}
   assertTrue("No incoming data during measurement",polls.get()>=3);assertTrue("No native frame samples",frames.size()>60);
  }finally{updates.shutdownNow();ui(()->rule.getActivity().getWindow().removeOnFrameMetricsAvailableListener(listener));metrics.quitSafely();metrics.join(2000);}
  JSONArray totals=new JSONArray(),uiSamples=new JSONArray();synchronized(frames){for(long n:frames)totals.put(n);}synchronized(uiTimes){for(long n:uiTimes)uiSamples.put(n);}
  JSONObject result=new JSONObject().put("version",version).put("frames_ns",totals).put("layout_draw_ns",uiSamples).put("dropped_metric_callbacks",dropped.get()).put("polls",polls.get()).put("start_y",ys[0]).put("max_y",ys[1]).put("fixture","actual HTTP fixture head-and-shoulders + position; emulator, not user phone");
  File out=new File(ctx.getExternalFilesDir(null),"scroll-"+version+".json");try(FileOutputStream stream=new FileOutputStream(out)){stream.write(result.toString().getBytes("UTF-8"));}
  device.executeShellCommand("mkdir -p /sdcard/Download/ec1-qa");device.executeShellCommand("cp "+out.getAbsolutePath()+" /sdcard/Download/ec1-qa/");
  assertFalse("Scrolling cannot arm trading",EventClient.state().optBoolean("auto"));
 }
}
