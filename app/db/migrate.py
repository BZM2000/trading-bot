from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

LOGGER = logging.getLogger("db.migrate")


def run_migrations(database_url: str) -> None:
    """Run Alembic migrations up to head for the provided database URL."""

    config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    alembic_cfg = Config(str(config_path))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    LOGGER.info("Running Alembic upgrade to head", extra={"database_url": scrub_url(database_url)})
    command.upgrade(alembic_cfg, "head")


def scrub_url(database_url: str) -> str:
    """Mask secrets in a SQLAlchemy URL for logging."""

    if "@" not in database_url:
        return database_url
    prefix, suffix = database_url.split("@", 1)
    return "***@" + suffix
