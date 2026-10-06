// ConfidenceBadge — shows the post-answer confidence score as a colored pill.
// Ported verbatim from raggles. While passes 3-4 are still running it shows
// a spinner ("Updating memory..."); once the `complete` event lands it shows
// the score, expandable to reveal the evaluator's report.
import { useState } from 'react'

interface Props {
  score: number | null
  report: string | null
  loading: boolean
}

export default function ConfidenceBadge({ score, report, loading }: Props) {
  // Whether the report text under the pill is expanded.
  const [expanded, setExpanded] = useState(false)

  // Between the answer and complete SSE events: show progress.
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-theme-tertiary">
        <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Updating memory...
      </div>
    )
  }

  // Confidence disabled or unavailable: render nothing.
  if (score === null) return null

  // Traffic-light coloring: green >= 0.8, amber >= 0.5, red below.
  const color =
    score >= 0.8
      ? 'bg-emerald-400/15 text-emerald-700 dark:text-emerald-300'
      : score >= 0.5
        ? 'bg-amber-400/15 text-amber-700 dark:text-amber-300'
        : 'bg-rose-400/15 text-rose-700 dark:text-rose-300'

  return (
    <div>
      {/* The pill itself toggles the report. */}
      <button
        onClick={() => setExpanded(!expanded)}
        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium ${color} hover:brightness-110 transition-all`}
      >
        Confidence: {(score * 100).toFixed(0)}%
        <svg
          className={`w-3 h-3 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {/* The evaluator's one-line explanation, when expanded. */}
      {expanded && report && (
        <p className="mt-1 text-xs text-theme-secondary pl-2 border-l-2 border-theme-main">{report}</p>
      )}
    </div>
  )
}
