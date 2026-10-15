"""evaluate.py — run the golden question set against the live pipeline (v2).

Self-contained (raggles' evaluation package is not ported): for every golden
question it runs the answer path and scores, per question:

  * source hit  — do the cited sources include the expected document(s)?
                  (matched on basename, case-insensitive; per question
                  `source_match` "any" = one listed source suffices, "all" /
                  unset = every listed source must be cited)
  * cited       — did the answer carry at least one valid citation?
  * page sanity — is every cited page within its document's page count?
  * retrieval   — what the retriever produced BEFORE generation: the fused
                  top-20 and reranked top-8 candidates, scored against the
                  expected documents/pages (recall@20, recall@8, MRR, nDCG@8,
                  page hit, distractor retrieved/cited)
  * declined    — did the answer say it could not answer (and cite nothing)?
  * think residue — did raw thinking text leak into the answer? (must be 0)

plus the answer text for the judge, token totals, hidden-reasoning length and
per-stage timings per question.

Two answer paths:
  --path rag   (default) one-shot `RAGAgent.query()`, as /query does. Follow-up
               questions are asked cold (no previous turn) and flagged.
  --path chat  `ChatAgent.chat()` with a fresh session per question, seeded
               with the entry's `history` turns — the only way the five
               follow-ups are measured honestly. Uses its own temporary
               session directory, never the app's memory store.

Usage:
    python scripts/evaluate.py eval/golden_set_hmi.json
    python scripts/evaluate.py eval/golden_set_hmi.json --output results.json
    python scripts/evaluate.py eval/golden_set_hmi.json -o eval/results/<date>_<label>.json --label <stack-name>
    python scripts/evaluate.py eval/golden_set_hmi.json --path chat --repeats 3 --warmup 3 \\
        --campaign eval-2026-10 --rung r2 --condition off --manifest-extra '{"gpu": "RTX PRO 6000"}'

With --campaign the results go to eval/results/<campaign>/<rung>/<condition>/r<N>.json
(one file per repeat); with --output and --repeats > 1 the files are
<output>_r<N>.json. Exit codes: 0 ok; 1 hit-rate below --threshold; 2 thinking
text leaked into an answer (the condition is invalid regardless of scores).

The results file records the stack it ran against (models, endpoint hosts,
git rev, golden-set digest, index size, thinking mode, extra manifest fields
the campaign runner supplies) and per-question latency, so runs on different
stacks can be compared later — see docs/evaluation.md.

Requires: Qdrant up, ingested corpus, configured .env.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ragline.logging_utils import configure_redaction, redact_text, redact_value  # noqa: E402

# How many fused candidates (before rerank) and final results (after rerank)
# are kept per question. 20 is the retrieval top_k the pipeline uses; 8 the
# rerank top_k — both recorded so the numbers can be checked against the run.
MERGED_KEEP = 20
RERANKED_KEEP = 8

# Phrases the answer prompt produces when the sources do not contain the
# answer. A "declined" answer must ALSO carry no citation (see is_declined):
# an answer that cites a page and says "not stated" is a grounded negative,
# which the judge decides, not this regex.
_DECLINE = re.compile(
    r"couldn.t find|could not find|unable to find|cannot find|"
    r"not enough information|no information|"
    r"do(?:es)? not (?:state|mention|specify|provide|say|list|give)|"
    r"not (?:stated|specified|mentioned|provided|listed|given) in|"
    r"cannot (?:answer|determine)|can.t (?:answer|determine)",
    re.IGNORECASE,
)

# Raw thinking markup. vLLM's reasoning parser removes it; its presence means
# the parser was not active and the answer (and its citations) are suspect.
_THINK = re.compile(r"</?think>", re.IGNORECASE)


# --------------------------------------------------------------------------
# Pure helpers — no stack needed, covered by tests/unit/test_evaluate_v2.py
# --------------------------------------------------------------------------


def _basename(path: str) -> str:
    """Case-insensitive basename across / and \\ separators."""
    return path.replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _host(url: str) -> str:
    """Host part of an endpoint URL, safe to publish in a results file.

    RunPod proxy hosts embed the pod id (<pod-id>-<port>.proxy.runpod.net);
    it is masked so a run can be shared without naming the pod.
    """
    if not url:
        return ""
    parts = urlsplit(url)
    host = parts.hostname or ""  # netloc includes basic-auth credentials.
    if ":" in host:
        host = f"[{host}]"  # Preserve IPv6 brackets when appending a port.
    if parts.port is not None:
        host += f":{parts.port}"
    return redact_text(host)


def _public_path(path: str) -> str:
    """Record repository-relative paths, or just a name for external files."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path(__file__).resolve().parent.parent).as_posix()
    except ValueError:
        return resolved.name


