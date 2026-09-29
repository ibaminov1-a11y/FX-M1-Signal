#!/usr/bin/env bash
set -euo pipefail
mkdir -p evidence/r56-red
files=(EventClient MainActivity ScenarioMapRenderer ScenarioUi SparklineView)
new_sources=$(mktemp -d)
restore() {
  for name in "${files[@]}"; do git restore --source=HEAD -- "app/src/main/java/com/openai/fxm1/$name.java"; done
  for source in "$new_sources"/*.java; do
    if [ -f "$source" ]; then mv "$source" app/src/main/java/com/openai/fxm1/; fi
  done
  rmdir "$new_sources"
}
trap restore EXIT
for name in TimeframeViewer Timeframes; do mv "app/src/main/java/com/openai/fxm1/$name.java" "$new_sources/"; done
for name in "${files[@]}"; do git show "24e280c6dfc87b239e21dd7863266c8b6e741922:app/src/main/java/com/openai/fxm1/$name.java" > "app/src/main/java/com/openai/fxm1/$name.java"; done
set +e
gradle --no-daemon :app:connectedDebugAndroidTest '-Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R56ChartSemanticsTest,com.openai.fxm1.R56TimeframesUiTest#chartFramesHaveIndependentForecastsWithoutChangingTradeProfile,com.openai.fxm1.R56TimeframesUiTest#oldNumericEntryPreferencesPreserveTheirNamedFrames' > evidence/r56-red/android.log 2>&1
set -e
cp -r app/build/outputs/androidTest-results evidence/r56-red/results
python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
cases=[]
for p in Path('evidence/r56-red/results').rglob('TEST-*.xml'):cases.extend(ET.parse(p).getroot().iter('testcase'))
expected={'falseReturnDoesNotAdvertiseUnrelatedGenericEntryLevels':'Generic SELL',
          'repeatedHypothesisStillDisplaysItsOwnFrameAndNewDataTime':'Chart must show',
          'chartFramesHaveIndependentForecastsWithoutChangingTradeProfile':'Independent chart timeframe chooser',
          'oldNumericEntryPreferencesPreserveTheirNamedFrames':'M10'}
assert len(cases)==len(expected),[(c.get('name'),c.find('failure') is not None) for c in cases]
for case in cases:
    failure=case.find('failure');assert failure is not None,case.get('name')
    assert expected[case.get('name')] in (failure.get('message','')+' '+(failure.text or '')),ET.tostring(case)
Path('evidence/R56_RED_UI_CONFIRMED.txt').write_text('Original R5.5 reproduced: misleading entry levels; missing data timestamp; missing independent chart choice; M10 still offered and M30 absent. Same tests rerun against R5.6.\n')
PY
restore
trap - EXIT
