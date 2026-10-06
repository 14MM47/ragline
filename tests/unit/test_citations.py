"""Citation extraction tests — ported from raggles, covering every marker
form plus the hallucination guard."""

from ragline.chunking.models import Chunk
from ragline.citations.postprocessor import extract_citations


def _make_chunks(n: int) -> list[Chunk]:
    """n distinct chunks: doc{i}.pdf, page i, section i."""
    return [
        Chunk(
            text=f"Content of source {i}.",
            source_file=f"doc{i}.pdf",
            document_id=f"id-{i}",
            page_start=i,
            page_end=i,
            char_start=0,
            char_end=20,
            section_header=f"Section {i}",
            chunk_index=i - 1,
        )
        for i in range(1, n + 1)
    ]


def test_single_citation():
    chunks = _make_chunks(3)
    text = "Revenue was $1.2M [Source 1]."
    result = extract_citations(text, chunks, "test query", "gpt-4o")
    assert len(result.sources_used) == 1
    assert result.sources_used[0].citation_id == 1
    assert result.sources_used[0].source_file == "doc1.pdf"


def test_multiple_citations():
    chunks = _make_chunks(3)
    text = "Claim A [Source 1]. Claim B [Source 2]. Claim C [Source 3]."
    result = extract_citations(text, chunks, "test", "gpt-4o")
    assert len(result.sources_used) == 3


def test_comma_separated():
    """[Source 1, 3] expands to two separate citations."""
    chunks = _make_chunks(3)
    text = "Both sources agree [Source 1, 3]."
    result = extract_citations(text, chunks, "test", "gpt-4o")
    assert len(result.sources_used) == 2
    ids = {s.citation_id for s in result.sources_used}
    assert ids == {1, 3}


def test_range_notation():
    """[Sources 1-3] expands the range."""
    chunks = _make_chunks(5)
    text = "All sources confirm [Sources 1-3]."
    result = extract_citations(text, chunks, "test", "gpt-4o")
    assert len(result.sources_used) == 3
    ids = {s.citation_id for s in result.sources_used}
    assert ids == {1, 2, 3}


def test_hallucinated_source():
    """THE guard: a source number not in the prompt is dropped entirely."""
    chunks = _make_chunks(2)
    text = "Claim [Source 5]."
    result = extract_citations(text, chunks, "test", "gpt-4o")
    # Source 5 doesn't exist, should be filtered out.
    assert len(result.sources_used) == 0


def test_no_citations():
    """Marker-free answers become one uncited span."""
    chunks = _make_chunks(2)
    text = "This response has no citations."
    result = extract_citations(text, chunks, "test", "gpt-4o")
    assert len(result.sources_used) == 0
    assert len(result.spans) == 1
    assert result.spans[0].text == text


def test_citation_metadata():
    """Citation fields come verbatim from the chunk, never the LLM."""
    chunks = _make_chunks(1)
    text = "Fact [Source 1]."
    result = extract_citations(text, chunks, "my query", "gpt-4o")
    assert result.query == "my query"
    assert result.model_used == "gpt-4o"
    source = result.sources_used[0]
    assert source.page_number == 1
    assert source.section == "Section 1"
    assert source.document_id == "id-1"


def test_dedup_same_document_and_page():
    """Two chunks from the SAME document + page collapse into one citation."""
    chunks = _make_chunks(2)
    # Make chunk 2 share chunk 1's document and page.
    chunks[1].document_id = "id-1"
    chunks[1].source_file = "doc1.pdf"
    chunks[1].page_start = 1
    chunks[1].page_end = 1
    text = "Claim A [Source 1]. Claim B [Source 2]."
    result = extract_citations(text, chunks, "test", "gpt-4o")
    assert len(result.sources_used) == 1
    # Both spans reference the single deduplicated citation id.
    cited_ids = [ids for s in result.spans for ids in s.citation_ids]
    assert set(cited_ids) == {1}


def test_no_dedup_across_documents_sharing_basename():
    """Two DIFFERENT documents sharing a basename+page must NOT collapse —
    otherwise content is mis-attributed to the wrong document."""
    chunks = _make_chunks(2)
    # Same basename + page, but genuinely different documents (distinct ids).
    chunks[1].source_file = "doc1.pdf"
    chunks[1].page_start = 1
    chunks[1].page_end = 1
    assert chunks[0].document_id != chunks[1].document_id
    text = "Claim A [Source 1]. Claim B [Source 2]."
    result = extract_citations(text, chunks, "test", "gpt-4o")
    assert len(result.sources_used) == 2
    assert {s.document_id for s in result.sources_used} == {"id-1", "id-2"}


def test_malformed_markers_do_not_crash():
    """Dangling/empty range bounds and absurd ranges degrade gracefully
    instead of raising (which would 500 the whole chat turn)."""
    chunks = _make_chunks(3)
    for text in (
        "Claim [Source 2-].",
        "Claim [Source -1].",
        "Claim [Sources 1-9999999].",
    ):
        result = extract_citations(text, chunks, "test", "gpt-4o")
        # No exception; the malformed marker yields no valid citation.
        assert result.sources_used == []