def is_declined(answer: str, citation_count: int) -> bool:
    """True when the answer says it cannot answer AND cites nothing."""
    return citation_count == 0 and bool(_DECLINE.search(answer or ""))


def has_think_residue(answer: str) -> bool:
    """True when raw <think> markup survived into the answer text."""
    return bool(_THINK.search(answer or ""))


def source_hit(expected: set[str], cited: set[str], match: str) -> bool | None:
    """The golden set's own rule: "any" (one listed source suffices) or "all"
    (every listed source must be cited; the default). None = nothing expected."""
    if not expected:
        return None
    if match == "any":
        return bool(expected & cited)
    return expected.issubset(cited)


def serialize_candidates(results, limit: int) -> list[dict]:
    """Flatten SearchResult objects to the fields the metrics and report need."""
    out = []
    for r in results[:limit]:
        chunk = r.chunk
        out.append({
            "source": _basename(chunk.source_file),
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "chunk_id": chunk.chunk_id,
            "score": round(float(r.score), 5),
        })
    return out


def union_by_best_rank(calls: list[list[dict]]) -> list[dict]:
    """Merge candidate lists from several retrieve() calls in one turn.

    Compound chat turns can retrieve more than once; a chunk's rank is the
    best (lowest) position it reached in any call, ties broken by call order.
    A single call comes back unchanged.
    """
    best: dict[tuple, tuple[int, int, dict]] = {}
    for call_index, items in enumerate(calls):
        for rank, item in enumerate(items):
            key = (item["source"], item["page_start"], item["chunk_id"])
            if key not in best or rank < best[key][0]:
                best[key] = (rank, call_index, item)
    return [item for _rank, _call, item in sorted(best.values(), key=lambda t: (t[0], t[1]))]


def _relevance(item: dict, expected: dict[str, set[int]]) -> int:
    """0 = not an expected document; 1 = expected document; 2 = and an expected page."""
    pages = expected.get(item["source"])
    if pages is None:
        return 0
    if pages and any(item["page_start"] <= p <= item["page_end"] for p in pages):
        return 2
    return 1


def retrieval_metrics(
    merged: list[dict],
    reranked: list[dict],
    expected_sources: list[str],
    expected_pages: dict[str, list[int]] | None,
    distractor_sources: list[str] | None,
) -> dict:
    """Score the retriever's two candidate lists against the golden entry.

    Document-level recall at the two cut-offs, MRR and nDCG@8 on the reranked
    list (relevance 2 for an expected page of an expected document, 1 for the
    document alone), whether any expected page reached the top-8, and whether
    a known distractor document did. Entries with nothing expected
    (unanswerables, library questions) get None for every metric.

    nDCG is computed at DOCUMENT level: a document is credited once, at the
    rank of its first chunk, with the best relevance any of its top-8 chunks
    reaches; the ideal list is one entry per expected document. Several
    chunks of one document therefore never add up, so nDCG is at most 1.0.
    """
    expected = {
        _basename(s): {int(p) for p in (expected_pages or {}).get(s, [])}
        for s in expected_sources
    }
    if not expected:
        return {
            "recall_at_20": None, "recall_at_8": None, "mrr": None, "ndcg_at_8": None,
            "page_hit": None, "distractor_retrieved": None,
        }
    distractors = {_basename(s) for s in (distractor_sources or [])}

    def recall(items: list[dict]) -> float:
        # Fraction of expected documents that appear at least once.
        seen = {i["source"] for i in items if i["source"] in expected}
        return round(len(seen) / len(expected), 4)

    top = reranked[:RERANKED_KEEP]
    rels = [_relevance(i, expected) for i in top]
    # Mean reciprocal rank: 1 / position of the first relevant chunk, else 0.
    mrr = next((1.0 / (k + 1) for k, rel in enumerate(rels) if rel > 0), 0.0)
    # nDCG@8 at document level: each expected document counts once, at the
    # rank where it first appears, with the best relevance among its chunks.
    best_rel: dict[str, int] = {}
    first_rank: dict[str, int] = {}
    for k, (item, rel) in enumerate(zip(top, rels)):
        if rel > 0:
            first_rank.setdefault(item["source"], k)
            best_rel[item["source"]] = max(best_rel.get(item["source"], 0), rel)
    dcg = sum(best_rel[doc] / math.log2(first_rank[doc] + 2) for doc in first_rank)
    ideal = sorted((2 if pages else 1 for pages in expected.values()), reverse=True)[:RERANKED_KEEP]
    idcg = sum(rel / math.log2(k + 2) for k, rel in enumerate(ideal))
    any_pages = any(expected.values())
    return {
        "recall_at_20": recall(merged[:MERGED_KEEP]),
        "recall_at_8": recall(reranked[:RERANKED_KEEP]),
        "mrr": round(mrr, 4),
        "ndcg_at_8": round(dcg / idcg, 4) if idcg else None,
        "page_hit": (any(rel == 2 for rel in rels) if any_pages else None),
        "distractor_retrieved": (
            any(i["source"] in distractors for i in reranked[:RERANKED_KEEP]) if distractors else None
        ),
    }


