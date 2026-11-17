"""Structured JSON logging with redaction of sensitive content.

Call transcripts, phone numbers, one-time codes, tokens and keys must never reach logs or telemetry. Redaction is
applied twice: by field name (anything that looks like content or a credential) and by value pattern.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
call_id_var: ContextVar[str | None] = ContextVar("call_id", default=None)

REDACTED = "[redacted]"

_SENSITIVE_KEYS = re.compile(
    r"(authorization|api[-_]?key|secret|token|password|passwd|pin|cvv|otp|cookie|signature|connection[-_]?string|"
    r"transcript|text|utterance|caller_text|body|content|audio|number|phone|email|address|ticket)",
    re.IGNORECASE,
)
# Keys that look sensitive by name but are safe, bounded metadata.
_SAFE_KEYS = {
    "text_length",
    "token_count",
    "tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "otp_requests",
    "pin_requests",
    "content_type",
    "content_length",
    "turn_text_len",
    "audio_seconds",
    "audio_bytes",
    "phone_masked",
    "number_masked",
}

_VALUE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)bearer\s+[a-z0-9._\-~+/]+=*"), "Bearer [redacted]"),
    (
        re.compile(r"(?i)\b(api[-_]?key|secret|token|password|signature)\s*[=:]\s*[^\s,;&\"']+"),
        r"\1=[redacted]",
    ),
    (re.compile(r"\beyJ[a-zA-Z0-9_\-]{8,}\.[a-zA-Z0-9_\-]{8,}\.[a-zA-Z0-9_\-]*"), "[jwt]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?<!\w)\+?\d[\d\s\-().]{8,}\d(?!\w)"), "[phone]"),
    (re.compile(r"(?<!\d)\d{4,8}(?!\d)"), "[digits]"),
]

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


def redact_text(value: str) -> str:
    for pattern, replacement in _VALUE_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def redact_value(key: str, value: Any, depth: int = 0) -> Any:
    if key not in _SAFE_KEYS and _SENSITIVE_KEYS.search(key):
        return REDACTED
    if depth > 4:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(k): redact_value(str(k), v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [redact_value(key, v, depth + 1) for v in list(value)[:50]]
    if isinstance(value, bool | int | float) or value is None:
        return value
    return redact_text(str(value))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
        }
        for var_name, var in (
            ("correlation_id", correlation_id_var),
            ("trace_id", trace_id_var),
            ("call_id", call_id_var),
        ):
            current = var.get()
            if current:
                payload[var_name] = current
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = redact_value(key, value)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class ReadableFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        stamp = self.formatTime(record, "%H:%M:%S")
        base = f"{stamp} {record.levelname:<7} {record.name}: {redact_text(record.getMessage())}"
        extras = {
            k: redact_value(k, v) for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")
        }
        if extras:
            base += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + redact_text(self.formatException(record.exc_info))
        return base


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else ReadableFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
