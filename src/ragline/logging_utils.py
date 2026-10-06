"""Redact endpoint identifiers from logs and shareable evaluation output.

RunPod proxy hostnames contain the pod id. Redact it everywhere in an event,
including HTTP error messages, while keeping the port and request path useful
for debugging. URL userinfo is also removed so basic-auth credentials cannot
be mistaken for a harmless hostname.
"""

import logging
import re

import structlog

_POD_HOST = re.compile(r"(?<![\w.-])[a-z0-9-]+(-\d+\.proxy\.runpod\.net)\b", re.IGNORECASE)
_URL_USERINFO = re.compile(r"(https?://)[^/\s@]+@", re.IGNORECASE)


def redact_text(text: str) -> str:
    """Remove pod ids and URL credentials from a string."""
    text = _URL_USERINFO.sub(r"\1<redacted>@", text)
    return _POD_HOST.sub(r"<pod-id>\1", text)


def redact_value(value):
    """Redact nested output without changing numeric scores or timings."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def _redact_event(_logger, _method, event_dict):
    """Structlog processor: sanitize fields before the renderer formats them."""
    return redact_value(event_dict)


class RedactingFormatter(logging.Formatter):
    """Wrap an existing formatter so exception tracebacks are redacted too."""

    def __init__(self, formatter: logging.Formatter | None = None):
        super().__init__()
        self._formatter = formatter or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(self._formatter.format(record))


def configure_redaction() -> None:
    """Protect structlog events and the root handlers used by HTTP clients.

    Call after basicConfig, before constructing model clients. Preserve the
    existing logging style and avoid stacking processors on repeated calls.
    """
    processors = list(structlog.get_config()["processors"])
    if _redact_event not in processors:
        processors.insert(len(processors) - 1, _redact_event)
        structlog.configure(processors=processors)
    for handler in logging.getLogger().handlers:
        if not isinstance(handler.formatter, RedactingFormatter):
            handler.setFormatter(RedactingFormatter(handler.formatter))