def seed_history(session_id: str, history: list[dict]):
    """A SessionMemory holding the golden entry's previous turns.

    Each turn becomes a TurnRecord with the user question and the canned
    answer (no spans or sources — the earlier answer is context, not a
    citation). The chat agent's pre-pass then sees exactly what it would
    after a real previous turn.
    """
    # Imported here so the pure helpers above stay importable without the app.
    from ragline.chat.models import SessionMemory, TurnRecord

    now = datetime.now(timezone.utc).isoformat()
    turns = [
        TurnRecord(
            turn_number=i + 1,
            user_query=turn["user"],
            rewritten_query=turn["user"],
            answer=turn["assistant"],
            spans=[],
            sources=[],
            model_used="golden-history",
            timestamp=now,
        )
        for i, turn in enumerate(history)
    ]
    return SessionMemory(session_id=session_id, created_at=now, turns=turns)


def output_path(args: argparse.Namespace, repeat: int) -> Path | None:
    """Where this repeat's results file goes, or None when nothing is written."""
    if args.campaign:
        # Campaign layout: one directory per rung and condition, one file per repeat.
        root = Path(args.output_dir or "eval/results")
        return root / args.campaign / (args.rung or "rung") / (args.condition or "cond") / f"r{repeat}.json"
    if not args.output:
        return None
    out = Path(args.output)
    if args.repeats > 1:
        return out.with_name(f"{out.stem}_r{repeat}{out.suffix or '.json'}")
    return out


def parse_manifest_extra(text: str | None) -> dict:
    """--manifest-extra: a JSON object inline, or @path to a JSON file."""
    if not text:
        return {}
    if text.startswith("@"):
        text = Path(text[1:]).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("--manifest-extra must be a JSON object")
    return data


def parse_ids(ids_arg: str | None, ids_file: str | None) -> list[str] | None:
    """Collect the ids named by `--ids` and `--ids-file`, in the order given.

    None = neither option was passed (the subset is "everything"). An empty
    list is possible when every line of the file is blank or a comment, and
    the caller should treat that as a user mistake. `#` starts a comment on
    any line; empty lines are ignored; the id itself is the first token on the
    line, stripped.
    """
    if not ids_arg and not ids_file:
        return None
    ids: list[str] = []
    if ids_arg:
        # Comma-separated on the command line (`--ids A09,D05,F12`).
        ids += [piece.strip() for piece in ids_arg.split(",") if piece.strip()]
    if ids_file:
        for raw in Path(ids_file).read_text(encoding="utf-8").splitlines():
            # Strip inline `#` comments, then whitespace.
            line = raw.split("#", 1)[0].strip()
            if line:
                ids.append(line)
    return ids


def select_golden(
    golden: list[dict], ids_arg: str | None, ids_file: str | None
) -> tuple[list[dict], list[str] | None]:
    """Pick the requested subset of golden entries, in golden-set order.

    Returns `(subset, subset_ids)`: `subset_ids is None` when neither option
    was passed (full set). Unknown ids raise `ValueError` listing them, so
    the harness fails before touching the stack.
    """
    requested = parse_ids(ids_arg, ids_file)
    if requested is None:
        # No subset — the whole golden set, in file order.
        return golden, None
    # Map every id in the file to its entry (unidentified entries are ignored
    # for selection but still part of the golden file's digest, which we keep).
    by_id = {pair.get("id"): pair for pair in golden if pair.get("id")}
    unknown = [qid for qid in requested if qid not in by_id]
    if unknown:
        # Error listing them, as the plan requires.
        raise ValueError(f"unknown golden ids: {unknown}")
    # Deduplicate while preserving the golden-set order.
    wanted = set(requested)
    subset = [pair for pair in golden if pair.get("id") in wanted]
    return subset, [pair["id"] for pair in subset]


def infer_thinking(extra_body: dict, answer_body: dict | None = None) -> str:
    """"on"/"off" from a chat_template_kwargs.enable_thinking flag, else "unset".

    The answer-only body wins when it sets the flag: thinking is a property of
    the answers being measured (ON = thinking for answers only, since 2026-10-14).
    """
    answer_flag = ((answer_body or {}).get("chat_template_kwargs") or {}).get("enable_thinking")
    llm_flag = (extra_body.get("chat_template_kwargs") or {}).get("enable_thinking")
    flag = answer_flag if answer_flag is not None else llm_flag
    if flag is True:
        return "on"
    if flag is False:
        return "off"
    return "unset"


# --------------------------------------------------------------------------
# Asking one question — the two paths return the same shape
# --------------------------------------------------------------------------


