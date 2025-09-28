from sqlalchemy import create_engine, text

from app.db.migrate import run_migrations, scrub_url
from app.db.models import Base


def test_scrub_url_masks_credentials():
    url = "postgresql+psycopg://user:secret@host:5432/db"
    assert scrub_url(url) == "***@host:5432/db"


def test_scrub_url_returns_plain_when_no_credentials():
    url = "sqlite:///./trading_bot.db"
    assert scrub_url(url) == url


def test_run_migrations_stamps_partial_schema(tmp_path):
    db_path = tmp_path / "partial.db"
    url = f"sqlite:///{db_path}"

    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))

        run_migrations(url)

        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == "20240801_0001"
    finally:
        engine.dispose()
