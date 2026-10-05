package com.openai.fxm1;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.lang.reflect.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class R732PatternNavigationUiTest {
    private final Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
    private void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    private static Object call(Object target,String name,Class<?>[] types,Object...values){
        try{Method m=target.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(target,values);}
        catch(NoSuchMethodException e){fail("PATTERN_NAVIGATION_MISSING: "+name);return null;}
        catch(InvocationTargetException e){throw new AssertionError(e.getCause());}catch(Exception e){throw new AssertionError(e);}
    }
    private JSONObject state()throws Exception{return R732PatternRendererUiTest.from(3);}
    @Test public void fitRangeCanShowMoreThan240Candles()throws Exception{
        ChartViewport v=new ChartViewport();JSONArray b=new JSONArray();
        for(int i=0;i<400;i++)b.put(new JSONObject().put("time",1800000000L+i*300).put("open",1.1).put("high",1.2).put("low",1.).put("close",1.1));
        v.merge(b);call(v,"fitRange",new Class<?>[]{long.class,long.class},1800000000L,1800000000L+399*300);
        assertEquals("Full pattern was silently truncated",400,v.window().length());
    }
    @Test public void explicitFitIncludesPoleAndLastAnchor()throws Exception{
        JSONObject s=state(),p=R732PatternRendererUiTest.pattern(s);
        ui(()->{SparklineView c=new SparklineView(context);ScenarioUi.populate(c,s);
            call(c,"selectPattern",new Class<?>[]{String.class},p.optString("view_id"));
            call(c,"fitSelectedPattern",new Class<?>[]{});
            JSONArray shown=(JSONArray)call(c,"displayedBars",new Class<?>[]{});
            assertTrue(shown.optJSONObject(0).optLong("time")<=p.optLong("start_at"));
            assertTrue(c.isFollowingLive());});
    }
    @Test public void recreationRestoresExactEdgeAndScale()throws Exception{
        JSONObject s=state();String key="navigation-"+java.util.UUID.randomUUID();
        ui(()->{SparklineView a=new SparklineView(context);a.setMarketIdentity(key);a.setMarket(s.optJSONArray("bars"),null,null,null,"SCENARIO_V2",s.optJSONObject("live_bar"),null,s.optJSONObject("forecast"));
            a.panHistory(15);a.zoomHistory(.7);long edge=a.historyRightTime();
            JSONObject stored=(JSONObject)call(a,"viewportState",new Class<?>[]{});
            SparklineView b=new SparklineView(context);b.setMarketIdentity(key);b.setMarket(s.optJSONArray("bars"),null,null,null,"SCENARIO_V2",s.optJSONObject("live_bar"),null,s.optJSONObject("forecast"));
            assertEquals(edge,b.historyRightTime());assertFalse(b.isFollowingLive());
            assertEquals(stored.toString(),((JSONObject)call(b,"viewportState",new Class<?>[]{})).toString());});
    }
    @Test public void newTicksDoNotResetManualViewport()throws Exception{
        JSONObject s=state();
        ui(()->{SparklineView c=new SparklineView(context);ScenarioUi.populate(c,s);c.panHistory(10);c.zoomHistory(.8);
            JSONObject before=(JSONObject)call(c,"viewportState",new Class<?>[]{});
            for(int i=0;i<4;i++)ScenarioUi.populate(c,s);
            assertEquals(before.toString(),((JSONObject)call(c,"viewportState",new Class<?>[]{})).toString());});
    }
    @Test public void missingSelectedPatternIsNotReplacedUnderItsName()throws Exception{
        JSONObject s=state(),p=R732PatternRendererUiTest.pattern(s);String id=p.getString("view_id");
        JSONObject empty=new JSONObject(s.toString());empty.getJSONObject("forecast").getJSONObject("pattern_chart").put("patterns",new JSONArray()).put("branches",new JSONArray());
        ui(()->{SparklineView c=new SparklineView(context);ScenarioUi.populate(c,s);call(c,"selectPattern",new Class<?>[]{String.class},id);ScenarioUi.populate(c,empty);
            assertEquals(id,c.displayedForecast().optString("selected_pattern_id"));
            assertTrue(c.getContentDescription().toString().contains("недоступна"));});
    }
    @Test public void candlesModeSurvivesPatternSelectionOnOtherScope()throws Exception{
        JSONObject s=state();String key="own-frame-"+java.util.UUID.randomUUID();
        ui(()->{SparklineView c=new SparklineView(context);c.setMarketIdentity(key);c.setChartMode("CANDLES");
            c.setMarketIdentity(key+"other");assertEquals("PATTERNS",c.displayedForecast().optString("chart_display_mode"));
            c.setMarketIdentity(key);assertEquals("CANDLES",c.displayedForecast().optString("chart_display_mode"));});
    }
}
