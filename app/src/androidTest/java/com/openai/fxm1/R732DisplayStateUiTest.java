package com.openai.fxm1;

import android.app.Activity;
import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry;
import androidx.test.runner.lifecycle.Stage;
import java.lang.reflect.Method;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class R732DisplayStateUiTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class);
    private final Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
    private void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    private SparklineView chart(String scope)throws Exception{
        SparklineView[] result={null};JSONObject f=R7ReleaseUiTest.forecast();JSONArray b=R7ReleaseUiTest.bars();
        ui(()->{result[0]=new SparklineView(context);result[0].setMarketIdentity(scope);result[0].setHistoryContext(scope,"M5","UTC");
            result[0].setMarket(b,null,null,null,"SCENARIO_V2",null,null,f);});return result[0];
    }
    private String scope(){return "r732-ui-"+java.util.UUID.randomUUID();}
    private void mode(SparklineView chart,String value){
        try{Method method=SparklineView.class.getMethod("setChartMode",String.class);method.invoke(chart,value);}
        catch(NoSuchMethodException e){fail("SCOPED_CHART_MODE_MISSING: native chart needs persistent PATTERNS/CANDLES modes");}
        catch(Exception e){throw new AssertionError(e);}
    }
    @Test public void defaultIsPatterns()throws Exception{
        SparklineView c=chart(scope());ui(()->{
            assertEquals("PATTERNS",c.displayedForecast().optString("chart_display_mode"));
            assertFalse(c.displayedForecast().optBoolean("show_price_forecast",true));
        });
    }
    @Test public void twoSurfacesUseOneChoice()throws Exception{
        String key=scope();SparklineView a=chart(key),b=chart(key);
        ui(()->{mode(a,"CANDLES");assertEquals("CANDLES",b.displayedForecast().optString("chart_display_mode"));
            mode(b,"PATTERNS");assertEquals("PATTERNS",a.displayedForecast().optString("chart_display_mode"));});
    }
    @Test public void newInstrumentDoesNotInheritSelection()throws Exception{
        SparklineView c=chart(scope());String other=scope();
        ui(()->{mode(c,"CANDLES");c.setMarketIdentity(other);assertEquals("PATTERNS",c.displayedForecast().optString("chart_display_mode"));});
    }
    @Test public void refreshKeepsChoiceAndDoesNotMutateSnapshot()throws Exception{
        SparklineView c=chart(scope());JSONObject f=R7ReleaseUiTest.forecast().put("show_price_forecast",true);String before=f.toString();
        JSONArray b=R7ReleaseUiTest.bars();
        ui(()->{mode(c,"CANDLES");for(int i=0;i<3;i++)c.setMarket(b,null,null,null,"SCENARIO_V2",null,null,f);
            assertEquals("CANDLES",c.displayedForecast().optString("chart_display_mode"));
            assertFalse(c.displayedForecast().optBoolean("show_price_forecast",true));assertEquals(before,f.toString());});
    }
    @Test public void explicitForecastButtonCannotEnableAnalogue()throws Exception{
        SparklineView c=chart(scope());ui(()->{c.showPriceForecast(true);
            assertFalse("Old forecast control must now select structural routes",c.displayedForecast().optBoolean("show_price_forecast",true));});
    }
    @Test public void recreationRestoresMode()throws Exception{
        String key=scope();MainActivity old=rule.getActivity();
        ui(()->{ScenarioUi.setActive(old,false);SparklineView c=old.findViewById(R.id.sparklineView);c.setMarketIdentity(key);mode(c,"CANDLES");old.recreate();});
        MainActivity[] restored={null};long until=android.os.SystemClock.elapsedRealtime()+8000;
        while(restored[0]==null&&android.os.SystemClock.elapsedRealtime()<until){
            ui(()->{for(Activity a:ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED))
                if(a instanceof MainActivity&&a!=old)restored[0]=(MainActivity)a;});Thread.sleep(50);
        }
        assertNotNull("Actual Activity recreation did not finish",restored[0]);
        ui(()->{ScenarioUi.setActive(restored[0],false);SparklineView c=restored[0].findViewById(R.id.sparklineView);c.setMarketIdentity(key);
            assertEquals("CANDLES",c.displayedForecast().optString("chart_display_mode"));assertFalse(c.displayedForecast().optBoolean("show_price_forecast",true));});
    }
}
