"""scripts/evaluate.py v2 — the pure helpers behind the harness.

Loads the script as a module (as test_evaluate_host_mask.py does) and checks
the pieces that need no stack: the retrieval metrics on a synthetic candidate
list, merging candidates across several retrieve() calls, the declined and
think-residue detectors, history seeding for the chat path, output-path
layout, the manifest-extra parser and the pass summary. No pipeline, no
endpoints, no files from eval/results.
"""

import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluate.py"
spec = importlib.util.spec_from_file_location("evaluate_v2_script", SCRIPT)
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


# --- detectors --------------------------------------------------------------


@pytest.mark.parametrize(
    "answer, citations, expected",
    [
        ("I couldn't find any relevant information in the document library.", 0, True),
        ("The documents do not state a SIL rating for this model.", 0, True),
        ("The documents do not state PoE support [1].", 1, False),   # cited negative: judge decides
        ("The DOP-107WV draws a maximum of 8.4 W [1].", 1, False),
        ("", 0, False),
    ],
)
def test_is_declined(answer, citations, expected):
    """Declined = refusal wording AND nothing cited."""
    assert ev.is_declined(answer, citations) is expected


def test_think_residue():
    """Raw thinking markup is caught in either case; clean text is not."""
    assert ev.has_think_residue("<think>let me see</think> 8.4 W") is True
    assert ev.has_think_residue("8.4 W </THINK>") is True
    assert ev.has_think_residue("8.4 W, I think.") is False


def test_source_hit_rules():
    """'any' needs one listed source; 'all' needs every one; nothing expected = None."""
    assert ev.source_hit({"a.pdf", "b.pdf"}, {"a.pdf"}, "any") is True
    assert ev.source_hit({"a.pdf", "b.pdf"}, {"a.pdf"}, "all") is False
    assert ev.source_hit({"a.pdf", "b.pdf"}, {"a.pdf", "b.pdf", "c.pdf"}, "all") is True
    assert ev.source_hit(set(), {"a.pdf"}, "any") is None


# --- candidates and metrics -------------------------------------------------


def _hit(source: str, page: int, chunk_id: str = "", score: float = 0.5) -> SimpleNamespace:
    """A stand-in SearchResult: .chunk with the fields serialize_candidates reads."""
    chunk = SimpleNamespace(source_file=f"hmi/x/{source}", page_start=page, page_end=page,
                            chunk_id=chunk_id or f"{source}:{page}")
    return SimpleNamespace(chunk=chunk, score=score)


def test_serialize_candidates_limits_and_flattens():
    """Only the first `limit` results, as flat dicts with the basename."""
    out = ev.serialize_candidates([_hit("A.PDF", 3), _hit("b.pdf", 7), _hit("c.pdf", 1)], 2)
    assert [o["source"] for o in out] == ["a.pdf", "b.pdf"]
    assert out[0] == {"source": "a.pdf", "page_start": 3, "page_end": 3, "chunk_id": "A.PDF:3", "score": 0.5}


def test_union_by_best_rank():
    """A chunk seen in two calls keeps its best rank; order is by that rank."""
    call1 = ev.serialize_candidates([_hit("a.pdf", 1), _hit("b.pdf", 2)], 20)
    call2 = ev.serialize_candidates([_hit("b.pdf", 2), _hit("c.pdf", 3)], 20)
    merged = ev.union_by_best_rank([call1, call2])
    assert [m["source"] for m in merged] == ["a.pdf", "b.pdf", "c.pdf"]
    assert ev.union_by_best_rank([call1]) == call1
    assert ev.union_by_best_rank([]) == []


def test_retrieval_metrics_by_hand():
    """recall, MRR, nDCG@8 and page hit on a small list, checked by hand."""
    expected_sources = ["hmi/x/a.pdf", "hmi/x/b.pdf"]
    expected_pages = {"hmi/x/a.pdf": [5], "hmi/x/b.pdf": [9]}
    # Reranked: an irrelevant chunk, then a.pdf on the right page, then b.pdf on a wrong page.
    reranked = ev.serialize_candidates([_hit("z.pdf", 1), _hit("a.pdf", 5), _hit("b.pdf", 2)], 8)
    # Merged (before rerank) also carried b.pdf somewhere in the top 20.
    merged = reranked + ev.serialize_candidates([_hit("b.pdf", 9)], 20)
    m = ev.retrieval_metrics(merged, reranked, expected_sources, expected_pages, ["hmi/x/z.pdf"])
    assert m["recall_at_20"] == 1.0 and m["recall_at_8"] == 1.0
    assert m["mrr"] == 0.5                                    # first relevant at rank 2
    # DCG = 0/log2(2) + 2/log2(3) + 1/log2(4); IDCG = 2/log2(2) + 2/log2(3)
    dcg = 2 / math.log2(3) + 1 / math.log2(4)
    idcg = 2 / math.log2(2) + 2 / math.log2(3)
    assert m["ndcg_at_8"] == round(dcg / idcg, 4)
    assert m["page_hit"] is True
    assert m["distractor_retrieved"] is True


