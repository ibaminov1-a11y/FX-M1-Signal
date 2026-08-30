package com.openai.fxm1;

import android.app.*;
import android.content.*;
import android.graphics.BitmapFactory;
import android.content.pm.ServiceInfo;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.*;
import android.widget.RemoteViews;
import android.graphics.Color;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

public class MonitoringService extends Service {

    public static final String ACTION_START = "com.openai.fxm1.action.START_MONITORING";
    public static final String ACTION_STOP = "com.openai.fxm1.action.STOP_MONITORING";
    public static final String ACTION_EMERGENCY = "com.openai.fxm1.action.EMERGENCY_STOP";
    public static final String ACTION_EMERGENCY_CONFIRMED = "com.openai.fxm1.action.EMERGENCY_CONFIRMED";
    public static final String ACTION_REFRESH = "com.openai.fxm1.action.REFRESH_MONITORING";
    public static final String ACTION_STOP_ALL = "com.openai.fxm1.action.STOP_ALL";
    public static final String ACTION_PAUSE = "com.openai.fxm1.action.PAUSE_BACKGROUND";
    public static final String ACTION_RESUME = "com.openai.fxm1.action.RESUME_BACKGROUND";
    public static final String ACTION_POWER_OFF = "com.openai.fxm1.action.POWER_OFF_BACKGROUND";

    private static final int NOTIFICATION_ID = 4101;
    private static final int SIGNAL_NOTIFICATION_ID = 4102;
    private static final String CHANNEL_MONITOR = "fx_monitor_background";
    private static final String CHANNEL_SIGNAL = "fx_trade_signals";

    private static final long CACHE_M1_MS = 18000L;
    private static final long CACHE_M5_MS = 2 * 60 * 1000L;
    private static final long CACHE_M15_MS = 7 * 60 * 1000L;
    private static final long CACHE_H1_MS = 30 * 60 * 1000L;
    private static final long CACHE_H4_MS = 90 * 60 * 1000L;
    private static final long CACHE_D1_MS = 6 * 60 * 60 * 1000L;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Map<String, CacheItem> cache = new HashMap<>();
    private final Map<String, String> lastSignalBySymbol = new HashMap<>();

    private volatile boolean running = false;
    private volatile boolean analyzing = false;
    private volatile boolean paused = false;

    private final String[] symbols = {
            "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
            "EUR/JPY", "GBP/JPY", "EUR/GBP", "EUR/CHF", "AUD/JPY", "CAD/JPY", "CHF/JPY",
            "GBP/CHF", "EUR/AUD", "GBP/AUD", "AUD/NZD", "NZD/JPY", "XAU/USD"
    };

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (!running) return;
            // PAUSE запрещает только НОВЫЕ ВХОДЫ. Рыночный анализ и сопровождение продолжаются.
            if (!analyzing) analyzeOnce();
            else scheduleNext(1000L);
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        createChannels();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? ACTION_START : intent.getAction();

        if (ACTION_STOP.equals(action)) {
            stopMonitoring(false);
            return START_NOT_STICKY;
        }
        if (ACTION_PAUSE.equals(action)) {
            paused = true;
            prefs().edit()
                    .putBoolean("bg_paused", true)
                    .putBoolean("trading_paused", true)
                    .putString("bg_status", "PAUSE · новые входы запрещены · сопровождение активно")
                    .apply();
            updateNotification(
                    currentSymbol() + " · " + currentTf() + " · " + currentMode(),
                    "PAUSE · новые входы запрещены · сопровождение активно",
                    prefs().getString("state_signal", "WAIT"),
                    prefs().getInt("state_quality", -1)
            );
            return START_STICKY;
        }

        if (ACTION_RESUME.equals(action)) {
            paused = false;
            prefs().edit()
                    .putBoolean("bg_paused", false)
                    .putBoolean("trading_paused", false)
                    .putString("bg_status", "PLAY · новые входы разрешены")
                    .apply();
            handler.removeCallbacks(tick);
            handler.post(tick);
            updateNotification(
                    currentSymbol() + " · " + currentTf() + " · " + currentMode(),
                    "PLAY · новые входы снова разрешены",
                    prefs().getString("state_signal", "WAIT"),
                    prefs().getInt("state_quality", -1)
            );
            return START_STICKY;
        }

        if (ACTION_POWER_OFF.equals(action)) {
            prefs().edit().putBoolean("bg_paused", false).apply();
            stopMonitoring(false);
            return START_NOT_STICKY;
        }


