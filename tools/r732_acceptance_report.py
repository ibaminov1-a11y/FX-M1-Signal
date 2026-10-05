"""Fail-closed evidence index. Missing/failed checks never become a release."""
from __future__ import annotations
import argparse,hashlib,json,re,xml.etree.ElementTree as E
from pathlib import Path
CERT='3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885'
VARIANTS=('triangle_ascending','triangle_descending','triangle_symmetric','flag_bull','flag_bear','pennant_bull','pennant_bear','channel_rising','channel_falling','range_horizontal','wedge_rising','wedge_falling','broadening_expanding','multi_extreme_double_top','multi_extreme_triple_top','multi_extreme_double_bottom','multi_extreme_triple_bottom','head_shoulders_top','head_shoulders_inverse')
PNG_NAMES=tuple('r732-pattern-%s-320.png'%i for i in range(19))+tuple('r732-activity-%s.png'%i for i in range(19))+('r732-pattern-forming.png','r732-activity-forming.png','r732-activity-no-figure.png','r732-activity-stale.png','r732-activity-offline.png','r732-activity-position.png','r732-activity-archive.png','r732-fullscreen-head-shoulders.png')
NATIVE_PATTERNS=('ascendingTriangle','descendingTriangle','symmetricTriangle','bullFlag','bearFlag','bullPennant','bearPennant','risingChannel','fallingChannel','rectangle','risingWedge','fallingWedge','broadening','doubleTop','tripleTop','doubleBottom','tripleBottom','headShoulders','inverseHeadShoulders')
# Each gate lists assertions in executed tests, not a blanket "green CI" inference.
CHECKS={
 '02':('serverForbidsAnalogueAfterRefresh','recreationRestoresMode','twoSurfacesUseOneChoice','explicitForecastButtonCannotEnableAnalogue'),
 '03':tuple('test_'+kind+'_'+v for v in VARIANTS for kind in ('positive_geometry','near_miss_rejected','prefix_visibility')),
 '04':('test_positive_geometry_flag_bull','test_near_miss_rejected_flag_bull','test_positive_geometry_head_shoulders_top','headShoulders','bullFlag'),
 '05':('test_pattern_visible_when_entry_waits','test_display_disabled_does_not_change_actual_entry','test_forming_anchor_and_confirmation_keep_identity'),
 '06':('test_moving_candidate_keeps_identity','formingExtremeUsesDashedObservedGeometry'),
 '07':NATIVE_PATTERNS,
 '08':('test_corrections_and_scopes_do_not_mutate_old_snapshots','test_first_chart_snapshot_remains_immutable')+tuple('test_prefix_visibility_'+v for v in VARIANTS),
 '09':('test_branches_have_separate_read_only_outcomes','test_same_bar_target_and_cancel_is_unknown_without_ticks','test_recorded_terminal_tick_has_its_own_evidence_time','test_cancel_and_expiry_are_not_targets'),
 '10':('test_branches_have_separate_read_only_outcomes',),
 '11':tuple('test_near_miss_rejected_'+v for v in VARIANTS),
 '12':('actualActivityShowsAllNineteenNumericPatternsWithoutTrading',),
 '13':('explicitFitIncludesPoleAndLastAnchor','newTicksDoNotResetManualViewport','fitRangeCanShowMoreThan240Candles'),
 '14':('fullScreenRetainsSelectedHeadAndShoulders','formingEmptyStaleOfflineAndPositionAreActualActivityScreens','recreationRestoresExactEdgeAndScale'),
 '15':('test_prices_frames_and_identity','test_monthly_freshness_is_eight_calendar_bars_not_240_days','chartTimeAxisUsesUtcAndKeepsFrameIdentityAtEveryScale'),
 '16':('test_prices_frames_and_identity','priceAxisPreservesBrokerPrecisionWithoutTruncationAcrossInstruments','equivalentSymbolFormattingDoesNotBlockTheTimeframeViewer'),
 '17':('foreignAndFutureOverlayIsRejected','test_stale_data_does_not_claim_live_catalog','connectedBridgeCannotLabelAnOldPublicationOrStaleQuoteLive'),
 '18':('brokerEntryAndStopAreVisibleOnlyForTheirActualInstrumentAndLiveView','formingEmptyStaleOfflineAndPositionAreActualActivityScreens'),
 '19':('test_reads_do_not_change_execution_or_read_mt5_again','test_display_disabled_does_not_change_actual_entry','actualActivityShowsAllNineteenNumericPatternsWithoutTrading'),
}
def _json(root,name):
 try:return json.loads((root/name).read_text(encoding='utf-8'))
 except (OSError,ValueError):return {}
