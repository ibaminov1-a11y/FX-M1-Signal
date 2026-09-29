package com.openai.fxm1;

import android.content.Context;
import android.graphics.Rect;
import android.graphics.Canvas;
import android.util.AttributeSet;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.widget.ScrollView;

/** A status refresh may update child focus/layout, but cannot navigate the page. */
public final class LiveScrollView extends ScrollView {
    private boolean liveUpdate;
    public LiveScrollView(Context context,AttributeSet attrs){
        super(context,attrs);
    }
    public void beginLiveUpdate(){liveUpdate=true;invalidate();}
    @Override protected void dispatchDraw(Canvas canvas){
        // TextView can request a rectangle from its own pre-draw callback. Keep
        // the guard through those callbacks and release it after this frame.
        super.dispatchDraw(canvas);liveUpdate=false;
    }
    @Override public boolean requestChildRectangleOnScreen(View child,Rect rectangle,boolean immediate){
        return !liveUpdate&&super.requestChildRectangleOnScreen(child,rectangle,immediate);
    }
    @Override public void requestChildFocus(View child,View focused){
        int x=getScrollX(),y=getScrollY();
        super.requestChildFocus(child,focused);
        if(liveUpdate)super.scrollTo(x,y);
    }
    @Override protected void onLayout(boolean changed,int left,int top,int right,int bottom){
        int x=getScrollX(),y=getScrollY();
        super.onLayout(changed,left,top,right,bottom);
        if(liveUpdate)super.scrollTo(x,y);
    }
    // Real user navigation always takes precedence over a pending passive refresh.
    @Override public boolean dispatchTouchEvent(MotionEvent event){liveUpdate=false;return super.dispatchTouchEvent(event);}
    @Override public boolean dispatchKeyEvent(KeyEvent event){liveUpdate=false;return super.dispatchKeyEvent(event);}
    @Override public boolean onGenericMotionEvent(MotionEvent event){liveUpdate=false;return super.onGenericMotionEvent(event);}
}
