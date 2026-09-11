"""CI preparation only, before commit/build. Not shipped as a user installer."""
from pathlib import Path
p=Path('mt5_bridge/bridge_v10_0.py');t=p.read_text()
old='ALLOW_REAL = os.environ.get("FXM1_ALLOW_REAL", "0") == "1"'
new='ALLOW_REAL = False  # V10.8 repair distribution is DEMO only, including environment overrides.'
if old in t:
    assert t.count(old)==1;p.write_text(t.replace(old,new))
else: assert new in t
p=Path('app/src/main/java/com/openai/fxm1/V10Repair.java');t=p.read_text()
# Production /signal returns order, not ticket. Accept the old alias without displaying order #0.
old='r.optLong("ticket",0)';new='r.optLong("ticket",r.optLong("order",0))'
if old in t:
    assert t.count(old)==2;t=t.replace(old,new);p.write_text(t)
else: assert new in t
p=Path('app/src/androidTest/java/com/openai/fxm1/V108RepairTest.java');t=p.read_text()
t=t.replace('.put("ticket",77).put("deal",88)','.put("order",77).put("deal",88)')
anchor='assertEquals("CONFIRMED",p.getString("execution_stage",""));'
if 'ордер #77' not in t:
    assert t.count(anchor)==1;t=t.replace(anchor,anchor+'assertTrue(p.getString("execution_detail","").contains("ордер #77"));')
p.write_text(t)
p=Path('qa/test_v108_risk.py');t=p.read_text()
if "os.environ['FXM1_ALLOW_REAL']='1'" not in t:
    old="fake=Fake('MetaTrader5');sys.modules['MetaTrader5']=fake"
    assert old in t;t=t.replace(old,old+"\nos.environ['FXM1_ALLOW_REAL']='1'  # Verify an old environment override cannot enable REAL.")
p.write_text(t)
p=Path('app/src/main/res/layout/activity_main.xml');t=p.read_text()
old='android:text="V10.0"';new='android:text="V10.8"'
if old in t:
    assert t.count(old)==1;p.write_text(t.replace(old,new))
else: assert new in t
p=Path('app/src/main/java/com/openai/fxm1/MainActivity.java');t=p.read_text()
old='return "APP V" + appV + "   •   BRIDGE V"';new='return "APP V10.8 (протокол " + appV + ")   •   BRIDGE V"'
if old in t:
    assert t.count(old)==1;p.write_text(t.replace(old,new))
else: assert new in t
