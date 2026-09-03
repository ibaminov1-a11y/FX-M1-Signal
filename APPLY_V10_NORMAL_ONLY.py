
from pathlib import Path
import re, sys, shutil, datetime, py_compile

ROOT=Path.cwd().resolve()
APP=ROOT/"app/src/main/java/com/openai/fxm1"
MAIN=APP/"MainActivity.java"; MON=APP/"MonitoringService.java"; FEAT=APP/"FeatureEngine.java"
GR=ROOT/"app/build.gradle"; BR=ROOT/"mt5_bridge/bridge_v9_6.py"
for p in [MAIN,MON,FEAT,GR,BR]:
    if not p.exists():
        print("ERROR missing:",p); input("Enter..."); sys.exit(1)

stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/f"_V10_BACKUP_{stamp}"
for p in [MAIN,MON,FEAT,GR,BR]:
    d=backup/p.relative_to(ROOT); d.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,d)

def rw(p): return p.read_text(encoding="utf-8")
def ww(p,s): p.write_text(s,encoding="utf-8",newline="\n")
def fail(x):
    print("ERROR:",x); print("Backup:",backup); input("Enter..."); sys.exit(1)

# BRIDGE V10
b=rw(BR)
b=re.sub(r'BRIDGE_VERSION\s*=\s*"[^"]+"','BRIDGE_VERSION = "10.0"',b,count=1)
b=b.replace(
'basket_mode = bool(data.get("basket_mode", False)) and str(data.get("signal_mode") or "").upper() == "SCALP"',
'basket_mode = bool(data.get("basket_mode", False)) and str(data.get("signal_mode") or "").upper() in ("NORMAL", "SCALP")'
)
b=b.replace(
"threading.Thread(target=scalp_supervisor_loop,name='FXM1-ScalpSupervisor',daemon=True).start()",
"# V10 NORMAL ONLY: scalp supervisor disabled"
)
b=b.replace(
"print('SCALP runtime: ACTIVE · 100 ms autonomous INTENT/CAMPAIGN/EXIT loop')",
'print("NORMAL runtime: ACTIVE · SCALP supervisor DISABLED")'
)
BR10=ROOT/"mt5_bridge/bridge_v10_0.py"; ww(BR10,b)
try: py_compile.compile(str(BR10),doraise=True)
except Exception as e: fail("Bridge compile: "+str(e))
(ROOT/"mt5_bridge/START_BRIDGE_V10_0.bat").write_text(
'@echo off\ncd /d "%~dp0"\necho Starting FX M1 MT5 Bridge V10.0 NORMAL ONLY...\n.venv\\Scripts\\python.exe bridge_v10_0.py\npause\n',encoding="utf-8")