@dataclass
class Asked:
    """What one answer path produced for one question."""

    answer: str
    sources: list[dict]                       # {source_file, page_number, document_id}
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_chars: int = 0
    step_ms: dict = field(default_factory=dict)
    rewritten_query: str | None = None        # chat path: the pre-pass rewrite
    used_rag: bool | None = None              # chat path: RAG vs library routing
    used_library: bool | None = None
    calls: list = field(default_factory=list)  # per-model-call records (TraceCollector.calls)


async def ask_rag(agent, question: str) -> Asked:
    """One-shot answer via RAGAgent.query(), token-traced per question."""
    from ragline.tracing.collector import TraceCollector

    # Fresh collector per question so token totals are per-question.
    trace = TraceCollector(query=question)
    cited = await agent.query(question)
    record = trace.finalize()
    return Asked(
        answer=cited.raw_text,
        sources=[
            {"source_file": s.source_file, "page_number": s.page_number, "document_id": s.document_id}
            for s in cited.sources_used
        ],
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        reasoning_chars=record.reasoning_chars,
        step_ms=json.loads(record.step_ms),
        # The collector keeps its call list after finalize().
        calls=list(trace.calls),
    )


async def ask_chat(chat_agent, store, session_id: str, question: str, history: list[dict]) -> Asked:
    """Answer via ChatAgent.chat() in a fresh session seeded with `history`."""
    # Seed (or leave empty) the session, then run the real turn with memory on.
    store.save(seed_history(session_id, history))
    formatted, _memory, rewritten = await chat_agent.chat(session_id, question, use_memory=True, store=store)
    return Asked(
        answer=formatted.get("answer", ""),
        sources=[
            {"source_file": s["source_file"], "page_number": s.get("page_number"), "document_id": s.get("document_id")}
            for s in formatted.get("sources", [])
        ],
        prompt_tokens=formatted.get("prompt_tokens") or 0,
        completion_tokens=formatted.get("completion_tokens") or 0,
        reasoning_chars=formatted.get("reasoning_chars") or 0,
        step_ms=formatted.get("step_ms") or {},
        rewritten_query=rewritten,
        used_rag=formatted.get("used_rag"),
        used_library=formatted.get("used_library"),
        calls=formatted.get("llm_calls") or [],
    )


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def _parser_version() -> str:
    """The PDF parser version — the frozen ingestion variable worth recording."""
    try:
        from importlib.metadata import version

        return version("pymupdf4llm")
    except Exception:  # noqa: BLE001 — absent in a minimal install
        return ""


def _run_metadata(args: argparse.Namespace, repeat: int, index: dict,
                  subset_ids: list[str] | None = None) -> dict:
    """What this run ran against, for later comparison. Model names and
    endpoint HOSTS only — never keys."""
    from ragline.config import settings

    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=False).stdout.strip()
    except OSError:
        rev = ""
    golden_path = Path(args.golden_set)
    extra_body = settings.llm_extra_body_dict
    return {
        "label": args.label,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ragline_rev": rev,
        "golden_set": _public_path(args.golden_set),
        "golden_sha256": hashlib.sha256(golden_path.read_bytes()).hexdigest()[:12],
        # Subset selected via `--ids` / `--ids-file`, in golden-set order; None
        # means the full set ran. `golden_sha256` above stays the FULL file's
        # digest so a run on a subset is still traceable to a specific golden set.
        "subset_ids": subset_ids,
        # --- the condition ---------------------------------------------
        "path": args.path,
        "thinking": args.thinking or infer_thinking(extra_body, settings.answer_extra_body_dict),
        "llm_extra_body": extra_body,
        # Answer-only options and output ceilings (first-class since 2026-10-15).
        "answer_extra_body": settings.answer_extra_body_dict,
        "answer_temperature": settings.answer_temperature,
        "answer_max_tokens": settings.answer_max_tokens,
        "library_answer_max_tokens": settings.library_answer_max_tokens,
        "side_call_max_tokens": {"prepass": settings.prepass_max_tokens, "memory": settings.post_pass_max_tokens,
                                 "confidence": settings.confidence_max_tokens},
        "llm_slow_call_s": settings.llm_slow_call_s,
        "transcripts": settings.llm_capture_transcripts,
        "repeat": repeat,
        "repeats": args.repeats,
        "warmup": args.warmup,
        "seed": args.seed,
        "campaign": args.campaign,
        "rung": args.rung,
        "condition": args.condition,
        # --- the stack ---------------------------------------------------
        "llm_model": settings.llm_model,
        "llm_host": _host(settings.llm_base_url),
        "embedding_model": settings.embedding_model,
        "embedding_host": _host(settings.effective_embedding_base_url),
        "embedding_dimensions": settings.embedding_dimensions,
        # The local model name is meaningless for an API reranker (the pod
        # decides the model); record the provider so a reader knows which applies.
        "reranker_provider": settings.reranker_provider,
        "reranker_model": None if settings.reranker_provider == "api" else settings.reranker_model,
        "reranker_host": _host(settings.reranker_base_url),
        "reranker_api_format": settings.reranker_api_format,
        "retrieval_top_k": settings.retrieval_top_k,
        "rerank_top_k": settings.rerank_top_k,
        "parser_version": _parser_version(),
        "index": index,                           # {"collection", "points"}
        # GPU, rate, vLLM args, quantisation… supplied by the campaign runner;
        # empty when run by hand — never guessed here.
        "extra": parse_manifest_extra(args.manifest_extra),
    }


