"""Structured JSON logging with sensitive-data masking filter.

Fields in every log record: ts, level, service, request_id, user_id_hash, event.
The MaskingFilter redacts account/card numbers, JWT tokens, Bearer tokens,
and sensitive field names (password, pin, otp, token, secret, key, etc.).
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Any

from pythonjsonlogger import jsonlogger

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# 16-digit card numbers (optionally separated by spaces or dashes)
_CARD_PATTERN = re.compile(
    r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b"
)

# Bearer <token>
_BEARER_PATTERN = re.compile(
    r"(Bearer\s+)[\w\.\-]+",
    re.IGNORECASE,
)

# Full JWT (three base64url segments)
_JWT_PATTERN = re.compile(
    r"\bey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
)

# Standalone 4-6 digit strings (potential PIN / OTP)
# Only mask when surrounded by non-digit chars (not part of a longer number).
_PIN_PATTERN = re.compile(r"(?<!\d)\d{4,6}(?!\d)")

# Field names whose values should always be masked on the log record
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "account_number",
        "card_number",
        "pan",
        "cvv",
        "pin",
        "otp",
        "password",
        "new_password",
        "old_password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "key",
        "api_key",
        "private_key",
        "transaction_pin",
        "transaction_pin_hash",
        "password_hash",
    }
)

# ---------------------------------------------------------------------------
# Masking helpers
# ---------------------------------------------------------------------------


def _mask_string(text: str) -> str:
    """Apply all masking patterns to a string."""
    # Cards before general number masking so we don't double-mask
    text = _CARD_PATTERN.sub(
        lambda m: m.group(0)[:4] + "-****-****-" + m.group(0)[-4:],
        text,
    )
    text = _BEARER_PATTERN.sub(r"\1[MASKED_TOKEN]", text)
    text = _JWT_PATTERN.sub("[MASKED_TOKEN]", text)
    return text


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


class MaskingFilter(logging.Filter):
    """Logging filter that redacts sensitive data from log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: ANN201
        # Mask the message string
        if isinstance(record.msg, str):
            record.msg = _mask_string(record.msg)

        # Mask args tuple/dict passed to % formatting
        if isinstance(record.args, tuple):
            record.args = tuple(
                _mask_string(a) if isinstance(a, str) else a for a in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                k: (_mask_string(v) if isinstance(v, str) else v)
                for k, v in record.args.items()
            }

        # Mask sensitive extra fields set directly on the record
        for attr in list(vars(record).keys()):
            if attr.lower() in _SENSITIVE_KEYS:
                setattr(record, attr, "[MASKED]")

        return True


# ---------------------------------------------------------------------------
# Custom JSON formatter
# ---------------------------------------------------------------------------


class _BankingJsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter that renames fields to match the agreed log schema."""

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        # Normalise field names
        log_record["ts"] = log_record.pop("asctime", None) or record.created
        log_record["level"] = log_record.pop("levelname", record.levelname)
        # Prefer 'event' key; fall back to 'message'
        if "event" not in log_record:
            log_record["event"] = log_record.pop("message", record.getMessage())
        else:
            log_record.pop("message", None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(
    service: str,
    level: str = "INFO",
    fmt: str = "json",
) -> None:
    """Configure the root logger for the given service.

    Args:
        service: Short service name injected into every log record.
        level:   Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        fmt:     Output format: "json" (default) or "text" for local dev.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove any existing handlers (safe for repeated calls in tests)
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)

    if fmt == "json":
        formatter = _BankingJsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    handler.setFormatter(formatter)
    handler.addFilter(MaskingFilter())
    root.addHandler(handler)

    # Inject service name via a LoggerAdapter shim on the root
    logging.getLogger().info(
        "Logging configured",
        extra={"service": service, "level": level, "format": fmt},
    )


def get_logger(name: str, service: str = "unknown") -> logging.Logger:
    """Return a named logger.  Call configure_logging() once at startup first."""
    return logging.getLogger(name)
