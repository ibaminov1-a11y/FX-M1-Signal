package com.openai.fxm1;

import android.content.*;
import android.os.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.JSONObject;
import org.junit.*;
import org.junit.runner.RunWith;
import java.io.*;
import java.util.function.BooleanSupplier;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class V11RuntimeTest {
    @Rule public ActivityTestRule<V11Activity> rule=new ActivityTestRule<>(V11Activity.class,false,false);
    Context context; UiDevice device;
    @Before public void prepare() throws Exception {
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        device.wakeUp();device.pressHome();
        context.stopService(new Intent(context,V11Service.class));Thread.sleep(500);
        shell("pm grant "+context.getPackageName()+" android.permission.POST_NOTIFICATIONS");
        V11Api.prefs(context).edit().clear().putString("server","http://10.0.2.2:8000")
                .putString("token","fixture-token-1234567890").commit();
        V11Api.request(context,"POST","/test/reset",new JSONObject());
        rule.launchActivity(new Intent());
        await(()->V11Api.prefs(context).getBoolean("online",false),20000,"Bridge connection");
    }
    void shell(String command) throws Exception {
        try(ParcelFileDescriptor p=InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);
            InputStream in=new ParcelFileDescriptor.AutoCloseInputStream(p)){byte[] b=new byte[4096];while(in.read(b)!=-1){}}
    }
    void await(BooleanSupplier condition,long timeout,String name) throws Exception {
        long end=SystemClock.elapsedRealtime()+timeout;
        while(SystemClock.elapsedRealtime()<end){if(condition.getAsBoolean())return;Thread.sleep(200);}
        fail("Timed out: "+name+" state="+V11Api.state(context)+" error="+V11Api.prefs(context).getString("command_message",""));
    }
    void screenshot(String name) throws Exception {
        shell("mkdir -p /sdcard/Download/v11-qa");
        shell("screencap -p /sdcard/Download/v11-qa/"+name+".png");
    }
    UiObject2 text(String s){return device.wait(Until.findObject(By.text(s)),10000);}
    @Test public void dashboardAndHistoryAreRealViews() throws Exception {
        assertNotNull(text("FX M1   /   NORMAL"));screenshot("01-trading");
        UiObject2 history=text("История");assertNotNull(history);history.click();
        assertNotNull(text("РЕЗУЛЬТАТ БОТА · USD · ДЕНЬ UTC+5"));screenshot("02-history");
        UiObject2 settings=text("Настройки");assertNotNull(settings);settings.click();
        assertNotNull(text("ПОДКЛЮЧЕНИЕ К BRIDGE V11"));screenshot("03-settings");
    }
    @Test public void notificationPlayPauseEmergencyActions() throws Exception {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->rule.getActivity().command("enable",new JSONObject()));
        await(()->V11Api.state(context).optBoolean("auto",false),15000,"AUTO enabled on fixture DEMO");
        device.openNotification();
        UiObject2 pause=text("PAUSE");
        if(pause==null){UiObject2 expand=device.findObject(By.res("android","expand_button"));if(expand!=null)expand.click();pause=text("PAUSE");}
        assertNotNull("Actual notification PAUSE must be visible",pause);
        assertNotNull(text("PLAY"));assertNotNull(text("EMERGENCY STOP"));screenshot("04-notification");
        pause.click();await(()->V11Api.state(context).optBoolean("paused",false),15000,"notification PAUSE");
        assertNotNull(text("PLAY"));text("PLAY").click();await(()->!V11Api.state(context).optBoolean("paused",true),15000,"notification PLAY");
        UiObject2 emergency=text("EMERGENCY STOP");assertNotNull(emergency);emergency.click();Thread.sleep(250);
        text("EMERGENCY STOP").click();
        await(()->V11Api.state(context).optBoolean("emergency",false),15000,"emergency latch on server");
        text("PLAY").click();Thread.sleep(1500);
        assertFalse("PLAY must not re-enable AUTO",V11Api.state(context).optBoolean("auto",true));
        assertTrue(V11Api.prefs(context).getBoolean("local_emergency",false));screenshot("05-emergency");device.pressBack();
    }
    @Test public void emergencyPersistsAcrossServiceRestart() throws Exception {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->context.startForegroundService(new Intent(context,V11Service.class).setAction("EMERGENCY_CONFIRMED")));
        await(()->V11Api.state(context).optBoolean("emergency",false),15000,"initial stop");
        context.stopService(new Intent(context,V11Service.class));Thread.sleep(800);
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->rule.getActivity().startClient());
        await(()->V11Api.prefs(context).getBoolean("online",false),15000,"reconnect");
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->rule.getActivity().command("play",new JSONObject()));
        Thread.sleep(1500);assertFalse(V11Api.state(context).optBoolean("auto",true));assertTrue(V11Api.prefs(context).getBoolean("local_emergency",false));
    }
    @After public void cleanup(){context.stopService(new Intent(context,V11Service.class));}
}