# --------------------------------------------------------------------------
# One pass over the set
# --------------------------------------------------------------------------


async def _ask(ctx: dict, pair: dict, qid: str) -> tuple[Asked, list[dict], list[dict], int]:
    """Run one question through the chosen path with retrieval capture on."""
    calls: list[tuple[list[dict], list[dict]]] = []
    # The pipeline is a process singleton; attach a per-question observer.
    ctx["pipeline"].capture = lambda merged, reranked: calls.append(
        (serialize_candidates(merged, MERGED_KEEP), serialize_candidates(reranked, RERANKED_KEEP))
    )
    try:
        if ctx["path"] == "chat":
            asked = await ask_chat(ctx["chat_agent"], ctx["store"], f"eval-{ctx['run_id']}-{qid}",
                                   pair["question"], pair.get("history") or [])
        else:
            asked = await ask_rag(ctx["agent"], pair["question"])
    finally:
        ctx["pipeline"].capture = None
    merged = union_by_best_rank([c[0] for c in calls])
    reranked = union_by_best_rank([c[1] for c in calls])
    return asked, merged, reranked, len(calls)


async def run_pass(golden: list[dict], ctx: dict, repeat: int) -> list[dict]:
    """Ask every golden question once; return the per-question records."""
    from ragline.storage.metadata_db import get_document

    results: list[dict] = []
    for i, pair in enumerate(golden, start=1):
        question = pair["question"]
        qid = pair.get("id") or f"q{i}"
        expected = {_basename(s) for s in pair.get("expected_sources", [])}
        match = pair.get("source_match", "all")
        started = time.perf_counter()

        # One flaky endpoint call must not kill a long run: contain any error
        # to this question, record it as a miss, and continue with the rest.
        try:
            asked, merged, reranked, n_calls = await _ask(ctx, pair, qid)

            cited_files = {_basename(s["source_file"]) for s in asked.sources}
            hit = source_hit(expected, cited_files, match)

            # Page sanity: each citation's page must exist in its document.
            pages_ok = True
            for s in asked.sources:
                doc = await get_document(s["document_id"]) if s.get("document_id") else None
                if doc and s.get("page_number") and doc.page_count and s["page_number"] > doc.page_count:
                    pages_ok = False

            distractors = {_basename(s) for s in pair.get("distractor_sources", [])}
            call_numbers, call_text = split_calls(asked.calls)
            metrics = retrieval_metrics(merged, reranked, pair.get("expected_sources", []),
                                        pair.get("expected_pages"), pair.get("distractor_sources"))
            results.append({
                "id": qid,
                "category": pair.get("category"),
                "question": question,
                "expected_sources": sorted(expected),
                "source_match": match,
                "cited_sources": sorted(cited_files),
                # (file, page) pairs; a citation without a page sorts first.
                "cited_pages": sorted({(_basename(s["source_file"]), s.get("page_number")) for s in asked.sources},
                                      key=lambda t: (t[0], t[1] or 0)),
                "source_hit": hit,
                "cited": bool(asked.sources),
                "pages_ok": pages_ok,
                "declined": is_declined(asked.answer, len(asked.sources)),
                "think_residue": has_think_residue(asked.answer),
                "distractor_cited": (bool(cited_files & distractors) if distractors else None),
                "answer": asked.answer,
                "expected_answer": pair.get("expected_answer", ""),
                "tokens": asked.prompt_tokens + asked.completion_tokens,
                "prompt_tokens": asked.prompt_tokens,
                "completion_tokens": asked.completion_tokens,
                "reasoning_chars": asked.reasoning_chars,
                "latency_s": round(time.perf_counter() - started, 2),
                "step_ms": asked.step_ms,
                "history_replayed": bool(pair.get("history")) and ctx["path"] == "chat",
                "rewritten_query": asked.rewritten_query,
                "used_rag": asked.used_rag,
                "used_library": asked.used_library,
                "retrieval": {"calls": n_calls, "merged": merged, "reranked": reranked, **metrics},
                "tags": pair.get("tags", []),
                # Numbers per model call; the text (if captured) goes to the sidecar.
                "calls": call_numbers,
                "_transcript": call_text,
            })

            status = "HIT " if hit else ("MISS" if hit is not None else "n/a ")
            flags = ("  DECLINED" if results[-1]["declined"] else "") + (
                "  THINK-RESIDUE" if results[-1]["think_residue"] else "")
            print(redact_text(f"[{i}/{len(golden)}] {status} {question[:70]}{flags}"))
            print(redact_text(f"        cited: {sorted(cited_files) or '(none)'}  tokens: {results[-1]['tokens']}"
                              f"  recall@8: {metrics['recall_at_8']}"))
        except Exception as exc:  # noqa: BLE001 — deliberate catch-all per question
            # Scored as a miss (False) when sources were expected, so the
            # hit-rate denominator stays honest; None keeps unscored questions
            # out of the rate exactly as in the success path.
            results.append({
                "id": qid,
                "category": pair.get("category"),
                "question": question,
                "expected_sources": sorted(expected),
                "source_match": match,
                "cited_sources": [],
                "cited_pages": [],
                "source_hit": False if expected else None,
                "cited": False,
                "pages_ok": True,
                "declined": False,
                "think_residue": False,
                "distractor_cited": None,
                "answer": "",
                "expected_answer": pair.get("expected_answer", ""),
                "tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_chars": 0,
                "latency_s": round(time.perf_counter() - started, 2),
                "step_ms": {},
                "history_replayed": bool(pair.get("history")) and ctx["path"] == "chat",
                "retrieval": retrieval_metrics([], [], [], None, None) | {"calls": 0, "merged": [], "reranked": []},
                "tags": pair.get("tags", []),
                "calls": [],
                "error": redact_text(str(exc)),
            })
            print(redact_text(f"[{i}/{len(golden)}] ERR  {question[:70]}"))
            print(f"        error: {results[-1]['error']}")
    return results


