// App — the ragline shell: header + two tabs (Chat, Documents).
// Ported from raggles with the playground surface removed: no Traces/Admin
// tabs, no RAGControlsBar, no enrichment/eval panels, no per-stage token
// tracking. localStorage keys are ragline-prefixed.
// New: polls /health every 30s to drive the header service-status dots and
// the Documents tab's ingest guard (uploads blocked when embedder/LLM down).
import { useState, useEffect, useCallback, useRef } from 'react'
import ChatHistory from './components/ChatHistory'
import ChatInput from './components/ChatInput'
import SessionList from './components/SessionList'
import CitationSidebar from './components/CitationSidebar'
import DocumentUpload from './components/DocumentUpload'
import DocumentList from './components/DocumentList'
import { FirstRunNotice } from './components/FirstRunNotice'
import UserBadge from './components/UserBadge'
import { chatQuery, getSessionHistory, compactMemory, clearMemory, getHealth } from './api'
import type { ChatMessage, ChatResponse, Citation, ConfidenceUpdate, HealthStatus } from './types'

// Fresh client-side session ids.
function generateId(): string {
  return crypto.randomUUID()
}

// One backend-service dot for the header health strip.
// up: true = reachable (green), false = down (red), null = not applicable
// (grey — e.g. the reranker in local/none mode has nothing to probe).
function StatusDot({ label, up }: { label: string; up: boolean | null }) {
  const color = up === null ? 'bg-gray-500' : up ? 'bg-emerald-400' : 'bg-rose-500'
  const state = up === null ? 'n/a (local/none)' : up ? 'reachable' : 'DOWN'
  return (
    <span className="flex items-center gap-1" title={`${label}: ${state}`}>
      <span className={`w-2 h-2 rounded-full shrink-0 ${color}`} />
      <span className="text-[10px] text-theme-tertiary select-none">{label}</span>
    </span>
  )
}

