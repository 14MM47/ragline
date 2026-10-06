// DocumentList — the Documents tab's main table, with live batch progress.
// Ported from raggles with:
//  * a NEW "Original path" column (truncated, tooltip, copy button),
//  * a version badge for re-uploaded documents (v2, v3, ...),
//  * the enrichment dot and enriching/vision stage bands dropped
//    (features not in ragline).
// NEW poll diet: while a batch runs, a LIGHT status poll (counters + the
// per-stage counts, no document rows) fires every 1.5s and drives the
// progress card, while the FULL status + document-table refresh only fires
// every ~10s and drives the per-row stage pills. The card also shows a
// per-stage strip and a client-side throughput/ETA readout.
// NEW explorer view: a "Folders | List" toggle (persisted) swaps the flat
// table for DocumentTree, which groups the same rows by upload source and
// sub-folder. Row pieces shared by both views live in DocumentRowParts.
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  listDocuments, deleteDocument, retryDocument, getBatchStatus, listBatches,
  getExplorer, createFolder, deleteFolder, moveDocument, unmoveDocument,
} from '../api'
import type { Document, BatchStatus, Layout, FolderRef } from '../types'
import DocumentTree from './DocumentTree'
import type { LayoutActions } from './DocumentTree'
import { CopyPathButton, DocActions, StatusPill, VersionBadge } from './DocumentRowParts'

type StageBand = { start: number; end: number }

// Stage-relative progress bands: the fraction of per-document completion
// each ingestion stage covers (0.0..1.0). A doc mid-stage is credited its
// band's midpoint when computing the overall batch bar.
const STAGE_BANDS: Record<string, StageBand> = {
  processing: { start: 0.0, end: 0.08 },
  parsing: { start: 0.08, end: 0.34 },
  chunking: { start: 0.34, end: 0.5 },
  embedding: { start: 0.5, end: 0.78 },
  storing: { start: 0.78, end: 0.88 },
  extracting_graph: { start: 0.88, end: 0.995 },
}

// Display order + text color for the per-stage strip in the progress card
// (text colors match the stage palette in DocumentRowParts.STATUS_COLORS).
const STAGE_STRIP: Array<{ key: string; label: string; color: string }> = [
  { key: 'parsing', label: 'parsing', color: 'text-amber-300' },
  { key: 'chunking', label: 'chunking', color: 'text-teal-300' },
  { key: 'embedding', label: 'embedding', color: 'text-violet-300' },
  { key: 'storing', label: 'storing', color: 'text-cyan-300' },
  { key: 'extracting_graph', label: 'graph', color: 'text-fuchsia-300' },
]

// Poll cadences while a batch is active.
const LIGHT_POLL_MS = 1500 // counters + stages only (cheap on large batches)
const HEAVY_POLL_MS = 10_000 // full batch status + document table

// Rolling sample window for the client-side throughput/ETA readout.
const THROUGHPUT_WINDOW_MS = 5 * 60_000

// One throughput sample: poll time + files finished at that moment.
type ThroughputSample = { t: number; done: number }

