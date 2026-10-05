package com.openai.fxm1;

import android.graphics.RectF;
import org.json.*;

/** Shared candle-slot transform; real time ordering, including calendar bars. */
final class ChartTransform {
    private final long[] times;
    private final RectF bounds;
    private final double low,high;
    final float density;
    ChartTransform(JSONArray bars,RectF area,double low,double high,float density){
        this.bounds=new RectF(area);this.low=low;this.high=high;this.density=density;
        times=new long[bars.length()];for(int i=0;i<times.length;i++)times[i]=bars.optJSONObject(i).optLong("time");
    }
    float x(long time){
        if(times.length==0)return bounds.left;
        double index=0;
        if(times.length==1)index=0;
        else if(time<=times[0])index=(time-times[0])/(double)Math.max(1,times[1]-times[0]);
        else if(time>=times[times.length-1])index=times.length-1+(time-times[times.length-1])/(double)Math.max(1,times[times.length-1]-times[times.length-2]);
        else{for(int i=1;i<times.length;i++)if(time<=times[i]){index=i-1+(time-times[i-1])/(double)Math.max(1,times[i]-times[i-1]);break;}}
        return bounds.left+(float)(index+.5)*bounds.width()/Math.max(1,times.length);
    }
    float y(double value){return bounds.top+(float)((high-value)/Math.max(1e-15,high-low))*bounds.height();}
    RectF plotBounds(){return new RectF(bounds);}
    long first(){return times.length==0?0:times[0];}long last(){return times.length==0?0:times[times.length-1];}
}
