"""Answer length: output ceilings and the deterministic library file list.

On a ~30 tok/s local model an unbounded answer is minutes of waiting, so both
answer calls carry an output ceiling and the prompts ask for short answers.
The library file list is never typed out by the model: it writes a placeholder
and ChatAgent swaps in a list rendered from the metadata DB.
"""

import asyncio
from types import SimpleNamespace

from ragline.agent.prompts import SYSTEM_PROMPT
from ragline.chat import chat_agent as chat_agent_module
from ragline.chat.chat_agent import ChatAgent, _complete_cut_off_marker, _splice_file_list
from ragline.chat.prompts import FILE_LIST_PLACEHOLDER, LIBRARY_USER_TEMPLATE
from ragline.config import settings
from ragline.llm import openai_provider
from ragline.llm.openai_provider import OpenAIProvider
from ragline.storage.metadata_db import render_library_listing, render_library_summary


class _RecordingLLM:
    """Stands in for BaseLLM, capturing each complete() call."""

    def __init__(self, answer: str):
        self.answer = answer
        self.calls: list[dict] = []

    async def complete(self, messages, temperature=0.0, max_tokens=None):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})
        return self.answer


def _doc(source_path: str, pages: int = 10, chunks: int = 20):
    return SimpleNamespace(source_path=source_path, filename=f"batch/{source_path}",
                           page_count=pages, chunk_count=chunks)


def _library_agent(monkeypatch, answer: str):
    """A ChatAgent with only what _library_query touches, plus a listing call log."""
    agent = ChatAgent.__new__(ChatAgent)
    agent._llm = _RecordingLLM(answer)
    listing_calls: list[int] = []

    async def fake_summary():
        return "Library totals: 2 documents"

    async def fake_listing():
        listing_calls.append(1)
        return "- `a.pdf` (1 pages)\n- `b.pdf` (2 pages)"

    monkeypatch.setattr(chat_agent_module, "get_library_summary", fake_summary)
    monkeypatch.setattr(chat_agent_module, "get_library_listing", fake_listing)
    return agent, listing_calls


def test_library_query_substitutes_placeholder(monkeypatch):
    """The model's marker is replaced by the DB-rendered list."""
    agent, listing_calls = _library_agent(
        monkeypatch, f"Here are the files:\n\n{FILE_LIST_PLACEHOLDER}\n\nAsk about any of them."
    )

    result = asyncio.run(agent._library_query("list files"))

    assert FILE_LIST_PLACEHOLDER not in result["answer"]
    assert "- `a.pdf` (1 pages)\n- `b.pdf` (2 pages)" in result["answer"]
    assert result["answer"].startswith("Here are the files:")
    assert result["answer"].endswith("Ask about any of them.")
    assert listing_calls == [1]


def test_library_query_repeated_placeholder_inserts_list_once(monkeypatch):
    agent, _ = _library_agent(
        monkeypatch, f"{FILE_LIST_PLACEHOLDER}\nAgain: {FILE_LIST_PLACEHOLDER}"
    )

    result = asyncio.run(agent._library_query("list files"))

    assert result["answer"].count("`a.pdf`") == 1
    assert FILE_LIST_PLACEHOLDER not in result["answer"]


def test_library_query_without_placeholder_is_untouched(monkeypatch):
    """A topic/count answer has no marker: no DB listing, answer unchanged."""
    agent, listing_calls = _library_agent(monkeypatch, "There are 2 documents.")

    result = asyncio.run(agent._library_query("how many documents?"))

    assert result["answer"] == "There are 2 documents."
    assert listing_calls == []


def test_library_query_passes_ceiling_and_placeholder_instruction(monkeypatch):
    agent, _ = _library_agent(monkeypatch, "ok")

    asyncio.run(agent._library_query("list files"))

    call = agent._llm.calls[0]
    assert call["max_tokens"] == settings.library_answer_max_tokens
    # The prompt must tell the model which marker to write.
    assert FILE_LIST_PLACEHOLDER in call["messages"][1]["content"]


def test_library_template_has_no_stray_format_fields():
    """The template formats with exactly the three fields ChatAgent supplies."""
    text = LIBRARY_USER_TEMPLATE.format(
        query="q", library_summary="s", file_list_placeholder=FILE_LIST_PLACEHOLDER
    )
    assert "{" not in text


def test_ceilings_are_sane():
    # A RAG ceiling that truncates a normal answer would cut off citations.
    assert settings.answer_max_tokens >= 1000
    assert 0 < settings.library_answer_max_tokens <= settings.answer_max_tokens


