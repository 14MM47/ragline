"""Confidence-pass prompt must see recent exchanges, including memory-off turns.

Regression: a memory-off turn changed the subject (ASEM 6300 PDF -> .mer
integrity-check log). The next memory-on "tell me more" correctly followed the
log file, but the scorer only saw summary/topics/key_facts — refreshed by the
post-pass, which memory-off turns skip — so it still thought the topic was
ASEM 6300 and scored the correct answer 0.0.
"""

from ragline.chat.models import KeyFact, SessionMemory, TurnRecord
from ragline.chat.prompts import CONFIDENCE_SYSTEM, build_confidence_user


def _turn(n: int, q: str, a: str, memory_enabled: bool) -> TurnRecord:
    return TurnRecord(
        turn_number=n,
        user_query=q,
        rewritten_query=q,
        answer=a,
        spans=[],
        sources=[],
        model_used="ragline-llm",
        memory_enabled=memory_enabled,
        timestamp="2026-09-22T16:00:00+00:00",
    )


def _session_after_memory_off_topic_change() -> SessionMemory:
    """State just before turn 4: summary is stale (turn 3 skipped the post-pass)."""
    return SessionMemory(
        session_id="s1",
        created_at="2026-09-22T16:00:00+00:00",
        summary="The user asked for details from one file; the assistant summarised the "
        "ASEM 6300 monitors/PCs/thin clients technical data document.",
        topics=["available files", "asem-6300 documentation"],
        key_facts=[
            KeyFact(fact="The ASEM 6300 technical data document is 64 pages long.",
                    source="asem_6300_monitors_pcs_thin_clients_technical_data.pdf", turn=2),
        ],
        turns=[
            _turn(1, "tell me about the files currently available",
                  "Here is a complete list of all available files...", True),
            _turn(2, "give me some details contained in one of these files",
                  "The document asem_6300_monitors_pcs_thin_clients_technical_data.pdf ...", True),
            _turn(3, "give me some details contained in one of these files",
                  "One of the files is the log file generated during the integrity check "
                  "of .mer application and runtime files...", False),
        ],
    )


def test_confidence_prompt_includes_memory_off_turn_as_most_recent():
    memory = _session_after_memory_off_topic_change()
    prompt = build_confidence_user(
        memory,
        "tell me more",
        "The log file generated during the integrity check of .mer application ...",
        rewritten_query="tell me more about the log file generated during the integrity check",
    )
    assert "Recent exchanges" in prompt
    # The memory-off turn is present, and it is the LAST exchange shown.
    assert "integrity check of .mer application" in prompt.split("User's ORIGINAL query")[0]
    recent = prompt.split("Recent exchanges")[1].split("User's ORIGINAL query")[0]
    assert recent.rstrip().endswith("runtime files...")
    assert recent.index("asem_6300") < recent.index(".mer application")


def test_confidence_prompt_recent_exchanges_capped_at_five_turns():
    memory = _session_after_memory_off_topic_change()
    memory.turns = [_turn(i, f"question {i}", f"answer {i}", True) for i in range(1, 9)]
    prompt = build_confidence_user(memory, "q", "a")
    assert "question 4" in prompt and "question 8" in prompt
    assert "question 3" not in prompt


def test_confidence_prompt_first_turn_has_no_recent_block():
    memory = SessionMemory(session_id="s0", created_at="2026-09-22T16:00:00+00:00")
    prompt = build_confidence_user(memory, "q", "a")
    assert "Recent exchanges" not in prompt


def test_confidence_system_says_recent_exchanges_beat_a_stale_summary():
    assert "MOST RECENT exchange" in CONFIDENCE_SYSTEM
    assert "recent exchanges win" in CONFIDENCE_SYSTEM
