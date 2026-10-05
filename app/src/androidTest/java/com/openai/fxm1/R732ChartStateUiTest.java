package com.openai.fxm1;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Checks the actual native view rather than a mocked server response. */
@RunWith(AndroidJUnit4.class)
public class R732ChartStateUiTest {
    @Test public void serverForbidsAnalogueAfterRefresh() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        JSONObject forecast=R7ReleaseUiTest.forecast().put("show_price_forecast",false);
        JSONArray history=R7ReleaseUiTest.bars();
        String before=forecast.toString();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
            SparklineView chart=new SparklineView(context);
            chart.layout(0,0,1080,660);
            for(int i=0;i<2;i++)chart.setMarket(history,new JSONArray(),new JSONArray(),new JSONArray(),"SCENARIO_V2",null,new JSONArray(),forecast);
            assertFalse("SERVER_FALSE_OVERRIDDEN: native chart must not re-enable analogue forecast",chart.displayedForecast().optBoolean("show_price_forecast",true));
            assertEquals("Server snapshot mutated",before,forecast.toString());
            Bitmap b=Bitmap.createBitmap(1080,660,Bitmap.Config.ARGB_8888);
            try {
                chart.draw(new Canvas(b));
                for(int y=0;y<b.getHeight();y++)for(int x=540;x<b.getWidth();x++)
                    assertNotEquals("Analogue line painted despite server prohibition",0xff62b6ff,b.getPixel(x,y));
            } finally {b.recycle();}
        });
    }
}
