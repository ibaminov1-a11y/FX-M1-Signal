package com.openai.fxm1;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.os.ParcelFileDescriptor;
import android.view.View;
import android.widget.TextView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.ArrayDeque;
import static org.junit.Assert.*;

/** Real Canvas regressions: preparation is not a SELL/BUY prediction or an executed entry. */
@RunWith(AndroidJUnit4.class)
public class R53ScenarioDisplayUiTest {
    private final Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
    private final float density=context.getResources().getDisplayMetrics().density;
    private static final int PREPARATION=0xffaaa7bf,SELL=0xffff4857,BUY=0xff42d67a;
    private static final class Render {Bitmap bitmap;String description;}

    private JSONArray bars()throws Exception{
        JSONArray rows=new JSONArray();
        for(int i=0;i<20;i++)rows.put(new JSONObject().put("time",1800000000L+i*300)
            .put("open",1.1000).put("close",1.1001).put("low",1.0990).put("high",1.1010));
        return rows;
    }
    private JSONObject point(double price,String phase,String anchor)throws Exception{
        return new JSONObject().put("price",price).put("phase",phase).put("anchor",anchor);
    }
    private JSONObject forecast(int side)throws Exception{
        // SELL first rises to the test zone; BUY first falls. Confirmation still belongs to preparation.
        double sign=side<0?1:-1;
        JSONArray path=new JSONArray().put(point(1.1000,"LIVE","LIVE"))
            .put(point(1.1000+sign*.0006,"PREPARATION","TOUCH"))
            .put(point(1.1000+sign*.0003,"PREPARATION","MICRO_CONFIRM"))
            .put(point(1.1000-sign*.0005,"TRADE","TARGET1"));
        JSONObject scenario=new JSONObject().put("scenario_id","live-watch").put("scenario_version",9)
            .put("name","PRIMARY").put("side",side).put("stage","WATCHING").put("status","WATCHING")
            .put("title","Текущая проверка зоны").put("quality_score",71).put("path",path);
        return new JSONObject().put("map_version",3).put("live_price",1.1000)
            .put("scenarios",new JSONArray().put(scenario));
    }
    private Render render(JSONObject f)throws Exception{
        JSONArray history=bars();Render out=new Render();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            SparklineView view=new SparklineView(context);
            int width=Math.round(360*density),height=Math.round(420*density);view.layout(0,0,width,height);
            view.setMarket(history,new JSONArray(),new JSONArray(),new JSONArray(),"SCENARIO_V2",null,null,f);
            out.bitmap=Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888);
            Canvas canvas=new Canvas(out.bitmap);canvas.drawColor(0xff141125);view.draw(canvas);
            out.description=String.valueOf(view.getContentDescription());
        });return out;
    }
    private int count(Render image,int color,int x1,int x2){
        int count=0;
        for(int y=Math.round(80*density);y<Math.round(345*density);y++)
            for(int x=Math.round(x1*density);x<Math.round(x2*density);x++)
                if(image.bitmap.getPixel(x,y)==color)count++;
        return count;
    }
    private int separateStrokes(Render image,int color,int x1,int x2){
        int left=Math.round(x1*density),top=Math.round(80*density),width=Math.round(x2*density)-left,height=Math.round(345*density)-top;
        boolean[] seen=new boolean[width*height];int strokes=0;
        for(int offset=0;offset<seen.length;offset++){
            if(seen[offset]||image.bitmap.getPixel(left+offset%width,top+offset/width)!=color)continue;
            ArrayDeque<Integer> todo=new ArrayDeque<>();todo.add(offset);seen[offset]=true;int size=0;
            while(!todo.isEmpty()){
                int at=todo.removeFirst(),x=at%width,y=at/width;size++;
                for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++){
                    int xx=x+dx,yy=y+dy;if(xx<0||xx>=width||yy<0||yy>=height)continue;int next=yy*width+xx;
                    if(!seen[next]&&image.bitmap.getPixel(left+xx,top+yy)==color){seen[next]=true;todo.add(next);}
                }
            }
            if(size>=3)strokes++;
        }return strokes;
    }
    private void save(Bitmap bitmap,String name)throws Exception{
        File file=new File(context.getExternalFilesDir(null),name+".png");
        try(FileOutputStream out=new FileOutputStream(file)){assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG,100,out));}
        for(String cmd:new String[]{"mkdir -p /sdcard/Download/ec1-qa","cp "+file.getAbsolutePath()+" /sdcard/Download/ec1-qa/"+name+".png"}){
            try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(cmd);
                InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){while(in.read()!=-1){}}
        }
    }
    private void checkPhases(int side,String screenshot)throws Exception{
        Render image=render(forecast(side));int tradeColor=side<0?SELL:BUY;
        try{
            // These x ranges isolate the first preparation segment and final trade segment, away from labels.
            assertTrue("The initial move toward the zone must be neutral",count(image,PREPARATION,148,181)>20);
            assertEquals("Preparation must not inherit the order-side color",0,count(image,tradeColor,148,181));
            assertTrue("Preparation needs distinct dashes separated by gaps",separateStrokes(image,PREPARATION,148,181)>=3);
            assertEquals("The path into confirmation is still preparation",0,count(image,tradeColor,204,231));
            assertTrue("The conditional target segment retains the order-side color",count(image,tradeColor,252,284)>20);
            assertTrue(image.description,image.description.contains("Серый пунктир"));
            assertTrue(image.description,image.description.contains("после подтверждения"));
            assertTrue(image.description,image.description.contains("Наблюдение"));
            save(image.bitmap,screenshot);
        }finally{image.bitmap.recycle();}
    }
    @Test public void sellRisesInNeutralPreparationThenFallsInRed()throws Exception{
        checkPhases(-1,"r53-sell-preparation");
    }
    @Test public void buyFallsInNeutralPreparationThenRisesInGreen()throws Exception{
        checkPhases(1,"r53-buy-preparation");
    }
    @Test public void oldV3AnchorsStillSeparatePreparationFromTargets()throws Exception{
        JSONObject f=forecast(-1);JSONArray path=f.getJSONArray("scenarios").getJSONObject(0).getJSONArray("path");
        for(int i=0;i<path.length();i++)path.getJSONObject(i).remove("phase");
        Render image=render(f);
        try{
            assertTrue("Existing semantic v3 paths remain readable",count(image,PREPARATION,148,181)>20);
            assertEquals(0,count(image,SELL,148,181));
            assertTrue(count(image,SELL,252,284)>20);
        }finally{image.bitmap.recycle();}
    }
    @Test public void phaseWinsOverSegmentSlope()throws Exception{
        JSONObject f=forecast(-1);JSONArray path=f.getJSONArray("scenarios").getJSONObject(0).getJSONArray("path");
        path.getJSONObject(3).put("price",1.1009); // A conditional SELL path is still SELL even when its segment rises.
        Render image=render(f);
        try{
            assertTrue("Trade color expresses scenario side, never local slope",count(image,SELL,252,284)>20);
            assertEquals("Do not relabel a rising SELL target as BUY",0,count(image,BUY,252,284));
        }finally{image.bitmap.recycle();}
    }
    private JSONObject campaignState()throws Exception{
        JSONObject entry=new JSONObject().put("scenario_id","entry-sell-42").put("scenario_version",3)
            .put("side",-1).put("title","Возврат после ложного выхода").put("stage","CONFIRMED")
            .put("target1",1.09870).put("invalidation",1.10180);
        JSONObject wrong=new JSONObject().put("scenario_id","other-frozen-branch").put("title","Чужая ветка");
        JSONObject frozen=new JSONObject().put("map_version",3).put("snapshot_id","entry-snapshot-17")
            .put("entry_scenario_id","entry-sell-42").put("entry_scenario_version",3)
            .put("scenarios",new JSONArray().put(wrong).put(entry));
        JSONObject campaign=new JSONObject().put("side",-1).put("confirmed",true).put("scenario_id","entry-sell-42")
            .put("scenario_version",3).put("snapshot_id","entry-snapshot-17").put("forecast_at_entry",frozen);
        JSONArray positions=new JSONArray().put(new JSONObject().put("volume",.01).put("price_open",1.1002).put("sl",1.1018).put("profit",2));
        return new JSONObject().put("forecast",forecast(-1)).put("campaign",campaign).put("positions",positions);
    }
    @Test public void watchingLiveHypothesisDoesNotReplaceFrozenEntryIdentity()throws Exception{
        JSONObject state=campaignState();String text=ScenarioUi.levels(state);
        assertTrue(text,text.contains("ТЕКУЩИЕ ГИПОТЕЗЫ"));
        assertTrue(text,text.contains("Наблюдение"));
        assertTrue(text,text.contains("СЦЕНАРИЙ ВХОДА"));
        assertTrue(text,text.contains("entry-sell-42"));
        assertTrue(text,text.contains("Версия: 3"));
        assertTrue(text,text.contains("entry-snapshot-17"));
        assertTrue("Find the frozen scenario by identity, not array position",text.contains("Возврат после ложного выхода"));
        assertTrue(text,text.contains("1.09870"));
        assertFalse(text,text.contains("Чужая ветка"));
        String entry=text.substring(text.indexOf("СЦЕНАРИЙ ВХОДА"));
        assertFalse("Current WATCHING is not the recorded entry",entry.contains("Наблюдение"));
        assertFalse(entry.contains("live-watch"));
        assertFalse(entry.contains("Текущая проверка зоны"));
        final Bitmap[] bitmap={null};
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            TextView view=new TextView(context);view.setText(text);view.setTextSize(13);view.setTextColor(0xffeeeeff);
            view.setPadding(24,24,24,24);view.setBackgroundColor(0xff141125);
            int width=Math.round(360*density);view.measure(View.MeasureSpec.makeMeasureSpec(width,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED));
            view.layout(0,0,width,view.getMeasuredHeight());bitmap[0]=Bitmap.createBitmap(width,view.getHeight(),Bitmap.Config.ARGB_8888);view.draw(new Canvas(bitmap[0]));
        });
        try{save(bitmap[0],"r53-live-versus-entry");}finally{bitmap[0].recycle();}
    }
    @Test public void missingFrozenForecastDoesNotBorrowWatchingHypothesis()throws Exception{
        JSONObject state=campaignState();state.getJSONObject("campaign").remove("forecast_at_entry");
        String text=ScenarioUi.levels(state);assertTrue(text,text.contains("СЦЕНАРИЙ ВХОДА"));
        String entry=text.substring(text.indexOf("СЦЕНАРИЙ ВХОДА"));
        assertTrue(entry,entry.contains("entry-sell-42"));
        assertTrue(entry,entry.contains("недоступна"));
        assertFalse(entry,entry.contains("Текущая проверка зоны"));
        assertFalse(entry,entry.contains("Наблюдение"));
    }
    @Test public void entryIdentitySurvivesUnavailableLiveForecast()throws Exception{
        JSONObject state=campaignState();state.remove("forecast");String text=ScenarioUi.levels(state);
        assertTrue("An unavailable live map must not hide the recorded entry",text.contains("entry-sell-42"));
        assertTrue(text,text.contains("entry-snapshot-17"));
    }
}
