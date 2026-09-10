package com.openai.fxm1;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;

final class V11Api {
    static SharedPreferences prefs(Context c) { return c.getSharedPreferences("fxm1_v11", Context.MODE_PRIVATE); }
    static JSONObject state(Context c) {
        try { return new JSONObject(prefs(c).getString("state", "{}")); }
        catch(Exception e) { return new JSONObject(); }
    }
    static JSONObject request(Context c, String method, String path, JSONObject body) throws Exception {
        SharedPreferences p=prefs(c);
        String base=p.getString("server", "").trim().replaceAll("/+$", "");
        String token=p.getString("token", "").trim();
        if(base.isEmpty() || token.length()<20) throw new IOException("Укажите адрес и ключ Bridge V11 в настройках");
        URI uri=new URI(base);
        if (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost()==null || uri.getUserInfo()!=null)
            throw new IOException("Некорректный адрес Bridge");
        HttpURLConnection conn=(HttpURLConnection)new URL(base+path).openConnection();
        conn.setConnectTimeout(4500); conn.setReadTimeout(4500); conn.setRequestMethod(method);
        conn.setRequestProperty("Authorization", "Bearer "+token);
        conn.setRequestProperty("Accept", "application/json");
        try {
            if(body!=null) {
                conn.setDoOutput(true); conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                try(OutputStream out=conn.getOutputStream()) { out.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
            }
            int code=conn.getResponseCode();
            InputStream in=code<400?conn.getInputStream():conn.getErrorStream();
            if(in==null) throw new IOException("Bridge HTTP "+code);
            ByteArrayOutputStream out=new ByteArrayOutputStream(); byte[] buf=new byte[4096]; int n;
            try(InputStream input=in) {
                while((n=input.read(buf))!=-1) { out.write(buf,0,n); if(out.size()>2_000_000) throw new IOException("Слишком большой ответ Bridge"); }
            }
            JSONObject result;
            try { result=new JSONObject(out.toString("UTF-8")); }
            catch(Exception e) { throw new IOException("Ответ не соответствует Bridge V11"); }
            if(code>=400 || (result.has("ok")&&!result.optBoolean("ok")&&!path.equals("/v11/state")))
                throw new IOException(result.optString("message","Bridge HTTP "+code));
            if(path.equals("/v11/state") && result.optInt("protocol",0)!=11)
                throw new IOException("Нужен Bridge V11, протокол 11. V10 не совместим");
            return result;
        } finally { conn.disconnect(); }
    }
    static String error(Exception e) { String s=e.getMessage(); return s==null?e.getClass().getSimpleName():s; }
}
