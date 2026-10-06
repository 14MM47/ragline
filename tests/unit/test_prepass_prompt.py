"""Structured pre-pass prompt — rewriting rules and worked examples.

The rewrite feeds BOTH the embedder and the reranker, so a bad rewrite costs
retrieval quality. Seen live (2026-09-23): "more about hmis" became "more
information about HMIS in the context of the document collection" — filler,
a meta phrase, and a different acronym (HMIS != HMI). The LLM itself can't be
tested offline, so these tests pin the prompt text: the rules that forbid those
failures are present, and every worked example is valid pre-pass JSON that
obeys the rules it teaches.
"""

import json

from ragline.chat.prepass_schema import PrePassResult
from ragline.chat.prompts import STRUCTURED_PRE_PASS_SYSTEM, build_structured_pre_pass_user


def _examples() -> list[dict]:
    """Every worked-example JSON object in the system prompt (one per line)."""
    # Example JSON sits on its own lines starting with "{" (the prompt's trailing
    # backslashes join each example onto a single line).
    return [json.loads(line) for line in STRUCTURED_PRE_PASS_SYSTEM.splitlines() if line.startswith("{")]


def test_rules_forbid_the_observed_failures():
    """The rules that target filler, meta phrases and acronym drift are present."""
    p = STRUCTURED_PRE_PASS_SYSTEM
    # Filler words named as things to drop.
    assert "more information about" in p and "SEARCH QUERY" in p
    # Meta phrases about the collection banned from retrieval rewrites.
    assert 'never mention the documents, the collection' in p
    # Acronym plurals + no acronym swapping.
    assert '"hmis" = HMIs = HMI' in p and "Never change one acronym into a different one" in p
    # Follow-ups must fold in the conversation topic.
    assert "fold in the specific product" in p


def test_examples_are_valid_prepass_json():
    """Four examples, each a complete PrePassResult (all six fields present)."""
    examples = _examples()
    assert len(examples) == 4
    for ex in examples:
        # Every schema field spelled out, so the model sees the full shape.
        assert set(ex) == set(PrePassResult.model_fields)
        PrePassResult.model_validate(ex)


def test_examples_obey_their_own_rules():
    """Retrieval examples contain no meta phrases or filler; the HMI one keeps HMI."""
    banned = ("document", "collection", "library", "context", "more information", "please")
    for ex in _examples():
        # Only retrieval-mode rewrites are held to the no-meta rule (library is about docs).
        if ex["mode"] == "retrieval":
            q = ex["rewritten_query"].lower()
            assert not any(b in q for b in banned), ex["rewritten_query"]
    hmi = next(ex for ex in _examples() if "PanelView 800" in ex["target_document_hints"])
    # Plural acronym resolved to HMI (with expansion), never the different acronym HMIS.
    assert "HMI" in hmi["rewritten_query"] and "HMIS" not in hmi["rewritten_query"]
    # The follow-up folded in the conversation's product.
    assert "PanelView 800" in hmi["rewritten_query"]


def test_contrastive_example_uses_excluded_sources_not_the_query():
    """Exclusions go to excluded_sources; the rewrite carries no exclusion phrase."""
    ex = next(e for e in _examples() if e["has_contrastive_intent"])
    assert ex["excluded_sources"] == ["M580_datasheet.pdf"]
    assert "besides" not in ex["rewritten_query"] and "M580" not in ex["rewritten_query"]


def test_prompt_is_not_a_format_string():
    """The prompt is sent verbatim; literal JSON braces must never be .format()-ed."""
    # If someone later calls .format() on it, the example braces would raise — so
    # prove the braces are there and the constant has no {placeholder} fields.
    assert '{"mode": "retrieval"' in STRUCTURED_PRE_PASS_SYSTEM
    assert "{query}" not in STRUCTURED_PRE_PASS_SYSTEM


def test_user_builder_unchanged_for_first_turn():
    """build_structured_pre_pass_user is untouched: first-turn shape pinned."""
    from ragline.chat.models import SessionMemory

    memory = SessionMemory(session_id="s1", created_at="2026-09-23T00:00:00Z")
    out = build_structured_pre_pass_user(memory, "more about hmis")
    # Exact text: the first-turn notice, the query, then the JSON cue.
    assert out == (
        "This is the first query in the conversation (no prior context).\n"
        "New user query: more about hmis\n\nJSON analysis:"
    )
