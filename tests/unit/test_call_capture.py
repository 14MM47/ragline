"""Per-call records, evaluation transcripts and their archive (docs/eval/call-capture-plan.md).

No network, no pod: the SDK client is an AsyncMock, Qdrant an httpx MockTransport,
and the scripts are loaded as modules from scripts/.
"""

import gzip
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from ragline.config import settings
from ragline.llm.openai_provider import OpenAIProvider
from ragline.tracing.collector import TraceCollector

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    """Load scripts/<name>.py as a module."""
    spec = importlib.util.spec_from_file_location(f"{name}_script", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _response(content: str, reasoning: str | None = None, finish: str = "stop"):
    """A stand-in ChatCompletion with the fields the provider reads."""
    message = SimpleNamespace(content=content)
    if reasoning is not None:
        message.reasoning = reasoning
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=40, total_tokens=160)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=usage)


def _provider(create: AsyncMock) -> OpenAIProvider:
    """An OpenAIProvider whose SDK client is the given mock."""
    provider = OpenAIProvider(model="m")
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return provider


# --- 1. per-call records ---------------------------------------------------------


async def test_each_call_is_recorded_with_numbers_only_by_default(monkeypatch):
    """Purpose, tokens each way, reasoning length, time, finish reason, ceiling — no text."""
    monkeypatch.setattr(settings, "llm_extra_body", "")
    monkeypatch.setattr(settings, "llm_capture_transcripts", False)
    trace = TraceCollector(query="q")
    provider = _provider(AsyncMock(return_value=_response("8.4 W", reasoning="think")))
    await provider.complete([{"role": "user", "content": "q"}], max_tokens=1500, answer=True)
    await provider.complete([], max_tokens=1024, purpose="confidence")
    trace.finalize()
    answer, side = trace.calls
    assert answer["purpose"] == "answer" and answer["answer"] is True
    assert answer["prompt_tokens"] == 120 and answer["completion_tokens"] == 40 and answer["reasoning_chars"] == 5
    assert answer["finish_reason"] == "stop" and answer["max_tokens"] == 1500 and answer["temperature"] == 0.0
    assert answer["ms"] >= 0 and "tok_s" in answer
    assert side["purpose"] == "confidence" and side["answer"] is False
    assert not any(k in answer for k in ("messages", "response", "reasoning"))


async def test_transcripts_kept_only_when_switched_on(monkeypatch):
    """With LLM_CAPTURE_TRANSCRIPTS on, the call keeps messages, response and reasoning text."""
    monkeypatch.setattr(settings, "llm_extra_body", "")
    monkeypatch.setattr(settings, "llm_capture_transcripts", True)
    trace = TraceCollector(query="q")
    messages = [{"role": "user", "content": "How much power?"}]
    await _provider(AsyncMock(return_value=_response("8.4 W", reasoning="let me see"))).complete(messages, answer=True)
    trace.finalize()
    call = trace.calls[0]
    assert call["messages"] == messages and call["response"] == "8.4 W" and call["reasoning"] == "let me see"


async def test_json_calls_are_recorded_with_their_purpose(monkeypatch):
    """The JSON-mode pre-pass is recorded under its purpose with its ceiling."""
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool

    monkeypatch.setattr(settings, "llm_extra_body", "")
    trace = TraceCollector(query="q")
    await _provider(AsyncMock(return_value=_response('{"ok": true}'))).complete_json(
        [], _Out, max_tokens=1024, purpose="prepass")
    trace.finalize()
    assert trace.calls[0]["purpose"] == "prepass" and trace.calls[0]["max_tokens"] == 1024


async def test_stream_records_time_to_first_token(monkeypatch):
    """A streamed call is one record with a TTFT and the joined text when capturing."""
    monkeypatch.setattr(settings, "llm_extra_body", "")
    monkeypatch.setattr(settings, "llm_capture_transcripts", True)

    async def chunks():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, reasoning="hm"),
                                                       finish_reason=None)])
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"), finish_reason=None)])
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=" there"),
                                                       finish_reason="stop")])
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2))

    trace = TraceCollector(query="q")
    out = [d async for d in _provider(AsyncMock(return_value=chunks())).stream([])]
    trace.finalize()
    call = trace.calls[0]
    assert out == ["hi", " there"] and call["response"] == "hi there" and call["reasoning"] == "hm"
    assert call["ttft_ms"] is not None and call["finish_reason"] == "stop" and call["completion_tokens"] == 2


# --- 2. harness: split, summary, sidecar, manifest ------------------------------

ev = _load("evaluate")


