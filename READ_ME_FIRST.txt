FX M1 BOT V9.5 FINAL — ROBUST

Эта версия исправляет сам updater:
- GREEN_CAPTURE заменяется точным цельным блоком, включая старый else;
- basket lock заменяется точным цельным блоком;
- перед созданием Bridge выполняется аудит: старые GREEN CAP / lost_green / early_probe запрещены;
- затем bridge_v9_5.py обязательно проходит py_compile;
- если хотя бы одна проверка не прошла, V9.5 не создаётся.

Скопируй содержимое этой папки FX-M1-Signal в корень проекта с заменой
APPLY_V9_5_FINAL.py / APPLY_V9_5_FINAL.bat.

Потом запусти APPLY_V9_5_FINAL.bat.

Правильный конец:
OK: V9.5 source audit: old Green Cap / early probe absent
OK: bridge_v9_5.py py_compile
DONE: FX M1 BOT V9.5 FINAL
