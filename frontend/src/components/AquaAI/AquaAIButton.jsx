/**
 * Aqua AI — the assistant's floating launcher and chat panel.
 *
 * Owns every piece of chat state: the open flag, the message list,
 * the in-flight request, the conversation id and the error. `ChatWindow` is
 * purely presentational so the behaviour lives in one readable place.
 *
 * There is no canned or pre-written assistant text anywhere in this file. A
 * reply is only ever whatever `POST /api/aqua-ai/chat` returned; when the
 * request fails, the turn is kept and marked failed so it can be retried,
 * rather than being replaced with something that looks like an answer.
 *
 * The backend reply is the client contract envelope:
 * `{ success, message, conversation_id, actions }`. `message` is the assistant
 * text; `actions` lists client-side effects the model asked for (navigation),
 * which this component executes under its own control.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

// CLICK-TO-OPEN (was hover-to-open). The launcher no longer opens on hover:
// a pointer passing over the waterdrop is not a request for a chat window, and
// the hover trigger made the panel pop open whenever the cursor crossed the
// corner. Opening and closing are now explicit clicks/taps on the launcher and
// the close button; the hover constants are kept only so nothing else needs
// changing, and are no longer wired to any timer.

import { aiApi, predictionApi } from '@/api'
import ChatWindow from '@/components/AquaAI/ChatWindow'
import { useAquaAIContext } from '@/context/useAquaAIContext'
import { ROUTES } from '@/utils/constants'
import { errorMessage } from '@/utils/format'
import {
  buildCsv,
  downloadReportsPdf,
  downloadText,
  exportStamp,
  reportCsv,
} from '@/utils/reports'

// The only destinations the assistant may navigate to. Deliberately narrower
// than every route in the app: `/login`, `/register`, `/profile` and `/admin` are
// excluded, so a navigation action can never bounce a visitor to a screen that
// does not exist or to the privileged console. A target outside this set is
// ignored.
const VALID_ROUTES = new Set([
  ROUTES.home,
  ROUTES.dashboard,
  ROUTES.predict,
  ROUTES.history,
  ROUTES.alerts,
  ROUTES.reports,
  ROUTES.location,
  ROUTES.rainyAlerts,
])

let nextMessageId = 0

export default function AquaAIButton({ open: controlledOpen, onOpenChange }) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
  const isControlled = controlledOpen !== undefined
  const open = isControlled ? controlledOpen : uncontrolledOpen

  const setOpen = useCallback(
    (next) => {
      const value = typeof next === 'function' ? next(open) : next
      if (isControlled) onOpenChange?.(value)
      else setUncontrolledOpen(value)
    },
    [isControlled, onOpenChange, open],
  )

  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const [error, setError] = useState(null)
  // Whether the history panel is open, and whether a thread is being fetched.
  const [historyOpen, setHistoryOpen] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [conversations, setConversations] = useState([])
  // THE SLOW EXIT. True during the 450ms in which the panel is animating away
  // after the user asked for close or minimise. The panel stays MOUNTED for
  // that window (`open || closing` below) so the fade-out has something to
  // animate, and is unmounted only once the animation has finished.
  const [closing, setClosing] = useState(false)
  const closingRef = useRef(false)
  const closeTimer = useRef(null)

  // THE ONLY TIMER THIS COMPONENT OWNS IS THE EXIT ANIMATION.
  //
  // The hover open/close timers were removed when the launcher became
  // click-to-open, but three references to `hoverOpenTimer` / `hoverCloseTimer`
  // were LEFT BEHIND in the cleanup effect and in `clearHoverTimers`. Those
  // names were never declared, so calling either threw a `ReferenceError` —
  // which is the "blink / will not stay closed" defect: a close that threw part
  // way through left the closing flag half-applied and the panel re-mounted.
  //
  // They are deleted outright rather than re-declared, because there is no
  // hover timer to clear any more; keeping a no-op around invited exactly the
  // stale reference that caused this. `closeTimer` is the one timer, and it is
  // cleared on unmount below.
  useEffect(() => () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
  }, [])

  /** Cancel a close in progress — the launcher re-opened the panel before the
      exit animation finished, so the pending unmount must not fire. */
  const cancelClose = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closingRef.current = false
    setClosing(false)
  }, [])

  /**
   * Run the slow close: play the exit animation first, THEN actually unmount.
   * 300ms matches the `panel-out` duration in the Tailwind config — and that
   * animation is the exact mirror of `panel-in` (same duration, same easing,
   * same distance), so the panel cannot disappear mid-animation and open and
   * close are one motion in reverse.
   */
  const animateClose = useCallback(() => {
    // ALREADY GONE, OR ALREADY ANIMATING AWAY. The blink bug: when the panel is
    // closed, `open` is false but a stray hover-leave or a second close click
    // still called this, setting `closing` true — and `(open || closing)` then
    // re-mounted the closed panel for 300ms so it could "animate out" again.
    // A panel that is already closed has nothing to animate; ignore the call.
    if (closingRef.current) return
    if (!open) return
    closingRef.current = true
    setClosing(true)
    closeTimer.current = setTimeout(() => {
      closingRef.current = false
      setClosing(false)
      setOpen(false)
    }, 300)
  }, [open, setOpen])

  /**
   * Start a fresh thread without leaving the panel.
   *
   * Exposed to the user because closing the panel is no longer the only way to
   * clear the view, and "clear this and start again" is a distinct action from
   * "put the panel away".
   */
  const startNewChat = useCallback(() => {
    setMessages([])
    setConversationId(null)
    setInput('')
    setError(null)
    setHistoryOpen(false)
    lastAttemptRef.current = null
  }, [])

  // The failed turn's text, so Retry can resend it verbatim.
  const lastAttemptRef = useRef(null)
  const inputRef = useRef(null)
  const location = useLocation()
  const navigate = useNavigate()

  /**
   * Download a report list the assistant offered.
   *
   * The assistant cannot produce a file - it returns a SCOPE (all / safe /
   * moderate / unsafe) and a FORMAT (csv / pdf), and this fetches that slice and
   * builds the file here, where the CSV and PDF builders already live.
   *
   * The data is re-fetched from the API rather than taken from the chat message,
   * so the export is exactly what the Reports screen would produce for the same
   * filter - it cannot go stale between the assistant reading it and the user
   * clicking. Nothing the model said is used to build the file.
   */
  const runDownload = useCallback(async (action) => {
    const scope = action?.scope || 'all'
    const format = action?.format === 'pdf' ? 'pdf' : 'csv'
    try {
      const response = await predictionApi.history({ per_page: 100 })
      const all = response?.data?.data || response?.data || []
      const rows = Array.isArray(all) ? all : []
      const filtered =
        scope === 'all' ? rows : rows.filter((row) => row.prediction === scope)

      if (filtered.length === 0) {
        setError(`There are no ${scope === 'all' ? '' : `${scope} `}reports to download yet.`)
        return
      }

      if (format === 'pdf') {
        await downloadReportsPdf(filtered, {
          filename: `aquaguard-reports-${scope}-${exportStamp()}.pdf`,
          title: `${filtered.length} reading${filtered.length === 1 ? '' : 's'}`,
        })
      } else {
        downloadText(
          `aquaguard-reports-${scope}-${exportStamp()}.csv`,
          buildCsv(reportCsv.headers, filtered.map(reportCsv.row)),
        )
      }
    } catch (err) {
      setError(errorMessage(err, 'That download could not be prepared.'))
    }
  }, [])

  // Which screen the user is on, so the suggested questions match it. The
  // context comes from the route plus any announcement the page made — the
  // Predict screen announces when a verdict is on screen. It only selects which
  // prompts to offer; no answer is derived from it.
  const { context } = useAquaAIContext()

  /**
   * Close the panel and DISCARD the visible conversation.
   *
   *   X  close   — clears the thread; the next open starts a NEW chat
   *   logo       — puts the panel away, keeping the thread (the same droplet
   *                that opened it closes it again)
   *
   * The two ideas stay separate, which is what makes either one predictable.
   * A cleared thread is not a DELETED thread: the server-side conversation is
   * still there, reachable from the history panel, so nothing is lost by closing.
   */
  const close = useCallback(() => {
    // The thread is discarded and the panel is put away, but through the SLOW
    // exit animation rather than an instant unmount. Any pending hover timer
    // dies with it.
    animateClose()
    setMessages([])
    setConversationId(null)
    setInput('')
    setError(null)
    lastAttemptRef.current = null
  }, [animateClose])

  /**
   * Minimise the panel — put it away WITHOUT throwing the thread away.
   *
   * This is the deliberate opposite of `close`: the visible messages, the
   * conversation id and the composer's text all survive, so clicking the
   * chatbot logo again drops the user straight back into the same exchange,
   * continuing it rather than starting over. The header's minimise button and
   * the launcher droplet both use this, which is what makes "minimise" and
   * "reopen" feel like one continuous surface. */
  const minimize = useCallback(() => {
    animateClose()
  }, [animateClose])

  // NAVIGATION CLOSES THE PANEL — immediately, with no exit animation.
  //
  // This deliberately does NOT go through `animateClose`. A route change already
  // unmounts the page under the panel, and making the panel play a 300ms exit
  // WHILE the new page renders behind it is what produced the visible flicker:
  // the panel briefly re-appeared over the new screen before finally going. On a
  // navigation the close is instant and final, so the panel is simply gone by the
  // time the next page paints.
  //
  // `closingRef` is reset here too, so a close that was mid-animation when the
  // user navigated cannot leave the flag set and block the NEXT open.
  useEffect(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closingRef.current = false
    setClosing(false)
    setOpen(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  useEffect(() => {
    function onKeyDown(event) {
      if (event.key === 'Escape') close()
    }
    if (open) {
      document.addEventListener('keydown', onKeyDown)
      return () => document.removeEventListener('keydown', onKeyDown)
    }
    return undefined
  }, [open, close])

  // Focus the composer when the panel opens, so the user can type immediately.
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  /** Send one turn, and record it as failed rather than dropping it. */
  const send = useCallback(
    async (text) => {
      const message = (text ?? input).trim()
      if (!message || sending) return

      lastAttemptRef.current = message
      setMessages((previous) => [
        ...previous,
        { id: (nextMessageId += 1), role: 'user', content: message, at: new Date() },
      ])
      setInput('')
      setSending(true)
      setError(null)

      try {
        const response = await aiApi.chat({ message, conversation_id: conversationId })
        // The envelope lives under `data` from the Axios wrapper; fall back to
        // the top level so either response shape is read correctly.
        const payload = response.data ?? response
        if (payload.conversation_id) setConversationId(payload.conversation_id)

        const text = typeof payload.message === 'string' ? payload.message : ''
        const assistantActions = Array.isArray(payload.actions) ? payload.actions : []
        setMessages((previous) => [
          ...previous,
          {
            id: (nextMessageId += 1),
            role: 'assistant',
            content: text,
            at: new Date(),
            status: payload.success === false ? 'error' : 'ok',
            // A misconfigured deployment (no API key) is not transient —
            // resending cannot fix it, so no Retry is offered for that case.
            retryable: /not configured|AQUA_AI_API_KEY/i.test(text),
            // The controls that belong to THIS reply: download buttons for a
            // report list, and any navigation the assistant requested. They are
            // stored on the message so they stay put in the transcript rather
            // than appearing as a floating bar that outlives the answer.
            actions: assistantActions,
          },
        ])

        // The assistant may request navigation. React Router performs it, under
        // this component's control. The action carries a `target`, and it is
        // only honoured when it is one of THIS app's own routes — the model
        // cannot drive the router to an arbitrary or external URL. An unknown
        // target is ignored rather than navigated to.
        //
        // A navigation action still navigates immediately (that is what "go to
        // X" means). DOWNLOAD actions do NOT fire on their own: they are buttons
        // the user clicks, so a download never starts without being asked for.
        for (const action of assistantActions) {
          if (action?.type !== 'NAVIGATE') continue
          const { target } = action
          if (VALID_ROUTES.has(target)) {
            navigate(target)
          }
        }
      } catch (err) {
        // Record the failure as an assistant turn rather than only as banner
        // text. A banner cannot carry a Retry control, and this is precisely
        // the case where retrying is worth offering: the question was asked,
        // the network dropped it, and sending it again may well work.
        const reason = errorMessage(
          err,
          'Aqua AI could not be reached. Please try again.',
        )
        setError(reason)
        setMessages((previous) => [
          ...previous,
          {
            id: (nextMessageId += 1),
            role: 'assistant',
            content: reason,
            at: new Date(),
            status: 'error',
            retryable: true,
          },
        ])
      } finally {
        setSending(false)
      }
    },
    [input, sending, conversationId, navigate],
  )

  /**
   * Load the account's conversation list.
   *
   * Fetched when the history panel is opened rather than on mount: the panel is
   * opened rarely, and a list that is refetched each time is one that is never
   * stale. A failure is swallowed into an empty list — a broken history must not
   * stop the user asking a question.
   */
  const loadConversations = useCallback(async () => {
    setLoadingHistory(true)
    try {
      const response = await aiApi.listConversations()
      const payload = response.data ?? response
      setConversations(Array.isArray(payload) ? payload : payload.conversations || [])
    } catch {
      setConversations([])
    } finally {
      setLoadingHistory(false)
    }
  }, [])

  /**
   * Restore a previous conversation into the panel.
   *
   * The threads are the account's own — the endpoint is scoped to the caller by
   * the server — and the turns come back in order, so the panel shows the same
   * exchange that produced the answers the first time.
   */
  const openConversation = useCallback(async (id) => {
    setLoadingHistory(true)
    setHistoryOpen(false)
    try {
      const response = await aiApi.getConversation(id)
      const payload = response.data ?? response
      const turns = payload.messages || []
      setMessages(
        turns.map((turn, position) => ({
          id: `${id}-${turn.id ?? position}`,
          role: turn.role === 'assistant' ? 'assistant' : 'user',
          content: turn.content || turn.message || '',
          at: new Date(turn.created_at || Date.now()),
          status: 'ok',
        })),
      )
      // Continue the restored thread rather than forking a new one: the next
      // question the user asks should belong to the conversation they just
      // opened.
      setConversationId(id)
    } catch (err) {
      setError(errorMessage(err, 'That conversation could not be opened.'))
    } finally {
      setLoadingHistory(false)
    }
  }, [])

  /** Resend the last message, removing the failed assistant turn first. */
  const retry = useCallback(() => {
    const text = lastAttemptRef.current
    if (!text || sending) return
    // Drop the failed assistant turn AND the user turn it answers, then send
    // again — otherwise the retry would post the question a second time and
    // leave two user bubbles for one question.
    setMessages((previous) => {
      const trimmed = [...previous]
      if (trimmed.at(-1)?.role === 'assistant') trimmed.pop()
      if (trimmed.at(-1)?.role === 'user') trimmed.pop()
      return trimmed
    })
    setError(null)
    send(text)
  }, [send, sending])

  const handleSubmit = useCallback(
    (event) => {
      event?.preventDefault?.()
      send()
    },
    [send],
  )

  return (
    <>
      {/* Backdrop over the page behind the panel.

          This sits OUTSIDE the launcher container on purpose. It used to be the
          container's first child, which meant every later sibling - including
          the launcher button itself - was painted underneath it and dimmed by
          the bg-slate-900/40 wash. Measured on the real launcher: mean
          brightness 110.8 closed, 46.1 open, i.e. 58 percent dimmed. That
          dimmed button is what read as a second, half-visible close control.

          backdrop-blur is on the overlay, not the panel, so what gets blurred
          is the PAGE. Blurring the panel would smear the chat text. */}
      {open || closing ? (
        <div
          // SYMMETRIC WITH THE PANEL: `aqua-backdrop-in` and `aqua-backdrop-out`
          // are both 0.3s on the panel's own easing curve, so the scrim and the
          // box open together and close together instead of the wash outliving
          // the panel and then snapping off.
          className={`fixed inset-0 z-40 ${closing ? 'animate-aqua-backdrop-out' : 'animate-aqua-backdrop-in'} bg-slate-900/20 backdrop-blur-[3px] dark:bg-slate-950/40`}
          onClick={close}
          aria-hidden="true"
        />
      ) : null}

      {/* A hover BRIDGE between the launcher and the panel is unnecessary:
          hover containment follows the DOM tree, and both the panel and the
          launcher are children of the container below, so moving between them
          never leaves the container. */}

      {/* The launcher container.

          ANCHORED BOTTOM-RIGHT ON EVERY VIEWPORT, because that is where the
          droplet logo lives when the chat is closed: the user asked for the
          mobile logo to sit in the bottom-right corner, not at the top.

          The PANEL does not follow that anchor on a phone. When it opens it is
          positioned `fixed` at the top of the screen (see the panel below), so it
          arrives from the top and runs down the page, while this container keeps
          the close control pinned near the bottom.

          The droplet LOGO is not rendered while the panel is open (see the
          launcher below), so the panel and its close control have the screen to
          themselves.

          `flex` here is load-bearing: without it the `flex-col` and `items-*`
          classes are inert and the panel lays out as a plain block. */}
      <div
        className="aqua-ai-root fixed bottom-4 right-4 z-50 flex-col items-end gap-3 sm:bottom-6 sm:right-6"
      >
      {/* NO HOVER HANDLERS. The launcher used to open on hover from this
          container; opening is a click now, so the container carries no
          mouse listeners at all. Hovering the waterdrop does nothing — only a
          click or tap opens the panel, and the X (or the backdrop, or Escape)
          closes it. */}

      {/* The chat panel. */}
      {(open || closing) && (
        // `pb-24` reserves the strip the close button sits in BELOW the panel on
        // a phone, so the "X" is clear of the box rather than behind it.
        // `lg:pb-0` drops that reservation: on desktop the X is beside the
        // panel, on the left, not below it.
        // MOBILE: `fixed` at the top of the screen, horizontally centred, so the
        // panel arrives from the TOP and spans the width of the phone — it no
        // longer hangs off the bottom-right corner where the logo used to be.
        // The group reserves `pb-24` so the close button below the box has room.
        //
        // DESKTOP (`lg:`): `lg:static` puts the panel back in the container's
        // flow so it rises above the corner launcher as before, and `lg:pb-0`
        // drops the mobile-only reservation.
        <div className={`fixed inset-x-3 top-3 z-40 ${closing ? 'animate-panel-out' : 'animate-panel-in'} pb-24 lg:static lg:inset-x-auto lg:top-auto lg:pb-0`}>
          <div
            role="dialog"
            aria-label="Aqua AI assistant"
            // While closing, pointer events are cut so the animating panel
            // cannot swallow a click meant for the page underneath.
            style={closing ? { pointerEvents: 'none' } : undefined}
            // TALL ON EVERY VIEW. On a phone it fills from the top of the screen
            // down to just above the close button; on desktop it is the familiar
            // tall panel above the corner launcher. `100dvh` rather than `vh` so
            // the mobile browser chrome that slides in and out does not crop the
            // composer.
            className="mx-auto flex h-[calc(100dvh-9.5rem)] w-full flex-col overflow-hidden rounded-panel border-slate-200/80 bg-white shadow-panel dark:border-slate-700 dark:bg-slate-900 lg:h-[min(38rem,calc(100dvh-6.5rem))] lg:w-[min(25rem,calc(100vw-1.5rem))]"
          >
            <ChatWindow
              messages={messages}
              input={input}
              onInputChange={setInput}
              onSend={handleSubmit}
              onSuggestion={send}
              onRetry={retry}
              onDownload={runDownload}
              sending={sending}
              error={error}
              inputRef={inputRef}
              context={context}
              historyOpen={historyOpen}
              onToggleHistory={() => {
                // Fetch on the way IN, not on every render, so the list is fresh
                // at the moment it is shown.
                if (!historyOpen) loadConversations()
                setHistoryOpen((open) => !open)
              }}
              onNewChat={startNewChat}
              onPickConversation={openConversation}
              conversations={conversations}
              loadingHistory={loadingHistory}
              onMinimize={minimize}
                  />
                </div>

                {/* --- The close control -------------------------------------------

                    It sits OUTSIDE the panel in both layouts, so it never covers a
                    message and never competes with the composer:

                      mobile   centred horizontally, just BELOW the panel
                      desktop  centred on the panel's LEFT edge, vertically centred
                    The base styles are the mobile ones and the `lg:` ones override
                    them, so one button serves both layouts with no JS breakpoint. */}
                <button
                  type="button"
                  onClick={close}
                  aria-label="Close Aqua AI"
                  title="Close"
                  className="absolute left-1/2 top-full z-20 mt-3 flex h-12 w-12 -translate-x-1/2 items-center justify-center rounded-full bg-gradient-to-br from-aqua-500 to-aqua-700 text-white shadow-panel ring-1 ring-white/30 transition-transform duration-200 hover:scale-110 focus-visible:scale-110 active:scale-95 focus-visible:ring-2 focus-visible:ring-aqua-500 dark:from-aqua-400 dark:to-aqua-600 dark:ring-white/25 lg:-left-14 lg:top-1/2 lg:mt-0 lg:-translate-x-0 lg:-translate-y-1/2"
                >
                  <span
                    className="absolute h-11 w-11 animate-pulse-ring rounded-full bg-aqua-400 dark:bg-aqua-300"
                    aria-hidden="true"
                  />
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" className="relative h-5 w-5">
                    <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
            )}

            {/* --- Floating launcher --------------------------------------------

                THE LOGO IS HIDDEN WHILE THE CHAT IS OPEN. It used to stay in the DOM
                and be pushed clear of the panel, which left a droplet sitting under an
                open chat doing nothing. The requirement is the opposite: the logo goes
                away the moment the chat opens, and comes back normally once the chat is
                closed again.

                So it is rendered only when the panel is CLOSED. Opening the panel
                replaces it with the X below the box, and closing restores it in the
                same spot it has always occupied — the bottom-right corner. */}
            {!open && (
            <button
        type="button"
        // Reopening a MINIMISED panel continues the same thread. When the panel
        // is closed there is nothing to toggle to, so this always opens; the
        // panel's own header carries the minimise control that puts it away.
        // CLICK, NOT HOVER. Hovering the droplet does nothing — only a click or
        // tap opens the panel. There is no hover handler left to remove, and no
        // hover timer left to clear, so a cursor crossing the corner cannot open
        // or re-open anything.
        onClick={() => {
          cancelClose()
          setOpen(!open)
        }}
        aria-expanded={open}
        aria-label={open ? 'Close Aqua AI assistant' : 'Open Aqua AI assistant'}
        // The launcher swaps its two colours between themes:
        //
        //   light mode   blue circle, white droplet
        //   dark mode    white circle, blue droplet
        //
        // Stated as a swap rather than "make it dark in dark mode" because the
        // point is contrast against what is behind it: a blue disc on a light
        // page needs a white glyph to read, and a white disc on a dark page needs
        // a blue one. Keeping the blue disc in dark mode (the previous state)
        // left it competing with the dark backdrop instead of sitting on it.
        //
        // The droplet takes `currentColor`, so setting `text-*` on the button is
        // what colours the glyph — the mark and its colour are one property and
        // cannot drift apart.
        className="group flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-aqua-500 to-aqua-700 text-white shadow-panel ring-1 ring-white/20 transition-transform duration-200 hover:scale-105 focus-visible:scale-105 active:scale-95 dark:from-aqua-300 dark:to-aqua-400 dark:text-aqua-900 dark:ring-white/30"
      >
        {/* The droplet is the launcher's mark, in every state — it is the logo the
            user recognises, and it does not change into a chevron or hide when the
            panel opens. Pressing it toggles the panel, so the same visible control
            both opens and puts away the chat. */}
        <span className="relative flex items-center justify-center">
          {/* The pulse ring follows the disc: `aqua-400` reads as a ripple
              against a light page, but against the dark one it would be the
              only blue left in the button and would look like a leftover
              state rather than a pulse, so dark mode pulses white. */}
          <span
              className="absolute h-14 w-14 animate-pulse-ring rounded-full bg-aqua-400 dark:bg-aqua-300"
              aria-hidden="true"
            />
          <svg viewBox="0 0 24 24" fill="currentColor" className="relative h-7 w-7">
            <path d="M12 3c4 5 6 8 6 11a6 6 0 0 1-12 0c0-3 2-6 6-11Z" />
          </svg>
          <span className="sr-only">Aqua AI</span>
        </span>
      </button>
      )}
      </div>
    </>
  )
}