helpers=r'''
    private int patternScoreV10(List<Candle> c) {
        if (c == null || c.size() < 20) return 0;
        int n=c.size(), from=Math.max(0,n-24), mid=from+(n-from)/2;
        double h1=-Double.MAX_VALUE,l1=Double.MAX_VALUE,h2=-Double.MAX_VALUE,l2=Double.MAX_VALUE;
        for(int i=from;i<mid;i++){ h1=Math.max(h1,c.get(i).high); l1=Math.min(l1,c.get(i).low); }
        for(int i=mid;i<n-1;i++){ h2=Math.max(h2,c.get(i).high); l2=Math.min(l2,c.get(i).low); }
        Candle x=c.get(n-1), p=c.get(n-2);
        double range=Math.max(1e-12,Math.max(h1,h2)-Math.min(l1,l2)), tol=range*0.10;
        boolean hl=l2>l1+tol*0.25, lh=h2<h1-tol*0.25, fh=Math.abs(h2-h1)<=tol, fl=Math.abs(l2-l1)<=tol;
        double ph=-Double.MAX_VALUE, pl=Double.MAX_VALUE;
        for(int i=Math.max(from,n-12);i<n-1;i++){ ph=Math.max(ph,c.get(i).high); pl=Math.min(pl,c.get(i).low); }
        boolean bu=x.close>ph&&x.close>x.open, bd=x.close<pl&&x.close<x.open;
        if(hl&&fh&&bu)return 2;
        if(lh&&fl&&bd)return -2;
        if(hl&&lh){ if(bu)return 2; if(bd)return -2; }
        if(fh&&fl){ if(bu)return 2; if(bd)return -2; }
        if(hl&&h2>h1)return 1;
        if(lh&&l2<l1)return -1;
        double lo1=c.get(n-6).low,lo2=c.get(n-2).low,hi1=c.get(n-6).high,hi2=c.get(n-2).high;
        if(Math.abs(lo1-lo2)<=tol&&x.close>p.high)return 1;
        if(Math.abs(hi1-hi2)<=tol&&x.close<p.low)return -1;
        double old=c.get(n-8).close-c.get(n-16).close, pull=c.get(n-2).close-c.get(n-8).close;
        if(old>range*0.25&&pull<=0&&Math.abs(pull)<Math.abs(old)*0.65&&x.close>p.high)return 1;
        if(old<-range*0.25&&pull>=0&&Math.abs(pull)<Math.abs(old)*0.65&&x.close<p.low)return -1;
        return 0;
    }

    private int entryTimingV10(List<Candle> c,int d){
        if(c==null||c.size()<8||d==0)return 0;
        int n=c.size(); Candle b=c.get(n-3),p=c.get(n-2),x=c.get(n-1);
        if(d>0){
            boolean pull=p.close<=b.close||p.low<b.low;
            boolean reject=x.close>x.open&&x.close>p.close;
            boolean resume=x.close>p.high||(x.close>b.close&&x.low>=Math.min(p.low,b.low));
            return pull&&reject&&resume?1:0;
        } else {
            boolean pull=p.close>=b.close||p.high>b.high;
            boolean reject=x.close<x.open&&x.close<p.close;
            boolean resume=x.close<p.low||(x.close<b.close&&x.high<=Math.max(p.high,b.high));
            return pull&&reject&&resume?-1:0;
        }
    }

'''

def patch_engine(path):
    s=rw(path)
    s=re.sub(r'private String currentMode\(\)\s*\{.*?\n\s*\}','private String currentMode() { return "NORMAL"; }',s,count=1,flags=re.S)
    if 'int patternV10 = patternScoreV10(entrySeries);' not in s:
        s=s.replace('        int breakout = breakoutScore(entrySeries);',
                    '        int breakout = breakoutScore(entrySeries);\n        int patternV10 = patternScoreV10(entrySeries);',1)
    pat=re.compile(r'        boolean buySetup;\s*boolean sellSetup;.*?(?=\s*String signal = buySetup)',re.S)
    nb='''        boolean buySetup;
        boolean sellSetup;
        int buyVotes=0,sellVotes=0;
        int[] v10Votes={sHigher2,sHigher1,sEntry,sFast,structure,breakout,patternV10};
        for(int v:v10Votes){ if(v>0)buyVotes++; else if(v<0)sellVotes++; }
        buySetup=sHigher2>=0&&sHigher1>0&&sEntry>0&&structure>=0&&buyVotes>=4&&sellVotes<=1&&patternV10>=0;
        sellSetup=sHigher2<=0&&sHigher1<0&&sEntry<0&&structure<=0&&sellVotes>=4&&buyVotes<=1&&patternV10<=0;

'''
    s,_=pat.subn(nb,s,count=1)
    q='        int quality = setupQualityAdaptive(signal, sHigher2, sHigher1, sEntry, sFast, structure, breakout);'
    if q in s and 'V10_CONFIDENCE_GATE' not in s:
        s=s.replace(q,q+'''
        // V10_CONFIDENCE_GATE
        int dirV10="BUY".equals(signal)?1:"SELL".equals(signal)?-1:0;
        if(dirV10!=0){
            if(patternV10==dirV10*2)quality=Math.min(100,quality+10);
            else if(patternV10==dirV10)quality=Math.min(100,quality+5);
            else if(patternV10==-dirV10||patternV10==-dirV10*2)quality=Math.max(0,quality-20);
            if(quality<82||entryTimingV10(entrySeries,dirV10)!=dirV10)signal="WAIT";
        }
''',1)
    if 'private int patternScoreV10' not in s:
        idx=s.find('    private int setupQualityAdaptive(')
        if idx<0: idx=s.find('    private int trendScore(')
        if idx<0: fail("pattern helper anchor "+path.name)
        s=s[:idx]+helpers+s[idx:]
    if s.count("{")!=s.count("}"): fail("brace balance "+path.name)
    ww(path,s)

