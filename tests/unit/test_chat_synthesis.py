"""Compound-mode merge test — cited RAG spans must survive synthesis untouched.

Adapted from raggles (ragline's _synthesize is a staticmethod and no longer
async — it's deliberately mechanical, no LLM involved).
"""

from ragline.chat.chat_agent import ChatAgent


def test_compound_merge_preserves_cited_rag_spans():
    rag_result = {
        "answer": "Fact A [Source 1]. Fact B [Source 2].",
        "spans": [
            {"text": "Fact A ", "citation_ids": [1]},
            {"text": ". Fact B ", "citation_ids": [2]},
            {"text": ".", "citation_ids": []},
        ],
        "sources": [
            {
                "citation_id": 1,
                "source_file": "doc1.pdf",
                "page_number": 3,
                "section": None,
                "quoted_text": "Fact A",
                "document_id": "d1",
            },
            {
                "citation_id": 2,
                "source_file": "doc2.pdf",
                "page_number": 7,
                "section": None,
                "quoted_text": "Fact B",
                "document_id": "d2",
            },
        ],
        "query": "compare facts",
        "model_used": "gpt-4o",
    }
    library_result = {"answer": "The library contains two relevant manuals."}

    merged = ChatAgent._synthesize("compare facts", rag_result, library_result)

    # Sources pass through untouched — no citation/page drift.
    assert merged["sources"] == rag_result["sources"]
    # The library overview leads as an uncited span.
    assert merged["spans"][0]["citation_ids"] == []
    assert "library contains two relevant manuals" in merged["spans"][0]["text"].lower()
    # Every cited RAG span follows verbatim.
    assert merged["spans"][1:] == rag_result["spans"]


def test_merge_without_library_answer_returns_rag_untouched():
    rag_result = {"answer": "A [Source 1].", "spans": [], "sources": [], "query": "q", "model_used": "m"}
    merged = ChatAgent._synthesize("q", rag_result, {"answer": "  "})
    assert merged is rag_result
