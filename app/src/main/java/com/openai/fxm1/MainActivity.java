package com.openai.fxm1;

import android.app.Activity;
import android.app.AlertDialog;
import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.drawable.GradientDrawable;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.widget.*;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {

    private Spinner symbolSpinner, entryTimeframeSpinner, signalModeSpinner;
    private EditText apiKeyInput;
    private TextView statusText, signalText, confidenceText, signalAgeText, levelsText, contextText, apiKeyLabel, whyWaitText, componentScoresText;
    private TextView marketStatusText, marketSessionText;
    private SparklineView sparklineView;
    private QualityBarView qualityBarView;
    private Button analyzeButton, saveKeyButton, serverCheckButton, emergencyStopButton, closeAllButton, smartFeaturesButton, managePositionsButton, moneyHistoryButton;
    private EditText serverUrlInput;
    private TextView serverStatusText, accountText, positionsText, journalText, priceCompareText, serverUrlLabel, smartStatusText, statsText, signalHistoryText, tradeHistoryText;
    private TextView versionBadgeText, smartTitleText, footerVersionText;
    private View serverInputRow;
    private Switch autoTradingSwitch;
    private TextView autoStatusText;
    private Spinner riskSpinner, maxPositionsSpinner, maxDriftSpinner;
    private View topCard, tfCard, modeCard, signalCard, tradingCard, metricsCard, riskCard, journalCard, marketStatusCard, positionsCard, smartCard, bottomNav;
    private ScrollView rootLayout;


    private static final int C_BG = Color.rgb(7, 8, 22);
    private static final int C_CARD = Color.rgb(17, 18, 39);
    private static final int C_CARD_2 = Color.rgb(24, 20, 48);
    private static final int C_PURPLE = Color.rgb(145, 77, 255);
    private static final int C_PURPLE_DARK = Color.rgb(78, 37, 153);
    private static final int C_TEXT = Color.rgb(244, 241, 255);
    private static final int C_MUTED = Color.rgb(176, 170, 199);
    private static final int C_GREEN = Color.rgb(66, 214, 122);
    private static final int C_RED = Color.rgb(255, 72, 87);
    private static final int C_YELLOW = Color.rgb(255, 193, 61);
    private static final int C_ORANGE = Color.rgb(255, 159, 67);

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler monitorHandler = new Handler(Looper.getMainLooper());
    private final Handler serviceUiHandler = new Handler(Looper.getMainLooper());

    private final Runnable serviceUiRunnable = new Runnable() {
        @Override
        public void run() {
            syncUiFromBackgroundService();
            serviceUiHandler.postDelayed(this, 1000L);
        }
    };

    private static final long CACHE_M1_MS = 18000L;
    private static final long CACHE_M5_MS = 2 * 60 * 1000L;
    private static final long CACHE_M15_MS = 7 * 60 * 1000L;
    private static final long CACHE_H1_MS = 30 * 60 * 1000L;
    private static final long CACHE_H4_MS = 90 * 60 * 1000L;
    private static final long CACHE_D1_MS = 6 * 60 * 60 * 1000L;
    private static final long CACHE_W1_MS = 18 * 60 * 60 * 1000L;
    private static final long CACHE_MN1_MS = 24 * 60 * 60 * 1000L;

    private boolean monitoring = false;
    private boolean isAnalyzing = false;
    private boolean serverConnected = false;
    private boolean mt5Connected = false;
    private boolean demoAccount = false;
    private boolean realTradingEnabled = false;
    private boolean suppressAutoSwitch = false;
    private boolean syncingScalpTimeframe = false;
    private long emergencyTapMs = 0L;
    private long lastMoneyRefreshMs = 0L;
    private volatile boolean moneyRefreshInFlight = false;

    private double lastApiPrice = Double.NaN;
    private double lastMt5Bid = Double.NaN;
    private double lastMt5Ask = Double.NaN;

    private final Map<String, String> lastSentSignal = new HashMap<>();

    private final Map<String, CacheItem> cache = new HashMap<>();
    private final Map<String, String> lastAlertSignal = new HashMap<>();

    private final ArrayList<String> symbolItems = new ArrayList<>(Arrays.asList(
            "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
            "EUR/JPY", "GBP/JPY", "EUR/GBP", "EUR/CHF", "AUD/JPY", "CAD/JPY", "CHF/JPY",
            "GBP/CHF", "EUR/AUD", "GBP/AUD", "AUD/NZD", "NZD/JPY", "XAU/USD"
    ));
    private ArrayAdapter<String> symbolAdapter;
    private boolean addingCustomSymbol = false;

    private final Runnable monitorRunnable = new Runnable() {
        @Override
        public void run() {
            if (!monitoring) return;

            if (!isAnalyzing) {
                runAnalysis();
            } else {
                scheduleNext(selectedMonitorIntervalMs());
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        EventClient.init(this);
        setContentView(R.layout.activity_main);

        symbolSpinner = findViewById(R.id.symbolSpinner);
        entryTimeframeSpinner = findViewById(R.id.entryTimeframeSpinner);
        signalModeSpinner = findViewById(R.id.signalModeSpinner);
        apiKeyInput = findViewById(R.id.apiKeyInput);
        apiKeyLabel = findViewById(R.id.apiKeyLabel);
        statusText = findViewById(R.id.statusText);
        signalText = findViewById(R.id.signalText);
        confidenceText = findViewById(R.id.confidenceText);
        signalAgeText = findViewById(R.id.signalAgeText);
        levelsText = findViewById(R.id.levelsText);
        contextText = findViewById(R.id.contextText);
        whyWaitText = findViewById(R.id.whyWaitText);
        componentScoresText = findViewById(R.id.componentScoresText);
        analyzeButton = findViewById(R.id.analyzeButton);
        saveKeyButton = findViewById(R.id.saveKeyButton);
        serverUrlInput = findViewById(R.id.serverUrlInput);
        serverCheckButton = findViewById(R.id.serverCheckButton);
        serverStatusText = findViewById(R.id.serverStatusText);
        versionBadgeText = findViewById(R.id.versionBadgeText);
        smartTitleText = findViewById(R.id.smartTitleText);
        footerVersionText = findViewById(R.id.footerVersionText);
        applyRuntimeVersionLabels();
        serverUrlLabel = findViewById(R.id.serverUrlLabel);
        serverInputRow = findViewById(R.id.serverInputRow);
        accountText = findViewById(R.id.accountText);
        positionsText = findViewById(R.id.positionsText);
        journalText = findViewById(R.id.journalText);
        priceCompareText = findViewById(R.id.priceCompareText);
        autoTradingSwitch = findViewById(R.id.autoTradingSwitch);
        autoStatusText = findViewById(R.id.autoStatusText);
        riskSpinner = findViewById(R.id.riskSpinner);
        maxPositionsSpinner = findViewById(R.id.maxPositionsSpinner);
        maxDriftSpinner = findViewById(R.id.maxDriftSpinner);
        emergencyStopButton = findViewById(R.id.emergencyStopButton);
        closeAllButton = findViewById(R.id.closeAllButton);
        smartFeaturesButton = findViewById(R.id.smartFeaturesButton);
        managePositionsButton = findViewById(R.id.managePositionsButton);
        moneyHistoryButton = findViewById(R.id.moneyHistoryButton);
        marketStatusText = findViewById(R.id.marketStatusText);
        marketSessionText = findViewById(R.id.marketSessionText);
        smartStatusText = findViewById(R.id.smartStatusText);
        statsText = findViewById(R.id.statsText);
        signalHistoryText = findViewById(R.id.signalHistoryText);
        tradeHistoryText = findViewById(R.id.tradeHistoryText);
        sparklineView = findViewById(R.id.sparklineView);
        qualityBarView = findViewById(R.id.qualityBarView);
        rootLayout = findViewById(R.id.rootLayout);

        topCard = findViewById(R.id.topCard);
        tfCard = findViewById(R.id.tfCard);
        modeCard = findViewById(R.id.modeCard);
        signalCard = findViewById(R.id.signalCard);
        tradingCard = findViewById(R.id.tradingCard);
        metricsCard = findViewById(R.id.metricsCard);
        riskCard = findViewById(R.id.riskCard);
        journalCard = findViewById(R.id.journalCard);
        marketStatusCard = findViewById(R.id.marketStatusCard);
        positionsCard = findViewById(R.id.positionsCard);
        smartCard = findViewById(R.id.smartCard);
        bottomNav = findViewById(R.id.bottomNav);

        applyDarkVioletTheme();
        if (modeCard != null) modeCard.setVisibility(View.VISIBLE);
        updateMarketStatusUi();

        loadSyncedMt5Symbols();
        loadCustomSymbols();
        if (!symbolItems.contains("＋ ДОБАВИТЬ ИНСТРУМЕНТ")) symbolItems.add("＋ ДОБАВИТЬ ИНСТРУМЕНТ");
        symbolAdapter = darkSpinnerAdapter(symbolItems.toArray(new String[0]));
        symbolSpinner.setAdapter(symbolAdapter);

        ArrayAdapter<String> timeframeAdapter = darkSpinnerAdapter(
                new String[]{"M1", "M5", "M10", "M15", "H1", "H4", "D1", "W1", "MN1"}
        );
        entryTimeframeSpinner.setAdapter(timeframeAdapter);

        ArrayAdapter<String> modeAdapter = darkSpinnerAdapter(
                new String[]{"NORMAL", "SCALP"}
        );
        signalModeSpinner.setAdapter(modeAdapter);

        SharedPreferences prefs = getSharedPreferences("fxm1", MODE_PRIVATE);
        FeatureEngine.ensureDefaults(prefs);
        if (!prefs.getBoolean("v108_initial_review",false)) prefs.edit().putBoolean("v108_initial_review",true)
            .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).apply();
        monitoring = prefs.getBoolean("bg_running", false);
        String savedSymbol = prefs.getString("selected_symbol", "EUR/USD");
        int savedSymbolIndex = symbolItems.indexOf(savedSymbol);
        symbolSpinner.setSelection(savedSymbolIndex >= 0 ? savedSymbolIndex : 0);
        int savedTfPos = prefs.getInt("entry_tf_pos", 1);
        if (!prefs.getBoolean("v800_tf_migrated", false)) {
            // V8.0 inserts M10 at index 2; migrate old M15+ saved indices by +1.
            if (savedTfPos >= 2) savedTfPos += 1;
            prefs.edit().putInt("entry_tf_pos", savedTfPos).putBoolean("v800_tf_migrated", true).apply();
        }
        entryTimeframeSpinner.setSelection(Math.max(0, Math.min(savedTfPos, 8)));
        signalModeSpinner.setSelection(Math.max(0,Math.min(1,prefs.getInt("signal_mode_pos",0))));
        apiKeyInput.setText(prefs.getString("ec_token", ""));
        serverUrlInput.setText(stripServerScheme(prefs.getString("server_url", "")));
        setApiKeyEditMode(prefs.getString("ec_token", "").trim().isEmpty());
        boolean savedServerVerified = prefs.getBoolean("server_verified", false)
                && !prefs.getString("server_url", "").trim().isEmpty();
        setServerEditMode(!savedServerVerified);

        ArrayAdapter<String> riskAdapter = darkSpinnerAdapter(
                new String[]{"0.25%", "0.50%", "1.00%"}
        );
        riskSpinner.setAdapter(riskAdapter);
        riskSpinner.setSelection(prefs.getInt("risk_pos", 0));

        ArrayAdapter<String> maxPosAdapter = darkSpinnerAdapter(
                new String[]{"По риску", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}
        );
        maxPositionsSpinner.setAdapter(maxPosAdapter);
        maxPositionsSpinner.setSelection(prefs.getInt("ec_limit", 0));

        ArrayAdapter<String> driftAdapter = darkSpinnerAdapter(
                new String[]{"0.03%", "0.05%", "0.10%", "0.20%"}
        );
        maxDriftSpinner.setAdapter(driftAdapter);
        maxDriftSpinner.setSelection(prefs.getInt("maxdrift_pos", 1));

        analyzeButton.setText(monitoring ? "ОСТАНОВИТЬ МОНИТОРИНГ" : "ЗАПУСТИТЬ МОНИТОРИНГ");
        restoreTradingSnapshotFromPrefs();

        saveKeyButton.setOnClickListener(v -> {
            boolean editing = apiKeyInput.getVisibility() == View.VISIBLE;

            if (!editing) {
                setApiKeyEditMode(true);
                apiKeyInput.requestFocus();
                return;
            }

            String key = apiKeyInput.getText().toString().trim();
            if (key.isEmpty()) {
                Toast.makeText(this, "Введите ключ EventCore из окна Bridge", Toast.LENGTH_SHORT).show();
                return;
            }

            prefs.edit().putString("ec_token", key).apply();
            setApiKeyEditMode(false);

            if (getSharedPreferences("fxm1", MODE_PRIVATE).getBoolean("bg_running", false)) {
                sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
            }
            Toast.makeText(this, "Ключ Bridge сохранён", Toast.LENGTH_SHORT).show();
        });

        analyzeButton.setOnClickListener(v -> {
            if (monitoring) {
                stopMonitoring();
            } else {
                startMonitoring();
            }
        });

        serverCheckButton.setOnClickListener(v -> showServerAddressDialog());

        riskSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                prefs.edit().putInt("risk_pos", position).putString("risk_label", String.valueOf(riskSpinner.getSelectedItem())).apply();
                if(monitoring)sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

        maxPositionsSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                prefs.edit().putInt("ec_limit", position).putString("maxpos_label", String.valueOf(maxPositionsSpinner.getSelectedItem())).apply();
                if(monitoring)sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });


        symbolSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                String selected = String.valueOf(symbolSpinner.getSelectedItem());
                if ("＋ ДОБАВИТЬ ИНСТРУМЕНТ".equals(selected)) {
                    if (!addingCustomSymbol) showAddSymbolDialog();
                    return;
                }
                prefs.edit().putInt("symbol_pos", position).putString("selected_symbol", selected).apply();
                lastSentSignal.clear();
                lastAlertSignal.clear();

                if (getSharedPreferences("fxm1", MODE_PRIVATE).getBoolean("bg_running", false)) {
                    sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
                }
            }

            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

        entryTimeframeSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){
            public void onItemSelected(AdapterView<?> parent,View view,int position,long id){
                prefs.edit().putInt("entry_tf_pos",position).apply();
                if(monitoring)sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
            }
            public void onNothingSelected(AdapterView<?> parent){}
        });
        signalModeSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){
            public void onItemSelected(AdapterView<?> parent,View view,int position,long id){
                prefs.edit().putInt("signal_mode_pos",position).apply();
                if(monitoring)sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
            }
            public void onNothingSelected(AdapterView<?> parent){}
        });
        maxDriftSpinner.setEnabled(false);
        autoTradingSwitch.setOnCheckedChangeListener((buttonView,isChecked)->{
            if(suppressAutoSwitch)return;
            if(!isChecked){eventCommand("disable",new JSONObject());return;}
            suppressAutoSwitch=true;autoTradingSwitch.setChecked(false);suppressAutoSwitch=false;
            if(prefs.getBoolean("v108_emergency_latched",false)){
                new AlertDialog.Builder(this).setTitle("Аварийная блокировка")
                    .setMessage("PLAY и AUTO не снимают Emergency. Выполните явную сверку в настройках.")
                    .setPositiveButton("OK",null).show();return;
            }
            new AlertDialog.Builder(this).setTitle("Разрешить AUTO только на DEMO?")
                .setMessage("Источник — MT5. Первый вход после отката и нового триггера. Добавления только в плюс и в пределах общего риска.\n\nБаза проверки риска: "+prefs.getString("ec_test_capital","100")+" USD (0 = фактический счёт). Предел кампании: "+prefs.getString("ec_risk_cap","0.50")+" USD. Баланс MT5 не подменяется. Комиссию укажите в настройках.")
                .setNegativeButton("Отмена",null).setPositiveButton("Подтвердить DEMO",(d,w)->executor.execute(()->{
                    try{EventClient.configure();EventClient.command("approve_profile",new JSONObject().put("confirmation","APPROVE_DEMO_RISK"));
                        JSONObject out=EventClient.command("enable",new JSONObject().put("confirmation","ENABLE_DEMO"));EventClient.poll();
                        runOnUiThread(()->{addJournal(out.optString("message"));startUnifiedMonitoringService();});
                    }catch(Exception e){runOnUiThread(()->new AlertDialog.Builder(this).setTitle("AUTO не включён").setMessage(safeMessage(e)).setPositiveButton("OK",null).show());}
                })).show();
        });

        emergencyStopButton.setOnClickListener(v -> {
            long now = System.currentTimeMillis();
            if (now - emergencyTapMs > 2500L) {
                emergencyTapMs = now;
                Toast.makeText(this, "EMERGENCY STOP: нажмите ещё раз в течение 2,5 сек", Toast.LENGTH_LONG).show();
                return;
            }
            emergencyTapMs = 0L;
            executeEmergencyStop();
        });

        closeAllButton.setOnClickListener(v -> sendCloseAll());
        smartFeaturesButton.setOnClickListener(v -> showSmartFeaturesDialog());
        managePositionsButton.setOnClickListener(v -> showPositionManagementHub());
        if (moneyHistoryButton != null) moneyHistoryButton.setOnClickListener(v -> showMoneyHistoryDialog());
        if (positionsCard != null) positionsCard.setOnClickListener(v -> showMoneyHistoryDialog());
        if (journalCard != null) journalCard.setOnClickListener(v -> showTradeJournalDialog());
        // V7.5.1: the entire analytics area opens as a full scrollable window.
        if (statsText != null) statsText.setOnClickListener(v -> showTradeJournalDialog());
        if (signalHistoryText != null) signalHistoryText.setOnClickListener(v -> showTradeJournalDialog());
        if (tradeHistoryText != null) tradeHistoryText.setOnClickListener(v -> showTradeJournalDialog());
        refreshSmartUi();

        // UI ticker: обновляет «прошло» каждую секунду без новых API-запросов.
        serviceUiHandler.removeCallbacks(serviceUiRunnable);
        serviceUiHandler.post(serviceUiRunnable);
        setupBottomNavigation();

    }


    private void setupBottomNavigation() {
        View overview = findViewById(R.id.navOverview);
        View positions = findViewById(R.id.navPositions);
        View signals = findViewById(R.id.navSignals);
        View journal = findViewById(R.id.navJournal);
        View settings = findViewById(R.id.navSettings);
        if (overview != null) overview.setOnClickListener(v -> scrollToView(topCard));
        if (positions != null) positions.setOnClickListener(v -> scrollToView(positionsCard));
        if (signals != null) signals.setOnClickListener(v -> scrollToView(signalCard));
        if (journal != null) journal.setOnClickListener(v -> showTradeJournalDialog());
        if (settings != null) settings.setOnClickListener(v -> scrollToView(tradingCard));
    }

    private void scrollToView(View target) {
        if (target == null) return;
        ScrollView root = findViewById(R.id.rootLayout);
        if (root == null) return;
        root.post(() -> root.smoothScrollTo(0, Math.max(0, target.getTop() - dp(12))));
    }

    private void applyDarkVioletTheme() {
        getWindow().setStatusBarColor(C_BG);
        getWindow().setNavigationBarColor(C_BG);

        int uiFlags = getWindow().getDecorView().getSystemUiVisibility();
        uiFlags &= ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            uiFlags &= ~View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        }
        getWindow().getDecorView().setSystemUiVisibility(uiFlags);


        styleCard(topCard, C_CARD);
        styleCard(tfCard, C_CARD_2);
        styleCard(modeCard, C_CARD_2);
        styleCard(signalCard, C_CARD);
        styleCard(tradingCard, C_CARD);
        styleCard(metricsCard, C_CARD);
        styleCard(riskCard, C_CARD);
        styleCard(journalCard, C_CARD);
        styleCard(marketStatusCard, C_CARD);
        styleCard(positionsCard, C_CARD);
        styleCard(smartCard, C_CARD);
        styleCard(bottomNav, Color.rgb(10, 12, 28));

        stylePrimaryButton(saveKeyButton);
        stylePrimaryButton(analyzeButton);
        styleOutlineButton(serverCheckButton, C_PURPLE);
        styleOutlineButton(closeAllButton, C_PURPLE);
        styleOutlineButton(emergencyStopButton, C_RED);
        styleOutlineButton(smartFeaturesButton, C_PURPLE);
        styleOutlineButton(managePositionsButton, C_PURPLE);
        if (moneyHistoryButton != null) styleOutlineButton(moneyHistoryButton, C_PURPLE);

        styleInput(apiKeyInput);
        styleInput(serverUrlInput);

        int[][] states = new int[][]{
                new int[]{android.R.attr.state_checked},
                new int[]{}
        };
        autoTradingSwitch.setThumbTintList(new ColorStateList(
                states,
                new int[]{C_PURPLE, Color.rgb(205, 202, 218)}
        ));
        autoTradingSwitch.setTrackTintList(new ColorStateList(
                states,
                new int[]{Color.rgb(83, 49, 145), Color.rgb(61, 61, 78)}
        ));
        autoTradingSwitch.setTextColor(C_TEXT);

        signalText.setTextColor(C_PURPLE);
        statusText.setTextColor(C_MUTED);
        confidenceText.setTextColor(C_MUTED);
        levelsText.setTextColor(C_TEXT);
        contextText.setTextColor(C_MUTED);
        accountText.setTextColor(C_TEXT);
        positionsText.setTextColor(C_TEXT);
        journalText.setTextColor(C_MUTED);
        priceCompareText.setTextColor(C_TEXT);
        serverStatusText.setTextColor(C_RED);
        if (whyWaitText != null) whyWaitText.setTextColor(C_ORANGE);
        if (componentScoresText != null) componentScoresText.setTextColor(C_PURPLE);
        if (smartStatusText != null) smartStatusText.setTextColor(C_MUTED);
        if (statsText != null) statsText.setTextColor(C_TEXT);
        if (signalHistoryText != null) signalHistoryText.setTextColor(C_MUTED);
    }

    private ArrayAdapter<String> darkSpinnerAdapter(String[] items) {
        return new ArrayAdapter<String>(
                this,
                android.R.layout.simple_spinner_item,
                items
        ) {
            @Override
            public View getView(int position, View convertView, android.view.ViewGroup parent) {
                TextView view = (TextView) super.getView(position, convertView, parent);
                view.setTextColor(C_TEXT);
                view.setTextSize(17f);
                view.setPadding(dp(8), 0, dp(8), 0);
                return view;
            }

            @Override
            public View getDropDownView(int position, View convertView, android.view.ViewGroup parent) {
                TextView view = (TextView) super.getDropDownView(position, convertView, parent);
                view.setTextColor(C_TEXT);
                view.setTextSize(16f);
                view.setPadding(dp(16), dp(14), dp(16), dp(14));
                view.setBackgroundColor(C_CARD_2);
                return view;
            }
        };
    }

    private void styleCard(View view, int fillColor) {
        if (view == null) return;
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(fillColor);
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), Color.rgb(72, 58, 111));
        view.setBackground(bg);
        view.setElevation(dp(2));
    }

    private void stylePrimaryButton(Button button) {
        GradientDrawable bg = new GradientDrawable(
                GradientDrawable.Orientation.LEFT_RIGHT,
                new int[]{Color.rgb(116, 48, 231), Color.rgb(77, 37, 151)}
        );
        bg.setCornerRadius(dp(10));
        bg.setStroke(dp(1), Color.rgb(159, 99, 255));
        button.setBackground(bg);
        button.setTextColor(Color.WHITE);
    }

    private void styleOutlineButton(Button button, int accent) {
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.rgb(13, 13, 30));
        bg.setCornerRadius(dp(9));
        bg.setStroke(dp(1), accent);
        button.setBackground(bg);
        button.setTextColor(accent);
    }

    private void styleInput(EditText input) {
        input.setTextColor(C_TEXT);
        input.setHintTextColor(Color.rgb(205, 199, 224));
        input.setBackgroundTintList(ColorStateList.valueOf(C_PURPLE));
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void setTradingControlsOffline() {
        serverConnected = false;
        mt5Connected = false;
        demoAccount = false;
        serverStatusText.setText("SERVER: NOT CONNECTED   •   MT5: OFFLINE");
        serverStatusText.setTextColor(C_RED);
        if (whyWaitText != null) whyWaitText.setTextColor(C_ORANGE);
        if (componentScoresText != null) componentScoresText.setTextColor(C_PURPLE);
        if (smartStatusText != null) smartStatusText.setTextColor(C_MUTED);
        if (statsText != null) statsText.setTextColor(C_TEXT);
        if (signalHistoryText != null) signalHistoryText.setTextColor(C_MUTED);
        accountText.setText("Счёт: —\nБаланс: —\nEquity: —");
        positionsText.setText("Открытые позиции: —\nТекущий P/L: —\nСегодня: —\nВсего: —");
        lastMt5Bid = Double.NaN;
        lastMt5Ask = Double.NaN;
        updatePriceComparison();
        closeAllButton.setEnabled(false);
        forceAutoOff(null);
    }

    private String targetTradeMode() { return "DEMO"; }

    private boolean currentAccountAllowedForAuto() {
        if (!serverConnected || !mt5Connected) return false;
        String target = targetTradeMode();
        if ("REAL".equals(target)) return !demoAccount && realTradingEnabled;
        return demoAccount;
    }

    private String appVersionName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "7.5.0";
        }
    }

    private void applyRuntimeVersionLabels() {
        String v = appVersionName();
        if (versionBadgeText != null) versionBadgeText.setText("V" + v);
        if (smartTitleText != null) smartTitleText.setText("УМНЫЕ ФУНКЦИИ V" + v);
        if (footerVersionText != null) footerVersionText.setText("V" + v + " · SCALP / NORMAL · EVENT CORE · MT5");
    }

    private void forceAutoOff(String journalMessage) {
        suppressAutoSwitch=true;autoTradingSwitch.setChecked(false);suppressAutoSwitch=false;
        SharedPreferences p=getSharedPreferences("fxm1",MODE_PRIVATE);boolean was=p.getBoolean("auto_user_enabled",false);
        p.edit().putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).apply();
        if(was)eventCommand("disable",new JSONObject());
        if(journalMessage!=null)addJournal(journalMessage);
    }

    private void restoreTradingSnapshotFromPrefs() {
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        String savedUrl = p.getString("server_url", "").trim();
        boolean verified = p.getBoolean("server_verified", false) && !savedUrl.isEmpty();
        boolean mt5 = p.getBoolean("mt5_connected_snapshot", false);
        String accountType = p.getString("mt5_account_type_snapshot", "UNKNOWN");
        String currency = p.getString("mt5_currency_snapshot", "USD");
        String bridgeVersion = p.getString("bridge_version_snapshot", "?");
        realTradingEnabled = p.getBoolean("bridge_real_enabled_snapshot", false);
        double balance = Double.longBitsToDouble(p.getLong("mt5_balance_bits", Double.doubleToLongBits(Double.NaN)));
        double equity = Double.longBitsToDouble(p.getLong("mt5_equity_bits", Double.doubleToLongBits(Double.NaN)));
        int positions = p.getInt("mt5_positions_snapshot", 0);
        double floating = Double.longBitsToDouble(p.getLong("mt5_floating_bits", Double.doubleToLongBits(0.0)));

        boolean profileEditable=EventClient.state().optJSONObject("campaign")==null;
        for(Spinner control:new Spinner[]{symbolSpinner,entryTimeframeSpinner,signalModeSpinner,riskSpinner,maxPositionsSpinner})if(control!=null)control.setEnabled(profileEditable);
        if (verified) {
            serverConnected = true;
            mt5Connected = mt5;
            demoAccount = "DEMO".equalsIgnoreCase(accountType);
            serverStatusText.setText("APP V" + appVersionName() + "   •   BRIDGE V" + bridgeVersion + "\nSERVER: CONNECTED   •   MT5: " + (mt5 ? "CONNECTED" : "OFFLINE"));
            serverStatusText.setTextColor(mt5 ? C_GREEN : C_RED);
            accountText.setText("Счёт: " + accountType + "\nБаланс: " + money(balance, currency) + "\nEquity: " + money(equity, currency));
            renderPositionsMoneyCard(positions, floating, currency);
            closeAllButton.setEnabled(mt5 && positions > 0);
            suppressAutoSwitch = true;
            boolean targetAllowed = "REAL".equals(targetTradeMode()) ? (!demoAccount && realTradingEnabled) : demoAccount;
            boolean autoSaved = !p.getBoolean("v108_emergency_latched", false) && p.getBoolean("auto_user_enabled", p.getBoolean("auto_trading", false)) && mt5 && targetAllowed;
            autoTradingSwitch.setChecked(autoSaved);
            p.edit().putBoolean("auto_trading", autoSaved).apply();
            suppressAutoSwitch = false;
        } else {
            setTradingControlsOffline();
        }
    }

    private void restoreSparklineFromPrefs(String signal) {
        if(sparklineView==null)return;
        JSONObject s=EventClient.state(),d=s.optJSONObject("decision");
        sparklineView.setMarket(s.optJSONArray("bars"),d==null?null:d.optJSONArray("levels"),s.optJSONArray("positions"));
        sparklineView.setSignal(signal);
    }

    private String stripServerScheme(String raw) {
        if (raw == null) return "";
        String u = raw.trim();
        if (u.startsWith("http://")) return u.substring(7);
        if (u.startsWith("https://")) return u.substring(8);
        return u;
    }

    private String normalizeServerUrl(String raw) {
        String u = raw == null ? "" : raw.trim();
        if (u.isEmpty()) return "";
        if (!u.startsWith("http://") && !u.startsWith("https://")) {
            if (u.matches("^\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d+$")) {
                int lastDot = u.lastIndexOf('.');
                u = u.substring(0, lastDot) + ":" + u.substring(lastDot + 1);
            }
            u = "http://" + u;
        }
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }

    private void checkServer() {
        final String base = normalizeServerUrl(serverUrlInput.getText().toString());
        if (base.isEmpty()) {
            Toast.makeText(this, "Адрес сервера пока пуст", Toast.LENGTH_SHORT).show();
            return;
        }
        serverUrlInput.setText(stripServerScheme(base));
        getSharedPreferences("fxm1", MODE_PRIVATE).edit()
                .putString("server_url", base)
                .putBoolean("server_verified", false)
                .apply();
        serverCheckButton.setEnabled(false);
        serverStatusText.setText("SERVER: CHECKING…   •   MT5: …");
        serverStatusText.setTextColor(C_YELLOW);

        executor.execute(() -> {
            try {
                JSONObject root = httpJson("GET", base + "/health", null);
                boolean serverOk = root.optBoolean("ok", false);
                boolean mt5Ok = root.optBoolean("mt5_connected", false);
                String accountType = root.optString("account_type", "UNKNOWN").toUpperCase(Locale.US);
                double balance = root.optDouble("balance", Double.NaN);
                double equity = root.optDouble("equity", Double.NaN);
                int positions = root.optInt("positions", 0);
                double floating = root.optDouble("floating_pl", 0.0);
                String currency = root.optString("currency", "USD");
                String bridgeVersion = root.optString("bridge_version", "?");
                boolean bridgeRealEnabled = root.optBoolean("real_trading_enabled", false);
                boolean versionMatch = ExecutionFeedback.bridgeCompatible(bridgeVersion);

                runOnUiThread(() -> {
                    serverCheckButton.setEnabled(true);
                    serverConnected = serverOk;
                    mt5Connected = mt5Ok;
                    demoAccount = "DEMO".equals(accountType);
                    realTradingEnabled = bridgeRealEnabled;

                    serverStatusText.setText(
                            "APP V" + appVersionName() + "   •   BRIDGE V" + bridgeVersion + "\n" +
                            (versionMatch ? "" : "⚠ VERSION MISMATCH · AUTO BLOCKED\n") +
                            "SERVER: " + (serverOk ? "CONNECTED" : "ERROR") +
                            "   •   MT5: " + (mt5Ok ? "CONNECTED" : "OFFLINE")
                    );
                    serverStatusText.setTextColor(
                            serverOk && mt5Ok && versionMatch ? C_GREEN : C_RED
                    );

                    if (serverOk && mt5Ok) {
                        getSharedPreferences("fxm1", MODE_PRIVATE).edit().putBoolean("server_verified", true).apply();
                        setServerEditMode(false);
                    } else {
                        getSharedPreferences("fxm1", MODE_PRIVATE).edit().putBoolean("server_verified", false).apply();
                        setServerEditMode(true);
                    }

                    accountText.setText(
                            "Счёт: " + accountType +
                            "\nБаланс: " + money(balance, currency) +
                            "\nEquity: " + money(equity, currency)
                    );
                    renderPositionsMoneyCard(positions, floating, currency);
                    getSharedPreferences("fxm1", MODE_PRIVATE).edit()
                            .putBoolean("mt5_connected_snapshot", serverOk && mt5Ok)
                            .putString("mt5_account_type_snapshot", accountType)
                            .putLong("mt5_balance_bits", Double.doubleToLongBits(balance))
                            .putLong("mt5_equity_bits", Double.doubleToLongBits(equity))
                            .putString("mt5_currency_snapshot", currency)
                            .putString("bridge_version_snapshot", bridgeVersion)
                            .putBoolean("bridge_version_match_snapshot", versionMatch)
                            .putBoolean("bridge_real_enabled_snapshot", bridgeRealEnabled)
                            .putInt("mt5_positions_snapshot", positions)
                            .putLong("mt5_floating_bits", Double.doubleToLongBits(floating))
                            .apply();
                    closeAllButton.setEnabled(serverOk && mt5Ok && positions > 0);

                    if (!serverOk || !mt5Ok || !versionMatch || !("REAL".equals(targetTradeMode()) ? (!demoAccount && realTradingEnabled) : demoAccount)) {
                        forceAutoOff(versionMatch ? null : "AUTO заблокирован: APP/BRIDGE версии не совпадают");
                    }
                    addJournal(serverOk && mt5Ok
                            ? "Связь с MT5 установлена · " + accountType + " · Bridge V" + bridgeVersion
                            : "Сервер ответил, MT5 пока не готов");

                    if (serverOk && mt5Ok) {
                        refreshMt5Quote((String) symbolSpinner.getSelectedItem());
                        refreshStatsAndPositions();
                    }
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    serverCheckButton.setEnabled(true);
                    getSharedPreferences("fxm1", MODE_PRIVATE).edit().putBoolean("server_verified", false).apply();
                    setServerEditMode(true);
                    setTradingControlsOffline();
                    addJournal("Ошибка сервера: " + safeMessage(e));
                    Toast.makeText(this, "Сервер пока недоступен", Toast.LENGTH_SHORT).show();
                });
            }
        });
    }

    private void maybeSendSignalToServer(Analysis a) { /* Execution belongs exclusively to EventCore. */ }

    private void executeEmergencyStop() {
        getSharedPreferences("fxm1",MODE_PRIVATE).edit().putBoolean("v108_emergency_latched",true)
            .putBoolean("auto_trading",false).putBoolean("auto_user_enabled",false).commit();
        sendBackgroundCommand(MonitoringService.ACTION_EMERGENCY_CONFIRMED);
        addJournal("Emergency: запрет новых входов сохранён; закрытие проверяется по MT5");
    }

    private void sendCloseAll() {
        new AlertDialog.Builder(this).setTitle("Закрыть всю кампанию бота?")
            .setMessage("Будут закрыты только позиции EventCore. Ручные позиции и старые V10 не затрагиваются. AUTO выключается.")
            .setNegativeButton("Отмена",null).setPositiveButton("Закрыть кампанию",(d,w)->eventCommand("close",new JSONObject())).show();
    }

    private JSONObject httpJson(String method,String url,JSONObject payload) throws Exception { return EventClient.http(method,url,payload); }

    private String money(double value, String currency) {
        if (Double.isNaN(value)) return "—";
        return String.format(Locale.US, "%.2f %s", value, currency);
    }

    private String signedMoney(double value, String currency) {
        return String.format(Locale.US, "%+.2f %s", value, currency);
    }

    private void addJournal(String line) {
        if (journalText == null) return;
        String current = journalText.getText().toString();
        String prefix = new java.text.SimpleDateFormat("HH:mm:ss", Locale.US).format(new Date());
        String updated = prefix + " · " + line;
        if (!current.trim().isEmpty() && !"Журнал пока пуст.".equals(current.trim())) {
            updated += "\n" + current;
        }
        String[] rows = updated.split("\\n");
        if (rows.length > 8) {
            StringBuilder limited = new StringBuilder();
            for (int i = 0; i < 8; i++) {
                if (i > 0) limited.append("\n");
                limited.append(rows[i]);
            }
            updated = limited.toString();
        }
        journalText.setText(updated);
        SharedPreferences jp = getSharedPreferences("fxm1", MODE_PRIVATE);
        String full = jp.getString("full_journal", "");
        String fullUpdated = prefix + " · " + line + (full.trim().isEmpty() ? "" : "\n" + full);
        String[] fullRows = fullUpdated.split("\n");
        StringBuilder saved = new StringBuilder();
        for (int i = 0; i < Math.min(500, fullRows.length); i++) { if (i > 0) saved.append('\n'); saved.append(fullRows[i]); }
        jp.edit().putString("full_journal", saved.toString()).apply();
    }

    private void showTradeJournalDialog() {
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        ScrollView scroll = new ScrollView(this);
        TextView tv = new TextView(this);
        tv.setTextColor(C_TEXT); tv.setTextSize(12f); tv.setPadding(dp(16), dp(12), dp(16), dp(16));
        String full = p.getString("full_journal", "");
        String sig = p.getString("signal_history", "");
        String trades = p.getString("trade_log_snapshot", tradeHistoryText == null ? "" : tradeHistoryText.getText().toString());
        String stats = p.getString("stats_snapshot", "");
        String text = "СОБЫТИЯ ПРИЛОЖЕНИЯ\n" + (full.trim().isEmpty()?"Пока пусто":full) +
                "\n\nИСТОРИЯ СИГНАЛОВ\n" + (sig.trim().isEmpty()?"Пока пусто":sig) +
                "\n\nСТАТИСТИКА 30 ДНЕЙ\n" + (stats.trim().isEmpty()?"Пока пусто":stats) +
                "\n\nСДЕЛКИ MT5 · ДО 200 СОБЫТИЙ\n" + (trades.trim().isEmpty()?"Пока пусто":trades);
        tv.setText(text); scroll.addView(tv);
        new AlertDialog.Builder(this).setTitle("Торговый журнал · подробно").setView(scroll)
                .setPositiveButton("ОБНОВИТЬ", (d,w) -> refreshStatsAndPositions())
                .setNeutralButton("ОЧИСТИТЬ ЛОКАЛЬНЫЙ", (d,w) -> { p.edit().remove("full_journal").apply(); journalText.setText("Журнал пока пуст."); })
                .setNegativeButton("ЗАКРЫТЬ", null).show();
    }

    private void setApiKeyEditMode(boolean editing) {
        if (apiKeyLabel != null) {
            apiKeyLabel.setVisibility(editing ? View.VISIBLE : View.GONE);
        }
        apiKeyInput.setVisibility(editing ? View.VISIBLE : View.GONE);
        saveKeyButton.setText(editing ? "СОХРАНИТЬ КЛЮЧ" : "КЛЮЧ BRIDGE");
    }

    private void setServerEditMode(boolean editing) {
        // V7.1: the trading module always stays compact. Address editing is dialog-only.
        if (serverUrlLabel != null) serverUrlLabel.setVisibility(View.GONE);
        if (serverInputRow != null) serverInputRow.setVisibility(View.GONE);
        if (serverUrlInput != null) serverUrlInput.setVisibility(View.GONE);
        boolean verified = getSharedPreferences("fxm1", MODE_PRIVATE).getBoolean("server_verified", false);
        if (serverCheckButton != null) serverCheckButton.setText(verified ? "ИЗМЕНИТЬ СЕРВЕР" : "ПОДКЛЮЧИТЬ СЕРВЕР");
    }

    private void showServerAddressDialog() {
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        final EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(stripServerScheme(p.getString("server_url", "")));
        input.setHint("192.168.1.8:8000");
        input.setTextColor(C_TEXT);
        input.setHintTextColor(Color.rgb(205, 199, 224));
        input.setSelectAllOnFocus(false);
        input.setPadding(dp(10), dp(10), dp(10), dp(10));

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(8), dp(20), dp(8));
        TextView hint = new TextView(this);
        hint.setText("http:// добавляется автоматически. Введите только IP:PORT");
        hint.setTextColor(C_MUTED);
        hint.setTextSize(12f);
        box.addView(hint, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(android.view.Gravity.CENTER_VERTICAL);
        TextView prefix = new TextView(this);
        prefix.setText("http://");
        prefix.setTextColor(C_PURPLE);
        prefix.setTextSize(17f);
        prefix.setGravity(android.view.Gravity.CENTER_VERTICAL);
        row.addView(prefix, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(54)));
        row.addView(input, new LinearLayout.LayoutParams(0, dp(54), 1f));
        box.addView(row, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Адрес MT5 Bridge")
                .setView(box)
                .setNegativeButton("ОТМЕНА", null)
                .setPositiveButton("ПОДКЛЮЧИТЬ", null)
                .create();

        dialog.setOnShowListener(d -> {
            android.view.Window w = dialog.getWindow();
            if (w != null) {
                w.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
                w.setGravity(android.view.Gravity.TOP | android.view.Gravity.CENTER_HORIZONTAL);
                android.view.WindowManager.LayoutParams lp = w.getAttributes();
                lp.y = dp(36);
                w.setAttributes(lp);
            }
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                String raw = input.getText().toString().trim();
                if (raw.isEmpty()) {
                    input.setError("Например: 192.168.1.8:8000");
                    return;
                }
                String normalized = normalizeServerUrl(raw);
                p.edit().putString("server_url", normalized).putBoolean("server_verified", false).apply();
                serverUrlInput.setText(stripServerScheme(normalized));
                dialog.dismiss();
                checkServer();
            });
            // Do not force the keyboard open. The field stays visible first; keyboard opens on tap.
            input.clearFocus();
        });
        dialog.show();
    }

    private Switch smartSwitch(String label, boolean checked) {
        Switch sw = new Switch(this);
        sw.setText(label);
        sw.setTextColor(C_TEXT);
        sw.setTextSize(13f);
        sw.setChecked(checked);
        sw.setPadding(0, dp(4), 0, dp(4));
        return sw;
    }

    private Spinner smartSpinner(String[] values, int selected) {
        Spinner sp = new Spinner(this);
        sp.setAdapter(darkSpinnerAdapter(values));
        sp.setSelection(Math.max(0, Math.min(selected, values.length - 1)));
        return sp;
    }

    private TextView smartLabel(String text) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextColor(C_PURPLE);
        tv.setTextSize(11f);
        tv.setPadding(0, dp(7), 0, 0);
        return tv;
    }

    private void showSmartFeaturesDialog() {
        SharedPreferences p=getSharedPreferences("fxm1",MODE_PRIVATE);
        ScrollView scroll=new ScrollView(this);LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(dp(18),dp(12),dp(18),dp(12));scroll.addView(box);
        box.addView(smartLabel("EventCore · только DEMO. Режим и ТФ независимы. Изменение профиля выключает AUTO; во время кампании профиль фиксирован."));
        EditText fee=eventNumber(box,"Комиссия полного круга USD за 1 lot. 0 — только при известном отсутствии комиссии",p.getString("ec_fee",""));
        EditText capital=eventNumber(box,"База DEMO-проверки риска; 0 = фактический счёт. Не меняет баланс MT5",p.getString("ec_test_capital","100"));
        EditText cap=eventNumber(box,"Предел планового риска всей кампании, USD",p.getString("ec_risk_cap","0.50"));
        EditText lot=eventNumber(box,"Верхний предел объёма одной ступени, lot",p.getString("ec_lot_cap","0.01"));
        EditText daily=eventNumber(box,"Дневной лимит убытка, % базы риска",String.valueOf(p.getFloat("daily_loss_limit_pct",3f)));
        EditText dd=eventNumber(box,"Лимит просадки, % базы риска",String.valueOf(p.getFloat("max_drawdown_pct",5f)));
        EditText streak=eventNumber(box,"Предел последовательных убыточных позиций",String.valueOf(p.getInt("max_consecutive_losses",3)));
        EditText spread=eventNumber(box,"Максимальный спред, pips",String.valueOf(p.getFloat("max_spread_pips",3f)));
        EditText cooldown=eventNumber(box,"Пауза после кампании, минут",String.valueOf(p.getInt("cooldown_minutes",10)));
        Switch dynamic=smartSwitch("Добавления по новым событиям (не усреднение)",p.getBoolean("ec_dynamic_adds",true));box.addView(dynamic);
        Switch sessions=smartSwitch("Фильтр сессий: "+p.getString("allowed_sessions","LONDON,NEW_YORK"),p.getBoolean("session_filter_enabled",false));box.addView(sessions);
        Button review=new Button(this);review.setText("Проверить блокировку серии убытков");styleOutlineButton(review,C_PURPLE);review.setOnClickListener(v->reviewLossStreak());box.addView(review);
        Button reset=new Button(this);reset.setText("Сверить и снять Emergency");styleOutlineButton(reset,C_PURPLE);box.addView(reset);
        reset.setOnClickListener(v->new AlertDialog.Builder(this).setTitle("Сверить DEMO-состояние?")
            .setMessage("Только без позиций/ордеров бота и неизвестных исполнений. AUTO остаётся выключенным.")
            .setNegativeButton("Назад",null).setPositiveButton("Сверить",(d,w)->{try{eventCommand("reset",new JSONObject().put("confirmation","RESET_DEMO_FLAT"));}catch(Exception ignored){}}).show());
        new AlertDialog.Builder(this).setTitle("Умные функции · EventCore").setView(scroll).setNegativeButton("ОТМЕНА",null)
            .setPositiveButton("СОХРАНИТЬ",(d,w)->{
                try{
                    double f=Double.parseDouble(fee.getText().toString().replace(',','.'));
                    double c=Double.parseDouble(capital.getText().toString().replace(',','.'));
                    double r=Double.parseDouble(cap.getText().toString().replace(',','.'));
                    double l=Double.parseDouble(lot.getText().toString().replace(',','.'));
                    if(!Double.isFinite(f)||!Double.isFinite(c)||!Double.isFinite(r)||!Double.isFinite(l)||f<0||c<0||r<=0||l<=0)throw new Exception("Проверьте числа профиля");
                    p.edit().putString("ec_fee",String.valueOf(f)).putString("ec_test_capital",String.valueOf(c)).putString("ec_risk_cap",String.valueOf(r)).putString("ec_lot_cap",String.valueOf(l))
                        .putFloat("daily_loss_limit_pct",Float.parseFloat(daily.getText().toString().replace(',','.'))).putFloat("max_drawdown_pct",Float.parseFloat(dd.getText().toString().replace(',','.')))
                        .putInt("max_consecutive_losses",Integer.parseInt(streak.getText().toString())).putFloat("max_spread_pips",Float.parseFloat(spread.getText().toString().replace(',','.')))
                        .putInt("cooldown_minutes",Integer.parseInt(cooldown.getText().toString())).putBoolean("ec_dynamic_adds",dynamic.isChecked()).putBoolean("session_filter_enabled",sessions.isChecked()).apply();
                    executor.execute(()->{try{EventClient.configure();EventClient.poll();}catch(Exception e){runOnUiThread(()->new AlertDialog.Builder(this).setMessage(safeMessage(e)).setPositiveButton("OK",null).show());}});
                }catch(Exception e){new AlertDialog.Builder(this).setMessage(safeMessage(e)).setPositiveButton("OK",null).show();}
            }).show();
    }

    private void reviewLossStreak() {
        eventCommand("disable",new JSONObject());
        executor.execute(()->{try{JSONObject rs=EventClient.http("GET",EventClient.base()+"/risk-state",null);
            String info="Последовательных убытков: "+rs.optInt("consecutive_losses")+" / "+getSharedPreferences("fxm1",MODE_PRIVATE).getInt("max_consecutive_losses",3)+"\n"+(rs.optBoolean("allowed")?"Риск разрешён":ExecutionFeedback.riskText("RISK BLOCK: "+rs.optJSONArray("blocks")));
            runOnUiThread(()->{AlertDialog.Builder b=new AlertDialog.Builder(this).setTitle("Проверка LOSS_STREAK").setMessage(info+"\nСброс не удаляет историю и не включает AUTO.").setNegativeButton("Назад",null);
                if(rs.optBoolean("can_acknowledge"))b.setPositiveButton("Проверено — сбросить серию",(d,w)->{try{eventCommand("ack_losses",new JSONObject().put("confirmation","ACK_LOSS_STREAK_DEMO").put("expected_last_deal",rs.optLong("last_closing_ticket")));}catch(Exception ignored){}});b.show();});
        }catch(Exception e){runOnUiThread(()->new AlertDialog.Builder(this).setTitle("Риск").setMessage(safeMessage(e)).setPositiveButton("OK",null).show());}});
    }

    private void refreshSmartUi() {
        SharedPreferences p=getSharedPreferences("fxm1",MODE_PRIVATE);JSONObject s=EventClient.state(),cfg=s.optJSONObject("config");
        if(smartStatusText!=null)smartStatusText.setText("Режим: "+(cfg==null?EventClient.mode():cfg.optString("mode"))+" · только DEMO\nИсточник: MT5\n"+
            "Наращивание: "+(cfg!=null&&cfg.optBoolean("dynamic_adds")?"по новым подтверждениям и общему риску":"один вход")+
            "\nСопровождение: независимый Bridge\n"+ExecutionFeedback.riskText(p.getString("risk_snapshot","не проверен"))+"\n"+p.getString("ec_message",""));
        if(statsText!=null)statsText.setText("СТАТИСТИКА\n"+p.getString("stats_snapshot","—"));
        if(signalHistoryText!=null)signalHistoryText.setText("ИСТОРИЯ СИГНАЛОВ\n"+p.getString("signal_history","—"));
        if(tradeHistoryText!=null)tradeHistoryText.setText(p.getString("trade_log_snapshot","ТОРГОВЫЙ ЖУРНАЛ"));
    }

    private String serverBaseFromPrefs() {
        return normalizeServerUrl(getSharedPreferences("fxm1", MODE_PRIVATE).getString("server_url", ""));
    }

    private void refreshStatsAndPositions() {
        final String base = serverBaseFromPrefs();
        if (base.isEmpty() || moneyRefreshInFlight) return;
        moneyRefreshInFlight = true;
        executor.execute(() -> {
            try {
                JSONObject pos = FeatureEngine.httpJson("GET", base + "/positions", null);
                JSONObject ledger30 = FeatureEngine.httpJson("GET", base + "/trade-ledger?days=30&limit=1000", null);
                JSONObject ledgerAll = FeatureEngine.httpJson("GET", base + "/trade-ledger?days=3650&limit=1000", null);

                String currency = getSharedPreferences("fxm1", MODE_PRIVATE).getString("mt5_currency_snapshot", "USD");
                String stText = FeatureEngine.formatLedgerStats(ledger30);
                String logText = FeatureEngine.formatTradeLog(ledger30);
                String fullText = FeatureEngine.formatFullTradeHistory(ledgerAll, currency);
                String moneySummary = FeatureEngine.formatRealizedMoneySummary(ledgerAll, currency);
                int openCount = pos.optInt("count", 0);
                double floating = pos.optDouble("floating_pl", 0.0);

                getSharedPreferences("fxm1", MODE_PRIVATE).edit()
                        .putString("trade_log_snapshot", logText)
                        .putString("trade_log_full_snapshot", fullText)
                        .putString("stats_snapshot", stText)
                        .putString("money_realized_snapshot", moneySummary)
                        .putInt("mt5_positions_snapshot", openCount)
                        .putLong("mt5_floating_bits", Double.doubleToLongBits(floating))
                        .apply();

                runOnUiThread(() -> {
                    if (statsText != null) statsText.setText("СТАТИСТИКА\n" + stText);
                    if (tradeHistoryText != null) tradeHistoryText.setText(logText);
                    renderPositionsMoneyCard(openCount, floating, currency);
                    // The lower JOURNAL card must never look empty while MT5 history exists.
                    if (journalText != null) {
                        String local = journalText.getText() == null ? "" : journalText.getText().toString().trim();
                        if (local.isEmpty() || local.equalsIgnoreCase("Журнал пока пуст.")) {
                            journalText.setText(logText);
                        }
                    }
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    String cachedStats = getSharedPreferences("fxm1", MODE_PRIVATE).getString("stats_snapshot", "");
                    String cachedLog = getSharedPreferences("fxm1", MODE_PRIVATE).getString("trade_log_snapshot", "");
                    if (statsText != null && !cachedStats.trim().isEmpty()) statsText.setText("СТАТИСТИКА\n" + cachedStats);
                    if (tradeHistoryText != null && !cachedLog.trim().isEmpty()) tradeHistoryText.setText(cachedLog);
                });
            } finally {
                moneyRefreshInFlight = false;
            }
        });
    }

    private void renderPositionsMoneyCard(int openCount, double floating, String currency) {
        if (positionsText == null) return;
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        String realized = p.getString("money_realized_snapshot", "");
        StringBuilder sb = new StringBuilder();
        sb.append("Открытые позиции: ").append(openCount)
          .append("\nТекущий P/L: ").append(signedMoney(floating, currency));
        if (realized != null && !realized.trim().isEmpty()) {
            sb.append("\n").append(realized.trim());
        } else {
            sb.append("\nСегодня: —")
              .append("\nВсего: —");
        }
        positionsText.setText(sb.toString());
    }

    private void showMoneyHistoryDialog() {
        final String base = serverBaseFromPrefs();
        final SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        final String currency = p.getString("mt5_currency_snapshot", "USD");

        // Show cached data immediately; then refresh from MT5 Bridge if reachable.
        String cachedSummary = p.getString("money_realized_snapshot", "Сегодня: —\nВсего: —");
        String cachedHistory = p.getString("trade_log_full_snapshot", p.getString("trade_log_snapshot", "Пока пусто"));
        if (base.isEmpty()) {
            showMoneyHistoryDialogText(cachedSummary, cachedHistory);
            return;
        }

        executor.execute(() -> {
            try {
                JSONObject pos = FeatureEngine.httpJson("GET", base + "/positions", null);
                JSONObject ledger = FeatureEngine.httpJson("GET", base + "/trade-ledger?days=3650&limit=1000", null);
                String summary = FeatureEngine.formatMoneyHistoryHeader(pos, ledger, currency);
                String history = FeatureEngine.formatFullTradeHistory(ledger, currency);
                String realized = FeatureEngine.formatRealizedMoneySummary(ledger, currency);
                p.edit()
                        .putString("money_realized_snapshot", realized)
                        .putString("trade_log_full_snapshot", history)
                        .putString("trade_log_snapshot", FeatureEngine.formatTradeLog(ledger))
                        .apply();
                runOnUiThread(() -> {
                    renderPositionsMoneyCard(pos.optInt("count", 0), pos.optDouble("floating_pl", 0.0), currency);
                    showMoneyHistoryDialogText(summary, history);
                });
            } catch (Exception e) {
                runOnUiThread(() -> showMoneyHistoryDialogText(
                        cachedSummary + "\n\nBridge: " + safeMessage(e), cachedHistory));
            }
        });
    }

    private void showMoneyHistoryDialogText(String summary, String history) {
        ScrollView scroll = new ScrollView(this);
        TextView tv = new TextView(this);
        tv.setTextColor(C_TEXT);
        tv.setTextSize(12f);
        tv.setPadding(dp(16), dp(12), dp(16), dp(18));
        tv.setText((summary == null ? "" : summary) +
                "\n\nВСЯ ИСТОРИЯ ЗАКРЫТЫХ СДЕЛОК\n" +
                ((history == null || history.trim().isEmpty()) ? "Пока пусто" : history));
        scroll.addView(tv);
        new AlertDialog.Builder(this)
                .setTitle("Деньги / история MT5")
                .setView(scroll)
                .setPositiveButton("ОБНОВИТЬ", (d, w) -> showMoneyHistoryDialog())
                .setNegativeButton("ЗАКРЫТЬ", null)
                .show();
    }

    private void showPositionManagementHub() { showPositionsManager(); }

    private void showPositionManagementSettings() {
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        LinearLayout box = new LinearLayout(this); box.setOrientation(LinearLayout.VERTICAL); box.setPadding(dp(18),dp(8),dp(18),dp(8));
        Switch master = smartSwitch("Автосопровождение позиций", p.getBoolean("position_manager_enabled", true)); box.addView(master);
        Switch hard = smartSwitch("Hard Cash Stop", p.getBoolean("scalp_hard_stop_enabled", true)); box.addView(hard);
        Switch peak = smartSwitch("Peak Profit Lock", p.getBoolean("scalp_peak_lock_enabled", true)); box.addView(peak);
        Switch take = smartSwitch("Cash Take Profit", p.getBoolean("scalp_cash_tp_enabled", true)); box.addView(take);
        Switch be = smartSwitch("Break-even", p.getBoolean("break_even_enabled", true)); box.addView(be);
        Switch tr = smartSwitch("Trailing stop", p.getBoolean("trailing_enabled", true)); box.addView(tr);
        Switch part = smartSwitch("Partial close", p.getBoolean("partial_close_enabled", true)); box.addView(part);
        new AlertDialog.Builder(this).setTitle("Автосопровождение · тумблеры").setView(box)
            .setPositiveButton("СОХРАНИТЬ", (d,w) -> { p.edit().putBoolean("position_manager_enabled", master.isChecked())
                .putBoolean("scalp_hard_stop_enabled", hard.isChecked()).putBoolean("scalp_peak_lock_enabled", peak.isChecked())
                .putBoolean("scalp_cash_tp_enabled", take.isChecked()).putBoolean("break_even_enabled", be.isChecked())
                .putBoolean("trailing_enabled", tr.isChecked()).putBoolean("partial_close_enabled", part.isChecked()).apply();
                refreshSmartUi(); if (monitoring) sendBackgroundCommand(MonitoringService.ACTION_REFRESH); })
            .setNegativeButton("ОТМЕНА", null).show();
    }

    private void showPositionsManager() {
        final String base = serverBaseFromPrefs();
        if (base.isEmpty() || !serverConnected || !mt5Connected) {
            Toast.makeText(this, "Сначала подключите MT5", Toast.LENGTH_SHORT).show();
            return;
        }
        executor.execute(() -> {
            try {
                JSONObject root = FeatureEngine.httpJson("GET", base + "/positions", null);
                JSONArray arr = root.optJSONArray("positions");
                if (arr == null || arr.length()==0) { runOnUiThread(() -> Toast.makeText(this,"Открытых позиций нет",Toast.LENGTH_SHORT).show()); return; }
                final ArrayList<JSONObject> items=new ArrayList<>(); final ArrayList<String> labels=new ArrayList<>();
                for(int i=0;i<arr.length();i++){ JSONObject o=arr.optJSONObject(i); if(o==null)continue; items.add(o); labels.add("#"+o.optLong("ticket")+" · "+o.optString("symbol")+" · "+o.optString("side")+" · P/L "+String.format(Locale.US,"%+.2f",o.optDouble("profit",0))); }
                runOnUiThread(() -> new AlertDialog.Builder(this).setTitle("Позиции MT5").setItems(labels.toArray(new String[0]), (d,which) -> showPositionActions(base,items.get(which))).setNegativeButton("ЗАКРЫТЬ",null).show());
            } catch(Exception e){ runOnUiThread(() -> Toast.makeText(this,"Позиции: "+safeMessage(e),Toast.LENGTH_LONG).show()); }
        });
    }

    private void showPositionActions(String base,JSONObject pos) {
        new AlertDialog.Builder(this).setTitle("Позиция #"+pos.optLong("ticket"))
            .setMessage(pos.optString("symbol")+" · "+pos.optString("side")+" · "+pos.optDouble("volume")+" lot\nSL: "+pos.optDouble("sl")+"\nP/L: "+pos.optDouble("profit")+"\nУправление — единая кампания; SL не расширяется.")
            .setNegativeButton("Назад",null).setPositiveButton("Закрыть кампанию",(d,w)->sendCloseAll()).show();
    }

    private void startMonitoring() {
        SharedPreferences p=getSharedPreferences("fxm1",MODE_PRIVATE);
        if(p.getString("ec_token","").trim().isEmpty()||EventClient.base().isEmpty()){
            new AlertDialog.Builder(this).setMessage("Сначала укажите адрес и ключ Bridge EventCore. Twelve Data не нужен.").setPositiveButton("OK",null).show();return;
        }
        p.edit().putInt("entry_tf_pos",entryTimeframeSpinner.getSelectedItemPosition()).putInt("signal_mode_pos",signalModeSpinner.getSelectedItemPosition())
            .putString("selected_symbol",String.valueOf(symbolSpinner.getSelectedItem())).putBoolean("ui_monitoring",true).putLong("monitor_stopped_ms",0).apply();
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED){requestNotificationPermissionIfNeeded();return;}
        startUnifiedMonitoringService();
    }

    private void startUnifiedMonitoringService() {
        Intent intent = new Intent(this, MonitoringService.class);
        intent.setAction(MonitoringService.ACTION_START);

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent);
            } else {
                startService(intent);
            }
        } catch (Exception e) {
            monitoring = false;
            getSharedPreferences("fxm1", MODE_PRIVATE).edit().putBoolean("ui_monitoring", false).apply();
            analyzeButton.setText("ЗАПУСТИТЬ МОНИТОРИНГ");
            statusText.setText("Ошибка запуска мониторинга: " + safeMessage(e));
            Toast.makeText(this, "Не удалось запустить мониторинг: " + safeMessage(e), Toast.LENGTH_LONG).show();
            return;
        }

        monitoring = true;
        analyzeButton.setText("ОСТАНОВИТЬ МОНИТОРИНГ");
        statusText.setText("Мониторинг запущен · можно свернуть приложение.");
        monitorHandler.removeCallbacks(monitorRunnable);
    }

    private void stopMonitoring() {
        monitoring = false;
        monitorHandler.removeCallbacks(monitorRunnable);
        long now = System.currentTimeMillis();
        getSharedPreferences("fxm1", MODE_PRIVATE)
                .edit()
                .putBoolean("ui_monitoring", false)
                .putLong("monitor_stopped_ms", now)
                .apply();

        sendBackgroundCommand(MonitoringService.ACTION_STOP);
        analyzeButton.setText("ЗАПУСТИТЬ МОНИТОРИНГ");
        statusText.setText("Мониторинг остановлен.");
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != 5001) return;

        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startUnifiedMonitoringService();
        } else {
            monitoring = false;
            getSharedPreferences("fxm1", MODE_PRIVATE).edit().putBoolean("ui_monitoring", false).apply();
            analyzeButton.setText("ЗАПУСТИТЬ МОНИТОРИНГ");
            statusText.setText("Мониторинг не запущен: уведомления запрещены.");
            Toast.makeText(this,
                    "Разрешите уведомления для FX M1 Bot — Android требует их для постоянного мониторинга.",
                    Toast.LENGTH_LONG).show();
        }
    }

    private void sendBackgroundCommand(String action) {
        Intent intent = new Intent(this, MonitoringService.class);
        intent.setAction(action);
        try {
            startService(intent);
        } catch (Exception ignored) {
        }
    }

    private void requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{Manifest.permission.POST_NOTIFICATIONS},
                    5001
            );
        }
    }

    private void syncUiFromBackgroundService() {
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        if (p.getBoolean("server_verified", false)) {
            restoreTradingSnapshotFromPrefs();
            long nowMoney = System.currentTimeMillis();
            if (nowMoney - lastMoneyRefreshMs >= 5000L) {
                lastMoneyRefreshMs = nowMoney;
                refreshStatsAndPositions();
            }
        }
        boolean bgRunning = p.getBoolean("bg_running", false);
        monitoring = bgRunning;

        analyzeButton.setText(bgRunning ? "ОСТАНОВИТЬ МОНИТОРИНГ" : "ЗАПУСТИТЬ МОНИТОРИНГ");

        if (p.getBoolean("stop_all_requested", false)) {
            p.edit().putBoolean("stop_all_requested", false).putBoolean("ui_monitoring", false).apply();
            monitoring = false;
            monitorHandler.removeCallbacks(monitorRunnable);
            analyzeButton.setText("ЗАПУСТИТЬ МОНИТОРИНГ");
        }

        String symbol = p.getString("state_symbol", "");
        String tf = p.getString("state_tf", "");
        if (symbol.isEmpty() || tf.isEmpty()) return;

        String selectedSymbol = (String) symbolSpinner.getSelectedItem();
        String selectedTf = selectedEntryTimeframe();

        String signal = p.getString("state_signal", "WAIT");
        String context = p.getString("state_context", "");
        String why = p.getString("state_why", "");
        String components = p.getString("state_components", "");
        int quality = p.getInt("state_quality", -1);
        int fresh = p.getInt("state_api_count", 0);
        int cached = p.getInt("state_cache_count", 0);
        long since = p.getLong("state_signal_since_ms", 0L);
        long updated = p.getLong("state_last_update_ms", 0L);
        String source = bgRunning ? "LIVE" : "STOP";

        if (!symbol.equals(selectedSymbol) || !tf.equals(selectedTf)) {
            signalText.setText("WAIT");
            signalText.setTextColor(C_PURPLE);
            confidenceText.setText("Сценарий: ожидание данных");
            updateSignalAgeText("WAIT", 0L, 0L);
            levelsText.setText("Entry: —\nSL: —\nTP1: —\nTP2: —");
            contextText.setText("Параметры изменены. Жду новый анализ для " + selectedSymbol + " · " + selectedTf + ".");
            if (whyWaitText != null) whyWaitText.setText("ПОЧЕМУ WAIT: жду новый анализ");
            if (componentScoresText != null) componentScoresText.setText("ПРАВИЛА СЦЕНАРИЯ: —");
            return;
        }

        double entry = Double.longBitsToDouble(p.getLong("state_entry_bits", Double.doubleToLongBits(Double.NaN)));
        double sl = Double.longBitsToDouble(p.getLong("state_sl_bits", Double.doubleToLongBits(Double.NaN)));
        double tp1 = Double.longBitsToDouble(p.getLong("state_tp1_bits", Double.doubleToLongBits(Double.NaN)));
        double tp2 = Double.longBitsToDouble(p.getLong("state_tp2_bits", Double.doubleToLongBits(Double.NaN)));

        statusText.setText(symbol+" · "+tf+" · "+source+" · ДАННЫЕ MT5");

        signalText.setText(signal);
        signalText.setTextColor("BUY".equals(signal) ? C_GREEN : ("SELL".equals(signal) ? C_RED : C_PURPLE));

        confidenceText.setText("Сценарий: "+EventClient.phaseName(EventClient.state().optJSONObject("decision")==null?"SEARCH":EventClient.state().optJSONObject("decision").optString("phase","SEARCH")));
        confidenceText.setTextColor(C_PURPLE);
        if (qualityBarView != null) qualityBarView.setVisibility(View.GONE);
        updateSignalAgeText(signal, since, updated);
        restoreSparklineFromPrefs(signal);

        if ("WAIT".equals(signal)) {
            levelsText.setText("Entry: " + (Double.isNaN(entry) ? "—" : fmt(entry)) + "\nSL: —\nTP1: —\nTP2: —");
        } else {
            levelsText.setText(
                    "Entry: " + fmt(entry) +
                    "\nSL: " + fmt(sl) +
                    "\nВыход: структура и защита кампании"
            );
        }
        contextText.setText(context);
        if (whyWaitText != null) whyWaitText.setText(("WAIT".equals(signal) ? "ПОЧЕМУ WAIT: " : "СИГНАЛ АНАЛИЗА: ") + (why == null || why.isEmpty() ? "—" : why) + ExecutionFeedback.render(p, symbol, tf));
        if (componentScoresText != null) componentScoresText.setText("ПРАВИЛА СЦЕНАРИЯ: " + (components == null || components.isEmpty() ? "—" : components));
        refreshSmartUi();

        if (!Double.isNaN(entry)) {
            lastApiPrice = entry;
            updatePriceComparison();
        }
    }

    private void scheduleNext(long delayMs) {
        monitorHandler.removeCallbacks(monitorRunnable);

        if (monitoring) {
            monitorHandler.postDelayed(monitorRunnable, delayMs);
        }
    }

    private void runAnalysis() { sendBackgroundCommand(MonitoringService.ACTION_REFRESH); }

    private void alertIfNewTradeSignal(Analysis a) {
        String oldSignal = lastAlertSignal.get(a.symbol);

        if ("BUY".equals(a.signal) || "SELL".equals(a.signal)) {
            if (!a.signal.equals(oldSignal)) {
                lastAlertSignal.put(a.symbol, a.signal);

                ToneGenerator tone = new ToneGenerator(
                        AudioManager.STREAM_NOTIFICATION,
                        90
                );
                tone.startTone(ToneGenerator.TONE_PROP_BEEP2, 600);

                Toast.makeText(
                        this,
                        a.symbol + " · " + a.signal +
                                " · качество " + a.quality + "/100",
                        Toast.LENGTH_LONG
                ).show();
            }
        } else {
            lastAlertSignal.put(a.symbol, "WAIT");
        }
    }

    private FetchResult getTenMinuteSeries(String symbol, String key, int outputsize) throws Exception {
        FetchResult base = getSeries(symbol, "5min", key, Math.max(80, outputsize * 2), CACHE_M5_MS);
        List<Candle> src = base.data;
        ArrayList<Candle> out = new ArrayList<>();
        int start = src.size() % 2;
        for (int i = start; i + 1 < src.size(); i += 2) {
            Candle a = src.get(i), b = src.get(i + 1);
            out.add(new Candle(a.open, Math.max(a.high, b.high), Math.min(a.low, b.low), b.close));
        }
        if (out.size() > outputsize) out = new ArrayList<>(out.subList(out.size() - outputsize, out.size()));
        if (out.size() < 30) throw new Exception("Недостаточно свечей для M10");
        return new FetchResult(out, base.fromCache);
    }

    private FetchResult getSeries(String symbol,
                                  String interval,
                                  String key,
                                  int outputsize,
                                  long maxAgeMs) throws Exception {

        String cacheKey = symbol + "|" + interval;
        CacheItem cached = cache.get(cacheKey);
        long now = System.currentTimeMillis();

        if (cached != null && now - cached.savedAtMs <= maxAgeMs) {
            return new FetchResult(cached.data, true);
        }

        List<Candle> data = fetch(symbol, interval, key, outputsize);
        cache.put(cacheKey, new CacheItem(data, now));

        return new FetchResult(data, false);
    }

    private List<Candle> fetch(String symbol,
                               String interval,
                               String key,
                               int outputsize) throws Exception {

        String url = "https://api.twelvedata.com/time_series?symbol=" +
                URLEncoder.encode(FeatureEngine.analysisSymbol(symbol), "UTF-8") +
                "&interval=" + URLEncoder.encode(interval, "UTF-8") +
                "&outputsize=" + outputsize +
                "&apikey=" + URLEncoder.encode(key, "UTF-8");

        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(12000);
        conn.setReadTimeout(12000);
        conn.setRequestMethod("GET");

        int code = conn.getResponseCode();

        InputStream is = code >= 200 && code < 300
                ? conn.getInputStream()
                : conn.getErrorStream();

        String body = readAll(is);
        JSONObject root = new JSONObject(body);

        if (root.has("status") &&
                "error".equalsIgnoreCase(root.optString("status"))) {

            String message = root.optString("message", "API error");
            String lower = message.toLowerCase(Locale.US);

            if (lower.contains("api credits") ||
                    lower.contains("current minute") ||
                    lower.contains("rate limit")) {
                throw new RateLimitException(message);
            }

            throw new Exception(message);
        }

        JSONArray vals = root.optJSONArray("values");

        if (vals == null || vals.length() < 30) {
            throw new Exception("Недостаточно свечей для " + interval);
        }

        List<Candle> list = new ArrayList<>();

        for (int i = vals.length() - 1; i >= 0; i--) {
            JSONObject o = vals.getJSONObject(i);

            list.add(new Candle(
                    o.getDouble("open"),
                    o.getDouble("high"),
                    o.getDouble("low"),
                    o.getDouble("close")
            ));
        }

        return list;
    }

    private String readAll(InputStream is) throws IOException {
        if (is == null) return "";

        BufferedReader br = new BufferedReader(
                new InputStreamReader(is, StandardCharsets.UTF_8)
        );

        StringBuilder sb = new StringBuilder();
        String line;

        while ((line = br.readLine()) != null) {
            sb.append(line);
        }

        return sb.toString();
    }


    private boolean isForexMarketOpen() {
        Calendar ny = Calendar.getInstance(TimeZone.getTimeZone("America/New_York"));
        int dow = ny.get(Calendar.DAY_OF_WEEK);
        int mins = ny.get(Calendar.HOUR_OF_DAY) * 60 + ny.get(Calendar.MINUTE);
        // Standard retail FX weekly window. NY timezone automatically handles DST.
        int sundayOpen = 17 * 60 + 5;
        int fridayClose = 16 * 60 + 59;
        if (dow == Calendar.SATURDAY) return false;
        if (dow == Calendar.SUNDAY) return mins >= sundayOpen;
        if (dow == Calendar.FRIDAY) return mins < fridayClose;
        return true;
    }

    private Calendar nyBoundary(int dayOffset, int hour, int minute) {
        Calendar c = Calendar.getInstance(TimeZone.getTimeZone("America/New_York"));
        c.add(Calendar.DAY_OF_MONTH, dayOffset);
        c.set(Calendar.HOUR_OF_DAY, hour); c.set(Calendar.MINUTE, minute); c.set(Calendar.SECOND, 0); c.set(Calendar.MILLISECOND, 0);
        return c;
    }

    private String tashkentTime(Calendar source) {
        java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("dd.MM (EEE) HH:mm", new Locale("ru"));
        f.setTimeZone(TimeZone.getTimeZone("Asia/Tashkent"));
        return f.format(source.getTime()) + " (TASH)";
    }

    private void updateMarketStatusUi() {
        if (marketStatusText == null || marketSessionText == null) return;
        Calendar ny = Calendar.getInstance(TimeZone.getTimeZone("America/New_York"));
        int dow = ny.get(Calendar.DAY_OF_WEEK);
        int mins = ny.get(Calendar.HOUR_OF_DAY) * 60 + ny.get(Calendar.MINUTE);
        boolean open = isForexMarketOpen();

        if (open) {
            // Spot FX is normally continuous during the trading week: Sunday 17:00 NY -> Friday 17:00 NY.
            int daysSinceSunday = (dow - Calendar.SUNDAY + 7) % 7;
            Calendar opened = nyBoundary(-daysSinceSunday, 17, 5);
            int daysToFriday = (Calendar.FRIDAY - dow + 7) % 7;
            Calendar closes = nyBoundary(daysToFriday, 16, 59);
            marketStatusText.setText("MARKET OPEN");
            marketStatusText.setTextColor(C_GREEN);
            marketSessionText.setText(
                    "Торговая неделя:\n" + shortTashkentTime(opened) + " — " + shortTashkentTime(closes) +
                    "\nСледующее закрытие: " + shortTashkentTime(closes)
            );
        } else {
            Calendar closed;
            Calendar next;
            if (dow == Calendar.FRIDAY && mins >= 16 * 60 + 59) {
                closed = nyBoundary(0, 16, 59);
                next = nyBoundary(2, 17, 5);
            } else if (dow == Calendar.SATURDAY) {
                closed = nyBoundary(-1, 16, 59);
                next = nyBoundary(1, 17, 5);
            } else { // Sunday before 17:00 NY
                closed = nyBoundary(-2, 16, 59);
                next = nyBoundary(0, 17, 5);
            }
            marketStatusText.setText("MARKET CLOSED");
            marketStatusText.setTextColor(C_RED);
            marketSessionText.setText(
                    "Выходные:\n" + shortTashkentTime(closed) + " — " + shortTashkentTime(next) +
                    "\nСледующее открытие: " + shortTashkentTime(next)
            );
        }
    }

    private String shortTashkentTime(Calendar source) {
        java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("EEE dd.MM HH:mm", new Locale("ru"));
        f.setTimeZone(TimeZone.getTimeZone("Asia/Tashkent"));
        String v = f.format(source.getTime());
        if (v.length() > 0) v = Character.toUpperCase(v.charAt(0)) + v.substring(1);
        return v + " (TASH)";
    }

    private void loadSyncedMt5Symbols() {
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        String raw = p.getString("mt5_symbols_cache", "");
        if (raw == null || raw.trim().isEmpty()) return;
        ArrayList<String> cached = new ArrayList<>();
        for (String x : raw.split("\\|")) {
            String v = x.trim();
            if (!v.isEmpty() && !cached.contains(v)) cached.add(v);
            if (cached.size() >= 500) break;
        }
        if (!cached.isEmpty()) {
            symbolItems.clear();
            symbolItems.addAll(cached);
        }
    }

    private void loadCustomSymbols() {
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        String raw = p.getString("custom_symbols", "");
        if (raw == null || raw.trim().isEmpty()) return;
        for (String x : raw.split("\\|")) {
            String v = x.trim();
            if (!v.isEmpty() && !symbolItems.contains(v)) symbolItems.add(v);
        }
    }

    private void showAddSymbolDialog() {
        addingCustomSymbol = true;
        final EditText input = new EditText(this);
        input.setHint("Например: BTC/USD, US100, XAG/USD");
        input.setSingleLine(true);
        new AlertDialog.Builder(this)
                .setTitle("Добавить инструмент")
                .setMessage("Введите символ. Он должен поддерживаться Twelve Data для анализа и MT5 для исполнения.")
                .setView(input)
                .setPositiveButton("ДОБАВИТЬ", (d, w) -> {
                    String v = input.getText().toString().trim().toUpperCase(Locale.US);
                    if (!v.isEmpty()) {
                        int addPos = symbolItems.indexOf("＋ ДОБАВИТЬ ИНСТРУМЕНТ");
                        if (!symbolItems.contains(v)) symbolItems.add(Math.max(0, addPos), v);
                        saveCustomSymbols();
                        symbolAdapter = darkSpinnerAdapter(symbolItems.toArray(new String[0]));
                        symbolSpinner.setAdapter(symbolAdapter);
                        int pos = symbolItems.indexOf(v);
                        symbolSpinner.setSelection(pos >= 0 ? pos : 0);
                    }
                    addingCustomSymbol = false;
                })
                .setNegativeButton("ОТМЕНА", (d, w) -> {
                    addingCustomSymbol = false;
                    String saved = getSharedPreferences("fxm1", MODE_PRIVATE).getString("selected_symbol", "EUR/USD");
                    int pos = symbolItems.indexOf(saved);
                    symbolSpinner.setSelection(pos >= 0 ? pos : 0);
                })
                .show();
    }

    private void saveCustomSymbols() {
        HashSet<String> base = new HashSet<>(Arrays.asList(
                "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
                "EUR/JPY", "GBP/JPY", "EUR/GBP", "EUR/CHF", "AUD/JPY", "CAD/JPY", "CHF/JPY",
                "GBP/CHF", "EUR/AUD", "GBP/AUD", "AUD/NZD", "NZD/JPY", "XAU/USD"
        ));
        StringBuilder b = new StringBuilder();
        for (String x : symbolItems) {
            if (base.contains(x) || x.startsWith("＋")) continue;
            if (b.length() > 0) b.append('|');
            b.append(x);
        }
        getSharedPreferences("fxm1", MODE_PRIVATE).edit().putString("custom_symbols", b.toString()).apply();
    }

    private String safeMessage(Exception e) {
        String m = e.getMessage();
        return m == null || m.trim().isEmpty()
                ? "неизвестная ошибка"
                : m;
    }


    private boolean isScalpTimeframe(String tf) {
        return "M5".equals(tf) || "M10".equals(tf) || "M15".equals(tf);
    }

    private String selectedEntryTimeframe() {
        Object selected = entryTimeframeSpinner.getSelectedItem();
        return selected == null ? "M5" : selected.toString();
    }

    private long selectedMonitorIntervalMs() {
        String tf = selectedEntryTimeframe();
        if ("M1".equals(tf)) return 10000L;
        if ("M5".equals(tf)) return 60000L;
        if ("M10".equals(tf)) return 120000L;
        if ("M15".equals(tf)) return 180000L;
        if ("H1".equals(tf)) return 300000L;
        if ("H4".equals(tf)) return 900000L;
        if ("D1".equals(tf)) return 1800000L;
        if ("W1".equals(tf)) return 3600000L;
        return 7200000L; // MN1
    }

    private String selectedMonitorLabel() {
        long sec = selectedMonitorIntervalMs() / 1000L;
        if (sec < 60) return sec + "с";
        long min = sec / 60L;
        return min + "м";
    }

    private String selectedSignalMode() { return signalModeSpinner.getSelectedItemPosition()==1?"SCALP":"NORMAL"; }

    private double selectedMaxDriftPct() {
        Object selected = maxDriftSpinner.getSelectedItem();
        if (selected == null) return 0.05;
        try {
            return Double.parseDouble(selected.toString().replace("%", ""));
        } catch (Exception ignored) {
            return 0.05;
        }
    }

    private void refreshMt5Quote(String symbol) {
        if (!serverConnected || !mt5Connected) {
            lastMt5Bid = Double.NaN;
            lastMt5Ask = Double.NaN;
            updatePriceComparison();
            return;
        }

        final String base = normalizeServerUrl(serverUrlInput.getText().toString());
        if (base.isEmpty()) return;

        executor.execute(() -> {
            try {
                String url = base + "/quote?symbol=" + URLEncoder.encode(FeatureEngine.analysisSymbol(symbol), "UTF-8");
                JSONObject root = httpJson("GET", url, null);
                double bid = root.optDouble("bid", Double.NaN);
                double ask = root.optDouble("ask", Double.NaN);

                runOnUiThread(() -> {
                    lastMt5Bid = bid;
                    lastMt5Ask = ask;
                    updatePriceComparison();
                });
            } catch (Exception ignored) {
                runOnUiThread(() -> {
                    lastMt5Bid = Double.NaN;
                    lastMt5Ask = Double.NaN;
                    updatePriceComparison();
                });
            }
        });
    }

    private void updatePriceComparison() {
        JSONObject s=EventClient.state(),q=s.optJSONObject("quote"),cfg=s.optJSONObject("config"),rs=s.optJSONObject("risk");
        String bid=q==null?"—":fmt(q.optDouble("bid",Double.NaN));String ask=q==null?"—":fmt(q.optDouble("ask",Double.NaN));
        priceCompareText.setText("MT5 Bid/Ask: "+bid+" / "+ask+"\nИсточник анализа и исполнения: MT5"+
            "\nБаза расчёта риска (отдельно от баланса): "+(rs==null?"—":money(rs.optDouble("base",Double.NaN),"USD"))+
            "\nПлановый риск всей кампании: "+(rs==null?"—":money(rs.optDouble("campaign_budget",Double.NaN),"USD")));
    }

    private Analysis analyzeAdaptive(String symbol,
                                     String entryTf,
                                     List<Candle> fast,
                                     String fastLabel,
                                     List<Candle> entrySeries,
                                     String entryLabel,
                                     List<Candle> higher1,
                                     String higher1Label,
                                     List<Candle> higher2,
                                     String higher2Label) {

        int sFast = trendScore(fast);
        int sEntry = trendScore(entrySeries);
        int sHigher1 = trendScore(higher1);
        int sHigher2 = trendScore(higher2);

        int structure = structureScore(entrySeries);
        int breakout = breakoutScore(entrySeries);

        Candle last = entrySeries.get(entrySeries.size() - 1);
        double entry = last.close;
        double atr = atr(entrySeries, 14);

        if (atr <= 0) {
            atr = Math.max(
                    minStopDistance(symbol),
                    last.high - last.low
            );
        }

        String mode = selectedSignalMode();
        // V10 NORMAL PATTERN -> CONFIRM -> ENTRY.
        // Entry starts from a recognised price pattern/structure, not from quality alone.
        int patternV10 = patternScoreV10(entrySeries);
        int buyVotesV10 = 0, sellVotesV10 = 0;
        int[] votesV10 = {sHigher2, sHigher1, sEntry, sFast, structure};
        for (int v : votesV10) { if (v > 0) buyVotesV10++; else if (v < 0) sellVotesV10++; }

        boolean buyPatternV10 = patternV10 > 0;
        boolean sellPatternV10 = patternV10 < 0;
        boolean buyContextV10 = sEntry >= 0 && sFast >= 0 && structure >= 0 && buyVotesV10 >= 3 && sellVotesV10 <= 1;
        boolean sellContextV10 = sEntry <= 0 && sFast <= 0 && structure <= 0 && sellVotesV10 >= 3 && buyVotesV10 <= 1;

        String candidateSignalV10 = buyPatternV10 && buyContextV10 ? "BUY" :
                (sellPatternV10 && sellContextV10 ? "SELL" : "WAIT");

        int quality = setupQualityAdaptive(candidateSignalV10, sHigher2, sHigher1, sEntry, sFast, structure, breakout);
        if ("BUY".equals(candidateSignalV10)) quality = Math.min(100, quality + Math.max(0, patternV10) * 5);
        if ("SELL".equals(candidateSignalV10)) quality = Math.min(100, quality + Math.max(0, -patternV10) * 5);

        int timingV10 = entryTimingV10(entrySeries);
        int wantedV10 = "BUY".equals(candidateSignalV10) ? 1 : ("SELL".equals(candidateSignalV10) ? -1 : 0);
        int momentumV10 = momentumConfirmV10(entrySeries);

        // A scheme must exist. Confirmation can be a clean pullback/retest OR a fresh
        // directional continuation candle. We no longer require a standalone breakout.
        boolean confirmationV10 = wantedV10 != 0 && (timingV10 == wantedV10 || momentumV10 == wantedV10);
        boolean entryReadyV10 = wantedV10 != 0 && quality >= 78 && confirmationV10;

        String signal = entryReadyV10 ? candidateSignalV10 : "WAIT";
        String executionSignal = signal;
        double scalpAtr = atr; // compatibility field only; NORMAL is the only runtime mode.

        double slMult = 1.8;
        double tp1R = 1.5;
        double tp2R = 2.0;
        double riskAtr = atr;
        double slDist = Math.max(
                riskAtr * slMult,
                minStopDistance(symbol)
        );

        double sl = 0;
        double tp1 = 0;
        double tp2 = 0;

        String protectionSignal = executionSignal;
        if ("BUY".equals(protectionSignal)) {
            sl = entry - slDist;
            tp1 = entry + slDist * tp1R;
            tp2 = entry + slDist * tp2R;
        } else if ("SELL".equals(protectionSignal)) {
            sl = entry + slDist;
            tp1 = entry - slDist * tp1R;
            tp2 = entry - slDist * tp2R;
        }

        String reason;

        if (breakout > 0) {
            reason = entryLabel + ": подтверждён пробой/импульс вверх";
        } else if (breakout < 0) {
            reason = entryLabel + ": подтверждён пробой/импульс вниз";
        } else {
            reason = patternV10 != 0 ? entryLabel + ": схема найдена · ждём/проверяем подтверждение" : entryLabel + ": подходящая схема ещё не сформирована";
        }

        String filter;

        if ("BUY".equals(signal)) {
            filter = "Фильтр: " + mode + " разрешил BUY";
        } else if ("SELL".equals(signal)) {
            filter = "Фильтр: " + mode + " разрешил SELL";
        } else if (!"WAIT".equals(executionSignal)) {
            filter = "Фильтр: " + mode + " · EXEC " + executionSignal + " внутри WAIT";
        } else {
            filter = "Фильтр: " + mode + " · условия для входа не совпали";
        }

        String context =
                "Вход: " + entryTf + " · Режим: " + mode +
                "\n" + higher2Label + " " + arrow(sHigher2) +
                "   " + higher1Label + " " + arrow(sHigher1) +
                "   " + entryLabel + " " + arrow(sEntry) +
                "   " + fastLabel + " " + arrow(sFast) +
                "\nСтруктура " + entryLabel + ": " + arrow(structure) +
                "\n" + reason +
                "\n" + filter +
                ("SCALP".equals(mode) ? "\nSCALP " + entryTf + ": " + executionSignal + " · timing " + arrow(sFast) : "") +
                "\nATR " + entryLabel + ": " + fmt(atr);

        String components = SignalScore.describe(candidateSignalV10, sHigher2, sHigher1, sEntry, sFast, structure, breakout, patternV10);

        ArrayList<String> whyParts = new ArrayList<>();
        if (sHigher1 != 0 && sHigher2 != 0 && sHigher1 != sHigher2) whyParts.add("старшие ТФ расходятся");
        if (sEntry == 0) whyParts.add(entryLabel + " без направления");
        if (sEntry != 0 && sFast != 0 && sFast != sEntry) whyParts.add(fastLabel + " против входа");
        if (structure == 0) whyParts.add("структура не подтверждена");
        if (breakout == 0) whyParts.add("отдельный пробой не обязателен");
        String why;
        if ("WAIT".equals(signal)) {
            why = whyParts.isEmpty() ? "условия режима " + mode + " не совпали одновременно" : android.text.TextUtils.join("; ", whyParts);
        } else {
            why = "Сигнал анализа " + signal + ": условия анализа выполнены; качество " + quality + "/100. Это не подтверждение открытия позиции.";
        }

        return new Analysis(
                symbol,
                signal,
                executionSignal,
                quality,
                entry,
                sl,
                tp1,
                tp2,
                context,
                why,
                components
        );
    }


    // V10 NORMAL pattern/structure confirmation.
    // Positive = bullish structure, negative = bearish structure.
    private int momentumConfirmV10(List<Candle> s) {
        if (s == null || s.size() < 5) return 0;
        int n = s.size();
        Candle a = s.get(n-3), b = s.get(n-2), x = s.get(n-1);
        double body = x.close - x.open;
        double range = Math.max(1e-12, x.high - x.low);
        boolean buy = body > range * 0.18 && x.close > b.close && b.close >= a.close
                && x.close >= b.high - (b.high-b.low)*0.20;
        boolean sell = -body > range * 0.18 && x.close < b.close && b.close <= a.close
                && x.close <= b.low + (b.high-b.low)*0.20;
        if (buy && !sell) return 1;
        if (sell && !buy) return -1;
        return 0;
    }

    private int patternScoreV10(List<Candle> s) {
        if (s == null || s.size() < 12) return 0;
        int n = s.size();
        Candle a = s.get(n - 4), b = s.get(n - 3), c = s.get(n - 2), d = s.get(n - 1);
        int score = 0;

        // HH/HL or LH/LL continuation structure.
        if (d.high > c.high && d.low > c.low) score += 2;
        if (d.high < c.high && d.low < c.low) score -= 2;

        // Local range breakout.
        double hi = -Double.MAX_VALUE, lo = Double.MAX_VALUE;
        for (int i = Math.max(0, n - 10); i < n - 1; i++) {
            hi = Math.max(hi, s.get(i).high);
            lo = Math.min(lo, s.get(i).low);
        }
        if (d.close > hi) score += 2;
        if (d.close < lo) score -= 2;

        // Pullback/retest and resume.
        if (b.close > a.close && c.close <= b.close && d.close > c.high) score += 2;
        if (b.close < a.close && c.close >= b.close && d.close < c.low) score -= 2;

        // Compression / triangle-like contraction followed by direction.
        double oldRange = Math.max(1e-9, s.get(n - 6).high - s.get(n - 6).low);
        double newRange = Math.max(1e-9, c.high - c.low);
        if (newRange < oldRange * 0.75) {
            if (d.close > c.high) score += 1;
            if (d.close < c.low) score -= 1;
        }

        // Approximate double bottom / double top confirmation.
        double atr = atr(s, 14);
        double tol = Math.max(atr * 0.35, 1e-9);
        Candle p1 = s.get(n - 6), p2 = s.get(n - 3);
        if (Math.abs(p1.low - p2.low) <= tol && d.close > Math.max(p1.high, p2.high)) score += 1;
        if (Math.abs(p1.high - p2.high) <= tol && d.close < Math.min(p1.low, p2.low)) score -= 1;

        return Math.max(-8, Math.min(8, score));
    }

    // Entry timing: do not chase the end of an impulse.
    // Requires a fresh resume/break after a pullback/retest.
    private int entryTimingV10(List<Candle> s) {
        if (s == null || s.size() < 5) return 0;
        int n = s.size();
        Candle a = s.get(n - 4), b = s.get(n - 3), c = s.get(n - 2), d = s.get(n - 1);
        double atr = atr(s, 14);
        if (atr <= 0) atr = Math.max(1e-9, d.high - d.low);

        boolean buyPullback = b.close >= a.close && c.low <= b.low + atr * 0.20 && d.close > c.high;
        boolean sellPullback = b.close <= a.close && c.high >= b.high - atr * 0.20 && d.close < c.low;

        if (buyPullback) return 1;
        if (sellPullback) return -1;
        return 0;
    }

    private int scalpExecutionDirection(List<Candle> s, double atr) {
        if (s == null || s.size() < 5) return 0;
        int n = s.size();
        Candle a = s.get(n - 4), b = s.get(n - 3), c = s.get(n - 2), d = s.get(n - 1);
        double move1 = d.close - c.close;
        double move2 = c.close - b.close;
        double net = d.close - a.close;
        double body = d.close - d.open;
        double localRange = Math.max(1e-12, (b.high - b.low) + (c.high - c.low) + (d.high - d.low));
        double floor = Math.max(atr * 0.045, localRange * 0.010);
        int impulse = scalpImpulse(s);
        if (impulse != 0) return impulse;
        boolean buy = (move1 > 0 && move2 >= 0 && net > floor) || (body > 0 && move1 > 0 && net > floor * 1.20);
        boolean sell = (move1 < 0 && move2 <= 0 && -net > floor) || (body < 0 && move1 < 0 && -net > floor * 1.20);
        if (buy && !sell) return 1;
        if (sell && !buy) return -1;
        return 0;
    }

    private int scalpImpulse(List<Candle> s) {
        if (s == null || s.size() < 6) return 0;
        int n = s.size();
        Candle a = s.get(n-4), b = s.get(n-3), c = s.get(n-2), d = s.get(n-1);
        double up = 0.0, down = 0.0;
        Candle[] arr = {a,b,c,d};
        for (Candle x : arr) {
            double body = x.close - x.open;
            if (body > 0) up += body; else down += -body;
        }
        boolean rising = d.close > c.close && c.close >= b.close;
        boolean falling = d.close < c.close && c.close <= b.close;
        double range = Math.max(1e-12, (d.high-d.low) + (c.high-c.low));
        double micro = d.close - c.close;
        double net = d.close - b.close;

        // Strong M1 impulse.
        if (rising && up > down * 1.03 && micro > range * 0.018) return 1;
        if (falling && down > up * 1.03 && -micro > range * 0.018) return -1;

        // CURRENT SCALP micro-entry: MAIN may still look neutral, but a small fresh
        // directional move can arm a scalp entry. We still require direction + body
        // dominance so a single random tick does not become a trade.
        double microFloor = range * 0.008;
        if (micro > microFloor && net >= 0 && up >= down * 0.90) return 1;
        if (-micro > microFloor && net <= 0 && down >= up * 0.90) return -1;
        return 0;
    }

    private int setupQualityAdaptive(String signal,
                                     int higher2,
                                     int higher1,
                                     int entry,
                                     int fast,
                                     int structure,
                                     int breakout) {

        if ("WAIT".equals(signal)) {
            int alignment = Math.abs(higher2 + higher1 + entry + fast);
            int q = 25 + alignment * 7;

            if (structure != 0) q += 5;
            if (breakout != 0) q += 8;

            return Math.min(59, q);
        }

        int direction = "BUY".equals(signal) ? 1 : -1;
        int q = 60;

        if (higher2 == direction) q += 8;
        if (higher1 == direction) q += 8;
        if (entry == direction) q += 8;
        if (fast == direction) q += 4;
        if (structure == direction) q += 5;

        if (breakout == direction * 2) {
            q += 7;
        } else if (breakout == direction) {
            q += 4;
        }

        return Math.min(100, q);
    }

    private double minStopDistance(String symbol) {
        if (symbol.startsWith("XAU/")) {
            return 1.00;
        }

        if (symbol.contains("JPY")) {
            return 0.050;
        }

        return 0.00050;
    }

    private int trendScore(List<Candle> c) {
        double ema9 = ema(c, 9);
        double ema21 = ema(c, 21);

        int s = ema9 > ema21
                ? 1
                : ema9 < ema21
                ? -1
                : 0;

        int n = c.size();
        double recentStart = c.get(Math.max(0, n - 10)).close;
        double recentEnd = c.get(n - 1).close;

        if (recentEnd > recentStart) {
            s++;
        } else if (recentEnd < recentStart) {
            s--;
        }

        if (s > 0) return 1;
        if (s < 0) return -1;
        return 0;
    }

    private double ema(List<Candle> c, int period) {
        double alpha = 2.0 / (period + 1.0);
        double e = c.get(0).close;

        for (int i = 1; i < c.size(); i++) {
            e = alpha * c.get(i).close + (1 - alpha) * e;
        }

        return e;
    }

    private int structureScore(List<Candle> c) {
        int n = c.size();

        if (n < 10) return 0;

        Candle a = c.get(n - 6);
        Candle b = c.get(n - 1);

        if (b.high > a.high && b.low > a.low) {
            return 1;
        }

        if (b.high < a.high && b.low < a.low) {
            return -1;
        }

        return 0;
    }

    private int breakoutScore(List<Candle> c) {
        int n = c.size();

        if (n < 30) return 0;

        Candle last = c.get(n - 1);
        double resistance = -Double.MAX_VALUE;
        double support = Double.MAX_VALUE;

        for (int i = n - 22; i < n - 2; i++) {
            resistance = Math.max(
                    resistance,
                    c.get(i).high
            );

            support = Math.min(
                    support,
                    c.get(i).low
            );
        }

        double a = atr(c, 14);
        double body = Math.abs(last.close - last.open);

        if (last.close > resistance) {
            return body > a * 0.50 ? 2 : 1;
        }

        if (last.close < support) {
            return body > a * 0.50 ? -2 : -1;
        }

        return 0;
    }

    private double atr(List<Candle> c, int period) {
        if (c.size() < period + 1) return 0;

        double sum = 0;
        int start = c.size() - period;

        for (int i = start; i < c.size(); i++) {
            Candle cur = c.get(i);
            Candle prev = c.get(i - 1);

            double tr = Math.max(
                    cur.high - cur.low,
                    Math.max(
                            Math.abs(cur.high - prev.close),
                            Math.abs(cur.low - prev.close)
                    )
            );

            sum += tr;
        }

        return sum / period;
    }

    private String arrow(int s) {
        return s > 0
                ? "↑"
                : s < 0
                ? "↓"
                : "→";
    }


    private String formatClock(long ms) {
        if (ms <= 0L) return "—";
        java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("HH:mm:ss", Locale.getDefault());
        return f.format(new Date(ms));
    }

    private String formatElapsed(long sinceMs) {
        if (sinceMs <= 0L) return "—";
        long sec = Math.max(0L, (System.currentTimeMillis() - sinceMs) / 1000L);
        long h = sec / 3600L;
        long m = (sec % 3600L) / 60L;
        long s = sec % 60L;
        if (h > 0L) return String.format(Locale.US, "%02d:%02d:%02d", h, m, s);
        return String.format(Locale.US, "%02d:%02d", m, s);
    }

    private String formatElapsedUntil(long sinceMs, long untilMs) {
        if (sinceMs <= 0L || untilMs <= 0L) return "—";
        long sec = Math.max(0L, (untilMs - sinceMs) / 1000L);
        long h = sec / 3600L;
        long m = (sec % 3600L) / 60L;
        long s = sec % 60L;
        if (h > 0L) return String.format(Locale.US, "%02d:%02d:%02d", h, m, s);
        return String.format(Locale.US, "%02d:%02d", m, s);
    }

    private void updateSignalAgeText(String signal, long sinceMs, long updatedMs) {
        if (signalAgeText == null) return;

        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        boolean active = p.getBoolean("bg_running", false);
        long stoppedAt = p.getLong("monitor_stopped_ms", 0L);
        long lastAttempt = p.getLong("state_last_attempt_ms", 0L);
        long lastSuccess = p.getLong("state_last_success_ms", updatedMs);
        long reference = active ? System.currentTimeMillis() : (stoppedAt > 0L ? stoppedAt : System.currentTimeMillis());

        if ("BUY".equals(signal) || "SELL".equals(signal)) {
            String elapsed = active ? formatElapsed(sinceMs) : formatElapsedUntil(sinceMs, reference);
            signalAgeText.setText(
                    "Сигнал " + signal + " с: " + formatClock(sinceMs) +
                    "\nДлительность сигнала: " + elapsed +
                    "\nПоследняя проверка: " + formatClock(lastAttempt) +
                    "\nПоследний успешный анализ: " + formatClock(lastSuccess) +
                    (active ? "" : " · мониторинг остановлен")
            );
            signalAgeText.setTextColor("SELL".equals(signal) ? C_RED : C_GREEN);
        } else {
            if (updatedMs <= 0L) {
                signalAgeText.setText(active ? "Ожидаю первый анализ…" : "Мониторинг остановлен.");
            } else if (active) {
                signalAgeText.setText(
                        "Последняя проверка: " + formatClock(lastAttempt) +
                        "\nПоследний успешный анализ: " + formatClock(lastSuccess) +
                        "  ·  " + formatElapsed(lastSuccess) + " назад"
                );
            } else {
                signalAgeText.setText("Мониторинг остановлен · последний анализ: " + formatClock(updatedMs));
            }
            signalAgeText.setTextColor(C_ORANGE);
        }
    }

    private void publishUnifiedSignalState(
            Analysis a, int freshRequests, int cachedRequests, String source
    ) {
        long now = System.currentTimeMillis();
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        String key = a.symbol + "|" + selectedEntryTimeframe();
        String oldKey = p.getString("state_signal_key", "");
        String oldSignal = p.getString("state_signal", "WAIT");
        long since = p.getLong("state_signal_since_ms", 0L);

        if (!key.equals(oldKey) || !a.signal.equals(oldSignal) || since <= 0L) {
            since = "WAIT".equals(a.signal) ? 0L : now;
        }
        if ("WAIT".equals(a.signal)) since = 0L;

        p.edit()
                .putString("state_signal_key", key)
                .putString("state_symbol", a.symbol)
                .putString("state_tf", selectedEntryTimeframe())
                .putString("state_signal", a.signal)
                .putInt("state_quality", a.quality)
                .putString("state_context", a.context)
                .putString("state_why", a.why)
                .putString("state_components", a.components)
                .putLong("state_entry_bits", Double.doubleToLongBits(a.entry))
                .putLong("state_sl_bits", Double.doubleToLongBits(a.sl))
                .putLong("state_tp1_bits", Double.doubleToLongBits(a.tp1))
                .putLong("state_tp2_bits", Double.doubleToLongBits(a.tp2))
                .putInt("state_api_count", freshRequests)
                .putInt("state_cache_count", cachedRequests)
                .putLong("state_signal_since_ms", since)
                .putLong("state_last_update_ms", now)
                .putString("state_source", source)
                .apply();
    }

    private void showAnalysis(Analysis a,
                              int freshRequests,
                              int cachedRequests) {

        statusText.setText(
                a.symbol +
                " · " + selectedEntryTimeframe() +
                " · MON · API " + freshRequests +
                " · кэш " + cachedRequests
        );

        publishUnifiedSignalState(a, freshRequests, cachedRequests, "MON");
        signalText.setText(a.signal);

        if ("BUY".equals(a.signal)) {
            signalText.setTextColor(C_GREEN);
        } else if ("SELL".equals(a.signal)) {
            signalText.setTextColor(C_RED);
        } else {
            signalText.setTextColor(C_PURPLE);
        }

        confidenceText.setTextColor(C_PURPLE);
        confidenceText.setText(
                "Качество сигнала: " +
                a.quality +
                "/100"
        );
        if (qualityBarView != null) { qualityBarView.setQuality(a.quality); qualityBarView.setSignal(a.signal); }

        long nowMs = System.currentTimeMillis();
        SharedPreferences localPrefs = getSharedPreferences("fxm1", MODE_PRIVATE);
        String localKey = a.symbol + "|" + selectedEntryTimeframe();
        String prevKey = localPrefs.getString("local_signal_key", "");
        String prevSignal = localPrefs.getString("local_signal_value", "WAIT");
        long localSince = localPrefs.getLong("local_signal_since_ms", 0L);
        if (!localKey.equals(prevKey) || !a.signal.equals(prevSignal) || localSince <= 0L) {
            localSince = nowMs;
            localPrefs.edit()
                    .putString("local_signal_key", localKey)
                    .putString("local_signal_value", a.signal)
                    .putLong("local_signal_since_ms", localSince)
                    .apply();
        }
        updateSignalAgeText(a.signal, localSince, nowMs);

        if ("WAIT".equals(a.signal)) {
            levelsText.setText(
                    "Entry: " + fmt(a.entry) +
                    "\nSL: —" +
                    "\nTP1: —" +
                    "\nTP2: —"
            );
        } else {
            levelsText.setText(
                    "Entry: " + fmt(a.entry) +
                    "\nSL: " + fmt(a.sl) +
                    "\nTP1: " + fmt(a.tp1) + "  (1.5R)" +
                    "\nTP2: " + fmt(a.tp2) + "  (2.0R)"
            );
        }

        contextText.setText(a.context);
        if (whyWaitText != null) whyWaitText.setText(("WAIT".equals(a.signal) ? "ПОЧЕМУ WAIT: " : "СИГНАЛ АНАЛИЗА: ") + a.why + ExecutionFeedback.render(localPrefs, a.symbol, selectedEntryTimeframe()));
        if (componentScoresText != null) componentScoresText.setText("КОМПОНЕНТЫ КАЧЕСТВА: " + a.components);
        FeatureEngine.appendSignalHistory(getSharedPreferences("fxm1", MODE_PRIVATE), a.symbol, selectedEntryTimeframe(), a.signal, a.quality, "analysis");
        refreshSmartUi();

        lastApiPrice = a.entry;
        updatePriceComparison();
        refreshMt5Quote(a.symbol);
    }

    private String fmt(double x) {
        if (x == 0) return "—";

        if (x >= 100) {
            return String.format(
                    Locale.US,
                    "%.3f",
                    x
            );
        }

        return String.format(
                Locale.US,
                "%.5f",
                x
        );
    }

    @Override
    protected void onDestroy() {
        monitorHandler.removeCallbacks(monitorRunnable);
        serviceUiHandler.removeCallbacks(serviceUiRunnable);

        executor.shutdownNow();
        super.onDestroy();
    }

    static class Candle {
        final double open;
        final double high;
        final double low;
        final double close;

        Candle(double open,
               double high,
               double low,
               double close) {

            this.open = open;
            this.high = high;
            this.low = low;
            this.close = close;
        }
    }

    static class Analysis {
        final String symbol;
        final String signal;
        final String executionSignal;
        final String context;
        final String why;
        final String components;
        final int quality;
        final double entry;
        final double sl;
        final double tp1;
        final double tp2;

        Analysis(String symbol,
                 String signal,
                 String executionSignal,
                 int quality,
                 double entry,
                 double sl,
                 double tp1,
                 double tp2,
                 String context,
                 String why,
                 String components) {

            this.symbol = symbol;
            this.signal = signal;
            this.executionSignal = executionSignal;
            this.quality = quality;
            this.entry = entry;
            this.sl = sl;
            this.tp1 = tp1;
            this.tp2 = tp2;
            this.context = context;
            this.why = why;
            this.components = components;
        }
    }

    static class CacheItem {
        final List<Candle> data;
        final long savedAtMs;

        CacheItem(List<Candle> data,
                  long savedAtMs) {

            this.data = data;
            this.savedAtMs = savedAtMs;
        }
    }

    static class FetchResult {
        final List<Candle> data;
        final boolean fromCache;

        FetchResult(List<Candle> data,
                    boolean fromCache) {

            this.data = data;
            this.fromCache = fromCache;
        }
    }

    static class RateLimitException extends Exception {
        RateLimitException(String message) {
            super(message);
        }
    }

    private EditText eventNumber(LinearLayout box,String label,String value){
        box.addView(smartLabel(label));EditText v=new EditText(this);v.setTextColor(C_TEXT);v.setHintTextColor(C_MUTED);v.setSingleLine(true);v.setInputType(android.text.InputType.TYPE_CLASS_NUMBER|android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL);v.setText(value);box.addView(v);return v;
    }
    private void eventCommand(String cmd,JSONObject data){
        final JSONObject envelope;try{envelope=EventClient.envelope(data);}catch(Exception e){addJournal(safeMessage(e));return;}
        executor.execute(()->{try{JSONObject r=EventClient.http("POST",EventClient.base()+"/ec/command/"+cmd,envelope);
            if("reset".equals(cmd))getSharedPreferences("fxm1",MODE_PRIVATE).edit().putBoolean("v108_emergency_latched",false).putBoolean("ec_emergency_pending",false).apply();
            EventClient.poll();runOnUiThread(()->{addJournal(r.optString("message"));restoreTradingSnapshotFromPrefs();});
        }catch(Exception e){runOnUiThread(()->new AlertDialog.Builder(this).setTitle("EventCore").setMessage(safeMessage(e)).setPositiveButton("OK",null).show());}});
    }
}