patch_engine(MON); patch_engine(MAIN)

# MAIN UI + unified money journal
a=rw(MAIN)
a=a.replace('new String[]{"CONSERVATIVE", "NORMAL", "AGGRESSIVE", "SCALP"}','new String[]{"NORMAL"}')
a=a.replace('new String[]{"CONSERVATIVE", "NORMAL", "AGGRESSIVE"}','new String[]{"NORMAL"}')
a=re.sub(r'signalModeSpinner\.setSelection\(prefs\.getInt\("signal_mode_pos",\s*1\)\);',
         'signalModeSpinner.setSelection(0);\n        prefs.edit().putInt("signal_mode_pos",0).apply();',a,count=1)
a=a.replace('riskSpinner.setSelection(prefs.getInt("risk_pos", 1));',
            'riskSpinner.setSelection(0);\n        prefs.edit().putInt("risk_pos",0).apply();',1)
a=a.replace('maxPositionsSpinner.setSelection(prefs.getInt("maxpos_pos", 0));',
            'maxPositionsSpinner.setSelection(9);\n        prefs.edit().putInt("maxpos_pos",9).putString("maxpos_label","10").apply();',1)
a=a.replace('base + "/trade-log?limit=200"','base + "/trade-ledger?days=30&limit=1000"')
a=a.replace('base + "/trade-ledger?days=30&limit=200"','base + "/trade-ledger?days=30&limit=1000"')
a=a.replace('JSONObject st = FeatureEngine.httpJson("GET", base + "/stats?days=30", null);\n                JSONObject pos',
            'JSONObject pos')
a=a.replace('String stText = FeatureEngine.formatStats(st);','String stText = FeatureEngine.formatLedgerStats(log);')
anchor='                payload.put("signal_mode", selectedSignalMode());'
if anchor in a:
    a=a.replace(anchor,'''                payload.put("basket_mode", true);
                payload.put("allow_same_symbol_multiple", true);
                payload.put("max_positions", 10);
                payload.put("basket_add_cooldown_sec", 15);
                payload.put("basket_min_progress_sl", 0.20);
                payload.put("signal_mode", "NORMAL");''',1)
ww(MAIN,a)

# MON payload
m=rw(MON)
m=re.sub(r'private String currentMode\(\)\s*\{.*?\n\s*\}','private String currentMode() { return "NORMAL"; }',m,count=1,flags=re.S)
anchor='            payload.put("max_positions", maxPos);'
if anchor in m and 'V10_NORMAL_BASKET' not in m:
    m=m.replace(anchor,anchor+'''
            // V10_NORMAL_BASKET
            payload.put("basket_mode", true);
            payload.put("allow_same_symbol_multiple", true);
            payload.put("max_positions", 10);
            payload.put("basket_add_cooldown_sec", 15);
            payload.put("basket_min_progress_sl", 0.20);''',1)
m=m.replace('payload.put("signal_mode", mode);','payload.put("signal_mode", "NORMAL");')
m=m.replace('payload.put("signal_mode", currentMode());','payload.put("signal_mode", "NORMAL");')
ww(MON,m)

