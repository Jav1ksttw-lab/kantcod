# Сценарий демо-видео (до 3 минут)

Файл для сдачи: `docs/demo.mp4` (записать перед отправкой, ссылка/доступ — без запроса у жюри).

1. **0:00–0:30.** Запуск установки и самопроверки:
   ```
   python -m pip install -r requirements.txt
   python -m src.cli check
   ```
   Показать, что обработка начинается в `src/cli.py`, расписание лежит в `config/config.json`.

2. **0:30–1:10.** Рабочий режим с реальным API:
   ```
   python -m src.cli run --max 20 --pages 2
   ```
   Показать в логе: загружено 2 страницы, отчёт сохранён в `data/reports/report.json`, число замечаний. Открыть `report.json`.

3. **1:10–1:50.** Где применяется ИИ: открыть `src/analyzer.py` и `src/prompt.py`, показать вызов провайдера, валидацию цитат и то, что модель получает структурированные поля и уже найденные правила. Показать `ai.provider` в отчёте.

4. **1:50–2:25.** Проверочный режим без портала и без покупки аккаунта:
   ```
   python -m src.cli verify --ai ollama --input data/sample/training_vacancies.json --output data/reports/report_verify_ai.json
   ```
   Показать замечание «гибкий график» и пустой массив для вакансии без проблем.

5. **2:25–2:50.** Доп. сценарий (если показываете):
   ```
   python -m src.cli resume --vacancy-id train-003 --input data/sample/training_vacancies.json --ai ollama
   ```
   Открыть `data/reports/resume_draft.md`.

6. **2:50–3:00.** Итог: один отчёт на ID, сохранение последнего успешного отчёта при недоступности API, ссылка на README.
