from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    db_host    : str = "localhost"
    db_port    : int = 5432
    db_name    : str = "parser"
    db_user    : str = "postgres"
    db_password: str = "postgres"
    db_echo    : bool = False

    @property
    def database_url(self) -> str:
        """Sync URL для SQLAlchemy и Alembic."""
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def async_database_url(self) -> str:
        """Async URL для asyncpg."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # ─────────────────────────── Parser ─────────────────────────
    chrome_version      : int   = 145    # версия Chrome для undetected-chromedriver
    chrome_headless     : bool  = True   # False для отладки
    delay_between_cases : float = 2.0    # секунд между делами в kad.arbitr.ru
    delay_between_inns  : float = 1.5    # секунд между ИНН в fedresurs.ru
    max_concurrent_inns : int   = 3      # параллельных запросов к fedresurs.ru
    max_retries         : int   = 3      # попыток при ошибке
    retry_base_delay    : int   = 2

    # ─────────────────────────── Logging ────────────────────────
    log_level      : str = "INFO"
    log_file       : str = "logs/parser.log"
    log_max_bytes  : int = 10 * 1024 * 1024  # 10 MB
    log_backup_count: int = 5                 # хранить 5 файлов


settings = Settings()