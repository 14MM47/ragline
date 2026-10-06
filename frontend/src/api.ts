// api.ts — thin fetch client for the ragline backend.
// Ported from raggles minus the feedback/traces/admin/feature-flag APIs.
// New: upload functions accept optional original-path provenance values,
// server-folder ingest, the /health probe, and a light batch-status variant.

import type {
  QueryResponse,
  Document,
  BatchUploadResponse,
  BatchStatus,
  BatchListItem,
  HealthStatus,
  ChatResponse,
  ConfidenceUpdate,
  SessionSummary,
  FolderRef,
  Layout,
  LayoutFolder,
  LayoutPlacement,
  ExplorerResponse,
} from './types'

// All routes live under /api (Vite dev proxy / same-origin in production).
const BASE = '/api'

// --- Auth-aware fetch --------------------------------------------------------

// Every API call goes through this: a 401 means the session is missing or
// expired, so the whole page is handed to the SSO login flow. The returned
// promise never settles in that case — the page is navigating away, and
// letting callers proceed would just flash error toasts during the redirect.
async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(input, init)
  if (res.status === 401) {
    window.location.href = `${BASE}/auth/login`
    return new Promise<Response>(() => {})
  }
  return res
}

// Identity for the header badge. Served by GET /api/auth/me; in dev mode
// (AUTH_ENABLED=false) the backend answers with a local "dev" identity.
export interface Me {
  oid: string
  upn: string
  display_name: string
  is_admin: boolean
  auth_enabled: boolean
}

export async function getMe(): Promise<Me> {
  const res = await apiFetch(`${BASE}/auth/me`)
  if (!res.ok) throw new Error(`Failed to load identity: ${res.statusText}`)
  return res.json()
}

// Sign out. POST-only server-side (CSRF hardening) — the response says where
// to navigate next: "/" normally, or the Entra end-session URL when the
// deployment enables front-channel logout (shared/kiosk machines).
export async function logout(): Promise<string> {
  const res = await fetch(`${BASE}/auth/logout`, { method: 'POST' })
  if (!res.ok) return '/'
  const body = await res.json().catch(() => null)
  return body?.logout_url || '/'
}

// --- One-shot query (no session) -------------------------------------------

// allowedDocumentIds (optional): the Documents tab's retrieval scope; null or
// empty searches the whole corpus.
export async function queryDocuments(question: string, allowedDocumentIds?: string[] | null): Promise<QueryResponse> {
  const res = await apiFetch(`${BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, allowed_document_ids: allowedDocumentIds?.length ? allowedDocumentIds : null }),
  })
  if (!res.ok) throw new Error(`Query failed: ${res.statusText}`)
  return res.json()
}

// --- Uploads ----------------------------------------------------------------

// Single-file upload. originalPath (optional) is the file's FULL original
// network path, recorded for citation provenance.
export async function uploadDocument(file: File, originalPath?: string): Promise<BatchUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  // Only send the field when the user provided a value.
  if (originalPath) form.append('original_path', originalPath)
  const res = await apiFetch(`${BASE}/documents/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
  return res.json()
}

// Multi-file or ZIP upload. originalBasePath (optional) is the FOLDER the
// files came from; the backend joins it with each file's relative path.
export async function uploadBatch(
  files: File[],
  zipFile?: File,
  originalBasePath?: string,
): Promise<BatchUploadResponse> {
  const form = new FormData()
  if (zipFile) {
    form.append('zip_file', zipFile)
  }
  for (const file of files) {
    form.append('files', file)
  }
  if (originalBasePath) form.append('original_base_path', originalBasePath)
  const res = await apiFetch(`${BASE}/batches/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Batch upload failed: ${res.statusText}`)
  return res.json()
}

// NEW: server-folder ingest — point the backend at a directory it can read
// directly (must sit inside the INGEST_ROOTS allowlist); no browser upload.
// originalBasePath is the citation-provenance base joined with each file's
// relative path server-side (may be "" when the user left it blank).
export async function ingestServerPath(
  path: string,
  originalBasePath: string,
): Promise<BatchUploadResponse> {
  const res = await apiFetch(`${BASE}/batches/ingest-path`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, original_base_path: originalBasePath }),
  })
  if (!res.ok) {
    // Surface the backend's `detail` string (400 validation / 403 allowlist)
    // so the UI shows the real reason, not just the HTTP status text.
    let detail = ''
    try {
      detail = (await res.json())?.detail ?? ''
    } catch {
      // Non-JSON error body — fall through to the generic message.
    }
    throw new Error(detail || `Server-folder ingest failed: ${res.statusText}`)
  }
  return res.json()
}

