from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError, OperationalError

from app.db.models import Base


LOGGER = logging.getLogger("db.migrate")

EXPECTED_TABLES = {table.name for table in Base.metadata.sorted_tables}


def _should_stamp_head(database_url: str) -> bool:
    """Detect a partially-initialised schema where Alembic needs stamping."""

    engine: Engine | None = None
    try:
        engine = create_engine(database_url)
        inspector = inspect(engine)

        if not inspector.has_table("alembic_version"):
            return False

        with engine.connect() as conn:
            version_rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()

        if any(row[0] for row in version_rows):
            return False

        existing_tables = set(inspector.get_table_names())
        missing_tables = EXPECTED_TABLES - existing_tables
        if missing_tables:
            LOGGER.warning(
                "Alembic version table empty but schema incomplete; leaving upgrade to run",
                extra={"missing_tables": sorted(missing_tables)},
            )
            return False

        return True
    except SQLAlchemyError as exc:
        LOGGER.warning("Unable to inspect database prior to migrations", exc_info=exc)
        return False
    finally:
        if engine is not None:
            engine.dispose()


def _stamp_head(alembic_cfg: Config, database_url: str) -> None:
    LOGGER.warning(
        "Stamping Alembic head due to partially initialised schema",
        extra={"database_url": scrub_url(database_url)},
    )
    command.stamp(alembic_cfg, "head")


def run_migrations(database_url: str) -> None:
    """Run Alembic migrations up to head for the provided database URL."""

    config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    alembic_cfg = Config(str(config_path))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)

    if _should_stamp_head(database_url):
        _stamp_head(alembic_cfg, database_url)
        return

    LOGGER.info("Running Alembic upgrade to head", extra={"database_url": scrub_url(database_url)})
    try:
        command.upgrade(alembic_cfg, "head")
    except OperationalError as exc:
        message = str(exc).lower()
        if "already exists" in message and _should_stamp_head(database_url):
            _stamp_head(alembic_cfg, database_url)
            return
        raise
    except SQLAlchemyError as exc:
        # OperationalError is a subclass; retain this for other SQLAlchemy issues.
        if "already exists" in str(exc).lower() and _should_stamp_head(database_url):
            _stamp_head(alembic_cfg, database_url)
            return
        raise


def scrub_url(database_url: str) -> str:
    """Mask secrets in a SQLAlchemy URL for logging."""

    if "@" not in database_url:
        return database_url
    _, suffix = database_url.split("@", 1)
    return "***@" + suffix
