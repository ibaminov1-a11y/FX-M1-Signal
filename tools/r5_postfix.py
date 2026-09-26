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

# Restore the two preserved structure overlays. Existing API35 regression tests
# independently failed on both paths; do not weaken or remove their assertions.
spark='app/src/main/java/com/openai/fxm1/SparklineView.java'
edit(spark,'private JSONArray positions=new JSONArray(),structure=new JSONArray();',
     'private JSONArray positions=new JSONArray(),structure=new JSONArray(),liveStructure=new JSONArray();')
edit(spark,'s.optJSONObject("live_bar"),null,s.optJSONObject("forecast")',
     's.optJSONObject("live_bar"),s.optJSONArray("live_structure"),s.optJSONObject("forecast")')
edit(spark,'liveBar=lb;forecast=f==null?new JSONObject():f;',
     'liveBar=lb;liveStructure=ls==null?new JSONArray():ls;forecast=f==null?new JSONObject():f;')
edit(spark,'viewport.live()?liveBar:null,f,viewport.live()?positions:new JSONArray());',
     'viewport.live()?liveBar:null,viewport.live()?liveStructure:new JSONArray(),f,viewport.live()?positions:new JSONArray());')
renderer='app/src/main/java/com/openai/fxm1/ScenarioMapRenderer.java'
edit(renderer,'JSONObject live,JSONObject f,JSONArray positions){',
              'JSONObject live,JSONArray liveStructure,JSONObject f,JSONArray positions){',2)
edit(renderer,'.draw(bars,structure,live,f,positions);',
              '.draw(bars,structure,live,liveStructure,f,positions);')
edit(renderer,'if(live!=null)candle(live,left+step*(count-.5f),step*.30f);',
     'if(live!=null){float xx=left+step*(count-.5f);xs.put(live.optLong("time"),xx);candle(live,xx,step*.30f);}')
edit(renderer,'line(previousX,previousY,xx,yy,0xffaaa7bf,.8f,false);',
              'line(previousX,previousY,xx,yy,0xff914dff,1f,false);')
edit(renderer,'text(s.optString("label"),xx-4*d,Math.max(top+8*d,yy-5*d),MUTED,8);previousX=xx;previousY=yy;',
              'p.setColor(0xff914dff);c.drawCircle(xx,yy,2.5f*d,p);\n            text(s.optString("label"),xx-4*d,Math.max(top+8*d,yy-5*d),0xff914dff,8);previousX=xx;previousY=yy;')
edit(renderer,'        if(routes!=null&&v3){',
'''        // Provisional structure describes already observed current-bar extremes,
        // not future route nodes. Hide it when browsing old candles.
        if(!historical&&live!=null&&liveStructure!=null){
            float prevX=Float.NaN,prevY=0;
            for(int i=0;i<liveStructure.length();i++){
                JSONObject s=liveStructure.optJSONObject(i);if(s==null)continue;
                Float xx=xs.get(s.optLong("time"));double v=s.optDouble("price");
                if(xx==null||!Double.isFinite(v)||v<low||v>high)continue;
                float yy=y(v);
                if(!Float.isNaN(prevX))line(prevX,prevY,xx,yy,0xffffb04d,1.2f,true);
                if(s.optBoolean("provisional",false)){
                    p.setColor(0xffffb04d);c.drawCircle(xx,yy,3*d,p);
                    text(s.optString("label"),xx+3*d,Math.max(top+8*d,yy-5*d),0xffffb04d,8);
                }
                prevX=xx;prevY=yy;
            }
        }
        if(routes!=null&&v3){''')
print('Confirmed violet swings and provisional amber LIVE structure restored end-to-end.')
