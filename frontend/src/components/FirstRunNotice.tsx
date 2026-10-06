// FirstRunNotice — dismissible banner warning about the one-time reranker
// model download. Ported from raggles; env-var wording updated to ragline's
// RERANKER_PROVIDER setting. Dismissal persists in localStorage.
import { useState } from 'react'

// localStorage key remembering the dismissal across sessions.
const STORAGE_KEY = 'ragline_first_run_notice_dismissed'

export function FirstRunNotice() {
  // Initialize from storage so a dismissed banner never flashes.
  const [dismissed, setDismissed] = useState<boolean>(
    () => localStorage.getItem(STORAGE_KEY) === 'true',
  )

  if (dismissed) return null

  // Persist and hide.
  const dismiss = () => {
    localStorage.setItem(STORAGE_KEY, 'true')
    setDismissed(true)
  }

  return (
    <div className="px-4 py-2 border-b border-theme-main bg-[var(--bg-surface)] text-sm text-theme-secondary flex items-start gap-3">
      <span className="shrink-0 font-medium text-[var(--accent)]">Heads up:</span>
      <span className="flex-1">
        Your first query will download the reranker model{' '}
        <code className="font-mono text-xs">BAAI/bge-reranker-v2-m3</code>{' '}
        (~2&nbsp;GB) and may take a few minutes. To skip the download, set{' '}
        <code className="font-mono text-xs">RERANKER_PROVIDER=none</code> in
        your <code className="font-mono text-xs">.env</code>.
      </span>
      {/* Dismiss button (×). */}
      <button
        onClick={dismiss}
        className="shrink-0 text-theme-tertiary hover:text-theme-primary transition-colors leading-none text-lg"
        title="Dismiss"
        aria-label="Dismiss notice"
      >
        ×
      </button>
    </div>
  )
}