// "45s" / "3m 20s" / "1h 12m" from a seconds count.
function formatEta(sec: number): string {
  const s = Math.max(0, Math.round(sec))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

// Which view the tab shows; persisted so it survives reloads.
type ViewMode = 'tree' | 'list'
const VIEW_KEY = 'ragline_doc_view'
function loadView(): ViewMode {
  try {
    return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'tree'
  } catch {
    return 'tree'
  }
}

// Sort: in-progress first, then ready/error/skipped, newest first within.
function sortDocs(docs: Document[]): Document[] {
  const order: Record<string, number> = { processing: 0, pending: 1, ready: 2, error: 3, skipped_duplicate: 4 }
  return [...docs].sort((a, b) => {
    const oa = order[a.status] ?? 5
    const ob = order[b.status] ?? 5
    if (oa !== ob) return oa - ob
    return new Date(b.upload_date).getTime() - new Date(a.upload_date).getTime()
  })
}

interface Props {
  activeBatchId: string | null
  onBatchComplete?: () => void
  // Retrieval scope (ticked document ids; empty = whole corpus) + its setter.
  scope: Set<string>
  onScopeChange: (next: Set<string>) => void
}

export default function DocumentList({ activeBatchId, onBatchComplete, scope, onScopeChange }: Props) {
  const [docs, setDocs] = useState<Document[]>([])
  // Shared explorer layout (user folders + moved documents) for the tree view.
  const [layout, setLayout] = useState<Layout>({ folders: [], placements: [] })
  const [loading, setLoading] = useState(true)
  const [batch, setBatch] = useState<BatchStatus | null>(null)
  const completeFired = useRef(false)
  // Rolling finished-count samples driving the throughput/ETA readout.
  const samplesRef = useRef<ThroughputSample[]>([])
  // Documents with a retry request in flight. Tracked separately from the
  // document's status so a failed retry can never leave a fabricated
  // "pending" spinner behind — the pill keeps showing the server's truth.
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set())
  // Last failed row action, shown inline. Deliberately not alert(): alert
  // blocks the JS thread, so the follow-up refresh could not run until the
  // dialog was dismissed, stretching a transient failure into a stuck row.
  const [actionError, setActionError] = useState<string | null>(null)
  // Folder explorer (default) or the flat table.
  const [view, setView] = useState<ViewMode>(loadView)
  const changeView = (v: ViewMode) => {
    setView(v)
    try { localStorage.setItem(VIEW_KEY, v) } catch { /* quota / private mode */ }
  }

  // Reload the document table and the explorer layout in ONE request (the
  // combined endpoint does a single scan + ACL lookup for both). If that
  // endpoint is missing (older API) fall back to the plain listing so the
  // documents still show, with the tree in its derived shape.
  const refresh = useCallback(async () => {
    try {
      const { documents, layout: lay } = await getExplorer()
      setDocs(documents)
      setLayout(lay)
    } catch {
      try {
        setDocs(await listDocuments())
      } catch {
        // Keep the old list on failure.
      }
    } finally {
      setLoading(false)
    }
  }, [])

  // Prune the scope of documents that no longer exist (deleted elsewhere,
  // another browser's stale selection). Only once rows have loaded — an
  // empty list on a failed fetch must not wipe the user's selection.
  useEffect(() => {
    if (!docs.length) return
    const ids = new Set(docs.map((d) => d.id))
    if ([...scope].some((id) => !ids.has(id))) {
      onScopeChange(new Set([...scope].filter((id) => ids.has(id))))
    }
  }, [docs, scope, onScopeChange])

  // Tick/untick one document or a whole set at once.
  const setSelected = (ids: string[], selected: boolean) => {
    const next = new Set(scope)
    for (const id of ids) selected ? next.add(id) : next.delete(id)
    onScopeChange(next)
  }

  // Explorer edits: call the server, surface a failure inline, re-fetch.
  const layoutActions: LayoutActions = {
    createFolder: (ref: FolderRef) => runLayoutEdit(() => createFolder(ref)),
    deleteFolder: (ref: FolderRef) => runLayoutEdit(() => deleteFolder(ref)),
    move: (id: string, ref: FolderRef) => runLayoutEdit(() => moveDocument(id, ref)),
    unmove: (id: string) => runLayoutEdit(() => unmoveDocument(id)),
  }
  async function runLayoutEdit(edit: () => Promise<unknown>): Promise<void> {
    setActionError(null)
    try {
      await edit()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Layout change failed')
    } finally {
      // Server truth wins either way (the layout is shared, so another
      // user's edits arrive with the same refresh).
      await refresh()
    }
  }

  // The batch ID to poll — passed from an upload, or discovered on mount.
  const [effectiveBatchId, setEffectiveBatchId] = useState<string | null>(activeBatchId)

  // Sync when the parent passes a new batch ID.
  useEffect(() => {
    if (activeBatchId) setEffectiveBatchId(activeBatchId)
  }, [activeBatchId])

  // Initial load + discover any in-progress batch (page reload case).
  useEffect(() => {
    refresh()
    if (!activeBatchId) {
      listBatches().then((batches) => {
        const active = batches.find((b) => b.status === 'pending' || b.status === 'processing')
        if (active) setEffectiveBatchId(active.id)
      }).catch(() => {})
    }
  }, [refresh, activeBatchId])

  // Dual-cadence polling while a batch is active: light every 1.5s, heavy
  // (full status + document table) every ~10s.
  useEffect(() => {
    if (!effectiveBatchId) {
      setBatch(null)
      completeFired.current = false
      samplesRef.current = []
      return
    }

    // Ignore in-flight responses after cleanup (batch switch/completion).
    let cancelled = false
    let lightTimer: ReturnType<typeof setInterval> | undefined
    let heavyTimer: ReturnType<typeof setInterval> | undefined
    const stopPolling = () => {
      if (lightTimer !== undefined) clearInterval(lightTimer)
      if (heavyTimer !== undefined) clearInterval(heavyTimer)
    }

    // New batch to watch — start the throughput window fresh.
    samplesRef.current = []

    // LIGHT poll: counters + stages only. `documents` comes back [] on this
    // variant, so keep whatever rows the last heavy poll already gave us.
    const lightPoll = async () => {
      try {
        const status = await getBatchStatus(effectiveBatchId, false)
        if (cancelled) return
        setBatch((prev) =>
          prev && prev.id === status.id ? { ...status, documents: prev.documents } : status,
        )

        // Record a throughput sample, pruning ones outside the window.
        const done = status.completed_files + status.failed_files + status.skipped_files
        const now = Date.now()
        samplesRef.current = [...samplesRef.current, { t: now, done }]
          .filter((s) => now - s.t <= THROUGHPUT_WINDOW_MS)

        // Fire completion exactly once, then stop polling.
        if (
          (status.status === 'completed' || status.status === 'completed_with_errors') &&
          !completeFired.current
        ) {
          completeFired.current = true
          stopPolling()
          // Final table refresh so the last ready/error states show now
          // instead of waiting for the next 10s heavy cycle.
          await refresh()
          setEffectiveBatchId(null)
          onBatchComplete?.()
        }
      } catch {
        // Transient poll failures are ignored.
      }
    }

    // HEAVY poll: full batch status (per-document rows) + the documents
    // table — this is what refreshes the per-row stage pills.
    const heavyPoll = async () => {
      try {
        const [status] = await Promise.all([
          getBatchStatus(effectiveBatchId, true),
          refresh(),
        ])
        if (cancelled) return
        setBatch(status)
      } catch {
        // Transient poll failures are ignored.
      }
    }

    // Kick both off immediately, then settle into their cadences.
    lightPoll()
    heavyPoll()
    lightTimer = setInterval(lightPoll, LIGHT_POLL_MS)
    heavyTimer = setInterval(heavyPoll, HEAVY_POLL_MS)
    return () => { cancelled = true; stopPolling() }
  }, [effectiveBatchId, onBatchComplete, refresh])

  const batchFinished = batch?.status === 'completed' || batch?.status === 'completed_with_errors'
  const batchActive = batch != null && !batchFinished

  // Batch-level progress: finished files count fully; each in-flight doc is
  // credited the midpoint of its current stage band, using the live per-
  // stage counts the light poll refreshes every 1.5s.
  const batchPct = batch ? (() => {
    const total = batch.total_files
    if (total === 0) return 0
    const done = batch.completed_files + batch.failed_files + batch.skipped_files
    if (done >= total) return 100
    let sum = done
    for (const [stage, count] of Object.entries(batch.stages ?? {})) {
      const band = STAGE_BANDS[stage] ?? STAGE_BANDS.processing
      sum += count * ((band.start + band.end) / 2)
    }
    // Cap at 99 until the batch is actually finished.
    return Math.min(Math.round((sum / total) * 100), 99)
  })() : null

  // Files/sec over the rolling window — null until 2+ samples have landed
  // (the UI shows "— computing" in that state).
  const throughput = (() => {
    if (!batchActive) return null
    const samples = samplesRef.current
    if (samples.length < 2) return null
    const first = samples[0]
    const last = samples[samples.length - 1]
    const dtSec = (last.t - first.t) / 1000
    if (dtSec <= 0) return null
    return (last.done - first.done) / dtSec
  })()

  // Seconds until the remaining files drain at the current rate (null when
  // the rate is unknown or zero — nothing finished inside the window yet).
  const etaSec = (() => {
    if (throughput === null || throughput <= 0 || !batch) return null
    const remaining = batch.total_files - (batch.completed_files + batch.failed_files + batch.skipped_files)
    return remaining / throughput
  })()

  // Optimistic delete with rollback-by-refresh on failure.
  const handleDelete = async (id: string) => {
    if (!confirm('Delete this document and all its chunks?')) return
    setDocs(prev => prev.filter(d => d.id !== id))
    setActionError(null)
    try {
      await deleteDocument(id)
    } catch (err) {
      // Say so rather than letting the row silently reappear on refresh.
      setActionError(err instanceof Error ? err.message : 'Delete failed')
      refresh()
    }
  }

  // Delete skipped-duplicate marker rows (no chunks, no vectors — only the
  // stored copy and the row go). One confirm for the lot; the ingested
  // copies they duplicate are untouched. Sequential: each is its own request.
  const handleDeleteSkipped = async (ids: string[]) => {
    if (!ids.length) return
    const what = ids.length === 1 ? 'this skipped duplicate record' : `these ${ids.length} skipped duplicate records`
    if (!confirm(`Delete ${what}? The ingested copies are kept.`)) return
    setActionError(null)
    const failed: string[] = []
    for (const id of ids) {
      try {
        await deleteDocument(id)
      } catch (err) {
        failed.push(err instanceof Error ? err.message : 'Delete failed')
      }
    }
    if (failed.length) setActionError(`${failed.length} of ${ids.length} deletes failed: ${failed[0]}`)
    await refresh()
  }

  // Re-ingest a failed document. Shown as 'pending' immediately so the row
  // moves out of the error group at once; the poll then tracks the real
  // stages. A rejected retry (pod down, wrong status) surfaces its message.
  const handleRetry = async (id: string) => {
    // Mark in-flight (disables the button, spins it) WITHOUT touching status.
    setRetryingIds(prev => new Set(prev).add(id))
    setActionError(null)
    try {
      await retryDocument(id)
      // Only now — once the server has actually queued it — does the row
      // become pending. The poll takes over from here.
      setDocs(prev => prev.map(d => (d.id === id ? { ...d, status: 'pending', stage: '' } : d)))
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Retry failed')
    } finally {
      setRetryingIds(prev => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      // Server truth always wins, whichever way the request went.
      refresh()
    }
  }

  if (loading) return <p className="text-theme-tertiary text-sm">Loading documents...</p>
  // Keep the progress card visible even before the first rows land — a
  // server-folder ingest can start against an empty table.
  if (!docs.length && !batchActive) return <p className="text-theme-tertiary text-sm">No documents uploaded yet.</p>

  const sorted = sortDocs(docs)

  return (
    <div className="space-y-3">
      {/* Inline failure notice for a row action (retry/delete). Non-blocking,
          and dismissable — a modal alert() here used to freeze the refresh. */}
      {actionError && (
        <div className="glass rounded-2xl p-3 border border-rose-400/30 flex items-start justify-between gap-3">
          <span className="text-sm text-rose-300">{actionError}</span>
          <button
            onClick={() => setActionError(null)}
            className="text-rose-300/70 hover:text-rose-200 text-xs shrink-0 transition-colors"
            title="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      {/* Overall batch progress card while ingestion runs. */}
      {batchActive && (
        <div className="glass rounded-2xl p-4 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-theme-primary">Ingesting batch...</span>
            <span className="text-theme-secondary">{Math.round(batchPct ?? 0)}%</span>
          </div>
          <div className="w-full bg-[var(--bg-surface)] rounded-full h-2.5 border border-theme-subtle">
            <div
              className="h-2.5 rounded-full transition-all duration-500 bg-gradient-to-r from-cyan-500 to-teal-400"
              style={{ width: `${batchPct ?? 0}%` }}
            />
          </div>

          {/* Per-stage strip: outcome counters | live in-flight stage counts
              (from the NEW `stages` field, fresh on every light poll). */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-mono">
            <span className="text-emerald-300">done {batch!.completed_files}</span>
            <span className="text-theme-tertiary select-none">&middot;</span>
            <span className="text-rose-300">failed {batch!.failed_files}</span>
            <span className="text-theme-tertiary select-none">&middot;</span>
            <span className="text-amber-300">skipped {batch!.skipped_files}</span>
            <span className="text-theme-tertiary select-none">|</span>
            {STAGE_STRIP.map(({ key, label, color }, i) => (
              <span key={key} className="flex items-center gap-x-2">
                {i > 0 && <span className="text-theme-tertiary select-none">&middot;</span>}
                <span className={color}>{label} {batch!.stages?.[key] ?? 0}</span>
              </span>
            ))}
          </div>

          {/* Files counter + client-side throughput/ETA readout. */}
          <div className="flex items-center justify-between text-xs text-theme-tertiary">
            <span>
              {batch!.completed_files + batch!.failed_files + batch!.skipped_files} / {batch!.total_files} files
            </span>
            <span className="font-mono">
              {throughput === null
                ? '— computing'
                : `${(throughput * 60).toFixed(1)} files/min${etaSec !== null ? ` · ETA ${formatEta(etaSec)}` : ''}`}
            </span>
          </div>
        </div>
      )}

      {/* View toggle: folder explorer or the flat table. */}
      {sorted.length > 0 && (
        <div className="flex items-center justify-between text-xs text-theme-tertiary px-1">
          <span className="flex items-center gap-3">
            <span>{sorted.length} {sorted.length === 1 ? 'document' : 'documents'}</span>
            {/* Retrieval scope readout + controls (empty = whole corpus). */}
            {scope.size > 0 ? (
              <>
                <span className="text-[var(--accent)]">{scope.size} selected for retrieval</span>
                <button onClick={() => onScopeChange(new Set())} className="text-rose-400 hover:text-rose-300 transition-colors">
                  Clear selection
                </button>
              </>
            ) : (
              <span className="opacity-70">no selection — retrieval searches everything</span>
            )}
            <button onClick={() => setSelected(docs.map((d) => d.id), true)} className="hover:text-theme-primary transition-colors">
              Select all
            </button>
          </span>
          <div className="flex items-center gap-1">
            <ViewButton active={view === 'tree'} onClick={() => changeView('tree')}>Folders</ViewButton>
            <ViewButton active={view === 'list'} onClick={() => changeView('list')}>List</ViewButton>
          </div>
        </div>
      )}

      {/* Folder explorer: the same rows grouped by upload source. */}
      {sorted.length > 0 && view === 'tree' && (
        <DocumentTree
          docs={docs}
          layout={layout}
          onDelete={handleDelete}
          onRetry={handleRetry}
          retryingIds={retryingIds}
          actions={layoutActions}
          scope={scope}
          onSelect={setSelected}
          onDeleteSkipped={handleDeleteSkipped}
        />
      )}

      {/* The documents table. overflow-x-auto, not overflow-hidden: clipping
          silently ate the back half of the action buttons rather than letting
          the row scroll. */}
      {sorted.length > 0 && view === 'list' && (
        <div className="glass rounded-2xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-theme-main">
                <th className="pl-4 py-3 w-px"></th>
                <th className="px-4 py-3 text-left font-medium text-theme-secondary">Filename</th>
                <th className="px-4 py-3 text-left font-medium text-theme-secondary">Type</th>
                <th className="px-4 py-3 text-left font-medium text-theme-secondary">Pages</th>
                <th className="px-4 py-3 text-left font-medium text-theme-secondary">Chunks</th>
                <th className="px-4 py-3 text-left font-medium text-theme-secondary">Original path</th>
                <th className="px-4 py-3 text-left font-medium text-theme-secondary">Status</th>
                <th className="px-4 py-3 text-left font-medium text-theme-secondary">Uploaded</th>
                {/* w-px + nowrap sizes the actions column to its content, so
                    Retry and Delete can never be squeezed by the wider cells. */}
                <th className="px-4 py-3 w-px whitespace-nowrap"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-subtle)]">
              {sorted.map((doc) => (
                <DocRow
                  key={doc.id}
                  doc={doc}
                  onDelete={handleDelete}
                  onRetry={handleRetry}
                  retrying={retryingIds.has(doc.id)}
                  selected={scope.has(doc.id)}
                  onSelect={(v) => setSelected([doc.id], v)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** Small pill button for the Folders | List toggle. */
function ViewButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-1 rounded-md transition-colors ${active ? 'glass-accent text-white' : 'hover:text-theme-primary hover:bg-[var(--bg-surface)]'}`}
    >
      {children}
    </button>
  )
}

/** Per-document row of the flat table: stage badge, original path with copy. */
function DocRow({ doc, onDelete, onRetry, retrying, selected, onSelect }: {
  doc: Document
  onDelete: (id: string) => void
  onRetry: (id: string) => void
  // True while this row's retry request is in flight — drives the button
  // only, never the status pill (the pill must stay the server's truth).
  retrying: boolean
  // Retrieval-scope tick.
  selected: boolean
  onSelect: (selected: boolean) => void
}) {
  return (
    <tr className="hover:bg-[var(--bg-surface)] transition-colors">
      <td className="pl-4 py-3 w-px">
        <input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} title="Include in retrieval" />
      </td>
      <td className="px-4 py-3 font-medium text-theme-primary min-w-0">
        <span className="flex items-center gap-2">
          <span className="break-all">{doc.filename}</span>
          <VersionBadge version={doc.version} />
        </span>
      </td>
      <td className="px-4 py-3 text-theme-secondary uppercase">{doc.file_type}</td>
      <td className="px-4 py-3 text-theme-secondary">{doc.page_count}</td>
      <td className="px-4 py-3 text-theme-secondary">{doc.chunk_count}</td>
      {/* NEW: original network path — truncated with tooltip + copy. */}
      <td className="px-4 py-3 text-theme-secondary">
        {doc.original_path ? (
          <span className="flex items-center gap-1.5 max-w-[220px]">
            <code className="text-xs truncate" title={doc.original_path}>
              {doc.original_path}
            </code>
            <CopyPathButton path={doc.original_path} />
          </span>
        ) : (
          <span className="text-xs text-theme-tertiary opacity-50">—</span>
        )}
      </td>
      <td className="px-4 py-3"><StatusPill doc={doc} /></td>
      <td className="px-4 py-3 text-theme-secondary">{new Date(doc.upload_date).toLocaleDateString()}</td>
      <td className="px-4 py-3 w-px whitespace-nowrap">
        <DocActions doc={doc} onDelete={onDelete} onRetry={onRetry} retrying={retrying} />
      </td>
    </tr>
  )
}
