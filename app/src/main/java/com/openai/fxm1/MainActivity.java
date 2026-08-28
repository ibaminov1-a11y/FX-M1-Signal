package com.openai.fxm1;

import android.app.Activity;
import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.drawable.GradientDrawable;
import android.graphics.Color;
import android.media.AudioManager;
import android.media.AudioAttributes;
import android.media.ToneGenerator;
import android.media.MediaPlayer;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.util.Base64;
import android.os.Handler;
import android.os.Looper;
import android.widget.*;
import android.view.View;

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
    private TextView statusText, signalText, confidenceText, signalAgeText, levelsText, contextText;
    private Button analyzeButton, saveKeyButton, serverCheckButton, emergencyStopButton, closeAllButton;
    private Button jarvisTalkButton, jarvisSendButton, backgroundModeButton;
    private EditText serverUrlInput, jarvisInput;
    private TextView serverStatusText, accountText, positionsText, journalText, priceCompareText;
    private TextView jarvisStatusText, jarvisChatText, backgroundStatusText;
    private Switch autoTradingSwitch;
    private Spinner riskSpinner, maxPositionsSpinner, maxDriftSpinner;
    private View topCard, tfCard, modeCard, signalCard, jarvisCard, backgroundCard, tradingCard, metricsCard, riskCard, journalCard;

    private SpeechRecognizer jarvisSpeechRecognizer;
    private TextToSpeech jarvisTts;
    private MediaPlayer jarvisPlayer;
    private boolean jarvisListening = false;
    private boolean jarvisStartAfterPermission = false;
    private boolean jarvisStartupAfterPermission = false;
    private boolean jarvisTtsReady = false;
    private boolean jarvisAutoListenAfterSpeech = false;
    private boolean jarvisStartupDone = false;
    private String pendingJarvisSpeech = null;
    private final String jarvisSessionId = UUID.randomUUID().toString();

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

    private boolean monitoring = false;
    private boolean isAnalyzing = false;
    private boolean serverConnected = false;
    private boolean mt5Connected = false;
    private boolean demoAccount = false;
    private boolean suppressAutoSwitch = false;

    private double lastApiPrice = Double.NaN;
    private double lastMt5Bid = Double.NaN;
    private double lastMt5Ask = Double.NaN;

    private final Map<String, String> lastSentSignal = new HashMap<>();

    private final Map<String, CacheItem> cache = new HashMap<>();
    private final Map<String, String> lastAlertSignal = new HashMap<>();

    private final String[] symbols = {
            "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
            "EUR/JPY", "GBP/JPY", "EUR/GBP", "EUR/CHF", "AUD/JPY", "CAD/JPY", "CHF/JPY",
            "GBP/CHF", "EUR/AUD", "GBP/AUD", "AUD/NZD", "NZD/JPY", "XAU/USD"
    };

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
        statusText = findViewById(R.id.statusText);
        signalText = findViewById(R.id.signalText);
        confidenceText = findViewById(R.id.confidenceText);
        signalAgeText = findViewById(R.id.signalAgeText);
        levelsText = findViewById(R.id.levelsText);
        contextText = findViewById(R.id.contextText);
        analyzeButton = findViewById(R.id.analyzeButton);
        saveKeyButton = findViewById(R.id.saveKeyButton);
        serverUrlInput = findViewById(R.id.serverUrlInput);
        serverCheckButton = findViewById(R.id.serverCheckButton);
        serverStatusText = findViewById(R.id.serverStatusText);
        accountText = findViewById(R.id.accountText);
        positionsText = findViewById(R.id.positionsText);
        journalText = findViewById(R.id.journalText);
        priceCompareText = findViewById(R.id.priceCompareText);
        autoTradingSwitch = findViewById(R.id.autoTradingSwitch);
        riskSpinner = findViewById(R.id.riskSpinner);
        maxPositionsSpinner = findViewById(R.id.maxPositionsSpinner);
        maxDriftSpinner = findViewById(R.id.maxDriftSpinner);
        emergencyStopButton = findViewById(R.id.emergencyStopButton);
        closeAllButton = findViewById(R.id.closeAllButton);
        jarvisTalkButton = findViewById(R.id.jarvisTalkButton);
        jarvisSendButton = findViewById(R.id.jarvisSendButton);
        jarvisInput = findViewById(R.id.jarvisInput);
        jarvisStatusText = findViewById(R.id.jarvisStatusText);
        jarvisChatText = findViewById(R.id.jarvisChatText);
        backgroundModeButton = findViewById(R.id.backgroundModeButton);
        backgroundStatusText = findViewById(R.id.backgroundStatusText);

        topCard = findViewById(R.id.topCard);
        tfCard = findViewById(R.id.tfCard);
        modeCard = findViewById(R.id.modeCard);
        signalCard = findViewById(R.id.signalCard);
        jarvisCard = findViewById(R.id.jarvisCard);
        backgroundCard = findViewById(R.id.backgroundCard);
        tradingCard = findViewById(R.id.tradingCard);
        metricsCard = findViewById(R.id.metricsCard);
        riskCard = findViewById(R.id.riskCard);
        journalCard = findViewById(R.id.journalCard);

        applyDarkVioletTheme();

        ArrayAdapter<String> adapter = darkSpinnerAdapter(symbols);
        symbolSpinner.setAdapter(adapter);

        ArrayAdapter<String> timeframeAdapter = darkSpinnerAdapter(
                new String[]{"M1", "M5", "M15", "H1"}
        );
        entryTimeframeSpinner.setAdapter(timeframeAdapter);

        ArrayAdapter<String> modeAdapter = darkSpinnerAdapter(
                new String[]{"CONSERVATIVE", "NORMAL", "AGGRESSIVE"}
        );
        signalModeSpinner.setAdapter(modeAdapter);

        SharedPreferences prefs = getSharedPreferences("fxm1", MODE_PRIVATE);
        symbolSpinner.setSelection(prefs.getInt("symbol_pos", 0));
        entryTimeframeSpinner.setSelection(prefs.getInt("entry_tf_pos", 1));
        signalModeSpinner.setSelection(prefs.getInt("signal_mode_pos", 1));
        apiKeyInput.setText(prefs.getString("apikey", ""));
        serverUrlInput.setText(prefs.getString("server_url", ""));

        ArrayAdapter<String> riskAdapter = darkSpinnerAdapter(
                new String[]{"0.25%", "0.50%", "1.00%"}
        );
        riskSpinner.setAdapter(riskAdapter);
        riskSpinner.setSelection(prefs.getInt("risk_pos", 1));

        ArrayAdapter<String> maxPosAdapter = darkSpinnerAdapter(
                new String[]{"1", "2", "3"}
        );
        maxPositionsSpinner.setAdapter(maxPosAdapter);
        maxPositionsSpinner.setSelection(prefs.getInt("maxpos_pos", 0));

        ArrayAdapter<String> driftAdapter = darkSpinnerAdapter(
                new String[]{"0.03%", "0.05%", "0.10%", "0.20%"}
        );
        maxDriftSpinner.setAdapter(driftAdapter);
        maxDriftSpinner.setSelection(prefs.getInt("maxdrift_pos", 1));

        analyzeButton.setText("ЗАПУСТИТЬ МОНИТОРИНГ");
        setTradingControlsOffline();

        saveKeyButton.setOnClickListener(v -> {
            String key = apiKeyInput.getText().toString().trim();
            prefs.edit().putString("apikey", key).apply();
            if (monitoring) {
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

        backgroundModeButton.setOnClickListener(v -> {
            if (monitoring) {
                stopMonitoring();
            } else {
                startMonitoring();
            }
        });

        serverCheckButton.setOnClickListener(v -> checkServer());

        riskSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                prefs.edit().putInt("risk_pos", position).apply();
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

        maxPositionsSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                prefs.edit().putInt("maxpos_pos", position).apply();
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });


        symbolSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                prefs.edit().putInt("symbol_pos", position).apply();
                lastSentSignal.clear();
                lastAlertSignal.clear();

                if (monitoring) {
                    sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
                }
            }

            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

        entryTimeframeSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                prefs.edit().putInt("entry_tf_pos", position).apply();
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
                prefs.edit().putInt("signal_mode_pos", position).apply();
                lastSentSignal.clear();
                if (monitoring) {
                    sendBackgroundCommand(MonitoringService.ACTION_REFRESH);
                }
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

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
                    forceAutoOff("AUTO заблокирован: V5.5 разрешает только DEMO.");
                    Toast.makeText(this, "V5.5 разрешает автоторговлю только на DEMO", Toast.LENGTH_LONG).show();
                    return;
                }
                prefs.edit().putBoolean("auto_trading", true).apply();
                addJournal("AUTO TRADING включён · DEMO");
            } else {
                prefs.edit().putBoolean("auto_trading", false).apply();
                addJournal("AUTO TRADING выключен");
            }
        });

        emergencyStopButton.setOnClickListener(v -> {
            forceAutoOff("EMERGENCY STOP: отправка новых сигналов остановлена.");
            sendBackgroundCommand(MonitoringService.ACTION_EMERGENCY);
            monitoring = false;
            analyzeButton.setText("ЗАПУСТИТЬ МОНИТОРИНГ");
            if (backgroundModeButton != null) backgroundModeButton.setText("▶  ВКЛЮЧИТЬ ФОН");
            if (backgroundStatusText != null) {
                backgroundStatusText.setText("○  ФОН: ВЫКЛЮЧЕН · EMERGENCY STOP");
                backgroundStatusText.setTextColor(C_RED);
            }
            addJournal("EMERGENCY STOP на телефоне");
            Toast.makeText(this, "STOP: фоновый мониторинг и AUTO выключены", Toast.LENGTH_LONG).show();
        });

        closeAllButton.setOnClickListener(v -> sendCloseAll());

        initJarvisVoice();

        jarvisTalkButton.setOnClickListener(v -> startJarvisListening());
        jarvisSendButton.setOnClickListener(v -> {
            String message = jarvisInput.getText().toString().trim();
            if (!message.isEmpty()) {
                jarvisInput.setText("");
                sendJarvisMessage(message);
            }
        });

        jarvisInput.setOnEditorActionListener((v, actionId, event) -> {
            String message = jarvisInput.getText().toString().trim();
            if (!message.isEmpty()) {
                jarvisInput.setText("");
                sendJarvisMessage(message);
                return true;
            }
            return false;
        });

        handleJarvisIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleJarvisIntent(intent);
    }

    private void handleJarvisIntent(Intent intent) {
        if (intent != null && intent.getBooleanExtra("open_jarvis", false)) {
            intent.removeExtra("open_jarvis");
            new Handler(Looper.getMainLooper()).postDelayed(this::startJarvisListening, 350L);
        }
    }

    private void initJarvisVoice() {
        jarvisStatusText.setText("JARVIS: запускаю голосовую систему…");
        jarvisChatText.setText("JARVIS: Инициализация голосового ассистента.");

        jarvisTts = new TextToSpeech(this, status -> {
            if (status != TextToSpeech.SUCCESS) {
                jarvisStatusText.setText("JARVIS: системный голос TTS недоступен");
                beginJarvisAutonomousStartup();
                return;
            }

            int languageResult = jarvisTts.setLanguage(new Locale("ru", "RU"));
            jarvisTts.setPitch(0.88f);
            jarvisTts.setSpeechRate(0.96f);

            try {
                jarvisTts.setAudioAttributes(
                        new AudioAttributes.Builder()
                                .setUsage(AudioAttributes.USAGE_ASSISTANT)
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .build()
                );
            } catch (Exception ignored) { }

            jarvisTts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override public void onStart(String utteranceId) { }

                @Override public void onDone(String utteranceId) {
                    runOnUiThread(() -> {
                        if (jarvisAutoListenAfterSpeech && hasMicrophonePermission()) {
                            jarvisAutoListenAfterSpeech = false;
                            new Handler(Looper.getMainLooper()).postDelayed(
                                    MainActivity.this::startJarvisListening,
                                    250L
                            );
                        }
                    });
                }

                @Override public void onError(String utteranceId) {
                    runOnUiThread(() -> jarvisStatusText.setText(
                            "JARVIS: ошибка системного голосового движка"
                    ));
                }
            });

            jarvisTtsReady = true;

            if (languageResult != TextToSpeech.LANG_MISSING_DATA &&
                    languageResult != TextToSpeech.LANG_NOT_SUPPORTED) {
                jarvisStatusText.setText("JARVIS: VOICE READY");
            } else {
                jarvisStatusText.setText(
                        "JARVIS: VOICE READY · русский голос ограничен системным TTS"
                );
            }

            if (pendingJarvisSpeech != null && jarvisTtsReady) {
                String queued = pendingJarvisSpeech;
                pendingJarvisSpeech = null;
                speakJarvisLocal(queued);
            }

            beginJarvisAutonomousStartup();
        });
    }

    private boolean hasMicrophonePermission() {
        return Build.VERSION.SDK_INT < 23 ||
                checkSelfPermission(Manifest.permission.RECORD_AUDIO) ==
                        PackageManager.PERMISSION_GRANTED;
    }

    private void beginJarvisAutonomousStartup() {
        if (jarvisStartupDone) return;

        if (!hasMicrophonePermission()) {
            jarvisStartupAfterPermission = true;
            jarvisStatusText.setText("JARVIS: нужен доступ к микрофону");
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 5002);
            return;
        }

        runJarvisWelcomeAndListen();
    }

    private void runJarvisWelcomeAndListen() {
        if (jarvisStartupDone) return;
        jarvisStartupDone = true;

        SharedPreferences p = getSharedPreferences("fxm1", MODE_PRIVATE);
        String savedKey = p.getString("apikey", "").trim();

        // Автономный запуск фона: только если API key уже сохранён.
        if (!savedKey.isEmpty() && !p.getBoolean("bg_running", false)) {
            startMonitoring();
        }

        boolean bg = p.getBoolean("bg_running", false) || monitoring;
        String symbol = String.valueOf(symbolSpinner.getSelectedItem());
        String tf = selectedEntryTimeframe();
        String signal = p.getString("bg_signal", signalText.getText().toString());
        if (signal == null || signal.trim().isEmpty()) signal = "WAIT";

        int hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY);
        String greeting;
        if (hour < 6) greeting = "Доброй ночи.";
        else if (hour < 12) greeting = "Доброе утро.";
        else if (hour < 18) greeting = "Добрый день.";
        else greeting = "Добрый вечер.";

        String report = greeting +
                " JARVIS на связи. " +
                "Текущий инструмент " + symbol +
                ", таймфрейм " + tf +
                ", последний сигнал " + signal + ". " +
                (bg
                        ? "Фоновый мониторинг активен; приложение можно свернуть. "
                        : (savedKey.isEmpty()
                            ? "Фоновый мониторинг пока не запущен: сначала нужен Twelve Data API key. "
                            : "Фоновый мониторинг сейчас остановлен. ")) +
                (serverConnected && mt5Connected
                        ? "Сервер и MT5 подключены. "
                        : "Торговый сервер или MT5 пока не подключены. ") +
                "Что будем делать?";

        appendJarvisLine("JARVIS", report);
        jarvisStatusText.setText("JARVIS: говорю…");
        jarvisAutoListenAfterSpeech = true;
        speakJarvisLocal(report);
    }

    private void startJarvisListening() {
        if (Build.VERSION.SDK_INT >= 23 &&
                checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            jarvisStartAfterPermission = true;
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 5002);
            return;
        }

        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            jarvisStatusText.setText("JARVIS: распознавание речи недоступно на устройстве");
            return;
        }

        if (jarvisSpeechRecognizer == null) {
            jarvisSpeechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);
            jarvisSpeechRecognizer.setRecognitionListener(new RecognitionListener() {
                @Override public void onReadyForSpeech(Bundle params) {
                    jarvisListening = true;
                    jarvisTalkButton.setText("СЛУШАЮ…");
                    jarvisStatusText.setText("JARVIS: слушаю.");
                }

                @Override public void onBeginningOfSpeech() { }
                @Override public void onRmsChanged(float rmsdB) { }
                @Override public void onBufferReceived(byte[] buffer) { }
                @Override public void onEndOfSpeech() {
                    jarvisListening = false;
                    jarvisTalkButton.setText("🎙 ГОВОРИТЬ");
                    jarvisStatusText.setText("JARVIS: думаю…");
                }

                @Override public void onError(int error) {
                    jarvisListening = false;
                    jarvisTalkButton.setText("🎙 ГОВОРИТЬ");
                    jarvisStatusText.setText("JARVIS: не расслышал. Попробуйте ещё раз.");
                }

                @Override public void onResults(Bundle results) {
                    jarvisListening = false;
                    jarvisTalkButton.setText("🎙 ГОВОРИТЬ");

                    ArrayList<String> matches =
                            results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);

                    if (matches == null || matches.isEmpty()) {
                        jarvisStatusText.setText("JARVIS: фраза не распознана");
                        return;
                    }

                    String message = matches.get(0).trim();

                    // Some phones ignore ru-RU and return English recognition.
                    // Do not silently send a wrong English phrase to JARVIS.
                    int cyr = 0;
                    int latin = 0;
                    for (int i = 0; i < message.length(); i++) {
                        char ch = message.charAt(i);
                        if ((ch >= 'А' && ch <= 'я') || ch == 'Ё' || ch == 'ё') cyr++;
                        if ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z')) latin++;
                    }
                    if (latin >= 3 && cyr == 0) {
                        jarvisStatusText.setText(
                                "JARVIS: телефон распознал речь как английскую. Нужен русский пакет распознавания или серверный STT."
                        );
                        appendJarvisLine(
                                "JARVIS",
                                "Системный распознаватель телефона вернул английский текст: «" +
                                message +
                                "». Я его не отправляю как русскую команду."
                        );
                        return;
                    }

                    jarvisInput.setText("");
                    sendJarvisMessage(message);
                }

                @Override public void onPartialResults(Bundle partialResults) { }
                @Override public void onEvent(int eventType, Bundle params) { }
            });
        }

        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU");
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "ru-RU");
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
        intent.putExtra(RecognizerIntent.EXTRA_PROMPT, "Говорите");

        try {
            jarvisSpeechRecognizer.startListening(intent);
        } catch (Exception e) {
            jarvisStatusText.setText("JARVIS: микрофон недоступен. Проверьте разрешение «Микрофон» в настройках приложения.");
        }
    }

    private void sendJarvisMessage(String message) {
        appendJarvisLine("ВЫ", message);

        String localCommandReply = handleSafeLocalJarvisCommand(message);
        if (localCommandReply != null) {
            deliverJarvisReply(localCommandReply, null);
            return;
        }

        final String base = normalizeServerUrl(serverUrlInput.getText().toString());
        if (base.isEmpty()) {
            deliverJarvisReply(localJarvisReply(message), null);
            return;
        }

        jarvisStatusText.setText("JARVIS: думаю…");

        final JSONObject payload = new JSONObject();
        try {
            payload.put("session_id", jarvisSessionId);
            payload.put("message", message);

            JSONObject context = new JSONObject();
            context.put("symbol", String.valueOf(symbolSpinner.getSelectedItem()));
            context.put("entry_timeframe", selectedEntryTimeframe());
            context.put("signal_mode", selectedSignalMode());
            context.put("signal", signalText.getText().toString());
            context.put("quality", confidenceText.getText().toString());
            context.put("levels", levelsText.getText().toString());
            context.put("market_context", contextText.getText().toString());
            context.put("monitor_status", statusText.getText().toString());
            context.put("server_connected", serverConnected);
            context.put("mt5_connected", mt5Connected);
            context.put("account", accountText.getText().toString());
            context.put("positions", positionsText.getText().toString());
            context.put("auto_trading", autoTradingSwitch.isChecked());
            context.put("risk", String.valueOf(riskSpinner.getSelectedItem()));
            context.put("max_positions", String.valueOf(maxPositionsSpinner.getSelectedItem()));
            payload.put("context", context);
            payload.put("voice", true);
        } catch (Exception e) {
            deliverJarvisReply("У меня возникла небольшая проблема с контекстом. Редкий случай, но технически возможный.", null);
            return;
        }

        executor.execute(() -> {
            try {
                JSONObject response = httpJson("POST", base + "/assistant", payload);
                boolean ok = response.optBoolean("ok", false);
                if (!ok) throw new Exception(response.optString("error", "AI server error"));

                String reply = response.optString("reply", "").trim();
                String audioB64 = response.optString("audio_base64", null);

                if (reply.isEmpty()) reply = "Я получил ответ, но, что несколько неловко, без текста.";

                final String finalReply = reply;
                final String finalAudio = audioB64;

                runOnUiThread(() -> deliverJarvisReply(finalReply, finalAudio));

            } catch (Exception e) {
                runOnUiThread(() -> {
                    String fallback = localJarvisReply(message);
                    appendJarvisLine(
                            "JARVIS",
                            fallback + "\n[AI-сервер недоступен: " + safeMessage(e) + "]"
                    );
                    jarvisStatusText.setText("JARVIS: LOCAL MODE");
                    speakJarvisLocal(fallback);
                });
            }
        });
    }

    private String handleSafeLocalJarvisCommand(String raw) {
        String q = raw.toLowerCase(new Locale("ru", "RU"));

        if (q.contains("останови мониторинг") || q.contains("остановить мониторинг")) {
            stopMonitoring();
            return "Мониторинг остановлен. Рынок переживёт наше отсутствие, полагаю.";
        }

        if (q.contains("запусти мониторинг") || q.contains("запустить мониторинг")) {
            startMonitoring();
            return monitoring
                    ? "Мониторинг запущен. Наблюдение продолжается."
                    : "Мониторинг не запущен. Проверьте API key.";
        }

        if (q.contains("emergency") || q.contains("аварийн") || q.contains("экстренн")) {
            forceAutoOff("JARVIS: EMERGENCY STOP");
            sendBackgroundCommand(MonitoringService.ACTION_EMERGENCY);
            monitoring = false;
            analyzeButton.setText("ЗАПУСТИТЬ МОНИТОРИНГ");
            if (backgroundModeButton != null) backgroundModeButton.setText("▶  ВКЛЮЧИТЬ ФОН");
            if (backgroundStatusText != null) {
                backgroundStatusText.setText("○  ФОН: ВЫКЛЮЧЕН · EMERGENCY STOP");
                backgroundStatusText.setTextColor(C_RED);
            }
            return "Emergency Stop выполнен. Мониторинг и автоматическая торговля отключены.";
        }

        return null;
    }

    private String localJarvisReply(String raw) {
        String q = raw.toLowerCase(new Locale("ru", "RU"));
        String signal = signalText.getText().toString().trim();
        String symbol = String.valueOf(symbolSpinner.getSelectedItem());
        String tf = selectedEntryTimeframe();

        if (q.contains("статус") || q.contains("что сейчас") || q.contains("что по рынку")) {
            return "По " + symbol + " на " + tf + " сейчас " + signal +
                    ". " + confidenceText.getText().toString() +
                    ". " + ("WAIT".equals(signal)
                    ? "Оснований торопиться нет. Рынок, к счастью, не берёт плату за терпение."
                    : "Сетап сформирован; детали уже на экране.");
        }

        if (q.contains("почему") && q.contains("wait")) {
            return "Причина WAIT указана в текущем контексте: " +
                    contextText.getText().toString() +
                    ". Входить просто из скуки я бы не рекомендовал.";
        }

        if (q.contains("позици")) {
            return positionsText.getText().toString() +
                    ". Для точных данных нужен подключённый MT5.";
        }

        if (q.contains("кто ты") || q.contains("что ты умеешь")) {
            return "Я голосовой интерфейс FX M1 Bot. Локально вижу состояние приложения, а после подключения AI-сервера смогу рассуждать по контексту, помнить разговор и работать с инструментами бота.";
        }

        return "Сейчас я работаю в локальном режиме. Подключите AI-сервер, и я смогу ответить на этот вопрос с полноценным рассуждением. До тех пор вынужден изображать скромность.";
    }

    private void deliverJarvisReply(String reply, String audioBase64) {
        appendJarvisLine("JARVIS", reply);
        jarvisStatusText.setText("JARVIS: ONLINE");

        if (audioBase64 != null && !audioBase64.trim().isEmpty()) {
            playJarvisAudio(audioBase64, reply);
        } else {
            speakJarvisLocal(reply);
        }
    }

    private void appendJarvisLine(String who, String text) {
        String current = jarvisChatText.getText().toString().trim();
        String line = who + ": " + text;

        if (current.isEmpty()) {
            jarvisChatText.setText(line);
            return;
        }

        String combined = current + "\n\n" + line;
        if (combined.length() > 5000) {
            combined = combined.substring(combined.length() - 5000);
        }
        jarvisChatText.setText(combined);
    }

    private void speakJarvisLocal(String text) {
        if (text == null || text.trim().isEmpty()) return;

        String spoken = text.replaceAll("\\[[^\\]]*\\]", "").trim();

        if (jarvisTts == null || !jarvisTtsReady) {
            pendingJarvisSpeech = spoken;
            return;
        }

        jarvisStatusText.setText("JARVIS: говорю…");
        jarvisAutoListenAfterSpeech = hasMicrophonePermission();

        int result = jarvisTts.speak(
                spoken,
                TextToSpeech.QUEUE_FLUSH,
                null,
                "jarvis_reply_" + System.currentTimeMillis()
        );

        if (result == TextToSpeech.ERROR) {
            jarvisStatusText.setText(
                    "JARVIS: системный TTS не смог воспроизвести голос"
            );
        }
    }

    private void playJarvisAudio(String audioBase64, String fallbackText) {
        try {
            if (jarvisPlayer != null) {
                try { jarvisPlayer.stop(); } catch (Exception ignored) { }
                jarvisPlayer.release();
                jarvisPlayer = null;
            }

            byte[] audio = Base64.decode(audioBase64, Base64.DEFAULT);
            File file = new File(getCacheDir(), "jarvis_reply.mp3");

            FileOutputStream fos = new FileOutputStream(file);
            fos.write(audio);
            fos.flush();
            fos.close();

            jarvisPlayer = new MediaPlayer();
            jarvisPlayer.setDataSource(file.getAbsolutePath());
            jarvisPlayer.setOnPreparedListener(MediaPlayer::start);
            jarvisPlayer.setOnCompletionListener(mp -> {
                mp.release();
                jarvisPlayer = null;
                file.delete();

                if (hasMicrophonePermission()) {
                    new Handler(Looper.getMainLooper()).postDelayed(
                            MainActivity.this::startJarvisListening,
                            250L
                    );
                }
            });
            jarvisPlayer.setOnErrorListener((mp, what, extra) -> {
                try { mp.release(); } catch (Exception ignored) { }
                jarvisPlayer = null;
                file.delete();
                speakJarvisLocal(fallbackText);
                return true;
            });
            jarvisPlayer.prepareAsync();

        } catch (Exception e) {
            speakJarvisLocal(fallbackText);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);

        if (requestCode == 5002) {
            boolean granted =
                    grantResults.length > 0 &&
                    grantResults[0] == PackageManager.PERMISSION_GRANTED;

            if (granted) {
                jarvisStatusText.setText("JARVIS: микрофон подключён");

                if (jarvisStartupAfterPermission) {
                    jarvisStartupAfterPermission = false;
                    jarvisStartAfterPermission = false;
                    runJarvisWelcomeAndListen();
                } else if (jarvisStartAfterPermission) {
                    jarvisStartAfterPermission = false;
                    startJarvisListening();
                }
            } else {
                jarvisStartAfterPermission = false;
                jarvisStartupAfterPermission = false;
                jarvisStatusText.setText(
                        "JARVIS: доступ к микрофону запрещён. Разрешите «Микрофон» в настройках приложения."
                );

                String warning =
                        "Голосовой ввод отключён, потому что Android не дал доступ к микрофону. " +
                        "Текстовый диалог остаётся доступен.";
                appendJarvisLine("JARVIS", warning);
                jarvisAutoListenAfterSpeech = false;
                speakJarvisLocal(warning);
            }
        }
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

        View root = findViewById(R.id.rootLayout);
        if (root != null) root.setBackgroundColor(C_BG);

        styleCard(topCard, C_CARD);
        styleCard(tfCard, C_CARD_2);
        styleCard(modeCard, C_CARD_2);
        styleCard(signalCard, C_CARD);
        styleCard(jarvisCard, C_CARD_2);
        styleCard(backgroundCard, C_CARD_2);
        styleCard(tradingCard, C_CARD);
        styleCard(metricsCard, C_CARD);
        styleCard(riskCard, C_CARD);
        styleCard(journalCard, C_CARD);

        stylePrimaryButton(saveKeyButton);
        stylePrimaryButton(analyzeButton);
        stylePrimaryButton(jarvisTalkButton);
        stylePrimaryButton(backgroundModeButton);
        styleOutlineButton(jarvisSendButton, C_PURPLE);
        styleOutlineButton(serverCheckButton, C_PURPLE);
        styleOutlineButton(closeAllButton, C_PURPLE);
        styleOutlineButton(emergencyStopButton, C_RED);

        styleInput(apiKeyInput);
        styleInput(serverUrlInput);
        styleInput(jarvisInput);

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
        jarvisStatusText.setTextColor(C_GREEN);
        jarvisChatText.setTextColor(C_TEXT);
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
        input.setHintTextColor(Color.rgb(126, 120, 151));
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
        accountText.setText("Счёт: —\nБаланс: —\nEquity: —");
        positionsText.setText("Открытые позиции: —\nТекущий P/L: —");
        lastMt5Bid = Double.NaN;
        lastMt5Ask = Double.NaN;
        updatePriceComparison();
        closeAllButton.setEnabled(false);
        forceAutoOff(null);
    }

    private void forceAutoOff(String journalMessage) {
        suppressAutoSwitch = true;
        autoTradingSwitch.setChecked(false);
        suppressAutoSwitch = false;
        getSharedPreferences("fxm1", MODE_PRIVATE).edit().putBoolean("auto_trading", false).apply();
        if (journalMessage != null) addJournal(journalMessage);
    }

    private String normalizeServerUrl(String raw) {
        String u = raw == null ? "" : raw.trim();
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }

    private void checkServer() {
        final String base = normalizeServerUrl(serverUrlInput.getText().toString());
        if (base.isEmpty()) {
            Toast.makeText(this, "Адрес сервера пока пуст", Toast.LENGTH_SHORT).show();
            return;
        }
        if (!base.startsWith("http://") && !base.startsWith("https://")) {
            Toast.makeText(this, "Адрес должен начинаться с http:// или https://", Toast.LENGTH_LONG).show();
            return;
        }

        getSharedPreferences("fxm1", MODE_PRIVATE).edit().putString("server_url", base).apply();
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

                runOnUiThread(() -> {
                    serverCheckButton.setEnabled(true);
                    serverConnected = serverOk;
                    mt5Connected = mt5Ok;
                    demoAccount = "DEMO".equals(accountType);

                    serverStatusText.setText(
                            "SERVER: " + (serverOk ? "CONNECTED" : "ERROR") +
                            "   •   MT5: " + (mt5Ok ? "CONNECTED" : "OFFLINE")
                    );
                    serverStatusText.setTextColor(
                            serverOk && mt5Ok ? C_GREEN : C_RED
                    );

                    accountText.setText(
                            "Счёт: " + accountType +
                            "\nБаланс: " + money(balance, currency) +
                            "\nEquity: " + money(equity, currency)
                    );
                    positionsText.setText(
                            "Открытые позиции: " + positions +
                            "\nТекущий P/L: " + signedMoney(floating, currency)
                    );
                    closeAllButton.setEnabled(serverOk && mt5Ok && demoAccount && positions > 0);

                    if (!serverOk || !mt5Ok || !demoAccount) {
                        forceAutoOff(null);
                    }
                    addJournal(serverOk && mt5Ok
                            ? "Связь с MT5 установлена · " + accountType
                            : "Сервер ответил, MT5 пока не готов");

                    if (serverOk && mt5Ok) {
                        refreshMt5Quote((String) symbolSpinner.getSelectedItem());
                    }
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    serverCheckButton.setEnabled(true);
                    setTradingControlsOffline();
                    addJournal("Ошибка сервера: " + safeMessage(e));
                    Toast.makeText(this, "Сервер пока недоступен", Toast.LENGTH_SHORT).show();
                });
            }
        });
    }

    private void maybeSendSignalToServer(Analysis a) {
        if (!autoTradingSwitch.isChecked() || !serverConnected || !mt5Connected || !demoAccount) {
            return;
        }

        if ("WAIT".equals(a.signal)) {
            lastSentSignal.put(a.symbol, "WAIT");
            return;
        }

        String previous = lastSentSignal.get(a.symbol);
        if (a.signal.equals(previous)) return;

        lastSentSignal.put(a.symbol, a.signal);
        final String base = normalizeServerUrl(serverUrlInput.getText().toString());
        final String risk = (String) riskSpinner.getSelectedItem();
        final String maxPositions = (String) maxPositionsSpinner.getSelectedItem();

        executor.execute(() -> {
            try {
                JSONObject payload = new JSONObject();
                payload.put("symbol", a.symbol);
                payload.put("signal", a.signal);
                payload.put("quality", a.quality);
                payload.put("entry", a.entry);
                payload.put("sl", a.sl);
                payload.put("tp1", a.tp1);
                payload.put("tp2", a.tp2);
                payload.put("risk_pct", Double.parseDouble(risk.replace("%", "")));
                payload.put("max_positions", Integer.parseInt(maxPositions));
                payload.put("mode", "DEMO");
                payload.put("signal_mode", selectedSignalMode());
                payload.put("entry_timeframe", selectedEntryTimeframe());
                payload.put("api_entry", a.entry);
                payload.put("max_price_drift_pct", selectedMaxDriftPct());
                payload.put("execution_price_source", "MT5");

                JSONObject response = httpJson("POST", base + "/signal", payload);
                boolean accepted = response.optBoolean("accepted", false);
                String message = response.optString("message", accepted ? "Сигнал принят" : "Сигнал отклонён");

                runOnUiThread(() -> addJournal(
                        a.symbol + " " + a.signal + " → " + message
                ));
            } catch (Exception e) {
                runOnUiThread(() -> {
                    lastSentSignal.put(a.symbol, "WAIT");
                    addJournal("Не отправлен " + a.symbol + " " + a.signal + ": " + safeMessage(e));
                });
            }
        });
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

    private void startMonitoring() {
        String key = apiKeyInput.getText().toString().trim();

        if (key.isEmpty()) {
            Toast.makeText(
                    this,
                    "Сначала вставьте Twelve Data API key",
                    Toast.LENGTH_LONG
            ).show();
            return;
        }

        SharedPreferences prefs = getSharedPreferences("fxm1", MODE_PRIVATE);
        prefs.edit()
                .putString("apikey", key)
                .putInt("symbol_pos", symbolSpinner.getSelectedItemPosition())
                .putInt("entry_tf_pos", entryTimeframeSpinner.getSelectedItemPosition())
                .putInt("signal_mode_pos", signalModeSpinner.getSelectedItemPosition())
                .apply();

        requestNotificationPermissionIfNeeded();

        monitoring = true;
        analyzeButton.setText("ОСТАНОВИТЬ МОНИТОРИНГ");
        if (backgroundModeButton != null) backgroundModeButton.setText("■  ОСТАНОВИТЬ ФОН");
        if (backgroundStatusText != null) {
            backgroundStatusText.setText("●  ФОН: АКТИВЕН · можно свернуть приложение");
            backgroundStatusText.setTextColor(C_GREEN);
        }
        statusText.setText(
                "Мониторинг запущен · " +
                selectedEntryTimeframe() +
                " · можно свернуть приложение."
        );

        Intent intent = new Intent(this, MonitoringService.class);
        intent.setAction(MonitoringService.ACTION_START);
        startForegroundService(intent);
    }

    private void stopMonitoring() {
        monitoring = false;
        sendBackgroundCommand(MonitoringService.ACTION_STOP);
        analyzeButton.setText("ЗАПУСТИТЬ МОНИТОРИНГ");
        if (backgroundModeButton != null) backgroundModeButton.setText("▶  ВКЛЮЧИТЬ ФОН");
        if (backgroundStatusText != null) {
            backgroundStatusText.setText("○  ФОН: ВЫКЛЮЧЕН");
            backgroundStatusText.setTextColor(C_MUTED);
        }
        statusText.setText("Мониторинг остановлен.");
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
        boolean running = p.getBoolean("bg_running", false);

        if (running != monitoring) {
            monitoring = running;
            analyzeButton.setText(
                    running
                            ? "ОСТАНОВИТЬ МОНИТОРИНГ"
                            : "ЗАПУСТИТЬ МОНИТОРИНГ"
            );
            if (backgroundModeButton != null) {
                backgroundModeButton.setText(
                        running ? "■  ОСТАНОВИТЬ ФОН" : "▶  ВКЛЮЧИТЬ ФОН"
                );
            }
            if (backgroundStatusText != null) {
                backgroundStatusText.setText(
                        running
                                ? "●  ФОН: АКТИВЕН · можно свернуть приложение"
                                : "○  ФОН: ВЫКЛЮЧЕН"
                );
                backgroundStatusText.setTextColor(running ? C_GREEN : C_MUTED);
            }
        }

        if (!running) return;

        String symbol = p.getString("bg_symbol", "");
        String tf = p.getString("bg_tf", "");
        String signal = p.getString("bg_signal", "WAIT");
        String status = p.getString("bg_status", "Фоновый мониторинг работает");
        String context = p.getString("bg_context", "");
        int quality = p.getInt("bg_quality", -1);
        long signalSinceMs = p.getLong("bg_signal_since_ms", 0L);
        long lastUpdateMs = p.getLong("bg_last_update_ms", 0L);

        // Never present a signal from another timeframe/symbol as current.
        String selectedSymbol = (String) symbolSpinner.getSelectedItem();
        String selectedTf = selectedEntryTimeframe();
        if (!symbol.equals(selectedSymbol) || !tf.equals(selectedTf)) {
            signal = "WAIT";
            quality = -1;
            signalSinceMs = 0L;
            context = "Параметры изменены. Жду новый анализ для " +
                    selectedSymbol + " · " + selectedTf + ".";
            status = "Обновляю выбранный инструмент/таймфрейм…";
        }
        int fresh = p.getInt("bg_api_count", 0);
        int cached = p.getInt("bg_cache_count", 0);
        double entry = Double.longBitsToDouble(p.getLong("bg_entry_bits", Double.doubleToLongBits(Double.NaN)));
        double sl = Double.longBitsToDouble(p.getLong("bg_sl_bits", Double.doubleToLongBits(Double.NaN)));
        double tp1 = Double.longBitsToDouble(p.getLong("bg_tp1_bits", Double.doubleToLongBits(Double.NaN)));
        double tp2 = Double.longBitsToDouble(p.getLong("bg_tp2_bits", Double.doubleToLongBits(Double.NaN)));

        statusText.setText(
                symbol + " · " + tf +
                " · MON · API " + fresh +
                " · кэш " + cached +
                "\n" + status
        );

        signalText.setText(signal);
        if ("BUY".equals(signal)) {
            signalText.setTextColor(C_GREEN);
        } else if ("SELL".equals(signal)) {
            signalText.setTextColor(C_RED);
        } else {
            signalText.setTextColor(C_PURPLE);
        }

        updateSignalAgeText(signal, signalSinceMs, lastUpdateMs);

        if (quality >= 0) {
            confidenceText.setText("Качество сетапа: " + quality + "/100");
        } else {
            confidenceText.setText("Качество сетапа: —");
        }

        if (!Double.isNaN(entry)) {
            if ("WAIT".equals(signal)) {
                levelsText.setText(
                        "Entry: " + fmt(entry) +
                        "\nSL: —" +
                        "\nTP1: —" +
                        "\nTP2: —"
                );
            } else {
                levelsText.setText(
                        "Entry: " + fmt(entry) +
                        "\nSL: " + fmt(sl) +
                        "\nTP1: " + fmt(tp1) + "  (1.5R)" +
                        "\nTP2: " + fmt(tp2) + "  (2.0R)"
                );
            }
            lastApiPrice = entry;
            updatePriceComparison();
        }

        if (!context.isEmpty()) {
            contextText.setText(context);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        serviceUiHandler.removeCallbacks(serviceUiRunnable);
        serviceUiHandler.post(serviceUiRunnable);
    }

    @Override
    protected void onPause() {
        serviceUiHandler.removeCallbacks(serviceUiRunnable);
        super.onPause();
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

                } else {
                    fast = getSeries(symbol, "15min", key, 120, CACHE_M15_MS);
                    entry = getSeries(symbol, "1h", key, 120, CACHE_H1_MS);
                    higher1 = getSeries(symbol, "4h", key, 100, CACHE_H4_MS);
                    higher2 = getSeries(symbol, "1day", key, 100, CACHE_D1_MS);

                    fastLabel = "M15";
                    entryLabel = "H1";
                    higher1Label = "H4";
                    higher2Label = "D1";
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
                URLEncoder.encode(symbol, "UTF-8") +
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
        if ("M1".equals(tf)) return 20000L;
        if ("M5".equals(tf)) return 60000L;
        if ("M15".equals(tf)) return 180000L;
        return 300000L; // H1
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
                String url = base + "/quote?symbol=" + URLEncoder.encode(symbol, "UTF-8");
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

        int quality = setupQualityAdaptive(
                signal,
                sHigher2,
                sHigher1,
                sEntry,
                sFast,
                structure,
                breakout
        );

        double slDist = Math.max(
                atr * 1.8,
                minStopDistance(symbol)
        );

        double sl = 0;
        double tp1 = 0;
        double tp2 = 0;

        if ("BUY".equals(signal)) {
            sl = entry - slDist;
            tp1 = entry + slDist * 1.5;
            tp2 = entry + slDist * 2.0;
        } else if ("SELL".equals(signal)) {
            sl = entry + slDist;
            tp1 = entry - slDist * 1.5;
            tp2 = entry - slDist * 2.0;
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
                "\nATR " + entryLabel + ": " + fmt(atr);

        return new Analysis(
                symbol,
                signal,
                quality,
                entry,
                sl,
                tp1,
                tp2,
                context
        );
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

    private void updateSignalAgeText(String signal, long sinceMs, long updatedMs) {
        if (signalAgeText == null) return;

        if ("BUY".equals(signal) || "SELL".equals(signal)) {
            signalAgeText.setText(
                    "Открыт: " + formatClock(sinceMs) +
                    "  ·  прошло: " + formatElapsed(sinceMs) +
                    "\nОбновлено: " + formatClock(updatedMs)
            );
            signalAgeText.setTextColor(C_YELLOW);
        } else {
            signalAgeText.setText(
                    updatedMs > 0L
                            ? "Последнее обновление: " + formatClock(updatedMs) +
                              "  ·  " + formatElapsed(updatedMs) + " назад"
                            : "Сигнал ещё не открыт."
            );
            signalAgeText.setTextColor(C_MUTED);
        }
    }

    private void showAnalysis(Analysis a,
                              int freshRequests,
                              int cachedRequests) {

        statusText.setText(
                a.symbol +
                " · " + selectedEntryTimeframe() +
                " · AUTO " + selectedMonitorLabel() +
                " · API " + freshRequests +
                " · кэш " + cachedRequests
        );

        signalText.setText(a.signal);

        if ("BUY".equals(a.signal)) {
            signalText.setTextColor(C_GREEN);
        } else if ("SELL".equals(a.signal)) {
            signalText.setTextColor(C_RED);
        } else {
            signalText.setTextColor(C_PURPLE);
        }

        confidenceText.setText(
                "Качество сетапа: " +
                a.quality +
                "/100"
        );

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

        if (jarvisSpeechRecognizer != null) {
            try { jarvisSpeechRecognizer.destroy(); } catch (Exception ignored) { }
            jarvisSpeechRecognizer = null;
        }

        if (jarvisTts != null) {
            try { jarvisTts.stop(); } catch (Exception ignored) { }
            try { jarvisTts.shutdown(); } catch (Exception ignored) { }
            jarvisTts = null;
        }

        if (jarvisPlayer != null) {
            try { jarvisPlayer.stop(); } catch (Exception ignored) { }
            try { jarvisPlayer.release(); } catch (Exception ignored) { }
            jarvisPlayer = null;
        }

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
        final String context;
        final int quality;
        final double entry;
        final double sl;
        final double tp1;
        final double tp2;

        Analysis(String symbol,
                 String signal,
                 int quality,
                 double entry,
                 double sl,
                 double tp1,
                 double tp2,
                 String context) {

            this.symbol = symbol;
            this.signal = signal;
            this.quality = quality;
            this.entry = entry;
            this.sl = sl;
            this.tp1 = tp1;
            this.tp2 = tp2;
            this.context = context;
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
