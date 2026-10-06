"""evaluate.py — run the golden question set against the live pipeline.

Self-contained (raggles' evaluation package is not ported): for every golden
question it runs the full RAG path and scores, per question:

  * source hit  — do the cited sources include the expected document(s)?
                  (matched on basename, case-insensitive; per question
                  `source_match` "any" = one listed source suffices, "all" /
                  unset = every listed source must be cited)
  * cited       — did the answer carry at least one valid citation?
  * page sanity — is every cited page within its document's page count?

plus the answer text for manual review, and token totals per question.

Usage:
    python scripts/evaluate.py eval/golden_set_hmi.json
    python scripts/evaluate.py eval/golden_set_hmi.json --output results.json
    python scripts/evaluate.py eval/golden_set_hmi.json --threshold 0.7
    python scripts/evaluate.py eval/golden_set_hmi.json -o eval/results/<date>_<label>.json --label <stack-name>

The results file records the stack it ran against (models, endpoint hosts, git
rev, golden-set digest) and per-question latency, so two runs on different
stacks can be A/B compared later.

Requires: Qdrant up, ingested corpus, configured .env. Run before and after
any change to the stack or the pipeline — see docs/evaluation.md.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ragline.logging_utils import configure_redaction, redact_text, redact_value  # noqa: E402


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


def _run_metadata(args: argparse.Namespace) -> dict:
    """What this run ran against, for later A/B comparison. Model names and
    endpoint HOSTS only — never keys."""
    from ragline.config import settings

    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=False).stdout.strip()
    except OSError:
        rev = ""
    golden_path = Path(args.golden_set)
    return {
        "label": args.label,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ragline_rev": rev,
        "golden_set": _public_path(args.golden_set),
        "golden_sha256": hashlib.sha256(golden_path.read_bytes()).hexdigest()[:12],
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
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ragline golden-set evaluation")
    parser.add_argument("golden_set", help="Path to golden Q&A pairs JSON file")
    parser.add_argument("--output", "-o", help="Write full results to a JSON file")
    parser.add_argument(
        "--threshold", "-t", type=float, default=0.0,
        help="Minimum source hit-rate to pass (exit code 1 if below)",
    )
    parser.add_argument("--label", default="", help="Free-text name for this stack/run, kept in the results")
    args = parser.parse_args()

    # Configure both logging systems before imports/client construction; the
    # reranker logs its endpoint on startup and HTTP errors include full URLs.
    from ragline.config import settings

    logging.basicConfig(level=settings.log_level.upper())
    configure_redaction()

    # Deferred imports so --help never touches the stack.
    from ragline.api.dependencies import get_rag_agent, get_retrieval_pipeline
    from ragline.storage.metadata_db import get_document, init_db
    from ragline.tracing.collector import TraceCollector

    await init_db()

    # Sparse search needs the BM25 index (normally built at app startup).
    await get_retrieval_pipeline().rebuild_bm25_index()

    # Golden set format: [{question, expected_answer, expected_sources, tags}].
    golden = json.loads(Path(args.golden_set).read_text())
    print(f"Loaded {len(golden)} golden Q&A pairs from {_public_path(args.golden_set)}\n")

    agent = get_rag_agent()
    results = []
    run_meta = _run_metadata(args)

    for i, pair in enumerate(golden, start=1):
        question = pair["question"]
        expected = {_basename(s) for s in pair.get("expected_sources", [])}
        started = time.perf_counter()

        # One flaky endpoint call must not kill a long run: contain any error
        # to this question, record it as a miss, and continue with the rest.
        try:
            # Fresh collector per question so token totals are per-question.
            trace = TraceCollector(query=question)
            cited = await agent.query(question)
            record = trace.finalize()

            cited_files = {_basename(s.source_file) for s in cited.sources_used}
            # Hit: the golden set's own rule per question — "any" (one of the
            # listed sources suffices; a spec repeated across a datasheet, a
            # manual and a catalog lists them all) or "all" (a comparison must
            # cite both sides). Unset = "all", the original strict rule.
            match = pair.get("source_match", "all")
            if not expected:
                hit = None
            elif match == "any":
                hit = bool(expected & cited_files)
            else:
                hit = expected.issubset(cited_files)

            # Page sanity: each citation's page must exist in its document.
            pages_ok = True
            for s in cited.sources_used:
                doc = await get_document(s.document_id)
                if doc and s.page_number and doc.page_count and s.page_number > doc.page_count:
                    pages_ok = False

            results.append({
                "id": pair.get("id"),
                "category": pair.get("category"),
                "question": question,
                "expected_sources": sorted(expected),
                "source_match": match,
                "cited_sources": sorted(cited_files),
                "source_hit": hit,
                "cited": bool(cited.sources_used),
                "pages_ok": pages_ok,
                "answer": cited.raw_text,
                "expected_answer": pair.get("expected_answer", ""),
                "tokens": record.prompt_tokens + record.completion_tokens,
                "prompt_tokens": record.prompt_tokens,
                "completion_tokens": record.completion_tokens,
                "latency_s": round(time.perf_counter() - started, 2),
                "step_ms": json.loads(record.step_ms),
                "tags": pair.get("tags", []),
            })

            status = "HIT " if hit else ("MISS" if hit is not None else "n/a ")
            print(redact_text(f"[{i}/{len(golden)}] {status} {question[:70]}"))
            print(redact_text(f"        cited: {sorted(cited_files) or '(none)'}  tokens: {results[-1]['tokens']}"))
        except Exception as exc:  # noqa: BLE001 — deliberate catch-all per question
            # Scored as a miss (False) when sources were expected, so the
            # hit-rate denominator stays honest; None keeps unscored questions
            # out of the rate exactly as in the success path.
            results.append({
                "id": pair.get("id"),
                "category": pair.get("category"),
                "question": question,
                "expected_sources": sorted(expected),
                "cited_sources": [],
                "source_hit": False if expected else None,
                "cited": False,
                "pages_ok": True,
                "answer": "",
                "expected_answer": pair.get("expected_answer", ""),
                "tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_s": round(time.perf_counter() - started, 2),
                "tags": pair.get("tags", []),
                "error": redact_text(str(exc)),
            })
            print(redact_text(f"[{i}/{len(golden)}] ERR  {question[:70]}"))
            print(f"        error: {results[-1]['error']}")

    # --- scorecard ----------------------------------------------------------
    scored = [r for r in results if r["source_hit"] is not None]
    hits = sum(1 for r in scored if r["source_hit"])
    hit_rate = hits / len(scored) if scored else 0.0
    cited_rate = sum(1 for r in results if r["cited"]) / len(results) if results else 0.0
    pages_ok_all = all(r["pages_ok"] for r in results)
    total_tokens = sum(r["tokens"] for r in results)

    print("\n=== Scorecard ===")
    print(f"source hit-rate : {hits}/{len(scored)} = {hit_rate:.2f}")
    print(f"cited answers   : {cited_rate:.2f}")
    print(f"page sanity     : {'ok' if pages_ok_all else 'FAILURES (see results)'}")
    print(f"total tokens    : {total_tokens}")

    # Where the time went: median per stage across the answered questions.
    step_names: list[str] = []
    for r in results:
        step_names += [name for name in r.get("step_ms", {}) if name not in step_names]
    step_medians = {
        name: round(statistics.median(r["step_ms"].get(name, 0.0) for r in results if "step_ms" in r), 1)
        for name in step_names
    }
    if step_medians:
        print("median stage ms : " + ", ".join(f"{name} {ms:.0f}" for name, ms in step_medians.items()))

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(redact_value({
            "run": run_meta,
            "hit_rate": hit_rate,
            "cited_rate": cited_rate,
            "pages_ok": pages_ok_all,
            "total_tokens": total_tokens,
            "step_ms_median": step_medians,
            "per_question": results,
        }), indent=2))
        print(f"\nFull results written to {_public_path(args.output)}")

    # Threshold gate for CI-style use.
    if args.threshold > 0 and hit_rate < args.threshold:
        print(f"\nFAILED: hit-rate {hit_rate:.2f} < threshold {args.threshold:.2f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