        if (ACTION_EMERGENCY_CONFIRMED.equals(action)) {
            prefs().edit().putLong("emergency_confirm_until_ms", 0L).apply();
            emergencyStop();
            return START_NOT_STICKY;
        }

        if (ACTION_EMERGENCY.equals(action)) {
            long now = System.currentTimeMillis();
            long until = prefs().getLong("emergency_confirm_until_ms", 0L);
            if (now <= until) {
                prefs().edit().putLong("emergency_confirm_until_ms", 0L).apply();
                emergencyStop();
                return START_NOT_STICKY;
            }
            prefs().edit().putLong("emergency_confirm_until_ms", now + 2500L).apply();
            updateNotification(
                    currentSymbol() + " · " + currentTf() + " · " + currentMode(),
                    "EMERGENCY: нажмите ещё раз в течение 2,5 сек",
                    prefs().getString("state_signal", "WAIT"),
                    prefs().getInt("state_quality", -1)
            );
            handler.postDelayed(() -> {
                long deadline = prefs().getLong("emergency_confirm_until_ms", 0L);
                if (deadline > 0L && System.currentTimeMillis() > deadline) {
                    prefs().edit().putLong("emergency_confirm_until_ms", 0L).apply();
                    updateNotification(
                            currentSymbol() + " · " + currentTf() + " · " + currentMode(),
                            paused ? "PAUSE · новые входы запрещены" : "MONITORING · анализ активен",
                            prefs().getString("state_signal", "WAIT"),
                            prefs().getInt("state_quality", -1)
                    );
                }
            }, 2700L);
            return START_STICKY;
        }

        if (ACTION_STOP_ALL.equals(action)) {
            prefs().edit()
                    .putBoolean("stop_all_requested", true)
                    .putBoolean("auto_trading", false)
                    .apply();
            stopMonitoring(false);
            return START_NOT_STICKY;
        }

        if (ACTION_REFRESH.equals(action)) {
            if (running) {
                prefs().edit()
                        .putString("bg_symbol", currentSymbol())
                        .putString("bg_tf", currentTf())
                        .putString("bg_signal", "WAIT")
                        .putInt("bg_quality", -1)
                        .putLong("bg_signal_since_ms", 0L)
                        .putString("bg_context", "Параметры изменены. Жду новый анализ.")
                        .putString("bg_status", "Обновляю настройки…")
                        .apply();
                handler.removeCallbacks(tick);
                handler.post(tick);
                updateNotification(currentSymbol() + " · " + currentTf() + " · " + currentMode(), "Обновляю настройки…", "WAIT", -1);
            }
            return START_STICKY;
        }

