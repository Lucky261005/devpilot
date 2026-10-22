"""JSON logging with request IDs and secret redaction."""

import contextvars
import json
import logging
import re

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(authorization|token|password|secret|api[_-]?key)(\"?\s*[:=]\s*\"?)[^\s\",]+"),
]


def redact(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub(lambda m: (m.group(1) + m.group(2) if m.lastindex else "") + "[REDACTED]", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "msg": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
