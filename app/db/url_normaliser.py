"""Utilities for adapting database connection URLs to local drivers."""

from __future__ import annotations

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def normalise_database_url(url: str | None) -> str | None:
    """Return a URL that defaults Postgres connections to psycopg."""

    if url is None:
        return None

    try:
        sa_url = make_url(url)
    except ArgumentError:
        return url

    driver = sa_url.drivername
    if driver in {"postgres", "postgresql", "postgresql+psycopg2"}:
        sa_url = sa_url.set(drivername="postgresql+psycopg")

    if hasattr(sa_url, "render_as_string"):
        return sa_url.render_as_string(hide_password=False)
    return str(sa_url)