# FEATURE money stats
f=rw(FEAT)
if 'formatLedgerStats(JSONObject root)' not in f:
    method=r'''
    public static String formatLedgerStats(JSONObject root) {
        JSONArray arr=root==null?null:root.optJSONArray("trades");
        if(arr==null)return "ДЕНЬГИ MT5: недоступно";
        double profit=0,loss=0,net=0,comm=0,swap=0,fee=0,tProfit=0,tLoss=0,tNet=0;
        int wins=0,today=0;
        Calendar cal=Calendar.getInstance(); cal.set(Calendar.HOUR_OF_DAY,0);cal.set(Calendar.MINUTE,0);cal.set(Calendar.SECOND,0);cal.set(Calendar.MILLISECOND,0);
        long dayStart=cal.getTimeInMillis()/1000L;
        for(int i=0;i<arr.length();i++){
            JSONObject e=arr.optJSONObject(i); if(e==null)continue;
            double n=e.optDouble("net_pl",0); net+=n; comm+=e.optDouble("commission",0); swap+=e.optDouble("swap",0); fee+=e.optDouble("fee",0);
            if(n>0){profit+=n;wins++;} else if(n<0)loss+=n;
            if(e.optLong("exit_time",0)>=dayStart){ today++; tNet+=n; if(n>0)tProfit+=n; else if(n<0)tLoss+=n; }
        }
        int count=arr.length(); double wr=count>0?wins*100.0/count:0;
        return "ДЕНЬГИ MT5 · ЕДИНЫЙ ЖУРНАЛ"+
            "\nСегодня: сделок "+today+" · PROFIT "+String.format(Locale.US,"%+.2f",tProfit)+" · LOSS "+String.format(Locale.US,"%+.2f",tLoss)+" · NET "+String.format(Locale.US,"%+.2f",tNet)+
            "\n30 дней: закрытых "+count+" · Win "+String.format(Locale.US,"%.1f%%",wr)+
            "\nPROFIT "+String.format(Locale.US,"%+.2f",profit)+" · LOSS "+String.format(Locale.US,"%+.2f",loss)+" · NET "+String.format(Locale.US,"%+.2f",net)+
            "\nComm "+String.format(Locale.US,"%+.2f",comm)+" · Swap "+String.format(Locale.US,"%+.2f",swap)+" · Fee "+String.format(Locale.US,"%+.2f",fee);
    }

'''
    idx=f.find('    public static String formatStats(')
    if idx<0: fail("FeatureEngine stats anchor")
    f=f[:idx]+method+f[idx:]
ww(FEAT,f)

# Version
g=rw(GR)
g=re.sub(r'versionName\s+["\'][^"\']+["\']','versionName "10.0"',g,count=1)
g=re.sub(r'versionCode\s+(\d+)',lambda x:f"versionCode {int(x.group(1))+1}",g,count=1)
ww(GR,g)

audits=[
("Bridge compile",True),
("NORMAL only UI",'new String[]{"NORMAL"}' in rw(MAIN)),
("Pattern Engine",'patternScoreV10' in rw(MON)),
("Timing gate",'V10_CONFIDENCE_GATE' in rw(MON)),
("Max 10",'payload.put("max_positions", 10)' in rw(MON)),
("Money ledger",'formatLedgerStats' in rw(FEAT)),
("SCALP supervisor disabled","ScalpSupervisor',daemon=True).start()" not in rw(BR10))
]
print()
for name,ok in audits:
    print(("OK: " if ok else "ERROR: ")+name)
    if not ok: fail(name)

print("\nDONE: FX M1 BOT V10.0 NORMAL ONLY")
print("Bridge:",BR10)
print("Start:",ROOT/"mt5_bridge/START_BRIDGE_V10_0.bat")
print("Android APK rebuild required")
print("REAL remains DISABLED")
print("Backup:",backup)
input("Нажми Enter...")
