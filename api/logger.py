"""
Structured JSON logger for the entire backend.

Usage:
    from api.logger import get_logger
    logger = get_logger(__name__)
    logger.info("asset_processed", asset=name, faces=3, quality=0.82)
    logger.warning("low_confidence", asset=name, score=0.3)
    logger.error("model_failed", error=str(e))

Output (JSON in production, coloured console in dev):
    {"event": "asset_processed", "asset": "IMG_001.jpg", "faces": 3, ...}
"""

import logging
import os
import sys
import uuid
from contextvars import ContextVar

import structlog

# Per-request ID stored in a context variable — set by middleware
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class SafeBoundLogger:
    """
    Wrapper around structlog BoundLogger that prevents reserved `event` kwarg
    collisions (e.g. logger.info("msg", event="...")).
    """

    _METHODS = {"debug", "info", "warning", "error", "exception", "critical"}

    def __init__(self, logger):
        self._logger = logger

    def _normalize_kwargs(self, kwargs):
        if "event" in kwargs:
            event_value = kwargs.pop("event")
            if "event_name" not in kwargs:
                kwargs["event_name"] = event_value
            else:
                kwargs["event_value"] = event_value
        return kwargs

    def _call(self, method: str, event, *args, **kwargs):
        return getattr(self._logger, method)(event, *args, **self._normalize_kwargs(kwargs))

    def debug(self, event, *args, **kwargs):
        return self._call("debug", event, *args, **kwargs)

    def info(self, event, *args, **kwargs):
        return self._call("info", event, *args, **kwargs)

    def warning(self, event, *args, **kwargs):
        return self._call("warning", event, *args, **kwargs)

    def error(self, event, *args, **kwargs):
        return self._call("error", event, *args, **kwargs)

    def exception(self, event, *args, **kwargs):
        return self._call("exception", event, *args, **kwargs)

    def critical(self, event, *args, **kwargs):
        return self._call("critical", event, *args, **kwargs)

    def bind(self, *args, **kwargs):
        return SafeBoundLogger(self._logger.bind(*args, **kwargs))

    def new(self, *args, **kwargs):
        return SafeBoundLogger(self._logger.new(*args, **kwargs))

    def unbind(self, *keys):
        return SafeBoundLogger(self._logger.unbind(*keys))

    def __getattr__(self, item):
        return getattr(self._logger, item)


def get_request_id() -> str:
    return request_id_var.get() or str(uuid.uuid4())[:8]


def _add_request_id(logger, method, event_dict):
    """structlog processor: inject request_id into every log record."""
    rid = request_id_var.get()
    if rid:
        event_dict["request_id"] = rid
    return event_dict


def setup_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """
    Configure structlog + stdlib logging.
    Call once at application startup.

    Args:
        log_level:   'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
        json_output: True = JSON (production), False = coloured console (dev)
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_request_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Silence noisy third-party loggers
    for noisy in ["uvicorn.access", "httpx", "httpcore", "urllib3"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str):
    """Return a bound structlog logger for the given module name."""
    return SafeBoundLogger(structlog.get_logger(name))