def test_ndcg_is_document_level_and_bounded():
    """Several chunks of one expected document do not add up: nDCG <= 1."""
    expected = ["hmi/x/a.pdf"]
    pages = {"hmi/x/a.pdf": [5]}
    # Three page-hitting chunks of the same document in the top-8: a perfect result, not 2.1.
    reranked = ev.serialize_candidates([_hit("a.pdf", 5, "c1"), _hit("a.pdf", 5, "c2"), _hit("a.pdf", 5, "c3")], 8)
    m = ev.retrieval_metrics(reranked, reranked, expected, pages, None)
    assert m["ndcg_at_8"] == 1.0
    # First chunk on a wrong page, a later one on the right page: the document is
    # credited at rank 1 with the best relevance (2), still a perfect list.
    reranked = ev.serialize_candidates([_hit("a.pdf", 2, "c1"), _hit("a.pdf", 5, "c2")], 8)
    assert ev.retrieval_metrics(reranked, reranked, expected, pages, None)["ndcg_at_8"] == 1.0
    # Two expected documents, only one found at rank 1: DCG 2/log2(2) over IDCG 2/log2(2)+2/log2(3).
    expected2 = ["hmi/x/a.pdf", "hmi/x/b.pdf"]
    pages2 = {"hmi/x/a.pdf": [5], "hmi/x/b.pdf": [9]}
    reranked = ev.serialize_candidates([_hit("a.pdf", 5, "c1"), _hit("a.pdf", 5, "c2")], 8)
    m = ev.retrieval_metrics(reranked, reranked, expected2, pages2, None)
    assert m["ndcg_at_8"] == round(2 / (2 + 2 / math.log2(3)), 4) and m["ndcg_at_8"] < 1.0


def test_retrieval_metrics_misses_and_none():
    """Nothing relevant scores 0; nothing expected scores None throughout."""
    reranked = ev.serialize_candidates([_hit("z.pdf", 1)], 8)
    m = ev.retrieval_metrics(reranked, reranked, ["hmi/x/a.pdf"], None, None)
    assert m == {"recall_at_20": 0.0, "recall_at_8": 0.0, "mrr": 0.0, "ndcg_at_8": 0.0,
                 "page_hit": None, "distractor_retrieved": None}
    assert all(v is None for v in ev.retrieval_metrics(reranked, reranked, [], None, None).values())


# --- chat-path seeding -------------------------------------------------------


def test_seed_history_builds_turns():
    """Golden history turns become TurnRecords in a fresh SessionMemory."""
    memory = ev.seed_history("eval-1-F04", [{"user": "How much does the DA50A weigh?", "assistant": "13 oz."}])
    assert memory.session_id == "eval-1-F04"
    assert memory.turn_count == 1
    turn = memory.turns[0]
    assert turn.user_query == "How much does the DA50A weigh?"
    assert turn.answer == "13 oz." and turn.sources == [] and turn.model_used == "golden-history"
    assert ev.seed_history("eval-1-A01", []).turn_count == 0


# --- paths, manifest extras, thinking ---------------------------------------


