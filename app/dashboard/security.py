from __future__ import annotations

import logging
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from passlib.context import CryptContext

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_basic_scheme = HTTPBasic(auto_error=False)
_password_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _is_authenticated(credentials: HTTPBasicCredentials | None, settings: Settings) -> bool:
    if not settings.dashboard_basic_auth_enabled:
        return True
    if credentials is None:
        return False

    expected_username = settings.dashboard_basic_username or ""
    expected_hash = settings.dashboard_basic_password_hash or ""

    if not expected_username or not expected_hash:
        logger.error("Dashboard basic auth enabled but credentials not fully configured")
        return False

    username_matches = secrets.compare_digest(credentials.username or "", expected_username)
    try:
        password_matches = _password_context.verify(credentials.password or "", expected_hash)
    except ValueError:
        logger.exception("Invalid password hash configured for dashboard access")
        return False

    return username_matches and password_matches


def require_dashboard_basic_auth(
    credentials: HTTPBasicCredentials | None = Depends(_basic_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    if _is_authenticated(credentials, settings):
        return

    logger.warning("Dashboard access denied", extra={"username": getattr(credentials, "username", None)})
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Dashboard authentication required",
        headers={"WWW-Authenticate": "Basic"},
    )
