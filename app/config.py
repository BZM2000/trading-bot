from functools import lru_cache
from typing import Optional
from decimal import Decimal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def _normalise_database_url(url: str | None) -> str | None:
    """Ensure Postgres URLs use the psycopg driver when unspecified."""

    if url is None:
        return None

    try:
        sa_url = make_url(url)
    except Exception:
        return url

    driver = sa_url.drivername
    if driver in {"postgres", "postgresql"}:
        sa_url = sa_url.set(drivername="postgresql+psycopg")
    elif driver == "postgresql+psycopg2":
        sa_url = sa_url.set(drivername="postgresql+psycopg")

    if hasattr(sa_url, "render_as_string"):
        return sa_url.render_as_string(hide_password=False)
    return str(sa_url)


class Settings(BaseSettings):
    """Centralised application configuration sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: Optional[str] = Field(
        default=None, validation_alias="OPENAI_API_KEY"
    )
    coinbase_api_key: Optional[str] = Field(
        default=None, validation_alias="COINBASE_API_KEY"
    )
    coinbase_api_secret: Optional[str] = Field(
        default=None, validation_alias="COINBASE_API_SECRET"
    )
    database_url: str = Field(
        default="sqlite:///./trading_bot.db", validation_alias="DATABASE_URL"
    )

    environment: str = Field(default="local", validation_alias="ENVIRONMENT")
    app_timezone: str = Field(default="UTC", validation_alias="APP_TIMEZONE")
    product_id: str = Field(default="ETH-USDC", validation_alias="PRODUCT_ID")
    min_distance_pct: Decimal = Field(
        default=Decimal("0.0015"), validation_alias="MIN_DISTANCE_PCT"
    )
    price_drift_pct: Decimal = Field(
        default=Decimal("0.005"), validation_alias="PRICE_DRIFT_PCT"
    )

    scheduler_jobstore_url: Optional[str] = Field(
        default=None, validation_alias="SCHEDULER_JOBSTORE_URL"
    )
    scheduler_max_instances: int = Field(
        default=1, validation_alias="SCHEDULER_MAX_INSTANCES"
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    llm_stub_mode: bool = Field(default=False, validation_alias="LLM_STUB_MODE")
    execution_enabled: bool = Field(
        default=False, validation_alias="EXECUTION_ENABLED"
    )

    openai_responses_model_m1: str = Field(
        default="gpt-5", validation_alias="OPENAI_MODEL_M1"
    )
    openai_responses_model_m2: str = Field(
        default="gpt-5", validation_alias="OPENAI_MODEL_M2"
    )
    openai_responses_model_m3: str = Field(
        default="gpt-5-mini", validation_alias="OPENAI_MODEL_M3"
    )
    openai_responses_model_summariser: str = Field(
        default="gpt-5-mini", validation_alias="OPENAI_MODEL_SUMMARISER"
    )

    openai_responses_reasoning_m1: str = Field(
        default="high", validation_alias="OPENAI_REASONING_M1"
    )
    openai_responses_reasoning_m2: str = Field(
        default="medium", validation_alias="OPENAI_REASONING_M2"
    )
    openai_responses_reasoning_m3: str = Field(
        default="minimal", validation_alias="OPENAI_REASONING_M3"
    )
    openai_responses_reasoning_summariser: str = Field(
        default="minimal", validation_alias="OPENAI_REASONING_SUMMARISER"
    )


    @model_validator(mode="after")
    def _require_credentials(self) -> "Settings":
        self.database_url = _normalise_database_url(self.database_url) or self.database_url
        self.scheduler_jobstore_url = _normalise_database_url(self.scheduler_jobstore_url)
        if not self.llm_stub_mode and not self.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY must be set when LLM_STUB_MODE is false"
            )
        if self.execution_enabled and not (self.coinbase_api_key and self.coinbase_api_secret):
            raise ValueError(
                "COINBASE_API_KEY and COINBASE_API_SECRET must be set when EXECUTION_ENABLED is true"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
