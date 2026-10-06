// SessionList — collapsible sidebar of past chat sessions.
// Ported verbatim from raggles: shows each session's summary, turn count,
// total token spend, age, and topic tags; supports selection and deletion.
import { useEffect, useState } from 'react'
import type { SessionSummary } from '../types'
import { listSessions, deleteSession } from '../api'

interface Props {
  currentSessionId: string
  onSelectSession: (sessionId: string) => void
  onNewChat: () => void
  open: boolean
}

// Compact relative timestamp for the session row ("3h ago").
function timeAgo(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diff = Math.floor((now - then) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export default function SessionList({ currentSessionId, onSelectSession, onNewChat, open }: Props) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])

  // Fetch the session list from the backend.
  const refresh = async () => {
    try {
      const data = await listSessions()
      setSessions(data)
    } catch {
      // A failed refresh just leaves the previous list in place.
    }
  }

  // Refresh whenever the sidebar opens or the active session changes.
  useEffect(() => {
    if (open) refresh()
  }, [open, currentSessionId])

  // Delete a session; if it was the active one, start a new chat.
  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation()
    try {
      await deleteSession(sessionId)
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId))
      if (sessionId === currentSessionId) {
        onNewChat()
      }
    } catch {
      // Deletion failure is non-fatal; the row stays.
    }
  }

  // Collapsed: render nothing at all.
  if (!open) return null

  return (
    <div className="w-64 glass-heavy border-r border-theme-main flex flex-col h-full overflow-hidden">
      {/* New-chat button pinned at the top. */}
      <div className="p-3 border-b border-theme-main">
        <button
          onClick={onNewChat}
          className="w-full px-3 py-2 glass-accent text-white text-sm font-medium rounded-xl hover:brightness-110 transition-all"
        >
          + New Chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <p className="text-xs text-theme-tertiary p-3">No sessions yet.</p>
        ) : (
          sessions.map((s) => (
            <div
              key={s.session_id}
              onClick={() => onSelectSession(s.session_id)}
              className={`group px-3 py-2.5 cursor-pointer border-b border-theme-subtle hover:bg-[var(--bg-surface)] transition-all ${
                s.session_id === currentSessionId ? 'bg-[var(--bg-surface)] border-l-2 border-l-cyan-400' : ''
              }`}
            >
              {/* Summary line + delete button. */}
              <div className="flex items-start justify-between gap-1">
                <p className="text-sm text-theme-secondary truncate flex-1">
                  {s.summary || `Session (${s.turn_count} turns)`}
                </p>
                <button
                  onClick={(e) => handleDelete(e, s.session_id)}
                  className="text-theme-tertiary hover:text-red-400 text-sm shrink-0 transition-colors"
                  title="Delete session"
                >
                  &times;
                </button>
              </div>
              {/* Stats row: turns, token spend, age. */}
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-theme-tertiary">{s.turn_count} turns</span>
                <span className="text-xs text-theme-tertiary">{(s.total_tokens ?? 0).toLocaleString()} tok</span>
                <span className="text-xs text-theme-tertiary opacity-60">{timeAgo(s.created_at)}</span>
              </div>
              {/* Up to three topic tags from the session memory. */}
              {s.topics.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {s.topics.slice(0, 3).map((t) => (
                    <span key={t} className="text-[10px] px-1.5 py-0.5 bg-[var(--bg-surface)] text-theme-tertiary rounded-full">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