def build_report(evidence_dir:Path,expected_sha:str)->dict:
 root=Path(evidence_dir);gates={f'{i:02}':dict(status='NOT_RUN',evidence=[]) for i in range(1,25)};passed=set();failures=[];count=0;xml_error=False
 for path in (root/'androidTest-results').rglob('*.xml'):
  try:
   for t in E.parse(path).getroot().iter('testcase'):
    count+=1
    if any(t.find(tag) is not None for tag in ('failure','error','skipped')):failures.append(t.get('classname','')+'.'+t.get('name',''))
    else:passed.add(t.get('name',''))
  except E.ParseError:xml_error=True
 try:log=(root/'python.log').read_text(encoding='utf-8')
 except OSError:log=''
 for name,status in re.findall(r'^(test_\S+) \([^)]+\) \.\.\. (ok|FAIL|ERROR|skipped[^\n]*)',log,re.M):
  if status=='ok':passed.add(name)
  elif not status.startswith('skipped'):failures.append(name)
 def set_gate(k,ok,evidence):gates[k]=dict(status='PASS' if ok else 'FAIL',evidence=evidence)
 for k,names in CHECKS.items():
  missing=sorted(set(names)-passed)
  if passed:set_gate(k,not missing,list(names) if not missing else ['Missing successful tests: '+', '.join(missing)])
 red=(root/'original-red.log').read_text(errors='replace') if (root/'original-red.log').is_file() else ''
 if red:set_gate('01','SERVER_FALSE_OVERRIDDEN' in red and 'serverForbidsAnalogueAfterRefresh' in passed,['original-red.log','Android serverForbidsAnalogueAfterRefresh'])
 if log:set_gate('20',bool(re.search(r'Ran \d+ tests',log) and re.search(r'^OK(?: \(skipped=1\))?$',log,re.M)) and not any(x.startswith('test_') for x in failures),['python.log; skips reported separately'])
 if count or xml_error:
  expected=_json(root,'EXPECTED_NATIVE_TESTS.json').get('tests',[])
  actual_names=set(passed)
  set_gate('21',count>=200 and not failures and not xml_error and bool(expected) and set(expected)<=actual_names,['JUnit count='+str(count),'Failures/skips='+str(failures),'manifest required='+str(len(expected))])
 win=_json(root,'WINDOWS_R732.json')
 if win:set_gate('23',win.get('ok') is True and win.get('platform')=='win32' and win.get('source_sha')==expected_sha and len(win.get('tests',{}))>=10 and all(win['tests'].values()),['WINDOWS_R732.json'])
 visual=_json(root,'VISUAL_REVIEW.json');pngs={p.name:p for p in (root/'ui').rglob('*.png')};missing=[]
 for name in PNG_NAMES:
  p=pngs.get(name);review=visual.get('files',{}).get(name,{})
  if p is None or p.read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n' or not review.get('reviewed') or review.get('sha256')!=hashlib.sha256(p.read_bytes()).hexdigest():missing.append(name)
 if pngs or visual:set_gate('22',not missing and visual.get('source_sha')==expected_sha,['Missing/unreviewed: '+', '.join(missing)] if missing else list(PNG_NAMES))
 identity=_json(root,'IDENTITY.json');upgrade=_json(root,'UPGRADE_RESULT.json');runtime=_json(root,'PACKAGE_RESULT.json')
 if identity:
  apk=root/'FXM1_R7_3_2.apk'
  match=apk.is_file() and hashlib.sha256(apk.read_bytes()).hexdigest()==identity.get('tested_apk_sha256')
  source_ok=(root/'SOURCE_COMMIT.txt').is_file() and (root/'SOURCE_COMMIT.txt').read_text().strip()==expected_sha
  ok=match and source_ok and identity.get('source_sha')==expected_sha and identity.get('certificate_sha256')==CERT and identity.get('version_code')==933 and identity.get('version_name')=='10.9-EC1-R7.3.2' and identity.get('application_id')=='com.openai.fxm1.ec1' and upgrade.get('ok') is True and upgrade.get('apk_sha256')==identity.get('tested_apk_sha256') and runtime.get('source_sha')==expected_sha
  try:
   from package_r732 import verify_bridge
   archive=root/'FXM1_R7_3_2_Bridge.zip';verified=verify_bridge(archive,expected_sha)
   ok=ok and verified['sha256']==runtime.get('sha256')
  except (OSError,ValueError,KeyError,Exception):ok=False
  set_gate('24',bool(ok),['IDENTITY.json','UPGRADE_RESULT.json','PACKAGE_RESULT.json','unpacked runtime manifest and APK checksum'])
 return dict(source_sha=expected_sha,release_allowed=all(v['status']=='PASS' for v in gates.values()),gates=gates,native_tests=count,failures=failures,scope='Emulator API35 + Windows CI + synthetic broker; not physical user devices or live executions')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('evidence');p.add_argument('source');a=p.parse_args();r=build_report(Path(a.evidence),a.source)
 Path(a.evidence,'R732_RESULT.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps({k:v['status'] for k,v in r['gates'].items()},indent=2));raise SystemExit(0 if r['release_allowed'] else 1)
