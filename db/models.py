import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class StatusEnum(str, enum.Enum):
    pending    = "pending"     # ещё не обработан
    processing = "processing"  # в процессе
    done       = "done"        # успешно завершён
    error      = "error"       # ошибка, можно повторить


# INN (входные данные)
class InnRecord(Base):
    """
    Одна строка из входного xlsx файла.
    Служит очередью задач — по статусу определяем что обрабатывать.
    """
    __tablename__ = "inn_records"

    id         : Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    inn        : Mapped[str]      = mapped_column(String(20), nullable=False, unique=True, index=True)
    status     : Mapped[StatusEnum] = mapped_column(
        Enum(StatusEnum), nullable=False, default=StatusEnum.pending, index=True
    )
    error_msg  : Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at : Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at : Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Связь с результатом
    result: Mapped["ParseResult | None"] = relationship(
        "ParseResult", back_populates="inn_record", uselist=False
    )

    def __repr__(self) -> str:
        return f"<InnRecord inn={self.inn} status={self.status}>"


# ParseResult (результат парсинга)
class ParseResult(Base):
    """
    Результат парсинга для одного ИНН.
    Данные с обоих сайтов — fedresurs.ru и kad.arbitr.ru.
    """
    __tablename__ = "parse_results"

    id             : Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    inn_record_id  : Mapped[int]      = mapped_column(
        Integer, ForeignKey("inn_records.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # Данные физлица (fedresurs.ru)
    inn            : Mapped[str]      = mapped_column(String(20), nullable=False, index=True)
    person_name    : Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Данные о банкротстве (fedresurs.ru)
    case_number    : Mapped[str | None] = mapped_column(String(50), nullable=True)
    fed_last_date  : Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Данные из kad.arbitr.ru
    kad_last_date  : Mapped[str | None] = mapped_column(String(20), nullable=True)
    document_type  : Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_name  : Mapped[str | None] = mapped_column(Text, nullable=True)

    parsed_at      : Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Связь с InnRecord
    inn_record: Mapped["InnRecord"] = relationship(
        "InnRecord", back_populates="result"
    )

    def __repr__(self) -> str:
        return f"<ParseResult inn={self.inn} case={self.case_number}>"