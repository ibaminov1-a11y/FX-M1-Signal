package com.openai.fxm1;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.os.*;
import android.provider.Settings;
import android.text.InputType;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.text.SimpleDateFormat;
import java.util.*;

public class V11Activity extends Activity {
    // Exact legacy palette. BLUE is the existing UI accent variable, now violet.
    static final int BG=Color.rgb(7,8,22),CARD=Color.rgb(17,18,39),TEXT=Color.rgb(244,241,255),
            MUTED=Color.rgb(176,170,199),BLUE=Color.rgb(145,77,255),GREEN=Color.rgb(66,214,122),RED=Color.rgb(255,72,87);
    private static final Pattern SIDE_WORD=Pattern.compile("\\b(BUY|SELL)\\b",Pattern.CASE_INSENSITIVE);
    static int sideColor(String side){return "BUY".equalsIgnoreCase(side)?GREEN:"SELL".equalsIgnoreCase(side)?RED:BLUE;}
    static CharSequence colorizeSides(CharSequence value){
        SpannableString styled=new SpannableString(value==null?"":value);
        Matcher matcher=SIDE_WORD.matcher(styled);
        while(matcher.find())styled.setSpan(new ForegroundColorSpan(sideColor(matcher.group())),
                matcher.start(),matcher.end(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        return styled;
    }
    private LinearLayout root,body,tabs;
    private TextView connection,signal,reason,money,today,account,action,notice,historyText;
    private CandleChart chart;
    private int page=0;
    private String renderedHistory="";
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final BroadcastReceiver receiver=new BroadcastReceiver(){ @Override public void onReceive(Context c,Intent i){ refresh(); } };
    private final Runnable refreshTick=new Runnable(){ public void run(){ refresh(); handler.postDelayed(this,2000); } };
    int dp(float x){ return Math.round(x*getResources().getDisplayMetrics().density); }
    GradientDrawable shape(int color,int radius){ GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d; }
    TextView text(String s,int size,int color){TextView t=new TextView(this);t.setText(colorizeSides(s));t.setTextSize(size);t.setTextColor(color);t.setFontFeatureSettings("tnum");return t;}
    LinearLayout column(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);return l;}
    LinearLayout card(String label){
        LinearLayout l=column();l.setPadding(dp(18),dp(15),dp(18),dp(15));l.setBackground(shape(CARD,18));
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,0,0,dp(12));body.addView(l,p);
        if(!label.isEmpty()){TextView t=text(label,12,MUTED); t.setLetterSpacing(.06f);l.addView(t);space(l,9);}return l;
    }
    void space(LinearLayout l,int h){View v=new View(this);l.addView(v,new LinearLayout.LayoutParams(1,dp(h)));}
    TextView button(String s,int color,Runnable task){
        TextView b=text(s,14,color);b.setGravity(Gravity.CENTER);b.setPadding(dp(10),dp(10),dp(10),dp(10));
        b.setMinHeight(dp(48));b.setBackground(shape(color==BLUE?Color.rgb(78,37,153):Color.rgb(24,20,48),12));if(color==BLUE)b.setTextColor(TEXT);b.setOnClickListener(v->task.run());b.setFocusable(true);return b;
    }
    void addButton(LinearLayout l,String s,int color,Runnable task){TextView b=button(s,color,task);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.topMargin=dp(8);l.addView(b,p);}
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);getWindow().setStatusBarColor(BG);getWindow().setNavigationBarColor(BG);
        if(!V11Api.prefs(this).contains("server")){
            String old=getSharedPreferences("fxm1",MODE_PRIVATE).getString("server_url","");
            V11Api.prefs(this).edit().putString("server",old).putBoolean("local_emergency",false).commit();
        }
        root=column();root.setBackgroundColor(BG);root.setFitsSystemWindows(true);root.setPadding(dp(16),dp(10),dp(16),0);
        setContentView(root);
        TextView title=text("FX M1   /   NORMAL",20,TEXT);title.setTypeface(null,Typeface.BOLD);root.addView(title);
        TextView version=text("V11.0.1 · DEMO-100 · Purple",12,MUTED);root.addView(version);space(root,12);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setClipToPadding(false);
        body=column();scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        tabs=new LinearLayout(this);tabs.setPadding(0,dp(8),0,dp(10));root.addView(tabs,new LinearLayout.LayoutParams(-1,-2));
        showPage(saved==null?0:saved.getInt("page",0));
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},11);
        if(!V11Api.prefs(this).getString("token","").isEmpty()) startClient();
    }
    @Override protected void onSaveInstanceState(Bundle b){super.onSaveInstanceState(b);b.putInt("page",page);}
    @Override protected void onStart(){super.onStart();IntentFilter f=new IntentFilter(V11Service.UPDATE);if(Build.VERSION.SDK_INT>=33)registerReceiver(receiver,f,Context.RECEIVER_NOT_EXPORTED);else registerReceiver(receiver,f);handler.post(refreshTick);}
    @Override protected void onStop(){handler.removeCallbacks(refreshTick);unregisterReceiver(receiver);super.onStop();}
    void startClient(){try{startForegroundService(new Intent(this,V11Service.class).setAction("START"));}catch(Exception e){dialog("Сервис",V11Api.error(e));}}
    void showPage(int next){
        page=next;body.removeAllViews();tabs.removeAllViews();connection=signal=reason=money=today=account=action=notice=historyText=null;chart=null;renderedHistory="";
        String[] names={"Торговля","История","Настройки"};
        for(int i=0;i<3;i++){final int n=i;TextView b=button(names[i],i==page?TEXT:MUTED,()->showPage(n));
            b.setBackground(shape(i==page?Color.rgb(78,37,153):BG,12));LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,dp(48),1);p.setMargins(dp(2),0,dp(2),0);tabs.addView(b,p);}
        if(page==0) trading(); else if(page==1) history(); else settings();refresh();
    }
    void trading(){
        LinearLayout status=card("");connection=text("Подключите Bridge V11",13,MUTED);status.addView(connection);
        LinearLayout c=card("EUR/USD  ·  M5  ·  ДАННЫЕ MT5");
        signal=text("Ожидание данных",23,TEXT);signal.setTypeface(null,Typeface.BOLD);c.addView(signal);
        chart=new CandleChart(this);c.addView(chart,new LinearLayout.LayoutParams(-1,dp(224)));
        reason=text("Нужен работающий MT5 и Bridge V11",13,MUTED);c.addView(reason);
        LinearLayout campaign=card("ТЕКУЩАЯ КАМПАНИЯ");money=text("— USD",30,TEXT);money.setTypeface(null,Typeface.BOLD);campaign.addView(money);
        account=text("Открытых позиций: —",13,MUTED);campaign.addView(account);space(campaign,9);
        today=text("Сегодня: —\nВсего: —",13,TEXT);campaign.addView(today);
        LinearLayout links=new LinearLayout(this);space(campaign,10);campaign.addView(links);
        TextView h=button("ДЕНЬГИ / ИСТОРИЯ",BLUE,()->showPage(1));links.addView(h,new LinearLayout.LayoutParams(0,-2,1));
        TextView pos=button("Позиции",MUTED,this::positionsDialog);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,-2,.7f);p.leftMargin=dp(8);links.addView(pos,p);
        LinearLayout controls=new LinearLayout(this);body.addView(controls);
        action=button("Включить AUTO",BLUE,this::autoAction);controls.addView(action,new LinearLayout.LayoutParams(0,dp(50),1));
        TextView emergency=button("EMERGENCY STOP",RED,this::emergencyAction);LinearLayout.LayoutParams ep=new LinearLayout.LayoutParams(0,dp(50),1);ep.leftMargin=dp(8);controls.addView(emergency,ep);
        notice=text("",12,MUTED);notice.setPadding(dp(4),dp(10),dp(4),dp(14));body.addView(notice);
    }
    void autoAction(){
        JSONObject s=V11Api.state(this);
        if(!V11Api.prefs(this).getBoolean("online",false)){showPage(2);return;}
        if(s.optBoolean("emergency")||s.optBoolean("recovery")||!s.optString("daily_latch","").isEmpty()||V11Api.prefs(this).getBoolean("local_emergency",false)){
            dialog("AUTO заблокирован","PLAY не снимает аварийный или дневной стоп. Сверка доступна в настройках.");return;}
        if(s.optBoolean("auto")){command(s.optBoolean("paused",true)?"play":"pause",new JSONObject());return;}
        new AlertDialog.Builder(this).setTitle("Включить AUTO только на DEMO?")
                .setMessage("Расчётная база $100. Плановый риск всей кампании до $0,50, дневной порог $2, до пяти позиций.\n\nЭто испытательная версия. Убыточные сделки возможны. При неподходящем минимальном лоте вход будет пропущен.")
                .setNegativeButton("Отмена",null).setPositiveButton("Включить DEMO",(d,w)->command("enable",new JSONObject())).show();
    }
    void emergencyAction(){startForegroundService(new Intent(this,V11Service.class).setAction("EMERGENCY"));Toast.makeText(this,"Для Emergency нажмите дважды за 2,5 секунды",Toast.LENGTH_SHORT).show();}
    void command(String cmd,JSONObject body){startForegroundService(new Intent(this,V11Service.class).setAction("COMMAND").putExtra("command",cmd).putExtra("body",body.toString()));}
    void positionsDialog(){
        JSONObject s=V11Api.state(this);JSONArray a=s.optJSONArray("positions");StringBuilder b=new StringBuilder("Только позиции нашего бота.\n\n");
        if(a==null||a.length()==0)b.append("Открытых позиций нет.");
        else for(int i=0;i<a.length();i++){JSONObject p=a.optJSONObject(i);if(p==null)continue;b.append(p.optString("symbol")).append(" ").append(p.optString("side")).append(" · ").append(p.optDouble("volume")).append(" lot\nВход ").append(price(p.optDouble("price"))).append(" · SL ").append(price(p.optDouble("sl"))).append("\nP/L ").append(cash(p.optDouble("pnl"))).append(" USD\n\n");}
        new AlertDialog.Builder(this).setTitle("Позиции / кампания").setMessage(colorizeSides(b.toString())).setNegativeButton("Назад",null)
                .setPositiveButton("Закрыть кампанию",(d,w)->new AlertDialog.Builder(this).setTitle("Закрыть позиции бота?")
                        .setMessage("Ручные позиции не затрагиваются. AUTO останется заблокирован до явной сверки.")
                        .setNegativeButton("Отмена",null).setPositiveButton("Закрыть",(x,y)->command("close",new JSONObject())).show()).show();
    }
    void history(){
        LinearLayout c=card("РЕЗУЛЬТАТ БОТА · USD · ДЕНЬ UTC+5");today=text("—",15,TEXT);c.addView(today);
        TextView scope=text("Закрытый результат отдельно от плавающего. Включена доступная история прежних сделок бота; DEMO-100 учитывается отдельно.",12,MUTED);space(c,8);c.addView(scope);
        LinearLayout list=card("ПОСЛЕДНИЕ ЗАКРЫТИЯ");historyText=text("Подключите Bridge V11",13,TEXT);historyText.setTextIsSelectable(true);list.addView(historyText);
        addButton(list,"События и диагностика",BLUE,this::eventsDialog);
    }
    void eventsDialog(){
        try{JSONObject h=new JSONObject(V11Api.prefs(this).getString("history","{}"));JSONArray a=h.optJSONArray("events");StringBuilder s=new StringBuilder();
            if(a!=null)for(int i=0;i<a.length();i++){JSONObject e=a.getJSONObject(i);s.append(clock(e.optLong("time"),true)).append(" · ").append(e.optString("kind")).append("\n").append(e.optString("detail")).append("\n\n");}
            dialog("События Bridge",s.length()>0?s.toString():"Пока нет событий");}catch(Exception e){dialog("История",V11Api.error(e));}
    }
    void settings(){
        LinearLayout network=card("ПОДКЛЮЧЕНИЕ К BRIDGE V11");network.addView(text("Без Twelve Data и платных API. MT5 и Bridge работают на компьютере в вашей доверенной сети.",13,MUTED));space(network,10);
        EditText server=new EditText(this);server.setTextColor(TEXT);server.setHintTextColor(MUTED);server.setTextSize(15);server.setSingleLine(true);server.setHint("http://192.168.1.10:8000");server.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);server.setText(V11Api.prefs(this).getString("server",""));network.addView(server);
        EditText token=new EditText(this);token.setTextColor(TEXT);token.setHintTextColor(MUTED);token.setTextSize(15);token.setSingleLine(true);token.setHint("Ключ подключения из окна Bridge V11");token.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);token.setText(V11Api.prefs(this).getString("token",""));network.addView(token);
        addButton(network,"Сохранить и подключить",BLUE,()->{V11Api.prefs(this).edit().putString("server",server.getText().toString().trim()).putString("token",token.getText().toString().trim()).putBoolean("online",false).apply();startClient();Toast.makeText(this,"Проверяю Bridge V11",Toast.LENGTH_SHORT).show();});
        LinearLayout profile=card("ПРОФИЛЬ DEMO-100");profile.addView(text("$100 расчётная база\n$0,50 плановый риск кампании\n$2 дневной порог\n0,01 lot — верхняя граница позиции\nREAL заблокирован на Bridge",15,TEXT));space(profile,10);
        profile.addView(text("Инструмент · RC торгует только EUR/USD",12,MUTED));
        Spinner symbol=new Spinner(this);String[] pairs={"EUR/USD","GBP/USD","USD/JPY","USD/CHF","AUD/USD","USD/CAD","NZD/USD","EUR/JPY","GBP/JPY","EUR/GBP","EUR/CHF","AUD/JPY","CAD/JPY","CHF/JPY","GBP/CHF","EUR/AUD","GBP/AUD","AUD/NZD","NZD/JPY","XAU/USD"};
        ArrayAdapter<String> pairsAdapter=new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,pairs);symbol.setAdapter(pairsAdapter);String selected=V11Api.state(this).optString("symbol","EUR/USD");for(int i=0;i<pairs.length;i++)if(pairs[i].equals(selected))symbol.setSelection(i);profile.addView(symbol);
        profile.addView(text("Максимум позиций: 1–5",12,MUTED));Spinner maximum=new Spinner(this);maximum.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"1","2","3","4","5"}));maximum.setSelection(Math.max(0,Math.min(4,V11Api.state(this).optInt("max_positions",5)-1)));profile.addView(maximum);
        TextView feeLabel=text("Комиссия за полный круг, USD за 1 lot. Укажите 0 только после подтверждения отсутствия комиссии на этом DEMO-счёте. Спред и резерв исполнения считаются отдельно.",12,MUTED);profile.addView(feeLabel);
        EditText fee=new EditText(this);fee.setTextColor(TEXT);fee.setHintTextColor(MUTED);fee.setHint("Комиссия: например 0 или 7");fee.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL);
        JSONObject state=V11Api.state(this);if(state.has("fee_per_lot")&&!state.isNull("fee_per_lot"))fee.setText(String.valueOf(state.optDouble("fee_per_lot")));profile.addView(fee);
        addButton(profile,"Подтвердить профиль DEMO",BLUE,()->{try{JSONObject b=new JSONObject();b.put("symbol",symbol.getSelectedItem().toString());b.put("max_positions",maximum.getSelectedItemPosition()+1);b.put("fee_per_lot",Double.parseDouble(fee.getText().toString().replace(',','.')));command("profile",b);}catch(Exception e){dialog("Профиль","Укажите известную комиссию числом. Неизвестные расходы не считаются нулём.");}});
        addButton(profile,"Выключить AUTO",MUTED,()->command("disable",new JSONObject()));
        LinearLayout safety=card("БЛОКИРОВКИ И УВЕДОМЛЕНИЯ");
        addButton(safety,"Сверить и снять аварийную блокировку",BLUE,()->new AlertDialog.Builder(this).setTitle("Явная сверка состояния")
                .setMessage("Разрешено только без позиций и ордеров бота. Дневной стоп в тот же день не снимается. AUTO после сверки останется выключенным.")
                .setNegativeButton("Отмена",null).setPositiveButton("Сверить",(d,w)->command("reset",new JSONObject())).show());
        addButton(safety,"Системные настройки уведомления",BLUE,()->startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,getPackageName())));
        addButton(safety,"Диагностика",MUTED,()->dialog("Диагностика V11","Android "+Build.VERSION.RELEASE+" · API "+Build.VERSION.SDK_INT+"\n"+Build.MANUFACTURER+" "+Build.MODEL+"\n"+Build.DISPLAY+"\n\n"+V11Api.state(this).optString("reason")+"\n"+V11Api.prefs(this).getString("network_error","")+"\n"+V11Api.prefs(this).getString("command_message","")));
        notice=text("",13,MUTED);body.addView(notice);space(body,20);
    }
    void refresh(){
        JSONObject s=V11Api.state(this);boolean online=V11Api.prefs(this).getBoolean("online",false)&&SystemClock.elapsedRealtime()-V11Api.prefs(this).getLong("received_elapsed",0)<15000;
        boolean healthy=online&&s.optBoolean("ok",false);JSONArray ps=s.optJSONArray("positions");int n=ps==null?0:ps.length();
        if(connection!=null){connection.setText(healthy?"● MT5 подключён   ·   DEMO   ·   база $100":online?"● Bridge доступен · MT5 / данные требуют проверки":"○ Нет связи · сохранённые данные");connection.setTextColor(healthy?GREEN:MUTED);}
        if(signal!=null){String tag=s.optBoolean("emergency")?"Аварийный стоп":n>0?"Кампания · "+n+" / "+s.optInt("max_positions",5):"Ожидание входа";signal.setText(tag);signal.setTextColor(s.optBoolean("emergency")?RED:BLUE);}
        if(reason!=null){String r=online?s.optString("reason","Ожидание MT5"):V11Api.prefs(this).getString("network_error","Откройте настройки и подключите Bridge V11");double stamp=s.optDouble("quote_time",0);r+="\nКотировка: "+(stamp>0?clock((long)stamp,false):"—")+" · источник MT5";reason.setText(colorizeSides(r));}
        if(money!=null){money.setText(s.isNull("floating")||!s.has("floating")?"— USD":cash(s.optDouble("floating"))+" USD");money.setTextColor(!healthy?MUTED:s.optDouble("floating",0)>=0?GREEN:RED);}
        if(account!=null)account.setText("Позиции: "+n+" · расчётный капитал "+String.format(Locale.US,"%.2f",s.optDouble("virtual_equity",100))+" USD\nБаланс MT5: "+(s.has("balance")&&!s.isNull("balance")?String.format(Locale.US,"%.2f",s.optDouble("balance")):"—")+" USD");
        if(today!=null)today.setText("Сегодня: "+summary(s.optJSONObject("today"))+"\nВсего: "+summary(s.optJSONObject("all"))+(healthy?"":"\nСохранённые данные, не свежий результат"));
        if(action!=null)action.setText(s.optBoolean("auto")?(s.optBoolean("paused",true)?"Продолжить":"Пауза"):"Включить AUTO");
        if(notice!=null){String msg=V11Api.prefs(this).getString("command_message","");boolean allowed=getSystemService(NotificationManager.class).areNotificationsEnabled();if(!allowed)msg="Уведомления отключены в системе. Разрешите их в настройках.\n"+msg;notice.setText(msg);}
        if(chart!=null)chart.update(s.optJSONArray("bars"),ps,s.optDouble("bid",0));
        if(historyText!=null){String raw=V11Api.prefs(this).getString("history","{}");if(!raw.equals(renderedHistory)){renderedHistory=raw;try{JSONObject h=new JSONObject(raw);JSONArray a=h.optJSONArray("rows");StringBuilder b=new StringBuilder();if(a!=null)for(int i=0;i<a.length();i++){JSONObject r=a.getJSONObject(i);b.append(clock(r.optLong("time"),true)).append(" · ").append(r.optString("symbol")).append(" ").append(r.optString("side")).append("\n").append(r.optDouble("volume")).append(" lot   ").append(cash(r.optDouble("net"))).append(" USD\n").append("Позиция #").append(r.optLong("position_id")).append("\n\n");}if(b.length()==0)b.append("Закрытий пока нет. История появится после получения данных MT5.");if(h.optInt("total",0)>200)b.append("Показаны последние 200 закрытий. Итоги включают весь доступный период.");historyText.setText(colorizeSides(b.toString()));}catch(Exception e){historyText.setText("Ошибка отображения истории");}}}
    }
    static String cash(double d){return String.format(Locale.US,"%+.2f",d);}
    static String price(double d){return String.format(Locale.US,"%.5f",d);}
    static String summary(JSONObject o){if(o==null)return "—";return cash(o.optDouble("profit"))+" / "+cash(o.optDouble("loss"))+" · итог "+cash(o.optDouble("net"))+" · "+o.optInt("count");}
    static String clock(long seconds,boolean date){SimpleDateFormat f=new SimpleDateFormat(date?"dd.MM HH:mm:ss":"HH:mm:ss",Locale.US);f.setTimeZone(TimeZone.getTimeZone("GMT+05:00"));return f.format(new Date(seconds*1000));}
    void dialog(String title,String message){TextView t=text(message,14,TEXT);t.setTextIsSelectable(true);t.setPadding(dp(20),dp(12),dp(20),dp(12));ScrollView scroll=new ScrollView(this);scroll.addView(t);new AlertDialog.Builder(this).setTitle(title).setView(scroll).setPositiveButton("Закрыть",null).show();}

    final class CandleChart extends View {
        final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);JSONArray bars,positions;double bid;String fingerprint="";
        CandleChart(Context c){super(c);setContentDescription("Свечной график MT5 с входами и стопами");}
        void update(JSONArray b,JSONArray p,double value){String next=String.valueOf(b)+String.valueOf(p)+value;if(next.equals(fingerprint))return;fingerprint=next;bars=b;positions=p;bid=value;invalidate();}
        @Override protected void onDraw(Canvas c){
            super.onDraw(c);paint.setTypeface(Typeface.create("sans-serif",Typeface.NORMAL));paint.setTextSize(dp(10));
            if(bars==null||bars.length()<2){paint.setColor(MUTED);c.drawText("Свечи появятся после подключения MT5",dp(4),getHeight()/2f,paint);return;}
            int start=Math.max(0,bars.length()-45),n=bars.length()-start;double lo=Double.POSITIVE_INFINITY,hi=Double.NEGATIVE_INFINITY;
            for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b!=null){lo=Math.min(lo,b.optDouble("low"));hi=Math.max(hi,b.optDouble("high"));}}
            if(positions!=null)for(int i=0;i<positions.length();i++){JSONObject p=positions.optJSONObject(i);if(p!=null&&p.optDouble("sl")>0){lo=Math.min(lo,p.optDouble("sl"));hi=Math.max(hi,p.optDouble("sl"));}}
            if(!Double.isFinite(lo)||hi<=lo)return;double pad=(hi-lo)*.10;lo-=pad;hi+=pad;
            float left=dp(2),right=getWidth()-dp(62),top=dp(16),bottom=getHeight()-dp(27);float w=(right-left)/n;
            for(int j=0;j<5;j++){float y=top+(bottom-top)*j/4f;paint.setColor(Color.rgb(47,39,67));paint.setStrokeWidth(dp(.5f));c.drawLine(left,y,right,y,paint);paint.setColor(MUTED);c.drawText(price(hi-(hi-lo)*j/4),right+dp(6),y+dp(3),paint);}
            for(int i=start;i<bars.length();i++){JSONObject b=bars.optJSONObject(i);if(b==null)continue;float x=left+(i-start+.5f)*w;double o=b.optDouble("open"),cl=b.optDouble("close");paint.setColor(cl>=o?GREEN:RED);paint.setStrokeWidth(dp(1));
                c.drawLine(x,y(b.optDouble("high"),lo,hi,top,bottom),x,y(b.optDouble("low"),lo,hi,top,bottom),paint);
                float a=y(o,lo,hi,top,bottom),z=y(cl,lo,hi,top,bottom);c.drawRect(x-w*.3f,Math.min(a,z),x+w*.3f,Math.max(Math.min(a,z)+dp(1),Math.max(a,z)),paint);}
            if(positions!=null)for(int i=0;i<positions.length();i++){JSONObject p=positions.optJSONObject(i);if(p==null)continue;for(String field:new String[]{"price","sl"}){double v=p.optDouble(field);if(v<=0)continue;paint.setColor(field.equals("sl")?RED:sideColor(p.optString("side")));paint.setStrokeWidth(dp(1));paint.setPathEffect(new DashPathEffect(new float[]{dp(4),dp(4)},0));float yy=y(v,lo,hi,top,bottom);c.drawLine(left,yy,right,yy,paint);paint.setPathEffect(null);}}
            paint.setColor(MUTED);c.drawText(clock(bars.optJSONObject(start).optLong("time"),false).substring(0,5),left,bottom+dp(18),paint);
            String end=clock(bars.optJSONObject(bars.length()-1).optLong("time"),false).substring(0,5);c.drawText(end,right-dp(32),bottom+dp(18),paint);
        }
        float y(double v,double lo,double hi,float t,float b){return (float)(b-(v-lo)/(hi-lo)*(b-t));}
    }
}
