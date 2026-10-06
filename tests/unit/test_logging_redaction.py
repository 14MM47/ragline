"""Endpoint redaction keeps useful diagnostics without publishing pod ids."""

import io
import logging

from ragline.logging_utils import RedactingFormatter, redact_text, redact_value


def test_redaction_handles_multiple_pod_urls_and_url_credentials():
    text = (
        "https://user:private-password@ABC123-8000.proxy.runpod.net/v1; "
        "https://another-pod-8081.proxy.runpod.net/rerank"
    )
    result = redact_text(text)
    assert result == (
        "https://<redacted>@<pod-id>-8000.proxy.runpod.net/v1; "
        "https://<pod-id>-8081.proxy.runpod.net/rerank"
    )
    assert redact_text(result) == result


def test_nested_redaction_preserves_measurements():
    value = {"errors": ["failed at abc123-8000.proxy.runpod.net"], "timing": 1.25, "ok": False}
    result = redact_value(value)
    assert result["errors"] == ["failed at <pod-id>-8000.proxy.runpod.net"]
    assert result["timing"] == 1.25
    assert result["ok"] is False
    assert value["errors"][0].startswith("failed at abc123")


def test_standard_logging_redacts_interpolated_messages_and_tracebacks():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(logging.Formatter("%(levelname)s %(message)s")))
    logger = logging.Logger("redaction-test")
    logger.addHandler(handler)
    url = "https://abc123-8081.proxy.runpod.net/rerank"
    try:
        raise RuntimeError(f"503 from {url}")
    except RuntimeError:
        logger.exception("Request failed: %s", url)
    result = stream.getvalue()
    assert "ERROR Request failed:" in result
    assert "Traceback" in result and "RuntimeError: 503" in result
    assert "abc123" not in result
    assert "<pod-id>-8081.proxy.runpod.net/rerank" in result