def _args(**kw):
    base = dict(output=None, repeats=1, campaign=None, rung=None, condition=None, output_dir=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_output_path_layouts():
    """Plain, repeated and campaign layouts."""
    assert ev.output_path(_args(), 1) is None
    assert ev.output_path(_args(output="eval/results/x.json"), 1) == Path("eval/results/x.json")
    assert ev.output_path(_args(output="eval/results/x.json", repeats=3), 2) == Path("eval/results/x_r2.json")
    assert ev.output_path(_args(campaign="c", rung="r2", condition="on", repeats=3), 3) == \
        Path("eval/results/c/r2/on/r3.json")
    assert ev.output_path(_args(campaign="c", rung="r2", condition="on", output_dir="/tmp/o"), 1) == \
        Path("/tmp/o/c/r2/on/r1.json")


def test_manifest_extra(tmp_path):
    """Inline JSON, @file, and rejection of non-objects."""
    assert ev.parse_manifest_extra(None) == {}
    assert ev.parse_manifest_extra('{"gpu": "RTX PRO 6000"}') == {"gpu": "RTX PRO 6000"}
    f = tmp_path / "extra.json"
    f.write_text(json.dumps({"rate_usd_per_hr": 2.09}))
    assert ev.parse_manifest_extra(f"@{f}") == {"rate_usd_per_hr": 2.09}
    with pytest.raises(ValueError):
        ev.parse_manifest_extra("[1, 2]")


def test_infer_thinking():
    """The thinking mode recorded follows the enable_thinking flag."""
    assert ev.infer_thinking({"chat_template_kwargs": {"enable_thinking": True}}) == "on"
    assert ev.infer_thinking({"chat_template_kwargs": {"enable_thinking": False}}) == "off"
    assert ev.infer_thinking({}) == "unset"


# --- subset selection (--ids / --ids-file) -----------------------------------


def _golden() -> list[dict]:
    """A small, in-order golden set with mixed ids — including one entry
    without an id, which the subset helper must ignore for matching but keep
    unaffected by selection."""
    return [
        {"id": "A01", "question": "Q A01"},
        {"id": "A02", "question": "Q A02"},
        {"question": "Q no-id"},                              # entries without ids are untouched
        {"id": "D05", "question": "Q D05"},
        {"id": "F12", "question": "Q F12"},
    ]


def test_parse_ids_combines_sources(tmp_path):
    """Comma-separated --ids and a file with comments merge in the given order."""
    f = tmp_path / "ids.txt"
    f.write_text("# header comment\nA02\n\nD05  # inline comment\n")
    assert ev.parse_ids("F12, A01 ,", str(f)) == ["F12", "A01", "A02", "D05"]
    # Nothing passed = no subset (None signals "run everything").
    assert ev.parse_ids(None, None) is None


def test_select_golden_in_golden_set_order():
    """The subset is returned in the golden file's order, deduped, with the ids."""
    subset, ids = ev.select_golden(_golden(), "D05,A01,A01", None)
    # Golden-set order (A01 appears before D05) and no duplicates.
    assert [p["id"] for p in subset] == ["A01", "D05"]
    assert ids == ["A01", "D05"]


def test_select_golden_full_set_when_nothing_requested():
    """`select_golden(..., None, None)` returns the full list and None for the ids."""
    golden = _golden()
    subset, ids = ev.select_golden(golden, None, None)
    # Identical object (no filtering happened at all).
    assert subset is golden and ids is None


def test_select_golden_rejects_unknown_ids():
    """Unknown ids raise ValueError that lists them, so the user can spot the typo."""
    with pytest.raises(ValueError, match=r"unknown golden ids:.*ZZZ"):
        ev.select_golden(_golden(), "ZZZ,A01", None)


def test_run_metadata_records_subset_ids(tmp_path):
    """`subset_ids` lands in the manifest; `golden_sha256` stays the full file's digest."""
    # Minimal golden file — the manifest reads its bytes for the digest.
    gf = tmp_path / "golden.json"
    gf.write_text(json.dumps(_golden()))
    args = SimpleNamespace(
        label="t", path="rag", thinking=None, repeats=1, warmup=0, seed=0,
        campaign=None, rung=None, condition=None, output_dir=None,
        golden_set=str(gf), manifest_extra=None,
    )
    # Monkeypatch the two helpers that would reach into live settings/subprocess
    # by calling _run_metadata through its public contract. We stub settings
    # by replacing the module-level `settings` import indirectly: just call it
    # and accept whatever the local .env gives us; only the fields we assert on
    # need to be deterministic (subset_ids and golden_sha256).
    meta = ev._run_metadata(args, repeat=1, index={"collection": "c", "points": 1},
                            subset_ids=["A01", "D05"])
    assert meta["subset_ids"] == ["A01", "D05"]
    # Full-file digest, not a subset digest.
    import hashlib as _hashlib
    assert meta["golden_sha256"] == _hashlib.sha256(gf.read_bytes()).hexdigest()[:12]
    # And the default (no subset) records None.
    meta_full = ev._run_metadata(args, repeat=1, index={"collection": "c", "points": 1})
    assert meta_full["subset_ids"] is None


# --- summary -----------------------------------------------------------------


def _record(**kw) -> dict:
    base = {
        "source_hit": True, "cited": True, "pages_ok": True, "declined": False, "think_residue": False,
        "tokens": 100, "reasoning_chars": 0, "latency_s": 2.0, "step_ms": {"answer": 1000.0},
        "retrieval": {"recall_at_20": 1.0, "recall_at_8": 1.0, "mrr": 1.0, "ndcg_at_8": 1.0,
                      "page_hit": True, "distractor_retrieved": False},
        "distractor_cited": None,
    }
    base.update(kw)
    return base


def test_summarise_counts_and_means():
    """Hit rate over scored questions, flags counted, retrieval means ignore None."""
    results = [
        _record(),
        _record(source_hit=False, declined=True, cited=False, tokens=50, latency_s=4.0,
                retrieval={"recall_at_20": 0.0, "recall_at_8": 0.0, "mrr": 0.0, "ndcg_at_8": 0.0,
                           "page_hit": False, "distractor_retrieved": True}),
        _record(source_hit=None, think_residue=True, reasoning_chars=300, latency_s=3.0,
                retrieval={"recall_at_20": None, "recall_at_8": None, "mrr": None, "ndcg_at_8": None,
                           "page_hit": None, "distractor_retrieved": None}),
    ]
    s = ev.summarise(results)
    assert s["hits"] == 1 and s["scored"] == 2 and s["hit_rate"] == 0.5
    assert s["declined"] == 1 and s["think_residue"] == 1 and s["errors"] == 0
    assert s["total_tokens"] == 250 and s["total_reasoning_chars"] == 300
    assert s["retrieval_mean"]["recall_at_8"] == 0.5 and s["page_hit_rate"] == 0.5
    assert s["distractor_retrieved"] == 1
    assert s["latency_median_s"] == 3.0
    assert s["step_ms_median"] == {"answer": 1000.0}
