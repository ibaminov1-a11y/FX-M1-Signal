package com.openai.fxm1;

import android.graphics.*;
import android.content.Context;
import android.os.ParcelFileDescriptor;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.lang.reflect.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import static org.junit.Assert.*;

/** Each family consumes the real Python catalog output, not invented display detections. */
@RunWith(AndroidJUnit4.class)
public class R732PatternRendererUiTest {
    static JSONArray fixtures()throws Exception{
        try(InputStream s=InstrumentationRegistry.getInstrumentation().getContext().getAssets().open("r732-pattern-fixtures.json")){
            ByteArrayOutputStream b=new ByteArrayOutputStream();byte[] chunk=new byte[4096];int n;
            while((n=s.read(chunk))!=-1)b.write(chunk,0,n);return new JSONArray(b.toString("UTF-8"));
        }
    }
    static Class<?> cls(String name){
        try{return Class.forName("com.openai.fxm1."+name);}catch(ClassNotFoundException e){fail("NATIVE_PATTERN_LAYER_MISSING: "+name);return null;}
    }
    static Object model(JSONObject state)throws Exception{return cls("PatternChartModel").getDeclaredMethod("fromSnapshot",JSONObject.class).invoke(null,state);}
    static int count(Object model)throws Exception{return (Integer)model.getClass().getDeclaredMethod("size").invoke(model);}
    static JSONObject from(int i)throws Exception{return fixtures().getJSONObject(i);}
    static JSONObject pattern(JSONObject s){JSONObject f=s.optJSONObject("forecast"),catalog=f.optJSONObject("pattern_chart");
        JSONArray ps=catalog.optJSONArray("patterns");String id=f.optString("selected_pattern_id");
        for(int i=0;i<ps.length();i++)if(id.equals(ps.optJSONObject(i).optString("view_id")))return ps.optJSONObject(i);return null;}
    private void verify(int index)throws Exception{
        cls("PatternChartModel");
        JSONObject s=from(index),p=pattern(s);Object m=model(s);assertTrue(count(m)>0);
        JSONArray bars=s.getJSONArray("bars");bars.put(s.getJSONObject("live_bar"));double lo=Double.POSITIVE_INFINITY,hi=0;
        for(int i=0;i<bars.length();i++){lo=Math.min(lo,bars.getJSONObject(i).getDouble("low"));hi=Math.max(hi,bars.getJSONObject(i).getDouble("high"));}
        for(int width:new int[]{320,360,412}){
            PatternTestCanvas c=new PatternTestCanvas(width,500);
            try{
                RectF area=new RectF(12,12,width-12,480);
                Constructor<?> ctor=cls("ChartTransform").getDeclaredConstructor(JSONArray.class,RectF.class,double.class,double.class,float.class);
                Object transform=ctor.newInstance(bars,area,lo-(hi-lo)*.1,hi+(hi-lo)*.1,1f);
                cls("PatternOverlayRenderer").getDeclaredMethod("draw",Canvas.class,cls("PatternChartModel"),cls("ChartTransform"),String.class)
                    .invoke(null,c,m,transform,p.getString("view_id"));
                assertTrue("Actual title missing: "+c.texts,c.hasText(p.getString("title")));
                JSONArray segments=p.getJSONArray("segments");
                for(int j=0;j<segments.length();j++){
                    JSONObject seg=segments.getJSONObject(j);
                    float x1=(Float)transform.getClass().getDeclaredMethod("x",long.class).invoke(transform,seg.getLong("from_time"));
                    float x2=(Float)transform.getClass().getDeclaredMethod("x",long.class).invoke(transform,seg.getLong("to_time"));
                    float y1=(Float)transform.getClass().getDeclaredMethod("y",double.class).invoke(transform,seg.getDouble("from_price"));
                    float y2=(Float)transform.getClass().getDeclaredMethod("y",double.class).invoke(transform,seg.getDouble("to_price"));
                    assertTrue("Geometry uses the same candle transform",c.hasLine(x1,y1,x2,y2));
                }
                String family=p.getString("family");
                if(family.equals("HEAD_SHOULDERS"))for(String t:new String[]{"Левое плечо","Голова","Правое плечо","Линия шеи"})assertTrue(t+" "+c.texts,c.hasText(t));
                if(family.equals("FLAG")||family.equals("PENNANT"))assertTrue(c.hasText("Флагшток"));
                for(int a=0;a<c.textBounds.size();a++)for(int b=a+1;b<c.textBounds.size();b++)assertFalse("Labels overlap: "+c.texts.get(a)+" / "+c.texts.get(b),RectF.intersects(c.textBounds.get(a),c.textBounds.get(b)));
                for(RectF box:c.textBounds)assertTrue("Label outside native view "+box,box.left>=0&&box.right<=width&&box.top>=0&&box.bottom<=500);
                save(c,"r732-pattern-"+index+"-"+width);
            }finally{c.bitmap.recycle();}
        }
    }
    private static void save(PatternTestCanvas c,String name)throws Exception{
        Context ctx=InstrumentationRegistry.getInstrumentation().getTargetContext();File file=new File(ctx.getExternalFilesDir(null),name+".png");
        try(FileOutputStream out=new FileOutputStream(file)){assertTrue(c.bitmap.compress(Bitmap.CompressFormat.PNG,100,out));}
        for(String command:new String[]{"mkdir -p /sdcard/Download/ec1-qa","cp "+file.getAbsolutePath()+" /sdcard/Download/ec1-qa/"+name+".png"})
            try(ParcelFileDescriptor fd=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(fd)){byte[] b=new byte[4096];while(in.read(b)!=-1){}}
    }
    @Test public void formingExtremeUsesDashedObservedGeometry()throws Exception{
        cls("PatternChartModel");
        JSONObject s=from(19),p=pattern(s);Object m=model(s);assertEquals("FORMING",p.getString("geometry_state"));
        JSONArray bars=s.getJSONArray("bars");bars.put(s.getJSONObject("live_bar"));PatternTestCanvas c=new PatternTestCanvas(360,500);
        try{Object tx=cls("ChartTransform").getDeclaredConstructor(JSONArray.class,RectF.class,double.class,double.class,float.class).newInstance(bars,new RectF(10,10,350,480),1.098,1.106,1f);
            cls("PatternOverlayRenderer").getDeclaredMethod("draw",Canvas.class,cls("PatternChartModel"),cls("ChartTransform"),String.class).invoke(null,c,m,tx,p.getString("view_id"));
            assertTrue("Provisional geometry not dashed",c.dashed>0);assertTrue("Preliminary status absent",c.hasText("Формируется"));assertTrue("Provisional point missing question mark",c.hasText("?"));
            save(c,"r732-pattern-forming");
        }finally{c.bitmap.recycle();}
    }
    @Test public void foreignAndFutureOverlayIsRejected()throws Exception{
        cls("PatternChartModel");
        JSONObject s=from(0);assertTrue(count(model(s))>0);
        for(String key:new String[]{"scope","symbol","timeframe","mode","history_clock"}){
            JSONObject wrong=new JSONObject(s.toString());wrong.getJSONObject("forecast").getJSONObject("pattern_chart").put(key,"FOREIGN");
            assertEquals("Identity not rejected: "+key,0,count(model(wrong)));
        }
        JSONObject future=new JSONObject(s.toString());pattern(future).getJSONArray("anchors").getJSONObject(0).put("time",s.getJSONObject("forecast").getDouble("data_asof")+900);
        assertEquals("Future observed anchor accepted",0,count(model(future)));
    }
    @Test public void rendererDoesNotMutateSharedSnapshots()throws Exception{
        cls("PatternChartModel");
        JSONObject s=from(17);String before=s.toString();Object m=model(s);
        assertTrue(count(m)>0);assertEquals(before,s.toString());
    }
    @Test public void ascendingTriangle()throws Exception{verify(0);}
    @Test public void descendingTriangle()throws Exception{verify(1);}
    @Test public void symmetricTriangle()throws Exception{verify(2);}
    @Test public void bullFlag()throws Exception{verify(3);}
    @Test public void bearFlag()throws Exception{verify(4);}
    @Test public void bullPennant()throws Exception{verify(5);}
    @Test public void bearPennant()throws Exception{verify(6);}
    @Test public void risingChannel()throws Exception{verify(7);}
    @Test public void fallingChannel()throws Exception{verify(8);}
    @Test public void rectangle()throws Exception{verify(9);}
    @Test public void risingWedge()throws Exception{verify(10);}
    @Test public void fallingWedge()throws Exception{verify(11);}
    @Test public void broadening()throws Exception{verify(12);}
    @Test public void doubleTop()throws Exception{verify(13);}
    @Test public void tripleTop()throws Exception{verify(14);}
    @Test public void doubleBottom()throws Exception{verify(15);}
    @Test public void tripleBottom()throws Exception{verify(16);}
    @Test public void headShoulders()throws Exception{verify(17);}
    @Test public void inverseHeadShoulders()throws Exception{verify(18);}
}
