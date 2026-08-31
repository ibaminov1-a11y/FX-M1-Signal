package com.openai.fxm1;

import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;

import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.*;

/**
 * V7.1 consolidated smart-trading settings + bridge helpers.
 * Defaults are deliberately conservative and DEMO-first.
 */
public final class FeatureEngine {
    private FeatureEngine() {}

    public static void ensureDefaults(SharedPreferences p) {
        if (p.getBoolean("v71_defaults_done", false)) return;
        p.edit()
                .putBoolean("v71_defaults_done", true)
                .putString("execution_mode", "FULL_AUTO")
                .putBoolean("risk_manager_enabled", true)
                .putFloat("daily_loss_limit_pct", 3.0f)
                .putFloat("max_drawdown_pct", 5.0f)
                .putInt("max_consecutive_losses", 3)
                .putBoolean("break_even_enabled", true)
                .putFloat("break_even_at_r", 1.0f)
                .putBoolean("trailing_enabled", true)
                .putFloat("trailing_start_r", 1.5f)
                .putFloat("trailing_distance_r", 0.8f)
                .putBoolean("partial_close_enabled", true)
                .putFloat("partial_close_at_r", 1.5f)
                .putFloat("partial_close_pct", 50.0f)
                .putBoolean("spread_filter_enabled", true)
                .putFloat("max_spread_pips", 3.0f)
                .putBoolean("confirm_risky_entries", true)
                .putInt("confirm_below_quality", 65)
                .putInt("cooldown_minutes", 10)
                .putBoolean("multi_pair_enabled", false)
                .putString("watchlist", "EUR/USD,GBP/USD,USD/JPY")
                .putString("favorite_symbols", "EUR/USD,GBP/USD,USD/JPY")
                .putBoolean("session_filter_enabled", false)
                .putString("allowed_sessions", "LONDON,NEW_YORK")
                .putBoolean("manual_news_blackout", false)
                .putLong("news_blackout_until_epoch", 0L)
                .putBoolean("position_manager_enabled", true)
                .apply();
    }

    public static JSONObject applySignalFeatures(JSONObject payload, SharedPreferences p, String why, String components) throws Exception {
        payload.put("execution_mode", p.getString("execution_mode", "FULL_AUTO"));
        boolean riskOn = p.getBoolean("risk_manager_enabled", true);
        payload.put("daily_loss_limit_pct", riskOn ? p.getFloat("daily_loss_limit_pct", 3.0f) : 999.0);
        payload.put("max_drawdown_pct", riskOn ? p.getFloat("max_drawdown_pct", 5.0f) : 999.0);
        payload.put("max_consecutive_losses", riskOn ? p.getInt("max_consecutive_losses", 3) : 999);
        payload.put("max_spread_pips", p.getBoolean("spread_filter_enabled", true) ? p.getFloat("max_spread_pips", 3.0f) : 0.0);
        payload.put("confirm_risky_entries", p.getBoolean("confirm_risky_entries", true));
        payload.put("confirm_below_quality", p.getInt("confirm_below_quality", 65));
        payload.put("cooldown_sec", Math.max(0, p.getInt("cooldown_minutes", 10)) * 60);
        payload.put("news_blackout_until_epoch", p.getBoolean("manual_news_blackout", false) ? p.getLong("news_blackout_until_epoch", 0L) : 0L);
        payload.put("why", why == null ? "" : why);
        payload.put("components", components == null ? "" : components);
        payload.put("session", currentSession());
        return payload;
    }

    public static JSONObject managePayload(SharedPreferences p) throws Exception {
        JSONObject o = new JSONObject();
        o.put("break_even_enabled", p.getBoolean("break_even_enabled", true));
        o.put("break_even_at_r", p.getFloat("break_even_at_r", 1.0f));
        o.put("trailing_enabled", p.getBoolean("trailing_enabled", true));
        o.put("trailing_start_r", p.getFloat("trailing_start_r", 1.5f));
        o.put("trailing_distance_r", p.getFloat("trailing_distance_r", 0.8f));
        o.put("partial_close_enabled", p.getBoolean("partial_close_enabled", true));
        o.put("partial_close_at_r", p.getFloat("partial_close_at_r", 1.5f));
        o.put("partial_close_pct", p.getFloat("partial_close_pct", 50.0f));
        return o;
    }

