from fastapi.security import HTTPBasicCredentials
from passlib.context import CryptContext
from types import SimpleNamespace

from app.dashboard.security import _is_authenticated


password_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _build_settings(**overrides: object):
    base = {
        "llm_stub_mode": True,
        "dashboard_basic_auth_enabled": True,
        "dashboard_basic_username": "user",
        "dashboard_basic_password_hash": password_context.hash("secret"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_basic_auth_accepts_matching_credentials() -> None:
    settings = _build_settings()
    credentials = HTTPBasicCredentials(username="user", password="secret")

    assert _is_authenticated(credentials, settings) is True


def test_basic_auth_rejects_invalid_password() -> None:
    settings = _build_settings()
    credentials = HTTPBasicCredentials(username="user", password="mismatch")

    assert _is_authenticated(credentials, settings) is False


def test_basic_auth_rejects_invalid_username() -> None:
    settings = _build_settings()
    credentials = HTTPBasicCredentials(username="wrong", password="secret")

    assert _is_authenticated(credentials, settings) is False


def test_basic_auth_denies_when_credentials_missing() -> None:
    settings = _build_settings()

    assert _is_authenticated(None, settings) is False


def test_basic_auth_allows_when_disabled() -> None:
    settings = _build_settings(
        dashboard_basic_auth_enabled=False,
    )

    assert _is_authenticated(None, settings) is True
