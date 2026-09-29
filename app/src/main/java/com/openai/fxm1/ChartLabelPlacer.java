package com.openai.fxm1;
import android.graphics.RectF;
import java.util.List;

/** Returns a nonoverlapping box, or null when no readable placement exists. */
final class ChartLabelPlacer {
    private ChartLabelPlacer(){}
    static RectF place(List<RectF> used,RectF bounds,float x,float y,float width,float height){
        if(width<=0||height<=0||width>bounds.width()||height>bounds.height())return null;
        float left=Math.max(bounds.left,Math.min(x,bounds.right-width));
        float step=height+3;int slots=(int)Math.ceil(bounds.height()/step)+2;
        for(int n=0;n<=slots*2;n++){
            int offset=n==0?0:(n+1)/2*(n%2==1?1:-1);
            float top=Math.max(bounds.top,Math.min(y+offset*step,bounds.bottom-height));
            RectF candidate=new RectF(left,top,left+width,top+height);boolean free=true;
            for(RectF box:used)if(RectF.intersects(candidate,box)){free=false;break;}
            if(free)return candidate;
        }
        return null;
    }
}
