"""Hybrid search tests — BM25 filtering and Reciprocal Rank Fusion."""

from ragline.chunking.models import Chunk
from ragline.retrieval.hybrid import BM25Index, reciprocal_rank_fusion, tokenise
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


def test_tokenise_strips_table_pipes_and_markdown():
    """A real table-row string: pipes, bold markers and <br> fall away."""
    # Row drawn from the corpus: two catalogue numbers glued by `<br>` and bold markers.
    row = "|**attribute**|**2715-t7cd**<br>**2715-t7cd-b**|"
    tokens = tokenise(row)
    # Each catalogue number appears both whole and as its parts (`t7cd-b` -> `t7cd`, `b`).
    assert "attribute" in tokens
    assert "2715-t7cd" in tokens and "2715" in tokens and "t7cd" in tokens
    assert "2715-t7cd-b" in tokens and "b" in tokens
    # Table pipes, asterisks and the `<br>` tag never survive as tokens of their own.
    assert "|" not in tokens and "**" not in tokens and "br" not in tokens


def test_tokenise_handles_fused_table_cell_from_corpus():
    """A fused `consumption**<br>***5**|max.` cell still yields its words and numbers."""
    # Mirrors the second corpus example: emphasis + <br> + a stray `*` run next to a pipe.
    tokens = tokenise("consumption**<br>***5**|max.")
    # `consumption` and `5` must appear; `max` stripped of its trailing period.
    assert tokens.count("consumption") == 1
    assert "5" in tokens
    assert "max" in tokens


def test_tokenise_strips_trailing_punctuation_in_prose():
    """Trailing commas, periods and parentheses fall off catalogue numbers in prose."""
    tokens = tokenise("The 2711P-T7C21D8S, DOP-107WV and 1756-L85E (v1.2).")
    # Case-folded whole identifiers with their parts emitted alongside.
    assert "2711p-t7c21d8s" in tokens and "2711p" in tokens and "t7c21d8s" in tokens
    assert "dop-107wv" in tokens and "dop" in tokens and "107wv" in tokens
    assert "1756-l85e" in tokens and "1756" in tokens and "l85e" in tokens
    assert "v1.2" in tokens and "v1" in tokens and "2" in tokens
    # Trailing punctuation never becomes a token.
    assert "," not in tokens and "." not in tokens and "(" not in tokens


def test_tokenise_query_matches_table_cell():
    """A `DOP-107WV` query shares tokens with the fused `|**DOP-107WV**|` table cell."""
    query_tokens = set(tokenise("How much power does the DOP-107WV draw?"))
    row_tokens = set(tokenise("|**DOP-107WV**|8.4 W|"))
    # The whole catalogue number AND its parts land in both bags.
    assert "dop-107wv" in query_tokens and "dop-107wv" in row_tokens
    assert "dop" in query_tokens and "dop" in row_tokens
    assert "107wv" in query_tokens and "107wv" in row_tokens


def test_tokenise_preserves_plain_prose_words():
    """Regression: ordinary prose still tokenises as before (lowercased split-on-space)."""
    # Both strings must produce the same plain-English token list.
    assert tokenise("The quick brown fox jumps over the lazy dog") == [
        "the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog",
    ]
    # And "revenue fiscal year 2024" splits exactly as the pre-tokeniser whitespace rule did.
    assert tokenise("A revenue report for fiscal year 2024") == [
        "a", "revenue", "report", "for", "fiscal", "year", "2024",
    ]


def test_tokenise_degree_sign_reduces_to_unit_letter():
    """Documented edge case: `°c` is reduced to `c` by the alphanumeric-only token rule."""
    # `°` is not alphanumeric; the alphanumeric-anchored regex captures just `c`.
    tokens = tokenise("Operating temperature: -20 °C to 55 °C")
    assert tokens.count("c") == 2
    # Numbers survive, including the sign-less `20` and `55` from the range.
    assert "20" in tokens and "55" in tokens


def test_bm25_catalogue_number_matches_table_chunk():
    """End-to-end: a BM25 query for a catalogue number scores a table-row chunk above zero."""
    index = BM25Index()
    # Build the SAME way `RetrievalPipeline.rebuild_bm25_index` does: a list of chunks.
    chunks = [
        _chunk("Introduction and general safety notes for the HMI product line.", 0),
        # Table row — the critical regression case: fused cells with the catalogue number.
        _chunk("|**attribute**|**DOP-107WV**<br>**DOP-107BV**|\n|**max. power**|**8.4 W**|", 1),
        _chunk("Warranty, support and ordering information for distributors.", 2),
    ]
    index.build(chunks)
    results = index.search("DOP-107WV power consumption", top_k=3)
    # The table-row chunk must come back with a non-zero score; before the fix
    # the whole bold-and-pipe cell was one unmatchable token.
    assert any(r.chunk.chunk_index == 1 and r.score > 0 for r in results)


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
