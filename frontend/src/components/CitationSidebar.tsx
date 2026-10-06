// CitationSidebar — detail panel for a clicked citation.
// Ported from raggles with two changes:
//  * the citation-flagging menu is removed (feedback feature dropped),
//  * NEW "Original location" row: the document's original network path in
//    monospace with a copy-to-clipboard button. Deliberately NOT a file://
//    hyperlink — browsers block those — so the user copies the path and
//    pastes it into File Explorer instead.
import { useState } from 'react'
import type { Citation } from '../types'

// Accent styling per display number (cycles through 8 colorways) so the
// sidebar's accents match the clicked pill's color family.
const ACCENT_COLORS = [
  { bg: 'bg-cyan-400/10', border: 'border-cyan-400/30', text: 'text-cyan-300', badge: 'bg-cyan-400/15 text-cyan-300', link: 'text-cyan-400 hover:text-cyan-300' },
  { bg: 'bg-emerald-400/10', border: 'border-emerald-400/30', text: 'text-emerald-300', badge: 'bg-emerald-400/15 text-emerald-300', link: 'text-emerald-400 hover:text-emerald-300' },
  { bg: 'bg-violet-400/10', border: 'border-violet-400/30', text: 'text-violet-300', badge: 'bg-violet-400/15 text-violet-300', link: 'text-violet-400 hover:text-violet-300' },
  { bg: 'bg-amber-400/10', border: 'border-amber-400/30', text: 'text-amber-300', badge: 'bg-amber-400/15 text-amber-300', link: 'text-amber-400 hover:text-amber-300' },
  { bg: 'bg-pink-400/10', border: 'border-pink-400/30', text: 'text-pink-300', badge: 'bg-pink-400/15 text-pink-300', link: 'text-pink-400 hover:text-pink-300' },
  { bg: 'bg-teal-400/10', border: 'border-teal-400/30', text: 'text-teal-300', badge: 'bg-teal-400/15 text-teal-300', link: 'text-teal-400 hover:text-teal-300' },
  { bg: 'bg-yellow-400/10', border: 'border-yellow-400/30', text: 'text-yellow-300', badge: 'bg-yellow-400/15 text-yellow-300', link: 'text-yellow-400 hover:text-yellow-300' },
  { bg: 'bg-rose-400/10', border: 'border-rose-400/30', text: 'text-rose-300', badge: 'bg-rose-400/15 text-rose-300', link: 'text-rose-400 hover:text-rose-300' },
]

interface Props {
  citation: Citation
  onClose: () => void
}

export default function CitationSidebar({ citation, onClose }: Props) {
  // The renumbered display id assigned by CitedResponse (fallback: raw id).
  const displayCitationId = citation.display_citation_id ?? citation.citation_id
  const accent = ACCENT_COLORS[(displayCitationId - 1) % ACCENT_COLORS.length]
  // Copy-feedback state for the original-path button.
  const [copied, setCopied] = useState(false)

  // Copy the original network path to the clipboard and flash confirmation.
  const handleCopyPath = async () => {
    try {
      await navigator.clipboard.writeText(citation.original_path)
      setCopied(true)
      // Reset the confirmation after a moment.
      setTimeout(() => setCopied(false), 2500)
    } catch {
      // Clipboard unavailable (http origin etc.) — silently ignore.
    }
  }

  return (
    <div className="w-80 glass-heavy rounded-2xl m-2 p-4 sticky top-8 max-h-[80vh] overflow-y-auto">
      {/* Header: numbered badge + close button. */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center justify-center w-6 h-6 text-xs font-bold rounded-full ${accent.badge}`}>
            {displayCitationId}
          </span>
          <h3 className={`text-sm font-bold ${accent.text}`}>Source</h3>
        </div>
        <button onClick={onClose} className="text-theme-tertiary hover:text-theme-secondary text-lg leading-none transition-colors">&times;</button>
      </div>

      <div className="space-y-3 text-sm">
        {/* Source filename. */}
        <div>
          <span className="text-theme-tertiary text-xs uppercase font-semibold">File</span>
          <p className="text-theme-primary font-medium">{citation.source_file}</p>
        </div>

        {/* Page number (exact — chunks never span pages). */}
        {citation.page_number && (
          <div>
            <span className="text-theme-tertiary text-xs uppercase font-semibold">Page</span>
            <p className={`font-medium ${accent.text}`}>{citation.page_number}</p>
          </div>
        )}

        {/* Section heading, when the cited page had one. */}
        {citation.section && (
          <div>
            <span className="text-theme-tertiary text-xs uppercase font-semibold">Section</span>
            <p className="text-theme-primary">{citation.section}</p>
          </div>
        )}

        {/* The cited chunk's text (first 500 chars, carried from ingestion). */}
        <div>
          <span className="text-theme-tertiary text-xs uppercase font-semibold">Quoted Text</span>
          <blockquote className={`mt-1 p-3 ${accent.bg} border-l-4 ${accent.border} text-theme-secondary text-xs leading-relaxed rounded-r-lg`}>
            {citation.quoted_text}
          </blockquote>
        </div>

        {/* "Open copy": the managed copy served by the backend; the #page
            fragment makes browser PDF viewers jump to the cited page.
            Rendered only when this user's NTFS access allows it — the flag is
            UX; the backend re-checks on the download itself. `accessible`
            defaults false so an unannotated payload renders locked. */}
        {citation.accessible ? (
          <a
            href={`/api/documents/${citation.document_id}/content#page=${citation.page_number ?? 1}`}
            target="_blank"
            rel="noopener noreferrer"
            className={`inline-block text-xs font-medium transition-colors ${accent.link}`}
          >
            Open copy{citation.page_number ? ` (p.${citation.page_number})` : ''}
          </a>
        ) : (
          <div className="flex items-start gap-1.5 text-xs text-theme-tertiary">
            {/* Lock glyph + explanation; filename above stays visible. */}
            <svg className="w-3.5 h-3.5 mt-px shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
            </svg>
            <span>Restricted — you don't have access to the source file.</span>
          </div>
        )}

        {/* Original network location — only when recorded AND accessible
            (the backend already blanks the path for restricted sources; the
            accessible check here keeps the UI honest if it ever doesn't). */}
        {citation.accessible && citation.original_path && (
          <div>
            <span className="text-theme-tertiary text-xs uppercase font-semibold">Original location</span>
            <div className="mt-1 flex items-start gap-1.5">
              {/* The path itself, monospace, wrapping on long UNC paths. */}
              <code className="flex-1 text-xs text-theme-secondary bg-[var(--bg-surface)] border border-theme-subtle rounded-md px-2 py-1.5 break-all">
                {citation.original_path}
              </code>
              {/* Copy-to-clipboard button. */}
              <button
                onClick={handleCopyPath}
                className={`shrink-0 px-2 py-1.5 text-xs rounded-md transition-colors ${accent.badge} hover:brightness-110`}
                title="Copy network path"
              >
                {copied ? '✓' : 'Copy'}
              </button>
            </div>
            {/* Confirmation subtext after copying. */}
            {copied && (
              <p className="mt-1 text-[11px] text-theme-tertiary">
                Network path copied — paste into File Explorer.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
