package com.openai.fxm1;

import android.content.*;
import android.graphics.Rect;
import android.os.ParcelFileDescriptor;
import android.view.View;
import android.widget.ScrollView;
import android.widget.TextView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.UiDevice;
import org.json.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.lang.reflect.Method;
import java.io.InputStream;
import static org.junit.Assert.*;

/** Native presentation regressions: trade requirements belong to the active profile. */
@RunWith(AndroidJUnit4.class)
public class R57ScalpUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    Context context;
    void ui(Runnable action){InstrumentationRegistry.getInstrumentation().runOnMainSync(action);}
    @Before public void setup(){
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        context.stopService(new Intent(context,MonitoringService.class));
        context.getSharedPreferences("fxm1",Context.MODE_PRIVATE).edit().clear()
            .putBoolean("ec1_migrated",true).putBoolean("v108_initial_review",true)
            .putBoolean("v800_tf_migrated",true).putBoolean("v925_tf_migrated",true)
            .putString("entry_tf_name","M1").putInt("entry_tf_pos",0).putInt("signal_mode_pos",1)
            .putString("selected_symbol","EUR/USD").putString("ec_lot_cap","0.01")
            .putString("target_trade_mode","DEMO").putString("ec_token","private-fixture-secret").commit();
        EventClient.init(context);
    }
    @After public void stop(){
        context.stopService(new Intent(context,MonitoringService.class));
        if(rule.getActivity()!=null)ui(()->rule.getActivity().finish());
    }
    JSONObject state(String stage)throws Exception{
        JSONObject setup=new JSONObject().put("engine","SCALP_MICRO_V1").put("timeframe","M1")
            .put("stage",stage).put("side",1).put("trigger",1.10123).put("invalidation",1.10054)
            .put("reason","Ждём пересечение micro-trigger новой котировкой").put("addition",false);
        return new JSONObject().put("protocol",EventClient.PROTOCOL)
            .put("config",new JSONObject().put("symbol","EUR/USD").put("timeframe","M1").put("mode","SCALP"))
            .put("forecast",new JSONObject().put("map_version",3).put("timeframe","M1").put("available",true)
                .put("execution_setup",setup).put("scenarios",new JSONArray()))
            .put("decision",new JSONObject().put("signal","WAIT").put("phase","TRIGGER").put("reason","Ожидание подтверждения"))
            .put("account",new JSONObject().put("key","qa-scalp").put("type","DEMO").put("balance",1000).put("equity",1000))
            .put("account_age",0).put("analysis_time",System.currentTimeMillis()/1000.0)
            .put("quote_fresh",true).put("bars",new JSONArray()).put("positions",new JSONArray());
    }
    String journal(JSONArray events)throws Exception{
        Method method=EventClient.class.getDeclaredMethod("formatJournal",JSONArray.class);method.setAccessible(true);
        return (String)method.invoke(null,events);
    }
    JSONObject event(String kind,JSONObject body)throws Exception{
        return new JSONObject().put("time",1800000000).put("kind",kind).put("body",body);
    }

    @Test public void journalExplainsNestedAnalysisAndCommandWithoutDumpingCredentials()throws Exception{
        JSONObject decision=new JSONObject().put("signal","WAIT").put("phase","TRIGGER").put("reason","Ждём новый micro-trigger")
            .put("forecast",new JSONObject().put("timeframe","M1")).put("token","do-not-show-decision-token");
        String text=journal(new JSONArray()
            .put(event("ANALYSIS",new JSONObject().put("decision",decision).put("mode","SCALP").put("authorization","secret-header")))
            .put(event("COMMAND",new JSONObject().put("command","enable").put("client_id","private-client")
                .put("result",new JSONObject().put("ok",true).put("message","AUTO разрешён").put("auto",true).put("paused",false)
                    .put("token","do-not-show-result-token")))));
        for(String required:new String[]{"ANALYSIS","WAIT","TRIGGER","SCALP","M1","Ждём новый micro-trigger","COMMAND","enable","AUTO разрешён"})
            assertTrue("Journal must explain "+required+": "+text,text.contains(required));
        for(String secret:new String[]{"secret-header","private-client","do-not-show-decision-token","do-not-show-result-token"})assertFalse(text,text.contains(secret));
    }
    @Test public void journalKeepsLegacyReasonsAndBoundsUntrustedText()throws Exception{
        String legacy=journal(new JSONArray().put(event("ENTRY_BLOCKED",new JSONObject().put("reason","Недостаточно свободной маржи"))));
        assertTrue(legacy,legacy.contains("Недостаточно свободной маржи"));
        StringBuilder longReason=new StringBuilder("private-fixture-secret\nBearer abc-secret ");for(int i=0;i<2000;i++)longReason.append('x');
        String text=journal(new JSONArray().put(event("ANALYSIS",new JSONObject().put("mode","SCALP")
            .put("decision",new JSONObject().put("signal","WAIT").put("phase","SEARCH").put("reason",longReason.toString())))));
        assertTrue("One event cannot fill the entire journal",text.length()<650);
        assertEquals("Reason cannot inject extra journal rows",2,text.split("\n",-1).length);
        assertFalse(text,text.contains("private-fixture-secret"));assertFalse(text,text.contains("abc-secret"));
        String object=journal(new JSONArray().put(event("UNKNOWN",new JSONObject().put("reason",new JSONObject().put("token","secret-object")))));
        assertFalse("Unknown objects must not be serialized into UI",object.contains("secret-object"));
    }
    @Test public void executionRequirementPrecedesHypothesesAndHasExactTradePrices()throws Exception{
        String text=ScenarioUi.levels(state("MICRO"));
        assertTrue("Execution requirement must precede observer hypotheses: "+text,text.startsWith("БЫСТРЫЙ SCALP · ТОРГОВЛЯ M1"));
        for(String required:new String[]{"micro-trigger","BUY","1.10123","1.10054"})assertTrue(text,text.contains(required));
        assertFalse("Empty observer hypotheses must not reserve a section: "+text,text.contains("ГИПОТЕЗЫ"));
    }
    @Test public void executionRequirementDoesNotLeakIntoNormalOtherFramesOrPendingProfile()throws Exception{
        for(String[] profile:new String[][]{{"NORMAL","M1"},{"NORMAL","M5"},{"SCALP","M5"}}){
            JSONObject state=state("MICRO");state.getJSONObject("config").put("mode",profile[0]).put("timeframe",profile[1]);
            state.put("pending_config",new JSONObject().put("mode","SCALP").put("timeframe","M1"));
            assertFalse(ScenarioUi.levels(state).contains("БЫСТРЫЙ SCALP"));
        }
        JSONObject wrongFrame=state("MICRO");wrongFrame.getJSONObject("forecast").put("timeframe","M15");
        assertFalse("Observer M15 cannot become M1 trade requirements",ScenarioUi.levels(wrongFrame).contains("БЫСТРЫЙ SCALP"));
        JSONObject legacy=state("MICRO");legacy.getJSONObject("forecast").remove("execution_setup");
        assertFalse("Legacy forecast remains readable",ScenarioUi.levels(legacy).contains("БЫСТРЫЙ SCALP"));
    }
    @Test public void nullLevelsBlockedAddsAndCachedRequirementsStayTruthful()throws Exception{
        JSONObject state=state("BLOCKED"),setup=state.getJSONObject("forecast").getJSONObject("execution_setup");
        setup.put("side",0).put("trigger",JSONObject.NULL).put("invalidation",JSONObject.NULL).put("addition",true)
            .put("reason","Добавление заблокировано: нет нового отката");
        String text=ScenarioUi.levels(state);assertTrue(text,text.contains("ДОБАВЛЕНИЕ")&&text.contains("заблокирован"));
        assertFalse(text,text.contains("NaN")||text.contains("null")||text.contains("1.10123"));
        state.put("client_offline",true);text=ScenarioUi.levels(state);
        assertTrue("Offline marker precedes any old requirement",text.indexOf("КЭШ")<text.indexOf("БЫСТРЫЙ SCALP"));
        state.remove("client_offline");state.getJSONObject("forecast").put("stale",true);text=ScenarioUi.levels(state);
        assertTrue("Stale requirement is not advertised as actionable",text.indexOf("УСТАРЕЛИ")<text.indexOf("БЫСТРЫЙ SCALP"));
        setup.put("stage","CONFIRMED");text=ScenarioUi.levels(state);
        assertFalse("Historical confirmation cannot advertise a current ready signal",text.contains("Сигнал подтверждён"));
        state.getJSONObject("forecast").put("stale",false);state.put("quote_fresh",false);text=ScenarioUi.levels(state);
        assertFalse("Stale market blocks readiness even before forecast invalidation",text.contains("Сигнал подтверждён"));
    }
    @Test public void nativeWaitAndSignalDetailsUseActiveTradeFrame()throws Exception{
        UiDevice.getInstance(InstrumentationRegistry.getInstrumentation()).wakeUp();
        JSONObject state=state("MICRO");EventClient.cache(state);rule.launchActivity(new Intent());
        Method sync=MainActivity.class.getDeclaredMethod("syncUiFromBackgroundService");sync.setAccessible(true);
        ui(()->{try{
            EventClient.cache(state);sync.invoke(rule.getActivity());
            String wait=((TextView)rule.getActivity().findViewById(R.id.whyWaitText)).getText().toString();
            String levels=((TextView)rule.getActivity().findViewById(R.id.levelsText)).getText().toString();
            assertTrue(wait,wait.contains("ТОРГОВЛЯ M1")&&wait.contains("micro-trigger"));
            assertTrue(levels,levels.startsWith("БЫСТРЫЙ SCALP · ТОРГОВЛЯ M1"));
            JSONObject observer=state("MICRO");observer.getJSONObject("config").put("timeframe","M15");
            observer.getJSONObject("forecast").put("timeframe","M15");observer.getJSONObject("forecast").remove("execution_setup");
            ScenarioUi.populate(rule.getActivity().findViewById(R.id.sparklineView),observer);
            assertEquals("M15",((SparklineView)rule.getActivity().findViewById(R.id.sparklineView)).historyFrame());
            assertEquals("Viewing another chart cannot replace trade WAIT",wait,((TextView)rule.getActivity().findViewById(R.id.whyWaitText)).getText().toString());
            assertEquals("M1",EventClient.config().getString("timeframe"));
            ScrollView root=rule.getActivity().findViewById(R.id.rootLayout);View levelsView=rule.getActivity().findViewById(R.id.levelsText);
            Rect bounds=new Rect();levelsView.getDrawingRect(bounds);root.offsetDescendantRectToMyCoords(levelsView,bounds);
            root.scrollTo(0,Math.max(0,bounds.top-Math.round(130*context.getResources().getDisplayMetrics().density)));
        }catch(Exception e){throw new AssertionError(e);}});
        InstrumentationRegistry.getInstrumentation().waitForIdleSync();
        for(String cmd:new String[]{"mkdir -p /sdcard/Download/ec1-qa","screencap -p /sdcard/Download/ec1-qa/r57-scalp-m1-requirement.png"})
            try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);
                InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] bytes=new byte[4096];while(in.read(bytes)!=-1){}}
    }
}
