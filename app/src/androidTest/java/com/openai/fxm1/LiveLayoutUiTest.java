package com.openai.fxm1;

import android.content.*;
import android.os.*;
import android.view.*;
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
import java.util.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class LiveLayoutUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context;
    final int[] fields={R.id.statusText,R.id.marketStatusText,R.id.marketSessionText,R.id.confidenceText,
        R.id.signalAgeText,R.id.levelsText,R.id.contextText,R.id.whyWaitText,R.id.componentScoresText,
        R.id.autoStatusText,R.id.accountText,R.id.positionsText,R.id.priceCompareText,R.id.smartStatusText,
        R.id.statsText,R.id.signalHistoryText,R.id.tradeHistoryText,R.id.serverStatusText,R.id.journalText};
    final int[] anchors={R.id.sparklineView,R.id.riskCard,R.id.metricsCard,R.id.positionsCard,R.id.smartCard,R.id.tradingCard,R.id.journalCard};
    void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    void settle()throws Exception{InstrumentationRegistry.getInstrumentation().waitForIdleSync();Thread.sleep(100);}
    void freezeCallbacks(){
        try{for(String name:new String[]{"serviceUiHandler","monitorHandler"}){
            Field f=MainActivity.class.getDeclaredField(name);f.setAccessible(true);((Handler)f.get(rule.getActivity())).removeCallbacksAndMessages(null);
        }}catch(Exception e){throw new AssertionError(e);}
    }
    @Before public void setup()throws Exception{
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        context.stopService(new Intent(context,MonitoringService.class));Thread.sleep(300);
        context.getSharedPreferences("fxm1",Context.MODE_PRIVATE).edit().clear()
            .putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true).putBoolean("v800_tf_migrated",true)
            .putString("ec_token","ci-fixture-token-not-for-real-trading").putString("server_url","http://127.0.0.1:8765")
            .putString("ec_client_id","layout-test-client-1234").putString("target_trade_mode","DEMO")
            .putString("selected_symbol","EUR/USD").putInt("entry_tf_pos",1).commit();
        EventClient.init(context);EventClient.http("POST",EventClient.base()+"/test/reset",new JSONObject());EventClient.poll();
        rule.launchActivity(new Intent());Thread.sleep(1200);ui(this::freezeCallbacks);settle();
    }
    @After public void stop(){context.stopService(new Intent(context,MonitoringService.class));}
    String longText(){StringBuilder b=new StringBuilder("LIVE LONG MARKER\n");for(int i=0;i<30;i++)b.append("Сценарий ").append(i).append(": ждём пересечения уровня; T1 1.10123, T2 нет; спред и время котировки проверены.\n");return b.append("END OF FULL DETAILS").toString();}
    void update(String value){ui(()->{for(int id:fields)((TextView)rule.getActivity().findViewById(id)).setText(value);});}
    int[] geometry(){final int[][] result={null};ui(()->{MainActivity a=rule.getActivity();ScrollView root=a.findViewById(R.id.rootLayout);
        int[] v=new int[2+anchors.length*2];v[0]=root.getScrollY();v[1]=root.getChildAt(0).getHeight();
        for(int i=0;i<anchors.length;i++){View view=a.findViewById(anchors[i]);int[] pos=new int[2];view.getLocationOnScreen(pos);v[2+i*2]=pos[1];v[3+i*2]=view.getHeight();}result[0]=v;});return result[0];}
    void shot(String name)throws Exception{
        for(String cmd:new String[]{"mkdir -p /sdcard/Download/ec1-qa","screencap -p /sdcard/Download/ec1-qa/"+name+".png"})
            try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);
                InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] b=new byte[4096];while(in.read(b)!=-1){}}
    }
    @Test public void changingLiveTextKeepsGeometryAndScroll()throws Exception{
        update("WAIT · короткий статус");settle();
        ui(()->{ScrollView root=rule.getActivity().findViewById(R.id.rootLayout);root.scrollTo(0,600);});settle();
        int[] before=geometry();shot("r52-layout-short");
        for(int i=0;i<12;i++){
            String value=i%2==0?longText():"WAIT · новый короткий статус "+i;
            update(value);settle();int[] after=geometry();
            assertArrayEquals("Live update must not move chart, trading controls or page: "+Arrays.toString(before)+" -> "+Arrays.toString(after),before,after);
            ui(()->assertEquals(value,((TextView)rule.getActivity().findViewById(R.id.levelsText)).getText().toString()));
        }
        update(longText());settle();shot("r52-layout-long");
    }
    @Test public void shrinkingStatusesAtPageBottomDoesNotSnap()throws Exception{
        update(longText());settle();ui(()->{ScrollView root=rule.getActivity().findViewById(R.id.rootLayout);root.scrollTo(0,root.getChildAt(0).getHeight());});settle();
        int[] before=geometry();update("WAIT");settle();
        assertArrayEquals("Shrinking content must not clamp scroll or move the bottom card",before,geometry());
    }
    @Test public void fullTextRemainsReadableInFrozenSnapshot()throws Exception{
        String full=longText();ui(()->{TextView view=rule.getActivity().findViewById(R.id.levelsText);view.setText(full);
            assertTrue("A compact live field must open all its text",view.performClick());});
        UiDevice d=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        assertTrue(d.wait(Until.hasObject(By.textContains("END OF FULL DETAILS")),5000));
        ui(()->((TextView)rule.getActivity().findViewById(R.id.levelsText)).setText("NEW LIVE DATA"));settle();
        assertNotNull("Reading snapshot must not be replaced by incoming ticks",d.findObject(By.textContains("END OF FULL DETAILS")));
        UiObject2 close=d.findObject(By.res("android","button1"));
        assertNotNull("Snapshot close button must remain on screen",close);
        android.graphics.Rect button=close.getVisibleBounds();
        assertTrue("Snapshot close button must not be pushed below the screen",button.height()>=32*context.getResources().getDisplayMetrics().density && button.top>=0 && button.bottom<=d.getDisplayHeight());
        shot("r52-full-details");close.click();
        ui(()->assertEquals("NEW LIVE DATA",((TextView)rule.getActivity().findViewById(R.id.levelsText)).getText().toString()));
    }
    @Test public void lateServerCallbackAfterDestroyIsIgnored()throws Exception {
        MainActivity old=rule.getActivity();
        rule.finishActivity();settle();
        String before=EventClient.prefs().getString("server_url","");
        Method check=MainActivity.class.getDeclaredMethod("checkServer");check.setAccessible(true);
        ui(()->{try {check.invoke(old);}catch(Exception e){throw new AssertionError("Late callback must not submit to a closed executor",e);}});
        assertEquals(before,EventClient.prefs().getString("server_url",""));
        final boolean[] delivered={false};
        Method deliver=MainActivity.class.getDeclaredMethod("deliverUi",Runnable.class);deliver.setAccessible(true);
        ui(()->{try {deliver.invoke(old,(Runnable)()->delivered[0]=true);}catch(Exception e){throw new AssertionError(e);}});
        settle();assertFalse("Closed Activity must not receive late dialog or text callbacks",delivered[0]);
    }

    @Test public void cachedLiveUpdatesKeepScreenAndHistoricalChartAnchored()throws Exception {
        EventClient.http("POST",EventClient.base()+"/test/r5-market",new JSONObject().put("family","TRIANGLE"));
        JSONObject state=EventClient.poll();
        EventClient.prefs().edit().putBoolean("server_verified",false).putString("ec_lot_cap","0.37").commit();
        Method sync=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");sync.setAccessible(true);
        ui(()->{try {sync.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}});settle();
        final long[] edge={0};
        ui(()->{SparklineView chart=rule.getActivity().findViewById(R.id.sparklineView);chart.panHistory(8);edge[0]=chart.historyRightTime();
            ((ScrollView)rule.getActivity().findViewById(R.id.rootLayout)).scrollTo(0,1000);});settle();
        int[] before=geometry();
        for(int i=0;i<8;i++) {
            String reason=i%2==0?longText():"Ждём свежий микропробой "+i;
            JSONObject next=new JSONObject(state.toString());
            next.getJSONObject("decision").put("signal","WAIT").put("reason",reason);
            EventClient.cache(next);
            ui(()->{try {sync.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}});settle();
            int[] after=geometry();
            assertArrayEquals("Actual cache-to-UI refresh must preserve page geometry: "+Arrays.toString(before)+" -> "+Arrays.toString(after),before,after);
            ui(()->{SparklineView chart=rule.getActivity().findViewById(R.id.sparklineView);
                assertEquals(edge[0],chart.historyRightTime());assertFalse(chart.isFollowingLive());
                assertTrue(((TextView)rule.getActivity().findViewById(R.id.whyWaitText)).getText().toString().contains(reason));});
            assertEquals("0.37",EventClient.prefs().getString("ec_lot_cap",""));
        }
        shot("r52-live-history-stable");
    }
    @Test public void offlineInstrumentChangeClearsUnrelatedLiveChart()throws Exception {
        EventClient.http("POST",EventClient.base()+"/test/r5-market",new JSONObject().put("family","TRIANGLE"));
        EventClient.poll();
        Method sync=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");sync.setAccessible(true);
        ui(()->{try{sync.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}});settle();
        // offline() labels a lost read; it does not disable the transport. A user
        // selection now sends immediately, so reproduce an actual unreachable Bridge.
        EventClient.prefs().edit().putString("server_url","http://127.0.0.1:1").commit();
        EventClient.offline(new IOException("phone disconnected"));
        ui(()->{Spinner symbol=rule.getActivity().findViewById(R.id.symbolSpinner);
            for(int i=0;i<symbol.getCount();i++)if("GBP/USD".equals(symbol.getItemAtPosition(i).toString())){symbol.setSelection(i);break;}});settle();
        ui(()->{try{sync.invoke(rule.getActivity());}catch(Exception e){throw new AssertionError(e);}
            SparklineView chart=rule.getActivity().findViewById(R.id.sparklineView);
            assertEquals("pending:GBP/USD|M5",chart.marketIdentity());
            assertEquals(0,chart.scenarioChoices().length());
            assertFalse(String.valueOf(chart.getContentDescription()).contains("Текущие гипотезы LIVE"));
            assertTrue(((TextView)rule.getActivity().findViewById(R.id.statusText)).getText().toString().contains("НЕТ СВЯЗИ"));});
    }
}
