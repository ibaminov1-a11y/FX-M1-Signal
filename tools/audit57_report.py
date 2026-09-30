"""Validate actual R5.7 execution evidence and write a count-derived release report."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET

REQUIRED_CLASSES = (
    'R57ScalpUiTest', 'R56ConcurrencyUiTest', 'R56TimeframesUiTest',
    'R56ChartSemanticsTest', 'R55ControlsUiTest', 'EventCoreUiTest',
    'CampaignSignalUiTest', 'ScenarioMapUiTest', 'ScenarioUpgradeUiTest',
    'R5SettingsHistoryTest', 'R5RedContractUiTest', 'R51RepairUiTest',
    'LiveLayoutUiTest', 'R53ControlsUiTest', 'R53ScenarioDisplayUiTest',
    'R54RefreshUiTest', 'R54ChartUiTest',
)


def read_results(root, required_classes=REQUIRED_CLASSES):
    root = Path(root)
    log = (root / 'evidence/python-tests.log').read_text(encoding='utf-8')
    summaries = list(re.finditer(r'^Ran (\d+) tests? in [^\n]+\n', log, re.M))
    if not summaries or log[summaries[-1].end():].strip() != 'OK':
        raise ValueError('Python full suite did not finish with an unqualified OK')
    python_count = int(summaries[-1].group(1))
    if python_count <= 0:
        raise ValueError('Python test results are empty')
    rows = []
    for path in sorted((root / 'app/build/outputs/androidTest-results').rglob('TEST-*.xml')):
        tree = ET.parse(path).getroot()
        for suite in tree.iter('testsuite'):
            if any(int(suite.get(name, '0')) for name in ('failures', 'errors', 'skipped')):
                raise ValueError('Android suite contains failures, errors or skips: ' + str(path))
        for case in tree.iter('testcase'):
            if any(case.find(status) is not None for status in ('failure', 'error', 'skipped')):
                raise ValueError('Android case failed or skipped: ' + str(case.attrib))
            rows.append({'classname': case.get('classname', ''), 'name': case.get('name', '')})
    if not rows:
        raise ValueError('Android test results are empty')
    identities = {(row['classname'], row['name']) for row in rows}
    if len(identities) != len(rows):
        raise ValueError('Android duplicate results would inflate the reported count')
    for name in required_classes:
        if not any(row['classname'].split('.')[-1] == name for row in rows):
            raise ValueError('Missing Android regression class: ' + name)
    return {'python_tests': python_count, 'android_tests': len(rows), 'android_cases': rows}


def main():
    root = Path(__file__).resolve().parents[1]
    evidence = root / 'evidence'
    result = read_results(root)
    commit = (evidence / 'COMMIT.txt').read_text(encoding='utf-8').strip()
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Missing exact source commit')
    screenshots = sorted((evidence / 'ui').rglob('*.png'))
    if not any(path.name == 'r57-scalp-m1-requirement.png' and path.stat().st_size for path in screenshots):
        raise ValueError('Missing R5.7 native requirement screenshot')
    (evidence / 'ANDROID_TESTS.json').write_text(json.dumps(result['android_cases'], indent=2) + '\n', encoding='utf-8')
    summary = {key: value for key, value in result.items() if key != 'android_cases'}
    summary.update(commit=commit, android_api=35, android_classes=list(REQUIRED_CLASSES),
                   screenshots=[str(path.relative_to(evidence)) for path in screenshots])
    (evidence / 'R57_RESULTS.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    (evidence / 'R57_REPORT_RU.md').write_text(f'''# R5.7 build926 — SCALP M1

Python: {result['python_tests']} тестов, результат OK. Android API35: {result['android_tests']} выполненных тестов, без ошибок и пропусков.
Числа получены из python-tests.log и XML текущего запуска. Список выполненных native-тестов: ANDROID_TESTS.json; сводка: R57_RESULTS.json.
Исходный commit: `{commit}`.

Проверяются новый быстрый вход SCALP M1, подтверждение микроуровня и сохранение ограничений Engine, подробности журнала и отображение требований входа. Полный действующий EC1-набор включает регрессии R5.6 и предыдущие сценарии/управление/историю. Исторические V108RepairTest (контракт 10.8/Bridge10.0) и OwnRiskOnlyUiTest (устаревшие требования к отсутствующим настройкам риска) не входят в действующий EC1-набор.

Изображения получены native-тестами эмулятора; список файлов находится в R57_RESULTS.json. Ожидаемые воспроизведения ошибок R5.6 для новых требований сохраняются отдельно в r57-red и R57_RED_PYTHON.log и не прибавляются к числу успешно выполненных тестов. Исторический audit56_red_ui.sh не запускался: его старый commit не содержит полного дерева исходников. Все действующие R5.6 GREEN-регрессии включены в текущий запуск.

Сервер проверен с имитатором MT5; интерфейс — на Android-эмуляторе с HTTP/Engine-стендом. Физический телефон и терминал пользователя не подключались. Проверки программного поведения не являются рыночным бэктестом или подтверждением доходности. REAL отключён в адаптере.
''', encoding='utf-8')
    print(f"R57_EVIDENCE_OK python={result['python_tests']} android={result['android_tests']} commit={commit}")


if __name__ == '__main__':
    main()