def test_split_calls_moves_text_out():
    """Numbers stay with the question; the full records go to the sidecar only if there is text."""
    plain = [{"purpose": "answer", "ms": 5.0}]
    assert ev.split_calls(plain) == (plain, None)
    full = [{"purpose": "answer", "ms": 5.0, "messages": [], "response": "x", "reasoning": "y"}]
    numbers, text = ev.split_calls(full)
    assert numbers == [{"purpose": "answer", "ms": 5.0}] and text == full


def test_summarise_calls_by_purpose():
    """Calls, tokens each way, reasoning, median tok/s and ms, truncations per purpose."""
    results = [{"calls": [
        {"purpose": "answer", "prompt_tokens": 5000, "completion_tokens": 900, "reasoning_chars": 2000,
         "tok_s": 70.0, "ms": 12000.0, "finish_reason": "stop"},
        {"purpose": "prepass", "prompt_tokens": 600, "completion_tokens": 80, "tok_s": 40.0, "ms": 2000.0},
    ]}, {"calls": [
        {"purpose": "answer", "prompt_tokens": 5200, "completion_tokens": 1100, "reasoning_chars": 0,
         "tok_s": 74.0, "ms": 15000.0, "finish_reason": "length"},
    ]}, {"calls": []}]
    s = ev.summarise_calls(results)
    assert s["answer"] == {"calls": 2, "prompt_tokens": 10200, "completion_tokens": 2000, "reasoning_chars": 2000,
                           "tok_s_median": 72.0, "ms_median": 13500.0, "truncated": 1}
    assert s["prepass"]["calls"] == 1


def test_transcript_sidecar_written_and_redacted(tmp_path):
    """One gzipped JSONL line per question with text; pod hosts are masked like everywhere else."""
    results = [{"id": "A01", "question": "q1", "_transcript": [
        {"purpose": "answer", "messages": [{"role": "user", "content": "see https://abc123xyz789-8000.proxy.runpod.net/v1"}],
         "response": "r", "reasoning": "t"}]},
        {"id": "A02", "question": "q2", "_transcript": None}]
    sidecar = tmp_path / "r1.transcripts.jsonl.gz"
    assert ev.write_transcripts(sidecar, results) == 1
    lines = [json.loads(line) for line in gzip.open(sidecar, "rt")]
    assert [x["id"] for x in lines] == ["A01"]
    assert "abc123xyz789" not in json.dumps(lines)
    assert ev.write_transcripts(tmp_path / "none.jsonl.gz", [{"id": "A", "_transcript": None}]) == 0
    assert not (tmp_path / "none.jsonl.gz").exists()


def test_thinking_label_follows_the_answer_body():
    """ON is answer-only since 2026-10-14: the answer body decides the label."""
    off = {"chat_template_kwargs": {"enable_thinking": False}}
    on = {"chat_template_kwargs": {"enable_thinking": True}}
    assert ev.infer_thinking(off, on) == "on" and ev.infer_thinking(off, {}) == "off"
    assert ev.infer_thinking({}, None) == "unset"


# --- 3. report -----------------------------------------------------------------

rep = _load("eval_report")


def test_report_call_metrics_from_records_and_fallback():
    """Exact per-call numbers when present; a marked approximation for older runs."""
    with_calls = [{"calls": [{"purpose": "answer", "prompt_tokens": 5000, "completion_tokens": 1000,
                              "reasoning_chars": 3000, "tok_s": 75.0, "ms": 13000.0, "finish_reason": "stop"},
                             {"purpose": "prepass", "prompt_tokens": 600, "completion_tokens": 100}]}]
    m = rep.call_metrics(with_calls)
    assert m["source"] == "calls" and m["answer_tok_s_median"] == 75.0 and m["answer_prompt_tokens_per_q"] == 5000
    assert m["side_prompt_tokens_per_q"] == 600 and m["answer_truncated"] == 0
    old = [{"completion_tokens": 1000, "step_ms": {"answer": 10000.0}, "reasoning_chars": 0}]
    m = rep.call_metrics(old)
    assert m["source"] == "approx" and m["answer_tok_s_median"] == 100.0


