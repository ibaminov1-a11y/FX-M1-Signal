package com.openai.fxm1;
import android.content.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;import org.junit.runner.RunWith;import static org.junit.Assert.*;
/** Explicit two-install acceptance probe; excluded from automatic *Test discovery. */
@RunWith(AndroidJUnit4.class)
public class R74UpgradeProbe {
 private Context c(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
 @Test public void seedOldSettings()throws Exception{
  assertEquals(933,c().getPackageManager().getPackageInfo(c().getPackageName(),0).getLongVersionCode());
  c().getSharedPreferences("fxm1",0).edit().clear().putBoolean("ec1_migrated",true).putString("r74_upgrade_sentinel","retained-settings")
   .putString("ec_token","ci-upgrade-dummy-not-a-user-key").putString("server_url","http://127.0.0.1:8765")
   .putString("selected_symbol","EUR/USD").putString("entry_tf_name","M5").putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).commit();
 }
 @Test public void verifyPreservedSettingsAfterUpdate()throws Exception{
  assertEquals(934,c().getPackageManager().getPackageInfo(c().getPackageName(),0).getLongVersionCode());
  SharedPreferences p=c().getSharedPreferences("fxm1",0);assertEquals("retained-settings",p.getString("r74_upgrade_sentinel",""));
  assertEquals("ci-upgrade-dummy-not-a-user-key",p.getString("ec_token",""));assertEquals("EUR/USD",p.getString("selected_symbol",""));
  assertFalse(p.getBoolean("auto_trading",true));assertFalse(p.getBoolean("auto_user_enabled",true));
 }
}
