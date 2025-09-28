import logging
import logging.config
import sys
from datetime import datetime
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """Emit logs as structured JSON strings."""

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info:
            log_entry["stack_info"] = self.formatStack(record.stack_info)

        for key, value in getattr(record, "__dict__", {}).items():
            if key.startswith("_") or key in log_entry:
                continue
            log_entry[key] = value

        return json_dumps(log_entry)


def json_dumps(payload: Dict[str, Any]) -> str:
    """Serialize a dictionary to JSON without relying on external libraries."""

    from json import dumps

    return dumps(payload, default=str, separators=(",", ":"))


def _normalise_level(level: str) -> str:
    """Return a logging level string compatible with dictConfig."""

    candidate = level.strip()
    if not candidate:
        return "INFO"
    return candidate.upper()


def setup_logging(level: str = "INFO") -> None:
    """Configure root and uvicorn loggers for structured output."""

    normalised_level = _normalise_level(level)

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "app.logging.JSONFormatter",
            }
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "json",
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": normalised_level, "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": normalised_level, "propagate": False},
            "apscheduler": {"handlers": ["default"], "level": normalised_level, "propagate": False},
        },
        "root": {"handlers": ["default"], "level": normalised_level},
    }

    logging.config.dictConfig(logging_config)
