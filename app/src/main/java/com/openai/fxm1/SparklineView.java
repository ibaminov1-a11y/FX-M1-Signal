package com.openai.fxm1;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.util.AttributeSet;
import android.view.View;
import java.util.ArrayList;
import java.util.List;

public class SparklineView extends View {
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<Double> values = new ArrayList<>();

    public SparklineView(Context context) { super(context); init(); }
    public SparklineView(Context context, AttributeSet attrs) { super(context, attrs); init(); }
    public SparklineView(Context context, AttributeSet attrs, int defStyleAttr) { super(context, attrs, defStyleAttr); init(); }

    private void init() {
        setLayerType(View.LAYER_TYPE_SOFTWARE, null);
        line.setStyle(Paint.Style.STROKE);
        line.setStrokeWidth(dp(1.8f));
        line.setStrokeCap(Paint.Cap.ROUND);
        line.setStrokeJoin(Paint.Join.ROUND);
        glow.setStyle(Paint.Style.STROKE);
        glow.setStrokeWidth(dp(5.2f));
        glow.setStrokeCap(Paint.Cap.ROUND);
        glow.setStrokeJoin(Paint.Join.ROUND);
        dot.setStyle(Paint.Style.FILL);
        setSignal("WAIT");
    }

    public void setValues(List<Double> newValues) {
        values.clear();
        if (newValues != null) {
            int from = Math.max(0, newValues.size() - 48);
            for (int i = from; i < newValues.size(); i++) values.add(newValues.get(i));
        }
        invalidate();
    }

    public void setSignal(String signal) {
        int color = "BUY".equals(signal) ? Color.rgb(66, 214, 122)
                : "SELL".equals(signal) ? Color.rgb(255, 72, 87)
                : Color.rgb(166, 107, 255);
        line.setColor(color);
        glow.setColor(Color.argb(58, Color.red(color), Color.green(color), Color.blue(color)));
        dot.setColor(color);
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (values.size() < 2 || getWidth() <= 0 || getHeight() <= 0) return;

        ArrayList<Double> clean = new ArrayList<>();
        for (Double v : values) if (v != null && !v.isNaN() && !v.isInfinite()) clean.add(v);
        if (clean.size() < 2) return;

        double min = Double.MAX_VALUE, max = -Double.MAX_VALUE;
        for (double v : clean) { min = Math.min(min, v); max = Math.max(max, v); }
        double range = max - min;
        if (range < 1e-12) range = Math.max(Math.abs(max) * 0.00002, 1e-6);
        double center = (max + min) / 2.0;
        double paddedRange = range * 1.18;
        min = center - paddedRange / 2.0;
        max = center + paddedRange / 2.0;

        float padX = dp(5), padY = dp(7);
        float w = getWidth() - padX * 2;
        float h = getHeight() - padY * 2;
        int n = clean.size();
        float[] xs = new float[n];
        float[] ys = new float[n];
        for (int i = 0; i < n; i++) {
            xs[i] = padX + w * i / Math.max(1f, n - 1f);
            ys[i] = padY + h * (float)((max - clean.get(i)) / (max - min));
        }

        Path p = new Path();
        p.moveTo(xs[0], ys[0]);
        for (int i = 1; i < n; i++) {
            float midX = (xs[i - 1] + xs[i]) / 2f;
            p.cubicTo(midX, ys[i - 1], midX, ys[i], xs[i], ys[i]);
        }
        canvas.drawPath(p, glow);
        canvas.drawPath(p, line);
        canvas.drawCircle(xs[n - 1], ys[n - 1], dp(2.5f), dot);
    }

    private float dp(float v) { return v * getResources().getDisplayMetrics().density; }
}