def _mean(values: list) -> float | None:
    """Mean of the non-None values, or None when there are none."""
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


# Text fields of a call record (present only with LLM_CAPTURE_TRANSCRIPTS on):
# kept out of the results JSON and written to the transcript sidecar instead.
TRANSCRIPT_KEYS = ("messages", "response", "reasoning")


def split_calls(calls: list[dict]) -> tuple[list[dict], list[dict] | None]:
    """(numbers-only call records, full records or None when there is no text)."""
    numbers = [{k: v for k, v in c.items() if k not in TRANSCRIPT_KEYS} for c in calls]
    has_text = any(any(k in c for k in TRANSCRIPT_KEYS) for c in calls)
    return numbers, (list(calls) if has_text else None)


def summarise_calls(results: list[dict]) -> dict:
    """Per call purpose: count, tokens each way, reasoning, median end-to-end tok/s and ms."""
    by: dict[str, list[dict]] = {}
    for r in results:
        for c in r.get("calls", []):
            by.setdefault(c.get("purpose") or "unlabelled", []).append(c)

    def med(values):
        values = [v for v in values if v is not None]
        return round(statistics.median(values), 1) if values else None

    return {
        purpose: {
            "calls": len(cs),
            "prompt_tokens": sum(c.get("prompt_tokens") or 0 for c in cs),
            "completion_tokens": sum(c.get("completion_tokens") or 0 for c in cs),
            "reasoning_chars": sum(c.get("reasoning_chars") or 0 for c in cs),
            "tok_s_median": med([c.get("tok_s") for c in cs]),
            "ms_median": med([c.get("ms") for c in cs]),
            "truncated": sum(1 for c in cs if c.get("finish_reason") == "length"),
        }
        for purpose, cs in sorted(by.items())
    }


def write_transcripts(path: Path, results: list[dict]) -> int:
    """Write the full per-call text of a pass to a gzipped JSONL sidecar; returns lines written."""
    import gzip

    lines = [{"id": r["id"], "question": r.get("question"), "calls": r["_transcript"]}
             for r in results if r.get("_transcript")]
    if not lines:
        return 0
    # Written to a temp name and renamed, so a failed write never leaves a
    # truncated sidecar that the archive step would copy.
    tmp = path.with_name(path.name + ".part")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for line in lines:
            # Same redaction as the results file and the run log.
            fh.write(json.dumps(redact_value(line)) + "\n")
    tmp.replace(path)
    return len(lines)


