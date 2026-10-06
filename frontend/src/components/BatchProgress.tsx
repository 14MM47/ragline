// BatchProgress — standalone batch progress card (polls one batch id).
// Ported from raggles; the stage weight table matches ragline's actual
// ingestion stages (vision/enriching stages removed).
import { useState, useEffect, useRef } from 'react'
import { getBatchStatus } from '../api'
import type { BatchStatus } from '../types'

interface Props {
  batchId: string
  onComplete?: () => void
  onDismiss?: () => void
}

// Badge colors per document status.
const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-400/15 text-gray-400',
  processing: 'bg-cyan-400/15 text-cyan-300',
  ready: 'bg-emerald-400/15 text-emerald-300',
  error: 'bg-rose-400/15 text-rose-300',
  skipped_duplicate: 'bg-amber-400/15 text-amber-300',
}

// Rough completion fraction reached by the START of each stage.
const STAGE_WEIGHTS: Record<string, number> = {
  parsing: 0.15,
  chunking: 0.4,
  embedding: 0.65,
  storing: 0.85,
  extracting_graph: 0.92,
}

// Batch-level percentage: finished docs count fully, processing docs count
// their stage weight.
function computeProgress(batch: BatchStatus): number {
  const total = batch.total_files
  if (total === 0) return 0

  const done = batch.completed_files + batch.failed_files + batch.skipped_files
  if (done >= total) return 100

  let progress = done
  for (const doc of batch.documents) {
    if (doc.status === 'processing' && doc.stage) {
      progress += STAGE_WEIGHTS[doc.stage] ?? 0.1
    }
  }

  // Cap at 99 until the batch is actually finished.
  return Math.min(Math.round((progress / total) * 100), 99)
}

// Human-readable stage line for single-file batches.
function stageLabel(batch: BatchStatus): string {
  if (batch.total_files === 1 && batch.documents.length === 1) {
    const doc = batch.documents[0]
    if (doc.status === 'processing' && doc.stage) {
      const labels: Record<string, string> = {
        parsing: 'Parsing document...',
        chunking: 'Chunking text...',
        embedding: 'Generating embeddings...',
        storing: 'Storing vectors...',
        extracting_graph: 'Extracting knowledge graph...',
      }
      return labels[doc.stage] ?? 'Processing...'
    }
  }
  return ''
}

export default function BatchProgress({ batchId, onComplete, onDismiss }: Props) {
  const [batch, setBatch] = useState<BatchStatus | null>(null)
  const [error, setError] = useState('')
  // Guard so onComplete fires exactly once.
  const completeFired = useRef(false)

  // Poll the batch every second until it completes.
  useEffect(() => {
    let timer: ReturnType<typeof setInterval>

    const poll = async () => {
      try {
        const status = await getBatchStatus(batchId)
        setBatch(status)

        if (
          (status.status === 'completed' || status.status === 'completed_with_errors') &&
          !completeFired.current
        ) {
          completeFired.current = true
          clearInterval(timer)
          onComplete?.()
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch status')
      }
    }

    poll()
    timer = setInterval(poll, 1000)

    return () => clearInterval(timer)
  }, [batchId, onComplete])

  if (error) {
    return <p className="text-sm text-rose-400">{error}</p>
  }

  if (!batch) {
    return <p className="text-sm text-theme-tertiary">Loading batch status...</p>
  }

  const pct = computeProgress(batch)
  const isFinished = batch.status === 'completed' || batch.status === 'completed_with_errors'
  const done = batch.completed_files + batch.failed_files + batch.skipped_files
  const stage = stageLabel(batch)

  return (
    <div className="glass rounded-2xl p-4 space-y-3">
      {/* Title + optional dismiss once finished. */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-theme-primary">
          Batch Ingestion {isFinished ? '— Done' : '— Processing'}
        </h3>
        {isFinished && onDismiss && (
          <button
            onClick={onDismiss}
            className="text-xs text-theme-tertiary hover:text-theme-secondary transition-colors"
          >
            Dismiss
          </button>
        )}
      </div>

      {/* Progress bar (amber when some files failed). */}
      <div className="w-full bg-[var(--bg-surface)] rounded-full h-2.5 border border-theme-subtle">
        <div
          className={`h-2.5 rounded-full transition-all duration-500 ${
            batch.status === 'completed_with_errors' ? 'bg-amber-500' : 'bg-gradient-to-r from-cyan-500 to-teal-400'
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Stage line (single doc) or file counter (multi). */}
      <div className="flex justify-between text-xs text-theme-secondary">
        <span>{stage || `${done} / ${batch.total_files} files`}</span>
        <span>{pct}%</span>
      </div>

      {/* Per-document rows for multi-file batches. */}
      {batch.documents.length > 1 && (
        <div className="max-h-48 overflow-y-auto space-y-1">
          {batch.documents.map((doc) => {
            const label = doc.stage && doc.status === 'processing' ? doc.stage : doc.status.replace('_', ' ')
            const docPct =
              doc.status === 'ready' || doc.status === 'error' || doc.status === 'skipped_duplicate' ? 100
              : doc.status === 'processing' && doc.stage ? Math.round((STAGE_WEIGHTS[doc.stage] ?? 0.1) * 100)
              : 0

            return (
              <div key={doc.id} className="flex items-center justify-between text-xs py-1">
                {/* Relative path identifies files inside folder/ZIP uploads. */}
                <span className="text-theme-secondary truncate max-w-[60%]" title={doc.source_path || doc.filename}>
                  {doc.source_path || doc.filename}
                </span>
                <span
                  className={`relative px-2 py-0.5 rounded-full text-xs font-medium overflow-hidden ${STATUS_COLORS[doc.status] || 'bg-gray-400/15 text-gray-400'}`}
                >
                  {/* Partial fill behind the badge text shows stage progress. */}
                  {docPct < 100 && (
                    <span
                      className="absolute inset-0 bg-current opacity-[0.12] rounded-full"
                      style={{ clipPath: `inset(0 ${100 - docPct}% 0 0)` }}
                    />
                  )}
                  <span className="relative">{label}</span>
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Failure/skip summaries. */}
      {batch.failed_files > 0 && (
        <p className="text-xs text-rose-400">
          {batch.failed_files} file{batch.failed_files > 1 ? 's' : ''} failed
        </p>
      )}
      {batch.skipped_files > 0 && (
        <p className="text-xs text-amber-400">
          {batch.skipped_files} file{batch.skipped_files > 1 ? 's' : ''} skipped (duplicate)
        </p>
      )}
    </div>
  )
}
