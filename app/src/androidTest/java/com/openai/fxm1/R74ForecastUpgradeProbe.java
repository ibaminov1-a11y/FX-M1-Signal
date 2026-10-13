package com.openai.fxm1;
import android.content.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;import org.junit.runner.RunWith;import static org.junit.Assert.*;
@RunWith(AndroidJUnit4.class)
public class R74ForecastUpgradeProbe {
 private Context c(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
 @Test public void seedOldSettings()throws Exception{
  assertEquals(934,c().getPackageManager().getPackageInfo(c().getPackageName(),0).getLongVersionCode());
  c().getSharedPreferences("fxm1",0).edit().putBoolean("ec1_migrated",true).putString("f1_upgrade_sentinel","unchanged")
   .putString("ec_token","f1-upgrade-test-token").putString("server_url","http://127.0.0.1:8765")
   .putString("selected_symbol","EUR/USD").putString("entry_tf_name","M5").putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).commit();
 }
 @Test public void verifyPreservedSettings()throws Exception{
  assertEquals(935,c().getPackageManager().getPackageInfo(c().getPackageName(),0).getLongVersionCode());
  SharedPreferences p=c().getSharedPreferences("fxm1",0);assertEquals("unchanged",p.getString("f1_upgrade_sentinel",""));
  assertEquals("f1-upgrade-test-token",p.getString("ec_token",""));assertEquals("EUR/USD",p.getString("selected_symbol",""));
  assertFalse(p.getBoolean("auto_trading",true));assertFalse(p.getBoolean("auto_user_enabled",true));
 }
}
