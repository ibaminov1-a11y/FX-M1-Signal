FX M1 Bot V5.5 — JARVIS AI

Что добавлено
=============
1. JARVIS-карточка прямо в приложении.
2. Можно писать JARVIS текстом.
3. Можно нажать "ГОВОРИТЬ" и говорить по-русски.
4. JARVIS получает контекст FX Bot:
   - инструмент;
   - таймфрейм;
   - режим сигнала;
   - WAIT / BUY / SELL;
   - качество;
   - Entry / SL / TP;
   - структуру рынка;
   - состояние мониторинга;
   - MT5 / счёт / позиции;
   - риск и AUTO.
5. Если AI-сервер подключён:
   - ответ формирует reasoning-модель OpenAI;
   - сохраняется история разговора в SQLite;
   - сервер генерирует естественный голос;
   - Android воспроизводит готовый MP3.
6. Если AI-сервер ещё не настроен:
   - JARVIS остаётся в LOCAL MODE;
   - умеет озвучить статус;
   - объяснить WAIT из текущего контекста;
   - сообщить позиции;
   - запустить/остановить мониторинг;
   - выполнить EMERGENCY STOP.
7. В фоновом уведомлении теперь:
   JARVIS | СТОП | EMERGENCY
8. Кнопка JARVIS из уведомления открывает приложение и включает голосовой ввод.
9. OpenAI API key НИКОГДА не хранится в APK.
10. V5.4 background monitoring, кэширование и торговые safeguards сохранены.

Файлы Android
=============
Заменить:
app/src/main/java/com/openai/fxm1/MainActivity.java
app/src/main/java/com/openai/fxm1/MonitoringService.java
app/src/main/res/layout/activity_main.xml
app/src/main/AndroidManifest.xml

GitHub Desktop Summary:
V5.5 Jarvis AI voice assistant

AI backend
==========
Файл:
backend/jarvis_ai_server.py

На личном PC/VPS позже:
1. Установить Python.
2. pip install -r requirements_jarvis.txt
3. Задать OPENAI_API_KEY как переменную окружения.
4. python jarvis_ai_server.py
5. В приложении указать защищённый адрес сервера.

ВАЖНО
=====
- Не вставлять OPENAI_API_KEY в MainActivity.java, GitHub или APK.
- Текущий репозиторий публичный, поэтому секреты туда не коммитить.
- Голос настроен как спокойный, низкий, мужской, с лёгкой британской манерой,
  сухим юмором и сдержанной подачей. Это НЕ копия голоса конкретного актёра.
- Настоящий continuous wake-word "JARVIS" без нажатия кнопки оставлен на следующий этап:
  он требует отдельного always-listening аудиомодуля и более строгой работы с Android battery/privacy.
