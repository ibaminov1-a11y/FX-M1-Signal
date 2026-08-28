package com.openai.fxm1;

import android.app.Activity;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.SystemClock;
import android.widget.*;
import org.json.JSONArray;
import org.json.JSONObject;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {

    private Spinner symbolSpinner;
    private EditText apiKeyInput;
    private TextView statusText, signalText, confidenceText, levelsText, contextText;
    private Button analyzeButton, saveKeyButton;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    private static final long BUTTON_COOLDOWN_MS = 15000L;
    private static final long CACHE_M1_MS = 15000L;
    private static final long CACHE_M5_MS = 2 * 60 * 1000L;
    private static final long CACHE_M15_MS = 7 * 60 * 1000L;
    private static final long CACHE_H1_MS = 30 * 60 * 1000L;

    private long lastAnalyzeClickMs = 0L;

    private final Map<String, CacheItem> cache = new HashMap<>();

    private final String[] symbols = {
            "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
            "EUR/JPY", "GBP/JPY", "EUR/GBP", "EUR/CHF", "AUD/JPY", "CAD/JPY", "CHF/JPY",
            "GBP/CHF", "EUR/AUD", "GBP/AUD", "AUD/NZD", "NZD/JPY", "XAU/USD"
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        symbolSpinner = findViewById(R.id.symbolSpinner);
        apiKeyInput = findViewById(R.id.apiKeyInput);
        statusText = findViewById(R.id.statusText);
        signalText = findViewById(R.id.signalText);
        confidenceText = findViewById(R.id.confidenceText);
        levelsText = findViewById(R.id.levelsText);
        contextText = findViewById(R.id.contextText);
        analyzeButton = findViewById(R.id.analyzeButton);
        saveKeyButton = findViewById(R.id.saveKeyButton);

        ArrayAdapter<String> adapter = new ArrayAdapter<>(
                this,
                android.R.layout.simple_spinner_dropdown_item,
                symbols
        );
        symbolSpinner.setAdapter(adapter);

        SharedPreferences prefs = getSharedPreferences("fxm1", MODE_PRIVATE);
        apiKeyInput.setText(prefs.getString("apikey", ""));

        saveKeyButton.setOnClickListener(v -> {
            String key = apiKeyInput.getText().toString().trim();
            prefs.edit().putString("apikey", key).apply();
            Toast.makeText(this, "API key сохранён", Toast.LENGTH_SHORT).show();
        });

        analyzeButton.setOnClickListener(v -> runAnalysis());
    }

    private void runAnalysis() {
        final String key = apiKeyInput.getText().toString().trim();
        final String symbol = (String) symbolSpinner.getSelectedItem();

        if (key.isEmpty()) {
            Toast.makeText(this, "Сначала вставьте Twelve Data API key", Toast.LENGTH_LONG).show();
            return;
        }

        long now = SystemClock.elapsedRealtime();
        long elapsed = now - lastAnalyzeClickMs;

        if (lastAnalyzeClickMs > 0 && elapsed < BUTTON_COOLDOWN_MS) {
            long seconds = (BUTTON_COOLDOWN_MS - elapsed + 999) / 1000;
            Toast.makeText(
                    this,
                    "Подождите " + seconds + " сек. перед повторным анализом",
                    Toast.LENGTH_SHORT
            ).show();
            return;
        }

        lastAnalyzeClickMs = now;

        getSharedPreferences("fxm1", MODE_PRIVATE)
                .edit()
                .putString("apikey", key)
                .apply();

        analyzeButton.setEnabled(false);
        statusText.setText("Обновляю рынок…");
        signalText.setText("…");
        confidenceText.setText("Анализ рынка");

        executor.execute(() -> {
            try {
                FetchResult r1 = getSeries(symbol, "1min", key, 120, CACHE_M1_MS);
                FetchResult r5 = getSeries(symbol, "5min", key, 100, CACHE_M5_MS);
                FetchResult r15 = getSeries(symbol, "15min", key, 100, CACHE_M15_MS);
                FetchResult r60 = getSeries(symbol, "1h", key, 100, CACHE_H1_MS);

                Analysis a = analyze(
                        symbol,
                        r1.data,
                        r5.data,
                        r15.data,
                        r60.data
                );

                int freshRequests =
                        (r1.fromCache ? 0 : 1) +
                        (r5.fromCache ? 0 : 1) +
                        (r15.fromCache ? 0 : 1) +
                        (r60.fromCache ? 0 : 1);

                int cachedRequests = 4 - freshRequests;

                runOnUiThread(() ->
                        showAnalysis(a, freshRequests, cachedRequests)
                );

            } catch (RateLimitException e) {
                runOnUiThread(() -> {
                    analyzeButton.setEnabled(true);
                    signalText.setText("WAIT");
                    signalText.setTextColor(Color.DKGRAY);
                    statusText.setText("Лимит Twelve Data на эту минуту исчерпан.");
                    confidenceText.setText("Подождите около 60 секунд и повторите.");
                    levelsText.setText("Entry: —\nSL: —\nTP1: —\nTP2: —");
                    contextText.setText(
                            "Приложение работает нормально.\n" +
                            "Сработало ограничение бесплатного API."
                    );
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    analyzeButton.setEnabled(true);
                    signalText.setText("ERROR");
                    signalText.setTextColor(Color.DKGRAY);
                    statusText.setText("Ошибка: " + safeMessage(e));
                    confidenceText.setText("Проверьте интернет и API key.");
                    levelsText.setText("Entry: —\nSL: —\nTP1: —\nTP2: —");
                });
            }
        });
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

            if (message.toLowerCase(Locale.US).contains("api credits") ||
                    message.toLowerCase(Locale.US).contains("current minute") ||
                    message.toLowerCase(Locale.US).contains("rate limit")) {
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
        return m == null || m.trim().isEmpty() ? "неизвестная ошибка" : m;
    }

    private Analysis analyze(String symbol,
                             List<Candle> m1,
                             List<Candle> m5,
                             List<Candle> m15,
                             List<Candle> h1) {

        int sH1 = trendScore(h1);
        int sM15 = trendScore(m15);
        int sM5 = trendScore(m5);
        int sM1 = trendScore(m1);
        int structure = structureScore(m1);
        int breakout = breakoutScore(m1);

        Candle last = m1.get(m1.size() - 1);
        double entry = last.close;
        double atr = atr(m1, 14);

        if (atr <= 0) {
            atr = Math.max(minStopDistance(symbol), last.high - last.low);
        }

        boolean buySetup =
                sH1 >= 0 &&
                sM15 >= 0 &&
                sM5 > 0 &&
                sM1 > 0 &&
                structure >= 0 &&
                breakout > 0;

        boolean sellSetup =
                sH1 <= 0 &&
                sM15 <= 0 &&
                sM5 < 0 &&
                sM1 < 0 &&
                structure <= 0 &&
                breakout < 0;

        String signal = buySetup ? "BUY" : sellSetup ? "SELL" : "WAIT";

        int quality = setupQuality(
                signal,
                sH1,
                sM15,
                sM5,
                sM1,
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
            reason = "M1: подтверждён пробой/импульс вверх";
        } else if (breakout < 0) {
            reason = "M1: подтверждён пробой/импульс вниз";
        } else {
            reason = "M1: подтверждённого пробоя нет";
        }

        String filter;

        if ("BUY".equals(signal)) {
            filter = "Фильтр: старшие ТФ не против BUY";
        } else if ("SELL".equals(signal)) {
            filter = "Фильтр: старшие ТФ не против SELL";
        } else {
            filter = "Фильтр: условия для входа не совпали";
        }

        String context =
                "H1 " + arrow(sH1) +
                "   M15 " + arrow(sM15) +
                "   M5 " + arrow(sM5) +
                "   M1 " + arrow(sM1) +
                "\nСтруктура M1: " + arrow(structure) +
                "\n" + reason +
                "\n" + filter +
                "\nATR M1: " + fmt(atr);

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

    private int setupQuality(String signal,
                             int h1,
                             int m15,
                             int m5,
                             int m1,
                             int structure,
                             int breakout) {

        if ("WAIT".equals(signal)) {
            int alignment = Math.abs(h1 + m15 + m5 + m1);
            int q = 25 + alignment * 7;

            if (structure != 0) q += 5;
            if (breakout != 0) q += 8;

            return Math.min(59, q);
        }

        int direction = "BUY".equals(signal) ? 1 : -1;
        int q = 60;

        if (h1 == direction) q += 8;
        if (m15 == direction) q += 8;
        if (m5 == direction) q += 6;
        if (m1 == direction) q += 6;
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

        int s = ema9 > ema21 ? 1 : ema9 < ema21 ? -1 : 0;

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

        if (n < 10) {
            return 0;
        }

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

        if (n < 30) {
            return 0;
        }

        Candle last = c.get(n - 1);
        double resistance = -Double.MAX_VALUE;
        double support = Double.MAX_VALUE;

        for (int i = n - 22; i < n - 2; i++) {
            resistance = Math.max(resistance, c.get(i).high);
            support = Math.min(support, c.get(i).low);
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
        if (c.size() < period + 1) {
            return 0;
        }

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
        return s > 0 ? "↑" : s < 0 ? "↓" : "→";
    }

    private void showAnalysis(Analysis a,
                              int freshRequests,
                              int cachedRequests) {

        analyzeButton.setEnabled(true);

        statusText.setText(
                a.symbol +
                " · Twelve Data · API " +
                freshRequests +
                " · кэш " +
                cachedRequests
        );

        signalText.setText(a.signal);

        if ("BUY".equals(a.signal)) {
            signalText.setTextColor(Color.rgb(20, 120, 70));
        } else if ("SELL".equals(a.signal)) {
            signalText.setTextColor(Color.rgb(190, 45, 45));
        } else {
            signalText.setTextColor(Color.DKGRAY);
        }

        confidenceText.setText(
                "Качество сетапа: " + a.quality + "/100"
        );

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
    }

    private String fmt(double x) {
        if (x == 0) {
            return "—";
        }

        if (x >= 100) {
            return String.format(Locale.US, "%.3f", x);
        }

        return String.format(Locale.US, "%.5f", x);
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
