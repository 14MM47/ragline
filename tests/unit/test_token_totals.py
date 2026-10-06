"""Unit tests for the minimal tracing layer.

Verifies the two behaviours the token-usage feature depends on:
  1. the ContextVar registration/lookup cycle (provider finds the collector),
  2. accumulation across multiple LLM calls summing into whole-turn totals.
"""

from types import SimpleNamespace

from ragline.llm.openai_provider import _record_usage
from ragline.tracing.collector import TraceCollector, get_current_trace


def _usage(prompt: int, completion: int) -> SimpleNamespace:
    """Build a stand-in for the SDK's usage object with the two fields we read."""
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)


def test_collector_registers_and_clears():
    """Constructing a collector makes it current; finalize() clears it."""
    # No collector active before construction.
    assert get_current_trace() is None
    trace = TraceCollector(query="q")
    # The new collector is now discoverable by the provider.
    assert get_current_trace() is trace
    trace.finalize()
    # finalize() must clear the ContextVar so later calls aren't misattributed.
    assert get_current_trace() is None


def test_usage_accumulates_across_calls():
    """Multiple LLM calls in one turn sum into whole-turn totals."""
    trace = TraceCollector(query="q", session_id="s1")
    # Simulate the four LLM passes of a chat turn recording usage.
    _record_usage(_usage(100, 20))   # pre-pass
    _record_usage(_usage(900, 150))  # answer
    _record_usage(_usage(300, 40))   # memory post-pass
    _record_usage(_usage(200, 10))   # confidence
    record = trace.finalize()
    # Totals are the sums across all passes.
    assert record.prompt_tokens == 1500
    assert record.completion_tokens == 220
    assert record.session_id == "s1"


def test_usage_ignores_missing_fields():
    """Servers that omit usage fields must not crash accounting."""
    trace = TraceCollector(query="q")
    # None fields exercise the `or 0` guards.
    _record_usage(SimpleNamespace(prompt_tokens=None, completion_tokens=None))
    # A missing usage object entirely must also be a no-op.
    _record_usage(None)
    record = trace.finalize()
    assert record.prompt_tokens == 0
    assert record.completion_tokens == 0


def test_usage_outside_request_is_noop():
    """Recording usage with no active collector must not raise."""
    assert get_current_trace() is None
    # Should silently do nothing.
    _record_usage(_usage(10, 10))
