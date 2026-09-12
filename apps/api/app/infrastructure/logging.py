"""Structured application logs. Never pass user input as messages or extra fields."""

import json
import logging
import logging.config
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger("app.http")
FIELDS = ("method", "route", "status_code", "duration_ms", "order_id", "outcome")


class JsonFormatter(logging.Formatter):
    def __init__(self, environment: str = "development") -> None:
        super().__init__()
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "environment": self.environment,
            "message": record.getMessage() if not record.exc_info else "exception",
            "request_id": request_id.get(),
        }
        for field in FIELDS:
            if hasattr(record, field):
                event[field] = getattr(record, field)
        if record.exc_info and record.exc_info[1] is not None:
            # Exception messages, source lines and locals can contain SQL parameters or PII.
            event["exception_type"] = type(record.exc_info[1]).__name__
            event["stack"] = [
                {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(event, ensure_ascii=True)


def configure_logging(level: str, environment: str) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonFormatter, "environment": environment}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json",
                }
            },
            "root": {"handlers": ["stdout"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": [], "propagate": True, "level": level},
                "uvicorn.error": {"handlers": [], "propagate": True, "level": level},
                # Library request/debug messages can expose URLs, headers or SQL values.
                "httpx": {"handlers": [], "propagate": True, "level": "WARNING"},
                "httpcore": {"handlers": [], "propagate": True, "level": "WARNING"},
                "sqlalchemy.engine": {"handlers": [], "propagate": True, "level": "WARNING"},
                # Our request event replaces access logs, which include raw URLs/query strings.
                "uvicorn.access": {"handlers": [], "propagate": False},
            },
        }
    )


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Generate our own ID so clients cannot inject values or spoof correlation IDs.
        identifier = uuid4().hex
        scope.setdefault("state", {})["request_id"] = identifier
        token = request_id.set(identifier)
        started = perf_counter()
        status = 500
        error = None

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = identifier
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            error = exc
            raise
        finally:
            route = scope.get("route")
            level = (
                logging.ERROR
                if error or status >= 500
                else (logging.WARNING if status >= 400 else logging.INFO)
            )
            try:
                logger.log(
                    level,
                    "http.request",
                    extra={
                        "method": scope["method"],
                        "route": getattr(route, "path", "<unmatched>"),
                        "status_code": status,
                        "duration_ms": round((perf_counter() - started) * 1000, 2),
                    },
                    exc_info=(type(error), error, error.__traceback__) if error else None,
                )
            finally:
                request_id.reset(token)
