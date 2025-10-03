import importlib
from typing import Any

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
        assert version == "20250115_0004"
    finally:
        engine.dispose()


def test_initial_schema_enum_creation_disables_recreate(monkeypatch):
    module_name = "app.db.migrations.versions.20240801_0001_initial_schema"
    module = importlib.reload(importlib.import_module(module_name))

    fake_bind = object()

    class FakeOp:
        def __init__(self) -> None:
            self.tables: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
            self.indexes: list[tuple[Any, ...]] = []

        def get_bind(self) -> Any:
            return fake_bind

        def create_table(self, *args: Any, **kwargs: Any) -> None:
            self.tables.append((args, kwargs))

        def create_index(self, *args: Any, **kwargs: Any) -> None:
            self.indexes.append((args, kwargs))

    fake_op = FakeOp()
    monkeypatch.setattr(module, "op", fake_op)

    real_enum_cls = module.postgresql.ENUM

    class TrackingEnum(real_enum_cls):
        instances: list["TrackingEnum"] = []

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.create_calls: list[tuple[Any, bool]] = []
            TrackingEnum.instances.append(self)

        def create(self, bind: Any, checkfirst: bool = False, **_: Any) -> None:
            self.create_calls.append((bind, checkfirst))
            # Skip the real DDL to keep the test self-contained.
            return None

    monkeypatch.setattr(module.postgresql, "ENUM", TrackingEnum)

    module.upgrade()

    assert TrackingEnum.instances, "Expected migration to define enums"
    for enum_instance in TrackingEnum.instances:
        assert enum_instance.create_calls == [(fake_bind, True)]
        assert enum_instance.create_type is False
