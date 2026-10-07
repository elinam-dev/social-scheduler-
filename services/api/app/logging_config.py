import json
import logging
import logging.config
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

_STRUCTURED_FIELDS = (
    "event",
    "operation",
    "duration_ms",
    "status",
    "job_id",
    "video_id",
    "clip_id",
    "method",
    "path",
    "status_code",
    "error_type",
    "retry_count",
)
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _redact_urls(value: str) -> str:
    return _URL_PATTERN.sub("[URL redacted]", value)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact_urls(record.getMessage()),
        }
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = _redact_urls(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "app.logging_config.JsonLogFormatter",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                },
            },
            "root": {
                "level": "INFO",
                "handlers": ["console"],
            },
        }
    )


@contextmanager
def log_timing(
    logger: logging.Logger,
    operation: str,
    **context: str,
) -> Iterator[None]:
    start = perf_counter()
    try:
        yield
    except Exception as error:
        logger.exception(
            "Pipeline operation failed",
            extra={
                **context,
                "event": "pipeline_operation",
                "operation": operation,
                "duration_ms": round((perf_counter() - start) * 1000, 2),
                "status": "failed",
                "error_type": type(error).__name__,
            },
        )
        raise
    else:
        logger.info(
            "Pipeline operation completed",
            extra={
                **context,
                "event": "pipeline_operation",
                "operation": operation,
                "duration_ms": round((perf_counter() - start) * 1000, 2),
                "status": "succeeded",
            },
        )
