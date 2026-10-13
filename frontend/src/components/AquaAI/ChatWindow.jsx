/**
 * Aqua AI chat window.
 *
 * Layout, top to bottom: a header that names the assistant and carries the
 * history control, a scrolling message area, and the composer.
 *
 * All state lives in `AquaAIButton`, so this component stays presentational and
 * is easy to reason about. It renders nothing of its own invention — every
 * assistant turn comes from the API response.
 */

import { useEffect, useRef } from 'react'

import ChatHistory from '@/components/AquaAI/ChatHistory'
import ChatMessage from '@/components/AquaAI/ChatMessage'
import ChatSuggestions from '@/components/AquaAI/ChatSuggestions'
import TypingIndicator from '@/components/AquaAI/TypingIndicator'
import Icon from '@/components/Icon'
import { ICONS } from '@/config/navigation'

export default function ChatWindow({
  messages,
  input,
  onInputChange,
  onSend,
  onSuggestion,
  onRetry,
  onDownload,
  sending,
  error,
  inputRef,
  context,
  historyOpen,
  onToggleHistory,
  onNewChat,
  onPickConversation,
  conversations,
  loadingHistory,
  onMinimize,
}) {
  const scrollRef = useRef(null)

  // Auto-scroll to the newest turn. Runs on message changes and while the
  // typing indicator is visible, so the user is not left looking at old
  // messages when a reply lands.
  useEffect(() => {
    const node = scrollRef.current
    if (!node) return
    node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  function handleKeyDown(event) {
    // Enter sends. Shift+Enter stays available for a newline, so a multi-line
    // question is still possible without reaching for the mouse.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSend()
    }
  }

  const isEmpty = messages.length === 0

  return (
    <>
      {/* --- Header --- */}
      <div className="relative flex items-center gap-3 overflow-hidden border-b border-slate-100 bg-gradient-to-r from-aqua-50 via-aqua-50/40 to-white px-4 py-3 dark:border-slate-700 dark:from-slate-800 dark:via-slate-800/60 dark:to-slate-900">
        {/* A soft brand wash behind the header, so the panel reads as a product
            surface rather than a plain white box. Purely decorative. */}
        <span
          className="pointer-events-none absolute -right-8 -top-10 h-24 w-24 rounded-full bg-aqua-200/25 blur-2xl dark:bg-aqua-500/20"
          aria-hidden="true"
        />

        {/* Header text. The droplet badge that used to sit to the LEFT of it has
            been removed: the assistant's logo is not shown anywhere while the
            panel is open, so the open panel carries no brand mark at all. It
            returns with the launcher once the panel is closed, where it is the
            affordance that reopens the chat rather than decoration on it. */}
        <div className="relative min-w-0 flex-1">
          <p className="truncate text-sm font-semibold tracking-tight text-slate-900 dark:text-white">
            Aqua AI
          </p>
          <p className="flex items-center gap-1.5 text-2xs text-slate-500 dark:text-slate-400">
            <span
              className={`h-1.5 w-1.5 rounded-full ${sending ? 'animate-pulse bg-caution' : 'bg-safe'
                }`}
              aria-hidden="true"
            />
            {sending ? 'Responding…' : 'AI Assistant'}
          </p>
        </div>

        {/* Header controls: history, then MINIMISE at the far right corner.

            The minimise button puts the panel away WITHOUT discarding the
            thread — it is the same action as pressing the droplet launcher, so
            when the user clicks the chatbot logo again they land back in the
            conversation exactly where they left it. It is deliberately distinct
            from the "X" outside the panel, which clears the thread. Both are
            kept, because "put this away" and "throw this away" are different
            intentions and one control cannot honestly mean both. */}
        <div className="relative flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onToggleHistory}
            aria-label="Chat history"
            aria-expanded={historyOpen}
            title="Chat history"
            className={`rounded-field p-1.5 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-black dark:hover:text-white ${
              historyOpen
                ? 'bg-aqua-50 text-aqua-700 dark:bg-black dark:text-white'
                : 'text-slate-400'
            }`}
          >
            {/* A clock with a rewinding arrow — "past conversations". */}
            <Icon path="M12 8v4l3 2M3.05 11a9 9 0 1 1 .5 3M3 4v4h4" className="h-4 w-4" strokeWidth={2} />
          </button>

          {/* MINIMISE — right-hand corner of the header. A short horizontal bar
              is the universal "collapse to a bar" mark. Hovering it in dark
              mode is black-on-white like every other control here. */}
          <button
            type="button"
            onClick={onMinimize}
            aria-label="Minimise Aqua AI"
            title="Minimise"
            className="rounded-field p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-white dark:hover:text-black"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" className="h-4 w-4">
              <path d="M5 12h14" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </div>

      {/* --- History panel -------------------------------------------------
          Replaces the message area rather than sitting beside it. The panel is
          only ~25rem wide, so a side-by-side layout would leave the messages in
          a column too narrow to read; a swap keeps the chat full width when it is
          showing and gives the list the whole panel when it is not. */}
      {historyOpen ? (
        <ChatHistory
          conversations={conversations}
          loading={loadingHistory}
          onPick={onPickConversation}
          onNewChat={onNewChat}
        />
      ) : (
      <div
        ref={scrollRef}
        className="flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4"
        aria-label="Conversation"
        role="log"
        aria-live="polite"
      >
        {isEmpty && !sending && (
          <ChatSuggestions onPick={onSuggestion} context={context} />
        )}

        {messages.map((message) => (
          <ChatMessage key={message.id} message={message} onRetry={onRetry} onDownload={onDownload} />
        ))}

        {sending && <TypingIndicator />}

        {/* The failure is rendered as an assistant turn (so it can carry a
            Retry control). A second banner saying the same thing would just be
            noise, so this one only appears if a failure somehow has no turn. */}
        {error && !sending && messages.at(-1)?.status !== 'error' && (
          <p className="text-center text-[11px] text-unsafe-dark dark:text-unsafe-light" role="alert">
            {error}
          </p>
        )}
      </div>
      )}

      {/* --- Composer --- */}
      <div className="border-t border-slate-100 bg-slate-50/60 px-3 py-3 dark:border-slate-700 dark:bg-slate-800/60">
        <div className="flex items-end gap-2 rounded-field border-slate-200 bg-white p-1 shadow-sm transition-colors focus-within:border-aqua-400 focus-within:ring-2 focus-within:ring-aqua-500/20 dark:border-slate-600 dark:bg-slate-900">
          <label className="sr-only" htmlFor="aqua-ai-input">
            Message Aqua AI
          </label>
          <textarea
            id="aqua-ai-input"
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            onKeyDown={handleKeyDown}
            disabled={sending}
            placeholder="Ask Aqua AI…"
            aria-label="Message Aqua AI"
            className="max-h-24 min-h-[2.25rem] flex-1 resize-none rounded-field border-0 bg-transparent px-2.5 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-0 dark:text-white dark:placeholder:text-slate-500"
          />
          <button
            type="submit"
            onClick={onSend}
            disabled={sending || !input.trim()}
            aria-label="Send message"
            className="btn-primary flex h-9 w-9 shrink-0 items-center justify-center p-0"
          >
            <Icon path={ICONS.send} className="h-4 w-4" strokeWidth={2} />
          </button>
        </div>
        <p className="mt-2 px-1 text-center text-2xs text-slate-400 dark:text-slate-500">
          Enter to send · Shift+Enter for a new line
        </p>
      </div>
    </>
  )
}
