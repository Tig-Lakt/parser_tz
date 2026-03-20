import re
import time
import logging

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


log = logging.getLogger(__name__)


_BASE_URL = "https://kad.arbitr.ru"


# Driver factory

def create_driver() -> uc.Chrome:
    """
    Создаёт и возвращает экземпляр undetected-chromedriver.

    Используем pyvirtualdisplay вместо --headless=new:
    сайт kad.arbitr.ru детектирует headless режим через wasm,
    виртуальный дисплей обходит эту защиту.

    Настройки берутся из config.py.
    """
    from config import settings

    # Запускаем виртуальный дисплей — только на Linux (VPS)
    # На Windows/Mac убрать этот блок
    try:
        from pyvirtualdisplay import Display
        display = Display(visible=False, size=(1920, 1080))
        display.start()
        log.info("  [+] Виртуальный дисплей запущен")
    except Exception as e:
        # На Windows pyvirtualdisplay не нужен
        log.debug(f"  pyvirtualdisplay недоступен: {e}")

    options = uc.ChromeOptions()
    options.add_argument("--disable-dev-shm-usage") 
    options.add_argument("--no-sandbox")              
    options.add_argument("--disable-gpu")          
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--memory-pressure-off")     
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")

    return uc.Chrome(options=options, version_main=settings.chrome_version)


# Navigation

def _search_case(driver: uc.Chrome, case_number: str) -> str | None:
    """
    Шаги 1-4: открываем сайт, вводим номер дела, нажимаем Найти,
    извлекаем URL карточки дела из результатов поиска.

    Возвращает URL карточки или None если дело не найдено.
    """

    log.info("1: Открываем kad.arbitr.ru...")
    driver.get(_BASE_URL)
    log.info(f"  [+] Страница: {driver.title}")
    time.sleep(5)

    log.info(f"2: Вводим номер дела: {case_number}")
    search_input = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, 'input[placeholder="например, А50-5568/08"]')
        )
    )
    search_input.clear()
    search_input.send_keys(case_number)
    time.sleep(1)

    log.info("3: Нажимаем кнопку Найти...")
    submit_btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "#b-form-submit button[type='submit']")
        )
    )

    submit_btn.click()
    time.sleep(5)

    log.info(f"  [+] URL после поиска: {driver.current_url}")

    try:
        link_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div.b-container a.num_case")
            )
        )
        card_url = link_element.get_attribute("href")
        log.info(f"  [+] URL карточки: {card_url}")
        return card_url
    except Exception:
        log.warning(f"  [!] Дело не найдено: {case_number}")
        return None


def _open_ed_tab(driver: uc.Chrome) -> bool:
    """
    Шаги 5-6: открываем карточку дела и кликаем на вкладку
    'Электронное дело'.

    Возвращает True если вкладка открыта успешно.
    """
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located(
            (By.CLASS_NAME, "b-case-chrono-button-text")
        )
    )

    log.info("  [+] Карточка загружена")

    tabs = driver.find_elements(By.CSS_SELECTOR, ".b-case-chrono-button-text")
    ed_tab = next((t for t in tabs if "Электронное дело" in t.text), None)
    if not ed_tab:
        log.error("  [!] Вкладка 'Электронное дело' не найдена")
        return False

    driver.execute_script("arguments[0].click();", ed_tab)
    time.sleep(5)
    log.info("  [+] Вкладка 'Электронное дело' открыта")
    return True


# Data extraction 

def _extract_latest_document(driver: uc.Chrome) -> dict | None:
    """
    Шаг 7: извлекаем данные последнего документа из вкладки
    'Электронное дело'.

    Возвращает словарь с датой и наименованием документа.
    """
    try:
        date_el = driver.find_element(By.CLASS_NAME, "b-case-chrono-ed-item-date")
        last_date = date_el.text.strip()

        doc_el = driver.find_element(By.CSS_SELECTOR, ".b-case-chrono-ed-item-link")
        raw_text = doc_el.text.strip()
        lines = [
            l.strip() for l in raw_text.splitlines()
            if l.strip() and not l.strip().startswith("[")
        ]
        doc_name = " ".join(lines)

        return {
            "last_date":     last_date,
            "document_name": doc_name,
        }

    except Exception as e:
        log.error(f"  [!] Ошибка при извлечении данных: {e}")
        return None


# Core

def parse(driver: uc.Chrome, case_number: str) -> dict:
    """
    Главный метод парсера — обрабатывает одно дело.
    Принимает уже созданный driver — он переиспользуется для всех дел
    (не создаётся заново на каждый запрос).

    Возвращает словарь с результатом или ошибкой.
    """
    log.info(f"\n{'─' * 50}")
    log.info(f"Обрабатываем дело: {case_number}")

    result = {
        "case_number":   case_number,
        "last_date":     None,
        "document_name": None,
        "error":         None,
    }

    try:
        from config import settings

        card_url = _search_case(driver, case_number)
        if not card_url:
            result["error"] = "Дело не найдено"
            return result

        log.info(f"5: Открываем карточку...")
        driver.get(card_url)
        time.sleep(10)

        log.info("6: Открываем 'Электронное дело'...")
        if not _open_ed_tab(driver):
            result["error"] = "Не удалось открыть вкладку 'Электронное дело'"
            return result

        log.info("7: Извлекаем данные...")
        doc_info = _extract_latest_document(driver)
        if doc_info:
            result.update(doc_info)
        else:
            result["error"] = "Не удалось извлечь данные документа"

        time.sleep(settings.delay_between_cases)

    except Exception as e:
        log.exception(f"  [✗] Неожиданная ошибка для дела {case_number}: {e}")
        result["error"] = str(e)

    return result


def run(case_numbers: list[str]) -> list[dict]:
    """
    Точка входа для запуска парсера из pipeline.py.
    Создаёт driver один раз и переиспользует для всех дел.
    Возвращает список результатов для сохранения в БД.
    """
    driver = create_driver()
    results = []

    try:
        for case_number in case_numbers:
            result = parse(driver, case_number)
            results.append(result)
    finally:
        driver.quit()
        log.info("  [+] Браузер закрыт")

    return results
