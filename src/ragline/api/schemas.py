"""API schemas — pydantic request/response models for every route.

Ported from raggles, trimmed to the surviving feature set, and extended with
`original_path` on document and source schemas (the citation-provenance
feature).
"""

from typing import Annotated

from pydantic import BaseModel, Field

# --- Citations / answers ----------------------------------------------------


class SpanSchema(BaseModel):
    """One run of answer text plus the citation ids attached to it."""

    text: str
    citation_ids: list[int] = []


class CitationSchema(BaseModel):
    """One deduplicated source: everything the CitationSidebar renders."""

    citation_id: int
    source_file: str
    page_number: int | None = None
    section: str | None = None
    quoted_text: str
    document_id: str
    # Original network location ("" when the uploader didn't record one, or
    # when the current user may not access the source — no path leaks).
    original_path: str = ""
    # Whether THIS user may open the source (NTFS ACL intersection). UX hint
    # only — GET /documents/{id}/content re-checks server-side regardless.
    # Default False: anything unannotated renders locked, never open.
    accessible: bool = False


# A document id is a uuid4 string; the cap keeps a hostile body from smuggling
# megabytes through the scope list. The LIST itself is deliberately uncapped:
# a selection of thousands of documents is a normal corpus-scale request.
DocumentId = Annotated[str, Field(max_length=64)]


class QueryRequest(BaseModel):
    """One-shot query (no session, no memory) — used by the eval harness."""

    question: str
    # Retrieval scope (NEW): only these documents are searched. Omitted or
    # empty = the whole corpus, as before. The Documents tab's selection
    # sends the ids it has ticked; folders are expanded client-side.
    allowed_document_ids: list[DocumentId] | None = None


class QueryResponse(BaseModel):
    """One-shot answer with citations and whole-call token totals."""

    answer: str
    spans: list[SpanSchema]
    sources: list[CitationSchema]
    query: str
    model_used: str
    used_graph: bool = False
    response_time_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


# --- Chat -------------------------------------------------------------------


class ChatRequest(BaseModel):
    """A chat turn; use_memory is THE memory toggle, sent per turn."""

    session_id: str
    question: str
    use_memory: bool = True
    # Retrieval scope (NEW), same semantics as QueryRequest: omitted/empty =
    # everything. Applies to the RAG leg only — library answers (document
    # listings) still describe the whole corpus.
    allowed_document_ids: list[DocumentId] | None = None


class ChatResponse(BaseModel):
    """SSE `answer` event payload — the cited answer, pre-confidence."""

    answer: str
    spans: list[SpanSchema]
    sources: list[CitationSchema]
    query: str
    model_used: str
    session_id: str
    rewritten_query: str
    turn_number: int
    used_rag: bool = True
    used_library: bool = False
    used_graph: bool = False
    response_time_ms: float
    memory_enabled: bool = True
    trace_id: str | None = None


class ConfidenceUpdate(BaseModel):
    """SSE `complete` event payload — confidence + whole-turn token totals."""

    confidence_score: float | None = None
    confidence_report: str | None = None
    # Whole-turn totals across all passes (the simple token usage score).
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    memory_enabled: bool = True


class SessionSummarySchema(BaseModel):
    """One row in the session list (sidebar)."""

    session_id: str
    created_at: str
    turn_count: int
    # Sum of whole-turn token totals — the header's session counter.
    total_tokens: int = 0
    summary: str = ""
    topics: list[str] = []


class SessionHistoryResponse(BaseModel):
    """Full turn history for re-rendering a session."""

    session_id: str
    created_at: str
    turns: list[dict]


# --- Documents / batches ----------------------------------------------------


class DocumentSchema(BaseModel):
    """One document row as the Documents tab sees it."""

    id: str
    filename: str
    file_type: str
    upload_date: str
    page_count: int
    chunk_count: int
    status: str
    stage: str = ""
    uploaded_by: str = ""
    # Original network location the file was uploaded from ("" when unknown).
    original_path: str = ""
    version: int = 1
    # Explorer-tree coordinates (NEW). upload_root is the folder the upload
    # came from, recovered from original_path (e.g. \\server\eng\ProjectX);
    # when that is unknown or ACL-hidden for this user it is a batch label
    # ("Upload 2026-09-12 · a1b2c3d4") so the hierarchy is always visible and
    # only the root's NAME depends on the ACL. folder_path is the directory
    # part of the upload-relative path, "/"-separated, "" at the root.
    upload_root: str = ""
    folder_path: str = ""
    # For a skipped_duplicate row: the id of the READY document with the same
    # bytes (the ingest that this upload was skipped in favour of). "" for
    # every other status, and for a skipped row whose twin has since gone.
    # Lets the tree draw the ingested copy at the duplicate's location.
    duplicate_of: str = ""


class FolderRef(BaseModel):
    """One explorer-tree coordinate: a root node plus a "/"-separated path
    beneath it ("" = directly under the root). Body of the layout writes."""

    # Same bounds the storage layer enforces (storage/layout.py), applied
    # here too so an oversized body is refused before it is deserialised
    # into a row.
    root: str = Field(max_length=512)
    folder_path: str = Field("", max_length=1024)


class LayoutFolderSchema(FolderRef):
    """A user-created explorer folder."""

    created_by: str = ""


class LayoutPlacementSchema(FolderRef):
    """Where a moved document is shown instead of its upload location."""

    document_id: str


class LayoutResponse(BaseModel):
    """GET /documents/layout — everything the tree adds on top of the listing."""

    folders: list[LayoutFolderSchema] = []
    placements: list[LayoutPlacementSchema] = []


class ExplorerResponse(BaseModel):
    """GET /documents/explorer — documents and layout from one scan."""

    documents: list[DocumentSchema] = []
    layout: LayoutResponse = LayoutResponse()


class BatchUploadResponse(BaseModel):
    """Returned immediately after an upload; processing continues in background."""

    batch_id: str
    total_files: int
    # Filenames rejected because their extension isn't supported.
    skipped_unsupported: list[str] = []


class IngestPathRequest(BaseModel):
    """Body of /batches/ingest-path — server-side folder ingest.

    `path` must resolve inside one of the operator-allowlisted INGEST_ROOTS
    directories; the endpoint streams the folder's files from local disk
    instead of receiving them over HTTP (built for multi-GB corpus runs).
    """

    path: str
    # Same provenance semantics as the upload form field: the network folder
    # this corpus really lives in, joined with each file's relative path.
    original_base_path: str = ""


class BatchDocumentSchema(BaseModel):
    """Per-document progress row inside a batch status response."""

    id: str
    filename: str
    file_type: str
    status: str
    source_path: str = ""
    original_path: str = ""
    page_count: int = 0
    chunk_count: int = 0
    # Live sub-document progress: parsing/chunking/embedding/storing/extracting_graph.
    stage: str = ""


class BatchStatusResponse(BaseModel):
    """Full batch state — polled by the BatchProgress UI."""

    id: str
    created_at: str
    total_files: int
    completed_files: int
    failed_files: int
    skipped_files: int
    status: str
    # Aggregate count of documents currently inside each pipeline stage
    # (parsing/chunking/embedding/storing/extracting_graph) — lets the UI
    # draw per-stage bars without walking the full documents list.
    stages: dict[str, int] = {}
    # Per-document rows; omitted (empty) when polled with
    # ?include_documents=false — the lightweight fast-poll variant.
    documents: list[BatchDocumentSchema] = []


class BatchListItem(BaseModel):
    """One row in the batch history list (no per-document detail)."""

    id: str
    created_at: str
    total_files: int
    completed_files: int
    failed_files: int
    skipped_files: int
    status: str