def test_answer_prompt_asks_for_requested_length():
    assert "give exactly that many" in SYSTEM_PROMPT
    assert "Be concise but thorough" not in SYSTEM_PROMPT


def test_render_library_listing_groups_and_sorts():
    docs = [
        _doc("hmi/beckhoff/cp39xx.pdf", pages=40),
        _doc("hmi/beckhoff/cp37xx.pdf", pages=1200),
        _doc("loose.pdf", pages=3),
    ]

    listing = render_library_listing(docs)

    assert listing.splitlines()[0] == "**Library totals:** 3 documents, 1,243 pages"
    assert "### beckhoff (2 docs)" in listing
    assert "### uncategorised (1 docs)" in listing
    # Sorted within the category; no chunk counts in the user-facing list.
    assert listing.index("cp37xx.pdf") < listing.index("cp39xx.pdf")
    assert "- `hmi/beckhoff/cp37xx.pdf` (1200 pages)" in listing
    assert "chunks" not in listing


def test_render_library_listing_empty():
    assert "empty" in render_library_listing([])


def test_render_library_summary_unchanged_shape():
    """The LLM-facing summary keeps its totals line and per-file chunk counts."""
    summary = render_library_summary([_doc("vfd/abb/acs880.pdf", pages=5, chunks=9)])

    assert summary.startswith("Library totals: 1 documents, 5 pages, 9 chunks")
    assert "Category 'abb' — 1 docs, 5 pages, 9 chunks:" in summary
    assert "  - vfd/abb/acs880.pdf (5 pages, 9 chunks)" in summary


def test_library_query_cut_off_marker_still_gets_the_list(monkeypatch):
    """The ceiling can cut the marker mid-way; the user must still get the list."""
    agent, listing_calls = _library_agent(monkeypatch, "Here are the files:\n\n[[FILE_")

    result = asyncio.run(agent._library_query("list files"))

    assert "[[" not in result["answer"]
    assert result["answer"].endswith("- `b.pdf` (2 pages)")
    assert listing_calls == [1]


def test_complete_cut_off_marker_only_touches_a_trailing_fragment():
    assert _complete_cut_off_marker("files: [[") == "files: " + FILE_LIST_PLACEHOLDER
    assert _complete_cut_off_marker("files: [[FILE_LIST]") == "files: " + FILE_LIST_PLACEHOLDER
    # A single bracket, a complete marker, or a fragment mid-text is left alone.
    assert _complete_cut_off_marker("see item [") == "see item ["
    assert _complete_cut_off_marker(f"a {FILE_LIST_PLACEHOLDER}") == f"a {FILE_LIST_PLACEHOLDER}"
    assert _complete_cut_off_marker("[[FILE_ then more") == "[[FILE_ then more"


def test_splice_puts_a_mid_line_marker_on_its_own_block():
    out = _splice_file_list(f"Files: {FILE_LIST_PLACEHOLDER} Enjoy.", "- `a.pdf`")

    assert out == "Files:\n\n- `a.pdf`\n\nEnjoy."


def test_splice_keeps_an_own_line_marker_unchanged():
    out = _splice_file_list(f"Files:\n\n{FILE_LIST_PLACEHOLDER}\n\nEnjoy.", "- `a.pdf`")

    assert out == "Files:\n\n- `a.pdf`\n\nEnjoy."
    assert _splice_file_list(FILE_LIST_PLACEHOLDER, "- `a.pdf`") == "- `a.pdf`"


def _provider_returning(monkeypatch, finish_reason):
    provider = OpenAIProvider("test-model")
    choice = SimpleNamespace(message=SimpleNamespace(content="partial"), finish_reason=finish_reason)
    response = SimpleNamespace(choices=[choice],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=5, total_tokens=6))

    async def fake_create(**kwargs):
        return response

    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)
    warnings: list[tuple] = []
    monkeypatch.setattr(openai_provider.log, "warning", lambda *a, **kw: warnings.append((a, kw)))
    return provider, warnings


def test_provider_warns_when_the_ceiling_truncates(monkeypatch):
    provider, warnings = _provider_returning(monkeypatch, "length")

    text = asyncio.run(provider.complete([{"role": "user", "content": "hi"}], max_tokens=5))

    assert text == "partial"
    assert len(warnings) == 1
    assert warnings[0][1]["max_tokens"] == 5


def test_provider_is_quiet_on_a_normal_stop(monkeypatch):
    provider, warnings = _provider_returning(monkeypatch, "stop")

    asyncio.run(provider.complete([{"role": "user", "content": "hi"}], max_tokens=5))

    assert warnings == []
