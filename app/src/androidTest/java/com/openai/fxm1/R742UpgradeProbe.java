package com.openai.fxm1;
import android.content.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;import org.junit.runner.RunWith;import static org.junit.Assert.*;
@RunWith(AndroidJUnit4.class)
public class R742UpgradeProbe {
 private Context c(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
 @Test public void seedOld()throws Exception{
  assertEquals(934,c().getPackageManager().getPackageInfo(c().getPackageName(),0).getLongVersionCode());
  c().getSharedPreferences("fxm1",0).edit().putBoolean("ec1_migrated",true).putString("r742_upgrade_sentinel","keep")
   .putString("ec_token","r742-ci-key-not-real").putString("server_url","http://127.0.0.1:8765")
   .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).commit();
 }
 @Test public void checkNew()throws Exception{
  assertEquals(935,c().getPackageManager().getPackageInfo(c().getPackageName(),0).getLongVersionCode());
  SharedPreferences p=c().getSharedPreferences("fxm1",0);assertEquals("keep",p.getString("r742_upgrade_sentinel",""));
  assertEquals("r742-ci-key-not-real",p.getString("ec_token",""));assertFalse(p.getBoolean("auto_trading",true));assertFalse(p.getBoolean("auto_user_enabled",true));
 }
}
