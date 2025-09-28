from app.config import Settings


def test_database_url_normalised_to_psycopg() -> None:
    settings = Settings(
        LLM_STUB_MODE=True,
        DATABASE_URL="postgresql://user:pass@localhost:5432/db",
    )
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_database_url_retains_existing_driver() -> None:
    url = "postgresql+asyncpg://user:pass@localhost/db"
    settings = Settings(LLM_STUB_MODE=True, DATABASE_URL=url)
    assert settings.database_url == url


def test_database_url_normalises_postgres_alias() -> None:
    settings = Settings(
        LLM_STUB_MODE=True,
        DATABASE_URL="postgres://user:pass@localhost/db",
    )
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_scheduler_jobstore_url_normalised() -> None:
    settings = Settings(
        LLM_STUB_MODE=True,
        DATABASE_URL="sqlite:///./local.db",
        SCHEDULER_JOBSTORE_URL="postgres://user:pass@localhost/db",
    )
    assert settings.scheduler_jobstore_url.startswith("postgresql+psycopg://")
