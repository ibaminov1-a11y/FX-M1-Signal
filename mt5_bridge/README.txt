Исправляет SyntaxError в bridge_v9_3.py.

1. Копируешь содержимое ZIP в корень FX-M1-Signal.
2. Запускаешь FIX_BRIDGE_V9_3.bat.
3. Скрипт сам берёт чистый bridge_v9_2.py из последнего _V9_2_BACKUP_*.
4. Целиком заменяет _scalp_entry_state корректной V9.3-логикой.
5. Добавляет /live-state.
6. СНАЧАЛА делает py_compile всего bridge_v9_3.py.
7. Только если compile успешен — сохраняет рабочий bridge_v9_3.py.
8. Затем запускаешь mt5_bridge\START_BRIDGE_V9_3.bat.
