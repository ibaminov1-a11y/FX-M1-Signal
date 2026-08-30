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
    public static final String ACTION_APPROVE_TRADE = "com.openai.fxm1.action.APPROVE_TRADE";
    public static final String ACTION_REJECT_TRADE = "com.openai.fxm1.action.REJECT_TRADE";

    private static final int NOTIFICATION_ID = 4101;
    private static final int SIGNAL_NOTIFICATION_ID = 4102;
    private static final int APPROVAL_NOTIFICATION_ID = 4103;
    private static final String CHANNEL_MONITOR = "fx_monitor_controls_v71";
    private static final String CHANNEL_SIGNAL = "fx_trade_signals";

    private static final long CACHE_M1_MS = 18000L;
    private static final long CACHE_M5_MS = 2 * 60 * 1000L;
    private static final long CACHE_M15_MS = 7 * 60 * 1000L;
    private static final long CACHE_H1_MS = 30 * 60 * 1000L;
    private static final long CACHE_H4_MS = 90 * 60 * 1000L;
    private static final long CACHE_D1_MS = 6 * 60 * 60 * 1000L;
    private static final long CACHE_W1_MS = 18 * 60 * 60 * 1000L;
    private static final long CACHE_MN1_MS = 24 * 60 * 60 * 1000L;

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

    // Keeps the foreground association and notification alive even on long H4/D1/W1/MN1 intervals.
    private final Runnable notificationWatchdog = new Runnable() {
        @Override
        public void run() {
            if (!running) return;
            updateNotification(
                    currentSymbol() + " · " + currentTf() + " · " + currentMode(),
                    paused ? "PAUSE · сопровождение активно" : "MONITORING · foreground active",
                    prefs().getString("state_signal", "WAIT"),
                    prefs().getInt("state_quality", -1));
            handler.postDelayed(this, 15000L);
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

        if (ACTION_APPROVE_TRADE.equals(action)) {
            approvePendingTrade();
            return START_STICKY;
        }
        if (ACTION_REJECT_TRADE.equals(action)) {
            prefs().edit().remove("pending_trade_json").apply();
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.cancel(APPROVAL_NOTIFICATION_ID);
            FeatureEngine.appendSignalHistory(prefs(), currentSymbol(), currentTf(), prefs().getString("state_signal", "WAIT"), prefs().getInt("state_quality", -1), "manual SKIP");
            return START_STICKY;
        }

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
        FeatureEngine.ensureDefaults(p);
        String key = p.getString("apikey", "").trim();
        if (key.isEmpty()) {
            p.edit().putBoolean("bg_running", false)
                    .putString("bg_status", "Нет Twelve Data API key")
                    .apply();
            stopSelf();
            return;
        }

        running = true;
        paused = p.getBoolean("bg_paused", false);
        p.edit().putBoolean("bg_running", true)
                .putLong("monitor_stopped_ms", 0L)
                .putBoolean("bg_paused", paused)
                .putBoolean("trading_paused", paused)
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
        handler.removeCallbacks(notificationWatchdog);
        handler.postDelayed(notificationWatchdog, 15000L);
    }

    private void stopMonitoring(boolean emergency) {
        running = false;
        handler.removeCallbacks(tick);
        handler.removeCallbacks(notificationWatchdog);
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
                List<Candle> sparkSeries = null;

                if ("M1".equals(tf)) {
                    FetchResult entry = getSeries(symbol, "1min", key, 120, CACHE_M1_MS);
                    sparkSeries = entry.data;
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
                    } else if ("H1".equals(tf)) {
                        fast = getSeries(symbol, "15min", key, 120, CACHE_M15_MS);
                        entry = getSeries(symbol, "1h", key, 120, CACHE_H1_MS);
                        higher1 = getSeries(symbol, "4h", key, 100, CACHE_H4_MS);
                        higher2 = getSeries(symbol, "1day", key, 100, CACHE_D1_MS);
                        fastLabel = "M15"; entryLabel = "H1"; higher1Label = "H4"; higher2Label = "D1";
                    } else if ("H4".equals(tf)) {
                        fast = getSeries(symbol, "1h", key, 120, CACHE_H1_MS);
                        entry = getSeries(symbol, "4h", key, 120, CACHE_H4_MS);
                        higher1 = getSeries(symbol, "1day", key, 100, CACHE_D1_MS);
                        higher2 = getSeries(symbol, "1week", key, 100, CACHE_W1_MS);
                        fastLabel = "H1"; entryLabel = "H4"; higher1Label = "D1"; higher2Label = "W1";
                    } else if ("D1".equals(tf)) {
                        fast = getSeries(symbol, "4h", key, 120, CACHE_H4_MS);
                        entry = getSeries(symbol, "1day", key, 120, CACHE_D1_MS);
                        higher1 = getSeries(symbol, "1week", key, 100, CACHE_W1_MS);
                        higher2 = getSeries(symbol, "1month", key, 100, CACHE_MN1_MS);
                        fastLabel = "H4"; entryLabel = "D1"; higher1Label = "W1"; higher2Label = "MN1";
                    } else if ("W1".equals(tf)) {
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

                    sparkSeries = entry.data;
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

                saveSparkline(sparkSeries);
                saveAnalysis(a, fresh, cached);
                refreshMt5Snapshot();
                manageOpenPositions();
                updateWatchlistRadar(key, tf);
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

    private void saveSparkline(List<Candle> series) {
        if (series == null || series.size() < 2) return;
        int from = Math.max(0, series.size() - 30);
        StringBuilder sb = new StringBuilder();
        for (int i = from; i < series.size(); i++) {
            if (sb.length() > 0) sb.append(',');
            Candle c = series.get(i);
            sb.append((c.high + c.low + c.close) / 3.0);
        }
        prefs().edit().putString("state_sparkline", sb.toString()).apply();
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
                .putString("bg_why", a.why)
                .putString("bg_components", a.components)
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
                .putString("state_why", a.why)
                .putString("state_components", a.components)
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
        FeatureEngine.appendSignalHistory(p, a.symbol, tf, a.signal, a.quality, "BG analysis");
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
        // V6.6.2: one persistent foreground notification only. This avoids OEM
        // "More notifications" bundles and keeps PAUSE/EMERGENCY on one card.
    }

    private void maybeSendToTradingServer(Analysis a, String tf, String mode) {
        SharedPreferences p = prefs();
        if (!isForexMarketOpen()) {
            p.edit().putString("bg_status", "MARKET CLOSED · торговля заблокирована").apply();
            FeatureEngine.appendSignalHistory(p, a.symbol, tf, a.signal, a.quality, "SKIP: MARKET CLOSED");
            return;
        }
        if (paused || p.getBoolean("trading_paused", false)) return;
        if (!p.getBoolean("auto_trading", false)) return;
        if ("WAIT".equals(a.signal)) return;

        if (p.getBoolean("session_filter_enabled", false)) {
            String session = FeatureEngine.currentSession();
            String allowed = p.getString("allowed_sessions", "LONDON,NEW_YORK");
            boolean sessionAllowed = false;
            if (allowed != null) {
                if (session.contains("+")) {
                    for (String part : session.split("\\+")) if (allowed.contains(part)) sessionAllowed = true;
                } else sessionAllowed = allowed.contains(session);
            }
            if (!sessionAllowed) {
                FeatureEngine.appendSignalHistory(p, a.symbol, tf, a.signal, a.quality, "SKIP: session " + session);
                return;
            }
        }

        final String base = normalizeUrl(p.getString("server_url", ""));
        if (base.isEmpty()) return;

        try {
            JSONObject health = httpJson("GET", base + "/health", null);
            if (!health.optBoolean("ok", false) || !health.optBoolean("mt5_connected", false)) return;
            if (!"DEMO".equalsIgnoreCase(health.optString("account_type", ""))) return;

            int riskPos = p.getInt("risk_pos", 1);
            double[] risks = {0.25, 0.50, 1.00};
            int maxPos = p.getInt("maxpos_pos", 0) + 1;
            int driftPos = p.getInt("maxdrift_pos", 1);
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
            payload.put("timeframe", tf);
            payload.put("api_entry", a.entry);
            payload.put("max_price_drift_pct", drifts[Math.max(0, Math.min(driftPos, drifts.length - 1))]);
            payload.put("execution_price_source", "MT5");
            FeatureEngine.applySignalFeatures(payload, p, a.why, a.components);

            JSONObject response = httpJson("POST", base + "/signal", payload);
            boolean accepted = response.optBoolean("accepted", false);
            String message = response.optString("message", accepted ? "DEMO order opened" : "signal rejected");
            FeatureEngine.appendSignalHistory(p, a.symbol, tf, a.signal, a.quality, message);
            p.edit().putString("last_execution_result", message).apply();

            if (response.optBoolean("pending_approval", false)) {
                p.edit().putString("pending_trade_json", payload.toString()).apply();
                notifyApprovalRequired(a, message);
            }
        } catch (Exception e) {
            FeatureEngine.appendSignalHistory(p, a.symbol, tf, a.signal, a.quality, "ERROR: " + safeMessage(e));
        }
    }

    private void approvePendingTrade() {
        SharedPreferences p = prefs();
        final String raw = p.getString("pending_trade_json", "");
        final String base = normalizeUrl(p.getString("server_url", ""));
        if (raw == null || raw.trim().isEmpty() || base.isEmpty()) return;
        executor.execute(() -> {
            try {
                JSONObject payload = new JSONObject(raw);
                payload.put("manual_approved", true);
                JSONObject response = httpJson("POST", base + "/signal", payload);
                String message = response.optString("message", "approval processed");
                FeatureEngine.appendSignalHistory(p, payload.optString("symbol"), payload.optString("entry_timeframe"), payload.optString("signal"), payload.optInt("quality", -1), "APPROVE: " + message);
            } catch (Exception e) {
                FeatureEngine.appendSignalHistory(p, currentSymbol(), currentTf(), prefs().getString("state_signal", "WAIT"), prefs().getInt("state_quality", -1), "APPROVE ERROR: " + safeMessage(e));
            } finally {
                p.edit().remove("pending_trade_json").apply();
                NotificationManager nm = getSystemService(NotificationManager.class);
                if (nm != null) nm.cancel(APPROVAL_NOTIFICATION_ID);
            }
        });
    }

    private void notifyApprovalRequired(Analysis a, String message) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;
        PendingIntent approve = serviceActionIntent(ACTION_APPROVE_TRADE, 201);
        PendingIntent reject = serviceActionIntent(ACTION_REJECT_TRADE, 202);
        Notification n = new Notification.Builder(this, CHANNEL_SIGNAL)
                .setSmallIcon(R.drawable.ic_stat_fx)
                .setLargeIcon(BitmapFactory.decodeResource(getResources(), R.drawable.app_icon))
                .setContentTitle("FX M1 Bot · требуется подтверждение")
                .setContentText(a.symbol + " · " + a.signal + " · " + a.quality + "/100")
                .setStyle(new Notification.BigTextStyle().bigText(message + "\n" + a.why))
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setPriority(Notification.PRIORITY_MAX)
                .setContentIntent(openAppIntent())
                .addAction(new Notification.Action.Builder(R.drawable.ic_stat_fx, "APPROVE", approve).build())
                .addAction(new Notification.Action.Builder(R.drawable.ic_stat_fx, "SKIP", reject).build())
                .setAutoCancel(false)
                .build();
        nm.notify(APPROVAL_NOTIFICATION_ID, n);
    }

    private void manageOpenPositions() {
        SharedPreferences p = prefs();
        if (!p.getBoolean("position_manager_enabled", true)) return;
        String base = normalizeUrl(p.getString("server_url", ""));
        if (base.isEmpty() || !p.getBoolean("mt5_connected_snapshot", false)) return;
        try {
            JSONObject r = FeatureEngine.httpJson("POST", base + "/manage-positions", FeatureEngine.managePayload(p));
            p.edit().putString("position_manager_status", r.optBoolean("ok", false) ? "ACTIVE" : r.optString("message", "ERROR")).apply();
            long last = p.getLong("smart_snapshot_ms", 0L);
            if (System.currentTimeMillis() - last > 60000L) {
                JSONObject st = FeatureEngine.httpJson("GET", base + "/stats?days=30", null);
                JSONObject rs = FeatureEngine.httpJson("GET", base + "/risk-state?daily_loss_limit_pct=" + p.getFloat("daily_loss_limit_pct",3f) + "&max_drawdown_pct=" + p.getFloat("max_drawdown_pct",5f) + "&max_consecutive_losses=" + p.getInt("max_consecutive_losses",3), null);
                p.edit().putString("stats_snapshot", FeatureEngine.formatStats(st))
                        .putString("risk_snapshot", rs.optBoolean("allowed", true) ? "RISK OK" : "RISK BLOCK: " + rs.optJSONArray("blocks"))
                        .putLong("smart_snapshot_ms", System.currentTimeMillis()).apply();
            }
        } catch (Exception e) {
            p.edit().putString("position_manager_status", "ERROR: " + safeMessage(e)).apply();
        }
    }

    private void updateWatchlistRadar(String key, String tf) {
        SharedPreferences p = prefs();
        if (!p.getBoolean("multi_pair_enabled", false)) return;
        long last = p.getLong("watchlist_radar_ms", 0L);
        if (System.currentTimeMillis() - last < 120000L) return;
        List<String> items = FeatureEngine.watchlistItems(p);
        if (items.isEmpty()) return;
        int idx = p.getInt("watchlist_radar_index", 0);
        String selected = currentSymbol();
        String candidate = null;
        for (int n=0;n<items.size();n++) {
            String c = items.get((idx+n)%items.size());
            if (!c.equalsIgnoreCase(selected)) { candidate = c; idx=(idx+n+1)%items.size(); break; }
        }
        if (candidate == null) return;
        try {
            FetchResult f = getSeries(candidate, "5min", key, 40, CACHE_M5_MS);
            int trend = trendScore(f.data);
            String arrow = trend > 0 ? "↑" : trend < 0 ? "↓" : "→";
            String old = p.getString("watchlist_radar", "");
            String line = candidate + " " + arrow;
            p.edit().putString("watchlist_radar", line + (old.isEmpty()?"":" · "+old))
                    .putLong("watchlist_radar_ms", System.currentTimeMillis())
                    .putInt("watchlist_radar_index", idx).apply();
        } catch (Exception ignored) { }
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
                    .putString("bridge_version_snapshot", h.optString("bridge_version", "—"))
                    .putInt("bridge_uptime_sec", h.optInt("uptime_sec", 0))
                    .putLong("bridge_heartbeat", h.optLong("heartbeat", 0L))
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
        if ("H1".equals(tf)) return 300000L;
        if ("H4".equals(tf)) return 900000L;
        if ("D1".equals(tf)) return 1800000L;
        if ("W1".equals(tf)) return 3600000L;
        return 7200000L;
    }

    private String currentSymbol() {
        String explicit = prefs().getString("selected_symbol", "");
        if (explicit != null && !explicit.trim().isEmpty()) return explicit.trim();
        int pos = prefs().getInt("symbol_pos", 0);
        pos = Math.max(0, Math.min(pos, symbols.length - 1));
        return symbols[pos];
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

    private String currentTf() {
        int pos = prefs().getInt("entry_tf_pos", 1);
        String[] values = {"M1", "M5", "M15", "H1", "H4", "D1", "W1", "MN1"};
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

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        super.onTaskRemoved(rootIntent);
        // The service is START_STICKY. Do not start a second service instance from the background.
        // Keeping bg_running=true lets Android recreate the same foreground service if needed.
        if (prefs().getBoolean("bg_running", false) && running) {
            updateNotification(currentSymbol() + " · " + currentTf() + " · " + currentMode(),
                    paused ? "PAUSE · сопровождение активно" : "MONITORING · приложение свернуто",
                    prefs().getString("state_signal", "WAIT"), prefs().getInt("state_quality", -1));
        }
    }

    private void createChannels() {
        if (Build.VERSION.SDK_INT < 26) return;

        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;

        NotificationChannel monitor = new NotificationChannel(
                CHANNEL_MONITOR,
                "FX M1 Bot · мониторинг",
                NotificationManager.IMPORTANCE_HIGH
        );
        monitor.setDescription("Постоянный мониторинг FX M1 Bot: сигнал, MT5, риск и аварийные действия");
        monitor.setShowBadge(false);
        monitor.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        monitor.enableVibration(false);
        monitor.setSound(null, null);

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
        boolean serverConnected = p.getBoolean("server_verified", false);
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
        String market = isForexMarketOpen() ? "MARKET OPEN" : "MARKET CLOSED";
        String qualityText = quality >= 0 ? quality + "/100" : "—";
        String balanceText = Double.isNaN(balance) ? "—" : String.format(Locale.US, "%.2f %s", balance, currency);
        double apiPrice = Double.longBitsToDouble(p.getLong("state_entry_bits", Double.doubleToLongBits(Double.NaN)));
        long updatedMs = p.getLong("state_last_update_ms", 0L);
        String apiText = Double.isNaN(apiPrice) ? "—" : String.format(Locale.US, "%.5f", apiPrice);
        String updatedText = updatedMs > 0L ? new java.text.SimpleDateFormat("HH:mm:ss", Locale.US).format(new Date(updatedMs)) : "—";
        String core = symbol + " · " + tf + " · " + mode + " · " + signal + " · " + qualityText;
        String connection = market + " · " + (serverConnected ? "SERVER CONNECTED" : "SERVER OFFLINE") + " · " + (mt5Connected ? "MT5 CONNECTED" : "MT5 OFFLINE");
        int signalColor = "BUY".equals(signal) ? Color.rgb(66,214,122) : "SELL".equals(signal) ? Color.rgb(255,72,87) : Color.rgb(166,107,255);

        PendingIntent pausePi = serviceActionIntent(paused ? ACTION_RESUME : ACTION_PAUSE, 101);
        PendingIntent emergencyPi = serviceActionIntent(ACTION_EMERGENCY, 102);

        RemoteViews compact = new RemoteViews(getPackageName(), R.layout.notification_monitoring_compact);
        compact.setImageViewResource(R.id.notifLogo, R.drawable.app_icon);
        compact.setTextViewText(R.id.notifTitle, "FX M1 Bot · " + signal);
        compact.setTextViewText(R.id.notifCore, core);
        compact.setTextViewText(R.id.notifConnection, connection);
        compact.setTextViewText(R.id.notifPause, paused ? "▶  PLAY" : "Ⅱ  PAUSE");
        compact.setOnClickPendingIntent(R.id.notifPause, pausePi);
        compact.setOnClickPendingIntent(R.id.notifEmergency, emergencyPi);

        RemoteViews expanded = new RemoteViews(getPackageName(), R.layout.notification_monitoring_expanded);
        expanded.setImageViewResource(R.id.notifLogo, R.drawable.app_icon);
        expanded.setTextViewText(R.id.notifTitle, "FX M1 Bot · " + signal);
        expanded.setTextViewText(R.id.notifCore, core);
        expanded.setTextViewText(R.id.notifAccount, "Баланс (" + accountType + ")\n" + balanceText);
        expanded.setTextViewText(R.id.notifPositions, "Открытые позиции\n" + positions);
        expanded.setTextViewText(R.id.notifRisk, "Риск на сделку\n" + risk + " · AUTO " + (auto ? "ON" : "OFF"));
        expanded.setTextViewText(R.id.notifQuality, "Качество сигнала\n" + qualityText);
        expanded.setProgressBar(R.id.notifQualityBar, 100, Math.max(0, quality), false);
        expanded.setTextViewText(R.id.notifApiPrice, "API Price\n" + apiText);
        expanded.setTextViewText(R.id.notifLastSignal, "Последний анализ\n" + updatedText);
        expanded.setTextViewText(R.id.notifConnection, connection);
        String smart = (p.getBoolean("risk_manager_enabled", true) ? "Risk ON" : "Risk OFF") +
                " · BE " + (p.getBoolean("break_even_enabled", true) ? "ON" : "OFF") +
                " · Trail " + (p.getBoolean("trailing_enabled", true) ? "ON" : "OFF") +
                " · " + FeatureEngine.currentSession();
        expanded.setTextViewText(R.id.notifSmart, smart);
        expanded.setTextViewText(R.id.notifPause, paused ? "▶  PLAY" : "Ⅱ  PAUSE");
        expanded.setOnClickPendingIntent(R.id.notifPause, pausePi);
        expanded.setOnClickPendingIntent(R.id.notifEmergency, emergencyPi);

        Notification.Builder b = new Notification.Builder(this, CHANNEL_MONITOR)
                .setSmallIcon(R.drawable.ic_stat_fx)
                .setColor(signalColor)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setContentTitle("FX M1 Bot · " + signal)
                .setContentText(core)
                .setContentIntent(openAppIntent())
                .setCustomContentView(compact)
                .setCustomBigContentView(expanded)
                .setCustomHeadsUpContentView(compact)
                .addAction(new Notification.Action.Builder(R.drawable.ic_stat_fx, paused ? "PLAY" : "PAUSE", pausePi).build())
                .addAction(new Notification.Action.Builder(R.drawable.ic_stat_fx, "EMERGENCY STOP", emergencyPi).build());
        if (Build.VERSION.SDK_INT >= 24) {
            b.setStyle(new Notification.DecoratedMediaCustomViewStyle().setShowActionsInCompactView(0, 1));
        } else {
            b.setStyle(new Notification.MediaStyle().setShowActionsInCompactView(0, 1));
        }
        if (Build.VERSION.SDK_INT >= 31) b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        if (Build.VERSION.SDK_INT < 26) b.setPriority(Notification.PRIORITY_MAX);
        return b.build();
    }

    private void updateNotification(String title, String text, String signal, int quality) {
        if (!running) return;
        Notification n = buildNotification(title, text, signal, quality);
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else {
                startForeground(NOTIFICATION_ID, n);
            }
        } catch (Exception e) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.notify(NOTIFICATION_ID, n);
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
                URLEncoder.encode(FeatureEngine.analysisSymbol(symbol), "UTF-8") +
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

        return new Analysis(symbol, signal, quality, entry, sl, tp1, tp2, context, why, components);
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
        boolean shouldRemainStarted = prefs().getBoolean("bg_running", false);
        handler.removeCallbacks(tick);
        handler.removeCallbacks(notificationWatchdog);
        running = false;
        executor.shutdownNow();
        super.onDestroy();
        // START_STICKY handles system recreation. We intentionally do not call stopForeground here
        // so an unexpected process death cannot explicitly remove the user's monitoring notification.
        if (!shouldRemainStarted) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.cancel(NOTIFICATION_ID);
        }
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
        final String symbol, signal, context, why, components;
        final int quality;
        final double entry, sl, tp1, tp2;

        Analysis(String symbol, String signal, int quality, double entry, double sl, double tp1, double tp2, String context, String why, String components) {
            this.symbol = symbol;
            this.signal = signal;
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