def summarise(results: list[dict]) -> dict:
    """The scorecard numbers for one pass."""
    scored = [r for r in results if r["source_hit"] is not None]
    hits = sum(1 for r in scored if r["source_hit"])
    step_names: list[str] = []
    for r in results:
        step_names += [name for name in r.get("step_ms", {}) if name not in step_names]
    # Median over the questions in which the stage actually ran (a stage a
    # question skipped, e.g. graph, must not enter as a zero).
    step_medians = {
        name: round(statistics.median(r["step_ms"][name] for r in results if name in r.get("step_ms", {})), 1)
        for name in step_names
    }
    latencies = sorted(r["latency_s"] for r in results)
    return {
        "hits": hits,
        "scored": len(scored),
        "hit_rate": hits / len(scored) if scored else 0.0,
        "cited_rate": sum(1 for r in results if r["cited"]) / len(results) if results else 0.0,
        "pages_ok": all(r["pages_ok"] for r in results),
        "declined": sum(1 for r in results if r["declined"]),
        "think_residue": sum(1 for r in results if r["think_residue"]),
        "errors": sum(1 for r in results if r.get("error")),
        "total_tokens": sum(r["tokens"] for r in results),
        "total_reasoning_chars": sum(r.get("reasoning_chars", 0) for r in results),
        "latency_median_s": statistics.median(latencies) if latencies else None,
        "latency_p90_s": latencies[int(0.9 * (len(latencies) - 1))] if latencies else None,
        "step_ms_median": step_medians,
        "retrieval_mean": {
            key: _mean([r["retrieval"].get(key) for r in results])
            for key in ("recall_at_20", "recall_at_8", "mrr", "ndcg_at_8")
        },
        "page_hit_rate": _mean([r["retrieval"].get("page_hit") for r in results]),
        "distractor_retrieved": sum(1 for r in results if r["retrieval"].get("distractor_retrieved")),
        "distractor_cited": sum(1 for r in results if r.get("distractor_cited")),
        # Per-model-call breakdown (empty for runs recorded before 2026-10-15).
        "calls_by_purpose": summarise_calls(results),
    }


def print_scorecard(s: dict) -> None:
    """Human-readable summary of one pass."""
    print("\n=== Scorecard ===")
    print(f"source hit-rate : {s['hits']}/{s['scored']} = {s['hit_rate']:.2f}")
    print(f"cited answers   : {s['cited_rate']:.2f}")
    print(f"page sanity     : {'ok' if s['pages_ok'] else 'FAILURES (see results)'}")
    print(f"declined        : {s['declined']}    errors: {s['errors']}    think residue: {s['think_residue']}")
    rm = s["retrieval_mean"]
    print(f"retrieval       : recall@20 {rm['recall_at_20']}  recall@8 {rm['recall_at_8']}  "
          f"MRR {rm['mrr']}  nDCG@8 {rm['ndcg_at_8']}  page-hit {s['page_hit_rate']}")
    print(f"distractors     : retrieved {s['distractor_retrieved']}  cited {s['distractor_cited']}")
    print(f"latency         : median {s['latency_median_s']} s  p90 {s['latency_p90_s']} s")
    print(f"total tokens    : {s['total_tokens']}    reasoning chars: {s['total_reasoning_chars']}")
    if s["step_ms_median"]:
        print("median stage ms : " + ", ".join(f"{name} {ms:.0f}" for name, ms in s["step_ms_median"].items()))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ragline golden-set evaluation")
    parser.add_argument("golden_set", help="Path to golden Q&A pairs JSON file")
    parser.add_argument("--output", "-o", help="Write full results to a JSON file (per repeat: <stem>_r<N>.json)")
    parser.add_argument(
        "--threshold", "-t", type=float, default=0.0,
        help="Minimum source hit-rate to pass (exit code 1 if below)",
    )
    parser.add_argument("--label", default="", help="Free-text name for this stack/run, kept in the results")
    parser.add_argument("--path", choices=["rag", "chat"], default="rag",
                        help="rag = one-shot RAGAgent.query (default); chat = ChatAgent with history replay")
    parser.add_argument("--repeats", type=int, default=1, help="Full passes over the set (default 1)")
    parser.add_argument("--warmup", type=int, default=0,
                        help="Untimed, unscored questions asked before the first pass (default 0)")
    parser.add_argument("--seed", type=int, default=0, help="Recorded in the manifest (generation is temperature 0)")
    parser.add_argument("--thinking", choices=["off", "on", "unset"], default=None,
                        help="Override the thinking mode recorded (default: inferred from LLM_EXTRA_BODY)")
    parser.add_argument("--campaign", default=None,
                        help="Campaign name: results go to <output-dir>/<campaign>/<rung>/<condition>/")
    parser.add_argument("--rung", default=None, help="Campaign rung name (with --campaign)")
    parser.add_argument("--condition", default=None, help="Campaign condition name, e.g. off/on (with --campaign)")
    parser.add_argument("--output-dir", default=None, help="Root for campaign results (default eval/results)")
    parser.add_argument("--manifest-extra", default=None,
                        help="JSON object (or @file) merged into the run manifest: GPU, rate, vLLM args…")
    # Subset selection (plan item 14): run only the named golden-set ids.
    parser.add_argument("--ids", default=None,
                        help="Comma-separated golden-set ids to run (e.g. A09,D05); the full set otherwise")
    parser.add_argument("--ids-file", default=None,
                        help="File with one golden-set id per line (`#` starts a comment); merged with --ids")
    return parser


