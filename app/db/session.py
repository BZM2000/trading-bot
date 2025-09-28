from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def get_engine(settings: Settings | None = None) -> Engine:
    global _ENGINE

    if _ENGINE is not None:
        return _ENGINE

    settings = settings or get_settings()
    database_url = settings.database_url
    create_kwargs = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        create_kwargs["connect_args"] = {"check_same_thread": False}
    _ENGINE = create_engine(database_url, **create_kwargs)
    return _ENGINE


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    global _SESSION_FACTORY

    if _SESSION_FACTORY is not None:
        return _SESSION_FACTORY

    engine = get_engine(settings)
    _SESSION_FACTORY = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return _SESSION_FACTORY


@contextmanager
def session_scope(settings: Settings | None = None) -> Generator[Session, None, None]:
    factory = get_session_factory(settings)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session() -> Generator[Session, None, None]:
    with session_scope() as session:
        yield session
