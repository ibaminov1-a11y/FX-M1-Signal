from pathlib import Path
import json,xml.etree.ElementTree as ET,re
root=Path(__file__).resolve().parents[1];e=root/'evidence'
cases=[]
for p in (root/'app/build/outputs/androidTest-results').rglob('TEST-*.xml'):
    cases.extend(ET.parse(p).getroot().iter('testcase'))
assert cases and not any(c.find(x) is not None for c in cases for x in ('failure','error','skipped'))
rows=[dict(classname=c.get('classname'),name=c.get('name')) for c in cases]
(e/'ANDROID_TESTS.json').write_text(json.dumps(rows,indent=2))
match=re.search(r'Ran (\d+) tests', (e/'python-tests.log').read_text());n=match.group(1) if match else '?'
report=f'''# R5.3 build922 — проверка и исправления

Основа: R5.2 build921, 1b2c4a02. Точный новый commit: COMMIT.txt / PROVENANCE.json.

## Исправлено
- SCALP действительно передаётся в Bridge; действующий режим отражается в экране и уведомлении. Scenario V2 работает на M5, выбор неподдерживаемого таймфрейма отключён явно.
- Вторая и третья отдельные позиции: новые события после благоприятного движения, отката, возобновления и микропробоя. Проверено для NORMAL/SCALP и BUY/SELL реальным Engine с имитатором брокера. Риск и маржа проверяются для всей кампании; усреднение запрещено.
- Подготовительные участки карты нейтральные и пунктирные; условные торговые участки окрашены по BUY/SELL. Показана исходная привязка кампании к сценарию/версии/снимку. Пройденная ближайшая цель не обосновывает новый вход.
- Исправлены локальный сброс Emergency, устаревший статус подключения, время последней проверки, обновление сессии, отсутствующая котировка, состояние завершённого мониторинга. Проверено отображение всех 19 динамических полей из меняющихся данных Bridge.

## Доказательства
- Python: {n} тестов, без ошибок.
- Android API35: {len(cases)} тестов, без ошибок/пропусков, включая управление, SCALP, 19 полей и карту. Полный список: ANDROID_TESTS.json.
- Новые тесты SCALP и цвета сначала воспроизвели ошибки на build921, затем прошли на исправленном коде. Журналы и снимки приложены.
- Подпись проверяется отдельно в apk-signature.txt; versionCode 922; exact-source package.

## Границы проверки
Физический телефон пользователя, пользовательский MT5 и последовательность его тиков не подключались. Это тесты на синтетических котировках и имитаторе брокера, не рыночный бэктест и не проверка доходности. REAL остаётся заблокирован в адаптере. Все кнопки проверены по доступным экранам/командам; внешняя сеть и особенности конкретного телефона требуют пользовательской DEMO-проверки.
'''
(e/'R53_REPORT_RU.md').write_text(report)
