"""LLM_EXTRA_BODY and reasoning capture (evaluation plan, Phase 1 step 1).

Three behaviours the evaluation campaign's thinking switch depends on:
  1. the setting is validated at startup (empty or a JSON object, nothing else),
  2. the provider sends `extra_body` only when the setting is non-empty, on
     every call shape (plain, JSON mode, streaming),
  3. a server's separated `reasoning_content` is counted on the trace and never
     reaches the returned text.
No network: the SDK client is replaced by an AsyncMock recording its kwargs.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from ragline.config import Settings, settings
from ragline.llm.openai_provider import OpenAIProvider
from ragline.tracing.collector import TraceCollector

# --- 1. validation ---------------------------------------------------------


def test_setting_defaults_to_empty():
    """An unset LLM_EXTRA_BODY is "" and parses to an empty dict."""
    s = Settings(_env_file=None)
    assert s.llm_extra_body == ""
    assert s.llm_extra_body_dict == {}


def test_setting_accepts_a_json_object():
    """A JSON object is kept verbatim and parsed on demand."""
    s = Settings(_env_file=None, llm_extra_body='{"chat_template_kwargs": {"enable_thinking": true}}')
    assert s.llm_extra_body_dict == {"chat_template_kwargs": {"enable_thinking": True}}


@pytest.mark.parametrize("bad", ["[1, 2]", "42", '"str"', "{not json"])
def test_setting_rejects_non_object(bad):
    """Lists, scalars and malformed text fail construction, not a later request."""
    with pytest.raises(ValueError):
        Settings(_env_file=None, llm_extra_body=bad)


@pytest.mark.parametrize("clash", ['{"model": "other"}', '{"messages": []}', '{"temperature": 1}', '{"stream": true}'])
def test_setting_rejects_request_parameter_overrides(clash):
    """extra_body is merged over the named parameters, so those keys are refused."""
    with pytest.raises(ValueError):
        Settings(_env_file=None, llm_extra_body=clash)


def test_setting_reads_single_quoted_dotenv_value(tmp_path):
    """The documented .env form (single-quoted JSON) survives dotenv parsing."""
    env = tmp_path / ".env"
    env.write_text("LLM_EXTRA_BODY='{\"chat_template_kwargs\": {\"enable_thinking\": false}}'\n")
    s = Settings(_env_file=env)
    assert s.llm_extra_body_dict == {"chat_template_kwargs": {"enable_thinking": False}}


# --- 2. + 3. provider behaviour ---------------------------------------------


def _response(content: str, reasoning: str | None = None) -> SimpleNamespace:
    """A stand-in for the SDK's ChatCompletion with the fields the provider reads."""
    message = SimpleNamespace(content=content)
    if reasoning is not None:
        # vLLM's reasoning parser adds this non-schema field to the message.
        message.reasoning_content = reasoning
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def _provider(create: AsyncMock) -> OpenAIProvider:
    """An OpenAIProvider whose SDK client is replaced by the given mock."""
    provider = OpenAIProvider(model="m")
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return provider


async def test_complete_omits_extra_body_when_unset(monkeypatch):
    """Production default: the request has no extra_body key at all."""
    monkeypatch.setattr(settings, "llm_extra_body", "")
    create = AsyncMock(return_value=_response("answer"))
    assert await _provider(create).complete([{"role": "user", "content": "q"}]) == "answer"
    assert "extra_body" not in create.call_args.kwargs


async def test_complete_sends_extra_body_when_set(monkeypatch):
    """The parsed setting is passed as extra_body on a plain completion."""
    monkeypatch.setattr(settings, "llm_extra_body", '{"chat_template_kwargs": {"enable_thinking": true}}')
    create = AsyncMock(return_value=_response("answer"))
    await _provider(create).complete([{"role": "user", "content": "q"}])
    assert create.call_args.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}


class _Out(BaseModel):
    """Tiny schema for the JSON-mode path."""

    ok: bool


async def test_complete_json_sends_extra_body(monkeypatch):
    """JSON-mode completions carry the same extra_body."""
    monkeypatch.setattr(settings, "llm_extra_body", '{"top_k": 1}')
    create = AsyncMock(return_value=_response('{"ok": true}'))
    result = await _provider(create).complete_json([], _Out)
    assert result.ok is True
    assert create.call_args.kwargs["extra_body"] == {"top_k": 1}


