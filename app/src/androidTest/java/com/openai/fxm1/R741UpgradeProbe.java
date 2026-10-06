package com.openai.fxm1;
import android.content.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;import org.junit.runner.RunWith;import static org.junit.Assert.*;
/** Two-install probe, not ordinary test discovery. Synthetic settings only. */
@RunWith(AndroidJUnit4.class)
public class R741UpgradeProbe {
 private Context c(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
 @Test public void seedOldSettings()throws Exception{
  assertEquals(934,c().getPackageManager().getPackageInfo(c().getPackageName(),0).getLongVersionCode());
  c().stopService(new Intent(c(),MonitoringService.class));
  c().getSharedPreferences("fxm1",0).edit().putString("r741_sentinel","retained-settings")
   .putString("ec_token","ci-upgrade-dummy-not-user-key").putString("server_url","http://127.0.0.1:8765")
   .putString("selected_symbol","EUR/USD").putString("entry_tf_name","M5").putString("ec_lot_cap","0.01")
   .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).commit();
  c().getSharedPreferences("fxm1_chart_v1",0).edit().putString("r741_chart_sentinel","retained-chart").commit();
 }
 @Test public void verifyPreservedSettingsAfterUpdate()throws Exception{
  assertEquals(935,c().getPackageManager().getPackageInfo(c().getPackageName(),0).getLongVersionCode());
  SharedPreferences p=c().getSharedPreferences("fxm1",0);
  assertEquals("retained-settings",p.getString("r741_sentinel",""));
  assertEquals("ci-upgrade-dummy-not-user-key",p.getString("ec_token",""));
  assertEquals("http://127.0.0.1:8765",p.getString("server_url",""));
  assertEquals("EUR/USD",p.getString("selected_symbol",""));assertEquals("M5",p.getString("entry_tf_name",""));
  assertEquals("0.01",p.getString("ec_lot_cap",""));
  assertFalse(p.getBoolean("auto_trading",true));assertFalse(p.getBoolean("auto_user_enabled",true));
  assertEquals("retained-chart",c().getSharedPreferences("fxm1_chart_v1",0).getString("r741_chart_sentinel",""));
 }
}
