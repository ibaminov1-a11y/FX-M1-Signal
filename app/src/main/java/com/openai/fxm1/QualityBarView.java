package com.openai.fxm1;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.util.AttributeSet;
import android.view.View;

public class QualityBarView extends View {
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint empty = new Paint(Paint.ANTI_ALIAS_FLAG);
    private int quality = 0;
    private String signal = "WAIT";

    public QualityBarView(Context context) { super(context); init(); }
    public QualityBarView(Context context, AttributeSet attrs) { super(context, attrs); init(); }
    public QualityBarView(Context context, AttributeSet attrs, int defStyleAttr) { super(context, attrs, defStyleAttr); init(); }

    private void init() {
        empty.setColor(Color.rgb(55, 57, 75));
        fill.setColor(Color.rgb(166, 107, 255));
    }

    public void setQuality(int value) {
        quality = Math.max(0, Math.min(100, value));
        invalidate();
    }

    public void setSignal(String value) {
        signal = value == null ? "WAIT" : value;
        if ("BUY".equals(signal)) fill.setColor(Color.rgb(66, 214, 122));
        else if ("SELL".equals(signal)) fill.setColor(Color.rgb(255, 72, 87));
        else fill.setColor(Color.rgb(166, 107, 255));
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int segments = 10;
        float gap = dp(2);
        float h = Math.max(dp(6), getHeight() - dp(6));
        float top = (getHeight() - h) / 2f;
        float usable = getWidth() - gap * (segments - 1);
        float w = usable / segments;
        int active = (int) Math.ceil(quality / 10.0);
        float radius = dp(3);
        for (int i = 0; i < segments; i++) {
            float left = i * (w + gap);
            canvas.drawRoundRect(left, top, left + w, top + h, radius, radius, i < active ? fill : empty);
        }
    }

    private float dp(float v) { return v * getResources().getDisplayMetrics().density; }
}
