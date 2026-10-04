"""Structured JSON logging with redaction of secrets."""
from __future__ import annotations

import json
import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"(password|passwd|secret|token|otp|code|authorization|cookie)([\"'=:\s]+)([^\s\"'&,]+)", re.I),
    re.compile(r"/s/[A-Za-z0-9_\-]{20,}"),  # public share tokens in URLs
]


def redact(text: str) -> str:
    text = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub("/s/[REDACTED]", text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - malformed log call
            return True
        record.msg = redact(msg)
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)
