# Парсер данных о банкротстве

Парсер собирает данные о банкротстве физических лиц с двух источников:
- **fedresurs.ru** — по ИНН находит номер дела о банкротстве
- **kad.arbitr.ru** — по номеру дела находит последний документ и дату

---

## Архитектура

```
xlsx (ИНН) → main.py → pipeline.py
                           │
                    fedresurs.py (aiohttp)
                    ИНН → guid → номер дела
                           │
                    kad.py (Selenium)
                    номер дела → дата + документ
                           │
                    PostgreSQL (SQLAlchemy)
```

### Почему такой подход к интеграции сервисов

**fedresurs.ru** использует открытый REST API без авторизации. Все данные
доступны через обычные GET запросы — браузер не нужен. Используем `aiohttp`
с семафором для параллельных запросов и экспоненциальным retry.

**kad.arbitr.ru** защищён DDoS Guard с WebAssembly верификацией. Headless
браузеры (Playwright, обычный Selenium) детектируются на уровне wasm и
получают 451. Решение — `undetected-chromedriver` с `pyvirtualdisplay`
(виртуальный дисплей вместо headless). Браузер создаётся один раз и
переиспользуется для всех дел.

**Resume (докачка)** реализован через таблицу `inn_records` со статусами
`pending / processing / done / error`. При повторном запуске обрабатываются
только незавершённые ИНН.

---

## Стек

| Компонент | Технология |
|-----------|-----------|
| Язык | Python 3.12 |
| fedresurs парсер | aiohttp + asyncio |
| kad парсер | undetected-chromedriver + selenium |
| ORM | SQLAlchemy 2.0 |
| БД | PostgreSQL 16 |
| Миграции | Alembic |
| Настройки | pydantic-settings |
| Деплой | Docker + docker-compose |

---

## Структура проекта

```
parser/
├── data/                   # xlsx файлы с ИНН (монтируется в Docker)
├── logs/                   # логи с ротацией (монтируется в Docker)
├── db/
│   ├── models.py           # SQLAlchemy модели
│   └── session.py          # подключение к БД, контекст менеджеры
├── parsers/
│   ├── fedresurs.py        # парсер fedresurs.ru
│   └── kad.py              # парсер kad.arbitr.ru
├── services/
│   └── pipeline.py         # связывает парсеры, сохраняет в БД
├── config.py               # настройки из .env
├── logging_config.py       # настройка логирования с ротацией
├── main.py                 # точка входа
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                    # переменные окружения (не коммитить!)
└── .env.example            # шаблон для .env
```

---

## Быстрый старт

### 1. Клонируй репозиторий

```bash
git clone <repo_url>
cd parser
```

### 2. Создай необходимые папки

```bash
mkdir -p data logs
```

- `data/` — сюда кладёшь xlsx файл с ИНН (не попадает в git)
- `logs/` — сюда пишутся логи с ротацией (не попадает в git)

### 3. Создай .env файл

```bash
cp .env.example .env
# Отредактируй .env если нужно изменить настройки
```

### 4. Подготовь xlsx файл с ИНН

Создай файл `data/inns.xlsx` с ИНН в первом столбце:

| A |
|---|
| ИНН |
| 999999999999 |
| 777777777777 |

### 5. Запусти через Docker

```bash
docker-compose up --build
```

Всё поднимается одной командой — PostgreSQL + парсер.

---

## Локальный запуск (без Docker)

### 1. Создай виртуальное окружение

```bash
python -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows
```

### 2. Установи зависимости

```bash
pip install -r requirements.txt
```

### 3. Запусти PostgreSQL

```bash
# Через Docker только БД
docker-compose up db -d
```

### 4. Настрой .env

```bash
cp .env.example .env
# DB_HOST=localhost  ← для локального запуска
```

### 5. Запусти парсер

```bash
python main.py data/inns.xlsx
```

---

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `DB_HOST` | `db` | Хост PostgreSQL (`localhost` для локального запуска) |
| `DB_PORT` | `5432` | Порт PostgreSQL |
| `DB_NAME` | `parser` | Имя базы данных |
| `DB_USER` | `postgres` | Пользователь БД |
| `DB_PASSWORD` | `postgres` | Пароль БД |
| `DB_ECHO` | `false` | Логировать SQL запросы |
| `CHROME_VERSION` | `145` | Версия Chrome для undetected-chromedriver |
| `CHROME_HEADLESS` | `true` | Headless режим (не используется, см. pyvirtualdisplay) |
| `DELAY_BETWEEN_CASES` | `2.0` | Задержка между делами в kad.arbitr.ru (сек) |
| `DELAY_BETWEEN_INNS` | `1.5` | Задержка между ИНН в fedresurs.ru (сек) |
| `MAX_CONCURRENT_INNS` | `3` | Параллельных запросов к fedresurs.ru |
| `MAX_RETRIES` | `3` | Попыток при ошибке |
| `RETRY_BASE_DELAY` | `2` | База экспоненциальной задержки (сек) |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `LOG_FILE` | `logs/parser.log` | Путь к файлу логов |
| `LOG_MAX_BYTES` | `10485760` | Максимальный размер лог файла (10 MB) |
| `LOG_BACKUP_COUNT` | `5` | Количество файлов ротации |

---

## Resume (докачка)

Парсер поддерживает продолжение с места остановки. При повторном запуске
обрабатываются только ИНН со статусом `pending`, `error` или `processing`.
Успешно обработанные (`done`) пропускаются.

Статусы в таблице `inn_records`:

| Статус | Описание |
|--------|----------|
| `pending` | Ожидает обработки |
| `processing` | В процессе (если процесс упал — будет повторен) |
| `done` | Успешно обработан |
| `error` | Ошибка — будет повторен при следующем запуске |

---

## Результаты

Результаты сохраняются в таблице `parse_results`:

| Поле | Описание |
|------|----------|
| `inn` | ИНН физлица |
| `person_name` | ФИО (fedresurs.ru) |
| `case_number` | Номер дела о банкротстве (fedresurs.ru) |
| `fed_last_date` | Последняя дата публикации (fedresurs.ru) |
| `kad_last_date` | Последняя дата документа (kad.arbitr.ru) |
| `document_name` | Наименование последнего документа (kad.arbitr.ru) |
| `parsed_at` | Время парсинга |
