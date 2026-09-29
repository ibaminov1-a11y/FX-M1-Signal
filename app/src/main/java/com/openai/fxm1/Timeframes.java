package com.openai.fxm1;

import android.content.SharedPreferences;

/** Stable names survive changes to the order of the native entry selector. */
final class Timeframes {
    static final String[] CHOICES={"M1","M5","M15","M30","H1","H4","D1","W1","MN1"};
    private static final String[] OLD={"M1","M5","M10","M15","H1","H4","D1","W1","MN1"};
    private Timeframes(){}
    static int index(String frame){for(int i=0;i<CHOICES.length;i++)if(CHOICES[i].equals(frame))return i;return -1;}
    static void migrate(SharedPreferences prefs){
        if(prefs.getBoolean("v925_tf_migrated",false))return;
        int position=prefs.getInt("entry_tf_pos",1);
        if(!prefs.getBoolean("v800_tf_migrated",false)&&position>=2)position++;
        String named=prefs.getString("entry_tf_name",OLD[Math.max(0,Math.min(OLD.length-1,position))]);
        if(index(named)<0&&!"M10".equals(named))named="M5";
        prefs.edit().putString("entry_tf_name",named).putInt("entry_tf_pos",index(named))
            .putBoolean("v800_tf_migrated",true).putBoolean("v925_tf_migrated",true).apply();
    }
    static String selected(SharedPreferences prefs){migrate(prefs);return prefs.getString("entry_tf_name","M5");}
    static void select(SharedPreferences.Editor editor,int position){
        if(position>=0&&position<CHOICES.length)editor.putString("entry_tf_name",CHOICES[position]).putInt("entry_tf_pos",position);
    }
    static void project(SharedPreferences.Editor editor,String frame){
        if(index(frame)>=0||"M10".equals(frame))editor.putString("entry_tf_name",frame).putInt("entry_tf_pos",index(frame));
    }
}
