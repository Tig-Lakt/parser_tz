import asyncio
import logging
import random

import aiohttp


log = logging.getLogger(__name__)


_BASE_URL = "https://fedresurs.ru/backend"


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


# HTTP helpers

def _make_headers(inn: str | None = None) -> dict:
    """
    Собирает заголовки запроса.
    Referer строится динамически из ИНН — имитирует реальный переход
    со страницы поиска на страницу результатов.
    """
    referer = (
        f"https://fedresurs.ru/entities?searchString={inn}"
        f"&regionNumber=all&isActive=true&offset=0&limit=15"
        if inn else "https://fedresurs.ru/"
    )
    return {
        "accept":             "application/json, text/plain, */*",
        "cache-control":      "no-cache",
        "pragma":             "no-cache",
        "referer":            referer,
        "sec-ch-ua":          '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "sec-ch-ua-mobile":   "?0",
        "sec-ch-ua-platform": '"Windows"',
        "user-agent":         random.choice(_USER_AGENTS),
    }


async def _safe_get(
    session: aiohttp.ClientSession,
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
) -> dict | None:
    """
    GET-запрос с retry и экспоненциальной задержкой.
    Настройки retry берутся из config.py.
    """
    from config import settings

    for attempt in range(1, settings.max_retries + 1):
        try:
            async with session.get(url, params=params, headers=headers or _make_headers()) as resp:
                if resp.status == 429:
                    wait = settings.retry_base_delay ** attempt
                    log.warning(f"    [!] 429 Too Many Requests — ждём {wait}с (попытка {attempt}/{settings.max_retries})")
                    await asyncio.sleep(wait)
                    continue
                if resp.status == 404:
                    log.warning(f"    [!] 404 Not Found: {url}")
                    return None
                resp.raise_for_status()
                return await resp.json()

        except aiohttp.ClientError as e:
            wait = settings.retry_base_delay ** attempt
            log.warning(f"    [!] Ошибка сети (попытка {attempt}/{settings.max_retries}): {e} — повтор через {wait}с")
            await asyncio.sleep(wait)

    log.error(f"    [✗] Все {settings.max_retries} попытки исчерпаны: {url}")
    return None


# API calls

async def get_person_by_inn(session: aiohttp.ClientSession, inn: str) -> dict | None:
    """Шаг 1 — ищем физлицо по ИНН, получаем guid."""
    log.info(f"Поиск по ИНН: {inn}")
    data = await _safe_get(
        session,
        url=f"{_BASE_URL}/persons",
        params={"searchString": inn, "limit": 15, "offset": 0, "isActive": "true"},
        headers=_make_headers(inn),
    )
    if not data or data.get("found", 0) == 0:
        log.warning(f"  [!] ИНН {inn} не найден в базе физлиц")
        return None

    person = data["pageData"][0]
    log.info(f"  [+] Найден: {person['name']} (guid: {person['guid']})")
    return person


async def get_person_details(session: aiohttp.ClientSession, guid: str) -> dict | None:
    """
    Шаг 2 — профиль физлица по guid.
    Пока не используется в pipeline, но оставлен для возможного
    расширения (адрес, СНИЛС и др.).
    """
    log.info(" Получаем профиль...")
    return await _safe_get(session, f"{_BASE_URL}/persons/{guid}", headers=_make_headers())


async def get_bankruptcy(session: aiohttp.ClientSession, guid: str) -> dict | None:
    """Шаг 3 — данные о банкротстве по guid."""
    log.info(" Получаем данные о банкротстве...")
    return await _safe_get(session, f"{_BASE_URL}/persons/{guid}/bankruptcy", headers=_make_headers())


# Extract

def extract_case_info(bankruptcy: dict) -> dict | None:
    """
    Извлекаем номер дела и последнюю дату из legalCases.
    Берём первое дело — оно самое актуальное.
    """
    legal_cases = bankruptcy.get("legalCases", [])
    if not legal_cases:
        return None

    case = legal_cases[0]
    case_number = case.get("number")

    last_date = None
    last_publications = case.get("lastPublications", [])
    if last_publications:
        raw_date = last_publications[0].get("datePublish", "")
        last_date = raw_date[:10] if raw_date else None

    return {
        "case_number": case_number,
        "last_date":   last_date,
    }


# Core

async def process_inn(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    inn: str,
) -> dict:
    """
    Обрабатывает один ИНН — возвращает результат или ошибку.
    Используется в pipeline.py как основная единица работы.
    """
    from config import settings

    async with semaphore:
        log.info(f"\n{'─' * 50}")
        log.info(f"Обрабатываем ИНН: {inn}")

        result = {
            "inn":         inn,
            "name":        None,
            "case_number": None,
            "last_date":   None,
            "error":       None,
        }

        try:
            person = await get_person_by_inn(session, inn)
            if not person:
                result["error"] = "Не найден в базе физлиц"
                return result

            result["name"] = person["name"]

            await get_person_details(session, person["guid"])

            bankruptcy = await get_bankruptcy(session, person["guid"])
            if bankruptcy:
                case_info = extract_case_info(bankruptcy)
                if case_info:
                    result["case_number"] = case_info["case_number"]
                    result["last_date"]   = case_info["last_date"]
                else:
                    result["error"] = "Дел о банкротстве не найдено"
            else:
                result["error"] = "Не удалось получить данные о банкротстве"

        except Exception as e:
            log.exception(f"  [✗] Неожиданная ошибка для ИНН {inn}: {e}")
            result["error"] = str(e)

        await asyncio.sleep(settings.delay_between_inns)
        return result


async def run(inn_list: list[str]) -> list[dict]:
    """
    Точка входа для запуска парсера из pipeline.py.
    Возвращает список результатов для сохранения в БД.
    """
    from config import settings

    semaphore = asyncio.Semaphore(settings.max_concurrent_inns)

    async with aiohttp.ClientSession() as session:
        tasks = [process_inn(session, semaphore, inn) for inn in inn_list]
        return await asyncio.gather(*tasks)