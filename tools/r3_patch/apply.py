from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'app/src/main/java/com/openai/fxm1/EventClient.java'
text=p.read_text(encoding='utf-8')
old='''.putString("state_components","Подтверждённая структура → откат → свежий триггер. Балльное голосование не используется.")'''
new='''.putString("state_components","R3: большой M5 импульс / неглубокое продолжение / классический откат. Вход только по подтверждённому событию MT5.")'''
if text.count(old)!=1: raise SystemExit('state_components block not found exactly once')
text=text.replace(old,new,1)
old2='''        String historyKey=phase+"|"+sig+"|"+why;\n        boolean changed=!historyKey.equals(p.getString("ec_history_key",""));\n        e.putString("ec_history_key",historyKey);e.apply();\n        if(changed)FeatureEngine.appendSignalHistory(p,symbol,tf,sig,-1,phaseName(phase)+": "+why);\n'''
new2='''        String historyKey=path+"|"+phase+"|"+sig+"|"+why;\n        boolean changed=!historyKey.equals(p.getString("ec_history_key",""));\n        e.putString("ec_history_key",historyKey);e.apply();\n        if(changed)FeatureEngine.appendSignalHistory(p,symbol,tf,sig,-1,pathName(path)+" · "+phaseName(phase)+": "+why);\n'''
if text.count(old2)!=1: raise SystemExit('history block not found exactly once')
p.write_text(text.replace(old2,new2,1),encoding='utf-8')
