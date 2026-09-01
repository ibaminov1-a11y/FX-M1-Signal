from pathlib import Path
import sys, shutil, datetime, re, py_compile

ROOT=Path.cwd().resolve()
MON=ROOT/'app/src/main/java/com/openai/fxm1/MonitoringService.java'
BR=ROOT/'mt5_bridge/bridge_v9_5.py'
GR=ROOT/'app/build.gradle'
for x in (MON,BR,GR):
    if not x.exists():
        print('ERROR missing',x); input('Enter...'); sys.exit(1)

stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
backup=ROOT/f'_V9_6_BACKUP_{stamp}'
for x in (MON,BR,GR):
    d=backup/x.relative_to(ROOT); d.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(x,d)

b=BR.read_text(encoding='utf-8')
b=re.sub(r'BRIDGE_VERSION\s*=\s*"[^"]+"','BRIDGE_VERSION = "9.6"',b,count=1)

start=b.find('def _scalp_entry_state(')
end=b.find('def scalp_autonomous_once(',start)
if start<0 or end<0:
    print('ERROR entry function anchors'); input('Enter...'); sys.exit(1)

entry = '''def _scalp_entry_state(symbol, side, tick, info, snap, state, basket):
    now=time.time(); data=state.get('data') or {}; quality=int(data.get('quality') or 0)
    _remember_tick(symbol,tick)
    q=[x for x in list(_SCALP_TICKS.get(symbol,())) if now-x[0] <= 18.0]
    if len(q)<12: return False,'WARMUP',{'stage':'WARMUP','ticks':len(q)}
    mids=[(x[1]+x[2])*0.5 for x in q]; cur=mids[-1]
    point=max(float(getattr(info,'point',0.0) or 0.0),1e-9)
    spread=max(0.0,float(tick.ask)-float(tick.bid))
    atr=max(float(snap.get('atr') or 0.0),point*10.0,spread*2.0)
    cm=_SCALP_CAMPAIGN_META.setdefault((symbol,side),{})
    recent=mids[-min(50,len(mids)):]; short=mids[-min(10,len(mids)):]
    hi,lo=max(recent),min(recent); rng=max(hi-lo,point)
    k=min(5,len(mids)-1); fast=cur-mids[-1-k]; eps=max(point*0.5,spread*0.10)
    if side=='BUY':
        favourable=fast>max(point,spread*0.15); counter=fast < -max(point*0.8,spread*0.12)
        extended=(hi-cur)<=max(rng*0.18,spread*1.5,point*4); depth=max(0.0,hi-cur)
        pull_ok=counter or depth>=max(atr*0.045,spread*1.0,point*2)
        rejection=favourable and cur>min(short[:-1]); micro_break=cur>=max(short[:-1])+eps
    else:
        favourable=fast < -max(point,spread*0.15); counter=fast>max(point*0.8,spread*0.12)
        extended=(cur-lo)<=max(rng*0.18,spread*1.5,point*4); depth=max(0.0,cur-lo)
        pull_ok=counter or depth>=max(atr*0.045,spread*1.0,point*2)
        rejection=favourable and cur<max(short[:-1]); micro_break=cur<=min(short[:-1])-eps

    if not basket:
        stage=cm.get('stage','WAIT_PULLBACK')
        if stage not in ('WAIT_PULLBACK','PULLBACK','REJECTION','RESUME'):
            stage='WAIT_PULLBACK'; cm['stage']=stage
        if stage=='WAIT_PULLBACK':
            if not pull_ok: return False,('CHASE_WAIT_PULLBACK' if extended else 'WAIT_PULLBACK'),{'stage':'WAIT_PULLBACK'}
            cm.update(stage='PULLBACK',pullback_at=now,pullback_price=cur); return False,'PULLBACK_SEEN',{'stage':'PULLBACK'}
        if cm.get('stage')=='PULLBACK':
            if not rejection: return False,'WAIT_REJECTION',{'stage':'PULLBACK'}
            cm.update(stage='REJECTION',rejection_at=now,rejection_price=cur); return False,'REJECTION_SEEN',{'stage':'REJECTION'}
        if cm.get('stage')=='REJECTION':
            if not favourable: return False,'WAIT_RESUME',{'stage':'REJECTION'}
            cm['stage']='RESUME'; return False,'RESUME_SEEN',{'stage':'RESUME'}
        if cm.get('stage')=='RESUME':
            if not (favourable and micro_break): return False,'WAIT_MICRO_BREAK',{'stage':'RESUME'}
            cm.update(stage='WAIT_PULLBACK',entry_trigger_at=now,trigger_price=cur)
            return True,'PULLBACK_MICRO_BREAK',{'stage':'ENTRY','side':side,'quality':quality}
        return False,'WAIT_PULLBACK',{'stage':'WAIT_PULLBACK'}

    pnl=sum(float(p.profit)+float(getattr(p,'swap',0.0) or 0.0) for p in basket)
    if pnl<=0:
        cm['add_stage']='ADD_WAIT_PULLBACK'; return False,'NO_ADD_RED_BASKET',{'basket_pnl':pnl}
    entries=[float(p.price_open) for p in basket]; best=max(entries) if side=='BUY' else min(entries)
    px=float(tick.ask if side=='BUY' else tick.bid); progress=px-best if side=='BUY' else best-px
    spacing=max(atr*max(0.035,safe_float(data.get('campaign_spacing_atr'),0.05)),spread*1.1,point*3)
    if progress<spacing: return False,'WAIT_PROGRESS',{'basket_pnl':pnl,'progress':progress,'spacing':spacing}
    st=cm.get('add_stage','ADD_WAIT_PULLBACK')
    if st=='ADD_WAIT_PULLBACK':
        if not pull_ok: return False,'ADD_WAIT_PULLBACK',{'basket_pnl':pnl}
        cm['add_stage']='ADD_PULLBACK'; return False,'ADD_PULLBACK_SEEN',{}
    if st=='ADD_PULLBACK':
        if not rejection: return False,'ADD_WAIT_REJECTION',{}
        cm['add_stage']='ADD_REJECTION'; return False,'ADD_REJECTION_SEEN',{}
    if st=='ADD_REJECTION':
        if not favourable: return False,'ADD_WAIT_RESUME',{}
        cm['add_stage']='ADD_RESUME'; return False,'ADD_RESUME_SEEN',{}
    if cm.get('add_stage')=='ADD_RESUME':
        if not (favourable and micro_break): return False,'ADD_WAIT_MICRO_BREAK',{}
        if now-float(cm.get('last_add_at',0.0))<0.75: return False,'ADD_DEBOUNCE',{}
        cm.update(add_stage='ADD_WAIT_PULLBACK',last_add_at=now)
        return True,'SCALE_IN_PULLBACK_BREAK',{'basket_pnl':pnl,'progress':progress,'spacing':spacing}
    cm['add_stage']='ADD_WAIT_PULLBACK'; return False,'ADD_WAIT_PULLBACK',{}

'''
b=b[:start]+entry+b[end:]

