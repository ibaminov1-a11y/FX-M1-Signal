package com.openai.fxm1;

import android.app.Activity;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.view.View;
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

        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, symbols);
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

        getSharedPreferences("fxm1", MODE_PRIVATE).edit().putString("apikey", key).apply();

        analyzeButton.setEnabled(false);
        statusText.setText("Загружаю M1 / M5 / M15 / H1…");
        signalText.setText("…");
        confidenceText.setText("Анализ рынка");

        executor.execute(() -> {
            try {
                List<Candle> m1 = fetch(symbol, "1min", key, 120);
                List<Candle> m5 = fetch(symbol, "5min", key, 100);
                List<Candle> m15 = fetch(symbol, "15min", key, 100);
                List<Candle> h1 = fetch(symbol, "1h", key, 100);

                Analysis a = analyze(symbol, m1, m5, m15, h1);
                runOnUiThread(() -> showAnalysis(a));
            } catch (Exception e) {
                runOnUiThread(() -> {
                    analyzeButton.setEnabled(true);
                    signalText.setText("ERROR");
                    signalText.setTextColor(Color.DKGRAY);
                    statusText.setText("Ошибка: " + e.getMessage());
                    confidenceText.setText("Проверьте API key и интернет.");
                    levelsText.setText("Entry: —\nSL: —\nTP1: —\nTP2: —");
                });
            }
        });
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
            throw new Exception(root.optString("message", "API error"));
        }
        JSONArray vals = root.optJSONArray("values");
        if (vals == null || vals.length() < 30) {
            throw new Exception("Недостаточно свечей для " + interval);
        }

        List<Candle> list = new ArrayList<>();
        // API отдаёт последние свечи сверху; переворачиваем в хронологический порядок.
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
        BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line);
        return sb.toString();
    }

    private Analysis analyze(String symbol, List<Candle> m1, List<Candle> m5,
                             List<Candle> m15, List<Candle> h1) {

        int sH1 = trendScore(h1);
        int sM15 = trendScore(m15);
        int sM5 = trendScore(m5);
        int sM1 = trendScore(m1);
        int structure = structureScore(m1);
        int breakout = breakoutScore(m1);

        int raw = sH1 * 9 + sM15 * 8 + sM5 * 7 + sM1 * 8 + structure * 10 + breakout * 12;

        String signal = raw > 16 ? "BUY" : raw < -16 ? "SELL" : "WAIT";
        int confidence = Math.max(50, Math.min(88, 50 + (int)(Math.abs(raw) * 0.85)));

        Candle last = m1.get(m1.size() - 1);
        double entry = last.close;
        double atr = atr(m1, 14);
        if (atr <= 0) atr = Math.max(0.0001, last.high - last.low);

        double slDist = atr * 1.2;
        double sl = 0, tp1 = 0, tp2 = 0;

        if ("BUY".equals(signal)) {
            sl = entry - slDist;
            tp1 = entry + slDist;
            tp2 = entry + slDist * 1.8;
        } else if ("SELL".equals(signal)) {
            sl = entry + slDist;
            tp1 = entry - slDist;
            tp2 = entry - slDist * 1.8;
        }

        String reason = breakout > 0 ? "M1: пробой/импульс вверх"
                : breakout < 0 ? "M1: пробой/импульс вниз"
                : "M1: чистого пробоя нет";

        String context = "H1 " + arrow(sH1) +
                "   M15 " + arrow(sM15) +
                "   M5 " + arrow(sM5) +
                "   M1 " + arrow(sM1) +
                "\nСтруктура M1: " + arrow(structure) +
                "\n" + reason;

        return new Analysis(symbol, signal, confidence, entry, sl, tp1, tp2, context);
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

        if (last.close > resistance) return body > a * 0.35 ? 2 : 1;
        if (last.close < support) return body > a * 0.35 ? -2 : -1;
        return 0;
    }

    private double atr(List<Candle> c, int period) {
        if (c.size() < period + 1) return 0;
        double sum = 0;
        int start = c.size() - period;
        for (int i = start; i < c.size(); i++) {
            Candle cur = c.get(i);
            Candle prev = c.get(i - 1);
            double tr = Math.max(cur.high - cur.low,
                    Math.max(Math.abs(cur.high - prev.close), Math.abs(cur.low - prev.close)));
            sum += tr;
        }
        return sum / period;
    }

    private String arrow(int s) {
        return s > 0 ? "↑" : s < 0 ? "↓" : "→";
    }

    private void showAnalysis(Analysis a) {
        analyzeButton.setEnabled(true);
        statusText.setText(a.symbol + " · данные Twelve Data");
        signalText.setText(a.signal);

        if ("BUY".equals(a.signal)) signalText.setTextColor(Color.rgb(20, 120, 70));
        else if ("SELL".equals(a.signal)) signalText.setTextColor(Color.rgb(190, 45, 45));
        else signalText.setTextColor(Color.DKGRAY);

        confidenceText.setText("Уверенность модели: " + a.confidence + "%");

        if ("WAIT".equals(a.signal)) {
            levelsText.setText("Entry: " + fmt(a.entry) +
                    "\nSL: —\nTP1: —\nTP2: —");
        } else {
            levelsText.setText("Entry: " + fmt(a.entry) +
                    "\nSL: " + fmt(a.sl) +
                    "\nTP1: " + fmt(a.tp1) +
                    "\nTP2: " + fmt(a.tp2));
        }
        contextText.setText(a.context);
    }

    private String fmt(double x) {
        if (x == 0) return "—";
        if (x >= 100) return String.format(Locale.US, "%.3f", x);
        return String.format(Locale.US, "%.5f", x);
    }

    static class Candle {
        final double open, high, low, close;
        Candle(double open, double high, double low, double close) {
            this.open = open; this.high = high; this.low = low; this.close = close;
        }
    }

    static class Analysis {
        final String symbol, signal, context;
        final int confidence;
        final double entry, sl, tp1, tp2;
        Analysis(String symbol, String signal, int confidence, double entry,
                 double sl, double tp1, double tp2, String context) {
            this.symbol = symbol; this.signal = signal; this.confidence = confidence;
            this.entry = entry; this.sl = sl; this.tp1 = tp1; this.tp2 = tp2;
            this.context = context;
        }
    }
}