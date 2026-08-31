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
    private Button analyzeButton, saveKeyButton, serverCheckButton, emergencyStopButton, closeAllButton, smartFeaturesButton, syncMt5SymbolsButton, managePositionsButton;
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
    private boolean suppressAutoSwitch = false;
    private boolean syncingScalpTimeframe = false;
    private long emergencyTapMs = 0L;

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
        syncMt5SymbolsButton = findViewById(R.id.syncMt5SymbolsButton);
        managePositionsButton = findViewById(R.id.managePositionsButton);
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
        updateMarketStatusUi();

        loadSyncedMt5Symbols();
        loadCustomSymbols();
        if (!symbolItems.contains("＋ ДОБАВИТЬ ИНСТРУМЕНТ")) symbolItems.add("＋ ДОБАВИТЬ ИНСТРУМЕНТ");
        symbolAdapter = darkSpinnerAdapter(symbolItems.toArray(new String[0]));
        symbolSpinner.setAdapter(symbolAdapter);

        ArrayAdapter<String> timeframeAdapter = darkSpinnerAdapter(
                new String[]{"M1", "M5", "M15", "H1", "H4", "D1", "W1", "MN1"}
        );
        entryTimeframeSpinner.setAdapter(timeframeAdapter);

        ArrayAdapter<String> modeAdapter = darkSpinnerAdapter(
                new String[]{"CONSERVATIVE", "NORMAL", "AGGRESSIVE", "SCALP"}
        );
        signalModeSpinner.setAdapter(modeAdapter);

        SharedPreferences prefs = getSharedPreferences("fxm1", MODE_PRIVATE);
        FeatureEngine.ensureDefaults(prefs);
        monitoring = prefs.getBoolean("bg_running", false);
        String savedSymbol = prefs.getString("selected_symbol", "EUR/USD");
        int savedSymbolIndex = symbolItems.indexOf(savedSymbol);
        symbolSpinner.setSelection(savedSymbolIndex >= 0 ? savedSymbolIndex : 0);
        entryTimeframeSpinner.setSelection(prefs.getInt("entry_tf_pos", 1));
        signalModeSpinner.setSelection(prefs.getInt("signal_mode_pos", 1));
        apiKeyInput.setText(prefs.getString("apikey", ""));
        serverUrlInput.setText(stripServerScheme(prefs.getString("server_url", "")));
        setApiKeyEditMode(prefs.getString("apikey", "").trim().isEmpty());
        boolean savedServerVerified = prefs.getBoolean("server_verified", false)
                && !prefs.getString("server_url", "").trim().isEmpty();
        setServerEditMode(!savedServerVerified);

        ArrayAdapter<String> riskAdapter = darkSpinnerAdapter(
                new String[]{"0.25%", "0.50%", "1.00%"}
        );
        riskSpinner.setAdapter(riskAdapter);
        riskSpinner.setSelection(prefs.getInt("risk_pos", 1));

        ArrayAdapter<String> maxPosAdapter = darkSpinnerAdapter(
                new String[]{"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}
        );
        maxPositionsSpinner.setAdapter(maxPosAdapter);
        maxPositionsSpinner.setSelection(prefs.getInt("maxpos_pos", 0));

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
                Toast.makeText(this, "Введите Twelve Data API key", Toast.LENGTH_SHORT).show();
                return;
            }

            prefs.edit().putString("apikey", key).apply();
            setApiKeyEditMode(false);

            if (getSharedPreferences("fxm1", MODE_PRIVATE).getBoolean("bg_running", false)) {
                sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
            }
            Toast.makeText(this, "API key сохранён", Toast.LENGTH_SHORT).show();
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
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

        maxPositionsSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                prefs.edit().putInt("maxpos_pos", position).putString("maxpos_label", String.valueOf(maxPositionsSpinner.getSelectedItem())).apply();
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

        entryTimeframeSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (syncingScalpTimeframe) return;

                // Rule CURRENT: SCALP is an M1 entry mode only.
                // Selecting M1 manually NEVER forces SCALP.
                // Selecting any TF other than M1 while SCALP is active switches mode to NORMAL.
                if (!"M1".equals(selectedEntryTimeframe()) && "SCALP".equals(selectedSignalMode())) {
                    syncingScalpTimeframe = true;
                    signalModeSpinner.setSelection(1); // NORMAL
                    prefs.edit()
                            .putInt("entry_tf_pos", position)
                            .putInt("signal_mode_pos", 1)
                            .apply();
                    syncingScalpTimeframe = false;
                    Toast.makeText(MainActivity.this,
                            "SCALP работает на M1. Режим переключён на NORMAL.",
                            Toast.LENGTH_SHORT).show();
                } else {
                    prefs.edit().putInt("entry_tf_pos", position).apply();
                }

                lastSentSignal.clear();
                lastAlertSignal.clear();

                if (monitoring) {
                    statusText.setText("Таймфрейм изменён на " + selectedEntryTimeframe() + " · обновляю…");
                    sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
                }
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

        signalModeSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (syncingScalpTimeframe) return;

                // Rule CURRENT: choosing SCALP forces entry TF to M1.
                // Choosing M1 itself does not select SCALP.
                if ("SCALP".equals(selectedSignalMode()) && !"M1".equals(selectedEntryTimeframe())) {
                    syncingScalpTimeframe = true;
                    entryTimeframeSpinner.setSelection(0); // M1
                    prefs.edit()
                            .putInt("signal_mode_pos", position)
                            .putInt("entry_tf_pos", 0)
                            .apply();
                    syncingScalpTimeframe = false;
                    Toast.makeText(MainActivity.this,
                            "SCALP: таймфрейм входа автоматически установлен M1.",
                            Toast.LENGTH_SHORT).show();
                } else {
                    prefs.edit().putInt("signal_mode_pos", position).apply();
                }

                // CURRENT DEMO behaviour: SCALP is an automated execution mode.
                // If Bridge+MT5 are already connected to a DEMO account, selecting SCALP
                // arms AUTO immediately so a valid scalp BUY/SELL can actually reach MT5.
                if ("SCALP".equals(selectedSignalMode()) && serverConnected && mt5Connected && demoAccount) {
                    autoTradingSwitch.setChecked(true);
                }

                // CURRENT: SCALP uses a basket. If the old 1-3 limit is still selected,
                // raise the safety cap to 8. User can still choose any value 1..10 manually.
                if ("SCALP".equals(selectedSignalMode()) && maxPositionsSpinner.getSelectedItemPosition() <= 2) {
                    maxPositionsSpinner.setSelection(7); // 8 positions
                    prefs.edit().putInt("maxpos_pos", 7).putString("maxpos_label", "8").apply();
                }

                lastSentSignal.clear();
                lastAlertSignal.clear();
                if (getSharedPreferences("fxm1", MODE_PRIVATE).getBoolean("bg_running", false)) {
                    sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
                }
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

        // Normalize an old saved invalid combination (SCALP + M5/M15/etc.) once at startup.
        if ("SCALP".equals(selectedSignalMode()) && !"M1".equals(selectedEntryTimeframe())) {
            syncingScalpTimeframe = true;
            entryTimeframeSpinner.setSelection(0);
            prefs.edit().putInt("entry_tf_pos", 0).apply();
            syncingScalpTimeframe = false;
        }

        maxDriftSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                prefs.edit().putInt("maxdrift_pos", position).apply();
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

        autoTradingSwitch.setOnCheckedChangeListener((buttonView, isChecked) -> {
            if (suppressAutoSwitch) return;

            if (isChecked) {
                if (!serverConnected || !mt5Connected) {
                    forceAutoOff("AUTO не включён: сервер/MT5 не подключены.");
                    Toast.makeText(this, "Сначала подключите сервер и MT5", Toast.LENGTH_LONG).show();
                    return;
                }
                if (!demoAccount) {
                    forceAutoOff("AUTO заблокирован: V" + appVersionName() + " разрешает только DEMO.");
                    Toast.makeText(this, "V" + appVersionName() + " разрешает автоторговлю только на DEMO", Toast.LENGTH_LONG).show();
                    return;
                }
                prefs.edit().putBoolean("auto_trading", true).apply();
                if (autoStatusText != null) { autoStatusText.setText("AUTO включён · DEMO · новые сигналы могут исполняться"); autoStatusText.setTextColor(C_GREEN); }
                addJournal("AUTO TRADING включён · DEMO");
            } else {
                prefs.edit().putBoolean("auto_trading", false).apply();
                if (autoStatusText != null) { autoStatusText.setText("AUTO выключен · DEMO ONLY"); autoStatusText.setTextColor(C_MUTED); }
                addJournal("AUTO TRADING выключен");
            }
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
        syncMt5SymbolsButton.setOnClickListener(v -> syncSymbolsFromMt5());
        managePositionsButton.setOnClickListener(v -> showPositionsManager());
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
        if (journal != null) journal.setOnClickListener(v -> scrollToView(journalCard));
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
        styleOutlineButton(syncMt5SymbolsButton, C_PURPLE);
        styleOutlineButton(managePositionsButton, C_PURPLE);

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
        positionsText.setText("Открытые позиции: —\nТекущий P/L: —");
        lastMt5Bid = Double.NaN;
        lastMt5Ask = Double.NaN;
        updatePriceComparison();
        closeAllButton.setEnabled(false);
        forceAutoOff(null);
    }

    private String appVersionName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "7.4.4";
        }
    }

    private void applyRuntimeVersionLabels() {
        String v = appVersionName();
        if (versionBadgeText != null) versionBadgeText.setText("V" + v);
        if (smartTitleText != null) smartTitleText.setText("УМНЫЕ ФУНКЦИИ V" + v);
        if (footerVersionText != null) footerVersionText.setText("V" + v + " · SCALP · WATCHDOG · SMART RISK · MT5 BRIDGE");
    }

    private void forceAutoOff(String journalMessage) {
        suppressAutoSwitch = true;
        autoTradingSwitch.setChecked(false);
        suppressAutoSwitch = false;
        getSharedPreferences("fxm1", MODE_PRIVATE).edit().putBoolean("auto_trading", false).apply();
        if (journalMessage != null) addJournal(journalMessage);
    }

    private void restoreTradingSnapshotFromPrefs() {
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        String savedUrl = p.getString("server_url", "").trim();
        boolean verified = p.getBoolean("server_verified", false) && !savedUrl.isEmpty();
        boolean mt5 = p.getBoolean("mt5_connected_snapshot", false);
        String accountType = p.getString("mt5_account_type_snapshot", "UNKNOWN");
        String currency = p.getString("mt5_currency_snapshot", "USD");
        String bridgeVersion = p.getString("bridge_version_snapshot", "?");
        double balance = Double.longBitsToDouble(p.getLong("mt5_balance_bits", Double.doubleToLongBits(Double.NaN)));
        double equity = Double.longBitsToDouble(p.getLong("mt5_equity_bits", Double.doubleToLongBits(Double.NaN)));
        int positions = p.getInt("mt5_positions_snapshot", 0);
        double floating = Double.longBitsToDouble(p.getLong("mt5_floating_bits", Double.doubleToLongBits(0.0)));

        if (verified) {
            serverConnected = true;
            mt5Connected = mt5;
            demoAccount = "DEMO".equalsIgnoreCase(accountType);
            serverStatusText.setText("APP V" + appVersionName() + "   •   BRIDGE V" + bridgeVersion + "\nSERVER: CONNECTED   •   MT5: " + (mt5 ? "CONNECTED" : "OFFLINE"));
            serverStatusText.setTextColor(mt5 ? C_GREEN : C_RED);
            accountText.setText("Счёт: " + accountType + "\nБаланс: " + money(balance, currency) + "\nEquity: " + money(equity, currency));
            positionsText.setText("Открытые позиции: " + positions + "\nТекущий P/L: " + signedMoney(floating, currency));
            closeAllButton.setEnabled(mt5 && demoAccount && positions > 0);
            suppressAutoSwitch = true;
            boolean scalpDemo = "SCALP".equals(selectedSignalMode()) && mt5 && demoAccount;
            boolean autoSaved = p.getBoolean("auto_trading", false) && mt5 && demoAccount;
            autoTradingSwitch.setChecked(autoSaved || scalpDemo);
            if (scalpDemo) p.edit().putBoolean("auto_trading", true).apply();
            suppressAutoSwitch = false;
        } else {
            setTradingControlsOffline();
        }
    }

    private void restoreSparklineFromPrefs(String signal) {
        if (sparklineView == null) return;
        String raw = getSharedPreferences("fxm1", MODE_PRIVATE).getString("state_sparkline", "");
        if (raw == null || raw.trim().isEmpty()) return;
        List<Double> points = new ArrayList<>();
        for (String part : raw.split(",")) {
            try { points.add(Double.parseDouble(part)); } catch (Exception ignored) {}
        }
        if (points.size() >= 2) {
            sparklineView.setValues(points);
            sparklineView.setSignal(signal);
        }
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

                runOnUiThread(() -> {
                    serverCheckButton.setEnabled(true);
                    serverConnected = serverOk;
                    mt5Connected = mt5Ok;
                    demoAccount = "DEMO".equals(accountType);

                    serverStatusText.setText(
                            "APP V" + appVersionName() + "   •   BRIDGE V" + bridgeVersion + "\n" +
                            "SERVER: " + (serverOk ? "CONNECTED" : "ERROR") +
                            "   •   MT5: " + (mt5Ok ? "CONNECTED" : "OFFLINE")
                    );
                    serverStatusText.setTextColor(
                            serverOk && mt5Ok ? C_GREEN : C_RED
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
                    positionsText.setText(
                            "Открытые позиции: " + positions +
                            "\nТекущий P/L: " + signedMoney(floating, currency)
                    );
                    getSharedPreferences("fxm1", MODE_PRIVATE).edit()
                            .putBoolean("mt5_connected_snapshot", serverOk && mt5Ok)
                            .putString("mt5_account_type_snapshot", accountType)
                            .putLong("mt5_balance_bits", Double.doubleToLongBits(balance))
                            .putLong("mt5_equity_bits", Double.doubleToLongBits(equity))
                            .putString("mt5_currency_snapshot", currency)
                            .putString("bridge_version_snapshot", bridgeVersion)
                            .putInt("mt5_positions_snapshot", positions)
                            .putLong("mt5_floating_bits", Double.doubleToLongBits(floating))
                            .apply();
                    closeAllButton.setEnabled(serverOk && mt5Ok && demoAccount && positions > 0);

                    if (!serverOk || !mt5Ok || !demoAccount) {
                        forceAutoOff(null);
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

    private void maybeSendSignalToServer(Analysis a) {
        if (!isForexMarketOpen()) {
            addJournal("MARKET CLOSED · новый ордер заблокирован");
            return;
        }
        if (!autoTradingSwitch.isChecked() || !serverConnected || !mt5Connected || !demoAccount) {
            return;
        }

        boolean scalp = "SCALP".equals(selectedSignalMode());
        String tradeSignal = scalp ? a.executionSignal : a.signal;
        if ("WAIT".equals(tradeSignal)) {
            lastSentSignal.put(a.symbol, "WAIT");
            return;
        }

        String previous = lastSentSignal.get(a.symbol);
        if (!scalp && tradeSignal.equals(previous)) return;

        lastSentSignal.put(a.symbol, tradeSignal);
        final String base = normalizeServerUrl(serverUrlInput.getText().toString());
        final String risk = (String) riskSpinner.getSelectedItem();
        final String maxPositions = (String) maxPositionsSpinner.getSelectedItem();

        executor.execute(() -> {
            try {
                JSONObject payload = new JSONObject();
                payload.put("symbol", a.symbol);
                payload.put("signal", tradeSignal);
                payload.put("quality", a.quality);
                payload.put("entry", a.entry);
                payload.put("sl", a.sl);
                payload.put("tp1", a.tp1);
                payload.put("tp2", a.tp2);
                double basketRiskPct = Double.parseDouble(risk.replace("%", ""));
                int basketMaxPositions = Integer.parseInt(maxPositions);
                payload.put("risk_pct", basketRiskPct);
                payload.put("max_positions", basketMaxPositions);
                if ("SCALP".equals(selectedSignalMode())) {
                    payload.put("basket_mode", true);
                    payload.put("allow_same_symbol_multiple", true);
                    payload.put("basket_risk_pct", basketRiskPct);
                    payload.put("risk_pct", basketRiskPct / Math.max(1, basketMaxPositions));
                    // V7.4.4: SCALP uses a separate money manager in Bridge.
                    // The percent spinner remains a global safety preference, not a per-scalp cash loss target.
                    payload.put("scalp_money_manager", true);
                    payload.put("scalp_risk_usd_cap", 5.0);
                    payload.put("scalp_hard_loss_usd_cap", 10.0);
                    payload.put("scalp_profit_protect_usd_cap", 3.0);
                    payload.put("scalp_take_profit_usd_cap", 8.0);
                    payload.put("scalp_basket_risk_usd_cap", 20.0);
                    payload.put("basket_add_cooldown_sec", 5);
                    payload.put("basket_min_progress_sl", 0.04);
                }
                payload.put("mode", "DEMO");
                payload.put("signal_mode", selectedSignalMode());
                payload.put("entry_timeframe", selectedEntryTimeframe());
                payload.put("api_entry", a.entry);
                payload.put("max_price_drift_pct", selectedMaxDriftPct());
                payload.put("execution_price_source", "MT5");
                FeatureEngine.applySignalFeatures(payload, getSharedPreferences("fxm1", MODE_PRIVATE), a.why, a.components);

                JSONObject response = httpJson("POST", base + "/signal", payload);
                boolean accepted = response.optBoolean("accepted", false);
                String message = response.optString("message", accepted ? "Сигнал принят" : "Сигнал отклонён");

                runOnUiThread(() -> {
                    addJournal(a.symbol + " SCALP " + tradeSignal + ("WAIT".equals(a.signal) ? " (micro inside WAIT)" : "") + " → " + message);
                    FeatureEngine.appendSignalHistory(getSharedPreferences("fxm1", MODE_PRIVATE), a.symbol, selectedEntryTimeframe(), tradeSignal, a.quality, ("WAIT".equals(a.signal) ? "MICRO inside WAIT · " : "") + message);
                    refreshSmartUi();
                    refreshStatsAndPositions();
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    lastSentSignal.put(a.symbol, "WAIT");
                    addJournal("Не отправлен " + a.symbol + " " + tradeSignal + ": " + safeMessage(e));
                });
            }
        });
    }

    private void executeEmergencyStop() {
        forceAutoOff("EMERGENCY STOP: AUTO выключен, запрошено закрытие всех позиций.");
        getSharedPreferences("fxm1", MODE_PRIVATE).edit()
                .putBoolean("stop_all_requested", true)
                .putBoolean("trading_paused", false)
                .apply();
        sendBackgroundCommand(MonitoringService.ACTION_EMERGENCY_CONFIRMED);
        monitoring = false;
        monitorHandler.removeCallbacks(monitorRunnable);
        analyzeButton.setText("ЗАПУСТИТЬ МОНИТОРИНГ");
        addJournal("EMERGENCY STOP · CLOSE ALL запрошен");
        Toast.makeText(this, "EMERGENCY STOP: закрытие позиций и остановка AUTO", Toast.LENGTH_LONG).show();
    }

    private void sendCloseAll() {
        if (!serverConnected || !mt5Connected || !demoAccount) {
            Toast.makeText(this, "Нет подключённого DEMO MT5", Toast.LENGTH_SHORT).show();
            return;
        }

        final String base = normalizeServerUrl(serverUrlInput.getText().toString());
        closeAllButton.setEnabled(false);
        forceAutoOff("AUTO выключен перед командой CLOSE ALL.");

        executor.execute(() -> {
            try {
                JSONObject payload = new JSONObject();
                payload.put("mode", "DEMO");
                JSONObject response = httpJson("POST", base + "/close-all", payload);
                String message = response.optString("message", "Команда отправлена");
                runOnUiThread(() -> {
                    addJournal("CLOSE ALL → " + message);
                    checkServer();
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    addJournal("CLOSE ALL ошибка: " + safeMessage(e));
                    closeAllButton.setEnabled(true);
                });
            }
        });
    }

    private JSONObject httpJson(String method, String url, JSONObject payload) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(8000);
        conn.setReadTimeout(10000);
        conn.setRequestMethod(method);
        conn.setRequestProperty("Accept", "application/json");

        if (payload != null) {
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] bytes = payload.toString().getBytes(StandardCharsets.UTF_8);
            OutputStream os = conn.getOutputStream();
            os.write(bytes);
            os.flush();
            os.close();
        }

        int code = conn.getResponseCode();
        InputStream is = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
        String body = readAll(is);
        if (code < 200 || code >= 300) throw new Exception("HTTP " + code + ": " + body);
        return new JSONObject(body);
    }

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
    }

    private void setApiKeyEditMode(boolean editing) {
        if (apiKeyLabel != null) {
            apiKeyLabel.setVisibility(editing ? View.VISIBLE : View.GONE);
        }
        apiKeyInput.setVisibility(editing ? View.VISIBLE : View.GONE);
        saveKeyButton.setText(editing ? "СОХРАНИТЬ API KEY" : "ИЗМЕНИТЬ API KEY");
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
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        FeatureEngine.ensureDefaults(p);
        ScrollView scroll = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(18), dp(6), dp(18), dp(10));
        scroll.addView(box);

        TextView intro = new TextView(this);
        intro.setText("Все функции ниже реально влияют на торговый цикл. Risk Manager рассчитывает размер позиции от Equity и SL; Break-even переносит SL в цену входа; Trailing сопровождает прибыль; Partial Close фиксирует часть позиции; Spread Filter блокирует дорогой вход; Cooldown не даёт роботу входить слишком часто.");
        intro.setTextColor(C_TEXT);
        intro.setTextSize(13f);
        intro.setLineSpacing(0f, 1.18f);
        intro.setPadding(0, dp(6), 0, dp(10));
        box.addView(intro);

        box.addView(smartLabel("РЕЖИМ ИСПОЛНЕНИЯ"));
        String[] execModes = {"SIGNALS_ONLY", "SEMI_AUTO", "FULL_AUTO"};
        int execSel = Arrays.asList(execModes).indexOf(p.getString("execution_mode", "FULL_AUTO"));
        Spinner exec = smartSpinner(execModes, execSel < 0 ? 2 : execSel); box.addView(exec);

        Switch riskM = smartSwitch("Умный риск-менеджер", p.getBoolean("risk_manager_enabled", true)); box.addView(riskM);
        box.addView(smartLabel("Лимит убытка за день")); Spinner daily = smartSpinner(new String[]{"2%","3%","4%","5%"}, Math.max(0, Math.min(3, Math.round(p.getFloat("daily_loss_limit_pct",3f))-2))); box.addView(daily);
        box.addView(smartLabel("Макс. просадка equity")); Spinner dd = smartSpinner(new String[]{"3%","5%","7%","10%"}, p.getFloat("max_drawdown_pct",5f)>=10?3:p.getFloat("max_drawdown_pct",5f)>=7?2:p.getFloat("max_drawdown_pct",5f)>=5?1:0); box.addView(dd);
        box.addView(smartLabel("Стоп после убыточных сделок подряд")); Spinner streak = smartSpinner(new String[]{"2","3","4","5"}, Math.max(0, Math.min(3,p.getInt("max_consecutive_losses",3)-2))); box.addView(streak);

        Switch be = smartSwitch("Break-even (перенос SL в цену входа)", p.getBoolean("break_even_enabled", true)); box.addView(be);
        Switch trailing = smartSwitch("Trailing stop", p.getBoolean("trailing_enabled", true)); box.addView(trailing);
        Switch partial = smartSwitch("Частичное закрытие 50% на 1.5R", p.getBoolean("partial_close_enabled", true)); box.addView(partial);
        Switch spread = smartSwitch("Фильтр спреда", p.getBoolean("spread_filter_enabled", true)); box.addView(spread);
        box.addView(smartLabel("Максимальный spread")); Spinner spreadSp = smartSpinner(new String[]{"1.5 pips","2.0 pips","3.0 pips","5.0 pips"}, p.getFloat("max_spread_pips",3f)>=5?3:p.getFloat("max_spread_pips",3f)>=3?2:p.getFloat("max_spread_pips",3f)>=2?1:0); box.addView(spreadSp);
        Switch confirm = smartSwitch("Подтверждать рискованные входы", p.getBoolean("confirm_risky_entries", true)); box.addView(confirm);
        box.addView(smartLabel("Ручное подтверждение ниже качества")); Spinner quality = smartSpinner(new String[]{"55/100","60/100","65/100","70/100","75/100"}, Math.max(0, Math.min(4,(p.getInt("confirm_below_quality",65)-55)/5))); box.addView(quality);
        box.addView(smartLabel("Cooldown после закрытия")); Spinner cooldown = smartSpinner(new String[]{"0 мин","5 мин","10 мин","20 мин","30 мин"}, p.getInt("cooldown_minutes",10)>=30?4:p.getInt("cooldown_minutes",10)>=20?3:p.getInt("cooldown_minutes",10)>=10?2:p.getInt("cooldown_minutes",10)>=5?1:0); box.addView(cooldown);
        Switch multi = smartSwitch("Multi-pair radar (дополнительный обзор watchlist)", p.getBoolean("multi_pair_enabled", false)); box.addView(multi);
        box.addView(smartLabel("WATCHLIST / ИЗБРАННОЕ через запятую"));
        EditText watchlistEdit = new EditText(this);
        watchlistEdit.setSingleLine(true);
        watchlistEdit.setText(p.getString("watchlist", "EUR/USD,GBP/USD,USD/JPY"));
        watchlistEdit.setTextColor(C_TEXT); watchlistEdit.setHintTextColor(C_MUTED); watchlistEdit.setHint("EUR/USD,GBP/USD,USD/JPY");
        box.addView(watchlistEdit, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(48)));
        Switch session = smartSwitch("Фильтр торговых сессий", p.getBoolean("session_filter_enabled", false)); box.addView(session);
        Switch positionManager = smartSwitch("Автосопровождение позиций", p.getBoolean("position_manager_enabled", true)); box.addView(positionManager);
        Switch news = smartSwitch("Ручная пауза перед важной новостью на 30 минут", p.getBoolean("manual_news_blackout", false)); box.addView(news);

        AlertDialog smartDialog = new AlertDialog.Builder(this)
                .setTitle("Умные функции V" + appVersionName())
                .setView(scroll)
                .setNegativeButton("ОТМЕНА", null)
                .setPositiveButton("СОХРАНИТЬ", (d,w) -> {
                    float[] dailyVals={2f,3f,4f,5f}; float[] ddVals={3f,5f,7f,10f}; int[] streakVals={2,3,4,5};
                    float[] spreadVals={1.5f,2f,3f,5f}; int[] qualityVals={55,60,65,70,75}; int[] cooldownVals={0,5,10,20,30};
                    long blackout = news.isChecked() ? (System.currentTimeMillis()/1000L + 30*60L) : 0L;
                    p.edit()
                            .putString("execution_mode", execModes[exec.getSelectedItemPosition()])
                            .putBoolean("risk_manager_enabled", riskM.isChecked())
                            .putFloat("daily_loss_limit_pct", dailyVals[daily.getSelectedItemPosition()])
                            .putFloat("max_drawdown_pct", ddVals[dd.getSelectedItemPosition()])
                            .putInt("max_consecutive_losses", streakVals[streak.getSelectedItemPosition()])
                            .putBoolean("break_even_enabled", be.isChecked())
                            .putBoolean("trailing_enabled", trailing.isChecked())
                            .putBoolean("partial_close_enabled", partial.isChecked())
                            .putBoolean("spread_filter_enabled", spread.isChecked())
                            .putFloat("max_spread_pips", spreadVals[spreadSp.getSelectedItemPosition()])
                            .putBoolean("confirm_risky_entries", confirm.isChecked())
                            .putInt("confirm_below_quality", qualityVals[quality.getSelectedItemPosition()])
                            .putInt("cooldown_minutes", cooldownVals[cooldown.getSelectedItemPosition()])
                            .putBoolean("multi_pair_enabled", multi.isChecked())
                            .putString("watchlist", watchlistEdit.getText().toString().trim())
                            .putString("favorite_symbols", watchlistEdit.getText().toString().trim())
                            .putBoolean("session_filter_enabled", session.isChecked())
                            .putBoolean("position_manager_enabled", positionManager.isChecked())
                            .putBoolean("manual_news_blackout", news.isChecked())
                            .putLong("news_blackout_until_epoch", blackout)
                            .apply();
                    refreshSmartUi();
                    if (monitoring) sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
                })
                .create();
        smartDialog.setOnShowListener(d -> {
            if (smartDialog.getWindow() != null) {
                GradientDrawable dlgBg = new GradientDrawable();
                dlgBg.setColor(C_CARD);
                dlgBg.setCornerRadius(dp(16));
                smartDialog.getWindow().setBackgroundDrawable(dlgBg);
            }
            int titleId = getResources().getIdentifier("alertTitle", "id", "android");
            TextView titleView = smartDialog.findViewById(titleId);
            if (titleView != null) titleView.setTextColor(C_TEXT);
            smartDialog.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(C_PURPLE);
            smartDialog.getButton(AlertDialog.BUTTON_NEGATIVE).setTextColor(C_TEXT);
        });
        smartDialog.show();
    }

    private void refreshSmartUi() {
        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        FeatureEngine.ensureDefaults(p);
        if (smartStatusText != null) {
            String radar = p.getString("watchlist_radar", "");
            String manager = p.getString("position_manager_status", "—");
            String risk = p.getString("risk_snapshot", "—");
            smartStatusText.setText(FeatureEngine.featureSummary(p) +
                    "\nPosition manager: " + manager + " · " + risk +
                    (radar == null || radar.isEmpty() ? "" : "\nRadar: " + radar));
        }
        if (statsText != null) {
            String snap = p.getString("stats_snapshot", "");
            if (snap != null && !snap.trim().isEmpty()) statsText.setText("СТАТИСТИКА\n" + snap);
        }
        if (signalHistoryText != null) {
            String h = p.getString("signal_history", "");
            signalHistoryText.setText(h == null || h.trim().isEmpty() ? "ИСТОРИЯ СИГНАЛОВ: пока пусто" : "ИСТОРИЯ СИГНАЛОВ\n" + h);
        }
    }

    private String serverBaseFromPrefs() {
        return normalizeServerUrl(getSharedPreferences("fxm1", MODE_PRIVATE).getString("server_url", ""));
    }

    private void refreshStatsAndPositions() {
        final String base = serverBaseFromPrefs();
        if (base.isEmpty() || !serverConnected) return;
        executor.execute(() -> {
            try {
                JSONObject st = FeatureEngine.httpJson("GET", base + "/stats?days=30", null);
                JSONObject pos = FeatureEngine.httpJson("GET", base + "/positions", null);
                JSONObject log = FeatureEngine.httpJson("GET", base + "/trade-log?limit=20", null);
                String stText = FeatureEngine.formatStats(st);
                String posText = FeatureEngine.formatPositions(pos);
                String logText = FeatureEngine.formatTradeLog(log);
                runOnUiThread(() -> {
                    if (statsText != null) statsText.setText("СТАТИСТИКА\n" + stText);
                    if (positionsText != null) positionsText.setText(posText);
                    if (tradeHistoryText != null) tradeHistoryText.setText(logText);
                });
            } catch (Exception e) {
                runOnUiThread(() -> { if (statsText != null) statsText.setText("СТАТИСТИКА: " + safeMessage(e)); });
            }
        });
    }

    private void syncSymbolsFromMt5() {
        final String base = serverBaseFromPrefs();
        if (base.isEmpty() || !serverConnected) {
            Toast.makeText(this, "Сначала подключите MT5 Bridge", Toast.LENGTH_SHORT).show();
            return;
        }
        syncMt5SymbolsButton.setEnabled(false);
        executor.execute(() -> {
            try {
                JSONObject root = FeatureEngine.httpJson("GET", base + "/symbols", null);
                JSONArray arr = root.optJSONArray("symbols");
                final ArrayList<String> incoming = new ArrayList<>();
                if (arr != null) for (int i=0;i<arr.length();i++) {
                    JSONObject o=arr.optJSONObject(i); if(o==null) continue;
                    String name=o.optString("symbol","").trim(); if(!name.isEmpty() && !incoming.contains(name)) incoming.add(name);
                    if (incoming.size() >= 300) break;
                }
                runOnUiThread(() -> {
                    syncMt5SymbolsButton.setEnabled(true);
                    if (incoming.isEmpty()) { Toast.makeText(this,"MT5 не вернул символы",Toast.LENGTH_SHORT).show(); return; }
                    String selected = String.valueOf(symbolSpinner.getSelectedItem());
                    symbolItems.clear(); symbolItems.addAll(incoming); symbolItems.add("＋ ДОБАВИТЬ ИНСТРУМЕНТ");
                    getSharedPreferences("fxm1", MODE_PRIVATE).edit().putString("mt5_symbols_cache", android.text.TextUtils.join("|", incoming)).apply();
                    symbolAdapter = darkSpinnerAdapter(symbolItems.toArray(new String[0]));
                    symbolSpinner.setAdapter(symbolAdapter);
                    int idx=symbolItems.indexOf(selected); symbolSpinner.setSelection(idx>=0?idx:0);
                    Toast.makeText(this,"Загружено символов MT5: "+incoming.size(),Toast.LENGTH_LONG).show();
                });
            } catch(Exception e) { runOnUiThread(() -> { syncMt5SymbolsButton.setEnabled(true); Toast.makeText(this,"Символы MT5: "+safeMessage(e),Toast.LENGTH_LONG).show(); }); }
        });
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

    private void showPositionActions(String base, JSONObject pos) {
        String[] actions={"CLOSE POSITION","MOVE SL → BREAK EVEN","PARTIAL CLOSE 50%"};
        new AlertDialog.Builder(this).setTitle(pos.optString("symbol")+" #"+pos.optLong("ticket")).setItems(actions,(d,which)->{
            String action=which==0?"close":which==1?"breakeven":"partial";
            executor.execute(() -> {
                try{
                    JSONObject req=new JSONObject(); req.put("ticket",pos.optLong("ticket")); req.put("action",action); if("partial".equals(action))req.put("pct",50);
                    JSONObject r=FeatureEngine.httpJson("POST",base+"/position-action",req);
                    runOnUiThread(() -> { addJournal("Позиция #"+pos.optLong("ticket")+" · "+action+" → "+r.optString("message")); refreshStatsAndPositions(); });
                }catch(Exception e){ runOnUiThread(() -> Toast.makeText(this,"Действие: "+safeMessage(e),Toast.LENGTH_LONG).show()); }
            });
        }).setNegativeButton("ОТМЕНА",null).show();
    }

    private void startMonitoring() {
        String key = apiKeyInput.getText().toString().trim();

        if (key.isEmpty()) {
            Toast.makeText(this, "Сначала вставьте Twelve Data API key", Toast.LENGTH_LONG).show();
            return;
        }

        SharedPreferences prefs = getSharedPreferences("fxm1", MODE_PRIVATE);
        prefs.edit()
                .putString("apikey", key)
                .putInt("symbol_pos", symbolSpinner.getSelectedItemPosition())
                .putString("selected_symbol", String.valueOf(symbolSpinner.getSelectedItem()))
                .putInt("entry_tf_pos", entryTimeframeSpinner.getSelectedItemPosition())
                .putInt("signal_mode_pos", signalModeSpinner.getSelectedItemPosition())
                .putBoolean("ui_monitoring", true)
                .putLong("monitor_stopped_ms", 0L)
                .apply();

        // Один мониторинг = один foreground service. Он продолжает работу после сворачивания APK.
        if (Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestNotificationPermissionIfNeeded();
            statusText.setText("Разрешите уведомления — они нужны Android для постоянного мониторинга.");
            return;
        }

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
        if (p.getBoolean("server_verified", false)) restoreTradingSnapshotFromPrefs();
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
            confidenceText.setText("Качество сигнала: —");
            updateSignalAgeText("WAIT", 0L, 0L);
            levelsText.setText("Entry: —\nSL: —\nTP1: —\nTP2: —");
            contextText.setText("Параметры изменены. Жду новый анализ для " + selectedSymbol + " · " + selectedTf + ".");
            if (whyWaitText != null) whyWaitText.setText("ПОЧЕМУ WAIT: жду новый анализ");
            if (componentScoresText != null) componentScoresText.setText("КОМПОНЕНТЫ КАЧЕСТВА: —");
            return;
        }

        double entry = Double.longBitsToDouble(p.getLong("state_entry_bits", Double.doubleToLongBits(Double.NaN)));
        double sl = Double.longBitsToDouble(p.getLong("state_sl_bits", Double.doubleToLongBits(Double.NaN)));
        double tp1 = Double.longBitsToDouble(p.getLong("state_tp1_bits", Double.doubleToLongBits(Double.NaN)));
        double tp2 = Double.longBitsToDouble(p.getLong("state_tp2_bits", Double.doubleToLongBits(Double.NaN)));

        statusText.setText(symbol + " · " + tf + " · " + source + " · API " + fresh + " · кэш " + cached);

        signalText.setText(signal);
        signalText.setTextColor("BUY".equals(signal) ? C_GREEN : ("SELL".equals(signal) ? C_RED : C_PURPLE));

        confidenceText.setText(quality >= 0 ? "Качество сигнала: " + quality + "/100" : "Качество сигнала: —");
        confidenceText.setTextColor(C_PURPLE);
        if (qualityBarView != null) { qualityBarView.setQuality(Math.max(0, quality)); qualityBarView.setSignal(signal); }
        updateSignalAgeText(signal, since, updated);
        restoreSparklineFromPrefs(signal);

        if ("WAIT".equals(signal)) {
            levelsText.setText("Entry: " + (Double.isNaN(entry) ? "—" : fmt(entry)) + "\nSL: —\nTP1: —\nTP2: —");
        } else {
            levelsText.setText(
                    "Entry: " + fmt(entry) +
                    "\nSL: " + fmt(sl) +
                    "\nTP1: " + fmt(tp1) + "  (1.5R)" +
                    "\nTP2: " + fmt(tp2) + "  (2.0R)"
            );
        }
        contextText.setText(context);
        if (whyWaitText != null) whyWaitText.setText(("WAIT".equals(signal) ? "ПОЧЕМУ WAIT: " : "ПОЧЕМУ ВХОД: ") + (why == null || why.isEmpty() ? "—" : why));
        if (componentScoresText != null) componentScoresText.setText("КОМПОНЕНТЫ КАЧЕСТВА: " + (components == null || components.isEmpty() ? "—" : components));
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

    private void runAnalysis() {
        if (!monitoring || isAnalyzing) return;

        final String key = apiKeyInput.getText().toString().trim();
        final String symbol = (String) symbolSpinner.getSelectedItem();

        isAnalyzing = true;
        statusText.setText(symbol + " · обновляю рынок…");

        executor.execute(() -> {
            try {
                String entryTf = selectedEntryTimeframe();

                FetchResult fast;
                FetchResult entry;
                FetchResult higher1;
                FetchResult higher2;

                String fastLabel;
                String entryLabel;
                String higher1Label;
                String higher2Label;

                if ("M1".equals(entryTf)) {
                    entry = getSeries(symbol, "1min", key, 120, CACHE_M1_MS);
                    fast = entry;
                    higher1 = getSeries(symbol, "5min", key, 100, CACHE_M5_MS);
                    higher2 = getSeries(symbol, "15min", key, 100, CACHE_M15_MS);
                    FetchResult h1 = getSeries(symbol, "1h", key, 100, CACHE_H1_MS);

                    Analysis a = analyzeAdaptive(
                            symbol,
                            entryTf,
                            entry.data, "M1",
                            higher1.data, "M5",
                            higher2.data, "M15",
                            h1.data, "H1"
                    );

                    int freshRequests =
                            (entry.fromCache ? 0 : 1) +
                            (higher1.fromCache ? 0 : 1) +
                            (higher2.fromCache ? 0 : 1) +
                            (h1.fromCache ? 0 : 1);
                    int cachedRequests = 4 - freshRequests;

                    final Analysis result = a;
                    final int fresh = freshRequests;
                    final int cached = cachedRequests;

                    runOnUiThread(() -> {
                        isAnalyzing = false;
                        showAnalysis(result, fresh, cached);
                        alertIfNewTradeSignal(result);
                        maybeSendSignalToServer(result);
                        scheduleNext(selectedMonitorIntervalMs());
                    });
                    return;

                } else if ("M5".equals(entryTf)) {
                    fast = getSeries(symbol, "1min", key, 120, CACHE_M1_MS);
                    entry = getSeries(symbol, "5min", key, 120, CACHE_M5_MS);
                    higher1 = getSeries(symbol, "15min", key, 100, CACHE_M15_MS);
                    higher2 = getSeries(symbol, "1h", key, 100, CACHE_H1_MS);

                    fastLabel = "M1";
                    entryLabel = "M5";
                    higher1Label = "M15";
                    higher2Label = "H1";

                } else if ("M15".equals(entryTf)) {
                    fast = getSeries(symbol, "5min", key, 120, CACHE_M5_MS);
                    entry = getSeries(symbol, "15min", key, 120, CACHE_M15_MS);
                    higher1 = getSeries(symbol, "1h", key, 100, CACHE_H1_MS);
                    higher2 = getSeries(symbol, "4h", key, 100, CACHE_H4_MS);

                    fastLabel = "M5";
                    entryLabel = "M15";
                    higher1Label = "H1";
                    higher2Label = "H4";

                } else if ("H1".equals(entryTf)) {
                    fast = getSeries(symbol, "15min", key, 120, CACHE_M15_MS);
                    entry = getSeries(symbol, "1h", key, 120, CACHE_H1_MS);
                    higher1 = getSeries(symbol, "4h", key, 100, CACHE_H4_MS);
                    higher2 = getSeries(symbol, "1day", key, 100, CACHE_D1_MS);
                    fastLabel = "M15"; entryLabel = "H1"; higher1Label = "H4"; higher2Label = "D1";
                } else if ("H4".equals(entryTf)) {
                    fast = getSeries(symbol, "1h", key, 120, CACHE_H1_MS);
                    entry = getSeries(symbol, "4h", key, 120, CACHE_H4_MS);
                    higher1 = getSeries(symbol, "1day", key, 100, CACHE_D1_MS);
                    higher2 = getSeries(symbol, "1week", key, 100, CACHE_W1_MS);
                    fastLabel = "H1"; entryLabel = "H4"; higher1Label = "D1"; higher2Label = "W1";
                } else if ("D1".equals(entryTf)) {
                    fast = getSeries(symbol, "4h", key, 120, CACHE_H4_MS);
                    entry = getSeries(symbol, "1day", key, 120, CACHE_D1_MS);
                    higher1 = getSeries(symbol, "1week", key, 100, CACHE_W1_MS);
                    higher2 = getSeries(symbol, "1month", key, 100, CACHE_MN1_MS);
                    fastLabel = "H4"; entryLabel = "D1"; higher1Label = "W1"; higher2Label = "MN1";
                } else if ("W1".equals(entryTf)) {
                    fast = getSeries(symbol, "1day", key, 120, CACHE_D1_MS);
                    entry = getSeries(symbol, "1week", key, 120, CACHE_W1_MS);
                    higher1 = getSeries(symbol, "1month", key, 100, CACHE_MN1_MS);
                    higher2 = higher1;
                    fastLabel = "D1"; entryLabel = "W1"; higher1Label = "MN1"; higher2Label = "MN1";
                } else {
                    fast = getSeries(symbol, "1week", key, 120, CACHE_W1_MS);
                    entry = getSeries(symbol, "1month", key, 120, CACHE_MN1_MS);
                    higher1 = entry;
                    higher2 = entry;
                    fastLabel = "W1"; entryLabel = "MN1"; higher1Label = "MN1"; higher2Label = "MN1";
                }

                Analysis a = analyzeAdaptive(
                        symbol,
                        entryTf,
                        fast.data, fastLabel,
                        entry.data, entryLabel,
                        higher1.data, higher1Label,
                        higher2.data, higher2Label
                );

                int freshRequests =
                        (fast.fromCache ? 0 : 1) +
                        (entry.fromCache ? 0 : 1) +
                        (higher1.fromCache ? 0 : 1) +
                        (higher2.fromCache ? 0 : 1);

                int cachedRequests = 4 - freshRequests;

                runOnUiThread(() -> {
                    isAnalyzing = false;
                    if (sparklineView != null) {
                        List<Double> pts = new ArrayList<>();
                        int from = Math.max(0, entry.data.size() - 30);
                        for (int i = from; i < entry.data.size(); i++) { Candle c = entry.data.get(i); pts.add((c.high + c.low + c.close) / 3.0); }
                        sparklineView.setValues(pts);
                        sparklineView.setSignal(a.signal);
                    }
                    updateMarketStatusUi();
                    showAnalysis(a, freshRequests, cachedRequests);
                    alertIfNewTradeSignal(a);
                    maybeSendSignalToServer(a);
                    scheduleNext(selectedMonitorIntervalMs());
                });

            } catch (RateLimitException e) {
                runOnUiThread(() -> {
                    isAnalyzing = false;

                    signalText.setText("WAIT");
                    signalText.setTextColor(C_PURPLE);
                    statusText.setText("Лимит Twelve Data на эту минуту исчерпан.");
                    confidenceText.setText("Автоповтор примерно через 60 секунд.");
                    levelsText.setText("Entry: —\nSL: —\nTP1: —\nTP2: —");
                    contextText.setText(
                            "Мониторинг остаётся включён.\n" +
                            "Приложение автоматически повторит запрос после паузы."
                    );

                    scheduleNext(60000L);
                });

            } catch (Exception e) {
                runOnUiThread(() -> {
                    isAnalyzing = false;

                    signalText.setText("ERROR");
                    signalText.setTextColor(C_PURPLE);
                    statusText.setText("Ошибка: " + safeMessage(e));
                    confidenceText.setText("Следующая попытка через " + selectedMonitorLabel() + ".");
                    levelsText.setText("Entry: —\nSL: —\nTP1: —\nTP2: —");

                    scheduleNext(selectedMonitorIntervalMs());
                });
            }
        });
    }

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


    private String selectedEntryTimeframe() {
        Object selected = entryTimeframeSpinner.getSelectedItem();
        return selected == null ? "M5" : selected.toString();
    }

    private long selectedMonitorIntervalMs() {
        String tf = selectedEntryTimeframe();
        if ("M1".equals(tf)) return "SCALP".equals(selectedSignalMode()) ? 5000L : 10000L;
        if ("M5".equals(tf)) return 60000L;
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

    private String selectedSignalMode() {
        Object selected = signalModeSpinner.getSelectedItem();
        return selected == null ? "NORMAL" : selected.toString();
    }

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
        String api = Double.isNaN(lastApiPrice) ? "—" : fmt(lastApiPrice);
        String bid = Double.isNaN(lastMt5Bid) ? "—" : fmt(lastMt5Bid);
        String ask = Double.isNaN(lastMt5Ask) ? "—" : fmt(lastMt5Ask);

        String diff = "—";
        if (!Double.isNaN(lastApiPrice) && lastApiPrice != 0 &&
                !Double.isNaN(lastMt5Bid) && !Double.isNaN(lastMt5Ask)) {
            double mid = (lastMt5Bid + lastMt5Ask) / 2.0;
            double pct = Math.abs(mid - lastApiPrice) / lastApiPrice * 100.0;
            diff = String.format(Locale.US, "%.4f%%", pct);
        }

        priceCompareText.setText(
                "API Price: " + api +
                "\nMT5 Bid/Ask: " + bid + " / " + ask +
                "\nРазница: " + diff +
                "\nEXECUTION PRICE: MT5"
        );
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

        boolean buySetup;
        boolean sellSetup;

        if ("CONSERVATIVE".equals(mode)) {
            buySetup =
                    sHigher2 >= 0 &&
                    sHigher1 > 0 &&
                    sEntry > 0 &&
                    sFast >= 0 &&
                    structure >= 0 &&
                    breakout > 0;

            sellSetup =
                    sHigher2 <= 0 &&
                    sHigher1 < 0 &&
                    sEntry < 0 &&
                    sFast <= 0 &&
                    structure <= 0 &&
                    breakout < 0;

        } else if ("SCALP".equals(mode)) {
            // V7.4.4: SCALP impulse MUST come from the fast M1 series.
            // In the M1 analysis mapping entrySeries is M5 context, so using entrySeries here
            // accidentally made the scalper wait for M5. M5/M15 remain context only.
            int impulse = scalpImpulse(fast);
            boolean m1 = "M1".equals(entryTf);
            buySetup = m1 && impulse > 0 && sFast >= 0;
            sellSetup = m1 && impulse < 0 && sFast <= 0;

        } else if ("AGGRESSIVE".equals(mode)) {
            int buyVotes = 0;
            int sellVotes = 0;

            if (sHigher2 > 0) buyVotes++; else if (sHigher2 < 0) sellVotes++;
            if (sHigher1 > 0) buyVotes++; else if (sHigher1 < 0) sellVotes++;
            if (sEntry > 0) buyVotes++; else if (sEntry < 0) sellVotes++;
            if (sFast > 0) buyVotes++; else if (sFast < 0) sellVotes++;
            if (structure > 0) buyVotes++; else if (structure < 0) sellVotes++;

            buySetup =
                    sEntry > 0 &&
                    sHigher1 >= 0 &&
                    breakout >= 0 &&
                    buyVotes >= 3 &&
                    sellVotes <= 1;

            sellSetup =
                    sEntry < 0 &&
                    sHigher1 <= 0 &&
                    breakout <= 0 &&
                    sellVotes >= 3 &&
                    buyVotes <= 1;

        } else {
            // NORMAL: таймфрейм входа + два старших ТФ должны смотреть
            // в одну сторону. Младший ТФ не должен идти явно против.
            // Пробой желателен, но отсутствие пробоя не блокирует вход.
            buySetup =
                    sHigher2 >= 0 &&
                    sHigher1 > 0 &&
                    sEntry > 0 &&
                    sFast >= 0 &&
                    structure >= 0 &&
                    breakout >= 0;

            sellSetup =
                    sHigher2 <= 0 &&
                    sHigher1 < 0 &&
                    sEntry < 0 &&
                    sFast <= 0 &&
                    structure <= 0 &&
                    breakout <= 0;
        }

        String signal = buySetup
                ? "BUY"
                : sellSetup
                ? "SELL"
                : "WAIT";

        // V7.4.4: display signal and SCALP execution trigger are separate.
        // The card may remain WAIT, but the execution trigger reads the actual M1 fast series,
        // not the M5 context series. This is the key fix for micro entries inside WAIT.
        String executionSignal = signal;
        double scalpAtr = atr;
        if ("SCALP".equals(mode) && "M1".equals(entryTf)) {
            double m1Atr = atr(fast, 14);
            if (m1Atr > 0) scalpAtr = m1Atr;
            if ("WAIT".equals(signal)) {
                int microDirection = scalpExecutionDirection(fast, scalpAtr);
                if (microDirection > 0) executionSignal = "BUY";
                else if (microDirection < 0) executionSignal = "SELL";
            }
        }

        int quality = setupQualityAdaptive(
                signal,
                sHigher2,
                sHigher1,
                sEntry,
                sFast,
                structure,
                breakout
        );

        double slMult = "SCALP".equals(mode) ? 0.85 : 1.8;
        double tp1R = "SCALP".equals(mode) ? 0.9 : 1.5;
        double tp2R = "SCALP".equals(mode) ? 1.4 : 2.0;
        double riskAtr = "SCALP".equals(mode) ? scalpAtr : atr;
        double slDist = Math.max(
                riskAtr * slMult,
                minStopDistance(symbol)
        );

        double sl = 0;
        double tp1 = 0;
        double tp2 = 0;

        String protectionSignal = "SCALP".equals(mode) ? executionSignal : signal;
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
            reason = entryLabel + ": подтверждённого пробоя нет";
        }

        String filter;

        if ("BUY".equals(signal)) {
            filter = "Фильтр: " + mode + " разрешил BUY";
        } else if ("SELL".equals(signal)) {
            filter = "Фильтр: " + mode + " разрешил SELL";
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
                ("SCALP".equals(mode) ? "\nSCALP micro M1: " + executionSignal : "") +
                "\nATR " + entryLabel + ": " + fmt(atr);

        int htfScore = (sHigher2 != 0 && sHigher2 == sHigher1) ? 20 : (sHigher2 == 0 || sHigher1 == 0 ? 11 : 3);
        int entryScore = sEntry == 0 ? 6 : 18;
        int fastScore = (sEntry != 0 && sFast == sEntry) ? 15 : (sFast == 0 ? 8 : 3);
        int structureScorePart = structure == 0 ? 5 : 15;
        int breakoutScorePart = Math.abs(breakout) >= 2 ? 20 : (Math.abs(breakout) == 1 ? 14 : 4);
        String components = "HTF " + htfScore + "/20 · Entry " + entryScore + "/20 · Fast " + fastScore + "/15 · Structure " + structureScorePart + "/15 · Breakout " + breakoutScorePart + "/20";

        ArrayList<String> whyParts = new ArrayList<>();
        if (sHigher1 != 0 && sHigher2 != 0 && sHigher1 != sHigher2) whyParts.add("старшие ТФ расходятся");
        if (sEntry == 0) whyParts.add(entryLabel + " без направления");
        if (sEntry != 0 && sFast != 0 && sFast != sEntry) whyParts.add(fastLabel + " против входа");
        if (structure == 0) whyParts.add("структура не подтверждена");
        if (breakout == 0) whyParts.add("нет подтверждённого пробоя");
        String why;
        if ("WAIT".equals(signal)) {
            why = whyParts.isEmpty() ? "условия режима " + mode + " не совпали одновременно" : android.text.TextUtils.join("; ", whyParts);
        } else {
            why = signal + " открыт: направление ТФ согласовано; структура/фильтр разрешили вход; качество " + quality + "/100";
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
        if (whyWaitText != null) whyWaitText.setText(("WAIT".equals(a.signal) ? "ПОЧЕМУ WAIT: " : "ПОЧЕМУ ВХОД: ") + a.why);
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
}