# V9.5 profit thresholds -> V9.6 micro scalp thresholds.
b=b.replace("single_arm = max(0.60, safe_float(cfg.get('scalp_campaign_single_arm_usd'), 0.90))",
            "single_arm = max(0.08, min(0.30, 0.10 * max(1.0, float(getattr(p,'volume',0.01) or 0.01)/0.01)))")
b=b.replace("min_giveback = max(0.15, safe_float(cfg.get('scalp_single_peak_min_giveback_usd'), 0.25))",
            "min_giveback = max(0.05, min(0.18, peak * 0.42))")
b=b.replace("campaign_arm = max(1.00, safe_float(cfg.get('scalp_campaign_arm_usd'), 1.25))",
            "campaign_arm = max(0.12, min(0.60, 0.10 * max(2, len(group))))")
b=b.replace("min_giveback = max(0.20, safe_float(cfg.get('scalp_basket_peak_min_giveback_usd'), 0.25))",
            "min_giveback = max(0.06, min(0.20, peak * 0.38))")
b=b.replace("comment='FXM1 PROFIT LOCK'","comment='FXM1 MICRO LOCK'")

if 'early_probe =' in b:
    print('ERROR early_probe remains'); input('Enter...'); sys.exit(1)
if 'PULLBACK_MICRO_BREAK' not in b or 'SCALE_IN_PULLBACK_BREAK' not in b:
    print('ERROR V9.6 entry audit'); input('Enter...'); sys.exit(1)

br96=ROOT/'mt5_bridge/bridge_v9_6.py'
br96.write_text(b,encoding='utf-8',newline='\n')
py_compile.compile(str(br96),doraise=True)
(ROOT/'mt5_bridge/START_BRIDGE_V9_6.bat').write_text(
'@echo off\ncd /d "%~dp0"\necho Starting FX M1 MT5 Bridge V9.6...\necho 100ms runtime - strict pullback entry - pyramiding - micro peak lock\n.venv\\Scripts\\python.exe bridge_v9_6.py\npause\n',
encoding='utf-8')

m=MON.read_text(encoding='utf-8')
m=m.replace('payload.put("campaign_spacing_atr", 0.07);','payload.put("campaign_spacing_atr", 0.05);')
m=m.replace('payload.put("scalp_campaign_single_arm_usd", 0.90);','payload.put("scalp_campaign_single_arm_usd", 0.10);')
m=m.replace('payload.put("scalp_basket_peak_giveback_pct", 28.0);','payload.put("scalp_basket_peak_giveback_pct", 38.0);')
m=m.replace('payload.put("scalp_basket_peak_min_giveback_usd", 0.25);','payload.put("scalp_basket_peak_min_giveback_usd", 0.06);')
MON.write_text(m,encoding='utf-8',newline='\n')

g=GR.read_text(encoding='utf-8')
g=re.sub(r'versionName\s+["\'][^"\']+["\']','versionName "9.6"',g,count=1)
g=re.sub(r'versionCode\s+(\d+)',lambda x:f'versionCode {int(x.group(1))+1}',g,count=1)
GR.write_text(g,encoding='utf-8',newline='\n')

checks=[
('direction 18/28','scalpDirectionScore >= 28' in m),
('network 1 sec','MT5_SNAPSHOT_MS = 1000L' in m),
('network 2 sec','POSITION_MANAGE_MS = 2000L' in m),
('bridge compile',True)]
for n,ok in checks:
    print(('OK: ' if ok else 'ERROR: ')+n)
    if not ok: sys.exit(1)

print('\nDONE: FX M1 BOT V9.6 CONSOLIDATED')
print('Bridge compile: OK')
print('Bridge:',br96)
print('Start:',ROOT/'mt5_bridge/START_BRIDGE_V9_6.bat')
print('Android APK must be rebuilt.')
print('REAL remains DISABLED.')
print('Backup:',backup)
input('Enter...')