    public static String featureSummary(SharedPreferences p) {
        long newsUntil = p.getLong("news_blackout_until_epoch", 0L);
        boolean newsActive = p.getBoolean("manual_news_blackout", false) && newsUntil > System.currentTimeMillis() / 1000L;
        return "Режим: " + p.getString("execution_mode", "FULL_AUTO") +
                "\nRisk Manager: " + onOff(p.getBoolean("risk_manager_enabled", true)) +
                " · день " + fmt1(p.getFloat("daily_loss_limit_pct", 3.0f)) + "%" +
                " · DD " + fmt1(p.getFloat("max_drawdown_pct", 5.0f)) + "%" +
                " · серия " + p.getInt("max_consecutive_losses", 3) +
                "\nBE: " + onOff(p.getBoolean("break_even_enabled", true)) + " @ " + fmt1(p.getFloat("break_even_at_r", 1.0f)) + "R" +
                " · Trailing: " + onOff(p.getBoolean("trailing_enabled", true)) + " @ " + fmt1(p.getFloat("trailing_start_r", 1.5f)) + "R" +
                "\nPartial: " + onOff(p.getBoolean("partial_close_enabled", true)) + " " + fmt0(p.getFloat("partial_close_pct", 50.0f)) + "% @ " + fmt1(p.getFloat("partial_close_at_r", 1.5f)) + "R" +
                "\nSpread: " + onOff(p.getBoolean("spread_filter_enabled", true)) + " ≤ " + fmt1(p.getFloat("max_spread_pips", 3.0f)) + " pips" +
                " · Cooldown: " + p.getInt("cooldown_minutes", 10) + " мин" +
                "\nRisky confirm: " + onOff(p.getBoolean("confirm_risky_entries", true)) + " < " + p.getInt("confirm_below_quality", 65) + "/100" +
                " · Session: " + currentSession() +
                "\nMulti-pair radar: " + onOff(p.getBoolean("multi_pair_enabled", false)) +
                " · News Guard: " + (newsActive ? "ACTIVE" : "READY");
    }

    public static String currentSession() {
        Calendar utc = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        int h = utc.get(Calendar.HOUR_OF_DAY);
        // Simple session labels for situational awareness, not broker trading hours.
        if (h >= 0 && h < 7) return "ASIA";
        if (h >= 7 && h < 12) return "LONDON";
        if (h >= 12 && h < 16) return "LONDON+NEW_YORK";
        if (h >= 16 && h < 21) return "NEW_YORK";
        return "OFF_HOURS";
    }

