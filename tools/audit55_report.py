from pathlib import Path
import json,re,xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1];e=root/'evidence'
cases=[]
for p in (root/'app/build/outputs/androidTest-results').rglob('TEST-*.xml'):
    cases.extend(ET.parse(p).getroot().iter('testcase'))
assert cases and not any(c.find(x) is not None for c in cases for x in ('failure','error','skipped'))
rows=[dict(classname=c.get('classname'),name=c.get('name')) for c in cases]
assert any(x['classname'].endswith('R55ControlsUiTest') for x in rows)
assert any(x['classname'].endswith('R54RefreshUiTest') for x in rows)
(e/'ANDROID_TESTS.json').write_text(json.dumps(rows,indent=2))
match=re.search(r'Ran (\d+) tests',(e/'python-tests.log').read_text());n=match.group(1) if match else '?'
(e/'R55_REPORT_RU.md').write_text(f'''# R5.5 build924

Python: {n} тестов. Android API35: {len(cases)} тестов, без ошибок и пропусков.
Названия проверок: ANDROID_TESTS.json и журналы. Точный commit: COMMIT.txt.

Исправлены принудительный M5, блокировка выбора при AUTO, потеря явного выбора при опросе Bridge, применение профиля при остановленном мониторинге. Во время кампании следующий профиль показывается отдельно от действующего.
Расчёт Scenario V2 использует выбранный таймфрейм и его текущую свечу, масштабирует сроки сценариев и учитывает календарную границу MN1.
История MT5 запрашивается с запасом даты, сохраняя исходные записи и исключая двойной учёт. Явная привязанная к счёту настройка времени нормализует свечи, тики и сделки; предположение по возрасту котировки не используется.

Свайп и фоновый опрос обновляют данные с проверкой источника. AUTO и тип счёта различаются; REAL-исполнение отключено в адаптере.

Проверялся эмулятор с настоящим Engine/HTTP и имитатором MT5. Физический телефон и терминал пользователя не подключались. Не бэктест. Прогноз требует пригодных рыночных данных и подтверждённой настройки часов, если терминал использует серверное время.
''',encoding='utf-8')
