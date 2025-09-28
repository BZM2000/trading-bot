from functools import lru_cache
from typing import Optional
from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised application configuration sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = Field(default=..., validation_alias="OPENAI_API_KEY")
    coinbase_api_key: str = Field(default=..., validation_alias="COINBASE_API_KEY")
    coinbase_api_secret: str = Field(default=..., validation_alias="COINBASE_API_SECRET")
    database_url: str = Field(default=..., validation_alias="DATABASE_URL")

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


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
