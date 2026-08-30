package com.openai.fxm1;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.util.AttributeSet;
import android.view.View;
import java.util.ArrayList;
import java.util.List;

public class SparklineView extends View {
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<Double> values = new ArrayList<>();

    public SparklineView(Context context) {
        super(context);
        init();
    }

    public SparklineView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    public SparklineView(Context context, AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr);
        init();
    }

    private void init() {
        line.setStyle(Paint.Style.STROKE);
        line.setStrokeWidth(3f);
        line.setStrokeCap(Paint.Cap.ROUND);
        line.setStrokeJoin(Paint.Join.ROUND);
        line.setColor(Color.rgb(166, 107, 255));

        glow.setStyle(Paint.Style.STROKE);
        glow.setStrokeWidth(8f);
        glow.setStrokeCap(Paint.Cap.ROUND);
        glow.setStrokeJoin(Paint.Join.ROUND);
        glow.setColor(Color.argb(45, 145, 77, 255));
    }

    public void setValues(List<Double> newValues) {
        values.clear();
        if (newValues != null) values.addAll(newValues);
        invalidate();
    }

    public void setSignal(String signal) {
        int color = "BUY".equals(signal)
                ? Color.rgb(66, 214, 122)
                : "SELL".equals(signal)
                ? Color.rgb(255, 72, 87)
                : Color.rgb(166, 107, 255);
        line.setColor(color);
        glow.setColor(Color.argb(45, Color.red(color), Color.green(color), Color.blue(color)));
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (values.size() < 2 || getWidth() <= 0 || getHeight() <= 0) return;

        double min = Double.MAX_VALUE;
        double max = -Double.MAX_VALUE;
        for (Double value : values) {
            if (value == null || value.isNaN() || value.isInfinite()) continue;
            min = Math.min(min, value);
            max = Math.max(max, value);
        }
        if (min == Double.MAX_VALUE || max == -Double.MAX_VALUE) return;
        if (Math.abs(max - min) < 1e-12) max = min + 1e-6;

        float pad = 8f;
        float width = getWidth();
        float height = getHeight();
        float previousX = 0f;
        float previousY = 0f;
        boolean havePrevious = false;
        float lastX = 0f;
        float lastY = 0f;

        for (int i = 0; i < values.size(); i++) {
            Double value = values.get(i);
            if (value == null || value.isNaN() || value.isInfinite()) continue;
            float x = pad + (width - 2f * pad) * i / Math.max(1f, values.size() - 1f);
            float y = pad + (height - 2f * pad) * (float) ((max - value) / (max - min));
            if (havePrevious) {
                canvas.drawLine(previousX, previousY, x, y, glow);
                canvas.drawLine(previousX, previousY, x, y, line);
            }
            previousX = x;
            previousY = y;
            lastX = x;
            lastY = y;
            havePrevious = true;
        }
        if (havePrevious) canvas.drawCircle(lastX, lastY, 4f, line);
    }
}
