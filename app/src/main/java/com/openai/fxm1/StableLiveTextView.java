package com.openai.fxm1;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.ContextWrapper;
import android.text.TextUtils;
import android.util.AttributeSet;
import android.widget.ScrollView;
import android.widget.LinearLayout;
import android.view.ViewGroup;
import android.widget.TextView;

/** A fixed-size live preview. The full value remains available as a reading snapshot. */
public final class StableLiveTextView extends TextView {
    private boolean initialized;

    public StableLiveTextView(Context context) { this(context, null); }
    public StableLiveTextView(Context context, AttributeSet attrs) { this(context, attrs, android.R.attr.textViewStyle); }
    public StableLiveTextView(Context context, AttributeSet attrs, int style) {
        super(context, attrs, style);
        boolean fixedLines = attrs != null && attrs.getAttributeValue(
            "http://schemas.android.com/apk/res/android", "lines") != null;
        int lines = getMaxLines();
        if (fixedLines) {
            setLines(lines > 0 && lines < 100 ? lines : 3);
        } else {
            if (lines <= 0 || lines >= 100) setMaxLines(3);
            setMinLines(1);
        }
        setEllipsize(TextUtils.TruncateAt.END);
        setTooltipText("Нажмите, чтобы прочитать полный текст");
        setOnClickListener(v -> showSnapshot(getContext(), "ПОДРОБНОСТИ · СНИМОК", getText()));
        initialized = true;
    }

    @Override public void setText(CharSequence text, BufferType type) {
        // Incoming ticks often repeat an identical value. Do not remeasure it each second.
        if (initialized && TextUtils.equals(getText(), text)) return;
        if(initialized){
            android.view.ViewParent parent=getParent();
            while(parent!=null){
                if(parent instanceof LiveScrollView){((LiveScrollView)parent).beginLiveUpdate();break;}
                parent=parent.getParent();
            }
        }
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
        text.setText("Снимок на момент открытия. LIVE продолжает обновляться на основном экране.\n\n" + snapshot);
        text.setTextIsSelectable(true);
        int padding = Math.round(16 * getDensity(activity));
        text.setPadding(padding, padding, padding, padding);
        scroll.setBackgroundColor(0xff111227);
        scroll.addView(text);
        // Constrain the reading viewport, not the content. Reserve room for title and close.
        android.util.DisplayMetrics dm = activity.getResources().getDisplayMetrics();
        int reserve = Math.round(220 * dm.density * activity.getResources().getConfiguration().fontScale);
        int viewport = Math.max(Math.round(80 * dm.density),
            Math.min(Math.round(dm.heightPixels * 0.60f), dm.heightPixels - reserve));
        LinearLayout body = new LinearLayout(activity);
        body.setOrientation(LinearLayout.VERTICAL);
        body.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, viewport));
        new AlertDialog.Builder(activity).setTitle(title)
            .setView(body).setPositiveButton("ЗАКРЫТЬ", null).show();
    }

    private static float getDensity(Context context) { return context.getResources().getDisplayMetrics().density; }
}
