from pathlib import Path
import json,re,xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1];e=root/'evidence'
cases=[]
for p in (root/'app/build/outputs/androidTest-results').rglob('TEST-*.xml'):
    cases.extend(ET.parse(p).getroot().iter('testcase'))
assert cases and not any(c.find(x) is not None for c in cases for x in ('failure','error','skipped'))
rows=[dict(classname=c.get('classname'),name=c.get('name')) for c in cases]
for name in ('R56TimeframesUiTest','R56ChartSemanticsTest','R55ControlsUiTest','R54RefreshUiTest','R54ChartUiTest'):
    assert any(x['classname'].endswith(name) for x in rows),name
(e/'ANDROID_TESTS.json').write_text(json.dumps(rows,indent=2))
match=re.search(r'Ran (\d+) tests',(e/'python-tests.log').read_text());assert match
(e/'R56_REPORT_RU.md').write_text(f'''# R5.6 build925

Python: {match.group(1)} тестов. Android API35: {len(cases)} тестов, без ошибок и пропусков.
Полный список: ANDROID_TESTS.json. Исходный commit: COMMIT.txt.

Проверены независимый просмотр периодов, M30, разметка текущей свечи, обновление времени данных, отказ от подмены выбранного периода запоздалым ответом, сохранение действующего торгового профиля при просмотре других графиков. Полная предыдущая Android-проверка включена в этот запуск.

Сервер проверяется с имитатором MT5; интерфейс — на Android-эмуляторе с настоящим HTTP/Engine. Физический телефон и терминал пользователя не подключались. Это проверка программного поведения, не проверка доходности и не рыночный бэктест.
''',encoding='utf-8')
