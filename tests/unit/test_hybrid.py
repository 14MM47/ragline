"""Hybrid search tests — BM25 filtering and Reciprocal Rank Fusion."""

from ragline.chunking.models import Chunk
from ragline.retrieval.hybrid import BM25Index, reciprocal_rank_fusion
from ragline.vectorstore.base import SearchResult


def _chunk(text: str, idx: int = 0) -> Chunk:
    """Minimal chunk with distinct offsets so RRF identity keys differ."""
    return Chunk(
        text=text,
        source_file="test.pdf",
        document_id="doc-1",
        page_start=1,
        page_end=1,
        char_start=idx * 100,
        char_end=idx * 100 + len(text),
        chunk_index=idx,
    )


def test_bm25_index():
    """Lexical search surfaces the chunk sharing the query's terms."""
    index = BM25Index()
    chunks = [
        _chunk("The quick brown fox jumps over the lazy dog", 0),
        _chunk("A revenue report for fiscal year 2024", 1),
        _chunk("Machine learning algorithms for NLP", 2),
    ]
    index.build(chunks)
    results = index.search("revenue fiscal year", top_k=2)
    assert len(results) > 0
    assert results[0].chunk.text == "A revenue report for fiscal year 2024"


def test_bm25_respects_allowed_document_ids():
    """The allow-list filter drops chunks from other documents."""
    index = BM25Index()
    chunks = [
        Chunk(
            text="Legacy chassis diagnostics and wiring reference",
            source_file="legacy.pdf",
            document_id="legacy-doc",
            page_start=1, page_end=1, char_start=0, char_end=40, chunk_index=0,
        ),
        Chunk(
            text="Current system safety interlock calibration checklist",
            source_file="current.pdf",
            document_id="current-doc",
            page_start=1, page_end=1, char_start=41, char_end=82, chunk_index=1,
        ),
        Chunk(
            text="Hydraulic pressure maintenance overview",
            source_file="hydraulic.pdf",
            document_id="hydraulic-doc",
            page_start=1, page_end=1, char_start=83, char_end=120, chunk_index=2,
        ),
    ]
    index.build(chunks)

    results = index.search(
        "safety interlock calibration",
        top_k=5,
        allowed_document_ids=["current-doc"],
    )

    assert len(results) == 1
    assert results[0].chunk.document_id == "current-doc"


def test_bm25_respects_excluded_source_files():
    """The exclusion filter drops chunks from named source files."""
    index = BM25Index()
    chunks = [
        _chunk("Site A ethernet uplink configuration", 0),
        _chunk("Site B ethernet uplink redundancy procedure", 1),
        _chunk("Site C backup routing and diagnostics", 2),
    ]
    chunks[0].source_file = "site-a.pdf"
    chunks[1].source_file = "site-b.pdf"
    index.build(chunks)

    results = index.search(
        "redundancy procedure",
        top_k=5,
        excluded_source_files=["site-a.pdf"],
    )

    assert len(results) == 1
    assert results[0].chunk.source_file == "site-b.pdf"


def test_rrf_merge():
    """A chunk present in both lists outranks single-list chunks."""
    c1 = _chunk("chunk one", 0)
    c2 = _chunk("chunk two", 1)
    c3 = _chunk("chunk three", 2)

    list_a = [SearchResult(chunk=c1, score=0.9), SearchResult(chunk=c2, score=0.7)]
    list_b = [SearchResult(chunk=c2, score=0.8), SearchResult(chunk=c3, score=0.6)]

    merged = reciprocal_rank_fusion([list_a, list_b])
    # c2 appears in both lists so should score highest.
    assert merged[0].chunk.text == "chunk two"
    assert len(merged) == 3


def test_rrf_weighted_list_counts_for_less():
    """Per-list weights let one list contribute less to the fused ranking."""
    c1 = _chunk("dense top", 0)
    c2 = _chunk("other top", 1)

    dense = [SearchResult(chunk=c1, score=0.9)]
    other = [SearchResult(chunk=c2, score=0.95)]

    merged = reciprocal_rank_fusion([dense, other], weights=[1.0, 0.3])
    # Both are rank 0 in their lists; the down-weighted list must lose.
    assert merged[0].chunk.text == "dense top"
    assert merged[0].score > merged[1].score