// --- Batches / documents ----------------------------------------------------

// includeDocuments=false requests the LIGHT variant: counters + per-stage
// counts only, with `documents` returned as [] — used by the fast 1.5s
// progress poll so it stays cheap on large batches.
export async function getBatchStatus(
  batchId: string,
  includeDocuments: boolean = true,
): Promise<BatchStatus> {
  const suffix = includeDocuments ? '' : '?include_documents=false'
  const res = await apiFetch(`${BASE}/batches/${batchId}${suffix}`)
  if (!res.ok) throw new Error(`Failed to get batch status: ${res.statusText}`)
  return res.json()
}

export async function listBatches(): Promise<BatchListItem[]> {
  const res = await apiFetch(`${BASE}/batches`)
  if (!res.ok) throw new Error(`Failed to list batches: ${res.statusText}`)
  return res.json()
}

export async function listDocuments(): Promise<Document[]> {
  const res = await apiFetch(`${BASE}/documents`)
  if (!res.ok) throw new Error(`List failed: ${res.statusText}`)
  return res.json()
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await apiFetch(`${BASE}/documents/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete failed: ${res.statusText}`)
}

// Re-ingest a document that errored. The backend refuses (409) unless the
// document's status is 'error', and refuses (503) when the pod is down — both
// carry a readable `detail`, so surface it rather than the bare status text.
export async function retryDocument(id: string): Promise<void> {
  const res = await apiFetch(`${BASE}/documents/${id}/retry`, { method: 'POST' })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail || `Retry failed: ${res.statusText}`)
  }
}

// --- Explorer layout ---------------------------------------------------------
// User-created folders + document placements for the Documents tab's folder
// view. Shared between users; purely visual (nothing in retrieval changes).

// Documents + layout in one round trip — what the Documents tab polls. One
// server-side document scan and ACL lookup serve both halves.
export async function getExplorer(): Promise<ExplorerResponse> {
  const res = await apiFetch(`${BASE}/documents/explorer`)
  if (!res.ok) throw new Error(`Explorer failed: ${res.statusText}`)
  return res.json()
}

export async function getLayout(): Promise<Layout> {
  const res = await apiFetch(`${BASE}/documents/layout`)
  if (!res.ok) throw new Error(`Layout failed: ${res.statusText}`)
  return res.json()
}

// The layout writes all answer a readable `detail` on 400/404/409.
async function detailOr(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => null)
  return new Error(body?.detail || `${fallback}: ${res.statusText}`)
}

export async function createFolder(ref: FolderRef): Promise<LayoutFolder> {
  const res = await apiFetch(`${BASE}/documents/layout/folders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(ref),
  })
  if (!res.ok) throw await detailOr(res, 'Create folder failed')
  return res.json()
}

export async function deleteFolder(ref: FolderRef): Promise<void> {
  const res = await apiFetch(`${BASE}/documents/layout/folders`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(ref),
  })
  if (!res.ok) throw await detailOr(res, 'Delete folder failed')
}

export async function moveDocument(id: string, ref: FolderRef): Promise<LayoutPlacement> {
  const res = await apiFetch(`${BASE}/documents/layout/placements/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(ref),
  })
  if (!res.ok) throw await detailOr(res, 'Move failed')
  return res.json()
}

