package com.openai.fxm1;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.uiautomator.UiDevice;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.UUID;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class R74ForecastHistoryTest {
    static final long T=R74ForecastRegressionTest.T;
    private final Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
    private void ui(Runnable r){InstrumentationRegistry.getInstrumentation().runOnMainSync(r);}
    private JSONObject f(long time,String id)throws Exception{return R74ForecastRegressionTest.frame(time,id);}
    private JSONArray bars()throws Exception{return R74ForecastRegressionTest.bars();}
    private SparklineView chart(JSONObject f,JSONArray b){return R74ForecastRegressionTest.chart(context,b,f);}
    private ForecastArchive book(){return new ForecastArchive(context.getSharedPreferences("f1-book-test-"+UUID.randomUUID(),0),"test");}
    private static String id(SparklineView c){return c.displayedForecast().optJSONObject("price_forecast").optString("snapshot_id");}
    @Test public void oldSnapshotSurvivesExpiryAndExplicitNewestDoesNotDeleteIt()throws Exception{
        JSONObject first=f(T,"first"),next=f(T+4000,"next");JSONArray bars=bars();
        ui(()->{SparklineView c=chart(first,bars);c.showPriceForecast(true);c.setMarket(bars,null,null,null,"SCENARIO_V2",null,null,next);
            assertEquals("first",id(c));assertNotNull(PriceForecastPlot.visible(c.displayedForecast()));assertTrue(c.forecastDetails().contains("Горизонт завершён"));
            assertTrue(c.newestForecast());assertEquals("next",id(c));assertTrue(c.selectForecast("first"));assertEquals("first",id(c));});
    }
    @Test public void sameIdCannotRewriteOriginOrPoints()throws Exception{
        ForecastArchive book=book();JSONObject first=f(T,"id"),changed=f(T,"id");book.receive(first);
        changed.getJSONObject("price_forecast").put("origin",1.9);changed.getJSONObject("price_forecast").getJSONArray("projection").getJSONObject(0).put("center",1.10008);
        book.receive(changed);assertEquals(1.1000,book.selected().getDouble("origin"),1e-12);assertEquals(1.10005,book.selected().getJSONArray("projection").getJSONObject(0).getDouble("center"),1e-12);
        assertTrue(book.warning().contains("изменён"));assertEquals(1,book.choices().length());
    }
    @Test public void inputsAndReturnedCopiesCannotMutateStoredForecast()throws Exception{
        ForecastArchive book=book();JSONObject first=f(T,"id");String before=first.toString();book.receive(first);assertEquals(before,first.toString());
        book.selected().put("origin",5);book.choices().getJSONObject(0).put("origin",4);first.getJSONObject("price_forecast").put("origin",3);
        assertEquals(1.1,book.selected().getDouble("origin"),1e-12);
    }
    @Test public void ringStaysBoundedAndProtectsSelectedOldSnapshot()throws Exception{
        ForecastArchive book=book();for(int i=0;i<70;i++)book.receive(f(T+60*i,"id-"+i));
        assertEquals(32,book.choices().length());assertEquals("id-0",book.selected().getString("snapshot_id"));
        assertEquals("id-69",book.choices().getJSONObject(0).getString("snapshot_id"));
    }
    @Test public void recreationAndTwoSurfacesPreserveSelection()throws Exception{
        SharedPreferences prefs=context.getSharedPreferences("f1-shared-"+UUID.randomUUID(),0);
        ForecastArchive a=new ForecastArchive(prefs,"scope"),b=new ForecastArchive(prefs,"scope");a.receive(f(T,"a"));a.receive(f(T+60,"b"));
        assertEquals("a",b.selected().getString("snapshot_id"));assertTrue(b.select("b"));assertEquals("b",a.selected().getString("snapshot_id"));
        assertEquals("b",new ForecastArchive(prefs,"scope").selected().getString("snapshot_id"));
        assertNull(new ForecastArchive(prefs,"different-account-clock").selected());
    }
    @Test public void rejectsWrongFrameSymbolScopeAndFutureIssue()throws Exception{
        for(String which:new String[]{"frame","symbol","scope","future"}){
            JSONObject bad=f(T,"bad");if(which.equals("frame"))bad.put("chart_timeframe","H1");
            if(which.equals("symbol"))bad.put("chart_symbol","GBPUSD");if(which.equals("scope"))bad.put("chart_scope","other-account");
            if(which.equals("future"))bad.put("data_asof",T-50);
            ForecastArchive b=book();b.receive(bad);assertNull(which,b.selected());assertNull(which,PriceForecastPlot.validated(bad));
        }
    }
    @Test public void missingHistoryReasonIsVisibleWithoutInventingALine()throws Exception{
        JSONObject none=f(T,"empty");none.getJSONObject("price_forecast").put("available",false).put("projection",new JSONArray()).put("reason","Нужно 48 закрытых свечей");JSONArray bars=bars();
        ui(()->{SparklineView c=chart(none,bars);c.showPriceForecast(true);assertNull(PriceForecastPlot.visible(c.displayedForecast()));assertTrue(c.forecastDetails().contains("48 закрытых свечей"));});
    }
    @Test public void staleOrUnavailableDataShowsOnlyLabelledSavedRecord()throws Exception{
        JSONObject first=f(T,"first"),offline=f(T+60,"offline").put("client_offline",true),unavailable=f(T+120,"bad").put("available",false);
        unavailable.getJSONObject("price_forecast").put("available",false).put("reason","История недоступна");JSONArray bars=bars();
        ui(()->{SparklineView c=chart(first,bars);c.showPriceForecast(true);c.setMarket(bars,null,null,null,"SCENARIO_V2",null,null,offline);
            assertEquals("first",id(c));assertEquals(1,c.forecastChoices().length());assertTrue(c.forecastDetails().contains("СОХРАНЁННЫЙ"));
            c.setMarket(bars,null,null,null,"SCENARIO_V2",null,null,unavailable);assertEquals("first",id(c));assertNotNull(PriceForecastPlot.visible(c.displayedForecast()));assertTrue(c.forecastDetails().contains("История недоступна"));});
    }
    @Test public void forecastModeAndSnapshotAreRestoredAcrossViewRecreation()throws Exception{
        JSONObject first=f(T,"first"),next=f(T+60,"next");JSONArray bars=bars();
        ui(()->{SparklineView a=chart(first,bars);a.showPriceForecast(true);String identity=a.marketIdentity();
            SparklineView b=new SparklineView(context);b.setMarketIdentity(identity);b.setMarket(bars,null,null,null,"SCENARIO_V2",null,null,next);
            assertTrue(b.isPriceForecastMode());assertEquals("first",id(b));a.showPriceForecast(false);assertEquals("PATTERNS",b.displayedForecast().optString("chart_display_mode"));});
    }
    @Test public void clockChangeCannotReusePriorForecast()throws Exception{
        JSONObject first=f(T,"first"),next=f(T+60,"next").put("chart_history_clock","clock-B");JSONArray bars=bars();
        ui(()->{SparklineView c=chart(first,bars);c.showPriceForecast(true);c.setMarket(bars,null,null,null,"SCENARIO_V2",null,null,next);assertEquals("next",id(c));assertEquals(1,c.forecastChoices().length());});
    }
    @Test public void manualCandleHistoryDoesNotPretendToBeCurrentForecast()throws Exception{
        JSONObject first=f(T,"first");JSONArray bars=bars();ui(()->{SparklineView c=chart(first,bars);c.showPriceForecast(true);c.panHistory(5);
            assertNull(PriceForecastPlot.visible(c.displayedForecast()));c.goLive();assertNotNull(PriceForecastPlot.visible(c.displayedForecast()));assertEquals("first",id(c));});
    }
    @Test public void timeCoordinatesDoNotShiftWithNewQuoteAndBar()throws Exception{
        JSONObject frame=f(T,"first").put("chart_display_mode","FORECAST").put("show_price_forecast",true),later=new JSONObject(frame.toString()).put("data_asof",T+900);JSONArray bars=bars();
        ForecastChartRenderer.Geometry a=ForecastChartRenderer.geometry(1000,1000,1,frame,bars,null,36);
        ForecastChartRenderer.Geometry b=ForecastChartRenderer.geometry(1000,1000,1,later,bars,null,36);
        assertEquals(a.start,b.start,0);assertEquals(a.end,b.end,0);assertEquals(a.x(T+300),b.x(T+300),0.001);
        assertEquals(a.x(T+300),a.area.left+(T+300-a.start)/(a.end-a.start)*a.area.width(),.001);
    }
    @Test public void snapshotSelectionNeverChangesTradingPreferences()throws Exception{
        EventClient.init(context);String before=EventClient.prefs().getAll().toString();JSONObject frame=f(T,"first");JSONArray bars=bars();
        ui(()->{SparklineView c=chart(frame,bars);c.showPriceForecast(true);c.newestForecast();c.selectForecast("first");c.showPriceForecast(false);});
        assertEquals(before,EventClient.prefs().getAll().toString());
    }
    static final class Picture extends Canvas {
        final Bitmap bitmap;int strokes,fills,candles;final ArrayList<String> text=new ArrayList<>();
        Picture(int w,int h){this(Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888));}
        Picture(Bitmap b){super(b);bitmap=b;drawColor(0xff141125);}
        @Override public void drawPath(Path path,Paint p){if(p.getColor()==ForecastChartRenderer.LINE){if(p.getStyle()==Paint.Style.FILL)fills++;else strokes++;}super.drawPath(path,p);}
        @Override public void drawRect(float l,float t,float r,float b,Paint p){if(p.getColor()==ForecastChartRenderer.UP||p.getColor()==ForecastChartRenderer.DOWN)candles++;super.drawRect(l,t,r,b,p);}
        @Override public void drawText(String s,float x,float y,Paint p){text.add(s);super.drawText(s,x,y,p);}
    }
    @Test public void actualNativeCanvasShowsLineNoFanAndAdvancingFactualCandles()throws Exception{
        JSONObject first=f(T,"first"),later=f(T+900,"later");JSONArray b=bars(),after=new JSONArray(b.toString());
        for(int i=0;i<3;i++)after.put(new JSONObject().put("time",T+i*300).put("open",1.1+i*.00005).put("close",1.10006+i*.00005).put("low",1.09998+i*.00005).put("high",1.10008+i*.00005));
        ui(()->{SparklineView c=chart(first,b);c.showPriceForecast(true);c.layout(0,0,1080,1300);
            Picture before=new Picture(1080,1300);c.draw(before);assertEquals(1,before.strokes);assertEquals(0,before.fills);assertTrue(before.candles>0);save(before,"forecast-f1-issued");int count=before.candles;before.bitmap.recycle();
            c.setMarket(after,null,null,null,"SCENARIO_V2",null,null,later);Picture now=new Picture(1080,1300);c.draw(now);assertEquals("first",id(c));assertTrue(now.candles>count);assertEquals(1,now.strokes);save(now,"forecast-f1-after-15min");now.bitmap.recycle();});
    }
    @Test public void fiveWorkingFramesKeepTheirOwnForecastAndPricePrecision()throws Exception{
        for(String tf:new String[]{"M1","M5","M15","M30","H1"}){
            JSONObject f=f(T,"tf-"+tf);f.put("timeframe",tf).put("chart_timeframe",tf).put("chart_digits",5);
            f.getJSONObject("price_forecast").put("timeframe",tf).put("scope","test|EURUSD|NORMAL|"+tf+"|ANALOG_R7_1");JSONArray bars=bars();
            ui(()->{SparklineView c=chart(f,bars);c.showPriceForecast(true);assertNotNull(PriceForecastPlot.visible(c.displayedForecast()));assertTrue(c.forecastDetails().contains("1.10005"));});
        }
    }
    private void save(Picture p,String name){try{File f=new File(context.getExternalFilesDir(null),name+".png");try(FileOutputStream out=new FileOutputStream(f)){assertTrue(p.bitmap.compress(Bitmap.CompressFormat.PNG,100,out));}
        UiDevice device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.executeShellCommand("mkdir -p /sdcard/Download/ec1-qa");device.executeShellCommand("cp "+f.getAbsolutePath()+" /sdcard/Download/ec1-qa/"+name+".png");
    }catch(Exception e){throw new AssertionError(e);}}
}
