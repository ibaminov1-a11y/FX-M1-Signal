package com.openai.fxm1;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.ContextWrapper;
import android.text.TextUtils;
import android.util.AttributeSet;
import android.widget.ScrollView;
import android.widget.TextView;

/** A fixed-size live preview. The full value remains available as a reading snapshot. */
public final class StableLiveTextView extends TextView {
    private boolean initialized;

    public StableLiveTextView(Context context) { this(context, null); }
    public StableLiveTextView(Context context, AttributeSet attrs) { this(context, attrs, android.R.attr.textViewStyle); }
    public StableLiveTextView(Context context, AttributeSet attrs, int style) {
        super(context, attrs, style);
        int lines = getMaxLines();
        setLines(lines > 0 && lines < 100 ? lines : 3);
        setEllipsize(TextUtils.TruncateAt.END);
        setTooltipText("Нажмите, чтобы прочитать полный текст");
        setOnClickListener(v -> showSnapshot(getContext(), "ПОДРОБНОСТИ · СНИМОК", getText()));
        initialized = true;
    }

    @Override public void setText(CharSequence text, BufferType type) {
        // Incoming ticks often repeat an identical value. Do not remeasure it each second.
        if (initialized && TextUtils.equals(getText(), text)) return;
        super.setText(text, type);
    }

    public static void showSnapshot(Context context, String title, CharSequence value) {
        Context owner = context;
        while (owner instanceof ContextWrapper && !(owner instanceof Activity)) {
            Context next = ((ContextWrapper) owner).getBaseContext();
            if (next == owner) break;
            owner = next;
        }
        if (!(owner instanceof Activity)) return;
        Activity activity = (Activity) owner;
        if (activity.isFinishing() || activity.isDestroyed()) return;
        // Copy instead of retaining a mutable Spannable or observing future UI updates.
        String snapshot = value == null ? "—" : value.toString();
        ScrollView scroll = new ScrollView(activity);
        TextView text = new TextView(activity);
        text.setTag("stable-live-detail-text");
        text.setTextSize(15);
        text.setTextColor(0xfff4f1ff);
        text.setText(snapshot);
        text.setTextIsSelectable(true);
        int padding = Math.round(16 * getDensity(activity));
        text.setPadding(padding, padding, padding, padding);
        scroll.setBackgroundColor(0xff111227);
        scroll.addView(text);
        new AlertDialog.Builder(activity).setTitle(title)
            .setMessage("Снимок на момент открытия. LIVE продолжает обновляться на основном экране.")
            .setView(scroll).setPositiveButton("ЗАКРЫТЬ", null).show();
    }

    private static float getDensity(Context context) { return context.getResources().getDisplayMetrics().density; }
}
