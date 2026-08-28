package com.openai.fxm1;

import android.Manifest;
import android.app.*;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.IBinder;
import android.util.Base64;

import org.json.JSONObject;

import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class JarvisVoiceService extends Service {

    public static final String ACTION_TALK = "com.openai.fxm1.action.JARVIS_TALK";
    public static final String ACTION_STOP = "com.openai.fxm1.action.JARVIS_STOP";

    private static final String CHANNEL_ID = "jarvis_voice";
    private static final int NOTIFICATION_ID = 2402;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private MediaRecorder recorder;
    private MediaPlayer player;
    private File audioFile;
    private volatile boolean recording = false;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? ACTION_TALK : intent.getAction();

        if (ACTION_STOP.equals(action)) {
            stopEverything();
            stopSelf();
            return START_NOT_STICKY;
        }

        startForeground(NOTIFICATION_ID, buildNotification("JARVIS · готовлю микрофон…", true));

        if (Build.VERSION.SDK_INT >= 23 &&
                checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            updateNotification("JARVIS · нет разрешения на микрофон", false);
            stopSelf();
            return START_NOT_STICKY;
        }

        String server = normalizeServerUrl(prefs().getString("server_url", ""));
        if (server.isEmpty()) {
            updateNotification("JARVIS · AI-сервер не настроен", false);
            stopSelf();
            return START_NOT_STICKY;
        }

        beginRecording();
        return START_NOT_STICKY;
    }

    private void beginRecording() {
        try {
            audioFile = new File(getCacheDir(), "jarvis_bg_" + System.currentTimeMillis() + ".m4a");
            recorder = new MediaRecorder();
            recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            recorder.setAudioEncodingBitRate(64000);
            recorder.setAudioSamplingRate(16000);
            recorder.setOutputFile(audioFile.getAbsolutePath());
            recorder.prepare();
            recorder.start();
            recording = true;

            updateNotification("JARVIS · слушаю… говорите сейчас", true);

            new android.os.Handler(getMainLooper()).postDelayed(() -> {
                if (recording) stopRecordingAndSend();
            }, 6500L);

        } catch (Exception e) {
            updateNotification("JARVIS · ошибка микрофона", false);
            stopEverything();
            stopSelf();
        }
    }

    private void stopRecordingAndSend() {
        recording = false;
        try { recorder.stop(); } catch (Exception ignored) { }
        try { recorder.release(); } catch (Exception ignored) { }
        recorder = null;

        if (audioFile == null || !audioFile.exists() || audioFile.length() < 512L) {
            updateNotification("JARVIS · речь не записана", false);
            stopSelf();
            return;
        }

        updateNotification("JARVIS · распознаю и думаю…", true);

        executor.execute(() -> {
            try {
                String server = normalizeServerUrl(prefs().getString("server_url", ""));
                JSONObject response = postVoice(
                        server + "/voice",
                        audioFile,
                        prefs().getString("jarvis_bg_session", UUID.randomUUID().toString()),
                        buildContext()
                );

                String transcript = response.optString("transcript", "").trim();
                String reply = response.optString("reply", "").trim();
                String audioB64 = response.optString("audio_base64", null);

                prefs().edit()
                        .putString("jarvis_last_transcript", transcript)
                        .putString("jarvis_last_reply", reply)
                        .apply();

                if (!prefs().getBoolean("jarvis_muted", false) &&
                        audioB64 != null && !audioB64.isEmpty()) {
                    updateNotification("JARVIS · отвечаю…", true);
                    playBase64(audioB64, reply);
                } else {
                    updateNotification(reply.isEmpty() ? "JARVIS · ответ готов" : "JARVIS · " + shortText(reply), false);
                    stopSelf();
                }

            } catch (Exception e) {
                updateNotification("JARVIS · AI-сервер недоступен", false);
                stopSelf();
            } finally {
                try { audioFile.delete(); } catch (Exception ignored) { }
            }
        });
    }

    private JSONObject buildContext() throws Exception {
        SharedPreferences p = prefs();
        JSONObject c = new JSONObject();
        c.put("symbol", p.getString("state_symbol", ""));
        c.put("entry_timeframe", p.getString("state_tf", ""));
        c.put("signal", p.getString("state_signal", "WAIT"));
        c.put("quality", p.getInt("state_quality", -1));
        c.put("market_context", p.getString("state_context", ""));
        c.put("background_running", p.getBoolean("bg_running", false));
        c.put("monitoring_running", p.getBoolean("ui_monitoring", false));
        c.put("auto_trading", p.getBoolean("auto_trading", false));
        return c;
    }

    private void playBase64(String b64, String reply) throws Exception {
        byte[] audio = Base64.decode(b64, Base64.DEFAULT);
        File out = new File(getCacheDir(), "jarvis_reply_" + System.currentTimeMillis() + ".mp3");
        try (FileOutputStream fos = new FileOutputStream(out)) { fos.write(audio); }

        player = new MediaPlayer();
        player.setAudioAttributes(new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build());
        player.setDataSource(out.getAbsolutePath());
        player.setOnCompletionListener(mp -> {
            try { out.delete(); } catch (Exception ignored) { }
            updateNotification(reply.isEmpty() ? "JARVIS · готов" : "JARVIS · " + shortText(reply), false);
            stopSelf();
        });
        player.prepare();
        player.start();
    }

    private JSONObject postVoice(String urlString, File file, String sessionId, JSONObject context) throws Exception {
        String boundary = "----FXM1BG" + System.currentTimeMillis();
        HttpURLConnection conn = (HttpURLConnection) new URL(urlString).openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(90000);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);

        try (DataOutputStream out = new DataOutputStream(conn.getOutputStream())) {
            writeText(out, boundary, "session_id", sessionId);
            writeText(out, boundary, "context", context.toString());

            out.writeBytes("--" + boundary + "\r\n");
            out.writeBytes("Content-Disposition: form-data; name=\"audio\"; filename=\"voice.m4a\"\r\n");
            out.writeBytes("Content-Type: audio/mp4\r\n\r\n");
            try (FileInputStream in = new FileInputStream(file)) {
                byte[] buffer = new byte[8192];
                int n;
                while ((n = in.read(buffer)) != -1) out.write(buffer, 0, n);
            }
            out.writeBytes("\r\n--" + boundary + "--\r\n");
            out.flush();
        }

        int code = conn.getResponseCode();
        InputStream input = code >= 200 && code < 300 ? conn.getInputStream() : conn.getErrorStream();
        String body = readAll(input);
        conn.disconnect();

        JSONObject obj = new JSONObject(body);
        if (code < 200 || code >= 300 || !obj.optBoolean("ok", false)) {
            throw new Exception(obj.optString("error", "HTTP " + code));
        }
        return obj;
    }

    private void writeText(DataOutputStream out, String boundary, String name, String value) throws Exception {
        out.writeBytes("--" + boundary + "\r\n");
        out.writeBytes("Content-Disposition: form-data; name=\"" + name + "\"\r\n");
        out.writeBytes("Content-Type: text/plain; charset=UTF-8\r\n\r\n");
        out.write(value.getBytes(StandardCharsets.UTF_8));
        out.writeBytes("\r\n");
    }

    private String readAll(InputStream in) throws Exception {
        if (in == null) return "";
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) != -1) b.write(buf, 0, n);
        return b.toString("UTF-8");
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("fxm1", MODE_PRIVATE);
    }

    private String normalizeServerUrl(String raw) {
        if (raw == null) return "";
        String s = raw.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        if (!s.isEmpty() && !s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        return s;
    }

    private void stopEverything() {
        recording = false;
        if (recorder != null) {
            try { recorder.stop(); } catch (Exception ignored) { }
            try { recorder.release(); } catch (Exception ignored) { }
            recorder = null;
        }
        if (player != null) {
            try { player.stop(); } catch (Exception ignored) { }
            try { player.release(); } catch (Exception ignored) { }
            player = null;
        }
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;
        NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "JARVIS voice", NotificationManager.IMPORTANCE_LOW);
        ch.setDescription("Голосовой разговор с JARVIS без открытия приложения");
        nm.createNotificationChannel(ch);
    }

    private Notification buildNotification(String text, boolean ongoing) {
        Intent stop = new Intent(this, JarvisVoiceService.class);
        stop.setAction(ACTION_STOP);
        PendingIntent stopPi = PendingIntent.getService(
                this, 801, stop, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent openPi = PendingIntent.getActivity(
                this, 802, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle("JARVIS")
                .setContentText(text)
                .setOngoing(ongoing)
                .setOnlyAlertOnce(true)
                .setContentIntent(openPi)
                .addAction(android.R.drawable.ic_media_pause, "СТОП", stopPi)
                .build();
    }

    private void updateNotification(String text, boolean ongoing) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) nm.notify(NOTIFICATION_ID, buildNotification(text, ongoing));
    }

    private String shortText(String s) {
        String t = s.replace("\n", " ").trim();
        return t.length() > 52 ? t.substring(0, 52) + "…" : t;
    }

    @Override
    public void onDestroy() {
        stopEverything();
        executor.shutdownNow();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
