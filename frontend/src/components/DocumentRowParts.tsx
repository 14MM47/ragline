// DocumentRowParts — the small pieces a document row is made of, shared by
// the flat table (DocumentList) and the folder explorer (DocumentTree) so the
// two views render a document identically: status pill with spinner, version
// badge, copy-original-path button and the Retry/Delete actions.
// NEW in ragline (split out of DocumentList when the explorer view arrived).
import { useState } from 'react'
import type { Document } from '../types'

// Badge colors per status/stage.
export const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-400/15 text-gray-400',
  processing: 'bg-cyan-400/15 text-cyan-300',
  parsing: 'bg-amber-400/15 text-amber-300',
  chunking: 'bg-teal-400/15 text-teal-300',
  embedding: 'bg-violet-400/15 text-violet-300',
  storing: 'bg-cyan-400/15 text-cyan-300',
  extracting_graph: 'bg-fuchsia-400/15 text-fuchsia-300',
  ready: 'bg-emerald-400/15 text-emerald-300',
  error: 'bg-rose-400/15 text-rose-300',
  skipped_duplicate: 'bg-amber-400/15 text-amber-300',
}

// Last path segment of an upload-relative path ("plc/s7.pdf" -> "s7.pdf").
// Backslashes are tolerated for legacy rows.
export function basename(path: string): string {
  const parts = path.split(/[\\/]/)
  return parts[parts.length - 1] || path
}

/** Status pill: the live stage while processing, otherwise the status. */
export function StatusPill({ doc }: { doc: Document }) {
  const stage = doc.stage || ''
  const label = stage && doc.status === 'processing'
    ? stage.replace(/_/g, ' ')
    : doc.status.replace(/_/g, ' ')
  const colorKey = stage && doc.status === 'processing' ? stage : doc.status
  const isProcessing = doc.status === 'processing' || doc.status === 'pending'
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[colorKey] || 'bg-gray-400/15 text-gray-400'}`}
    >
      {/* Spinner while pending/processing. */}
      {isProcessing && (
        <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {label}
    </span>
  )
}

/** "v2", "v3"... badge for re-uploaded documents; nothing for version 1. */
export function VersionBadge({ version }: { version: number }) {
  if (version <= 1) return null
  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-sky-400/15 text-sky-300 font-mono shrink-0">
      v{version}
    </span>
  )
}

/** Copy-to-clipboard button for a network path, with brief tick feedback. */
export function CopyPathButton({ path, title = 'Copy network path' }: { path: string; title?: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(path)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard unavailable — ignore.
    }
  }
  return (
    <button
      onClick={copy}
      className="text-xs text-theme-tertiary hover:text-[var(--accent)] shrink-0 transition-colors"
      title={title}
    >
      {copied ? '✓' : '⧉'}
    </button>
  )
}

/** Retry (errored rows) + Delete (settled rows) actions for one document. */
export function DocActions({ doc, onDelete, onRetry, retrying }: {
  doc: Document
  onDelete: (id: string) => void
  onRetry: (id: string) => void
  // True while this row's retry request is in flight — drives the button
  // only, never the status pill (the pill must stay the server's truth).
  retrying: boolean
}) {
  return (
    <div className="flex items-center gap-2">
      {/* Retry re-parses the stored copy, so it also picks up parser fixes
          made since the failure. Errored rows only. Disabled while the
          request is in flight, which both shows progress and blocks a
          double-press queueing the same document twice. */}
      {doc.status === 'error' && (
        <button
          onClick={() => onRetry(doc.id)}
          disabled={retrying}
          className="text-cyan-400 hover:text-cyan-300 text-xs transition-colors disabled:opacity-50 disabled:cursor-wait"
        >
          {retrying ? 'Retrying…' : 'Retry'}
        </button>
      )}
      {/* Deletable once the worker is no longer touching the row. Without
          'error' and 'skipped_duplicate' here, failed rows are unremovable
          from the UI and have to be cleared by hand in SQL. */}
      {(doc.status === 'ready' || doc.status === 'error' || doc.status === 'skipped_duplicate') && (
        <button onClick={() => onDelete(doc.id)} className="text-rose-400 hover:text-rose-300 text-xs transition-colors">
          Delete
        </button>
      )}
    </div>
  )
}
