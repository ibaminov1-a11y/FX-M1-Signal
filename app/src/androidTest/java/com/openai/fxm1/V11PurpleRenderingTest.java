package com.openai.fxm1;

import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.util.TypedValue;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.File;
import java.io.FileOutputStream;
import static org.junit.Assert.*;

/** Render production views. These tests never connect to a real trading account. */
@RunWith(AndroidJUnit4.class)
public class V11PurpleRenderingTest {
    @Rule public ActivityTestRule<V11Activity> rule=new ActivityTestRule<>(V11Activity.class,false,false);
    private Context context;
    @Before public void prepare() throws Exception {
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        context.stopService(new Intent(context,V11Service.class));
        Thread.sleep(700);
        V11Api.prefs(context).edit().clear().commit();
        rule.launchActivity(new Intent());
    }
    @Test public void oldPaletteAndBuySellTextAreApplied() {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            V11Activity a=rule.getActivity();
            ViewGroup content=a.findViewById(android.R.id.content);
            assertEquals(0xFF070816,((ColorDrawable)content.getChildAt(0).getBackground()).getColor());
            TypedValue accent=new TypedValue();
            assertTrue(a.getTheme().resolveAttribute(android.R.attr.colorAccent,accent,true));
            assertEquals(0xFF914DFF,accent.data);
            TextView label=a.text("BUY / SELL / WAIT",14,V11Activity.MUTED);
            Spanned text=(Spanned)label.getText();
            ForegroundColorSpan[] spans=text.getSpans(0,text.length(),ForegroundColorSpan.class);
            assertEquals(2,spans.length);
            for(ForegroundColorSpan span:spans){
                String word=text.subSequence(text.getSpanStart(span),text.getSpanEnd(span)).toString();
                assertEquals("BUY".equals(word)?0xFF42D67A:0xFFFF4857,span.getForegroundColor());
            }
            assertEquals(0xFF914DFF,V11Activity.sideColor("WAIT"));
        });
    }
    @Test public void actualCandleViewPaintsGreenAndRed() throws Exception {
        JSONArray bars=new JSONArray();
        bars.put(new JSONObject().put("time",1789036200).put("open",1.1000).put("close",1.1010).put("high",1.1012).put("low",1.0998));
        bars.put(new JSONObject().put("time",1789036500).put("open",1.1010).put("close",1.1001).put("high",1.1013).put("low",1.0999));
        final Bitmap[] rendered=new Bitmap[1];
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            V11Activity a=rule.getActivity();
            V11Activity.CandleChart chart=a.new CandleChart(a);
            int width=a.dp(330),height=a.dp(224);
            chart.layout(0,0,width,height);
            chart.update(bars,new JSONArray(),1.1001);
            Bitmap bitmap=Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888);
            Canvas canvas=new Canvas(bitmap);canvas.drawColor(V11Activity.CARD);chart.draw(canvas);
            rendered[0]=bitmap;
        });
        Bitmap bitmap=rendered[0];int green=0,red=0;
        int[] pixels=new int[bitmap.getWidth()*bitmap.getHeight()];
        bitmap.getPixels(pixels,0,bitmap.getWidth(),0,0,bitmap.getWidth(),bitmap.getHeight());
        for(int pixel:pixels){if(pixel==0xFF42D67A)green++;if(pixel==0xFFFF4857)red++;}
        assertTrue("Bullish candle pixels must actually be green",green>100);
        assertTrue("Bearish candle pixels must actually be red",red>100);
        assertEquals(0xFF42D67A,V11Activity.sideColor("BUY"));
        assertEquals(0xFFFF4857,V11Activity.sideColor("SELL"));
        try(FileOutputStream out=new FileOutputStream(new File(context.getExternalFilesDir(null),"purple-candle-render.png"))){
            assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG,100,out));
        }
        bitmap.recycle();
    }
    @Test public void notificationLayoutsArePurpleWithReadableControls() {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            for(int layout:new int[]{R.layout.v11_notification_compact,R.layout.v11_notification_expanded}){
                View view=LayoutInflater.from(context).inflate(layout,null,false);
                assertEquals(0xFF111227,((GradientDrawable)view.getBackground()).getColor().getDefaultColor());
                for(int id:new int[]{R.id.n_play,R.id.n_pause,R.id.n_stop}){
                    TextView control=view.findViewById(id);
                    assertNotNull(control);
                    assertEquals(View.VISIBLE,control.getVisibility());
                    assertEquals(id==R.id.n_stop?0xFFFF4857:0xFFF4F1FF,control.getCurrentTextColor());
                    assertTrue(control.getText().length()>0);
                }
                assertEquals("PLAY",((TextView)view.findViewById(R.id.n_play)).getText().toString());
                assertEquals("PAUSE",((TextView)view.findViewById(R.id.n_pause)).getText().toString());
                assertEquals("EMERGENCY STOP",((TextView)view.findViewById(R.id.n_stop)).getText().toString());
            }
        });
    }
}
