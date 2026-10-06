// CitedResponse — renders an assistant answer with inline citation pills.
// Ported from raggles with one simplification: the agentic/CRAG pipeline
// dots are gone (those features aren't in ragline); the RAG / library /
// knowledge-graph dots remain.
//
// Rendering rules (verbatim raggles behavior — do not alter):
//  * each span's text renders followed by superscript pill buttons,
//  * pill color is keyed per DISPLAY CITATION NUMBER via an 8-color palette
//    — the SAME (n-1) % 8 formula CitationSidebar uses, so a citation's
//    color matches across inline dot, sources chip, and sidebar,
//  * display numbers are renumbered 1,2,3… in order of first appearance,
//    regardless of the backend's internal citation ids.
import type { ChatResponse, Citation } from '../types'

// Per-document color palette (light + dark variants baked into each entry).
const COLORS = [
  'bg-cyan-400/15 text-cyan-700 dark:text-cyan-300 hover:bg-cyan-400/25',
  'bg-emerald-400/15 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-400/25',
  'bg-violet-400/15 text-violet-700 dark:text-violet-300 hover:bg-violet-400/25',
  'bg-amber-400/15 text-amber-700 dark:text-amber-300 hover:bg-amber-400/25',
  'bg-pink-400/15 text-pink-700 dark:text-pink-300 hover:bg-pink-400/25',
  'bg-teal-400/15 text-teal-700 dark:text-teal-300 hover:bg-teal-400/25',
  'bg-yellow-400/15 text-yellow-700 dark:text-yellow-300 hover:bg-yellow-400/25',
  'bg-rose-400/15 text-rose-700 dark:text-rose-300 hover:bg-rose-400/25',
]

interface Props {
  response: ChatResponse
  onCitationClick: (citation: Citation) => void
  memoryEnabled?: boolean
}

export default function CitedResponse({ response, onCitationClick, memoryEnabled = true }: Props) {
  // Color is derived from the display citation number with the same formula
  // the sidebar uses — one source of truth, three matching surfaces.
  const colorForDisplayId = (displayId: number) => COLORS[(displayId - 1) % COLORS.length]

  // Normalize spans: dedupe ids within a span, and merge empty-text marker
  // spans (produced by adjacent [Source 1][Source 2] markers) into the
  // previous text span so pills sit after the text they belong to.
  const normalizedSpans = response.spans.reduce<Array<{ text: string; citation_ids: number[] }>>(
    (acc, span) => {
      const dedupedIds = [...new Set(span.citation_ids)]
      const text = span.text ?? ''
      const isEmptyText = text.trim().length === 0

      // First span always starts the list.
      if (acc.length === 0) {
        acc.push({ text, citation_ids: dedupedIds })
        return acc
      }

      // Empty marker span: fold its ids into the previous span.
      if (isEmptyText) {
        const prev = acc[acc.length - 1]
        prev.citation_ids = [...new Set([...prev.citation_ids, ...dedupedIds])]
        return acc
      }

      acc.push({ text, citation_ids: dedupedIds })
      return acc
    },
    [],
  )

  // Build the display renumbering: ids in order of first appearance in the
  // answer, then any remaining sources, mapped to 1,2,3…
  const usedCitationOrder: number[] = []
  const seenCitationIds = new Set<number>()
  normalizedSpans.forEach((span) => {
    span.citation_ids.forEach((id) => {
      if (!seenCitationIds.has(id)) {
        seenCitationIds.add(id)
        usedCitationOrder.push(id)
      }
    })
  })
  response.sources.forEach((source) => {
    if (!seenCitationIds.has(source.citation_id)) {
      seenCitationIds.add(source.citation_id)
      usedCitationOrder.push(source.citation_id)
    }
  })
  const displayIdByCitationId = new Map<number, number>()
  usedCitationOrder.forEach((id, idx) => displayIdByCitationId.set(id, idx + 1))

  // Lookup helpers used by both the inline pills and the sources footer.
  const getCitation = (id: number) => response.sources.find((s) => s.citation_id === id)
  const getDisplayCitationId = (id: number) => displayIdByCitationId.get(id) ?? id

  return (
    <div
      className="glass rounded-2xl p-6 relative"
      // Accent edge marks memory-on turns, matching raggles' visual cue.
      style={memoryEnabled ? { borderLeft: '2px solid var(--accent)', borderBottom: '2px solid var(--accent)' } : undefined}
    >
      {/* Pipeline dots (top-right): which subsystems produced this answer. */}
      <div className="absolute top-2 right-2 flex gap-1.5 items-center">
        {(response.used_rag ?? true) && (
          <span
            className="w-2.5 h-2.5 rounded-full bg-cyan-400 shadow-sm shadow-cyan-400/50"
            title="RAG search"
          />
        )}
        {response.used_library && (
          <span
            className="w-2.5 h-2.5 rounded-full bg-amber-400 shadow-sm shadow-amber-400/50"
            title="Library overview"
          />
        )}
        {response.used_graph && (
          <span
            className="w-2.5 h-2.5 rounded-full bg-green-400 shadow-sm shadow-green-400/50"
            title="Knowledge graph"
          />
        )}
      </div>

      {/* The answer body: spans with inline citation pills. */}
      <div className="prose prose-sm dark:prose-invert max-w-none">
        {normalizedSpans.length > 0 ? (
          normalizedSpans.map((span, i) => (
            <span key={i}>
              {span.text}
              {span.citation_ids.map((id, j) => {
                const citation = getCitation(id)
                // Ids without a matching source render nothing (defensive).
                if (!citation) return null
                const displayId = getDisplayCitationId(id)
                return (
                  <button
                    key={`${i}-${j}-${id}`}
                    // Pass the display number along so the sidebar shows it.
                    onClick={() => onCitationClick({ ...citation, display_citation_id: displayId })}
                    className={`inline-flex items-center justify-center w-5 h-5 text-xs font-bold rounded-full cursor-pointer mx-0.5 align-super transition-all ${colorForDisplayId(displayId)}`}
                    title={`${citation.source_file}${citation.page_number ? `, p.${citation.page_number}` : ''}`}
                  >
                    {displayId}
                  </button>
                )
              })}
            </span>
          ))
        ) : (
          // No spans at all (e.g. library answers): plain text fallback.
          <p className="whitespace-pre-wrap">{response.answer}</p>
        )}
      </div>

      {/* Sources footer: one chip per deduplicated source, display order. */}
      {response.sources.length > 0 && (
        <div className="mt-4 pt-4 border-t border-theme-main">
          <h4 className="text-xs font-semibold text-theme-tertiary uppercase mb-2">Sources</h4>
          <div className="flex flex-wrap gap-2">
            {[...response.sources]
              .sort(
                (a, b) =>
                  getDisplayCitationId(a.citation_id) - getDisplayCitationId(b.citation_id),
              )
              .map((source) => {
              const displayId = getDisplayCitationId(source.citation_id)
              return (
                <button
                  key={source.citation_id}
                  onClick={() => onCitationClick({ ...source, display_citation_id: displayId })}
                  className={`text-xs px-2.5 py-1 rounded-full transition-all ${colorForDisplayId(displayId)}`}
                >
                  [{displayId}] {source.source_file}
                  {source.page_number ? ` p.${source.page_number}` : ''}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
