package com.openai.fxm1;

import android.graphics.*;
import java.util.*;

/** Diagnostic Canvas records real draw operations; no production test hooks. */
final class PatternTestCanvas extends Canvas {
    final Bitmap bitmap;
    final List<String> texts=new ArrayList<>();
    final List<RectF> textBounds=new ArrayList<>();
    final List<float[]> lines=new ArrayList<>();
    int dashed=0,candles=0;
    PatternTestCanvas(int w,int h){this(Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888));}
    private PatternTestCanvas(Bitmap b){super(b);bitmap=b;drawColor(0xff141125);}
    @Override public void drawText(String s,float x,float y,Paint p){
        texts.add(s);textBounds.add(new RectF(x,y+p.ascent(),x+p.measureText(s),y+p.descent()));super.drawText(s,x,y,p);
    }
    @Override public void drawLine(float x1,float y1,float x2,float y2,Paint p){
        lines.add(new float[]{x1,y1,x2,y2});if(p.getPathEffect()!=null)dashed++;super.drawLine(x1,y1,x2,y2,p);
    }
    @Override public void drawRect(float l,float t,float r,float b,Paint p){
        if(p.getColor()==0xff42d67a||p.getColor()==0xffff4857)candles++;super.drawRect(l,t,r,b,p);
    }
    boolean hasText(String s){for(String t:texts)if(t.contains(s))return true;return false;}
    boolean hasLine(float a,float b,float c,float d){for(float[] v:lines)if(Math.abs(v[0]-a)<.1&&Math.abs(v[1]-b)<.1&&Math.abs(v[2]-c)<.1&&Math.abs(v[3]-d)<.1)return true;return false;}
}
