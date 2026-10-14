"""Run every selected native test class without sharing an instrumentation process.
No assertions are changed. No account or real MT5 is contacted. Fixtures are local.
"""
import hashlib, json, os, re, subprocess, sys, time
from pathlib import Path

out=Path('evidence');out.mkdir(exist_ok=True);(out/'ui').mkdir(exist_ok=True)
shard=int(os.environ['SHARD']); source=Path('app/src/androidTest/java/com/openai/fxm1')
classes=[p for p in sorted(source.glob('*Test.java')) if p.stem!='V108RepairTest']
selected=classes[shard::4]
expected={p.stem:re.findall(r'@Test\s+(?:public\s+)?void\s+(\w+)\s*\(',p.read_text()) for p in selected}
(out/'EXPECTED.json').write_text(json.dumps(expected,indent=2))
result={'shard':shard,'source':os.environ['R742_SOURCE_SHA'],'apk_sha256':hashlib.sha256(Path('binaries/app.apk').read_bytes()).hexdigest(),'tests':[],'classes':[]}

def call(args,timeout=30):
    return subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout,text=True,encoding='utf-8',errors='replace')
def diagnose(stem):
    for label,args in [('threads',['adb','shell','dumpsys','activity','processes']),('window',['adb','shell','dumpsys','window']),('logcat',['adb','logcat','-d','-t','3500'])]:
        try:(out/(stem+'-'+label+'.txt')).write_text(call(args).stdout)
        except Exception:pass
    try:call(['adb','shell','screencap','-p','/sdcard/r742-hang.png']);call(['adb','pull','/sdcard/r742-hang.png',str(out/'ui'/('hang-'+stem+'.png'))])
    except Exception:pass

for p in selected:
    stem=p.stem;print('BEGIN',shard,stem,flush=True)
    call(['adb','shell','am','force-stop','com.openai.fxm1.ec1'])
    cmd=['adb','shell','am','instrument','-w','-r','-e','timeout_msec','90000','-e','class','com.openai.fxm1.'+stem,'com.openai.fxm1.ec1.test/androidx.test.runner.AndroidJUnitRunner']
    started=time.monotonic(); log=out/(stem+'.log')
    timed=False
    with log.open('w') as stream:
        proc=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT)
        try:proc.wait(timeout=max(180,min(600,30+len(expected[stem])*35)))
        except subprocess.TimeoutExpired:
            timed=True;diagnose(stem);proc.kill();proc.wait();call(['adb','shell','am','force-stop','com.openai.fxm1.ec1'])
    text=log.read_text(errors='replace');current={}; finished=[]
    for line in text.splitlines():
        m=re.match(r'INSTRUMENTATION_STATUS: (class|test)=(.*)',line)
        if m:current[m.group(1)]=m.group(2)
        m=re.match(r'INSTRUMENTATION_STATUS_CODE: (-?\d+)',line)
        if m:
            code=int(m.group(1))
            if code!=1 and current.get('test'):
                item={'class':current.get('class',''),'test':current['test'],'code':code};finished.append(item);result['tests'].append(item)
            current={}
    want={'com.openai.fxm1.'+stem+'.'+n for n in expected[stem]}; got={t['class']+'.'+t['test'] for t in finished}
    ok=(not timed and proc.returncode==0 and len(finished)==len(want) and got==want and all(t['code']==0 for t in finished) and re.search(r'OK \('+str(len(want))+r' tests?\)',text) is not None)
    result['classes'].append(dict(name=stem,ok=ok,timed_out=timed,returncode=proc.returncode,expected=len(want),executed=len(finished),missing=sorted(want-got),seconds=round(time.monotonic()-started,2)))
    (out/'RESULT.json').write_text(json.dumps(result,indent=2));print('END',stem,'PASS' if ok else 'FAIL',len(finished),'/',len(want),flush=True)
    if not ok:diagnose(stem)

for remote in ['/sdcard/Download/ec1-qa','/sdcard/Android/data/com.openai.fxm1.ec1/files']:
    try:call(['adb','pull',remote,str(out/'ui')],60)
    except Exception:pass
result['ok']=bool(result['classes']) and all(x['ok'] for x in result['classes'])
(out/'RESULT.json').write_text(json.dumps(result,indent=2));sys.exit(0 if result['ok'] else 1)
