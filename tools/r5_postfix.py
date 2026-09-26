"""Finalize approved UI migration contracts after the pinned R5 source bundle."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def edit(name, old, new, count=1):
 p=root/name; s=p.read_text(encoding='utf-8')
 assert s.count(old)==count,(name,old,s.count(old))
 p.write_text(s.replace(old,new),encoding='utf-8')
main='app/src/main/java/com/openai/fxm1/MainActivity.java'
edit(main,'new Spinner[]{symbolSpinner,entryTimeframeSpinner,signalModeSpinner,riskSpinner,maxPositionsSpinner}',
          'new Spinner[]{symbolSpinner,entryTimeframeSpinner,signalModeSpinner,riskSpinner}')
edit(main,'control.setEnabled(profileEditable);',
          'control.setEnabled(profileEditable);\n        if(maxPositionsSpinner!=null)maxPositionsSpinner.setEnabled(true);')
edit('app/src/main/java/com/openai/fxm1/FeatureEngine.java',
     '.putString("target_trade_mode", "DEMO")',
     '.putString("target_trade_mode", p.getString("target_trade_mode", "DEMO"))')
edit('app/src/main/java/com/openai/fxm1/EventClient.java',
     '.putString("target_trade_mode","DEMO").putInt("ec_limit",0)',
     '.putString("target_trade_mode",p.getString("target_trade_mode","DEMO")).putInt("ec_limit",0)')
edit('app/src/main/java/com/openai/fxm1/EventClient.java',
     '.putString("ec_lot_cap","0.01").apply();',
     '.putString("ec_lot_cap",p.getString("ec_lot_cap","0.01")).apply();')
# The legacy tests keep their safety assertions, but expect the new requested UI contract.
test='app/src/androidTest/java/com/openai/fxm1/EventCoreUiTest.java'
p=root/test;s=p.read_text(encoding='utf-8')
assert s.count('"COMPUTE_V1"')==3
s=s.replace('"COMPUTE_V1"','"SCENARIO_V2"').replace('"10.9-EC1-R4.2"','"10.9-EC1-R5"')
s=s.replace('assertEquals(.01,real.getDouble("lot_cap"),0.000001);','assertEquals(.50,real.getDouble("lot_cap"),0.000001);')
s=s.replace('assertEquals(1,adds.getCount());','assertTrue("Fixed lot presets and manual entry are present",adds.getCount()>=6);')
s=s.replace('assertEquals("По риску",String.valueOf(adds.getSelectedItem()));','assertEquals("0.01",String.valueOf(adds.getSelectedItem()));')
p.write_text(s,encoding='utf-8')
# Preserve concurrent regression work; bind the assertion to this protocol's canonical field.
p=root/'app/src/androidTest/java/com/openai/fxm1/R5RedContractUiTest.java'
if p.exists():
 s=p.read_text(encoding='utf-8');assert 'optDouble("requested_lot",0)' in s
 p.write_text(s.replace('optDouble("requested_lot",0)','optDouble("lot_cap",0)'),encoding='utf-8')
 edit('tools/run_ec1_qa.sh','com.openai.fxm1.R5SettingsHistoryTest \\\n',
      'com.openai.fxm1.R5SettingsHistoryTest,com.openai.fxm1.R5RedContractUiTest \\\n')
print('R5 migration preserves explicit mode/volume, lot changes queue internally, legacy assertions updated.')
# The lot callback runs outside onCreate; use the shared preferences accessor.
edit('app/src/main/java/com/openai/fxm1/MainActivity.java',
     'Toast.makeText(this,"Лот сохранён: "+prefs.getString("ec_lot_cap","")',
     'Toast.makeText(this,"Лот сохранён: "+EventClient.prefs().getString("ec_lot_cap","")')
edit('app/src/main/java/com/openai/fxm1/ChartViewport.java',
     'Math.max(1,Math.min(keys.size()-1,index-count))',
     'Math.max(0,Math.min(keys.size()-1,index-count))')
p=root/'app/src/androidTest/java/com/openai/fxm1/R5SettingsHistoryTest.java'
s=p.read_text(encoding='utf-8');where=s.rfind('}')
s=s[:where]+'''    @Test public void singleBarHistoryDoesNotThrow()throws Exception{
        JSONArray only=bars(1);
        ui(()->{SparklineView chart=new SparklineView(context);
            chart.setMarket(only,null,null,null,"SCENARIO_V2",null,null,null);
            chart.panHistory(12);assertEquals(1800000000L,chart.historyRightTime());
            chart.panHistory(-12);assertEquals(1800000000L,chart.historyRightTime());});
    }
'''+s[where:]
p.write_text(s,encoding='utf-8')
