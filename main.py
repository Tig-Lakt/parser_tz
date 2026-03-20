import asyncio
import logging
import sys
from pathlib import Path

import openpyxl

from config import settings
from db.session import init_db
from logging_config import setup_logging
from services.pipeline import run_pipeline

log = logging.getLogger(__name__)


# xlsx reader

def read_inns_from_xlsx(filepath: str) -> list[str]:
    """
    Читает список ИНН из первого столбца xlsx файла.
    Пропускает пустые строки и заголовок (если первая ячейка — строка 'инн').
    """
    path = Path(filepath)
    if not path.exists():
        log.error(f"Файл не найден: {filepath}")
        sys.exit(1)

    if path.suffix.lower() != ".xlsx":
        log.error(f"Ожидается файл .xlsx, получен: {path.suffix}")
        sys.exit(1)

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    inns = []
    for row in ws.iter_rows(min_col=1, max_col=1, values_only=True):
        value = row[0]
        if value is None:
            continue
        inn = str(value).strip()

        if inn.lower() in ("инн", "inn", ""):
            continue

        inns.append(inn)

    wb.close()
    log.info(f"[Main] Прочитано {len(inns)} ИНН из {filepath}")
    return inns


# Entry point

async def main() -> None:
    setup_logging()

    log.info("=" * 60)
    log.info("Парсер запущен")
    log.info("=" * 60)

    if len(sys.argv) < 2:
        log.error("Использование: python main.py <path_to_inns.xlsx>")
        sys.exit(1)

    xlsx_path = sys.argv[1]

    inn_list = read_inns_from_xlsx(xlsx_path)
    if not inn_list:
        log.error("Список ИНН пуст")
        sys.exit(1)

    log.info(f"[Main] Всего ИНН к обработке: {len(inn_list)}")

    log.info("[Main] Инициализируем БД...")
    init_db()

    await run_pipeline(inn_list)

    log.info("=" * 60)
    log.info("Парсер завершил работу")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())