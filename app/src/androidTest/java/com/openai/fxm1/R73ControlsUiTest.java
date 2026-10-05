package com.openai.fxm1;

import android.content.*;
import android.os.SystemClock;
import android.widget.Switch;
import android.widget.TextView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.lang.reflect.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

/** Native controls, real HTTP and deliberately held work reproduce R7.3 races. */
@RunWith(AndroidJUnit4.class)
public class R73ControlsUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context; SharedPreferences prefs;
    /** Real loopback transport: drops a packet after receipt to model an unknown command result. */
    static final class TransportServer implements AutoCloseable {
        final ServerSocket socket=new ServerSocket(0,16,InetAddress.getByName("127.0.0.1"));
        final ExecutorService workers=Executors.newCachedThreadPool();
        final List<String> emergencyBodies=Collections.synchronizedList(new ArrayList<>());
        final CountDownLatch emergencyReceived=new CountDownLatch(1),releaseEmergency=new CountDownLatch(1);
        final String state;
        volatile boolean running=true,dropEmergency=false,holdEmergency=false,failState=false,busyState=false;
        volatile int resets;
        TransportServer(JSONObject snapshot)throws Exception{state=snapshot.toString();workers.execute(()->{while(running)try{
            Socket accepted=socket.accept();workers.execute(()->reply(accepted));
        }catch(IOException e){if(running)throw new AssertionError(e);}});}
        String base(){return "http://127.0.0.1:"+socket.getLocalPort();}
        void reply(Socket client){try(Socket connection=client){
            connection.setSoTimeout(5000);BufferedReader reader=new BufferedReader(new InputStreamReader(connection.getInputStream(),StandardCharsets.UTF_8));
            String first=reader.readLine();if(first==null)return;int length=0;String header;
            while((header=reader.readLine())!=null&&!header.isEmpty())if(header.toLowerCase(Locale.US).startsWith("content-length:"))length=Integer.parseInt(header.substring(15).trim());
            char[] body=new char[length];int read=0;while(read<length){int count=reader.read(body,read,length-read);if(count<0)break;read+=count;}
            int status=200;String response="{\"ok\":true,\"auto\":false,\"paused\":true,\"emergency\":false,\"trades\":[],\"history_time\":0}";
            if(first.contains("/ec/command/emergency")){emergencyBodies.add(new String(body));emergencyReceived.countDown();if(holdEmergency)releaseEmergency.await(5,TimeUnit.SECONDS);if(dropEmergency)return;}
            if(first.contains("/ec/command/reset"))resets++;
            if(first.contains("/ec/state")){if(failState)return;response=state;if(busyState){status=503;response="{\"message\":\"Bridge busy\",\"server_connected\":true,\"runtime_busy\":true,\"accepted\":false}";}}
            byte[] data=response.getBytes(StandardCharsets.UTF_8);OutputStream out=connection.getOutputStream();
            out.write(("HTTP/1.1 "+status+" "+(status==200?"OK":"Service Unavailable")+"\r\nContent-Type: application/json\r\nContent-Length: "+data.length+"\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));out.write(data);out.flush();
        }catch(Exception ignored){}}
        public void close()throws Exception{running=false;releaseEmergency.countDown();socket.close();workers.shutdownNow();}
    }
    void ui(Runnable action){InstrumentationRegistry.getInstrumentation().runOnMainSync(action);}
    void await(BooleanSupplier condition,long timeout,String message)throws Exception{
        long end=SystemClock.elapsedRealtime()+timeout;
        while(SystemClock.elapsedRealtime()<end){if(condition.getAsBoolean())return;Thread.sleep(25);}fail(message);
    }
    JSONObject fixture(String method,String path,JSONObject body)throws Exception{return EventClient.http(method,EventClient.base()+path,body);}
    void invoke(String name,Class<?>[] types,Object... values){
        try{Method method=MainActivity.class.getDeclaredMethod(name,types);method.setAccessible(true);method.invoke(rule.getActivity(),values);}
        catch(Exception e){throw new AssertionError(e);}
    }
    void sync(){ui(()->invoke("restoreTradingSnapshotFromPrefs",new Class<?>[]{}));}
    ExecutorService queue(String preferred)throws Exception{
        Field field;try{field=MainActivity.class.getDeclaredField(preferred);}catch(NoSuchFieldException e){field=MainActivity.class.getDeclaredField("executor");}
        field.setAccessible(true);return (ExecutorService)field.get(rule.getActivity());
    }
    void command(String name){ui(()->invoke("eventCommand",new Class<?>[]{String.class,JSONObject.class},name,new JSONObject()));}
    int audit(){try{return fixture("GET","/test/r53-command-audit",null).getJSONArray("commands").length();}catch(Exception e){throw new AssertionError(e);}}
    @Before public void setup()throws Exception{
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();context.stopService(new Intent(context,MonitoringService.class));
        prefs=context.getSharedPreferences("fxm1",Context.MODE_PRIVATE);
        prefs.edit().clear().putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","r73-controls").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).putString("ec_lot_cap","0.01").commit();
        EventClient.init(context);fixture("POST","/test/reset",new JSONObject());EventClient.poll();
        rule.launchActivity(new Intent());InstrumentationRegistry.getInstrumentation().waitForIdleSync();
    }
    @After public void stop()throws Exception{
        fixture("POST","/test/r56-read-release",new JSONObject());context.stopService(new Intent(context,MonitoringService.class));
        if(rule.getActivity()!=null)rule.finishActivity();
    }
    @Test public void reachableBridgeWithStaleMt5DoesNotBecomePhoneOffline()throws Exception{
        JSONObject snapshot=EventClient.state();snapshot.put("account_age",60);EventClient.cache(snapshot);sync();
        assertTrue("Successful Bridge response proves transport reachability",prefs.getBoolean("server_verified",false));
        assertFalse("Stale MT5 account must stay independently unavailable",prefs.getBoolean("mt5_connected_snapshot",true));
        assertFalse("MT5 unavailability is not phone offline",EventClient.state().optBoolean("client_offline"));
        ui(()->assertTrue(((TextView)rule.getActivity().findViewById(R.id.serverStatusText)).getText().toString().contains("SERVER: CONNECTED")));
    }
    @Test public void commandDoesNotWaitBehindMoneyRead()throws Exception{
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        queue("executor").execute(()->{entered.countDown();try{release.await();}catch(InterruptedException ignored){}});
        assertTrue(entered.await(2,TimeUnit.SECONDS));int before=audit();
        try{command("disable");await(()->audit()>before,1500,"DISABLE must reach Bridge while history work is held");}
        finally{release.countDown();}
    }
    @Test public void queuedCommandCannotMoveToChangedServer()throws Exception{
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        ExecutorService commands=queue("commandExecutor");
        commands.execute(()->{entered.countDown();try{release.await();}catch(InterruptedException ignored){}});
        assertTrue(entered.await(2,TimeUnit.SECONDS));int before=audit();
        try{
            command("disable");prefs.edit().putString("server_url","http://localhost:8765").commit();release.countDown();
            commands.submit(()->{}).get(5,TimeUnit.SECONDS);
            assertEquals("A queued command belongs to the source at the tap; never retarget it",before,audit());
        }finally{release.countDown();prefs.edit().putString("server_url","http://127.0.0.1:8765").commit();}
    }
    @Test public void pendingDisableKeepsConfirmedSwitchAndBlocksDuplicateTap()throws Exception{
        fixture("POST","/test/r55-controls",new JSONObject().put("auto",true).put("campaign",false).put("quote_future",false));EventClient.poll();sync();
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        queue("commandExecutor").execute(()->{entered.countDown();try{release.await();}catch(InterruptedException ignored){}});
        assertTrue(entered.await(2,TimeUnit.SECONDS));
        try{ui(()->{Switch control=rule.getActivity().findViewById(R.id.autoTradingSwitch);assertTrue(control.isChecked());control.performClick();
            assertTrue("Confirmed AUTO stays ON until Bridge acknowledges DISABLE",control.isChecked());
            assertFalse("A pending command cannot be sent twice",control.isEnabled());
            assertTrue(((TextView)rule.getActivity().findViewById(R.id.autoStatusText)).getText().toString().contains("Ожидается"));});}
        finally{release.countDown();}
    }
    @Test public void acceptedDisableRejectsOlderAutoSnapshot()throws Exception{
        fixture("POST","/test/r55-controls",new JSONObject().put("auto",true).put("campaign",false));EventClient.poll();
        fixture("POST","/test/r56-read-hold",new JSONObject().put("hold",true));
        ExecutorService reads=Executors.newSingleThreadExecutor();Future<JSONObject> old=reads.submit(EventClient::poll);
        try{
            await(()->{try{return fixture("GET","/test/r56-read-hold",null).optBoolean("captured");}catch(Exception e){throw new AssertionError(e);}},2500,"AUTO ON snapshot is held");
            EventClient.command("disable",new JSONObject());EventClient.poll();
            fixture("POST","/test/r56-read-release",new JSONObject());old.get(4,TimeUnit.SECONDS);
            assertFalse("Old AUTO ON response cannot replace confirmed disable",EventClient.state().optBoolean("auto",true));
        }finally{fixture("POST","/test/r56-read-release",new JSONObject());old.cancel(true);reads.shutdownNow();}
    }
    @Test public void emergencyReachesBridgeWhileServiceReadIsHeld()throws Exception{
        EventClient.configure();fixture("POST","/test/r56-read-hold",new JSONObject().put("hold",true));
        ui(()->context.startForegroundService(new Intent(context,MonitoringService.class).setAction(MonitoringService.ACTION_START)));
        await(()->{try{return fixture("GET","/test/r56-read-hold",null).optBoolean("captured");}catch(Exception e){throw new AssertionError(e);}},3000,"Service read is held");
        try{
            ui(()->context.startForegroundService(new Intent(context,MonitoringService.class).setAction(MonitoringService.ACTION_EMERGENCY_CONFIRMED)));
            await(()->{try{return fixture("GET","/ec/state",null).optBoolean("emergency");}catch(Exception e){throw new AssertionError(e);}},1500,"Emergency must bypass held poll/configure work");
        }finally{fixture("POST","/test/r56-read-release",new JSONObject());}
    }
    @Test public void offlineFinancialCardExplicitlyLabelsCachedNumbers()throws Exception{
        EventClient.offline(new java.io.IOException("test offline"));sync();
        ui(()->{
            String account=((TextView)rule.getActivity().findViewById(R.id.accountText)).getText().toString();
            String positions=((TextView)rule.getActivity().findViewById(R.id.positionsText)).getText().toString();
            assertTrue("Account snapshot needs cache label: "+account,account.contains("КЭШ"));
            assertTrue("Positions snapshot needs cache label: "+positions,positions.contains("КЭШ"));
        });
    }
    @Test public void queuedCommandCannotMoveToChangedProfile()throws Exception{
        JSONObject original=EventClient.state().put("profile_id","profile-A").put("capabilities",new JSONObject().put("profile_registry",true));
        EventClient.cache(original);
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);ExecutorService commands=queue("commandExecutor");
        commands.execute(()->{entered.countDown();try{release.await();}catch(InterruptedException ignored){}});
        assertTrue(entered.await(2,TimeUnit.SECONDS));int before=audit();
        try{
            command("disable");EventClient.cache(new JSONObject(original.toString()).put("profile_id","profile-B"));release.countDown();
            commands.submit(()->{}).get(5,TimeUnit.SECONDS);
            assertEquals("An obsolete profile command cannot act on a newer selected profile",before,audit());
        }finally{release.countDown();}
    }
    @Test public void emergencyRetryRetainsIdentityAndResetCancelsOldRetry()throws Exception{
        EventClient.CommandRequest original=EventClient.beginEmergency();EventClient.sendCommand(original);
        prefs.edit().putBoolean("ec_emergency_pending",true).commit();
        EventClient.CommandRequest retry=EventClient.pendingEmergency();EventClient.sendCommand(retry);
        JSONArray commands=fixture("GET","/test/r53-command-audit",null).getJSONArray("commands");
        JSONObject first=commands.getJSONObject(commands.length()-2).getJSONObject("body"),second=commands.getJSONObject(commands.length()-1).getJSONObject("body");
        assertEquals("Retry must reuse the deduplication identity",first.getString("command_id"),second.getString("command_id"));
        assertEquals(first.getLong("sequence"),second.getLong("sequence"));
        assertFalse("Emergency is account-wide, never narrowed to selected instrument",first.has("profile_id"));
        EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));int count=audit();
        try{EventClient.sendCommand(retry);fail("Accepted reset must invalidate an older emergency task");}catch(java.io.IOException expected){}
        assertEquals(count,audit());assertFalse(prefs.getBoolean("ec_emergency_pending",true));assertFalse(prefs.getBoolean("v108_emergency_latched",true));
    }
    @Test public void pollingNeverReplaysLegacyPauseOrUnsentProfileSelection()throws Exception{
        EventClient.rememberProfileSelection("GBP/USD",2,1,0);prefs.edit().putBoolean("ec_mode_pause_pending",true).commit();int before=audit();
        EventClient.poll();assertEquals("A read after reconnection cannot become an old command",before,audit());
        assertTrue(EventClient.hasProfileDraft());assertEquals("GBP/USD",prefs.getString("selected_symbol",""));
    }
    @Test public void legacyEmergencyFlagCannotAcquireANewDestinationOnRestart()throws Exception{
        prefs.edit().putBoolean("ec_emergency_pending",true).putBoolean("v108_emergency_latched",true).remove("ec_emergency_request").commit();
        int before=audit();
        try{EventClient.pendingEmergency();fail("A legacy retry without recorded source needs a new explicit emergency action");}
        catch(java.io.IOException expected){}
        assertEquals(before,audit());assertFalse(prefs.contains("ec_emergency_request"));
        assertTrue(prefs.getBoolean("v108_emergency_latched",false));assertTrue(prefs.getBoolean("ec_emergency_pending",false));
    }
    @Test public void emergencyRetryCapturedAfterResetPreparationCannotRunAfterAcceptedReset()throws Exception{
        EventClient.beginEmergency();
        EventClient.CommandRequest reset=EventClient.prepareCommand("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));
        EventClient.CommandRequest retry=EventClient.pendingEmergency();
        EventClient.sendCommand(reset);int before=audit();
        try{EventClient.sendCommand(retry);fail("A retry captured with reset's generation must still require the persisted pending identity");}
        catch(IOException expected){}
        assertEquals(before,audit());assertFalse(prefs.getBoolean("v108_emergency_latched",true));
    }
    @Test public void uncertainEmergencyBlocksResetUntilSameIdentityIsAcknowledged()throws Exception{
        JSONObject snapshot=EventClient.state();String source=EventClient.base();
        try(TransportServer transport=new TransportServer(snapshot)){
            prefs.edit().putString("server_url",transport.base()).commit();EventClient.cache(snapshot);
            transport.dropEmergency=true;EventClient.CommandRequest first=EventClient.beginEmergency();
            try{EventClient.sendCommand(first);fail("Dropped HTTP response must remain unconfirmed");}catch(IOException expected){}
            assertTrue(prefs.getBoolean("ec_emergency_uncertain",false));
            try{EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));fail("Reset cannot overtake an uncertain emergency");}
            catch(IOException expected){assertTrue(expected.getMessage().contains("EMERGENCY"));}
            assertEquals(0,transport.resets);
            transport.dropEmergency=false;EventClient.sendCommand(EventClient.pendingEmergency());
            assertFalse(prefs.getBoolean("ec_emergency_uncertain",true));assertFalse(prefs.getBoolean("ec_emergency_pending",true));
            assertEquals(new JSONObject(transport.emergencyBodies.get(0)).getString("command_id"),new JSONObject(transport.emergencyBodies.get(transport.emergencyBodies.size()-1)).getString("command_id"));
            EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));assertEquals(1,transport.resets);
        }finally{prefs.edit().putString("server_url",source).commit();}
    }
    @Test public void resetWaitsForInFlightEmergencyAcknowledgement()throws Exception{
        JSONObject snapshot=EventClient.state();String source=EventClient.base();ExecutorService tasks=Executors.newFixedThreadPool(2);
        try(TransportServer transport=new TransportServer(snapshot)){
            prefs.edit().putString("server_url",transport.base()).commit();EventClient.cache(snapshot);transport.holdEmergency=true;
            EventClient.CommandRequest emergency=EventClient.beginEmergency();Future<?> sent=tasks.submit(()->{EventClient.sendCommand(emergency);return null;});
            assertTrue(transport.emergencyReceived.await(2,TimeUnit.SECONDS));
            EventClient.CommandRequest reset=EventClient.prepareCommand("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));
            Future<?> reconciliation=tasks.submit(()->{EventClient.sendCommand(reset);return null;});
            try{reconciliation.get(200,TimeUnit.MILLISECONDS);fail("Reset must wait for emergency acknowledgement");}catch(TimeoutException expected){}
            assertEquals(0,transport.resets);transport.releaseEmergency.countDown();sent.get(3,TimeUnit.SECONDS);reconciliation.get(3,TimeUnit.SECONDS);
            assertEquals(1,transport.resets);assertFalse(prefs.getBoolean("v108_emergency_latched",true));
        }finally{tasks.shutdownNow();prefs.edit().putString("server_url",source).commit();}
    }
    @Test public void stoppedServiceForegroundFailureMarksCachedFinancialStateOffline()throws Exception{
        JSONObject snapshot=EventClient.state();String source=EventClient.base();queue("executor").submit(()->{}).get(5,TimeUnit.SECONDS);
        try(TransportServer transport=new TransportServer(snapshot)){
            prefs.edit().putString("server_url",transport.base()).commit();EventClient.cache(snapshot);EventClient.poll();sync();
            assertFalse(prefs.getBoolean("bg_running",false));assertTrue(prefs.getBoolean("server_verified",false));transport.failState=true;
            ui(()->invoke("refreshStatsAndPositions",new Class<?>[]{}));
            await(()->!prefs.getBoolean("server_verified",true),4500,"Foreground financial failure must mark the current Bridge offline");
            sync();ui(()->{
                assertTrue(((TextView)rule.getActivity().findViewById(R.id.accountText)).getText().toString().contains("КЭШ"));
                assertTrue(((TextView)rule.getActivity().findViewById(R.id.positionsText)).getText().toString().contains("КЭШ"));
                assertFalse(rule.getActivity().findViewById(R.id.autoTradingSwitch).isEnabled());
            });
        }finally{prefs.edit().putString("server_url",source).commit();}
    }
    @Test public void busyBridgeRemainsReachableWhileExpiredAccountIsLabelledCached()throws Exception{
        JSONObject snapshot=EventClient.state().put("account_age",60);String source=EventClient.base();
        try(TransportServer transport=new TransportServer(snapshot)){
            prefs.edit().putString("server_url",transport.base()).commit();EventClient.cache(snapshot);transport.busyState=true;
            EventClient.ReadRequest read=EventClient.newReadRequest();
            try{EventClient.refreshFinancial(read);fail("Fixture must report the busy response");}catch(IOException expected){EventClient.offlineIfCurrent(read,expected);}
            assertTrue("HTTP busy confirms transport reachability",prefs.getBoolean("server_verified",false));
            assertFalse(EventClient.state().optBoolean("client_offline"));assertFalse(prefs.getBoolean("mt5_connected_snapshot",true));
            sync();ui(()->assertTrue(((TextView)rule.getActivity().findViewById(R.id.accountText)).getText().toString().contains("КЭШ")));
        }finally{prefs.edit().putString("server_url",source).commit();}
    }
    @Test public void explicitEmergencyOnNewBridgePreservesOldUncertainIdentityAndResetGate()throws Exception{
        JSONObject snapshot=EventClient.state();String originalSource=EventClient.base();
        try(TransportServer oldBridge=new TransportServer(snapshot);TransportServer newBridge=new TransportServer(snapshot)){
            prefs.edit().putString("server_url",oldBridge.base()).commit();EventClient.cache(snapshot);oldBridge.dropEmergency=true;
            EventClient.CommandRequest old=EventClient.beginEmergency();
            try{EventClient.sendCommand(old);fail("Old Bridge response must be uncertain");}catch(IOException expected){}
            prefs.edit().putString("server_url",newBridge.base()).commit();EventClient.cache(snapshot);
            EventClient.CommandRequest newer=EventClient.beginEmergency();EventClient.sendCommand(newer);
            assertEquals(newBridge.base(),newer.source);assertNotEquals(new JSONObject(old.payload).getString("command_id"),new JSONObject(newer.payload).getString("command_id"));
            assertEquals(1,newBridge.emergencyBodies.size());EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));assertEquals(1,newBridge.resets);
            prefs.edit().putString("server_url",oldBridge.base()).commit();EventClient.cache(snapshot);
            try{EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));fail("Returning to old source cannot lose its unresolved reset gate");}
            catch(IOException expected){assertTrue(expected.getMessage().contains("EMERGENCY"));}
            assertEquals(0,oldBridge.resets);oldBridge.dropEmergency=false;EventClient.CommandRequest retry=EventClient.beginEmergency();
            assertEquals(new JSONObject(old.payload).getString("command_id"),new JSONObject(retry.payload).getString("command_id"));
            EventClient.sendCommand(retry);EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));assertEquals(1,oldBridge.resets);
        }finally{prefs.edit().putString("server_url",originalSource).commit();}
    }
    @Test public void resettingNewBridgeDirectlyCannotDiscardOldUncertainEmergency()throws Exception{
        JSONObject snapshot=EventClient.state();String originalSource=EventClient.base();
        try(TransportServer oldBridge=new TransportServer(snapshot);TransportServer newBridge=new TransportServer(snapshot)){
            prefs.edit().putString("server_url",oldBridge.base()).commit();EventClient.cache(snapshot);oldBridge.dropEmergency=true;
            EventClient.CommandRequest old=EventClient.beginEmergency();
            try{EventClient.sendCommand(old);fail("Old response must be uncertain");}catch(IOException expected){}
            prefs.edit().putString("server_url",newBridge.base()).commit();EventClient.cache(snapshot);
            EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));assertEquals(1,newBridge.resets);
            prefs.edit().putString("server_url",oldBridge.base()).commit();EventClient.cache(snapshot);
            try{EventClient.command("enable",new JSONObject().put("confirmation","ENABLE_DEMO"));fail("Unresolved source-specific emergency must still block AUTO after another Bridge resets");}
            catch(IOException expected){assertTrue(expected.getMessage().contains("EMERGENCY"));}
            try{EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));fail("Other Bridge reset cannot erase this unresolved identity");}
            catch(IOException expected){assertTrue(expected.getMessage().contains("EMERGENCY"));}
            assertEquals(0,oldBridge.resets);oldBridge.dropEmergency=false;EventClient.CommandRequest restored=EventClient.beginEmergency();
            assertEquals(new JSONObject(old.payload).getString("command_id"),new JSONObject(restored.payload).getString("command_id"));
            EventClient.sendCommand(restored);EventClient.command("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));assertEquals(1,oldBridge.resets);
        }finally{prefs.edit().putString("server_url",originalSource).commit();}
    }
    @Test public void campaignPricesUseBrokerDigitsForJpyMetalsAndBitcoin()throws Exception{
        for(int digits:new int[]{2,3,5}){
            double entry=digits==2?64321.12:digits==3?149.123:1.12345;
            JSONObject snapshot=EventClient.state().put("instrument",new JSONObject().put("digits",digits))
                .put("campaign",new JSONObject().put("side",1).put("confirmed",true))
                .put("positions",new JSONArray().put(new JSONObject().put("volume",.01).put("price_open",entry).put("sl",entry-1)));
            String expected=String.format(java.util.Locale.US,"%."+digits+"f",entry);
            String summary=EventClient.campaignSummary(snapshot);
            assertTrue("Broker precision must be preserved: "+summary,summary.contains("Entry MT5: "+expected+" ·"));
            EventClient.cache(snapshot);
            Method format=MainActivity.class.getDeclaredMethod("fmt",double.class);format.setAccessible(true);
            assertEquals(expected,format.invoke(rule.getActivity(),entry));
        }
    }
}
