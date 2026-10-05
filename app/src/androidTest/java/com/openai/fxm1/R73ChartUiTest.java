package com.openai.fxm1;

import android.content.Context;
import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.ParcelFileDescriptor;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.TimeZone;
import java.util.Calendar;
import static org.junit.Assert.*;

/** Real Android Canvas, self-contained market fixtures and exported chart PNGs. No trading calls. */
@RunWith(AndroidJUnit4.class)
public class R73ChartUiTest {
    private static final long T=1800000000L;
    private static final int GREEN=0xff42d67a,RED=0xffff4857;
    private final Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
    private static final class Label {
        final String text;final RectF bounds;
        Label(String text,float x,float y,Paint paint){this.text=text;bounds=new RectF(x,y+paint.ascent(),x+paint.measureText(text),y+paint.descent());}
    }
    private static final class RecordingCanvas extends Canvas {
        final Bitmap bitmap;final List<Label> labels=new ArrayList<>();int candles;float lastCandleRight;
        RecordingCanvas(int width,int height){this(Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888));}
        private RecordingCanvas(Bitmap bitmap){super(bitmap);this.bitmap=bitmap;drawColor(0xff141125);}
        @Override public void drawText(String text,float x,float y,Paint paint){labels.add(new Label(text,x,y,paint));super.drawText(text,x,y,paint);}
        @Override public void drawRect(float l,float t,float r,float b,Paint paint){if(paint.getColor()==GREEN||paint.getColor()==RED){candles++;lastCandleRight=r;}super.drawRect(l,t,r,b,paint);}
        boolean has(String text){for(Label label:labels)if(label.text.contains(text))return true;return false;}
    }
    private void ui(Runnable work){InstrumentationRegistry.getInstrumentation().runOnMainSync(work);}
    private static JSONObject bar(long time,double value,double tick)throws Exception{
        return new JSONObject().put("time",time).put("open",value).put("close",value+tick)
            .put("low",value-2*tick).put("high",value+3*tick);
    }
    private static JSONArray bars(String tf,double origin,double tick)throws Exception{
        JSONArray rows=new JSONArray();long interval=seconds(tf);
        for(int i=0;i<36;i++){
            long time=T-(36-i)*interval;
            if("MN1".equals(tf)){Calendar month=Calendar.getInstance(TimeZone.getTimeZone("UTC"));month.setTimeInMillis(T*1000);
                month.set(Calendar.DAY_OF_MONTH,1);month.set(Calendar.HOUR_OF_DAY,0);month.set(Calendar.MINUTE,0);month.set(Calendar.SECOND,0);
                month.add(Calendar.MONTH,-(36-i));time=month.getTimeInMillis()/1000;}
            rows.put(bar(time,origin+Math.sin(i*.6)*tick*7,tick));
        }
        return rows;
    }
    private static long seconds(String tf){switch(tf){case "M1":return 60;case "M15":return 900;case "M30":return 1800;
        case "H1":return 3600;case "H4":return 14400;case "D1":return 86400;case "W1":return 604800;case "MN1":return 2678400;default:return 300;}}
    private static JSONObject forecast(String symbol,String tf,double origin,double tick,int digits)throws Exception{
        JSONArray projection=new JSONArray();
        int first=(int)Math.max(5,seconds(tf)/60);
        for(int minutes:new int[]{first,first*2,first*3,first*6,first*12}){
            double value=origin+tick*minutes/first;
            projection.put(new JSONObject().put("time",T+minutes*60L).put("minutes",minutes)
                .put("center",value).put("low",value-tick*3).put("high",value+tick*3));
        }
        JSONObject price=new JSONObject().put("available",true).put("symbol",symbol).put("timeframe",tf)
            .put("model","ANALOG_R7_1").put("scope","account|"+symbol+"|"+symbol+"|NORMAL|"+tf+"|ANALOG_R7_1")
            .put("issued_at",T).put("origin",origin).put("projection",projection);
        return new JSONObject().put("map_version",3).put("available",true).put("timeframe",tf)
            .put("chart_symbol",symbol).put("chart_digits",digits).put("chart_timeframe",tf)
            .put("chart_scope","account|"+symbol).put("chart_mode","NORMAL")
            .put("live_price",origin).put("data_asof",T).put("scenarios",new JSONArray()).put("price_forecast",price);
    }
    private RecordingCanvas draw(JSONObject f,JSONArray rows,JSONObject live,int width,int height){
        RecordingCanvas canvas=new RecordingCanvas(width,height);
        ScenarioMapRenderer.draw(canvas,width,height,1,rows,new JSONArray(),live,new JSONArray(),f,new JSONArray());return canvas;
    }
    @Test public void malformedCandleCannotOverwriteTheLastValidHistoryRow()throws Exception{
        ChartViewport viewport=new ChartViewport();JSONObject original=bar(T,147.234,.001);
        viewport.merge(new JSONArray().put(original));
        viewport.merge(new JSONArray().put(bar(T,147.234,.001).put("low",148))
            .put(new JSONObject().put("time",T+300)).put(bar(T+600,-1,.001)));
        assertEquals("Missing, negative and inverted OHLC must never become candle history",1,viewport.window().length());
        assertEquals(original.toString(),viewport.window().getJSONObject(0).toString());
    }
    @Test public void invalidZoomDoesNotCollapseAnExistingViewport(){
        ChartViewport viewport=new ChartViewport();int count=viewport.visible();
        for(double factor:new double[]{Double.NaN,Double.POSITIVE_INFINITY,0,-1}){
            viewport.zoom(factor);assertEquals("A nonfinite/nonpositive scale is not a zoom gesture",count,viewport.visible());
        }
    }
    @Test public void flatRealCandlesStillRenderInsteadOfABlankChart()throws Exception{
        JSONArray rows=new JSONArray().put(bar(T-600,65850.25,0)).put(bar(T-300,65850.25,0));
        JSONObject f=forecast("BTCUSD","M5",65850.25,.01,2).put("show_price_forecast",false);
        RecordingCanvas canvas=draw(f,rows,null,320,220);
        try{assertEquals("Flat MT5 bars remain factual candles",2,canvas.candles);}finally{canvas.bitmap.recycle();}
    }
    @Test public void oldFormingCandleDoesNotDuplicateAClosedCandle()throws Exception{
        JSONObject f=forecast("EURUSD","M5",1.10324,.00001,5).put("show_price_forecast",false);
        JSONArray rows=new JSONArray().put(bar(T-600,1.10324,.00001)).put(bar(T-300,1.10325,.00001));
        final RecordingCanvas[] result={null};
        ui(()->{SparklineView chart=new SparklineView(context);chart.layout(0,0,720,500);
            chart.setMarket(rows,null,null,null,"SCENARIO_V2",rows.optJSONObject(1),null,f);
            result[0]=new RecordingCanvas(720,500);chart.draw(result[0]);});
        try{assertEquals("A closed time must not also be plotted as forming",2,result[0].candles);}finally{result[0].bitmap.recycle();}
    }
    @Test public void singleAvailableCandleIsVisibleWhileHistoryLoads()throws Exception{
        JSONObject f=forecast("USDJPY","M1",147.234,.001,3).put("show_price_forecast",false);
        JSONObject live=bar(T,147.234,.001);final RecordingCanvas[] result={null};
        ui(()->{SparklineView chart=new SparklineView(context);chart.layout(0,0,720,500);
            chart.setMarket(new JSONArray(),null,null,null,"SCENARIO_V2",live,null,f);
            result[0]=new RecordingCanvas(720,500);chart.draw(result[0]);});
        try{assertEquals("Do not replace an available real candle with a waiting message",1,result[0].candles);}finally{result[0].bitmap.recycle();}
    }
    @Test public void waitingCandlesUseAvailableWidthWhenThereIsNoProjection()throws Exception{
        JSONObject f=forecast("EURUSD","M5",1.10324,.00001,5).put("show_price_forecast",false);
        RecordingCanvas canvas=draw(f,bars("M5",1.10324,.00001),null,320,220);
        try{assertTrue("WAIT must not reserve over half the plot for nonexistent future paths",canvas.lastCandleRight>320*.70f);}finally{canvas.bitmap.recycle();}
    }
    @Test public void unavailableWrongInstrumentAndWrongScopePriceForecastsAreHidden()throws Exception{
        JSONObject f=forecast("BTCUSD","M5",65850.25,.01,2);assertNotNull(PriceForecastPlot.visible(f));
        JSONObject unavailable=new JSONObject(f.toString()).put("available",false);
        assertNull("Unavailable parent cannot advertise an available child forecast",PriceForecastPlot.visible(unavailable));
        assertFalse("Unavailable forecasts must not claim current LIVE hypotheses to accessibility",SparklineView.mapDescription(unavailable).contains("Текущие гипотезы LIVE"));
        JSONObject wrongSymbol=new JSONObject(f.toString());wrongSymbol.getJSONObject("price_forecast").put("symbol","EURUSD");
        assertNull("Same timeframe is insufficient for another instrument",PriceForecastPlot.visible(wrongSymbol));
        JSONObject wrongScope=new JSONObject(f.toString());wrongScope.getJSONObject("price_forecast").put("scope","another-account|BTCUSD|BTCUSD|NORMAL|M5|ANALOG_R7_1");
        assertNull("Another account/clock's forecast cannot be shown",PriceForecastPlot.visible(wrongScope));
        assertNull("Configured chart timeframe owns this canvas",PriceForecastPlot.visible(new JSONObject(f.toString()).put("chart_timeframe","H1")));
    }
    @Test public void forecastLabelsDoNotOverlapAndExpiredPointsDoNotBecomeFutureTicks()throws Exception{
        JSONObject f=forecast("EURUSD","M5",1.10324,.00001,5),price=f.getJSONObject("price_forecast");
        RecordingCanvas canvas=new RecordingCanvas(160,160);
        try{
            PriceForecastPlot.draw(canvas,f,price,new RectF(10,10,110,110),1.102,1.105,1);
            for(int i=0;i<canvas.labels.size();i++)for(int j=i+1;j<canvas.labels.size();j++)
                assertFalse("Forecast horizon labels overlap: "+canvas.labels.get(i).text+" / "+canvas.labels.get(j).text,
                    RectF.intersects(canvas.labels.get(i).bounds,canvas.labels.get(j).bounds));
            canvas.labels.clear();f.put("data_asof",T+11*60);
            PriceForecastPlot.draw(canvas,f,price,new RectF(10,10,110,110),1.102,1.105,1);
            assertFalse("An expired +5 estimate is not a future tick",canvas.has("+5 мин"));
            assertFalse("An expired +10 estimate is not a future tick",canvas.has("+10 мин"));
        }finally{canvas.bitmap.recycle();}
    }
    @Test public void staleAndArchiveMarkersNeverClaimLive()throws Exception{
        for(String flag:new String[]{"stale","archive","client_offline"}){
            JSONObject f=forecast("EURUSD","M5",1.10324,.00001,5).put(flag,true);
            RecordingCanvas canvas=draw(f,bars("M5",1.10324,.00001),null,360,260);
            try{for(Label label:canvas.labels)assertNotEquals(flag+" marker must disclose its age","LIVE",label.text);
                assertFalse(flag+" accessibility cannot advertise a live last price",SparklineView.mapDescription(f).contains(" LIVE 1.10324"));
            }finally{canvas.bitmap.recycle();}
        }
    }
    @Test public void priceAxisPreservesBrokerPrecisionWithoutTruncationAcrossInstruments()throws Exception{
        String[] symbols={"EURUSD","USDJPY","XAUUSD","BTCUSD"};double[] origins={1.10324,147.234,2658.42,65850.25};int[] digits={5,3,2,2};
        for(int i=0;i<symbols.length;i++){
            double tick=Math.pow(10,-digits[i]);JSONObject f=forecast(symbols[i],"M5",origins[i],tick,digits[i]);
            RecordingCanvas canvas=draw(f,bars("M5",origins[i],tick),null,320,220);
            try{int ticks=0;
                for(Label label:canvas.labels)if(label.bounds.left>250&&label.text.matches("[0-9]+[.][0-9]+.*")){
                    ticks++;assertFalse(symbols[i]+" price axis must not ellipsize prices: "+label.text,label.text.contains("…"));
                    assertEquals("Broker decimal precision: "+label.text,digits[i],label.text.length()-label.text.indexOf('.')-1);
                    assertTrue("Axis label must fit within native canvas",label.bounds.right<=320);
                }
                assertEquals("Five complete price ticks for "+symbols[i],5,ticks);
            }finally{canvas.bitmap.recycle();}
        }
    }
    @Test public void selectedInstrumentMetadataDoesNotMutateTheServerSnapshot()throws Exception{
        JSONObject f=forecast("BTCUSD","M5",65850.25,.01,2);
        for(String key:new String[]{"chart_symbol","chart_digits","chart_timeframe","chart_scope","chart_mode"})f.remove(key);
        JSONObject state=new JSONObject().put("config",new JSONObject().put("symbol","BTC/USD").put("timeframe","M5").put("mode","NORMAL"))
            .put("market_scope","account|BTCUSD").put("instrument",new JSONObject().put("name","BTCUSD").put("digits",2))
            .put("bars",bars("M5",65850.25,.01)).put("forecast",f);
        String before=state.toString();
        ui(()->{SparklineView chart=new SparklineView(context);ScenarioUi.populate(chart,state);
            assertEquals("Broker symbol travels with this chart","BTCUSD",chart.displayedForecast().optString("chart_symbol"));
            assertEquals(2,chart.displayedForecast().optInt("chart_digits",-1));});
        assertEquals("Chart metadata is presentation-only",before,state.toString());
    }
    @Test public void mismatchedForecastCannotOverlaySelectedTimeframeCandles()throws Exception{
        JSONObject f=forecast("EURUSD","M15",1.10324,.00001,5);
        f.put("scenarios",new JSONArray().put(new JSONObject().put("scenario_id","wrong-frame").put("side",1)));
        JSONObject state=new JSONObject().put("config",new JSONObject().put("symbol","EUR/USD").put("timeframe","M5").put("mode","NORMAL"))
            .put("market_scope","account|EURUSD").put("bars",bars("M5",1.10324,.00001)).put("forecast",f);
        ui(()->{SparklineView chart=new SparklineView(context);ScenarioUi.populate(chart,state);
            assertEquals("Confirmed M5 candles are still available",T-36*300,chart.oldestTime());
            assertEquals("M15 hypotheses cannot overlay M5 candles",0,chart.scenarioChoices().length());
            assertNull(PriceForecastPlot.visible(chart.displayedForecast()));
            assertTrue("The mismatch is explained",chart.getContentDescription().toString().contains("не соответств"));});
    }
    @Test public void topLevelOfflineStatusPropagatesIntoTheCopiedChartForecast()throws Exception{
        JSONObject f=forecast("EURUSD","M5",1.10324,.00001,5);
        JSONObject state=new JSONObject().put("config",new JSONObject().put("symbol","EUR/USD").put("timeframe","M5").put("mode","NORMAL"))
            .put("client_offline",true).put("bars",bars("M5",1.10324,.00001)).put("forecast",f);
        ui(()->{SparklineView chart=new SparklineView(context);ScenarioUi.populate(chart,state);
            assertTrue(chart.displayedForecast().optBoolean("client_offline"));
            assertFalse(chart.getContentDescription().toString().contains("Текущие гипотезы LIVE"));});
        assertFalse("Server forecast remains untouched",f.optBoolean("client_offline"));
    }
    @Test public void connectedBridgeCannotLabelAnOldPublicationOrStaleQuoteLive()throws Exception{
        for(String cause:new String[]{"snapshot_age","quote_fresh"}){
            JSONObject f=forecast("EURUSD","M5",1.10324,.00001,5);
            JSONObject state=new JSONObject().put("config",new JSONObject().put("symbol","EUR/USD").put("timeframe","M5").put("mode","NORMAL"))
                .put("client_offline",false).put("server_time",T).put("analysis_time",T).put("bars",bars("M5",1.10324,.00001)).put("forecast",f);
            state.put(cause,"snapshot_age".equals(cause)?12:false);
            ui(()->{SparklineView chart=new SparklineView(context);ScenarioUi.populate(chart,state);
                assertTrue(cause+" is stale independently of transport",chart.displayedForecast().optBoolean("stale"));
                assertFalse("Bridge remains connected",chart.displayedForecast().optBoolean("client_offline"));
                assertFalse(chart.getContentDescription().toString().contains("Текущие гипотезы LIVE"));});
            assertFalse("Chart freshness must not mutate the snapshot",f.optBoolean("stale"));
        }
    }
    @Test public void equivalentSymbolFormattingDoesNotBlockTheTimeframeViewer()throws Exception{
        EventClient.init(context);
        String selected=EventClient.prefs().getString("selected_symbol","EUR/USD"),frame=EventClient.tf();
        EventClient.prefs().edit().putString("selected_symbol","EUR/USD").putString("entry_tf_name","M5").commit();
        JSONObject state=new JSONObject().put("config",new JSONObject().put("symbol","EURUSD").put("timeframe","M5"));
        final boolean[] waiting={true};
        try{ui(()->{TimeframeViewer viewer=new TimeframeViewer(new Activity());
            try{viewer.update(state);java.lang.reflect.Method method=TimeframeViewer.class.getDeclaredMethod("profileWaiting");method.setAccessible(true);
                waiting[0]=(Boolean)method.invoke(viewer);
            }catch(Exception error){throw new AssertionError(error);}finally{viewer.close();}});
            assertFalse("EURUSD and EUR/USD are one selected instrument",waiting[0]);
        }finally{EventClient.prefs().edit().putString("selected_symbol",selected).putString("entry_tf_name",frame).commit();}
    }
    @Test public void brokerEntryAndStopAreVisibleOnlyForTheirActualInstrumentAndLiveView()throws Exception{
        JSONObject f=forecast("EURUSD","M5",1.10324,.00001,5);
        JSONArray positions=new JSONArray().put(new JSONObject().put("ticket",731).put("symbol","EURUSD").put("side",1)
            .put("volume",.02).put("price_open",1.10325).put("sl",1.10310))
            .put(new JSONObject().put("ticket",999).put("symbol","BTCUSD").put("side",-1).put("volume",.01).put("price_open",1.10330).put("sl",1.10340));
        for(String view:new String[]{"live","history_only","archive","chart_read_only"}){
            JSONObject shown=new JSONObject(f.toString()).put(view,true);RecordingCanvas canvas=new RecordingCanvas(360,420);
            try{ScenarioMapRenderer.draw(canvas,360,420,1,bars("M5",1.10324,.00001),new JSONArray(),null,new JSONArray(),shown,positions);
                if("live".equals(view)){
                    assertTrue("Actual broker entry is separate from hypothetical entry",canvas.has("MT5 #731 BUY 1.10325"));
                    assertTrue("Actual broker SL is labeled",canvas.has("SL MT5 #731 1.10310"));save(canvas,"r73-chart-broker-position");
                }else assertFalse("A live position must not overlay "+view,canvas.has("#731"));
                assertFalse("Another instrument's trade must never overlay this chart",canvas.has("#999"));
            }finally{canvas.bitmap.recycle();}
        }
    }
    @Test public void chartTimeAxisUsesUtcAndKeepsFrameIdentityAtEveryScale()throws Exception{
        TimeZone previous=TimeZone.getDefault();TimeZone.setDefault(TimeZone.getTimeZone("GMT+09:00"));
        try{for(String frame:Timeframes.CHOICES){
            JSONObject f=forecast("USDJPY",frame,147.234,.001,3).put("show_price_forecast",false);
            RecordingCanvas canvas=draw(f,bars(frame,147.234,.001),null,360,260);
            try{assertTrue("Chart identifies its instrument and selected timeframe",canvas.has("USDJPY")&&canvas.has(frame));
                boolean timeAxis=false;for(Label label:canvas.labels)if(label.bounds.top>190&&label.text.contains("UTC"))timeAxis=true;
                assertTrue("Actual candle time range and timezone are visible below plot on "+frame,timeAxis);
                save(canvas,"r73-chart-frame-"+frame.toLowerCase());
            }finally{canvas.bitmap.recycle();}
        }}finally{TimeZone.setDefault(previous);}
    }
    @Test public void historyAnchorSurvivesNewCandlesAndForecastStaysHidden()throws Exception{
        final JSONObject f=forecast("EURUSD","M5",1.10324,.00001,5);final JSONArray rows=bars("M5",1.10324,.00001);
        final JSONArray update=new JSONArray().put(bar(T,1.10327,.00001));
        ui(()->{SparklineView chart=new SparklineView(context);chart.setMarketIdentity("account|EURUSD|M5");
            chart.setMarket(rows,null,null,null,"SCENARIO_V2",null,null,f);chart.panHistory(12);long edge=chart.historyRightTime();
            chart.setMarket(update,null,null,null,"SCENARIO_V2",null,null,f);
            assertEquals(edge,chart.historyRightTime());assertFalse(chart.isFollowingLive());
            assertNull(PriceForecastPlot.visible(chart.displayedForecast()));
            chart.goLive();assertEquals(T,chart.historyRightTime());assertNotNull(PriceForecastPlot.visible(chart.displayedForecast()));});
    }
    private void save(RecordingCanvas canvas,String name)throws Exception{
        File output=new File(context.getExternalFilesDir(null),name+".png");
        try(FileOutputStream stream=new FileOutputStream(output)){assertTrue(canvas.bitmap.compress(Bitmap.CompressFormat.PNG,100,stream));}
        assertTrue("Native chart screenshot is a nonempty regular file",output.isFile()&&output.length()>1000);
        for(String command:new String[]{"mkdir -p /sdcard/Download/ec1-qa","cp "+output.getAbsolutePath()+" /sdcard/Download/ec1-qa/"+name+".png"})
            try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);
                InputStream stream=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] bytes=new byte[4096];while(stream.read(bytes)!=-1){}}
    }
    @Test public void nativeChartScreenshotsCoverInstrumentScaleSmallScreensAndHistory()throws Exception{
        String[] symbols={"EURUSD","USDJPY","XAUUSD","BTCUSD"};double[] origins={1.10324,147.234,2658.42,65850.25};int[] digits={5,3,2,2};
        for(int i=0;i<symbols.length;i++)for(int width:new int[]{320,360}){
            double tick=Math.pow(10,-digits[i]);JSONObject f=forecast(symbols[i],"M5",origins[i],tick,digits[i]);
            RecordingCanvas canvas=draw(f,bars("M5",origins[i],tick),bar(T,origins[i],tick),width,width==320?220:420);
            try{assertTrue("Screenshot includes real candle bodies",canvas.candles>30);save(canvas,"r73-chart-"+symbols[i].toLowerCase()+"-"+width);}finally{canvas.bitmap.recycle();}
        }
        for(String variant:new String[]{"history_only","stale","archive","client_offline"}){
            JSONObject f=forecast("EURUSD","M15",1.10324,.00001,5).put(variant,true);
            RecordingCanvas canvas=draw(f,bars("M15",1.10324,.00001),null,320,260);
            try{assertTrue(canvas.candles>30);save(canvas,"r73-chart-"+variant);}finally{canvas.bitmap.recycle();}
        }
        JSONObject f=forecast("EURUSD","M5",1.10324,.00001,5).put("show_price_forecast",false);
        for(int side:new int[]{1,-1})f.getJSONArray("scenarios").put(new JSONObject().put("scenario_id","fixture-"+side)
            .put("name",side>0?"PRIMARY":"ALTERNATIVE").put("title",side>0?"Пробой с подтверждением":"Возврат в диапазон")
            .put("side",side).put("quality_score",side>0?64:58).put("stage","WATCHING").put("event_level",1.10324+side*.00006)
            .put("invalidation",1.10324-side*.00006).put("path",new JSONArray()
                .put(new JSONObject().put("price",1.10324).put("phase","LIVE"))
                .put(new JSONObject().put("price",1.10324+side*.00006).put("phase","PREPARATION").put("label","Проверка"))
                .put(new JSONObject().put("price",1.10324+side*.00010).put("phase","TRADE").put("label","T1"))));
        RecordingCanvas canvas=draw(f,bars("M5",1.10324,.00001),null,320,260);
        try{assertTrue(canvas.candles>30);save(canvas,"r73-chart-two-scenarios");}finally{canvas.bitmap.recycle();}
    }
}
