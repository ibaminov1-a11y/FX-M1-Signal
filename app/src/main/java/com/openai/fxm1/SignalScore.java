package com.openai.fxm1;

/** Explains the existing score; never grants permission to execute a trade. */
public final class SignalScore {
    private SignalScore() {}
    public static int[] parts(String candidate,int h2,int h1,int entry,int fast,int structure,int breakout,int pattern) {
        if ("WAIT".equals(candidate)) return new int[]{25,Math.abs(h2+h1+entry+fast)*7,structure!=0?5:0,breakout!=0?8:0};
        int d="BUY".equals(candidate)?1:-1;
        return new int[]{60,h2==d?8:0,h1==d?8:0,entry==d?8:0,fast==d?4:0,structure==d?5:0,
                breakout==d*2?7:breakout==d?4:0,Math.max(0,pattern*d)*5};
    }
    public static int score(String candidate,int h2,int h1,int entry,int fast,int structure,int breakout,int pattern) {
        int sum=0;for(int x:parts(candidate,h2,h1,entry,fast,structure,breakout,pattern))sum+=x;
        return Math.min("WAIT".equals(candidate)?59:100,sum);
    }
    public static String describe(String candidate,int h2,int h1,int entry,int fast,int structure,int breakout,int pattern) {
        int[] p=parts(candidate,h2,h1,entry,fast,structure,breakout,pattern);
        String[] labels="WAIT".equals(candidate)?new String[]{"База","Согласованность","Структура","Пробой"}:
            new String[]{"База","Старший ТФ 2","Старший ТФ 1","Входной ТФ","Быстрый ТФ","Структура","Пробой","Паттерн"};
        StringBuilder s=new StringBuilder();int sum=0;
        for(int i=0;i<p.length;i++){if(i>0)s.append(" + ");s.append(labels[i]).append(" ").append(p[i]);sum+=p[i];}
        int cap="WAIT".equals(candidate)?59:100;
        s.append(" = ").append(sum);if(sum>cap)s.append("; потолок ").append(cap);
        return s.append("\nИтого: ").append(Math.min(sum,cap)).append("/100 · оценка сценария, не вероятность прибыли").toString();
    }
}
