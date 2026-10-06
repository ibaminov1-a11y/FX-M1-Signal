package com.openai.fxm1;
import android.content.Context;
import android.content.Intent;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.*;
import org.junit.runner.RunWith;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.Assert.*;
/** Real client HTTP, delayed receipts; no calls to MT5. */
@RunWith(AndroidJUnit4.class)
public class R74ControlUiTest {
 static class Receipts implements AutoCloseable {
  final ServerSocket server=new ServerSocket(0);final AtomicInteger posts=new AtomicInteger(),gets=new AtomicInteger();
  volatile boolean open=true;volatile String result="APPLIED",id="",account="",protocol="";
  Receipts()throws Exception {new Thread(()->{while(open)try{serve(server.accept());}catch(Exception e){if(open)throw new AssertionError(e);}}).start();}
  String base(){return "http://127.0.0.1:"+server.getLocalPort();}
  void serve(Socket socket)throws Exception {try(Socket s=socket){
   BufferedReader r=new BufferedReader(new InputStreamReader(s.getInputStream(),StandardCharsets.UTF_8));
   String first=r.readLine(),line;int size=0;
   while((line=r.readLine())!=null&&!line.isEmpty()){
    if(line.toLowerCase().startsWith("content-length:"))size=Integer.parseInt(line.substring(15).trim());
    if(line.toLowerCase().startsWith("x-fxm1-control:"))protocol=line.substring(15).trim();
   }
   char[] body=new char[size];for(int n=0;n<size;){int got=r.read(body,n,size-n);if(got<0)break;n+=got;}
   boolean post=first.startsWith("POST");String status;
   if(post){posts.incrementAndGet();JSONObject b=new JSONObject(new String(body));id=b.getString("command_id");account=b.optString("account_key");status="QUEUED";}
   else{status=gets.incrementAndGet()<3?"QUEUED":result;assertTrue(first.contains("/ec/commands/"+id));}
   JSONObject response=new JSONObject().put("ok",!status.equals("REJECTED")).put("accepted",true).put("applied",status.equals("APPLIED"))
    .put("command_status",status).put("command_id",id).put("message",status.equals("REJECTED")?"ACCOUNT_CHANGED":"received, not a fill");
   byte[] data=response.toString().getBytes(StandardCharsets.UTF_8);OutputStream o=s.getOutputStream();
   o.write(("HTTP/1.1 "+(post?"202 Accepted":"200 OK")+"\r\nContent-Type: application/json\r\nContent-Length: "+data.length+"\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));o.write(data);o.flush();
  }}
  public void close()throws Exception {open=false;server.close();}
 }
 Context context;
 @Before public void setup(){context=InstrumentationRegistry.getInstrumentation().getTargetContext();context.stopService(new Intent(context,MonitoringService.class));EventClient.init(context);}
 void configure(Receipts server)throws Exception {
  EventClient.prefs().edit().clear().putString("server_url",server.base()).putString("ec_token","r74-dummy-token")
   .putString("ec_client_id","r74-native-client").putBoolean("ec1_migrated",true).putBoolean("ec1_r2_risk_migrated",true).commit();
  JSONObject f=new JSONObject().put("protocol",EventClient.PROTOCOL).put("profile_id","profile-A")
   .put("account",new JSONObject().put("key","123@DEMO").put("type","DEMO")).put("account_age",0)
   .put("config",new JSONObject().put("mode","NORMAL").put("timeframe","M5"))
   .put("capabilities",new JSONObject().put("profile_registry",true).put("queued_controls",true));
  EventClient.cache(f);
 }
 @Test public void queuedReceiptIsNotAppliedUntilSameIdTerminalPoll()throws Exception {
  try(Receipts server=new Receipts()){configure(server);
   JSONObject r=EventClient.command("pause",new JSONObject());
   assertEquals("QUEUED_RECEIPT_IS_NOT_APPLIED","APPLIED",r.optString("command_status"));
   assertEquals(1,server.posts.get());assertEquals(3,server.gets.get());
   assertEquals("queued-v1",server.protocol);assertEquals("123@DEMO",server.account);
  }
 }
 @Test public void rejectedQueuedControlCannotBeReportedAsSuccess()throws Exception {
  try(Receipts server=new Receipts()){configure(server);server.result="REJECTED";
   try{EventClient.command("pause",new JSONObject());fail("REJECTED_RECEIPT_REPORTED_SUCCESS");}
   catch(IOException e){assertTrue(e.getMessage(),e.getMessage().contains("ACCOUNT_CHANGED"));}
   assertEquals(1,server.posts.get());
  }
 }
 @Test public void emergencyWaitsForAppliedAndKeepsProtectiveLatch()throws Exception {
  try(Receipts server=new Receipts()){configure(server);
   JSONObject r=EventClient.sendCommand(EventClient.beginEmergency());
   assertEquals("EMERGENCY_RECEIPT_NOT_APPLICATION","APPLIED",r.optString("command_status"));
   assertFalse(EventClient.prefs().getBoolean("ec_emergency_uncertain",true));
   assertTrue("Emergency protection remains until explicit reset",EventClient.prefs().getBoolean("v108_emergency_latched",false));
   assertEquals(1,server.posts.get());
  }
 }
 @Test public void stableEntryDisplaysFixedLevelsInsteadOfInventedImpulse()throws Exception {
  JSONObject state=new JSONObject().put("config",new JSONObject().put("mode","NORMAL").put("timeframe","M5").put("entry_model","STABLE_V1"))
   .put("forecast",new JSONObject().put("timeframe","M5").put("execution_setup",new JSONObject().put("engine","STABLE_V1").put("stage","TOUCH_SEEN")
    .put("side",1).put("trigger",1.22345).put("invalidation",1.22310).put("target1",1.22450).put("expires_at",1800000000).put("reason","Ждём возврат выше уровня")));
  String text=ScenarioUi.executionRequirement(state);
  assertTrue("STABLE_PLAN_LEVELS_NOT_VISIBLE: "+text,text.contains("1.22345")&&text.contains("1.22310")&&text.contains("1.22450"));
  assertFalse(text,text.contains("Импульс наблюдается"));
 }
}