async def main() -> int:
    args = build_parser().parse_args()
    if args.repeats < 1:
        print("--repeats must be >= 1", file=sys.stderr)
        return 1
    if args.campaign and not (args.rung and args.condition):
        print("--campaign needs --rung and --condition", file=sys.stderr)
        return 1
    parse_manifest_extra(args.manifest_extra)       # fail early on a bad value

    # Configure both logging systems before imports/client construction; the
    # reranker logs its endpoint on startup and HTTP errors include full URLs.
    from ragline.config import settings

    logging.basicConfig(level=settings.log_level.upper())
    configure_redaction()

    # Deferred imports so --help never touches the stack.
    from ragline.api.dependencies import get_llm, get_rag_agent, get_retrieval_pipeline, get_vector_store
    from ragline.storage.metadata_db import init_db

    await init_db()

    # Sparse search needs the BM25 index (normally built at app startup).
    pipeline = get_retrieval_pipeline()
    await pipeline.rebuild_bm25_index()
    index = {"collection": settings.qdrant_collection, "points": await get_vector_store().count()}

    # Golden set format: [{id, question, expected_answer, expected_sources, …}].
    golden = json.loads(Path(args.golden_set).read_text())
    # Narrow the run to the requested ids (plan item 14) before anything else:
    # a bad id must stop the run before any model call, and the warm-up loop
    # below must draw from the subset — not the first entries of the full set.
    try:
        golden, subset_ids = select_golden(golden, args.ids, args.ids_file)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if subset_ids is not None:
        print(f"Running subset: {len(subset_ids)} id(s): {', '.join(subset_ids)}")
    print(f"Loaded {len(golden)} golden Q&A pairs from {_public_path(args.golden_set)}  path={args.path}\n")

    ctx: dict = {"path": args.path, "pipeline": pipeline, "agent": get_rag_agent(),
                 "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")}
    tmp_sessions: Path | None = None
    if args.path == "chat":
        # The chat path needs a session store; use a throw-away directory so
        # evaluation sessions never land in the app's memory store.
        from ragline.chat.chat_agent import ChatAgent
        from ragline.chat.memory_store import MemoryStore

        tmp_sessions = Path(tempfile.mkdtemp(prefix="ragline-eval-sessions-"))
        ctx["store"] = MemoryStore(sessions_dir=tmp_sessions)
        ctx["chat_agent"] = ChatAgent(rag_agent=ctx["agent"], llm=get_llm(), memory_store=ctx["store"])

    exit_code = 0
    try:
        # Warm-up: the first K questions, asked and discarded, so cold caches
        # (model, embedder, reranker, BM25) do not land in repeat 1's timings.
        if args.warmup > 0:
            print(f"--- warm-up: {args.warmup} question(s), not scored ---")
            for pair in golden[: args.warmup]:
                try:
                    await _ask(ctx, pair, f"warmup-{pair.get('id')}")
                except Exception as exc:  # noqa: BLE001 — a warm-up failure is reported, not fatal
                    print(redact_text(f"        warm-up error: {exc}"))
            print()

        for repeat in range(1, args.repeats + 1):
            if args.repeats > 1:
                print(f"=== repeat {repeat}/{args.repeats} ===")
            run_meta = _run_metadata(args, repeat, index, subset_ids=subset_ids)
            results = await run_pass(golden, ctx, repeat)
            summary = summarise(results)
            print_scorecard(summary)

            out = output_path(args, repeat)
            if out:
                out.parent.mkdir(parents=True, exist_ok=True)
                # Transcript text (if captured) leaves the results file for its sidecar.
                sidecar = out.with_name(out.stem + ".transcripts.jsonl.gz")
                written = write_transcripts(sidecar, results)
                public = [{k: v for k, v in r.items() if k != "_transcript"} for r in results]
                out.write_text(json.dumps(redact_value({
                    "run": run_meta,
                    **summary,
                    "per_question": public,
                }), indent=2))
                print(f"\nFull results written to {_public_path(str(out))}")
                if written:
                    print(f"Transcripts ({written} questions) written to {_public_path(str(sidecar))}")

            # Thinking text in an answer invalidates the whole condition.
            if summary["think_residue"]:
                print(f"\nFAILED: {summary['think_residue']} answer(s) contain raw <think> text — "
                      "start vLLM with the model's reasoning parser")
                exit_code = 2
            # Threshold gate for CI-style use (never overrides a residue failure).
            elif args.threshold > 0 and summary["hit_rate"] < args.threshold and exit_code == 0:
                print(f"\nFAILED: hit-rate {summary['hit_rate']:.2f} < threshold {args.threshold:.2f}")
                exit_code = 1
            print()
    finally:
        if tmp_sessions is not None:
            shutil.rmtree(tmp_sessions, ignore_errors=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
