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
  assertTrue(device.wait(Until.hasObject(By.textContains("Комиссия полного круга")),5000));
  assertFalse(device.hasObject(By.textContains("База DEMO-проверки")));
  assertFalse(device.hasObject(By.textContains("Предел планового риска всей кампании")));
  assertFalse(device.hasObject(By.textContains("Дневной лимит убытка")));
  assertFalse(device.hasObject(By.textContains("Предел последовательных")));
  assertFalse(device.hasObject(By.textContains("Проверить блокировку серии")));
 }
}
