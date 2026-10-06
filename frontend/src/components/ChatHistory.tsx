// ChatHistory — the scrolling transcript of one chat session.
// Ported from raggles minus the playground extras (FeedbackButtons,
// RetrievalScoreChart, per-stage TokenUsageBar, context-token meter).
// Their replacement: a single per-message token chip showing the turn's
// whole-turn total ("1,842 tok").
import { useEffect, useRef } from 'react'
import type { ChatMessage, Citation } from '../types'
import CitedResponse from './CitedResponse'
import ConfidenceBadge from './ConfidenceBadge'

interface Props {
  messages: ChatMessage[]
  onCitationClick: (citation: Citation) => void
  loading: boolean
}

export default function ChatHistory({ messages, onCitationClick, loading }: Props) {
  // Anchor element scrolled into view whenever the transcript grows.
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // Empty session: a gentle prompt instead of an empty scroll area.
  if (messages.length === 0 && !loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-theme-tertiary text-sm">
        Start a conversation by asking a question about your documents.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
      {messages.map((msg, i) => (
        <div key={i}>
          {msg.role === 'user' ? (
            // User bubble, right-aligned.
            <div className="flex justify-end">
              <div className="glass-accent text-white px-4 py-2.5 rounded-2xl rounded-br-md max-w-[75%] text-sm whitespace-pre-wrap">
                {msg.content}
              </div>
            </div>
          ) : (
            // Assistant answer with citations + status row.
            <div className="max-w-[85%]">
              {msg.response && (
                <>
                  {/* Collapsible pre-pass rewrite, when it differs and isn't turn 1. */}
                  {msg.response.rewritten_query !== msg.content && msg.response.turn_number > 1 && (
                    <details className="mb-1">
                      <summary className="text-xs text-theme-tertiary cursor-pointer hover:text-theme-secondary">
                        Rewritten query
                      </summary>
                      <p className="text-xs text-theme-tertiary mt-0.5 pl-3 border-l border-theme-main">
                        {msg.response.rewritten_query}
                      </p>
                    </details>
                  )}
                  {/* The cited answer body. */}
                  <CitedResponse
                    response={msg.response}
                    onCitationClick={onCitationClick}
                    memoryEnabled={msg.response.memory_enabled ?? true}
                  />
                  {/* Status row: confidence, response time, token chip. */}
                  <div className="mt-2 flex items-center gap-3 flex-wrap">
                    <ConfidenceBadge
                      score={msg.response.confidence_score}
                      report={msg.response.confidence_report}
                      loading={msg.memoryLoading ?? false}
                    />
                    {msg.response.response_time_ms != null && (
                      <span className="text-xs text-theme-tertiary">
                        {(msg.response.response_time_ms / 1000).toFixed(1)}s
                      </span>
                    )}
                    {/* THE simple token usage score: whole-turn total. */}
                    {msg.response.prompt_tokens != null && (
                      <span
                        className="text-xs text-theme-tertiary font-mono px-1.5 py-0.5 rounded-md bg-[var(--bg-surface)] border border-theme-subtle"
                        title={`Prompt: ${msg.response.prompt_tokens ?? 0} / Completion: ${msg.response.completion_tokens ?? 0}`}
                      >
                        {((msg.response.prompt_tokens ?? 0) + (msg.response.completion_tokens ?? 0)).toLocaleString()} tok
                      </span>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      ))}

      {/* Thinking indicator while the answer frame is pending. */}
      {loading && messages[messages.length - 1]?.role === 'user' && (
        <div className="max-w-[85%]">
          <div className="glass rounded-2xl p-6">
            <div className="flex items-center gap-2 text-theme-secondary text-sm">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Thinking...
            </div>
          </div>
        </div>
      )}

      {/* Scroll anchor. */}
      <div ref={bottomRef} />
    </div>
  )
}
