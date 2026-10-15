"""Structural chunking tests — the invariants citations depend on."""

from ragline.chunking.models import Chunk
from ragline.chunking.structural import chunk_document
from ragline.parsing.models import PageContent, ParsedDocument


def _make_doc(text: str, filename: str = "test.pdf") -> ParsedDocument:
    """One-page document with a known header, for concise test setup."""
    return ParsedDocument(
        filename=filename,
        file_type="pdf",
        pages=[PageContent(page_number=1, text=text, headers=["Introduction"])],
    )


def test_basic_chunking():
    """Long text splits into multiple chunks, all carrying source identity."""
    text = "This is a test sentence. " * 100
    doc = _make_doc(text)
    chunks = chunk_document(doc, document_id="doc-1", max_tokens=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.source_file == "test.pdf"
        assert chunk.document_id == "doc-1"
        assert chunk.page_start == 1


def test_single_page_metadata():
    """Short text yields one chunk with header and exact page span."""
    doc = _make_doc("Short text.")
    chunks = chunk_document(doc, document_id="doc-1")
    assert len(chunks) == 1
    assert chunks[0].section_header == "Introduction"
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 1


def test_multi_page():
    """Chunks never span pages — each page's text stays on its page number."""
    doc = ParsedDocument(
        filename="multi.pdf",
        file_type="pdf",
        pages=[
            PageContent(page_number=1, text="Page one content.", headers=["Intro"]),
            PageContent(page_number=2, text="Page two content.", headers=["Body"]),
        ],
    )
    chunks = chunk_document(doc, document_id="doc-2")
    assert len(chunks) >= 2
    pages = {c.page_start for c in chunks}
    assert pages == {1, 2}


def test_context_prefix():
    """The embedding prefix names file, page, and section."""
    chunk = Chunk(
        text="test",
        source_file="report.pdf",
        document_id="1",
        page_start=5,
        page_end=5,
        char_start=0,
        char_end=4,
        section_header="Revenue",
    )
    assert "report.pdf" in chunk.context_prefix
    assert "Page: 5" in chunk.context_prefix
    assert "Revenue" in chunk.context_prefix


def test_empty_page_skipped():
    """Blank pages produce no chunks but don't derail later pages."""
    doc = ParsedDocument(
        filename="test.pdf",
        file_type="pdf",
        pages=[
            PageContent(page_number=1, text="", headers=[]),
            PageContent(page_number=2, text="Real content here.", headers=["Section"]),
        ],
    )
    chunks = chunk_document(doc, document_id="doc-3")
    assert len(chunks) == 1
    assert chunks[0].page_start == 2


# --- tables and tiny chunks (2026-10, docs/eval/phase0-index-plan.md) -------

import tiktoken  # noqa: E402

_ENC = tiktoken.encoding_for_model("gpt-4o")


def _page_doc(text: str, filename: str = "t.pdf") -> ParsedDocument:
    """One-page document with the given text and no headings."""
    return ParsedDocument(filename=filename, file_type="pdf",
                          pages=[PageContent(page_number=1, text=text, headers=[])])


def _table(n_rows: int) -> str:
    """A markdown table: header row, separator, then n numbered data rows."""
    lines = ["|Model|Memory|Temperature|", "|---|---|---|"]
    # Each data row is long enough that a small budget splits the table.
    lines += [f"|M-{i:03d}|{i * 64} MB RAM and flash|{i} to {i + 50} degrees C|" for i in range(n_rows)]
    return "\n".join(lines)


def test_table_rows_never_split():
    """Every line of every chunk built from a table is a whole markdown row."""
    chunks = chunk_document(_page_doc(_table(40)), "d", max_tokens=80, min_tokens=0)
    assert len(chunks) > 1
    for c in chunks:
        for line in c.text.splitlines():
            assert line.startswith("|") and line.endswith("|")


def test_table_header_repeated_on_continuations():
    """Each continuation chunk opens with the header row and separator."""
    chunks = chunk_document(_page_doc(_table(40)), "d", max_tokens=80, min_tokens=0)
    for c in chunks:
        lines = c.text.splitlines()
        assert lines[0] == "|Model|Memory|Temperature|" and lines[1] == "|---|---|---|"
    # Every data row appears exactly once across the chunks (no row overlap).
    rows = [ln for c in chunks for ln in c.text.splitlines() if ln.startswith("|M-")]
    assert len(rows) == 40 and len(set(rows)) == 40


def test_continuation_char_start_points_at_first_row():
    """A continuation's char_start is its first own row, not the copied header."""
    text = _table(40)
    chunks = chunk_document(_page_doc(text), "d", max_tokens=80, min_tokens=0)
    for c in chunks[1:]:
        first_row = c.text.splitlines()[2]
        assert text[c.char_start:].startswith(first_row)
        assert text[c.char_end - len(c.text.splitlines()[-1]):c.char_end] == c.text.splitlines()[-1]


def test_bold_row_under_separator_is_header():
    """A spanning group row, separator and all-bold row are all repeated."""
    text = "\n".join(
        ["||**6.5-in.**|**9-in.**|", "|---|---|---|", "|**Attribute**|**2715-T7CD**|**2715-T9WD**|"]
        + [f"|Spec {i}|value {i} for the small terminal|value {i} for the wide terminal|" for i in range(30)]
    )
    chunks = chunk_document(_page_doc(text), "d", max_tokens=90, min_tokens=0)
    assert len(chunks) > 1
    assert all("2715-T7CD" in c.text for c in chunks)


def test_table_without_separator_has_no_header():
    """No separator near the top: rows are still atomic but nothing is repeated."""
    text = "\n".join(f"|row {i}|some value number {i} with words|" for i in range(40))
    chunks = chunk_document(_page_doc(text), "d", max_tokens=60, min_tokens=0)
    assert len(chunks) > 1
    assert sum(c.text.count("|row 0|") for c in chunks) == 1


def test_oversized_row_kept_whole_with_header():
    """A row bigger than the budget is one chunk, still under its header."""
    big = "|Notes|" + "very long cell text " * 60 + "|"
    text = "\n".join(["|Name|Text|", "|---|---|", "|a|short|", big, "|b|short|"])
    chunks = chunk_document(_page_doc(text), "d", max_tokens=60, min_tokens=0)
    holder = [c for c in chunks if big in c.text]
    assert len(holder) == 1 and holder[0].text.startswith("|Name|Text|\n|---|---|")


def test_oversized_first_row_leaves_no_header_only_chunk():
    """A table at page top whose first data row is oversized: no data-less header chunk."""
    big = "|Notes|" + "very long cell text " * 60 + "|"
    text = "\n".join(["|Name|Text|", "|---|---|", big, "|b|short|"])
    chunks = chunk_document(_page_doc(text), "d", max_tokens=60, min_tokens=0)
    for c in chunks:
        # Every chunk holds at least one data row, not just the header and separator.
        assert any(ln not in ("|Name|Text|", "|---|---|") for ln in c.text.splitlines())
    assert sum(c.text.count(big) for c in chunks) == 1


def test_no_sentence_overlap_into_or_out_of_tables():
    """Prose overlap is not seeded into a table chunk, nor rows into prose."""
    prose_before = " ".join(f"Introductory sentence number {i} about the panel." for i in range(12))
    prose_after = " ".join(f"Closing sentence number {i} about the panel." for i in range(12))
    text = prose_before + "\n\n" + _table(12) + "\n\n" + prose_after
    chunks = chunk_document(_page_doc(text), "d", max_tokens=80, min_tokens=0)
    for c in chunks:
        has_rows = any(ln.startswith("|") for ln in c.text.splitlines())
        if has_rows and c.text.startswith("|"):
            # A chunk that opens with a table holds no introductory prose.
            assert "Introductory" not in c.text
        if c.text.startswith("Closing"):
            # A prose chunk after the table carries no rows as overlap.
            assert "|" not in c.text


def test_orphan_header_moves_forward():
    """A header that would end a chunk with no rows under it moves to the next chunk."""
    prose = " ".join(f"Filler sentence {i} for the budget." for i in range(8))
    text = prose + "\n\n" + _table(6)
    chunks = chunk_document(_page_doc(text), "d", max_tokens=70, min_tokens=0)
    for c in chunks:
        assert not c.text.rstrip().endswith("|---|---|---|")


def test_tiny_tail_merged_into_sibling():
    """A tiny chunk after a sibling on the same page is folded into it."""
    long_sentence = "word " * 100 + "end."
    text = long_sentence + " Contact: TEL 1234."
    chunks = chunk_document(_page_doc(text), "d", max_tokens=60, min_tokens=12)
    assert len(chunks) == 1 and chunks[0].text.endswith("Contact: TEL 1234.")


def test_tiny_head_merged_forward():
    """A tiny first chunk of a page is folded into the next chunk."""
    big = "|Notes|" + "long cell " * 80 + "|"
    text = "Title.\n\n" + "\n".join(["|A|B|", "|---|---|", big])
    chunks = chunk_document(_page_doc(text), "d", max_tokens=60, min_tokens=12)
    assert len(chunks) == 1 and chunks[0].text.startswith("Title.")
    assert chunks[0].char_start == 0


def test_single_tiny_chunk_kept_and_pages_not_merged():
    """A page whose only chunk is tiny keeps it; tiny chunks never cross pages."""
    doc = ParsedDocument(filename="t.pdf", file_type="pdf", pages=[
        PageContent(page_number=1, text="A long first page sentence. " * 30, headers=[]),
        PageContent(page_number=2, text="Tiny.", headers=[]),
    ])
    chunks = chunk_document(doc, "d", max_tokens=100, min_tokens=20)
    assert chunks[-1].text == "Tiny." and chunks[-1].page_start == 2
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_min_tokens_capped_by_budget():
    """With a small budget the minimum shrinks, so full chunks never merge."""
    text = "This is a test sentence. " * 100
    assert len(chunk_document(_page_doc(text), "d", max_tokens=50, min_tokens=48)) > 1


# --- regressions from the real corpus (pymupdf4llm 1.28.2 parse) ------------

# PanelView 5500 technical data p.3, trimmed: the spanning group row, the
# separator, the Attribute row naming 2715-T7CD, then data rows. The memory row
# used to land in a chunk with neither header row (golden question A09).
_PV5500_P3 = "\n".join([
    "PanelView 5500 Terminal Specifications",
    "",
    "### **Technical Specifications**",
    "",
    "This section provides technical specifications for the PanelView 5500 terminals. "
    "#### **Technical Specifications - PanelView 5500 Terminals (6.5-inch and 9-inch)**",
    "",
    "||**6.5-in. Touch**|**6.5-in. Touch**|**with Keypad**|**9-in.**|**Touch**|",
    "|---|---|---|---|---|---|",
    "|**Attribute**|**2715-T7CD**<br>**2715-T7CD-B**<sup>**(1)**</sup><br>**2715-T7CA**<br>**2715-T7CA-B**"
    "<sup>**(1)**</sup>|**2715-B7CD**<br>**2715-B7CD -B**<sup>**(1)**</sup>|**2715-B7CA**<br>**2715-B7CA-B**"
    "<sup>**(1)**</sup>|**2715-T9WD**<br>**2715-T9WD-B**<sup>**(1)**</sup>|**2715-T9WA**<br>**2715-T9WA-B**"
    "<sup>**(1)**</sup>|",
    "|Operator input|Touch plus menu navigation button|Touch with keypad plus menu|navigation button|"
    "Touch plus menu navigation b|utton|",
    "|Display type|Color TFT LCD (thin-film-transistor, liquid-crystal display)|||||",
    "|Display size, diagonal|6.5-in.|6.5-in.||9-in. widescreen||",
    "|Viewing area, W x H|132 x 99 mm (5.2 x 3.9 in.)|132 x 99 mm (5.2 x 3.9 in.)||196 x 118 mm (7.7 x 4.6 in.)||",
    "|Display resolution/aspect<br>ratio|640 x 480 VGA, 4:3|640 x 480 VGA, 4:3||800 x 480 WVGA, 5:3||",
    "|Color depth|18-bit color graphics (262,144 colors)|||||",
    "|Brightness, typical|300 cd/m<sup>2</sup>(Nits)|||||",
    "|Backlight|Light-emitting diode, non-replaceable<br>Life: 50,000 h min at 40 °C (104 °F) to half-brightness|||||",
    "|Backlight power<br>consumption, typical|3 W|3 W||3.5 W||",
    "|Touch screen|Analog resistive<br>Actuation rating: 1 million presses<br>Operating force: 100 grams|"
    "Analog resistive<br>Actuation rating: 1 million pres<br>Operating force: 100 grams|ses|Analog resistive"
    "<br>Actuation rating: 1 million pre<br>Operating force: 100 grams|sses|",
    "|Keypad|—|**•** 12 function keys: L1…L6, R<br>**•** Numeric keypad and naviga<br>**•** Actuating rating: "
    "1 million p<br>**•** Operating force: 300 grams|1…R6<br>tion keys<br>resses|—||",
    "|Battery (real-time clock<br>backup)|Accuracy: +/-2 minutes per month.<br>Battery life: 4 years min at "
    "25 °C (77 °F)<br>Replacement: CR2032 lithium coin cell|||||",
    "|Memory<br>RAM<br>Use available|512 MB RAM<br>250 MB nonvolatile storage for projects|||||",
    "|Secure Digital (SD) card slot|One SD card slot for external storage; supports cat. no. 1784-S|D_x_cards.||||",
    "|Status indicators|STS (status, green), ERR (error, red)|||||",
])


def test_regression_pv5500_memory_row_keeps_catalogue_header():
    """A09: the chunk holding the memory row also names 2715-T7CD."""
    chunks = chunk_document(_page_doc(_PV5500_P3, "panelview_5500_technical_data.pdf"), "d", max_tokens=512)
    holder = [c for c in chunks if "512 MB RAM" in c.text]
    assert len(holder) == 1
    assert "2715-T7CD" in holder[0].text and "|---|" in holder[0].text


# Weintek eMT3070A datasheet p.2, trimmed: the drawing/pin-table text arrives as
# one oversized "sentence", and the contact line used to become a 32-token chunk
# on its own that outranked the real spec chunk (golden question D10).
_EMT3070A_P2 = (
    "Top View\n\n200,35\n [7,888]\n\n" + "PIN# Symbol COM1 [RS232] COM3 [RS232] Rx- Data- Rx+ Data+ Tx- Tx+ GND\n" * 40
    + "Ordering Information eMT3070A: 7\" TFT LCD HMI, 256 MB flash memory / 256 MB RAM\n\n"
    + "Contact: WEINTEK LABS., INC.  TEL: +886-2-22286770  Web:www.weintek.com\n\n"
    + "eMT3070A1_DataSheet_ENG_20150123\n"
)


def test_regression_emt3070a_no_tiny_tail():
    """D10: no chunk under 48 tokens follows a sibling on the same page."""
    chunks = chunk_document(_page_doc(_EMT3070A_P2, "emt3070a_7in_datasheet.pdf"), "d", max_tokens=512)
    assert len(chunks) >= 1
    for c in chunks[1:]:
        assert len(_ENC.encode(c.text)) >= 48
    assert "eMT3070A1_DataSheet_ENG_20150123" in chunks[-1].text
