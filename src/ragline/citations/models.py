"""Citation data models.

Ported from raggles with one addition: Citation.original_path — the network
location the source document was uploaded from, filled in by the chat/query
routes from the metadata DB AFTER extraction (never stored in Qdrant, so it
stays correctable without re-ingesting).
"""

from dataclasses import dataclass, field


@dataclass
class Citation:
    """One deduplicated source reference the answer actually used."""

    # Stable id within this response (the deduped source number).
    citation_id: int
    # Display name of the source document.
    source_file: str
    # 1-indexed page the cited chunk starts on (None when unknown).
    page_number: int | None
    # Section heading of the cited chunk (None when the page had none).
    section: str | None
    # First 500 chars of the cited chunk — shown as the quote in the sidebar.
    quoted_text: str
    # Metadata-DB document id — key for the "Open copy" content link.
    document_id: str
    # NEW: original network location (e.g. \\server\share\...\manual.pdf);
    # "" when the uploader did not record one.
    original_path: str = ""


@dataclass
class CitedSpan:
    """A run of answer text plus the citation ids attached to it."""

    text: str
    citation_ids: list[int] = field(default_factory=list)


@dataclass
class CitedResponse:
    """The fully parsed answer: spans + deduplicated sources + metadata."""

    spans: list[CitedSpan]
    sources_used: list[Citation]
    query: str
    model_used: str
    # The unparsed answer text (kept for the API's `answer` field).
    raw_text: str = ""
    # True when knowledge-graph context was injected into the prompt.
    used_graph: bool = False