// Back to the upload location (drops the placement row).
export async function unmoveDocument(id: string): Promise<void> {
  const res = await apiFetch(`${BASE}/documents/layout/placements/${id}`, { method: 'DELETE' })
  if (!res.ok) throw await detailOr(res, 'Reset location failed')
}

// --- Chat (SSE) -------------------------------------------------------------

// POST /chat and parse the two-frame SSE stream:
//   event: answer   -> onAnswer(ChatResponse)   (the cited answer)
//   event: complete -> onComplete(ConfidenceUpdate) (confidence + tokens)
export async function chatQuery(
  sessionId: string,
  question: string,
  onAnswer: (resp: ChatResponse) => void,
  onComplete: (update: ConfidenceUpdate) => void,
  useMemory: boolean = true,
  // Retrieval scope from the Documents tab selection; null/empty = everything.
  allowedDocumentIds?: string[] | null,
): Promise<void> {
  const res = await apiFetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      question,
      use_memory: useMemory,
      allowed_document_ids: allowedDocumentIds?.length ? allowedDocumentIds : null,
    }),
  })
  if (!res.ok) throw new Error(`Chat failed: ${res.statusText}`)

  // Manual SSE parsing over the fetch body stream.
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  // These must persist across chunk boundaries — an SSE frame can be split
  // across multiple network reads, so resetting them per-chunk loses events.
  let currentEvent = ''
  let currentData = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // Split into lines; the final partial line stays in the buffer.
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const rawLine of lines) {
        const line = rawLine.replace(/\r$/, '')
        if (line.startsWith('event:')) {
          // Remember which event the next data line belongs to.
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          currentData = line.slice(5).trim()
        } else if (line === '' && currentData) {
          // Empty line = end of SSE frame — dispatch it.
          const parsed = JSON.parse(currentData)
          if (currentEvent === 'answer') {
            onAnswer(parsed)
          } else if (currentEvent === 'complete') {
            onComplete(parsed)
          }
          currentEvent = ''
          currentData = ''
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// --- Health ------------------------------------------------------------------

// GET /health — per-service reachability snapshot (qdrant/llm/embedder/
// reranker). Cached server-side ~30s, so polling at 30s costs one probe.
export async function getHealth(): Promise<HealthStatus> {
  const res = await apiFetch(`${BASE}/health`)
  if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`)
  return res.json()
}

// --- Sessions ----------------------------------------------------------------

export async function listSessions(): Promise<SessionSummary[]> {
  const res = await apiFetch(`${BASE}/sessions`)
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.statusText}`)
  return res.json()
}

export async function getSessionHistory(
  sessionId: string,
): Promise<{ session_id: string; created_at: string; turns: any[] }> {
  const res = await apiFetch(`${BASE}/sessions/${sessionId}`)
  if (!res.ok) throw new Error(`Failed to get session: ${res.statusText}`)
  return res.json()
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await apiFetch(`${BASE}/sessions/${sessionId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete session failed: ${res.statusText}`)
}

// --- Memory management -------------------------------------------------------

// Re-summarize the whole conversation, then keep only the last 2 turns.
export async function compactMemory(sessionId: string): Promise<{ status: string; turns_kept: number }> {
  const res = await apiFetch(`${BASE}/sessions/${sessionId}/compact`, { method: 'POST' })
  if (!res.ok) throw new Error(`Compact memory failed: ${res.statusText}`)
  return res.json()
}

// Reset summary/facts/topics/turns but keep the session id.
export async function clearMemory(sessionId: string): Promise<{ status: string }> {
  const res = await apiFetch(`${BASE}/sessions/${sessionId}/clear-memory`, { method: 'POST' })
  if (!res.ok) throw new Error(`Clear memory failed: ${res.statusText}`)
  return res.json()
}
