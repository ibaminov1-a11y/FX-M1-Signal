package com.openai.fxm1;

import android.content.Context;
import android.graphics.Rect;
import android.graphics.Canvas;
import android.util.AttributeSet;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.widget.ScrollView;

/** A status refresh may update child focus/layout, but cannot navigate the page. */
public final class LiveScrollView extends ScrollView {
    private boolean liveUpdate;
    public interface RefreshListener {
        void onPullProgress(float progress);
        void onPullCancelled();
        void onRefresh();
    }
    private RefreshListener refreshListener;
    private boolean refreshing,pullEligible,pulling;
    private float downX,downY;
    private final int touchSlop;
    private final float refreshDistance;
    public LiveScrollView(Context context,AttributeSet attrs){
        super(context,attrs);
        touchSlop=ViewConfiguration.get(context).getScaledTouchSlop();
        refreshDistance=72*getResources().getDisplayMetrics().density;
    }
    public void setRefreshListener(RefreshListener listener){refreshListener=listener;}
    public void setRefreshing(boolean value){refreshing=value;if(value)pullEligible=false;}
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
    @Override public boolean dispatchTouchEvent(MotionEvent event){
        liveUpdate=false;
        int action=event.getActionMasked();
        if(action==MotionEvent.ACTION_DOWN){
            downX=event.getX();downY=event.getY();pulling=false;
            pullEligible=isEnabled()&&!refreshing&&refreshListener!=null&&getScrollY()==0;
        }else if(event.getPointerCount()>1||action==MotionEvent.ACTION_POINTER_DOWN||!isEnabled()){
            pullEligible=false;
        }else if(action==MotionEvent.ACTION_MOVE&&pullEligible){
            float dx=Math.abs(event.getX()-downX),dy=event.getY()-downY;
            // Lock intent for this entire gesture, including after a second finger lifts.
            if(dy < -touchSlop||(dx>touchSlop&&dx>=Math.abs(dy)))pullEligible=false;
        }
        boolean handled=super.dispatchTouchEvent(event);
        if(action==MotionEvent.ACTION_UP||action==MotionEvent.ACTION_CANCEL){pullEligible=false;pulling=false;}
        return handled;
    }
    private boolean startPull(MotionEvent event){
        if(pulling)return true;
        if(!pullEligible||refreshListener==null||event.getActionMasked()!=MotionEvent.ACTION_MOVE)return false;
        float dy=event.getY()-downY,dx=Math.abs(event.getX()-downX);
        if(getScrollY()!=0||dy<=touchSlop*2||dy<=dx*1.3f)return false;
        pulling=true;
        // Release ScrollView's velocity/edge tracking before taking over the drag.
        MotionEvent cancel=MotionEvent.obtain(event);cancel.setAction(MotionEvent.ACTION_CANCEL);
        super.onTouchEvent(cancel);cancel.recycle();
        return true;
    }
    @Override public boolean onInterceptTouchEvent(MotionEvent event){
        return startPull(event)||super.onInterceptTouchEvent(event);
    }
    @Override public boolean onTouchEvent(MotionEvent event){
        // Non-clickable headers may route directly here without a child touch target.
        if(!startPull(event))return super.onTouchEvent(event);
        int action=event.getActionMasked();
        RefreshListener listener=refreshListener;
        if(action==MotionEvent.ACTION_MOVE&&listener!=null)
            listener.onPullProgress(pullEligible?Math.max(0,Math.min(1,(event.getY()-downY)/refreshDistance)):0);
        if(action==MotionEvent.ACTION_UP||action==MotionEvent.ACTION_CANCEL){
            float dy=event.getY()-downY,dx=Math.abs(event.getX()-downX);
            boolean ready=action==MotionEvent.ACTION_UP&&pullEligible&&isEnabled()&&!refreshing
                &&dy>=refreshDistance&&dy>dx*1.3f;
            pulling=false;pullEligible=false;
            if(listener!=null){if(ready)listener.onRefresh();else listener.onPullCancelled();}
        }
        return true;
    }
    @Override public void requestDisallowInterceptTouchEvent(boolean disallow){
        if(disallow&&!pulling)pullEligible=false;
        super.requestDisallowInterceptTouchEvent(disallow);
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event){liveUpdate=false;return super.dispatchKeyEvent(event);}
    @Override public boolean onGenericMotionEvent(MotionEvent event){liveUpdate=false;return super.onGenericMotionEvent(event);}
}
