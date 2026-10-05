package com.openai.fxm1;

import android.content.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.JSONObject;
import org.junit.*;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class OwnRiskOnlyUiTest {
 @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
 UiDevice device;
 @Before public void prepare(){
  Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();
  c.getSharedPreferences("fxm1",Context.MODE_PRIVATE).edit().clear().putBoolean("ec1_migrated",true).commit();
  EventClient.init(c);device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
  rule.launchActivity(new Intent());
 }
 @Test public void accountWideRiskControlsAreAbsent()throws Exception{
  JSONObject cfg=EventClient.config();
  assertFalse(cfg.has("test_capital"));assertFalse(cfg.has("absolute_risk_cap"));
  assertFalse(cfg.has("daily_loss_pct"));assertFalse(cfg.has("drawdown_pct"));assertFalse(cfg.has("loss_streak"));
  InstrumentationRegistry.getInstrumentation().runOnMainSync(()->rule.getActivity().findViewById(R.id.smartFeaturesButton).performClick());
  assertTrue("Settings dialog must open",device.wait(Until.hasObject(By.text("Умные функции")),5000));
  // The old manual round-trip fee field was replaced before R7.2. Inspect the
  // entire dialog, including controls below the visible engine description.
  UiScrollable dialog=new UiScrollable(new UiSelector().scrollable(true));
  boolean scrollable=dialog.exists();if(scrollable)dialog.scrollToBeginning(20);
  boolean commissionSeen=false,more=false;
  for(int page=0;page<20;page++){
   commissionSeen|=device.hasObject(By.textContains("DEMO-комиссия: автоматически 0"));
   for(String forbidden:new String[]{"База DEMO-проверки","Предел планового риска всей кампании","Дневной лимит убытка","Предел последовательных","Проверить блокировку серии"})
    assertFalse("Forbidden account-wide control: "+forbidden,device.hasObject(By.textContains(forbidden)));
   more=scrollable&&dialog.scrollForward();if(!more)break;
  }
  assertFalse("Inspect every settings page",more);
  assertTrue("Current automatic DEMO commission section remains present",commissionSeen);
 }
}