    public static void appendSignalHistory(SharedPreferences p, String symbol, String tf, String signal, int quality, String result) {
        String old = p.getString("signal_history", "");
        String ts = new SimpleDateFormat("dd.MM HH:mm:ss", Locale.US).format(new Date());
        String line = ts + " · " + symbol + " · " + tf + " · " + signal + " " + quality + "/100" + (result == null || result.isEmpty() ? "" : " · " + result);
        String merged = line + (old.trim().isEmpty() ? "" : "\n" + old);
        String[] rows = merged.split("\\n");
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < Math.min(40, rows.length); i++) {
            if (i > 0) out.append('\n');
            out.append(rows[i]);
        }
        p.edit().putString("signal_history", out.toString()).apply();
    }

    public static String watchlist(SharedPreferences p) {
        return p.getString("watchlist", "EUR/USD,GBP/USD,USD/JPY");
    }

    public static List<String> watchlistItems(SharedPreferences p) {
        ArrayList<String> out = new ArrayList<>();
        for (String s : watchlist(p).split(",")) {
            String v = s.trim();
            if (!v.isEmpty() && !out.contains(v)) out.add(v);
        }
        return out;
    }

    public static String analysisSymbol(String raw) {
        String v = raw == null ? "" : raw.trim().toUpperCase(Locale.US);
        if (v.isEmpty()) return v;
        // Broker symbols often look like EURUSD, EURUSD.a or XAUUSDm.
        // Twelve Data FX/metal endpoints are more reliable with AAA/BBB form.
        String letters = v.replaceAll("[^A-Z]", "");
        if (letters.length() >= 6) {
            String six = letters.substring(0, 6);
            String a = six.substring(0, 3);
            String b = six.substring(3, 6);
            Set<String> ccy = new HashSet<>(Arrays.asList(
                    "USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD","XAU","XAG"));
            if (ccy.contains(a) && ccy.contains(b)) return a + "/" + b;
        }
        return v;
    }

    public static List<String> favoriteItems(SharedPreferences p) {
        String raw = p.getString("favorite_symbols", watchlist(p));
        ArrayList<String> out = new ArrayList<>();
        for (String s : raw.split(",")) {
            String v = s.trim();
            if (!v.isEmpty() && !out.contains(v)) out.add(v);
        }
        return out;
    }

    public static JSONObject httpJson(String method, String url, JSONObject payload) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setConnectTimeout(8000);
        conn.setReadTimeout(12000);
        conn.setRequestMethod(method);
        conn.setRequestProperty("Accept", "application/json");
        if (payload != null) {
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (OutputStream os = conn.getOutputStream()) {
                os.write(payload.toString().getBytes(StandardCharsets.UTF_8));
            }
        }
        int code = conn.getResponseCode();
        InputStream is = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
        String body = readAll(is);
        if (code < 200 || code >= 300) throw new Exception("HTTP " + code + ": " + body);
        return new JSONObject(body);
    }

    public static String formatStats(JSONObject s) {
        if (s == null) return "Статистика недоступна";
        JSONObject x = s.optJSONObject("stats");
        if (x == null) x = s;
        return "Сделок: " + x.optInt("closed_trades", x.optInt("trades", 0)) +
                " · Win rate: " + String.format(Locale.US, "%.1f%%", x.optDouble("win_rate_pct", x.optDouble("win_rate", 0))) +
                "\nNet P/L: " + String.format(Locale.US, "%+.2f", x.optDouble("net_pl", x.optDouble("net_profit", 0))) +
                " · PF: " + String.format(Locale.US, "%.2f", x.optDouble("profit_factor", 0)) +
                "\nAvg: " + String.format(Locale.US, "%+.2f", x.optDouble("avg_trade", 0)) +
                " · Avg win: " + String.format(Locale.US, "%+.2f", x.optDouble("avg_win", 0)) +
                " · Avg loss: " + String.format(Locale.US, "%+.2f", x.optDouble("avg_loss", 0)) +
                "\nMax DD: " + String.format(Locale.US, "%.2f", x.optDouble("max_closed_drawdown", 0)) +
                " · Сегодня: " + String.format(Locale.US, "%+.2f", x.optDouble("daily_realized_pl", 0)) +
                " · Loss streak: " + x.optInt("max_consecutive_losses", x.optInt("consecutive_losses", 0));
    }

    public static String formatTradeLog(JSONObject root) {
        JSONArray arr = root == null ? null : root.optJSONArray("events");
        if (arr == null && root != null) arr = root.optJSONArray("deals");
        if (arr == null || arr.length() == 0) return "ТОРГОВЫЙ ЖУРНАЛ: пока пусто";
        StringBuilder sb = new StringBuilder("ТОРГОВЫЙ ЖУРНАЛ");
        SimpleDateFormat f = new SimpleDateFormat("dd.MM HH:mm:ss", Locale.US);
        for (int i = 0; i < Math.min(arr.length(), 10); i++) {
            JSONObject e = arr.optJSONObject(i);
            if (e == null) continue;
            long ts = e.optLong("ts", 0L);
            String event = e.optString("event", "event");
            sb.append("\n").append(ts > 0 ? f.format(new Date(ts * 1000L)) : "—")
                    .append(" · ").append(event);
            if (e.has("symbol")) sb.append(" · ").append(e.optString("symbol"));
            if (e.has("ticket")) sb.append(" #").append(e.optLong("ticket"));
            if (e.has("reason")) sb.append(" · ").append(e.optString("reason"));
            if (e.has("message")) sb.append(" · ").append(e.optString("message"));
            if (e.has("slippage_pips") && !e.isNull("slippage_pips")) {
                sb.append(" · slip ").append(String.format(Locale.US, "%.2f p", e.optDouble("slippage_pips", 0)));
            }
        }
        return sb.toString();
    }

    public static String formatPositions(JSONObject root) {
        JSONArray arr = root == null ? null : root.optJSONArray("positions");
        if (arr == null || arr.length() == 0) return "Нет открытых позиций";

        double totalLot = 0.0;
        double floating = 0.0;
        double weightedOpen = 0.0;
        String basketSymbol = "";
        String basketSide = "";
        boolean sameBasket = true;

        for (int i = 0; i < arr.length(); i++) {
            JSONObject p = arr.optJSONObject(i);
            if (p == null) continue;
            double v = p.optDouble("volume", 0);
            totalLot += v;
            floating += p.optDouble("profit", 0);
            weightedOpen += p.optDouble("open_price", 0) * v;
            String sym = p.optString("symbol");
            String side = p.optString("side");
            if (basketSymbol.isEmpty()) { basketSymbol = sym; basketSide = side; }
            else if (!basketSymbol.equals(sym) || !basketSide.equals(side)) sameBasket = false;
        }

        StringBuilder sb = new StringBuilder();
        sb.append("Открыто: ").append(arr.length())
                .append(" · Total lot: ").append(String.format(Locale.US, "%.2f", totalLot))
                .append(" · P/L ").append(String.format(Locale.US, "%+.2f", floating));
        if (sameBasket && totalLot > 0) {
            sb.append("\nSCALP basket: ").append(basketSymbol).append(' ').append(basketSide)
                    .append(" · Avg ").append(String.format(Locale.US, "%.5f", weightedOpen / totalLot));
        }

        for (int i = 0; i < arr.length(); i++) {
            JSONObject p = arr.optJSONObject(i);
            if (p == null) continue;
            sb.append('\n').append(i + 1).append(") #").append(p.optLong("ticket"))
                    .append(" · ").append(p.optString("symbol"))
                    .append(" · ").append(p.optString("side"))
                    .append(" · ").append(String.format(Locale.US, "%.2f lot", p.optDouble("volume", 0)))
                    .append(" · P/L ").append(String.format(Locale.US, "%+.2f", p.optDouble("profit", 0)));
        }
        return sb.toString();
    }

    private static String readAll(InputStream is) throws IOException {
        if (is == null) return "";
        BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line);
        return sb.toString();
    }

    private static String onOff(boolean b) { return b ? "ON" : "OFF"; }
    private static String fmt1(float v) { return String.format(Locale.US, "%.1f", v); }
    private static String fmt0(float v) { return String.format(Locale.US, "%.0f", v); }
}