        startMonitoring();
        return START_STICKY;
    }

    private void startMonitoring() {
        SharedPreferences p = prefs();
        String key = p.getString("apikey", "").trim();
        if (key.isEmpty()) {
            p.edit().putBoolean("bg_running", false)
                    .putString("bg_status", "Нет Twelve Data API key")
                    .apply();
            stopSelf();
            return;
        }

        running = true;
        paused = false;
        p.edit().putBoolean("bg_running", true)
                .putLong("monitor_stopped_ms", 0L)
                .putBoolean("bg_paused", false)
                .putBoolean("trading_paused", false)
                .putString("bg_status", "Фоновый мониторинг работает")
                .apply();

        Notification n = buildNotification(
                currentSymbol() + " · " + currentTf() + " · " + currentMode(),
                "Фоновый мониторинг запущен",
                "WAIT",
                -1
        );

        try {
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(
                        NOTIFICATION_ID,
                        n,
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
                );
            } else {
                startForeground(NOTIFICATION_ID, n);
            }
        } catch (Exception e) {
            p.edit()
                    .putBoolean("bg_running", false)
                    .putString("bg_status", "Ошибка запуска фонового сервиса: " + safeMessage(e))
                    .apply();
            stopSelf();
            return;
        }

        handler.removeCallbacks(tick);
        handler.post(tick);
    }

    private void stopMonitoring(boolean emergency) {
        running = false;
        handler.removeCallbacks(tick);
        prefs().edit()
                .putLong("monitor_stopped_ms", System.currentTimeMillis())
                .putBoolean("bg_running", false)
                .putBoolean("bg_paused", false)
                .putBoolean("trading_paused", false)
                .putString("bg_status", emergency ? "EMERGENCY STOP" : "Фон полностью выключен")
                .apply();

        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private void emergencyStop() {
        SharedPreferences p = prefs();
        p.edit()
                .putBoolean("auto_trading", false)
                .putBoolean("trading_paused", false)
                .putBoolean("stop_all_requested", true)
                .putString("bg_status", "EMERGENCY STOP · CLOSE ALL")
                .apply();

        final String base = normalizeUrl(p.getString("server_url", ""));
        executor.execute(() -> {
            String result = "AUTO остановлен";
            if (!base.isEmpty()) {
                try {
                    JSONObject payload = new JSONObject();
                    payload.put("mode", "DEMO");
                    httpJson("POST", base + "/close-all", payload);
                    result = "CLOSE ALL отправлен в MT5 bridge";
                } catch (Exception ignored) {
                    result = "AUTO остановлен · CLOSE ALL не подтверждён";
                }
            }
            final String finalResult = result;
            handler.post(() -> finishEmergencyStop(finalResult));
        });
    }

    private void finishEmergencyStop(String result) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) {
            Notification emergency = new Notification.Builder(this, CHANNEL_SIGNAL)
                    .setSmallIcon(R.drawable.ic_stat_fx)
                    .setLargeIcon(BitmapFactory.decodeResource(getResources(), R.drawable.app_icon))
                    .setContentTitle("FX M1 Bot · EMERGENCY STOP")
                    .setContentText(result)
                    .setStyle(new Notification.BigTextStyle().bigText(
                            result + "\nНовые входы запрещены. Проверьте MT5 перед повторным запуском."
                    ))
                    .setAutoCancel(true)
                    .setContentIntent(openAppIntent())
                    .build();
            nm.notify(SIGNAL_NOTIFICATION_ID, emergency);
        }
        stopMonitoring(true);
    }

    private void analyzeOnce() {
        if (!running || analyzing) return;

        final SharedPreferences p = prefs();
        final String key = p.getString("apikey", "").trim();
        final String symbol = currentSymbol();
        final String tf = currentTf();
        final String mode = currentMode();

        analyzing = true;
        p.edit().putString("bg_status", "Обновляю рынок…").apply();
        updateNotification(symbol + " · " + tf + " · " + mode, "Обновляю рынок…", "WAIT", -1);

        executor.execute(() -> {
            try {
                Analysis a;
                int fresh;
                int cached;

                if ("M1".equals(tf)) {
                    FetchResult entry = getSeries(symbol, "1min", key, 120, CACHE_M1_MS);
                    FetchResult fast = entry;
                    FetchResult h1 = getSeries(symbol, "5min", key, 100, CACHE_M5_MS);
                    FetchResult h2 = getSeries(symbol, "15min", key, 100, CACHE_M15_MS);
                    FetchResult h3 = getSeries(symbol, "1h", key, 100, CACHE_H1_MS);

                    a = analyzeAdaptive(
                            symbol, tf, mode,
                            fast.data, "M1",
                            h1.data, "M5",
                            h2.data, "M15",
                            h3.data, "H1"
                    );

                    fresh = (entry.fromCache ? 0 : 1) +
                            (h1.fromCache ? 0 : 1) +
                            (h2.fromCache ? 0 : 1) +
                            (h3.fromCache ? 0 : 1);
                    cached = 4 - fresh;

                } else {
                    FetchResult fast;
                    FetchResult entry;
                    FetchResult higher1;
                    FetchResult higher2;
                    String fastLabel;
                    String entryLabel;
                    String higher1Label;
                    String higher2Label;

                    if ("M5".equals(tf)) {
                        fast = getSeries(symbol, "1min", key, 120, CACHE_M1_MS);
                        entry = getSeries(symbol, "5min", key, 120, CACHE_M5_MS);
                        higher1 = getSeries(symbol, "15min", key, 100, CACHE_M15_MS);
                        higher2 = getSeries(symbol, "1h", key, 100, CACHE_H1_MS);
                        fastLabel = "M1";
                        entryLabel = "M5";
                        higher1Label = "M15";
                        higher2Label = "H1";
                    } else if ("M15".equals(tf)) {
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

                    a = analyzeAdaptive(
                            symbol, tf, mode,
                            fast.data, fastLabel,
                            entry.data, entryLabel,
                            higher1.data, higher1Label,
                            higher2.data, higher2Label
                    );

                    fresh = (fast.fromCache ? 0 : 1) +
                            (entry.fromCache ? 0 : 1) +
                            (higher1.fromCache ? 0 : 1) +
                            (higher2.fromCache ? 0 : 1);
                    cached = 4 - fresh;
                }

                saveAnalysis(a, fresh, cached);
                refreshMt5Snapshot();
                updateNotification(
                        a.symbol + " · " + tf + " · " + mode,
                        "API " + fresh + " · кэш " + cached,
                        a.signal,
                        a.quality
                );

                notifyTradeSignalIfNew(a);
                maybeSendToTradingServer(a, tf, mode);

                analyzing = false;
                scheduleNext(intervalFor(tf));

            } catch (RateLimitException e) {
                analyzing = false;
                prefs().edit()
                        .putString("bg_signal", "WAIT")
                        .putInt("bg_quality", -1)
                        .putLong("bg_signal_since_ms", 0L)
                        .putString("bg_context", "Нет свежего подтверждения: достигнут лимит Twelve Data. Старый BUY/SELL снят до нового анализа.")
                        .putString("bg_status", "Лимит Twelve Data · повтор через 60 сек")
                        .putString("state_signal", "WAIT")
                        .putInt("state_quality", -1)
                        .putLong("state_signal_since_ms", 0L)
                        .putString("state_context", "Нет свежего подтверждения: достигнут лимит Twelve Data. Старый BUY/SELL снят до нового анализа.")
                        .putLong("state_last_update_ms", System.currentTimeMillis())
                        .putString("state_source", "BG")
                        .apply();
                updateNotification(
                        currentSymbol() + " · " + currentTf(),
                        "Лимит API · повтор через 60 сек",
                        "WAIT",
                        -1
                );
                scheduleNext(60000L);

            } catch (Exception e) {
                analyzing = false;
                String msg = safeMessage(e);
                prefs().edit()
                        .putString("bg_status", "Ошибка: " + msg)
                        .apply();
                updateNotification(
                        currentSymbol() + " · " + currentTf(),
                        "Ошибка · повтор автоматически",
                        "WAIT",
                        -1
                );
                scheduleNext(intervalFor(currentTf()));
            }
        });
    }

    private void saveAnalysis(Analysis a, int fresh, int cached) {
        SharedPreferences p = prefs();
        String tf = currentTf();
        String oldSignal = p.getString("state_signal", "WAIT");
        String oldSymbol = p.getString("state_symbol", "");
        String oldTf = p.getString("state_tf", "");
        long now = System.currentTimeMillis();
        long signalSince = p.getLong("state_signal_since_ms", 0L);

        if (!a.signal.equals(oldSignal) ||
                !a.symbol.equals(oldSymbol) ||
                !tf.equals(oldTf) ||
                signalSince <= 0L) {
            signalSince = now;
        }

        if ("WAIT".equals(a.signal)) {
            signalSince = 0L;
        }

        p.edit()
                .putBoolean("bg_running", true)
                .putString("bg_symbol", a.symbol)
                .putString("bg_tf", tf)
                .putString("bg_signal", a.signal)
                .putInt("bg_quality", a.quality)
                .putString("bg_context", a.context)
                .putInt("bg_api_count", fresh)
                .putInt("bg_cache_count", cached)
                .putLong("bg_entry_bits", Double.doubleToLongBits(a.entry))
                .putLong("bg_sl_bits", Double.doubleToLongBits(a.sl))
                .putLong("bg_tp1_bits", Double.doubleToLongBits(a.tp1))
                .putLong("bg_tp2_bits", Double.doubleToLongBits(a.tp2))
                .putLong("bg_signal_since_ms", signalSince)
                .putLong("bg_last_update_ms", now)
                .putString("bg_status", "Мониторинг работает")
                .putString("state_signal_key", a.symbol + "|" + tf)
                .putString("state_symbol", a.symbol)
                .putString("state_tf", tf)
                .putString("state_signal", a.signal)
                .putInt("state_quality", a.quality)
                .putString("state_context", a.context)
                .putInt("state_api_count", fresh)
                .putInt("state_cache_count", cached)
                .putLong("state_entry_bits", Double.doubleToLongBits(a.entry))
                .putLong("state_sl_bits", Double.doubleToLongBits(a.sl))
                .putLong("state_tp1_bits", Double.doubleToLongBits(a.tp1))
                .putLong("state_tp2_bits", Double.doubleToLongBits(a.tp2))
                .putLong("state_signal_since_ms", signalSince)
                .putLong("state_last_update_ms", now)
                .putString("state_source", "BG")
                .apply();
    }

    private void notifyTradeSignalIfNew(Analysis a) {
        String old = lastSignalBySymbol.get(a.symbol);

        if (!"BUY".equals(a.signal) && !"SELL".equals(a.signal)) {
            lastSignalBySymbol.put(a.symbol, "WAIT");
            return;
        }

        if (a.signal.equals(old)) return;
        lastSignalBySymbol.put(a.symbol, a.signal);

        ToneGenerator tone = new ToneGenerator(AudioManager.STREAM_NOTIFICATION, 90);
        tone.startTone(ToneGenerator.TONE_PROP_BEEP2, 600);

        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;

        String levels = "Entry " + fmt(a.entry) +
                " · SL " + fmt(a.sl) +
                " · TP1 " + fmt(a.tp1);

        Notification n = new Notification.Builder(this, CHANNEL_SIGNAL)
                .setSmallIcon(R.drawable.ic_stat_fx)
                .setLargeIcon(BitmapFactory.decodeResource(getResources(), R.drawable.app_icon))
                .setContentTitle("FX M1 Bot · " + a.signal + " · " + a.symbol)
                .setContentText("Качество " + a.quality + "/100 · " + levels)
                .setStyle(new Notification.BigTextStyle().bigText(
                        a.symbol + " · " + a.signal +
                        "\nКачество: " + a.quality + "/100" +
                        "\n" + levels
                ))
                .setAutoCancel(true)
                .setContentIntent(openAppIntent())
                .build();

        nm.notify(SIGNAL_NOTIFICATION_ID, n);
    }

    private void maybeSendToTradingServer(Analysis a, String tf, String mode) {
        if (paused || prefs().getBoolean("trading_paused", false)) return;
        if (!prefs().getBoolean("auto_trading", false)) return;
        if ("WAIT".equals(a.signal)) return;

        final String base = normalizeUrl(prefs().getString("server_url", ""));
        if (base.isEmpty()) return;

        try {
            JSONObject health = httpJson("GET", base + "/health", null);
            if (!health.optBoolean("ok", false)) return;
            if (!health.optBoolean("mt5_connected", false)) return;
            if (!"DEMO".equalsIgnoreCase(health.optString("account_type", ""))) return;

            int riskPos = prefs().getInt("risk_pos", 1);
            double[] risks = {0.25, 0.50, 1.00};

            int maxPos = prefs().getInt("maxpos_pos", 0) + 1;
            int driftPos = prefs().getInt("maxdrift_pos", 1);
            double[] drifts = {0.03, 0.05, 0.10, 0.20};

            JSONObject payload = new JSONObject();
            payload.put("symbol", a.symbol);
            payload.put("signal", a.signal);
            payload.put("quality", a.quality);
            payload.put("entry", a.entry);
            payload.put("sl", a.sl);
            payload.put("tp1", a.tp1);
            payload.put("tp2", a.tp2);
            payload.put("risk_pct", risks[Math.max(0, Math.min(riskPos, risks.length - 1))]);
            payload.put("max_positions", maxPos);
            payload.put("mode", "DEMO");
            payload.put("signal_mode", mode);
            payload.put("entry_timeframe", tf);
            payload.put("api_entry", a.entry);
            payload.put("max_price_drift_pct", drifts[Math.max(0, Math.min(driftPos, drifts.length - 1))]);
            payload.put("execution_price_source", "MT5");

            httpJson("POST", base + "/signal", payload);

        } catch (Exception ignored) {
        }
    }

    private void refreshMt5Snapshot() {
        SharedPreferences p = prefs();
        String base = normalizeUrl(p.getString("server_url", ""));
        if (base.isEmpty()) return;
        try {
            JSONObject h = httpJson("GET", base + "/health", null);
            boolean ok = h.optBoolean("ok", false);
            boolean connected = h.optBoolean("mt5_connected", false);
            double balance = h.optDouble("balance", Double.NaN);
            double equity = h.optDouble("equity", Double.NaN);
            double floating = h.optDouble("floating_pl", 0.0);
            p.edit()
                    .putBoolean("mt5_connected_snapshot", ok && connected)
                    .putString("mt5_account_type_snapshot", h.optString("account_type", "—"))
                    .putLong("mt5_balance_bits", Double.doubleToLongBits(balance))
                    .putLong("mt5_equity_bits", Double.doubleToLongBits(equity))
                    .putString("mt5_currency_snapshot", h.optString("currency", "USD"))
                    .putInt("mt5_positions_snapshot", h.optInt("positions", 0))
                    .putLong("mt5_floating_bits", Double.doubleToLongBits(floating))
                    .apply();
        } catch (Exception ignored) {
            p.edit().putBoolean("mt5_connected_snapshot", false).apply();
        }
    }

    private void scheduleNext(long delayMs) {
        handler.removeCallbacks(tick);
        if (running) handler.postDelayed(tick, delayMs);
    }

    private long intervalFor(String tf) {
        if ("M1".equals(tf)) return 20000L;
        if ("M5".equals(tf)) return 60000L;
        if ("M15".equals(tf)) return 180000L;
        return 300000L;
    }

    private String currentSymbol() {
        int pos = prefs().getInt("symbol_pos", 0);
        pos = Math.max(0, Math.min(pos, symbols.length - 1));
        return symbols[pos];
    }

    private String currentTf() {
        int pos = prefs().getInt("entry_tf_pos", 1);
        String[] values = {"M1", "M5", "M15", "H1"};
        pos = Math.max(0, Math.min(pos, values.length - 1));
        return values[pos];
    }

    private String currentMode() {
        int pos = prefs().getInt("signal_mode_pos", 1);
        String[] values = {"CONSERVATIVE", "NORMAL", "AGGRESSIVE"};
        pos = Math.max(0, Math.min(pos, values.length - 1));
        return values[pos];
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("fxm1", MODE_PRIVATE);
    }

    private void createChannels() {
        if (Build.VERSION.SDK_INT < 26) return;

        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;

        NotificationChannel monitor = new NotificationChannel(
                CHANNEL_MONITOR,
                "FX M1 Bot · мониторинг",
                NotificationManager.IMPORTANCE_LOW
        );
        monitor.setDescription("Мониторинг рынка FX M1 Bot");
        monitor.setShowBadge(false);

        NotificationChannel signal = new NotificationChannel(
                CHANNEL_SIGNAL,
                "FX Bot · торговые сигналы",
                NotificationManager.IMPORTANCE_HIGH
        );
        signal.setDescription("BUY/SELL и аварийные уведомления");

        nm.createNotificationChannel(monitor);
        nm.createNotificationChannel(signal);
    }

    private Notification buildNotification(String title, String text, String signal, int quality) {
        SharedPreferences p = prefs();
        boolean mt5Connected = p.getBoolean("mt5_connected_snapshot", false);
        String accountType = p.getString("mt5_account_type_snapshot", "—");
        String currency = p.getString("mt5_currency_snapshot", "USD");
        double balance = Double.longBitsToDouble(p.getLong("mt5_balance_bits", Double.doubleToLongBits(Double.NaN)));
        int positions = p.getInt("mt5_positions_snapshot", 0);
        boolean auto = p.getBoolean("auto_trading", false);
        String risk = p.getString("risk_label", "0.50%");
        if (risk == null || risk.trim().isEmpty() || "null".equals(risk)) risk = "0.50%";

        String symbol = currentSymbol();
        String tf = currentTf();
        String mode = currentMode();
        String core = symbol + " · " + tf + " · " + mode + " · " + signal + (quality >= 0 ? " · " + quality + "/100" : "");
        String balanceText = Double.isNaN(balance) ? "—" : String.format(Locale.US, "%.2f %s", balance, currency);
        String accountLine = "Счёт: " + accountType + " · Баланс: " + balanceText;
        String positionsLine = "Позиции: " + positions + " · Риск: " + risk + " · AUTO: " + (auto ? "ON" : "OFF");
        String connectionLine = mt5Connected ? "MT5 CONNECTED" : "MT5 OFFLINE";

        int signalColor = "BUY".equals(signal) ? Color.rgb(66,214,122)
                : "SELL".equals(signal) ? Color.rgb(255,72,87)
                : Color.WHITE;

        RemoteViews collapsed = new RemoteViews(getPackageName(), R.layout.notification_monitoring_compact);
        collapsed.setImageViewResource(R.id.notifLogo, R.drawable.app_icon);
        collapsed.setTextViewText(R.id.notifTitle, "FX M1 Bot");
        collapsed.setTextViewText(R.id.notifCore, core);
        collapsed.setTextColor(R.id.notifCore, signalColor);
        collapsed.setTextViewText(R.id.notifAccount, accountLine);
        collapsed.setTextViewText(R.id.notifPositions, positionsLine);
        collapsed.setTextViewText(R.id.notifPause, paused ? "PLAY" : "PAUSE");
        collapsed.setOnClickPendingIntent(R.id.notifPause, serviceActionIntent(paused ? ACTION_RESUME : ACTION_PAUSE, 101));
        collapsed.setOnClickPendingIntent(R.id.notifEmergency, serviceActionIntent(ACTION_EMERGENCY, 102));

        RemoteViews expanded = new RemoteViews(getPackageName(), R.layout.notification_monitoring_expanded);
        expanded.setImageViewResource(R.id.notifLogo, R.drawable.app_icon);
        expanded.setTextViewText(R.id.notifTitle, "FX M1 Bot · MONITORING");
        expanded.setTextViewText(R.id.notifCore, core);
        expanded.setTextColor(R.id.notifCore, signalColor);
        expanded.setTextViewText(R.id.notifAccount, accountLine);
        expanded.setTextViewText(R.id.notifPositions, positionsLine);
        expanded.setTextViewText(R.id.notifConnection, connectionLine);
        expanded.setTextViewText(R.id.notifPause, paused ? "PLAY" : "PAUSE");
        expanded.setOnClickPendingIntent(R.id.notifPause, serviceActionIntent(paused ? ACTION_RESUME : ACTION_PAUSE, 101));
        expanded.setOnClickPendingIntent(R.id.notifEmergency, serviceActionIntent(ACTION_EMERGENCY, 102));

        Notification.Action pausePlayAction = new Notification.Action.Builder(
                paused ? android.R.drawable.ic_media_play : android.R.drawable.ic_media_pause,
                paused ? "PLAY" : "PAUSE",
                serviceActionIntent(paused ? ACTION_RESUME : ACTION_PAUSE, 101)
        ).build();
        Notification.Action emergencyAction = new Notification.Action.Builder(
                android.R.drawable.stat_sys_warning,
                "EMERGENCY",
                serviceActionIntent(ACTION_EMERGENCY, 102)
        ).build();

        return new Notification.Builder(this, CHANNEL_MONITOR)
                .setSmallIcon(R.drawable.ic_stat_fx)
                .setContentTitle("FX M1 Bot")
                .setContentText(core)
                .setCustomContentView(collapsed)
                .setCustomBigContentView(expanded)
                .setStyle(new Notification.DecoratedCustomViewStyle())
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setContentIntent(openAppIntent())
                .addAction(pausePlayAction)
                .addAction(emergencyAction)
                .build();
    }

    private void updateNotification(String title, String text, String signal, int quality) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null && running) {
            nm.notify(NOTIFICATION_ID, buildNotification(title, text, signal, quality));
        }
    }

    private PendingIntent openAppIntent() {
        Intent i = new Intent(this, MainActivity.class);
        i.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        return PendingIntent.getActivity(
                this,
                100,
                i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
    }

    private PendingIntent serviceActionIntent(String action, int requestCode) {
        Intent i = new Intent(this, MonitoringService.class);
        i.setAction(action);
        return PendingIntent.getService(
                this,
                requestCode,
                i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
    }

    private FetchResult getSeries(String symbol, String interval, String key, int outputsize, long maxAgeMs) throws Exception {
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

    private List<Candle> fetch(String symbol, String interval, String key, int outputsize) throws Exception {
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
        InputStream is = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
        String body = readAll(is);

        JSONObject root = new JSONObject(body);
        if (root.has("status") && "error".equalsIgnoreCase(root.optString("status"))) {
            String message = root.optString("message", "API error");
            String lower = message.toLowerCase(Locale.US);
            if (lower.contains("api credits") || lower.contains("current minute") || lower.contains("rate limit")) {
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

    private Analysis analyzeAdaptive(String symbol,
                                     String entryTf,
                                     String mode,
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
        if (atr <= 0) atr = Math.max(minStopDistance(symbol), last.high - last.low);

        boolean buySetup;
        boolean sellSetup;

        if ("CONSERVATIVE".equals(mode)) {
            buySetup = sHigher2 >= 0 && sHigher1 > 0 && sEntry > 0 && sFast >= 0 && structure >= 0 && breakout > 0;
            sellSetup = sHigher2 <= 0 && sHigher1 < 0 && sEntry < 0 && sFast <= 0 && structure <= 0 && breakout < 0;

        } else if ("AGGRESSIVE".equals(mode)) {
            int buyVotes = 0;
            int sellVotes = 0;

            if (sHigher2 > 0) buyVotes++; else if (sHigher2 < 0) sellVotes++;
            if (sHigher1 > 0) buyVotes++; else if (sHigher1 < 0) sellVotes++;
            if (sEntry > 0) buyVotes++; else if (sEntry < 0) sellVotes++;
            if (sFast > 0) buyVotes++; else if (sFast < 0) sellVotes++;
            if (structure > 0) buyVotes++; else if (structure < 0) sellVotes++;

            buySetup = sEntry > 0 && sHigher1 >= 0 && breakout >= 0 && buyVotes >= 3 && sellVotes <= 1;
            sellSetup = sEntry < 0 && sHigher1 <= 0 && breakout <= 0 && sellVotes >= 3 && buyVotes <= 1;

        } else {
            buySetup = sHigher2 >= 0 && sHigher1 > 0 && sEntry > 0 && sFast >= 0 && structure >= 0 && breakout >= 0;
            sellSetup = sHigher2 <= 0 && sHigher1 < 0 && sEntry < 0 && sFast <= 0 && structure <= 0 && breakout <= 0;
        }

        String signal = buySetup ? "BUY" : sellSetup ? "SELL" : "WAIT";
        int quality = setupQualityAdaptive(signal, sHigher2, sHigher1, sEntry, sFast, structure, breakout);

        double slDist = Math.max(atr * 1.8, minStopDistance(symbol));
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
        if (breakout > 0) reason = entryLabel + ": подтверждён пробой/импульс вверх";
        else if (breakout < 0) reason = entryLabel + ": подтверждён пробой/импульс вниз";
        else reason = entryLabel + ": подтверждённого пробоя нет";

        String filter;
        if ("BUY".equals(signal)) filter = "Фильтр: " + mode + " разрешил BUY";
        else if ("SELL".equals(signal)) filter = "Фильтр: " + mode + " разрешил SELL";
        else filter = "Фильтр: " + mode + " · условия для входа не совпали";

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

        return new Analysis(symbol, signal, quality, entry, sl, tp1, tp2, context);
    }

    private int setupQualityAdaptive(String signal, int higher2, int higher1, int entry, int fast, int structure, int breakout) {
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
        if (breakout == direction * 2) q += 7;
        else if (breakout == direction) q += 4;
        return Math.min(100, q);
    }

    private int trendScore(List<Candle> c) {
        double ema9 = ema(c, 9);
        double ema21 = ema(c, 21);
        int s = ema9 > ema21 ? 1 : ema9 < ema21 ? -1 : 0;

        int n = c.size();
        double recentStart = c.get(Math.max(0, n - 10)).close;
        double recentEnd = c.get(n - 1).close;

        if (recentEnd > recentStart) s++;
        else if (recentEnd < recentStart) s--;

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

        if (b.high > a.high && b.low > a.low) return 1;
        if (b.high < a.high && b.low < a.low) return -1;
        return 0;
    }

    private int breakoutScore(List<Candle> c) {
        int n = c.size();
        if (n < 30) return 0;

        Candle last = c.get(n - 1);
        double resistance = -Double.MAX_VALUE;
        double support = Double.MAX_VALUE;

        for (int i = n - 22; i < n - 2; i++) {
            resistance = Math.max(resistance, c.get(i).high);
            support = Math.min(support, c.get(i).low);
        }

        double a = atr(c, 14);
        double body = Math.abs(last.close - last.open);

        if (last.close > resistance) return body > a * 0.50 ? 2 : 1;
        if (last.close < support) return body > a * 0.50 ? -2 : -1;
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

    private double minStopDistance(String symbol) {
        if (symbol.startsWith("XAU/")) return 1.00;
        if (symbol.contains("JPY")) return 0.050;
        return 0.00050;
    }

    private String arrow(int s) {
        return s > 0 ? "↑" : s < 0 ? "↓" : "→";
    }

    private String fmt(double x) {
        if (x == 0 || Double.isNaN(x)) return "—";
        if (x >= 100) return String.format(Locale.US, "%.3f", x);
        return String.format(Locale.US, "%.5f", x);
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

    private String normalizeUrl(String raw) {
        String u = raw == null ? "" : raw.trim();
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }

    private String readAll(InputStream is) throws IOException {
        if (is == null) return "";
        BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line);
        return sb.toString();
    }

    private String safeMessage(Exception e) {
        String m = e.getMessage();
        return m == null || m.trim().isEmpty() ? "неизвестная ошибка" : m;
    }

    @Override
    public void onDestroy() {
        running = false;
        handler.removeCallbacks(tick);
        executor.shutdownNow();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    static class Candle {
        final double open, high, low, close;
        Candle(double open, double high, double low, double close) {
            this.open = open;
            this.high = high;
            this.low = low;
            this.close = close;
        }
    }

    static class Analysis {
        final String symbol, signal, context;
        final int quality;
        final double entry, sl, tp1, tp2;

        Analysis(String symbol, String signal, int quality, double entry, double sl, double tp1, double tp2, String context) {
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
        CacheItem(List<Candle> data, long savedAtMs) {
            this.data = data;
            this.savedAtMs = savedAtMs;
        }
    }

    static class FetchResult {
        final List<Candle> data;
        final boolean fromCache;
        FetchResult(List<Candle> data, boolean fromCache) {
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
