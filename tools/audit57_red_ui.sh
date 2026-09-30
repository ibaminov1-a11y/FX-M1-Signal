#!/usr/bin/env bash
# Run current native regression tests against the unchanged R5.6 presentation code.
set -euo pipefail
mkdir -p evidence/r57-red
files=(EventClient MainActivity ScenarioUi)
source_backup=$(mktemp -d)
restore() {
  for name in "${files[@]}"; do
    if [ -f "$source_backup/$name.java" ]; then
      cp "$source_backup/$name.java" "app/src/main/java/com/openai/fxm1/$name.java"
    fi
  done
  rm -rf "$source_backup"
}
trap restore EXIT
for name in "${files[@]}"; do
  source="app/src/main/java/com/openai/fxm1/$name.java"
  cp "$source" "$source_backup/$name.java"
  git show "a983ee1293647e2d312c55af13bd14c0b1723a8e:$source" > "$source"
done
# Remove generated results so a compilation failure cannot reuse stale test XML.
rm -rf app/build/outputs/androidTest-results
set +e
gradle --no-daemon --stacktrace :app:connectedDebugAndroidTest \
  '-Pandroid.testInstrumentationRunnerArguments.class=com.openai.fxm1.R57ScalpUiTest#journalExplainsNestedAnalysisAndCommandWithoutDumpingCredentials,com.openai.fxm1.R57ScalpUiTest#executionRequirementPrecedesHypothesesAndHasExactTradePrices' \
  > evidence/r57-red/android.log 2>&1
red_rc=$?
set -e
cat evidence/r57-red/android.log
test "$red_rc" -ne 0
test -d app/build/outputs/androidTest-results
cp -r app/build/outputs/androidTest-results evidence/r57-red/results
python - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
cases = []
for path in Path('evidence/r57-red/results').rglob('TEST-*.xml'):
    cases.extend(ET.parse(path).getroot().iter('testcase'))
expected = {
    'journalExplainsNestedAnalysisAndCommandWithoutDumpingCredentials': 'Journal must explain WAIT:',
    'executionRequirementPrecedesHypothesesAndHasExactTradePrices': 'Execution requirement must precede observer hypotheses:',
}
assert len(cases) == len(expected), [(case.get('name'), case.attrib) for case in cases]
assert {case.get('name') for case in cases} == set(expected)
for case in cases:
    assert case.find('error') is None and case.find('skipped') is None, case.attrib
    failure = case.find('failure')
    assert failure is not None, case.get('name')
    message = failure.get('message', '') + ' ' + (failure.text or '')
    assert expected[case.get('name')] in message, message
Path('evidence/R57_RED_UI_CONFIRMED.txt').write_text(
    'R5.6 presentation baseline a983ee1293647e2d312c55af13bd14c0b1723a8e: '
    'two actual native assertion failures reproduced: empty nested ANALYSIS/COMMAND journal '
    'and missing active SCALP M1 execution requirement. Identical tests are in the current GREEN suite.\n',
    encoding='utf-8')
PY
restore
trap - EXIT