def test_report_thinking_label_repairs_older_manifests():
    """A pre-fix ON manifest labelled "off" is read as "on" from its condition env."""
    meta = {"thinking": "off", "extra": {"condition_env": {
        "ANSWER_EXTRA_BODY": "'{\"chat_template_kwargs\": {\"enable_thinking\": true}, \"top_p\": 0.95}'"}}}
    assert rep.thinking_of(meta) == "on"
    assert rep.thinking_of({"thinking": "off", "extra": {"condition_env": {"ANSWER_EXTRA_BODY": ""}}}) == "off"
    assert rep.thinking_of({"answer_extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}) == "off"


# --- 4. archive and transcript viewer ---------------------------------------------

arc = _load("eval_archive")


def test_archive_transcripts_copies_and_skips(tmp_path):
    """Sidecars land under dest/<campaign>/..., identical ones are skipped, checksums listed."""
    camp = tmp_path / "eval-x"
    (camp / "r2" / "on").mkdir(parents=True)
    side = camp / "r2" / "on" / "r1.transcripts.jsonl.gz"
    with gzip.open(side, "wt") as fh:
        fh.write('{"id": "A01"}\n')
    (camp / "r2" / "on" / "r1.json").write_text("{}")                  # not a transcript: ignored
    dest = tmp_path / "archive"
    assert arc.archive_transcripts(camp, dest)["copied"] == 1
    assert (dest / "eval-x" / "r2" / "on" / "r1.transcripts.jsonl.gz").is_file()
    assert not (dest / "eval-x" / "r2" / "on" / "r1.json").exists()
    again = arc.archive_transcripts(camp, dest)
    assert again["copied"] == 0 and again["already_archived"] == 1
    assert json.loads((dest / "eval-x" / "transcripts.sha256.json").read_text())["r2/on/r1.transcripts.jsonl.gz"]


def test_archive_index_snapshot_and_db_backup(tmp_path):
    """Qdrant snapshot streamed and cleaned up; SQLite copied consistently; digest written."""
    db = tmp_path / "eval.db"
    con = sqlite3.connect(db)
    con.execute("create table t (x int)")
    con.execute("insert into t values (7)")
    con.commit()
    con.close()
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path))
        if req.method == "POST":
            return httpx.Response(200, json={"result": {"name": "snap-1.snapshot"}})
        if req.method == "GET":
            return httpx.Response(200, content=b"SNAPSHOTBYTES")
        return httpx.Response(200, json={"result": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    digest = arc.archive_index("coll", db, tmp_path / "archive", "http://qdrant", client)
    folder = next((tmp_path / "archive").glob("index-coll-*"))
    assert (folder / "coll.snapshot").read_bytes() == b"SNAPSHOTBYTES" and digest["snapshot"]["bytes"] == 13
    assert sqlite3.connect(folder / "eval.db").execute("select x from t").fetchone() == (7,)
    assert ("DELETE", "/collections/coll/snapshots/snap-1.snapshot") in seen
    assert json.loads((folder / "digest.json").read_text())["db"]["sha256"] == digest["db"]["sha256"]


def test_transcript_viewer_renders_one_question(tmp_path):
    """The viewer finds the question and prints its calls, filterable by purpose."""
    side = tmp_path / "r1.transcripts.jsonl.gz"
    with gzip.open(side, "wt") as fh:
        fh.write(json.dumps({"id": "A09", "question": "RAM?", "calls": [
            {"purpose": "prepass", "messages": [{"role": "user", "content": "rewrite"}], "response": "{}"},
            {"purpose": "answer", "messages": [{"role": "system", "content": "SYS"}], "response": "512 MB",
             "reasoning": "look at table", "prompt_tokens": 5000, "completion_tokens": 300}]}) + "\n")
    view = _load("eval_transcript")
    entry = view.load_question(side, "A09")
    text = view.render(entry, purpose="answer")
    assert "512 MB" in text and "look at table" in text and "SYS" in text and "rewrite" not in text
    assert "SYS" not in view.render(entry, purpose="answer", messages=False)
    assert view.load_question(side, "Z99") is None


# --- 5. campaign wiring ---------------------------------------------------------

ec = _load("eval_campaign")


def test_campaign_validates_archive_dest(tmp_path):
    """[archive].dest must be absolute (it goes into a subprocess)."""
    c = ec.load_campaign(SCRIPTS.parent / "eval" / "campaign" / "eval-2026-10.toml")
    c["archive"] = {"dest": "relative/path"}
    with pytest.raises(ec.CampaignError):
        ec.validate_campaign(c)
    c["archive"] = {"dest": "/mnt/c/archive"}
    ec.validate_campaign(c)
    cmd = ec.archive_cmd(c, "/mnt/c/archive")
    assert cmd[1].endswith("eval_archive.py") and cmd[2] == "transcripts" and cmd[-1] == "/mnt/c/archive"


async def test_invalid_json_reply_is_recorded_as_such(monkeypatch):
    """A JSON reply that fails validation is still a recorded call, flagged json_valid False."""
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool

    monkeypatch.setattr(settings, "llm_extra_body", "")
    trace = TraceCollector(query="q")
    provider = _provider(AsyncMock(return_value=_response('{"ok": tr', finish="length")))
    with pytest.raises(Exception):
        # Bypass the retry wrapper: one attempt, one record.
        await OpenAIProvider.complete_json.__wrapped__(provider, [], _Out, max_tokens=8, purpose="prepass")
    trace.finalize()
    assert [c["json_valid"] for c in trace.calls] == [False] and trace.calls[0]["finish_reason"] == "length"