async def test_stream_sends_extra_body_and_counts_reasoning(monkeypatch):
    """Streaming passes extra_body and counts reasoning deltas without yielding them."""
    monkeypatch.setattr(settings, "llm_extra_body", '{"top_k": 1}')

    async def chunks():
        # A reasoning delta, a text delta, then the usage-only final chunk.
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, reasoning_content="hmm"))])
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"))])
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))

    create = AsyncMock(return_value=chunks())
    trace = TraceCollector(query="q")
    out = [d async for d in _provider(create).stream([])]
    record = trace.finalize()
    assert out == ["hi"]
    assert create.call_args.kwargs["extra_body"] == {"top_k": 1}
    assert record.reasoning_chars == 3


async def test_reasoning_content_counted_not_returned(monkeypatch):
    """Separated reasoning lands on the trace as a length; the text stays clean."""
    monkeypatch.setattr(settings, "llm_extra_body", "")
    create = AsyncMock(return_value=_response("8.4 W", reasoning="let me think " * 10))
    trace = TraceCollector(query="q")
    text = await _provider(create).complete([])
    record = trace.finalize()
    assert text == "8.4 W"
    assert "think" not in text
    assert record.reasoning_chars == len("let me think " * 10)
    # Token totals still accumulate as before.
    assert record.prompt_tokens == 10 and record.completion_tokens == 5


def test_reasoning_chars_defaults_to_zero():
    """A turn with no reasoning records 0, so older analyses are unaffected."""
    record = TraceCollector(query="q").finalize()
    assert record.reasoning_chars == 0


# --- 4. answer-only options and the current vLLM reasoning field (2026-10-14) ---


def test_answer_extra_body_validated_like_llm_extra_body():
    """ANSWER_EXTRA_BODY: empty or a JSON object, no request-parameter keys, named in errors."""
    assert Settings(_env_file=None).answer_extra_body_dict == {}
    s = Settings(_env_file=None, answer_extra_body='{"chat_template_kwargs": {"enable_thinking": true}}')
    assert s.answer_extra_body_dict == {"chat_template_kwargs": {"enable_thinking": True}}
    with pytest.raises(ValueError, match="ANSWER_EXTRA_BODY"):
        Settings(_env_file=None, answer_extra_body="[1]")
    with pytest.raises(ValueError, match="ANSWER_EXTRA_BODY"):
        Settings(_env_file=None, answer_extra_body='{"max_tokens": 9}')


async def test_answer_extra_body_only_on_answer_calls(monkeypatch):
    """Answer calls get ANSWER_EXTRA_BODY merged over LLM_EXTRA_BODY; other calls do not."""
    monkeypatch.setattr(settings, "llm_extra_body", '{"chat_template_kwargs": {"enable_thinking": false, "x": 1}}')
    monkeypatch.setattr(settings, "answer_extra_body", '{"chat_template_kwargs": {"enable_thinking": true}}')
    create = AsyncMock(return_value=_response("a"))
    provider = _provider(create)
    await provider.complete([], answer=True)
    # Nested objects merge key by key: thinking flips, the other key survives.
    assert create.call_args.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True, "x": 1}}
    await provider.complete([])
    assert create.call_args.kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False, "x": 1}}
    create = AsyncMock(return_value=_response('{"ok": true}'))
    await _provider(create).complete_json([], _Out)                      # side calls: never the answer body
    assert create.call_args.kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


async def test_answer_extra_body_alone(monkeypatch):
    """With LLM_EXTRA_BODY empty, an answer call sends only ANSWER_EXTRA_BODY and others send nothing."""
    monkeypatch.setattr(settings, "llm_extra_body", "")
    monkeypatch.setattr(settings, "answer_extra_body", '{"top_k": 2}')
    create = AsyncMock(return_value=_response("a"))
    provider = _provider(create)
    await provider.complete([], answer=True)
    assert create.call_args.kwargs["extra_body"] == {"top_k": 2}
    await provider.complete([])
    assert "extra_body" not in create.call_args.kwargs


async def test_reasoning_field_of_current_vllm_is_counted(monkeypatch):
    """Current vLLM names the field `reasoning`; it is counted like `reasoning_content`."""
    monkeypatch.setattr(settings, "llm_extra_body", "")
    message = SimpleNamespace(content="8.4 W", reasoning="step by step")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))
    trace = TraceCollector(query="q")
    assert await _provider(AsyncMock(return_value=response)).complete([]) == "8.4 W"
    assert trace.finalize().reasoning_chars == len("step by step")



# --- 5. side-call ceilings and the slow-call warning (2026-10-15) --------------


def test_side_call_ceilings_default():
    """Pre-pass, memory and confidence calls are capped by default; the slow-call log is on."""
    s = Settings(_env_file=None)
    assert s.prepass_max_tokens == 1024 and s.post_pass_max_tokens == 1024 and s.confidence_max_tokens == 1024
    assert s.llm_slow_call_s == 120.0


