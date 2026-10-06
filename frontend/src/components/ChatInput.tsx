// ChatInput — auto-growing textarea + Send button at the bottom of the chat.
// Ported verbatim from raggles. Enter sends; Shift+Enter inserts a newline.
import { useState, useRef } from 'react'

interface Props {
  onSend: (message: string) => void
  disabled: boolean
}

export default function ChatInput({ onSend, disabled }: Props) {
  // Controlled textarea value.
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Send the trimmed text and reset the input height.
  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  // Enter (without Shift) submits instead of inserting a newline.
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Grow the textarea with its content, capped at 150px.
  const handleInput = () => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 150) + 'px'
    }
  }

  return (
    <div className="glass-heavy border-t border-theme-main p-4">
      <div className="flex gap-3 items-end max-w-4xl mx-auto">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => { setText(e.target.value); handleInput() }}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={disabled ? 'Waiting...' : 'Ask a question...'}
          rows={1}
          className="flex-1 resize-none rounded-xl bg-[var(--bg-surface)] backdrop-blur-sm border border-theme-main px-4 py-2.5 text-sm text-theme-primary focus:outline-none focus:ring-2 focus:ring-cyan-400/40 focus:border-transparent disabled:opacity-50 disabled:text-theme-tertiary placeholder:text-theme-tertiary transition-all"
        />
        {/* Disabled while a turn is in flight or the input is empty. */}
        <button
          onClick={handleSend}
          disabled={disabled || !text.trim()}
          className="glass-accent text-white px-4 py-2.5 text-sm font-medium rounded-xl disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:brightness-110"
        >
          Send
        </button>
      </div>
    </div>
  )
}
