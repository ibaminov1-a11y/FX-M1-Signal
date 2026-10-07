package com.openai.fxm1;
import android.content.Context;
import android.graphics.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.uiautomator.UiDevice;
import org.json.*;import org.junit.Test;import org.junit.runner.RunWith;
import java.io.*;import java.util.*;
import static org.junit.Assert.*;
/** The supplied records are actual Portfolio/Engine replay results with fake MT5. */
@RunWith(AndroidJUnit4.class)
public class R75SeriesUiTest {
 @Test public void engineSeriesSnapshotsKeepPinnedRootAndActualPositionCountVisible()throws Exception{
  Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();JSONArray rows;
  try(InputStream in=InstrumentationRegistry.getInstrumentation().getContext().getAssets().open("r75-series.json")){
   ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] block=new byte[8192];int n;while((n=in.read(block))!=-1)bytes.write(block,0,n);
   rows=new JSONArray(bytes.toString("UTF-8"));
  }
  assertEquals(8,rows.length());Map<Integer,String> roots=new HashMap<>();
  for(int i=0;i<rows.length();i++){
   JSONObject row=rows.getJSONObject(i),state=row.getJSONObject("state");int side=row.getInt("side"),count=row.getInt("count");
   String id=state.getJSONObject("forecast").getJSONObject("execution_plan").getString("plan_id");
   if(count==0)roots.put(side,id);else assertEquals(roots.get(side),id);
   assertEquals(count,state.getJSONArray("positions").length());
   String requirement=ScenarioUi.executionRequirement(state);
   assertTrue("SERIES_PROGRESS_NOT_VISIBLE: "+requirement,requirement.contains("Серия: открыто "+count+" / 10"));
   final Bitmap[] image={null};
   InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
    SparklineView chart=new SparklineView(context);chart.layout(0,0,1080,900);ScenarioUi.populate(chart,state);chart.selectPattern("");chart.goLive();
    JSONObject shown=chart.displayedForecast();assertEquals("EXECUTION",shown.optString("chart_plan_role"));
    assertEquals(id,shown.optJSONArray("scenarios").optJSONObject(0).optString("scenario_id"));
    image[0]=Bitmap.createBitmap(1080,900,Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(image[0]);canvas.drawColor(0xff141125);chart.draw(canvas);
   });
   String name="r75-series-"+(side>0?"buy":"sell")+"-"+count+".png";File out=new File(context.getExternalFilesDir(null),name);
   try(FileOutputStream stream=new FileOutputStream(out)){image[0].compress(Bitmap.CompressFormat.PNG,100,stream);}finally{image[0].recycle();}
   UiDevice device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());device.executeShellCommand("mkdir -p /sdcard/Download/ec1-qa");
   device.executeShellCommand("cp "+out.getAbsolutePath()+" /sdcard/Download/ec1-qa/"+name);
  }
 }
}