async def test_complete_json_sends_max_tokens_and_warns_on_truncation(monkeypatch):
    """JSON mode passes the ceiling; a cut-off JSON reply is logged before validation fails."""
    import structlog

    monkeypatch.setattr(settings, "llm_extra_body", "")
    response = _response('{"ok": tr')
    response.choices[0].finish_reason = "length"
    create = AsyncMock(return_value=response)
    with structlog.testing.capture_logs() as logs, pytest.raises(Exception):
        await _provider(create).complete_json([], _Out, max_tokens=1024, purpose="prepass")
    assert create.call_args.kwargs["max_tokens"] == 1024
    assert any(e["event"] == "llm json completion truncated at output ceiling" and e["purpose"] == "prepass"
               for e in logs)


async def test_complete_json_without_ceiling_sends_none(monkeypatch):
    """Existing callers that pass no ceiling are unchanged: no max_tokens key."""
    monkeypatch.setattr(settings, "llm_extra_body", "")
    create = AsyncMock(return_value=_response('{"ok": true}'))
    await _provider(create).complete_json([], _Out)
    assert "max_tokens" not in create.call_args.kwargs


async def test_slow_call_is_logged_with_its_purpose(monkeypatch):
    """A call over LLM_SLOW_CALL_S is logged with purpose, seconds and tokens; a fast one is not."""
    import structlog

    from ragline.llm import openai_provider as op

    monkeypatch.setattr(settings, "llm_extra_body", "")
    # Each call reads the clock at start, at the slow check and for its record (end repeats).
    clock = iter([100.0, 250.0, 250.0, 300.0, 301.0, 301.0])   # first call 150 s, second 1 s
    monkeypatch.setattr(op, "_now", lambda: next(clock))
    create = AsyncMock(return_value=_response("a"))
    provider = _provider(create)
    with structlog.testing.capture_logs() as logs:
        await provider.complete([], max_tokens=1024, purpose="confidence")
        await provider.complete([], purpose="memory")
    slow = [e for e in logs if e["event"] == "slow llm call"]
    assert len(slow) == 1 and slow[0]["purpose"] == "confidence" and slow[0]["seconds"] == 150.0
    assert slow[0]["max_tokens"] == 1024 and slow[0]["completion_tokens"] == 5


async def test_answer_calls_are_named_answer_in_the_slow_log(monkeypatch):
    """An answer call without an explicit purpose is logged as 'answer'."""
    import structlog

    from ragline.llm import openai_provider as op

    monkeypatch.setattr(settings, "llm_extra_body", "")
    monkeypatch.setattr(settings, "llm_slow_call_s", 0.5)
    clock = iter([0.0, 1.0, 1.0])
    monkeypatch.setattr(op, "_now", lambda: next(clock))
    with structlog.testing.capture_logs() as logs:
        await _provider(AsyncMock(return_value=_response("a"))).complete([], answer=True)
    assert [e["purpose"] for e in logs if e["event"] == "slow llm call"] == ["answer"]



# --- 6. answer-only temperature (2026-10-15) -----------------------------------


def test_answer_temperature_setting():
    """Empty means unset; a value must be a valid sampling temperature."""
    assert Settings(_env_file=None).answer_temperature is None
    assert Settings(_env_file=None, answer_temperature="").answer_temperature is None
    assert Settings(_env_file=None, answer_temperature="0.6").answer_temperature == 0.6
    with pytest.raises(ValueError):
        Settings(_env_file=None, answer_temperature="3")


async def test_answer_temperature_applies_to_answer_calls_only(monkeypatch):
    """Answer calls run at ANSWER_TEMPERATURE; side calls keep the caller's temperature."""
    monkeypatch.setattr(settings, "llm_extra_body", "")
    monkeypatch.setattr(settings, "answer_temperature", 0.6)
    create = AsyncMock(return_value=_response("a"))
    provider = _provider(create)
    await provider.complete([], temperature=0.0, answer=True)
    assert create.call_args.kwargs["temperature"] == 0.6
    await provider.complete([], temperature=0.0)
    assert create.call_args.kwargs["temperature"] == 0.0
    create = AsyncMock(return_value=_response('{"ok": true}'))
    await _provider(create).complete_json([], _Out)
    assert create.call_args.kwargs["temperature"] == 0.0
    monkeypatch.setattr(settings, "answer_temperature", None)
    create = AsyncMock(return_value=_response("a"))
    await _provider(create).complete([], temperature=0.0, answer=True)
    assert create.call_args.kwargs["temperature"] == 0.0            # unset: unchanged
