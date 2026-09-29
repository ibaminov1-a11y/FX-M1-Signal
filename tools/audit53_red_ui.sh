#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence/r53-red
files=(EventClient MainActivity MonitoringService ScenarioMapRenderer ScenarioUi SparklineView)
new_tests=$(mktemp -d)
restore() {
  for name in "${files[@]}"; do git restore --source=HEAD -- "app/src/main/java/com/openai/fxm1/$name.java"; done
  for test in "$new_tests"/*.java; do
    if [ -f "$test" ]; then mv "$test" app/src/androidTest/java/com/openai/fxm1/; fi
  done
  rmdir "$new_tests"
}
trap restore EXIT
# R5.4 tests use the new refresh API; this historical reproduction compiles
# only tests compatible with the original build921, then restores every test.
for test in app/src/androidTest/java/com/openai/fxm1/R54*Test.java app/src/androidTest/java/com/openai/fxm1/R55*Test.java; do
  if [ -f "$test" ]; then mv "$test" "$new_tests/"; fi
done
for name in "${files[@]}"; do git show "1b2c4a02a912ec76c06954bab36bb68e558d2b96:app/src/main/java/com/openai/fxm1/$name.java" > "app/src/main/java/com/openai/fxm1/$name.java"; done
set +e
gradle --no-daemon :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R53ControlsUiTest#scalpSelectionReachesBridgeAndSurvivesActivityRecreation,com.openai.fxm1.R53ScenarioDisplayUiTest#sellRisesInNeutralPreparationThenFallsInRed,com.openai.fxm1.R53ControlsUiTest#offlineCachedForecastIsExplicitAndRecoveryRestoresLive' > evidence/r53-red/android.log 2>&1
rc=$?
set -e
cp -r app/build/outputs/androidTest-results evidence/r53-red/results
python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
cases=[]
for p in Path('evidence/r53-red/results').rglob('TEST-*.xml'):cases.extend(ET.parse(p).getroot().iter('testcase'))
assert len(cases)==3,[(x.get('name'),x.find('failure') is not None) for x in cases]
expected={'scalpSelectionReachesBridgeAndSurvivesActivityRecreation':'Selected SCALP must reach actual Bridge config','sellRisesInNeutralPreparationThenFallsInRed':'initial move toward the zone must be neutral','offlineCachedForecastIsExplicitAndRecoveryRestoresLive':'Cached forecast must not be labelled LIVE'}
for case in cases:
    failure=case.find('failure');assert failure is not None,case.get('name')
    assert expected[case.get('name')] in (failure.get('message','')+' '+(failure.text or '')),ET.tostring(case)
Path('evidence/RED_UI_CONFIRMED.txt').write_text('Build921 reproduced: selected SCALP sent NORMAL; SELL preparation drawn red; offline forecast labelled LIVE. Same runtime tests rerun against fixed build.\n')
PY
restore
trap - EXIT
