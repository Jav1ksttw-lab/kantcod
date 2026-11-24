# Прозрачная вакансия

Сервис проверяет вакансии Калининградской области с портала «Работа в России». Он показывает редактору, какие условия могут быть непонятны соискателю, цитирует карточку и предлагает конкретный вопрос работодателю.

Проверяются название должности, обязанности, требования, зарплата, график, место работы и тип занятости. Сервис сопоставляет структурированные поля с текстом карточки и обрабатывает вакансии всех работодателей, которых возвращает API региона 39.

- [Демо до 3 минут](docs/demo.mp4)
- [Пример JSON-отчёта с локальным ИИ](data/reports/report_example.json)
- [Учебные вакансии](data/sample/training_vacancies.json)
- [Точка входа обработки](src/cli.py)

## Установка и проверка

Требуется Python 3.10 или новее. Создайте виртуальное окружение и активируйте его через `source .venv/bin/activate` в Linux/macOS или `.venv\Scripts\Activate.ps1` в Windows PowerShell.

```sh
python -m venv .venv
```

После активации установите зависимости и выполните самопроверку.

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.cli check
```

`check` проверяет формат отчёта на учебных карточках без сетевых запросов. Зависимости перечислены в [requirements.txt](requirements.txt).

## Проверочный режим с ИИ

Установите [Ollama](https://ollama.com/download). Запустите приложение или `ollama serve` на отдельном терминале, если сервер ещё не запущен. После одноразовой загрузки весов обработка выполняется локально. Аккаунт и ключи не требуются.

```sh
ollama pull qwen2.5:3b
python -m src.cli verify --ai ollama --strict-ai --input data/sample/training_vacancies.json --output data/reports/report_verify.json
```

Подставьте путь к JSON жюри в `--input`. Команда обрабатывает все карточки из `results.vacancies`, независимо от лимита рабочего режима. Повторные ID дают одну запись в отчёте. `--strict-ai` выдаёт ошибку при сбое модели и сохраняет уже существующий файл отчёта.

### Локальный запуск через llama.cpp

Опубликованный пример и демо записаны с **Qwen2.5-3B-Instruct (Q4_K_M) через llama.cpp**. Скачайте [llama.cpp](https://github.com/ggml-org/llama.cpp/releases/tag/b12686) и [файл GGUF](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf) объёмом около 2 ГБ. Эта команда запускает сервер на локальном порту 18080.

```sh
llama-server --model qwen2.5-3b-instruct-q4_k_m.gguf --alias qwen2.5-3b-instruct --host 127.0.0.1 --port 18080 --ctx-size 8192 --parallel 2
```

Из корня репозитория запустите проверку в другом терминале.

```sh
python -m src.cli verify --ai llamacpp --strict-ai --input data/sample/training_vacancies.json --output data/reports/report_verify.json
```

Также поддерживается GigaChat (Сбер, модель `GigaChat`). Передайте `GIGACHAT_CLIENT_ID` и `GIGACHAT_CLIENT_SECRET` или `GIGACHAT_ACCESS_TOKEN` через окружение или локальный `.env`. При необходимости задайте путь к доверенному набору сертификатов в `GIGACHAT_CA_BUNDLE`. Пример переменных приведён в [.env.example](.env.example).

## Ручной запуск и расписание

```sh
python -m src.cli run --ai ollama --strict-ai
python -m src.cli schedule --ai ollama --strict-ai --now
```

`schedule` держит процесс запущенным и ежедневно в **09:00 по Калининграду** вызывает ту же обработку, что и `run`. Флаг `--now` также запускает её сразу. Для быстрого прогона на двух страницах используйте `run --max 4 --ai ollama --strict-ai`. Для диагностики загрузки и формата можно явно выбрать `--ai rules`.

| Настройка в [config/config.json](config/config.json) | Значение | Переменная окружения |
| --- | --- | --- |
| `source_url` | HTTPS API региона 39 | `VACANCY_SOURCE_URL` |
| `schedule` | `0 9 * * *` | `VACANCY_SCHEDULE` |
| `timezone` | `Europe/Kaliningrad` | |
| `max_vacancies` | 50 уникальных карточек | `VACANCY_MAX` |
| `page_size` | До 25 карточек на странице | |
| `max_pages` | До 20 запросов на запуск | |
| `ai.provider` | `ollama` | `AI_PROVIDER` |
| `ai.workers` | 4 параллельных задания | |
| `paths` | Файлы под `data/reports/` | |

Пагинация использует `offset` как номер страницы, начиная с нуля. При сбое API после повторных попыток команда возвращает код 1 и фиксирует причину в `last_run.json`. Рабочий отчёт `report.json` и копия `report.last_success.json` сохраняют предыдущие данные. При успехе JSON заменяется целиком, а статус обновляется. Последний успешный вход в `last_input.json` можно передать обратно в `verify` или `resume`.

## Как ИИ влияет на отчёт

[Правила](src/facts.py) учитывают структурированные поля и описание, фиксируют пропуски и проверяемые противоречия, например расхождение сумм. Для возможных неоднозначностей [анализатор](src/analyzer.py) передаёт модели поля карточки и цитаты с вопросами. Модель решает, какие вопросы остаются открытыми с учётом всех полей. Например, при «гибком графике» она решает, нужно ли уточнить дни и часы. Анализатор принимает только номера предложенных вопросов, поэтому в отчёте остаются цитаты из карточки и подготовленные рекомендации. Подтверждённые моделью замечания получают `origin: "ai"` и учитываются в `stats.ai_findings`.

### Формат JSON

- `mode`, `generated_at`, `source` и `ai` показывают, когда и как сформирован отчёт. `fetch` в рабочем режиме хранит число загруженных страниц и карточек.
- `vacancies` содержит по одному объекту с полями `id`, `url` (или `null`) и `findings` на каждый уникальный ID. Для понятной карточки `findings: []`.
- Замечание содержит `kind` (`omission`, `ambiguity` или `contradiction`), `topic`, `field`, `quote`, `issue` и `recommendation`. У пропуска пустая цитата. У противоречия `values` содержит две исходные цитаты, а `value_fields` — соответствующие им поля API в том же порядке.
- `stats` содержит число карточек, повторных ID, замечаний и ошибок ИИ. Примеры ошибок сохраняются в `ai_error_samples`, если запуск разрешает частичный результат.

## Дополнительный сценарий

Команда `resume` помогает соискателю выделить подходящие навыки и опыт для выбранной вакансии. Она передаёт модели название, обязанности и требования вакансии и нумерованные пункты исходного резюме. Модель выбирает номера, а программа собирает Markdown из исходных формулировок.

```sh
python -m src.cli resume --ai llamacpp --vacancy-id train-003 --input data/sample/training_vacancies.json
```

По умолчанию используется [вымышленное резюме](data/sample/resume.json), результат сохраняется в `data/reports/resume_draft.md`.

## Вклад участников

- [RyyZeSslayer](https://github.com/RyyZeSslayer) — исходный прототип в репозитории, включая загрузку API, анализ карточек и интеграцию GigaChat/Ollama.
- [Jav1ksttw-lab](https://github.com/Jav1ksttw-lab), доработка с Codex — исправление пагинации и обработки сбоев, проверка цитат, локальный запуск Qwen через llama.cpp, регрессионные тесты и демонстрация.