export default function App() {
  // The chat transcript for the active session.
  const [messages, setMessages] = useState<ChatMessage[]>([])
  // Active session id, persisted so a reload resumes the conversation.
  const [sessionId, setSessionId] = useState<string>(() => {
    return localStorage.getItem('ragline_session_id') || generateId()
  })
  // The citation whose detail sidebar is open (null = closed).
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)
  // Which top-level tab is showing.
  const [activeTab, setActiveTab] = useState<'chat' | 'documents'>('chat')
  // True while a chat turn is in flight.
  const [loading, setLoading] = useState(false)
  // Session sidebar visibility.
  const [sidebarOpen, setSidebarOpen] = useState(false)
  // Batch id passed from DocumentUpload to DocumentList for progress polling.
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null)
  // Running whole-session token total (header counter).
  const [sessionTokens, setSessionTokens] = useState<number>(0)
  // Memory management dropdown state.
  const [memoryMenuOpen, setMemoryMenuOpen] = useState(false)
  // Wrapper around the button + menu, so a click can be tested for "outside".
  const memoryMenuRef = useRef<HTMLDivElement>(null)
  // THE memory toggle — per-session, persisted in localStorage.
  const [memoryEnabled, setMemoryEnabled] = useState<boolean>(() => {
    const stored = localStorage.getItem(`ragline_memory_${localStorage.getItem('ragline_session_id') || ''}`)
    return stored !== null ? stored === 'true' : true
  })
  // Dark/light theme, persisted.
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    return (localStorage.getItem('ragline_theme') as 'light' | 'dark') || 'dark'
  })
  // Latest /health snapshot (null until the first poll lands).
  const [health, setHealth] = useState<HealthStatus | null>(null)
  // Retrieval scope: document ids ticked in the Documents tab. Empty = the
  // whole corpus. Persisted so the scope survives reloads; pruned by the
  // Documents tab whenever a ticked document no longer exists.
  const [scope, setScope] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem('ragline_scope')
      return new Set(raw ? (JSON.parse(raw) as string[]) : [])
    } catch {
      return new Set()
    }
  })
  const handleScopeChange = useCallback((next: Set<string>) => {
    setScope(next)
    try { localStorage.setItem('ragline_scope', JSON.stringify([...next])) } catch { /* quota / private mode */ }
  }, [])

  // Poll backend service health for the header dots + the ingest guard.
  // The endpoint is cached server-side (~30s), so a 30s client poll is cheap.
  useEffect(() => {
    let cancelled = false
    const fetchHealth = async () => {
      try {
        const h = await getHealth()
        if (!cancelled) setHealth(h)
      } catch {
        // Keep the last known snapshot on transient fetch failures — a fully
        // unreachable backend will surface through the API calls themselves.
      }
    }
    fetchHealth()
    const timer = setInterval(fetchHealth, 30_000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [])

  // Apply the theme by toggling the .dark class on <html>.
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'dark') {
      root.classList.add('dark')
    } else {
      root.classList.remove('dark')
    }
    localStorage.setItem('ragline_theme', theme)
  }, [theme])

  const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))

  // Persist the session id and load that session's memory-toggle state.
  useEffect(() => {
    localStorage.setItem('ragline_session_id', sessionId)
    const stored = localStorage.getItem(`ragline_memory_${sessionId}`)
    setMemoryEnabled(stored !== null ? stored === 'true' : true)
  }, [sessionId])

  // Load the session's turn history from the backend on session switch.
  useEffect(() => {
    let cancelled = false
    async function loadHistory() {
      try {
        const data = await getSessionHistory(sessionId)
        if (cancelled) return
        const loaded: ChatMessage[] = []
        // Rebuild the transcript: each stored turn becomes a user +
        // assistant message pair with the full response payload.
        for (const turn of data.turns) {
          loaded.push({
            role: 'user',
            content: turn.user_query,
            timestamp: turn.timestamp,
          })
          loaded.push({
            role: 'assistant',
            content: turn.answer,
            response: {
              answer: turn.answer,
              spans: turn.spans,
              sources: turn.sources,
              query: turn.rewritten_query,
              model_used: turn.model_used,
              session_id: sessionId,
              rewritten_query: turn.rewritten_query,
              turn_number: turn.turn_number,
              confidence_score: turn.confidence_score ?? null,
              confidence_report: turn.confidence_report ?? null,
              used_rag: turn.used_rag ?? true,
              used_library: turn.used_library ?? false,
              used_graph: turn.used_graph ?? false,
              response_time_ms: null,
              prompt_tokens: turn.prompt_tokens ?? null,
              completion_tokens: turn.completion_tokens ?? null,
              memory_enabled: turn.memory_enabled ?? true,
              trace_id: turn.trace_id ?? null,
            },
            timestamp: turn.timestamp,
            memoryLoading: false,
          })
        }
        // Restore the session token total from stored per-turn totals.
        let totalTokens = 0
        for (const turn of data.turns) {
          totalTokens += (turn.prompt_tokens ?? 0) + (turn.completion_tokens ?? 0)
        }
        setSessionTokens(totalTokens)
        setMessages(loaded)
      } catch {
        // Unknown/new session: start empty.
        setMessages([])
        setSessionTokens(0)
      }
    }
    loadHistory()
    return () => { cancelled = true }
  }, [sessionId])

  // The previous turn's still-open SSE stream (post-passes running). The
  // input unlocks as soon as an answer arrives, so a fast follow-up send can
  // overlap the previous turn's memory write — this ref lets the next send
  // wait for that stream to close instead of racing it.
  const inflightRef = useRef<Promise<void> | null>(null)

  // Send one chat turn over the SSE endpoint.
  const handleSend = useCallback(async (question: string) => {
    setLoading(true)
    setSelectedCitation(null)

    // Show the user's message immediately.
    const userMsg: ChatMessage = {
      role: 'user',
      content: question,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMsg])

    // Serialize with the previous turn: the backend appends each turn to
    // session memory when its stream ends, so a new turn must not start
    // until then. Usually resolved before the user finishes typing.
    if (inflightRef.current) {
      try { await inflightRef.current } catch { /* previous turn's error is its own */ }
    }

    try {
      const turn = chatQuery(
        sessionId,
        question,
        // Frame 1 (`answer`): append the assistant message and UNLOCK the
        // input — confidence/token data streams in behind it (frame 2), and
        // the message shows its own "Updating memory..." spinner meanwhile.
        (resp: ChatResponse) => {
          const assistantMsg: ChatMessage = {
            role: 'assistant',
            content: resp.answer,
            response: resp,
            timestamp: new Date().toISOString(),
            memoryLoading: true,
          }
          setMessages((prev) => [...prev, assistantMsg])
          setLoading(false)
        },
        // Frame 2 (`complete`): fill in confidence + whole-turn tokens.
        (update: ConfidenceUpdate) => {
          const promptTokens = update.prompt_tokens
          const completionTokens = update.completion_tokens

          // Bump the header's session counter by this turn's total.
          if (promptTokens != null || completionTokens != null) {
            setSessionTokens((prev) => prev + (promptTokens ?? 0) + (completionTokens ?? 0))
          }

          // Update the newest still-loading assistant message in place.
          setMessages((prev) => {
            const updated = [...prev]
            for (let i = updated.length - 1; i >= 0; i--) {
              if (updated[i].role === 'assistant' && updated[i].memoryLoading) {
                updated[i] = {
                  ...updated[i],
                  memoryLoading: false,
                  response: updated[i].response
                    ? {
                        ...updated[i].response!,
                        confidence_score: update.confidence_score,
                        confidence_report: update.confidence_report,
                        prompt_tokens: promptTokens ?? null,
                        completion_tokens: completionTokens ?? null,
                        memory_enabled: update.memory_enabled,
                      }
                    : undefined,
                }
                break
              }
            }
            return updated
          })
          setLoading(false)
        },
        memoryEnabled,
        // Retrieval scope (empty set = whole corpus).
        [...scope],
      )
      // Publish the open stream for the next send to serialize against,
      // then wait for it to close (frame 2 / post-passes done).
      inflightRef.current = turn
      await turn
    } catch (err) {
      console.error('Chat error:', err)
      // Never fail silently: show the error where the answer would have been
      // so a backend failure reads as "something broke", not "ignored me".
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: `⚠ The backend failed to answer this question (${err instanceof Error ? err.message : 'stream error'}). Check the header status dots and try again.`,
        timestamp: new Date().toISOString(),
      }])
    } finally {
      inflightRef.current = null
      // Safety net: ensure loading is cleared even if the stream closes
      // without emitting a `complete` event (backend exception mid-stream).
      setMessages((prev) => {
        const updated = [...prev]
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].role === 'assistant' && updated[i].memoryLoading) {
            updated[i] = { ...updated[i], memoryLoading: false }
            break
          }
        }
        return updated
      })
      setLoading(false)
    }
  }, [sessionId, memoryEnabled, scope])

  // Close the memory dropdown on any click outside it, or on Escape — the
  // usual menu behaviour. Listeners are only attached while the menu is open,
  // and mousedown (not click) closes it before the click lands, so a click on
  // another control both dismisses the menu and activates that control.
  useEffect(() => {
    if (!memoryMenuOpen) return

    const onPointerDown = (event: MouseEvent) => {
      if (!memoryMenuRef.current?.contains(event.target as Node)) {
        setMemoryMenuOpen(false)
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMemoryMenuOpen(false)
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [memoryMenuOpen])

  // Persist the memory toggle per session.
  const handleToggleMemory = useCallback((value: boolean) => {
    setMemoryEnabled(value)
    localStorage.setItem(`ragline_memory_${sessionId}`, String(value))
  }, [sessionId])

  // Start a fresh session.
  const handleNewChat = useCallback(() => {
    const newId = generateId()
    setSessionId(newId)
    setMessages([])
    setSelectedCitation(null)
    setSessionTokens(0)
    setMemoryMenuOpen(false)
    setMemoryEnabled(true)
  }, [])

  // Switch to an existing session from the sidebar.
  const handleSelectSession = useCallback((id: string) => {
    if (id !== sessionId) {
      setSessionId(id)
      setSelectedCitation(null)
      setSessionTokens(0)
      setMemoryMenuOpen(false)
    }
  }, [sessionId])

  // Memory menu action: re-summarize, keep only the last 2 turns.
  const handleCompactMemory = useCallback(async () => {
    setMemoryMenuOpen(false)
    try {
      await compactMemory(sessionId)
    } catch (err) {
      console.error('Compact memory error:', err)
    }
  }, [sessionId])

  // Memory menu action: wipe summary/facts/topics/turns.
  const handleClearMemory = useCallback(async () => {
    setMemoryMenuOpen(false)
    try {
      await clearMemory(sessionId)
      // Clearing memory removes the stored turns — reset the transcript too.
      setMessages([])
      setSessionTokens(0)
    } catch (err) {
      console.error('Clear memory error:', err)
    }
  }, [sessionId])

  return (
    <div className="h-screen flex flex-col">
      {/* ---- Header: brand, session controls, tabs, theme switch ---- */}
      <header className="glass-heavy border-b border-theme-main px-4 py-3 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-3">
          {/* Session-sidebar toggle (chat tab only). */}
          {activeTab === 'chat' && (
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-theme-tertiary hover:text-[var(--accent)] text-lg leading-none transition-colors"
              title="Toggle sessions"
            >
              &#9776;
            </button>
          )}
          {/* Text brand (no logo asset in ragline). */}
          <span className="text-lg font-bold tracking-tight text-theme-primary">
            rag<span className="text-[var(--accent)]">line</span>
          </span>
        </div>
        <nav className="flex items-center gap-2">
          {/* Backend service status dots (from the 30s /health poll). */}
          {health && (
            <div className="flex items-center gap-2 mr-1">
              <StatusDot label="LLM" up={health.llm} />
              <StatusDot label="Embed" up={health.embedder} />
              <StatusDot label="Rerank" up={health.reranker} />
              <StatusDot label="Qdrant" up={health.qdrant} />
            </div>
          )}
          {/* Running session token total. */}
          {activeTab === 'chat' && sessionTokens > 0 && (
            <span className="text-xs text-theme-tertiary font-mono">
              {sessionTokens.toLocaleString()} tokens
            </span>
          )}
          {/* New-session button. */}
          {activeTab === 'chat' && (
            <div className="relative">
              <button
                onClick={handleNewChat}
                className="px-3 py-1.5 rounded-lg text-sm font-medium text-[var(--accent)] hover:bg-[var(--bg-surface)] transition-all"
              >
                + New
              </button>
            </div>
          )}
          {/* THE memory ON/OFF toggle. */}
          {activeTab === 'chat' && (
            <button
              onClick={() => !loading && handleToggleMemory(!memoryEnabled)}
              disabled={loading}
              className={`flex items-center gap-1.5 px-1 py-1 rounded-lg transition-all ${loading ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
              title={`Conversation memory: ${memoryEnabled ? 'ON' : 'OFF'}`}
            >
              <span className="text-xs text-theme-tertiary select-none">Memory</span>
              <div
                className={`relative w-9 h-5 rounded-full transition-colors duration-200 ${memoryEnabled ? 'glass-accent' : 'bg-slate-600'}`}
              >
                <div
                  className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 ${memoryEnabled ? 'translate-x-[18px]' : 'translate-x-0.5'}`}
                />
              </div>
            </button>
          )}
          {/* Memory management dropdown (Compact / Clear). */}
          {activeTab === 'chat' && messages.length > 0 && (
            <div className="relative" ref={memoryMenuRef}>
              <button
                onClick={() => setMemoryMenuOpen(!memoryMenuOpen)}
                className="px-2 py-1.5 rounded-lg text-sm text-theme-tertiary hover:text-theme-primary hover:bg-[var(--bg-surface)] transition-all"
                title="Memory management"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                </svg>
              </button>
              {memoryMenuOpen && (
                <div className="absolute right-0 top-full mt-1 w-48 glass rounded-lg border border-theme-main shadow-lg z-50 py-1">
                  <button
                    onClick={handleCompactMemory}
                    className="w-full text-left px-3 py-2 text-sm text-theme-secondary hover:bg-[var(--bg-surface)] transition-colors"
                  >
                    Compact Memory
                  </button>
                  <button
                    onClick={handleClearMemory}
                    className="w-full text-left px-3 py-2 text-sm text-rose-400 hover:bg-[var(--bg-surface)] transition-colors"
                  >
                    Clear Memory
                  </button>
                </div>
              )}
            </div>
          )}
          {/* The two tabs. */}
          <button
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'chat' ? 'glass-accent text-white' : 'text-theme-secondary hover:text-theme-primary hover:bg-[var(--bg-surface)]'}`}
            onClick={() => setActiveTab('chat')}
          >
            Chat
          </button>
          <button
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${activeTab === 'documents' ? 'glass-accent text-white' : 'text-theme-secondary hover:text-theme-primary hover:bg-[var(--bg-surface)]'}`}
            onClick={() => setActiveTab('documents')}
          >
            Documents
          </button>
          {/* Theme switcher (sun/moon). */}
          <button
            onClick={toggleTheme}
            className="px-2.5 py-1.5 rounded-lg text-sm transition-all text-theme-secondary hover:text-theme-primary hover:bg-[var(--bg-surface)]"
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            )}
          </button>
          {/* Signed-in identity + sign-out (hidden when auth is disabled). */}
          <UserBadge />
        </nav>
      </header>

      {/* One-time reranker-download notice. */}
      <FirstRunNotice />

      {/* ---- Tab bodies ---- */}
      {activeTab === 'chat' ? (
        <div className="flex flex-1 overflow-hidden">
          {/* Collapsible session list. */}
          <SessionList
            currentSessionId={sessionId}
            onSelectSession={handleSelectSession}
            onNewChat={handleNewChat}
            open={sidebarOpen}
          />

          {/* Transcript + input. */}
          <div className="flex-1 flex flex-col min-w-0">
            <ChatHistory
              messages={messages}
              onCitationClick={setSelectedCitation}
              loading={loading}
            />
            {/* Retrieval-scope banner: only while a selection is active. */}
            {scope.size > 0 && (
              <div className="mx-4 mb-1 px-3 py-1.5 rounded-lg glass text-xs flex items-center justify-between gap-3">
                <span className="text-theme-secondary">
                  Retrieval limited to <span className="text-theme-primary font-medium">{scope.size}</span> selected {scope.size === 1 ? 'document' : 'documents'}
                </span>
                <span className="flex items-center gap-3">
                  <button onClick={() => setActiveTab('documents')} className="text-theme-tertiary hover:text-theme-primary transition-colors">
                    Edit
                  </button>
                  <button onClick={() => handleScopeChange(new Set())} className="text-rose-400 hover:text-rose-300 transition-colors">
                    Clear
                  </button>
                </span>
              </div>
            )}
            <ChatInput onSend={handleSend} disabled={loading} />
          </div>

          {/* Citation detail sidebar, when a pill is clicked. */}
          {selectedCitation && (
            <div className="shrink-0">
              <CitationSidebar
                citation={selectedCitation}
                onClose={() => setSelectedCitation(null)}
              />
            </div>
          )}
        </div>
      ) : (
        <main className="flex-1 overflow-y-auto">
          {/* Full width: the explorer's tables are wide (name + stats +
              actions), so no max-width — a capped container forced a
              horizontal scrollbar at the bottom of the panel. */}
          <div className="w-full px-6 py-8 space-y-6">
            {/* Upload card feeds the batch id into the list's progress poll;
                health drives its ingest guard (block when embedder/LLM down). */}
            <DocumentUpload onBatchStarted={setActiveBatchId} health={health} />
            <DocumentList
              activeBatchId={activeBatchId}
              onBatchComplete={() => setActiveBatchId(null)}
              scope={scope}
              onScopeChange={handleScopeChange}
            />
          </div>
        </main>
      )}
    </div>
  )
}
