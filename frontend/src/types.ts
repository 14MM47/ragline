// types.ts — TypeScript mirrors of the backend API schemas
// (src/ragline/api/schemas.py). Ported from raggles and trimmed to the
// surviving feature set: no traces/admin/feedback/retrieval-metrics types,
// no per-stage token fields — plus the new original_path provenance fields.

// One deduplicated source reference the answer used (CitationSchema).
export interface Citation {
  citation_id: number
  // Assigned client-side by CitedResponse: badges renumber 1,2,3… in order
  // of first appearance, regardless of backend citation ids.
  display_citation_id?: number
  source_file: string
  page_number: number | null
  section: string | null
  quoted_text: string
  document_id: string
  // NEW: original network location the source document was uploaded from
  // ("" when the uploader didn't record one).
  original_path: string
  // Whether THIS user may open the source file (NTFS ACL intersection).
  // UX hint only — the backend re-checks on the download itself.
  accessible: boolean
}

// One run of answer text plus the citation ids attached to it (SpanSchema).
export interface Span {
  text: string
  citation_ids: number[]
}

// One-shot /query response (QueryResponse) — also the base of ChatResponse.
export interface QueryResponse {
  answer: string
  spans: Span[]
  sources: Citation[]
  query: string
  model_used: string
}

// A document row in the Documents tab (DocumentSchema).
export interface Document {
  id: string
  filename: string
  file_type: string
  upload_date: string
  page_count: number
  chunk_count: number
  status: string
  stage: string
  uploaded_by?: string
  // Provenance: where the file originally lives on the network.
  original_path: string
  // Version number within its version chain (1 = original upload).
  version: number
  // Explorer-tree coordinates: the folder the upload came from (or a batch
  // label when unknown/hidden) and the "/"-separated directory part of the
  // upload-relative path ("" at the root).
  upload_root: string
  folder_path: string
  // skipped_duplicate rows: id of the ready document with the same bytes
  // ("" otherwise, or when that twin has since been deleted).
  duplicate_of: string
}

// Immediate response to any upload (BatchUploadResponse).
export interface BatchUploadResponse {
  batch_id: string
  total_files: number
  skipped_unsupported: string[]
}

// Per-document progress row inside a batch status (BatchDocumentSchema).
export interface BatchDocument {
  id: string
  filename: string
  file_type: string
  status: string
  source_path: string
  original_path: string
  page_count: number
  chunk_count: number
  stage: string
}

// Full batch state, polled during ingestion (BatchStatusResponse).
export interface BatchStatus {
  id: string
  created_at: string
  total_files: number
  completed_files: number
  failed_files: number
  skipped_files: number
  status: string
  // Empty when polled with include_documents=false (the light variant).
  documents: BatchDocument[]
  // NEW: count of documents currently in each ingestion stage
  // (parsing/chunking/embedding/storing/extracting_graph). Present on both
  // the light and full variants of GET /batches/{id}.
  stages: Record<string, number>
}

// One row in the batch history list (BatchListItem).
export interface BatchListItem {
  id: string
  created_at: string
  total_files: number
  completed_files: number
  failed_files: number
  skipped_files: number
  status: string
}

// --- Health ------------------------------------------------------------------

// GET /health response — reachability snapshot for each backing service
// (cached server-side ~30s). Drives the header status dots + ingest guard.
export interface HealthStatus {
  status: 'ok' | 'degraded'
  version: string
  qdrant: boolean
  llm: boolean
  embedder: boolean
  // null = local/none reranker configured — reachability not applicable.
  reranker: boolean | null
}

// --- Chat types -------------------------------------------------------------

// SSE `answer` event payload (ChatResponse), extended client-side with the
// token/confidence fields the `complete` event later fills in.
export interface ChatResponse extends QueryResponse {
  session_id: string
  rewritten_query: string
  turn_number: number
  // Filled by the `complete` SSE event (null until then).
  confidence_score: number | null
  confidence_report: string | null
  // Which pipeline(s) produced this answer.
  used_rag: boolean
  used_library: boolean
  used_graph: boolean
  response_time_ms: number | null
  memory_enabled?: boolean
  trace_id?: string | null
  // Whole-turn token totals (the simple usage score) — from the `complete`
  // event on live turns, or from the stored TurnRecord on history loads.
  prompt_tokens?: number | null
  completion_tokens?: number | null
}

// SSE `complete` event payload (ConfidenceUpdate).
export interface ConfidenceUpdate {
  confidence_score: number | null
  confidence_report: string | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  total_tokens?: number | null
  memory_enabled?: boolean
}

// One rendered message in the chat transcript (client-side only).
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  // Assistant messages carry the full response for citation rendering.
  response?: ChatResponse
  timestamp: string
  // True between the `answer` and `complete` SSE events (memory updating).
  memoryLoading?: boolean
}

// One row in the session sidebar (SessionSummarySchema).
export interface SessionSummary {
  session_id: string
  created_at: string
  turn_count: number
  total_tokens: number
  summary: string
  topics: string[]
}

// --- Explorer layout (LayoutResponse) ---------------------------------------

// One explorer-tree coordinate: a root node + "/"-separated path beneath it.
export interface FolderRef {
  root: string
  folder_path: string
}

// A user-created explorer folder.
export interface LayoutFolder extends FolderRef {
  created_by: string
}

// Where a moved document is shown instead of its upload location.
export interface LayoutPlacement extends FolderRef {
  document_id: string
}

// GET /documents/layout — everything the tree adds on top of the listing.
export interface Layout {
  folders: LayoutFolder[]
  placements: LayoutPlacement[]
}

// GET /documents/explorer — documents and layout from one server pass.
export interface ExplorerResponse {
  documents: Document[]
  layout: Layout
}
