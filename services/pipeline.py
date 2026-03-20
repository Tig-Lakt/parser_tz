import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db.models import InnRecord, ParseResult, StatusEnum
from db.session import get_sync_session

log = logging.getLogger(__name__)


# DB helpers 

def load_inns_to_db(inn_list: list[str]) -> None:
    """
    Загружает список ИНН в таблицу inn_records.
    Уже существующие записи не перезаписываются (ON CONFLICT DO NOTHING) —
    это и есть механизм resume: повторный запуск не сбрасывает прогресс.
    """
    with get_sync_session() as session:
        for inn in inn_list:
            stmt = (
                insert(InnRecord)
                .values(inn=inn, status=StatusEnum.pending)
                .on_conflict_do_nothing(index_elements=["inn"])
            )
            session.execute(stmt)
        log.info(f"[DB] Загружено {len(inn_list)} ИНН в очередь")


def get_pending_inns() -> list[str]:
    """
    Возвращает список ИНН которые нужно обработать:
    - pending  — ещё не обрабатывались
    - error    — завершились с ошибкой, пробуем снова
    - processing — зависли (например, упал процесс), пробуем снова
    """
    with get_sync_session() as session:
        stmt = select(InnRecord.inn).where(
            InnRecord.status.in_([
                StatusEnum.pending,
                StatusEnum.error,
                StatusEnum.processing,
            ])
        )
        result = session.execute(stmt)
        inns = [row[0] for row in result]
        log.info(f"[DB] Найдено {len(inns)} ИНН для обработки")
        return inns


def mark_processing(inn: str) -> None:
    """Помечает ИНН как 'в процессе' перед началом обработки."""
    with get_sync_session() as session:
        stmt = select(InnRecord).where(InnRecord.inn == inn)
        record = session.execute(stmt).scalar_one_or_none()
        if record:
            record.status = StatusEnum.processing


def save_result(fed_result: dict, kad_result: dict | None) -> None:
    """
    Сохраняет результат парсинга в БД.
    Обновляет статус InnRecord и создаёт/обновляет ParseResult.
    """
    inn = fed_result["inn"]
    has_error = bool(fed_result.get("error")) or (
        kad_result and bool(kad_result.get("error"))
    )

    with get_sync_session() as session:
        inn_record = session.execute(
            select(InnRecord).where(InnRecord.inn == inn)
        ).scalar_one_or_none()

        if not inn_record:
            log.error(f"[DB] InnRecord не найден для ИНН {inn}")
            return

        inn_record.status = StatusEnum.error if has_error else StatusEnum.done
        inn_record.error_msg = fed_result.get("error") or (
            kad_result.get("error") if kad_result else None
        )

        parse_result = session.execute(
            select(ParseResult).where(ParseResult.inn == inn)
        ).scalar_one_or_none()

        if not parse_result:
            parse_result = ParseResult(inn=inn, inn_record_id=inn_record.id)
            session.add(parse_result)

        parse_result.person_name   = fed_result.get("name")
        parse_result.case_number   = fed_result.get("case_number")
        parse_result.fed_last_date = fed_result.get("last_date")

        if kad_result and not kad_result.get("error"):
            parse_result.kad_last_date  = kad_result.get("last_date")
            parse_result.document_name  = kad_result.get("document_name")

        log.info(f"[DB] Сохранён результат для ИНН {inn} — статус: {inn_record.status}")


# ─────────────────────────── Pipeline ───────────────────────────

async def run_fedresurs(inn_list: list[str]) -> dict[str, dict]:
    """
    Запускает fedresurs парсер для списка ИНН.
    Возвращает словарь {inn: result}.
    """
    from parsers.fedresurs import run as fedresurs_run

    log.info(f"[Pipeline] Запускаем fedresurs для {len(inn_list)} ИНН...")
    results = await fedresurs_run(inn_list)

    return {r["inn"]: r for r in results}


def run_kad(case_numbers: list[str]) -> dict[str, dict]:
    """
    Запускает kad парсер для списка номеров дел.
    Возвращает словарь {case_number: result}.
    """
    from parsers.kad import run as kad_run

    log.info(f"[Pipeline] Запускаем kad для {len(case_numbers)} дел...")
    results = kad_run(case_numbers)

    return {r["case_number"]: r for r in results}


async def run_pipeline(inn_list: list[str]) -> None:
    """
    Главная функция pipeline:
    1. Загружает ИНН в БД (с учётом resume)
    2. Получает список необработанных ИНН
    3. Запускает fedresurs — получаем номера дел
    4. Запускает kad — получаем данные документов
    5. Сохраняет всё в БД

    Если запуск повторный — обрабатывает только pending/error ИНН.
    """
    log.info("[Pipeline] Загружаем ИНН в БД...")
    load_inns_to_db(inn_list)

    pending = get_pending_inns()
    if not pending:
        log.info("[Pipeline] Все ИНН уже обработаны. Выход.")
        return

    fed_results = await run_fedresurs(pending)

    case_numbers = [
        r["case_number"]
        for r in fed_results.values()
        if r.get("case_number") and not r.get("error")
    ]

    kad_results = {}
    if case_numbers:
        kad_results = run_kad(case_numbers)
    else:
        log.warning("[Pipeline] Нет номеров дел для kad.arbitr.ru")

    log.info("[Pipeline] Сохраняем результаты в БД...")
    for inn, fed_result in fed_results.items():
        case_number = fed_result.get("case_number")
        kad_result = kad_results.get(case_number) if case_number else None
        save_result(fed_result, kad_result)

    total    = len(pending)
    done     = sum(1 for r in fed_results.values() if not r.get("error"))
    errors   = total - done
    log.info(f"\n[Pipeline] Готово: {done}/{total} успешно, {errors} ошибок")