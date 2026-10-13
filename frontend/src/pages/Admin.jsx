import { useCallback, useEffect, useRef, useState } from 'react'

import { adminApi } from '@/api'
import Badge from '@/components/Badge'
import Button from '@/components/Button'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import Icon from '@/components/Icon'
import LocationPinIcon from '@/components/LocationPinIcon'
import Spinner from '@/components/Spinner'
import { ICONS } from '@/config/navigation'
import { useApi } from '@/hooks/useApi'
import {
  errorMessage,
  formatDate,
  formatNumber,
  formatPercent,
  formatPredictionStamp,
  waterSourceLabel,
} from '@/utils/format'
import { NORMAL_LEVELS, PARAMETER_ORDER } from '@/utils/reports'
import { STORAGE_KEYS } from '@/utils/constants'

// The shared visitor account's address, mirrored from
// `backend/app/services/identity.py`.
//
// EVERY READING SUBMITTED WITHOUT A SIGN-IN IS FILED UNDER THIS ONE ACCOUNT,
// because `water_predictions.user_id` is a NOT NULL foreign key. It is
// infrastructure holding the public record rather than a person's login, so the
// console must not offer to delete it. Checked by ADDRESS, not by role: the
// database constrains `users.role` to `user`/`admin`, so there is no role value
// that means "not a real account".
const VISITOR_EMAIL = 'visitor@aquaguard.local'

/**
 * Read the PAYLOAD out of the backend's response envelope, ONCE.
 *
 * THE ONE RULE EVERY ADMIN CALL NEEDS, and the bug it exists to prevent. The
 * shared Axios layer (`@/api/client`) already unwraps the HTTP response: `api.get`
 * resolves to the JSON BODY, which for every endpoint here is the envelope
 * `{success, message, data, ...}`. So the payload is `response.data` — ONE level,
 * not two.
 *
 * The approval poll and the unlock-spend call used to read `(response.data).data`
 * — a SECOND level that does not exist — so they always ended up with
 * `undefined`. The poll therefore never saw `status: "approved"` or `"denied"`,
 * which is why the mailed YES never opened the console and the mailed NO never
 * showed "Access Denied"; and the spend call fell back to a hard-coded
 * `{unlocked: true}`, which reported success for an unlock that never happened.
 *
 * This helper unwraps exactly once, and falls back to the raw value when a
 * response has no envelope (a bare `{unlocked: false}` on an error path, say), so
 * no caller has to guess the depth.
 */
function payloadOf(response) {
  if (response === null || response === undefined) return {}
  const inner = response.data
  // An envelope has `success` alongside `data`; anything else is already the payload.
  if (inner !== undefined && typeof response === 'object' && 'success' in response) {
    return inner ?? {}
  }
  return inner !== undefined ? inner : response
}

const TABS = [
  { key: 'dashboard', label: 'Dashboard', icon: ICONS.dashboard },
  { key: 'access', label: 'Admin access', icon: ICONS.shield },
  { key: 'users', label: 'User management', icon: ICONS.profile },
  { key: 'logins', label: 'Login details', icon: ICONS.history },
  { key: 'unsafe', label: 'Unsafe Prediction History', icon: ICONS.alerts },
  { key: 'reportmail', label: 'Report Email Activity', icon: ICONS.reports },
  { key: 'reports', label: 'Overall reports', icon: ICONS.reports },
  { key: 'parameters', label: 'Parameter control', icon: ICONS.analytics },
  { key: 'location', label: 'Location access', icon: ICONS.location },
  { key: 'models', label: 'ML model management', icon: ICONS.shield },
  { key: 'notifications', label: 'Notification settings', icon: ICONS.alerts },
  { key: 'system', label: 'AI & mail', icon: ICONS.info },
]

/**
 * The admin console.
 *
 * GATED BY ITS OWN CREDENTIAL, and the page reflects that:

 *   1. The console's own username and password. Normal users have no login at
 *      all in this application, so there is no account session to escalate from
 *      and no token a visitor could already hold - this credential is the whole
 *      of the console's authentication.
 *   2. The console must then be UNLOCKED, which the backend only does once the
 *      mailed confirmation is confirmed. Until then this page renders the lock
 *      screen and nothing else; the data is not fetched, so an unlocked-looking
 *      panel cannot be showing stale content from before a lock.
 *
 * WHY THE LOCK IS A SEPARATE STEP rather than the password alone: the console is
 * the highest-privilege surface in the application. Proving the password on one
 * device and confirming it in the mailbox on any other means a stolen password
 * alone cannot reach the data.
 *
 * NOT LINKED ANYWHERE. `/admin` is reached by its own URL and appears in no menu,
 * so it is not offered to a visitor as an ordinary destination.
 *
 * THE UI IS DELIBERATELY ITS OWN WORLD. The console uses a dark, terminal-like
 * water theme with animated scan lines and rising bubbles, distinct from the
 * rest of the application. That is not decoration for its own sake: an
 * administrator who has several tabs open should never be unsure whether they
 * are looking at the user-facing app or the console, and the most reliable way
 * to make that unmistakable is for the two to look nothing alike.
 */

/**
 * THE APPROVAL WATCH, PERSISTED SO IT SURVIVES A RELOAD, A SLEEP OR A DROP.
 *
 * The poll below is what learns that the admin answered the mail, and it only
 * works while the page knows WHICH request to watch. Held only in React state
 * that knowledge died with the tab: a reload, a closed lid, a tunnel or a flat
 * battery each ended the wait, and the page that came back showed a bare sign-in
 * form even though an approval might already be sitting in the database. That is
 * the sync gap this closes.
 *
 * WHAT IS STORED, AND WHY IT IS SAFE TO STORE. Two values, in `sessionStorage`
 * (tab-scoped, cleared when the tab closes):
 *
 *   request_id — a NON-SECRET handle. The backend hands it to the page so the
 *     page can ask about ONE request. It authorises nothing: `poll` also demands
 *     the challenge, and `consume` re-checks the approved status and the
 *     challenge again before it opens anything.
 *   challenge — the browser binding, which the backend stores only as a SHA-256
 *     and which never travels in a URL. It lived in this tab already; persisting
 *     it to this tab's own `sessionStorage` does not widen where it can be seen.
 *
 * NO TOKEN, NO PASSWORD AND NO SESSION SECRET IS EVER STORED HERE. The mail
 * action token is never sent to the browser at all, and the console credential is
 * never held by the page beyond the single sign-in request.
 */
const WATCH_KEY = STORAGE_KEYS.adminApprovalWatch

function readWatch() {
  try {
    const raw = sessionStorage.getItem(WATCH_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    // A watch with no request id or no challenge could not be polled anyway.
    if (!parsed?.request_id || !parsed?.challenge) return null
    return parsed
  } catch {
    // A corrupt entry, or storage disabled (private mode): no watch, which is
    // the same state as a first visit. Never throw from here.
    return null
  }
}

function writeWatch(watch) {
  try {
    if (!watch?.request_id || !watch?.challenge) {
      sessionStorage.removeItem(WATCH_KEY)
      return
    }
    sessionStorage.setItem(WATCH_KEY, JSON.stringify(watch))
  } catch {
    // Storage unavailable. The in-memory state still drives the poll for this
    // page load; only the survive-a-reload part is lost, which is preferable to
    // breaking the sign-in.
  }
}

function clearWatch() {
  try {
    sessionStorage.removeItem(WATCH_KEY)
  } catch {
    // Nothing to do — see `writeWatch`.
  }
}

export default function Admin() {
  const [tab, setTab] = useState('dashboard')
  const [session, setSession] = useState(null)
  const [checking, setChecking] = useState(true)
  const [unlocking, setUnlocking] = useState(false)
  const [unlockError, setUnlockError] = useState(null)
  // PROMPT 8. The live approval request, if one is waiting on the mail.
  const [pending, setPending] = useState(null)
  // What the mail transport can actually do about in-message buttons, reported
  // by the backend rather than assumed here.
  const [mailCaps, setMailCaps] = useState(null)

  const refreshSession = useCallback(async () => {
    try {
      const response = await adminApi.sessionState()
      setSession(payloadOf(response))
    } catch {
      setSession({ unlocked: false })
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    refreshSession()
  }, [refreshSession])

  /* --------------------------------------------------------------------------
   * PROMPT 8: THE BROWSER CHALLENGE.
   *
   * Minted once per page load and kept in `sessionStorage` — deliberately NOT a
   * cookie and NOT a URL parameter.
   *
   * A cookie would be attached to any cross-site request, so it could not bind an
   * approval to one browser tab; a query parameter would land in the address bar,
   * in `Referer` headers, in proxy logs and in browser history. `sessionStorage`
   * is scoped to this tab and never leaves it, so the value cannot leak, and it
   * dies with the tab.
   *
   * The backend stores only its SHA-256. A value that never leaves the browser and
   * is not recoverable server-side cannot be harvested from a database dump.
   * -------------------------------------------------------------------------- */
  const challengeRef = useRef(null)
  // True once the challenge has arrived. The sign-in form is DISABLED until
  // this is true: submitting without a challenge is exactly what produced the
  // "This sign-in is missing its browser challenge" refusal, and the fix is to
  // guarantee the challenge exists BEFORE the credential is sent rather than
  // to retry after the refusal.
  const [challengeReady, setChallengeReady] = useState(false)

  // The watch survives a reload, so the challenge it was bound with has to
  // survive with it: a fresh challenge on reload would no longer match the
  // stored request's `challenge_hash`, and the poll would answer `unknown` for a
  // request that is perfectly valid. Restored synchronously, before the mount
  // effect can decide to mint a new one.
  const restoredWatchRef = useRef(readWatch())
  if (challengeRef.current === null && restoredWatchRef.current?.challenge) {
    challengeRef.current = restoredWatchRef.current.challenge
  }

  /** Fetch one challenge and hold it in the ref. Called on mount, and again
      immediately before a sign-in in case the minted one failed or the page
      has been sitting open long enough that a fresh bind is safer. */
  const fetchChallenge = useCallback(async () => {
    try {
      const response = await adminApi.challenge()
      // `api.get` resolves to the response BODY, which is `{data: {challenge},
      // message, success}` — a single `data` level, not two. Read through the
      // shared `payloadOf` helper so this cannot drift from the other calls.
      const payload = payloadOf(response)
      const challenge = payload?.challenge
      if (challenge) {
        challengeRef.current = challenge
        setChallengeReady(true)
        return true
      }
      challengeRef.current = null
      setChallengeReady(false)
      return false
    } catch {
      // Without a challenge the sign-in cannot be bound to this browser, and
      // the backend refuses it with an explicit message rather than accepting
      // an unbound approval. Failing here is safe; failing silently is not.
      challengeRef.current = null
      setChallengeReady(false)
      return false
    }
  }, [])

  useEffect(() => {
    // RESUME FIRST. A watch restored from `sessionStorage` means this tab was
    // part-way through a sign-in when the page reloaded, went to sleep or lost
    // the network. Its challenge is the one the stored request was bound with,
    // so it must NOT be replaced by a fresh mint — that would break the binding
    // and make the poll answer `unknown` for a perfectly valid request. Instead
    // the restored watch drives the poll below, which fetches the current status
    // the moment this page is alive again.
    const restored = restoredWatchRef.current
    if (restored?.request_id && restored?.challenge) {
      setChallengeReady(true)
      setPending({
        request_id: restored.request_id,
        expires_in_minutes: restored.expires_in_minutes,
        seconds_remaining: restored.seconds_remaining ?? 0,
        resumed: true,
      })
      return undefined
    }

    let cancelled = false
    ;(async () => {
      const ok = await fetchChallenge()
      if (!cancelled) setChallengeReady(ok)
    })()
    return () => {
      cancelled = true
    }
  }, [fetchChallenge])

  /**
   * WHILE WAITING FOR THE EMAILED DECISION, POLL THIS REQUEST'S OUTCOME.
   *
   * THIS PAGE NEVER NAVIGATES. The approver answers in their own mail client;
   * the decision is recorded on the backend; this poll is how the page that asked
   * learns what happened. There is no separate approval website and no second tab.
   *
   * The poll is scoped by BOTH the request id and the challenge, so it can only
   * ever report on this attempt from this browser - not somebody else's login.
   *
   * 2s feels instant without being noise, and the interval is cleared the moment
   * the wait ends, whichever way it ends.
   *
   * THE SYNC IS RESUMED, NOT RESTARTED. The watch is persisted (see `readWatch`),
   * and `checkOnce` is also fired the instant the tab becomes visible again, the
   * browser comes back online, or the window regains focus. So an approval that
   * arrived while this page was closed, asleep or offline is applied as soon as
   * the page can reach the server again — with no manual refresh and no second
   * access request. A terminal answer clears the stored watch, so a finished
   * request is never resumed.
   */
  useEffect(() => {
    if (!pending?.request_id) return undefined
    const requestId = pending.request_id
    // Captured with the id so the effect does not need to re-run (and restart the
    // interval) when only the countdown ticks.
    const expiresInMinutes = pending.expires_in_minutes
    let stopped = false

    async function checkOnce() {
      let data
      try {
        const response = await adminApi.approvalStatus({
          request_id: requestId,
          challenge: challengeRef.current,
        })
        // ONE unwrap (see `payloadOf`). This was the double-unwrap that stopped a
        // mailed YES from ever being seen here, so the console never opened.
        data = payloadOf(response)
      } catch {
        // Offline, asleep or the server is unreachable. NOT an outcome: the wait
        // continues and the stored watch is left in place, so the next check (on
        // reconnect) picks the request up exactly where it was.
        return
      }
      if (stopped) return

      if (data.status === 'approved') {
        // APPROVED. Spending the approval is a SEPARATE, explicit call: the
        // backend re-checks the status, the mail token and this browser's
        // challenge before it opens anything, so approval in the mail is not by
        // itself access. Only this call is.
        setPending(null)
        clearWatch()
        const spent = await adminApi.consumeApproval(requestId, {
          challenge: challengeRef.current,
        })
        // ONE unwrap, and NO fabricated fallback: the session reported here is
        // the backend's own answer. If it did not open the console, the page
        // must SAY so rather than assume success.
        const opened = payloadOf(spent)
        if (opened?.unlocked) {
          setSession(opened)
          setUnlockError(null)
        } else {
          setSession({ unlocked: false })
          setUnlockError(
            'The approval could not be applied. Sign in again to get a new approval request.',
          )
        }
      } else if (data.status === 'denied') {
        setPending(null)
        clearWatch()
        setSession({ unlocked: false })
        setUnlockError('Access denied — the login was refused from the admin email.')
      } else if (data.status === 'expired') {
        setPending(null)
        clearWatch()
        setSession({ unlocked: false })
        setUnlockError(
          'That approval request expired before it was answered. Sign in again to get a new one.',
        )
      } else if (data.status === 'consumed') {
        // ALREADY SPENT. The approval was used — by this tab earlier, or it was
        // superseded. It can never open a console again, so the wait is over and
        // the stored watch is dropped rather than resumed into a dead end.
        setPending(null)
        clearWatch()
        setSession({ unlocked: false })
        setUnlockError(
          'This approval has already been used. Sign in again to get a new one.',
        )
      } else if (data.status === 'unknown') {
        // The backend will not tell this browser about this request — the
        // challenge did not match, or the row is gone. Stop polling rather than
        // hammering a call that will keep refusing. This is also the honest
        // answer when a request was REVOKED out from under the session.
        setPending(null)
        clearWatch()
        setSession({ unlocked: false })
        setUnlockError(
          'This sign-in could not be verified from this browser. Sign in again.',
        )
      } else {
        // Still pending. Keep the countdown honest AND keep the stored watch
        // fresh, so a reload resumes with an accurate remaining time.
        setPending((previous) =>
          previous ? { ...previous, seconds_remaining: data.seconds_remaining } : previous,
        )
        writeWatch({
          request_id: requestId,
          challenge: challengeRef.current,
          expires_in_minutes: expiresInMinutes,
          seconds_remaining: data.seconds_remaining,
        })
      }
    }

    const id = setInterval(checkOnce, 2000)

    // RESUME TRIGGERS. Each is a moment at which the answer may already exist
    // and the page would not otherwise know: the tab was hidden, the device was
    // offline, or the window was in the background. Firing the check here is
    // what removes the "manual refresh" step after an approval that arrived
    // while the page was not looking.
    const onVisible = () => {
      if (document.visibilityState === 'visible') checkOnce()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('online', checkOnce)
    window.addEventListener('focus', checkOnce)

    // ONE immediate check on mount, so a resumed watch does not wait 2s for its
    // first answer.
    checkOnce()

    return () => {
      stopped = true
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('online', checkOnce)
      window.removeEventListener('focus', checkOnce)
    }
  }, [pending?.request_id])  // eslint-disable-line react-hooks/exhaustive-deps -- keyed on the REQUEST, not on the countdown it carries: re-running on every tick would tear down and rebuild the interval and the reconnect listeners twice a second.

  async function unlock(username, password) {
    setUnlocking(true)
    setUnlockError(null)
    setPending(null)
    try {
      // THE CHALLENGE IS GUARANTEED BEFORE THE CREDENTIAL IS SENT. If the
      // page-load mint failed (or never returned), a fresh one is fetched
      // right here — the old flow sent an empty challenge and the backend
      // answered 400 "missing its browser challenge", which is the exact
      // symptom this removes. A still-failing mint is reported as its own
      // clear error instead of the generic credential message.
      if (!challengeRef.current) {
        const ok = await fetchChallenge()
        if (!ok) {
          setUnlockError(
            'Could not start a sign-in session (the browser challenge could not be issued). Check that the server is reachable and try again.',
          )
          return
        }
      }

      // THE CREDENTIAL IS CHECKED FIRST, ON THE SERVER. Nothing is mailed and no
      // request row is created unless the username and password are both correct,
      // so a wrong password cannot be used to probe for a valid username by
      // watching the admin's inbox.
      const response = await adminApi.requestApproval({
        username,
        password,
        challenge: challengeRef.current,
      })
      const data = payloadOf(response)
      setMailCaps(data.email_capabilities ?? null)

      if (data.mail_sent === false) {
        // The backend could not deliver the approval mail, and it has already
        // closed the request rather than leaving a login to time out silently.
        setUnlockError(
          'The approval email could not be sent, so this sign-in was not accepted. Check the mail settings and try again.',
        )
        return
      }

      const watch = {
        request_id: data.request_id,
        challenge: challengeRef.current,
        expires_in_minutes: data.approval_window_minutes,
        seconds_remaining: (data.approval_window_minutes ?? 15) * 60,
      }
      // PERSIST BEFORE SETTING STATE. The backend has already created and mailed
      // the request, so if this tab reloads (or is closed and reopened) between
      // the mail being sent and the admin answering, the watch must already be on
      // disk for the resumed page to find it. Writing after `setPending` would
      // leave exactly that window uncovered.
      writeWatch(watch)
      setPending(watch)
    } catch (err) {
      setUnlockError(
        errorMessage(err, 'That username or password is not correct.'),
      )
    } finally {
      setUnlocking(false)
    }
  }


  if (checking) {
    return <AdminShell title="Admin console" centered>{<Spinner label="Checking the console…" />}</AdminShell>
  }

  if (!session?.unlocked) {
    return (
      <AdminShell title="Admin console" centered>
        {pending ? (
          <AwaitingApproval pending={pending} capabilities={mailCaps} />
        ) : (
          <LockScreen
            onUnlock={unlock}
            busy={unlocking || !challengeReady}
            error={unlockError}
            challengePending={!challengeReady}
          />
        )}
      </AdminShell>
    )
  }

  return (
    <AdminShell title="Admin console">
      {/* Lock control, always visible while unlocked: the console tells the
          administrator it is open and gives them the one-click way to close it. */}
      <div className="mb-5 flex-wrap items-center justify-between gap-3 rounded-panel border-aqua-500/30 bg-slate-900/70 px-4 py-3 backdrop-blur">
        <p className="flex items-center gap-2 text-xs text-aqua-200">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-2 w-2 animate-ping rounded-full bg-aqua-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-aqua-400" />
          </span>
          Console unlocked
          {session.seconds_remaining ? (
            <span className="text-slate-400">
              · auto-locks in {Math.ceil(session.seconds_remaining / 60)} min
            </span>
          ) : null}
        </p>
        <Button
          variant="secondary"
          className="px-3 py-1.5 text-xs"
          onClick={async () => {
            await adminApi.lockSession()
            // The watch belongs to the sign-in that just ended. Drop it, so a
            // later page load does not try to resume a request the administrator
            // deliberately walked away from.
            clearWatch()
            setPending(null)
            refreshSession()
          }}
        >
          Lock console
        </Button>
      </div>

      <nav className="flex flex-wrap mb-6 gap-2" aria-label="Console sections">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            aria-current={tab === item.key ? 'page' : undefined}
            className={`flex items-center gap-2 rounded-field px-3.5 py-2 text-xs font-medium transition-colors ${tab === item.key
                ? 'bg-aqua-500 text-slate-950 shadow-sm'
                : 'bg-slate-800/70 text-slate-300 hover:bg-black hover:text-white'
              }`}
          >
            <Icon path={item.icon} className="h-3.5 w-3.5" />
            {item.label}
          </button>
        ))}
      </nav>

      {tab === 'dashboard' && <DashboardTab />}
      {tab === 'access' && <AccessTab />}
      {tab === 'users' && <UsersTab />}
      {tab === 'logins' && <LoginDetailsTab />}
      {tab === 'unsafe' && <UnsafeHistoryTab />}
      {tab === 'reportmail' && <ReportEmailAuditTab />}
      {tab === 'reports' && <ReportsTab />}
      {tab === 'parameters' && <ParametersTab />}
      {tab === 'location' && <LocationScopeTab />}
      {tab === 'models' && <ModelsTab />}
      {tab === 'notifications' && <NotificationsTab />}
      {tab === 'system' && <SystemTab />}
    </AdminShell>
  )
}

/**
 * The console's frame: dark, water-themed, with the ambient animation.
 *
 * The animated layers are the console's own "hacking" read — a rising bubble
 * field, a scan sweep and a faint grid — and they are all `aria-hidden` and
 * `pointer-events-none`, so none of them can be announced or clicked.
 */
function AdminShell({ title, children, centered = false }) {
  return (
    <div className={`relative min-h-[80vh] overflow-hidden bg-slate-950 px-4 pb-6 sm:px-6 lg:px-8 -mx-4 -mb-4 -mt-[calc(var(--topbar-h)+1.5rem)] pt-[calc(var(--topbar-h)+1.5rem)] sm:-mx-6 sm:-mb-6 sm:-mt-[calc(var(--topbar-h)+1.5rem)] sm:pt-[calc(var(--topbar-h)+1.5rem)] lg:-mx-8 lg:-mb-8 lg:-mt-[calc(var(--topbar-h)+2rem)] lg:pt-[calc(var(--topbar-h)+2rem)] ${centered ? 'flex flex-col items-center justify-center' : ''}`}>
      {/* The bubble field, rising through the whole console. */}
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        {consoleBubbles().map((bubble) => (
          <span
            key={bubble.id}
            className="absolute bottom-0 block rounded-full border-aqua-400/30 bg-aqua-400/10 motion-safe:[animation:console-bubble_linear_infinite]"
            style={{
              left: `${bubble.left}%`,
              height: `${bubble.size}px`,
              width: `${bubble.size}px`,
              animationDuration: `${bubble.duration}s`,
              animationDelay: `${bubble.delay}s`,
            }}
          />
        ))}
      </div>

      {/* The scan sweep: a single bright band travelling down the console, the
          "being scanned" read that makes the surface feel instrumented. */}
      <span
        className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-aqua-400/10 to-transparent motion-safe:[animation:console-scan_9s_linear_infinite]"
        aria-hidden="true"
      />

      <div className={`relative mx-auto flex flex-col items-center ${centered ? 'max-w-md' : 'w-full max-w-7xl'}`}>
        <header className="mb-6 flex flex-col items-center gap-3 text-center sm:flex-row sm:text-left">
          <span
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-field bg-gradient-to-br from-aqua-400 to-aqua-700 text-slate-950 shadow-lg"
            aria-hidden="true"
          >
            <Icon path={ICONS.droplet} className="h-6 w-6" strokeWidth={2.2} />
          </span>
          <div>
            <p className="text-2xs font-semibold uppercase tracking-[0.22em] text-aqua-400">
              AquaGuard AI · restricted
            </p>
            <h1 className="text-lg font-semibold tracking-tight text-white">{title}</h1>
          </div>
        </header>

        <div className={centered ? 'w-full text-slate-200' : 'text-slate-200'}>{children}</div>
      </div>
    </div>
  )
}

/** Deterministic bubble layout, so the field is stable across renders. */
function consoleBubbles() {
  const PHI = 0.6180339887498949
  return Array.from({ length: 22 }, (_, id) => ({
    id,
    left: Math.round(((id * PHI) % 1) * 100 * 100) / 100,
    size: 5 + ((id * 13) % 22),
    duration: 14 + ((id * 29) % 140) / 10,
    delay: -((id * 41) % 180) / 10,
  }))
}

/**
 * THE WAITING SCREEN — the original login page stays open right here.
 *
 * It says three things and nothing else:
 *
 *   1. a request was sent, and what to do with it;
 *   2. what will ACTUALLY happen when the mail is opened — reported by the
 *      BACKEND, not assumed here, so the screen cannot claim an in-message button
 *      works when the transport has no such facility;
 *   3. how long is left, counting down.
 *
 * There is no link out, no second tab, and nothing to navigate to. The decision
 * is made in the mail and the answer arrives here on its own, which is the whole
 * point: the admin approves from their own inbox, and THIS browser — the one that
 * entered the password — is the one that gets in.
 */
function AwaitingApproval({ pending, capabilities }) {
  const seconds = pending.seconds_remaining ?? 0
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60

  return (
    <div className="mx-auto max-w-md rounded-panel border-aqua-500/40 bg-slate-900/80 p-6 text-center shadow-2xl backdrop-blur">
      <h2 className="text-base font-semibold text-white">Check your email</h2>

      <p className="mt-2 text-xs leading-relaxed text-slate-400">
        Your password was accepted. An approval request was sent to the admin
        address — open it and choose <span className="text-aqua-300">Yes — Approve</span>
        or <span className="text-rose-300">No — Deny</span>. This page updates by
        itself; nothing new will open and there is nothing to do here.
      </p>

      {/* WHAT THE BUTTONS IN THE MAIL ACTUALLY DO.
          Taken from the backend's own capability report rather than written here,
          because only the backend knows which mail transport is configured. This
          is the screen stating the limitation plainly instead of promising an
          in-message button most mail clients cannot run. */}
      {capabilities && (
        <div className="mt-4 rounded-field border border-slate-700 bg-slate-950/60 p-3 text-left">
          <p className="text-2xs font-semibold uppercase tracking-wider text-slate-500">
            How to approve
          </p>
          <p className="mt-1.5 text-2xs leading-relaxed text-slate-400">
            {capabilities.mechanism}
          </p>
          {!capabilities.interactive_actions_supported && (
            <p className="mt-1.5 text-2xs leading-relaxed text-slate-500">
              {capabilities.limitation}
            </p>
          )}
        </div>
      )}

      <p className="mt-5 animate-pulse text-xs text-aqua-300">
        Waiting for your decision…
      </p>

      {seconds > 0 && (
        <p className="mt-1.5 text-2xs tabular text-slate-500">
          This request expires in {minutes}:{String(rest).padStart(2, '0')}
        </p>
      )}
    </div>
  )
}

/**
 * The console sign-in screen.
 *
 * TWO FIELDS, ALWAYS. The console asks for its own USERNAME AND PASSWORD. The
 * username is checked with the password server-side, so a wrong name and a wrong
 * password fail identically and neither half is revealed by the response.
 *
 * FORGOT PASSWORD. "Forgot password?" switches the same card to a three-step
 * flow:
 *
 *   1. press to mail a 6-digit code to the recovery address
 *   2. type the code here, in a field on this page — no navigation away
 *   3. choose the new password; the code is consumed on success
 *
 * The code is never returned by the API (it is mailed), so the field is genuinely
 * required input rather than a formality, and it is single-use with a 15-minute
 * expiry and a limited number of guesses.
 *
 * UNCHANGED BY PROMPT 8. The console credential is still entered here and still
 * verified here; only what happens AFTER a correct credential moved to the
 * approval request. This component, its fields, its steps and its styling are the
 * existing login page exactly as they were.
 */
export function LockScreen({ onUnlock, busy, error, challengePending = false }) {
  // 'signin' | 'request' | 'verify'
  const [mode, setMode] = useState('signin')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  // Forgot-password state.
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [notice, setNotice] = useState(null)
  const [flowError, setFlowError] = useState(null)
  const [working, setWorking] = useState(false)

  async function requestCode() {
    setWorking(true)
    setFlowError(null)
    setNotice(null)
    try {
      const response = await adminApi.forgotPassword()
      const data = payloadOf(response)
      const destination = data.sent_to
      // PROMPT 9, requirement 13: only claim "sent" because the backend already
      // refused to return success on a failed delivery — reaching here means the
      // mail service accepted the message.
      setNotice(
        destination
          ? `A 6-digit code has been sent to ${destination}. It expires in ${data.expires_in_minutes ?? 15} minutes.`
          : 'A 6-digit code has been sent. It expires in 15 minutes.',
      )
      setMode('verify')
    } catch (err) {
      // A delivery failure surfaces its real detail and the cooldown is waived
      // server-side, so retrying right away is genuinely possible.
      setFlowError(errorMessage(err, 'The reset code could not be sent.'))
    } finally {
      setWorking(false)
    }
  }

  /**
   * PROMPT 10, requirement 2. The login card already holds a username and a
   * password. This authentication model does not permit verifying the password
   * at the moment recovery starts — the code is mailed BEFORE any new password
   * exists — so no credential check happens here and nothing about the password
   * is validated or reported. The password field is RETAINED exactly as the
   * requirement asks, and the recovery identifier (the registered email the
   * backend resolves from this console's account) is validated on the BACKEND,
   * never in the browser. The only client-side gate is that the username field
   * must be filled, so the recovery step cannot be started half-typed.
   */
  function startForgotPassword() {
    if (!username.trim()) {
      setFlowError('Enter your admin username first, then press Forgot password.')
      return
    }
    setFlowError(null)
    setNotice(
      'Your password field is kept as it is — it is not checked during recovery. ' +
      'A code will be sent to the registered email address on record for this account.',
    )
    setMode('request')
  }

  async function resetPassword() {
    if (newPassword !== confirmPassword) {
      setFlowError('The two passwords do not match.')
      return
    }
    setWorking(true)
    setFlowError(null)
    try {
      await adminApi.resetPassword({ code, new_password: newPassword })
      // Back to sign-in, with the new password: the code is now spent and the
      // console is still locked, so proving the new credential is the next step.
      setMode('signin')
      setCode('')
      setNewPassword('')
      setConfirmPassword('')
      setNotice('Your password has been changed. Sign in with the new password.')
    } catch (err) {
      setFlowError(errorMessage(err, 'That code could not be applied.'))
    } finally {
      setWorking(false)
    }
  }

  const inputClass =
    'w-full rounded-field border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white placeholder:text-slate-500 focus:border-aqua-400 focus:outline-none focus:ring-2 focus:ring-aqua-400/30'
  const primaryButton =
    'mt-4 flex w-full items-center justify-center gap-2 rounded-field bg-aqua-500 px-4 py-2.5 text-sm font-semibold text-slate-950 transition-colors hover:bg-aqua-400 disabled:opacity-50'

  return (
    <div className="mx-auto max-w-md">
      <div className="rounded-panel border-aqua-500/40 bg-slate-900/80 p-6 shadow-2xl backdrop-blur">
        <span
          className="mx-auto flex h-14 w-14 items-center justify-center rounded-field bg-aqua-500/15 text-aqua-300 ring-1 ring-aqua-400/40"
          aria-hidden="true"
        >
          <Icon path="M12 15v2m-6 4h12a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2Zm3-10V7a3 3 0 0 1 6 0v2" className="h-7 w-7" strokeWidth={2} />
        </span>

        {mode === 'signin' && (
          <>
            <h2 className="mt-4 text-center text-base font-semibold text-white">
              Admin console sign-in
            </h2>
            <form
              className="mt-5"
              onSubmit={(event) => {
                event.preventDefault()
                onUnlock(username, password)
                setPassword('')
              }}
            >
              <label className="sr-only" htmlFor="admin-console-username">
                Admin username
              </label>
              <input
                id="admin-console-username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="Admin username"
                className={inputClass}
              />

              <label className="sr-only" htmlFor="admin-console-password">
                Admin console password
              </label>
              <input
                id="admin-console-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Admin console password"
                className={`mt-3 ${inputClass}`}
              />

              {(error || flowError) && (
                <p role="alert" className="mt-3 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
                  {error || flowError}
                </p>
              )}
              {notice && !error && !flowError && (
                <p role="status" className="mt-3 rounded-field bg-aqua-500/15 px-3 py-2 text-xs text-aqua-200">
                  {notice}
                </p>
              )}

              <button
                type="submit"
                disabled={busy || !username || !password}
                className={primaryButton}
              >
                {busy ? (challengePending ? 'Preparing sign-in…' : 'Signing in…') : 'Sign in'}
              </button>
            </form>

            <button
              type="button"
              onClick={startForgotPassword}
              className="mt-3 w-full text-center text-xs font-medium text-aqua-300 transition-colors hover:text-white"
            >
              Forgot password?
            </button>
          </>
        )}

        {mode === 'request' && (
          <>
            <h2 className="mt-4 text-center text-base font-semibold text-white">
              Reset the console password
            </h2>
            <p className="mt-1 text-center text-xs text-slate-400">
              A 6-digit code will be emailed to the console&rsquo;s recovery address.
              Enter it here to set a new password.
            </p>

            {flowError && (
              <p role="alert" className="mt-4 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
                {flowError}
              </p>
            )}

            <button
              type="button"
              disabled={working}
              onClick={requestCode}
              className={primaryButton}
            >
              {working ? 'Sending…' : 'Email me a code'}
            </button>
            <button
              type="button"
              onClick={() => setMode('signin')}
              className="mt-3 w-full text-center text-xs font-medium text-slate-400 transition-colors hover:text-white"
            >
              Back to sign-in
            </button>
          </>
        )}

        {mode === 'verify' && (
          <>
            <h2 className="mt-4 text-center text-base font-semibold text-white">
              Enter your code
            </h2>
            {notice && (
              <p role="status" className="mt-2 rounded-field bg-aqua-500/15 px-3 py-2 text-xs text-aqua-200">
                {notice}
              </p>
            )}

            <form
              className="mt-4"
              onSubmit={(event) => {
                event.preventDefault()
                resetPassword()
              }}
            >
              <label className="sr-only" htmlFor="admin-reset-code">
                6-digit reset code
              </label>
              <input
                id="admin-reset-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
                placeholder="6-digit code"
                className={`${inputClass} text-center font-mono text-lg tracking-[0.5em]`}
              />

              <label className="sr-only" htmlFor="admin-new-password">
                New password
              </label>
              <input
                id="admin-new-password"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                placeholder="New password"
                className={`mt-3 ${inputClass}`}
              />

              <label className="sr-only" htmlFor="admin-confirm-password">
                Confirm new password
              </label>
              <input
                id="admin-confirm-password"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder="Confirm new password"
                className={`mt-3 ${inputClass}`}
              />

              {flowError && (
                <p role="alert" className="mt-3 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
                  {flowError}
                </p>
              )}

              <button
                type="submit"
                disabled={working || code.length !== 6 || newPassword.length < 8}
                className={primaryButton}
              >
                {working ? 'Saving…' : 'Set new password'}
              </button>
            </form>

            <div className="mt-3 flex justify-between text-xs">
              <button
                type="button"
                onClick={requestCode}
                disabled={working}
                className="font-medium text-aqua-300 transition-colors hover:text-white disabled:opacity-50"
              >
                Send a new code
              </button>
              <button
                type="button"
                onClick={() => setMode('signin')}
                className="font-medium text-slate-400 transition-colors hover:text-white"
              >
                Back to sign-in
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/** A console-styled surface. The app's own `card` is light, which would break the
 *  one rule this page has: nothing here should look like the user-facing app. */
function Panel({ title, subtitle, actions, children, className = '' }) {
  return (
    <section
      className={`rounded-panel border-slate-700/60 bg-slate-900/70 shadow-xl backdrop-blur ${className}`}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-700/60 px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-white">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

/** Shared loading/error/empty wrapper. */
function Section({ loading, error, onRetry, empty, emptyText, children }) {
  if (loading) return <Spinner label="Loading…" />
  if (error) return <ErrorState message={error} onRetry={onRetry} />
  if (empty) {
    return (
      <EmptyState
        title="Nothing here yet"
        description={emptyText}
        icon={<Icon path={ICONS.info} className="h-7 w-7" />}
      />
    )
  }
  return children
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
function DashboardTab() {
  const summary = useApi(() => adminApi.dashboard(), [])
  const counters = summary.data?.data ?? summary.data ?? {}

  const tiles = [
    { label: 'Accounts', value: counters.users, tone: 'text-aqua-300' },
    { label: 'Administrators', value: counters.admins, tone: 'text-aqua-300' },
    { label: 'Predictions', value: counters.predictions, tone: 'text-white' },
    { label: 'Safe', value: counters.safe, tone: 'text-safe-light' },
    { label: 'Warning', value: counters.moderate, tone: 'text-caution-light' },
    { label: 'Unsafe', value: counters.unsafe, tone: 'text-unsafe-light' },
    { label: 'Alerts', value: counters.alerts, tone: 'text-unsafe-light' },
    { label: 'Sign-ins', value: counters.signins, tone: 'text-white' },
    { label: 'Failed sign-ins', value: counters.failed_signins, tone: 'text-unsafe-light' },
  ]

  return (
    <Section
      loading={summary.loading}
      error={summary.error}
      onRetry={summary.refetch}
      empty={false}
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {tiles.map((tile) => (
          <div
            key={tile.label}
            className="rounded-panel border-slate-700/60 bg-slate-900/70 px-4 py-4 backdrop-blur"
          >
            <p className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
              {tile.label}
            </p>
            <p className={`mt-2 text-2xl font-semibold tabular ${tile.tone}`}>
              {summary.loading ? '—' : (tile.value ?? 0)}
            </p>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ---------------------------------------------------------------------------
// Admin access (console identity)
// ---------------------------------------------------------------------------
/**
 * The console's own credentials — its login name and where a reset code goes.
 *
 * This is a separate tab because both values are about GETTING IN, not about the
 * data the console administers. Changing the recovery email redirects the whole
 * forgot-password path, so it belongs beside the username rather than buried in
 * general settings.
 */
function AccessTab() {
  const identity = useApi(() => adminApi.identity(), [])
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(null)

  // PROMPT 9, requirement 10: verified email change. A separate address can be
  // registered, but it only becomes active after its own inbox confirms a code.
  const [changeMode, setChangeMode] = useState('idle') // idle | code-sent
  const [pendingEmail, setPendingEmail] = useState('')
  const [verifyCode, setVerifyCode] = useState('')
  const [changeStatus, setChangeStatus] = useState(null)
  const [changeWorking, setChangeWorking] = useState(false)

  const current = identity.data?.data ?? identity.data ?? {}

  // Seed the fields from the server once, without clobbering anything the admin
  // has already started typing (the effect only runs when the value arrives).
  useEffect(() => {
    if (current.username != null) setUsername((v) => v || current.username)
    if (current.email != null) setEmail((v) => v || current.email)
  }, [current.username, current.email])

  async function save(event) {
    event.preventDefault()
    setSaving(true)
    setStatus(null)
    try {
      await adminApi.updateIdentity({ username, email })
      // PROMPT 9, requirement 11: the backend re-syncs the approval address to
      // the recovery address whenever this form saves an email, so the two
      // settings never disagree silently.
      setStatus({
        ok: true,
        message: 'Console identity updated. Login approvals will go to the same address.',
      })
      identity.refetch()
    } catch (err) {
      setStatus({ ok: false, message: errorMessage(err, 'That could not be saved.') })
    } finally {
      setSaving(false)
    }
  }

  /** Send the verification code to the NEW address, or re-sync in one click. */
  async function startEmailChange(payload) {
    setChangeWorking(true)
    setChangeStatus(null)
    try {
      const response = await adminApi.requestEmailChange(payload)
      const data = (response.data ?? response).data ?? {}
      if (data.mode === 'synced_to_recovery') {
        setChangeMode('idle')
        setChangeStatus({ ok: true, message: 'Login approvals now go to the recovery address.' })
        identity.refetch()
      } else {
        setPendingEmail(data.sent_to ?? '')
        setChangeMode('code-sent')
        setChangeStatus({ ok: true, message: `A verification code was sent to ${data.sent_to}.` })
      }
    } catch (err) {
      setChangeStatus({ ok: false, message: errorMessage(err, 'That could not be sent.') })
    } finally {
      setChangeWorking(false)
    }
  }

  /** Activate the pending change with the code the new inbox received. */
  async function confirmEmailChange(event) {
    event.preventDefault()
    setChangeWorking(true)
    setChangeStatus(null)
    try {
      await adminApi.confirmEmailChange({ code: verifyCode })
      setChangeMode('idle')
      setVerifyCode('')
      setChangeStatus({ ok: true, message: 'The new email address is verified and active.' })
      identity.refetch()
    } catch (err) {
      setChangeStatus({ ok: false, message: errorMessage(err, 'That code could not be verified.') })
    } finally {
      setChangeWorking(false)
    }
  }

  return (
    <Panel
      title="Admin access"
      subtitle="The username and recovery address this console signs in with. Changing the email redirects where a password-reset code is sent."
    >
      <Section loading={identity.loading} error={identity.error} onRetry={identity.refetch}>
        <form className="max-w-md space-y-4" onSubmit={save}>
          <label className="block text-2xs uppercase tracking-wider text-slate-400">
            Console username
            <input
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="mt-1 block w-full rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-aqua-400 focus:outline-none"
            />
          </label>

          <label className="block text-2xs uppercase tracking-wider text-slate-400">
            Recovery email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1 block w-full rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-aqua-400 focus:outline-none"
            />
          </label>

          <p className="text-xs text-slate-400">
            A password-reset code is mailed to this address. It is not shown to
            anyone else and is never returned by the API. Saving an email here
            also re-points login approvals to the same address.
          </p>

          {status && (
            <p
              role="status"
              className={`rounded-field px-3 py-2 text-xs ${status.ok ? 'bg-safe/15 text-safe-light' : 'bg-unsafe/15 text-unsafe-light'}`}
            >
              {status.message}
            </p>
          )}

          <Button type="submit" loading={saving} className="px-4 py-2 text-xs">
            Save changes
          </Button>
        </form>

        {/* PROMPT 9, requirement 10: a SEPARATE approval mailbox, verified first. */}
        <div className="mt-6 border-t border-slate-800 pt-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-300">
            Login approval email
          </h3>
          <p className="mt-1 text-xs text-slate-400">
            Where login-approval requests are sent. Same as the recovery address
            by default; a different address must confirm a code from its own
            inbox before it becomes active.
          </p>

          {changeMode === 'idle' && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input
                type="email"
                value={pendingEmail}
                onChange={(event) => setPendingEmail(event.target.value)}
                placeholder="new-approver@example.com"
                className="min-w-[220px] flex-1 rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-aqua-400 focus:outline-none"
              />
              <Button
                type="button"
                loading={changeWorking}
                disabled={!pendingEmail}
                onClick={() => startEmailChange({ new_email: pendingEmail })}
                className="px-4 py-2 text-xs"
              >
                Send verification code
              </Button>
              <button
                type="button"
                disabled={changeWorking}
                onClick={() => startEmailChange({ same_as_recovery: true })}
                className="text-xs font-medium text-aqua-300 transition-colors hover:text-white disabled:opacity-50"
              >
                Use the recovery address
              </button>
            </div>
          )}

          {changeMode === 'code-sent' && (
            <form className="mt-3 flex flex-wrap items-center gap-2" onSubmit={confirmEmailChange}>
              <input
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={verifyCode}
                onChange={(event) => setVerifyCode(event.target.value.replace(/\D/g, ''))}
                placeholder="6-digit code"
                className="w-40 rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-center font-mono text-sm tracking-[0.4em] text-white focus:border-aqua-400 focus:outline-none"
              />
              <Button type="submit" loading={changeWorking} disabled={verifyCode.length !== 6} className="px-4 py-2 text-xs">
                Verify &amp; activate
              </Button>
              <button
                type="button"
                onClick={() => { setChangeMode('idle'); setVerifyCode('') }}
                className="text-xs font-medium text-slate-400 transition-colors hover:text-white"
              >
                Cancel
              </button>
            </form>
          )}

          {changeStatus && (
            <p
              role="status"
              className={`mt-3 rounded-field px-3 py-2 text-xs ${changeStatus.ok ? 'bg-safe/15 text-safe-light' : 'bg-unsafe/15 text-unsafe-light'}`}
            >
              {changeStatus.message}
            </p>
          )}
        </div>
      </Section>
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
function UsersTab() {
  const [search, setSearch] = useState('')
  const [actionError, setActionError] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [confirmId, setConfirmId] = useState(null)

  const users = useApi(() => adminApi.users({ search: search || undefined }), [search])
  const rows = users.data?.data ?? users.data ?? []

  async function remove(row) {
    setBusyId(row.id)
    setActionError(null)
    try {
      await adminApi.deleteUser(row.id)
      setConfirmId(null)
      users.refetch()
    } catch (err) {
      setActionError(errorMessage(err, 'That account could not be removed.'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <Panel
      title="User management"
      subtitle="Every registered account. Removing one deletes its readings, alerts and history with it."
      actions={
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search name or email"
          className="w-56 rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white placeholder:text-slate-500 focus:border-aqua-400 focus:outline-none"
        />
      }
    >
      {actionError && (
        <p role="alert" className="mb-4 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
          {actionError}
        </p>
      )}

      <Section
        loading={users.loading}
        error={users.error}
        onRetry={users.refetch}
        empty={rows.length === 0}
        emptyText="No accounts match that search."
      >
        <div className="-mx-5 overflow-x-auto">
          <table className="w-full min-w-[46rem] text-sm">
            <thead>
              <tr className="border-b border-slate-700/60 text-left text-2xs uppercase tracking-wider text-slate-400">
                <th className="px-5 py-2.5">Name</th>
                <th className="px-3 py-2.5">Email</th>
                <th className="px-3 py-2.5">Role</th>
                <th className="px-3 py-2.5">Readings</th>
                <th className="px-3 py-2.5">Joined</th>
                <th className="px-5 py-2.5 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-slate-800/60 transition-colors hover:bg-black/60 hover:text-white"
                >
                  <td className="px-5 py-3 font-medium text-white">{row.name}</td>
                  <td className="px-3 py-3 text-slate-300">{row.email}</td>
                  <td className="px-3 py-3">
                    <Badge tone={row.role === 'admin' ? 'aqua' : 'slate'}>{row.role}</Badge>
                  </td>
                  <td className="px-3 py-3 tabular text-slate-300">{row.prediction_count}</td>
                  <td className="px-3 py-3 text-xs text-slate-400">{formatDate(row.created_at)}</td>
                  <td className="px-5 py-3 text-right">
                    {/* Two steps, because this is irreversible and the cascade
                        takes the account's whole history with it. */}
                    {confirmId === row.id ? (
                      <span className="inline-flex gap-2">
                        <button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => remove(row)}
                          className="rounded-field bg-unsafe px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-unsafe-dark disabled:opacity-50"
                        >
                          {busyId === row.id ? 'Removing…' : 'Confirm remove'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmId(null)}
                          className="rounded-field px-2.5 py-1.5 text-xs text-slate-300 hover:text-white"
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        // The shared visitor record is refused by the API as
                        // well - it owns everything submitted without a sign-in -
                        // so this is an affordance, not the actual guard.
                        disabled={row.email === VISITOR_EMAIL}
                        title={
                          row.email === VISITOR_EMAIL
                            ? 'The shared visitor record cannot be deleted'
                            : 'Remove this account'
                        }
                        onClick={() => setConfirmId(row.id)}
                        className="rounded-field border-unsafe/50 px-2.5 py-1.5 text-xs font-medium text-unsafe-light transition-colors hover:bg-unsafe/20 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Login details
// ---------------------------------------------------------------------------
function LoginDetailsTab() {
  const [search, setSearch] = useState('')
  const [success, setSuccess] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)

  const params = {
    search: search || undefined,
    success: success || undefined,
    start: start || undefined,
    end: end || undefined,
  }

  const stats = useApi(() => adminApi.loginDetailsStats(), [])
  const rows = useApi(() => adminApi.loginDetails(params), [search, success, start, end])

  const items = rows.data?.data ?? rows.data ?? []
  const counters = stats.data?.data ?? stats.data ?? {}

  async function download(format) {
    setExporting(true)
    setExportError(null)
    try {
      const response = await adminApi.exportLoginDetails({ ...params, format })
      const blob = response.data instanceof Blob ? response.data : new Blob([response.data])
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `aquaguard-login-details-${Date.now()}.csv`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (err) {
      setExportError(errorMessage(err, 'The export could not be downloaded.'))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-4">
        {[
          { label: 'Total sign-ins', value: counters.total },
          { label: 'Today', value: counters.today },
          { label: 'Failed', value: counters.failed },
          { label: 'Distinct accounts', value: counters.unique_users },
        ].map((tile) => (
          <div key={tile.label} className="rounded-panel border-slate-700/60 bg-slate-900/70 px-4 py-3">
            <p className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
              {tile.label}
            </p>
            <p className="mt-1.5 text-xl font-semibold tabular text-aqua-300">
              {stats.loading ? '—' : (tile.value ?? 0)}
            </p>
          </div>
        ))}
      </div>

      <Panel
        title="Login details"
        subtitle="Every sign-in attempt, successful or not, with the account it belongs to."
        actions={
          <>
            <Button
              variant="secondary"
              className="px-3 py-1.5 text-xs"
              disabled={exporting}
              onClick={() => download('csv')}
            >
              {exporting ? 'Preparing…' : 'Download CSV'}
            </Button>
            <Button
              variant="secondary"
              className="px-3 py-1.5 text-xs"
              disabled={exporting}
              onClick={() => download('xlsx')}
            >
              Download for Excel
            </Button>
          </>
        }
      >
        <div className="mb-4 flex-wrap items-end gap-3">
          <label className="text-2xs uppercase tracking-wider text-slate-400">
            Search
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name or email"
              className="mt-1 block w-52 rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white placeholder:text-slate-500 focus:border-aqua-400 focus:outline-none"
            />
          </label>
          <label className="text-2xs uppercase tracking-wider text-slate-400">
            Result
            <select
              value={success}
              onChange={(event) => setSuccess(event.target.value)}
              className="mt-1 block rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
            >
              <option value="">All</option>
              <option value="true">Succeeded</option>
              <option value="false">Failed</option>
            </select>
          </label>
          <label className="text-2xs uppercase tracking-wider text-slate-400">
            From
            <input
              type="date"
              value={start}
              onChange={(event) => setStart(event.target.value)}
              className="mt-1 block rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
            />
          </label>
          <label className="text-2xs uppercase tracking-wider text-slate-400">
            To
            <input
              type="date"
              value={end}
              onChange={(event) => setEnd(event.target.value)}
              className="mt-1 block rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
            />
          </label>
        </div>

        {exportError && (
          <p role="alert" className="mb-4 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
            {exportError}
          </p>
        )}

        <Section
          loading={rows.loading}
          error={rows.error}
          onRetry={rows.refetch}
          empty={items.length === 0}
          emptyText="No sign-in events match these filters yet."
        >
          <div className="-mx-5 overflow-x-auto">
            <table className="w-full min-w-[48rem] text-sm">
              <thead>
                <tr className="border-b border-slate-700/60 text-left text-2xs uppercase tracking-wider text-slate-400">
                  <th className="px-5 py-2.5">Username</th>
                  <th className="px-3 py-2.5">Email</th>
                  <th className="px-3 py-2.5">Result</th>
                  <th className="px-3 py-2.5">Device</th>
                  <th className="px-3 py-2.5">IP</th>
                  <th className="px-5 py-2.5">Date &amp; time</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className="border-b border-slate-800/60 transition-colors hover:bg-black/60 hover:text-white"
                  >
                    {/* The username is joined server-side, so it travels with
                        the row rather than being looked up per line here. */}
                    <td className="px-5 py-3 font-medium text-white">{item.user_name}</td>
                    <td className="px-3 py-3 text-slate-300">{item.user_email}</td>
                    <td className="px-3 py-3">
                      <Badge tone={item.success ? 'safe' : 'unsafe'}>
                        {item.success ? 'Success' : 'Failed'}
                      </Badge>
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-400">{item.device || '—'}</td>
                    <td className="px-3 py-3 font-mono text-xs text-slate-400">
                      {item.ip_address || '—'}
                    </td>
                    <td className="px-5 py-3 text-xs tabular text-slate-300">
                      {formatDate(item.created_at, { dateStyle: 'medium', timeStyle: 'medium' })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </Panel>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// PROMPT 12: Report-email audit tab
// ---------------------------------------------------------------------------
const REPORT_MAIL_OPTION_LABELS = {
  REPORT_PDF: 'Single report (PDF)',
  REPORT_CSV: 'Single report (CSV)',
  ALL_PDF: 'All reports (PDF)',
  ALL_CSV: 'All reports (CSV)',
}

const REPORT_MAIL_STATUS_LABELS = {
  sent: 'Sent',
  failed: 'Failed',
  suppressed: 'Suppressed',
  disabled: 'Disabled',
  unconfigured: 'Unconfigured',
}

/**
 * The audit table's status cell. Each delivery state is a real state with its
 * own tone, so "provider accepted" (sent) is never styled like a suppression
 * or an outright failure.
 */
function mailStatusTone(status) {
  if (status === 'sent') return 'safe'
  if (status === 'failed') return 'unsafe'
  return 'moderate'
}

/**
 * UNSAFE PREDICTION HISTORY — a separate console section holding ONLY the rows
 * the model judged UNSAFE.
 *
 * THE FILTER IS THE BACKEND'S, NOT THE BROWSER'S. `adminApi.unsafeHistory()`
 * asks `/admin/unsafe-history`, whose SQL selects `prediction = 'unsafe'` — so
 * this lists every unsafe reading in the console's scope, and the count is the
 * real number of unsafe readings rather than the unsafe rows that happened to
 * land on a fetched page. The browser never receives a mixed set it must sift,
 * and it never invents a row: every column is the stored value, or "—".
 *
 * THE REQUIRED COLUMNS, in the order the brief lists them: Prediction ID,
 * Location, District, State, Country, Pincode, Water source, the five measured
 * Parameters, Confidence, and the exact Date and Time.
 */
function UnsafeHistoryTab() {
  const [search, setSearch] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [page, setPage] = useState(1)

  // A page number from a previous filter is meaningless against new filters.
  useEffect(() => {
    setPage(1)
  }, [search, start, end])

  const params = {
    search: search || undefined,
    start: start || undefined,
    end: end || undefined,
    page,
    per_page: 20,
  }

  const rows = useApi(
    () => adminApi.unsafeHistory(params),
    [search, start, end, page],
  )

  const items = rows.data?.data ?? rows.data ?? []
  const meta = rows.data?.meta ?? {}
  const scopeMode = meta.scope?.mode || null
  const totalPages = meta.pages || 0

  return (
    <Panel
      title="Unsafe Prediction History"
      subtitle="Every reading the model judged UNSAFE, filtered in the database. The count below is the real number of unsafe readings, not a page of mixed results."
    >
      {/* A standing count, so the section states its own size. `meta.total` is
          the SQL count of unsafe rows, not the length of the fetched page. */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <span className="rounded-field border-unsafe/40 bg-unsafe/10 px-3 py-1.5 text-xs font-semibold text-unsafe-light">
          {meta.total ?? '—'} unsafe prediction{meta.total === 1 ? '' : 's'} recorded
        </span>
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-2xs uppercase tracking-wider text-slate-400">
          Search
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Location, district, state, country or pincode"
            className="mt-1 block w-64 rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white placeholder:text-slate-500 focus:border-aqua-400 focus:outline-none"
          />
        </label>
        <label className="text-2xs uppercase tracking-wider text-slate-400">
          From
          <input
            type="date"
            value={start}
            onChange={(event) => setStart(event.target.value)}
            className="mt-1 block rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
          />
        </label>
        <label className="text-2xs uppercase tracking-wider text-slate-400">
          To
          <input
            type="date"
            value={end}
            onChange={(event) => setEnd(event.target.value)}
            className="mt-1 block rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
          />
        </label>
      </div>

      {scopeMode && (
        <p className="mb-3 rounded-field bg-aqua-400/10 px-3 py-2 text-xs text-aqua-200">
          Location scope active ({scopeMode}): unsafe records outside the configured scope are withheld.
        </p>
      )}

      <Section
        loading={rows.loading}
        error={rows.error}
        onRetry={rows.refetch}
        empty={items.length === 0}
        emptyText="No unsafe predictions match these filters. That is the good outcome — nothing unsafe has been recorded in this scope."
      >
        <div className="-mx-5 overflow-x-auto">
          <table className="w-full min-w-[76rem] text-sm">
            <thead>
              <tr className="border-b border-slate-700/60 text-left text-2xs uppercase tracking-wider text-slate-400">
                <th className="px-5 py-2.5">Prediction ID</th>
                <th className="px-3 py-2.5">Location</th>
                <th className="px-3 py-2.5">District</th>
                <th className="px-3 py-2.5">State</th>
                <th className="px-3 py-2.5">Country</th>
                <th className="px-3 py-2.5">Pincode</th>
                <th className="px-3 py-2.5">Water source</th>
                {PARAMETER_ORDER.map((key) => (
                  <th key={key} className="px-3 py-2.5">
                    {NORMAL_LEVELS[key]?.symbol || NORMAL_LEVELS[key]?.label || key}
                  </th>
                ))}
                <th className="px-3 py-2.5">Confidence</th>
                <th className="px-3 py-2.5">Date</th>
                <th className="px-5 py-2.5">Time</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  className="border-b border-slate-800/60 align-top transition-colors hover:bg-black/60 hover:text-white"
                >
                  <td className="whitespace-nowrap px-5 py-3 font-mono text-xs text-slate-200">
                    {item.prediction_id || `PRED-${String(item.id).padStart(5, '0')}`}
                    <Badge tone="unsafe" className="ml-2">UNSAFE</Badge>
                  </td>
                  {/* The place as stored. A record with no location says so
                      rather than borrowing another row's place. */}
                  <td className="px-3 py-3 text-xs text-slate-300">
                    {item.location_name || item.location_city || item.location_area || (
                      <span className="text-slate-500">Not recorded</span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-300">{item.location_district || '—'}</td>
                  <td className="px-3 py-3 text-xs text-slate-300">{item.location_state || '—'}</td>
                  <td className="px-3 py-3 text-xs text-slate-300">{item.location_country || '—'}</td>
                  <td className="px-3 py-3 text-xs tabular text-slate-300">
                    {item.location_pincode || '—'}
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-300">{waterSourceLabel(item)}</td>
                  {PARAMETER_ORDER.map((key) => (
                    <td key={key} className="px-3 py-3 text-xs tabular text-slate-300">
                      {formatNumber(item[key])}
                    </td>
                  ))}
                  <td className="px-3 py-3 text-xs tabular text-slate-200">
                    {formatPercent(item.confidence)}
                  </td>
                  {/* THE STORED INSTANT, split into its two parts — the same
                      `created_at` the History page and the PDF print. */}
                  <td className="whitespace-nowrap px-3 py-3 text-xs tabular text-slate-300">
                    {formatPredictionStamp(item.created_at).date}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-xs tabular text-slate-300">
                    {formatPredictionStamp(item.created_at).time}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
            <span>
              Page {meta.page ?? page} of {totalPages} · {meta.total ?? '—'} unsafe records
            </span>
            <span className="flex gap-2">
              <Button
                variant="secondary"
                className="px-3 py-1.5 text-xs"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                className="px-3 py-1.5 text-xs"
                disabled={!meta.has_next}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </span>
          </div>
        )}
      </Section>
    </Panel>
  )
}

function ReportEmailAuditTab() {
  const [search, setSearch] = useState('')
  const [option, setOption] = useState('')
  const [status, setStatus] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [page, setPage] = useState(1)

  // Reset to page 1 whenever a filter changes: a page number from a previous
  // result set is meaningless against new filters.
  useEffect(() => {
    setPage(1)
  }, [search, option, status, start, end])

  const params = {
    search: search || undefined,
    option: option || undefined,
    status: status || undefined,
    start: start || undefined,
    end: end || undefined,
    page,
    per_page: 20,
  }

  const rows = useApi(
    () => adminApi.reportEmailAudit(params),
    [search, option, status, start, end, page],
  )

  const items = rows.data?.data ?? rows.data ?? []
  const meta = rows.data?.meta ?? {}
  const scopeMode = meta.scope?.mode || null
  const totalPages = meta.pages || 0

  function locationText(item) {
    // Requirement 4/5: never fabricate. When no consented location was
    // recorded, say so plainly — no guessed city, no IP-derived substitute.
    const loc = item.location || {}
    if (!loc.available) return 'Location unavailable'
    const parts = [loc.name, loc.city, loc.state, loc.country].filter(Boolean)
    const label = parts.join(', ') || 'Location unavailable'
    return loc.pincode ? `${label} · ${loc.pincode}` : label
  }

  function requesterText(item) {
    if (item.admin_username) return `Admin: ${item.admin_username}`
    if (item.requester_name) return item.requester_name
    return '—'
  }

  return (
    <Panel
      title="Report Email Activity"
      subtitle="Every Reports-to-Mail request: the recipient, the report option, the real delivery outcome and the requester. Location appears only when the requester's browser granted it — otherwise 'Location unavailable'."
    >
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-2xs uppercase tracking-wider text-slate-400">
          Search
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Recipient, requester or location"
            className="mt-1 block w-56 rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white placeholder:text-slate-500 focus:border-aqua-400 focus:outline-none"
          />
        </label>
        <label className="text-2xs uppercase tracking-wider text-slate-400">
          Report type
          <select
            value={option}
            onChange={(event) => setOption(event.target.value)}
            className="mt-1 block rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
          >
            <option value="">All types</option>
            {Object.entries(REPORT_MAIL_OPTION_LABELS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </label>
        <label className="text-2xs uppercase tracking-wider text-slate-400">
          Delivery status
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="mt-1 block rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
          >
            <option value="">All statuses</option>
            {Object.entries(REPORT_MAIL_STATUS_LABELS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </label>
        <label className="text-2xs uppercase tracking-wider text-slate-400">
          From
          <input
            type="date"
            value={start}
            onChange={(event) => setStart(event.target.value)}
            className="mt-1 block rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
          />
        </label>
        <label className="text-2xs uppercase tracking-wider text-slate-400">
          To
          <input
            type="date"
            value={end}
            onChange={(event) => setEnd(event.target.value)}
            className="mt-1 block rounded-field border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
          />
        </label>
      </div>

      {scopeMode && (
        <p className="mb-3 rounded-field bg-aqua-400/10 px-3 py-2 text-xs text-aqua-200">
          Location scope active ({scopeMode}): records outside the configured scope are withheld.
        </p>
      )}

      <Section
        loading={rows.loading}
        error={rows.error}
        onRetry={rows.refetch}
        empty={items.length === 0}
        emptyText="No report-mail requests match these filters yet."
      >
        <div className="-mx-5 overflow-x-auto">
          <table className="w-full min-w-[60rem] text-sm">
            <thead>
              <tr className="border-b border-slate-700/60 text-left text-2xs uppercase tracking-wider text-slate-400">
                <th className="px-5 py-2.5">Recipient email</th>
                <th className="px-3 py-2.5">Report</th>
                <th className="px-3 py-2.5">Delivery status</th>
                <th className="px-3 py-2.5">Requester</th>
                <th className="px-3 py-2.5">Location</th>
                <th className="px-3 py-2.5">Device</th>
                <th className="px-5 py-2.5">Date &amp; time</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  className="border-b border-slate-800/60 transition-colors hover:bg-black/60 hover:text-white"
                >
                  <td className="px-5 py-3 font-medium text-white break-all">
                    {item.recipient_email}
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-300">
                    {REPORT_MAIL_OPTION_LABELS[item.report_option] || item.report_option}
                    {item.reports_included != null && (
                      <span className="block text-slate-500">
                        {item.reports_included} report{item.reports_included === 1 ? '' : 's'} attached
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <Badge tone={mailStatusTone(item.delivery_status)}>
                      {REPORT_MAIL_STATUS_LABELS[item.delivery_status] || item.delivery_status}
                    </Badge>
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-300">
                    {requesterText(item)}
                  </td>
                  {/* Consent-gated location only. 'browser' means the
                      requester's own device provided it (approximate,
                      place-level) — never a precise or inferred address. */}
                  <td className="px-3 py-3 text-xs text-slate-300">
                    {item.location?.available ? (
                      <span>
                        {/* A professional SVG pin, not the OS-drawn "📍": an emoji
                            renders differently on every platform and cannot take
                            the console's palette. `animated={false}` keeps this
                            list marker perfectly still. */}
                        <LocationPinIcon
                          className="mr-1 inline-block h-3.5 w-3.5 shrink-0 align-[-0.1em] text-aqua-400"
                          animated={false}
                        />
                        {locationText(item)}
                        <span className="block text-slate-500">Browser-provided (approximate)</span>
                      </span>
                    ) : (
                      <span className="text-slate-500">Location unavailable</span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-400">{item.device_label || '—'}</td>
                  <td className="px-5 py-3 text-xs tabular text-slate-300">
                    {formatDate(item.created_at, { dateStyle: 'medium', timeStyle: 'medium' })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
            <span>
              Page {meta.page ?? page} of {totalPages} · {meta.total ?? '—'} records
            </span>
            <span className="flex gap-2">
              <Button
                variant="secondary"
                className="px-3 py-1.5 text-xs"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                className="px-3 py-1.5 text-xs"
                disabled={!meta.has_next}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </span>
          </div>
        )}
      </Section>
    </Panel>
  )
}

const REPORT_CATEGORIES = [
  { key: 'all', label: 'All results' },
  { key: 'safe', label: 'Safe results' },
  { key: 'warning', label: 'Warning results' },
  { key: 'unsafe', label: 'Unsafe results' },
]

function ReportsTab() {
  const [category, setCategory] = useState('all')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)

  const summary = useApi(() => adminApi.reportsSummary(), [])
  const reports = useApi(() => adminApi.reports({ category }), [category])

  const items = reports.data?.data ?? reports.data ?? []
  const counts = summary.data?.data ?? summary.data ?? {}

  async function download(format) {
    setExporting(true)
    setExportError(null)
    try {
      const response = await adminApi.exportReports({ category, format })
      const blob = response.data instanceof Blob ? response.data : new Blob([response.data])
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `aquaguard-reports-${category}-${Date.now()}.csv`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (err) {
      setExportError(errorMessage(err, 'The export could not be downloaded.'))
    } finally {
      setExporting(false)
    }
  }

  return (
    <Panel
      title="Overall reports"
      subtitle="Every account's results, attached to its username. Filter by category, then download just that slice or everything."
      actions={
        <>
          <Button
            variant="secondary"
            className="px-3 py-1.5 text-xs"
            disabled={exporting}
            onClick={() => download('csv')}
          >
            {exporting ? 'Preparing…' : `Download ${category} CSV`}
          </Button>
          <Button
            variant="secondary"
            className="px-3 py-1.5 text-xs"
            disabled={exporting}
            onClick={() => download('xlsx')}
          >
            Download for Excel
          </Button>
        </>
      }
    >
      {/* One filter, and the download follows it — so "download what I am
          looking at" is the only thing the buttons can mean. */}
      <div className="flex flex-wrap mb-4 items-center gap-2 sm:gap-3">
        {REPORT_CATEGORIES.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setCategory(item.key)}
            aria-pressed={category === item.key}
            /* The console is always dark, so its inactive chips hover to WHITE
               with BLACK text — the same inversion the rest of the app uses on
               dark surfaces, keeping "this is what I am about to click" obvious. */
            className={`rounded-full px-4 py-2 text-xs font-medium transition-colors ${category === item.key
                ? 'bg-aqua-500 text-slate-950'
                : 'bg-slate-800/70 text-slate-300 hover:bg-white hover:text-black'
              }`}
          >
            {item.label}
            <span className="ml-2 opacity-70 tabular">{counts[item.key] ?? 0}</span>
          </button>
        ))}
      </div>

      {exportError && (
        <p role="alert" className="mb-4 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
          {exportError}
        </p>
      )}

      <Section
        loading={reports.loading}
        error={reports.error}
        onRetry={reports.refetch}
        empty={items.length === 0}
        emptyText="No results in this category yet."
      >
        <div className="-mx-5 overflow-x-auto">
          <table className="w-full min-w-[75rem] text-sm">
            <thead>
              <tr className="border-b border-slate-700/60 text-left text-2xs uppercase tracking-wider text-slate-400">
                <th className="px-5 py-2.5">Report ID</th>
                <th className="px-3 py-2.5">User</th>
                <th className="px-3 py-2.5">Location</th>
                <th className="px-3 py-2.5">Water Source</th>
                <th className="px-3 py-2.5">Parameters</th>
                <th className="px-3 py-2.5">Prediction</th>
                <th className="px-3 py-2.5">Confidence</th>
                <th className="px-3 py-2.5">Risk</th>
                <th className="px-5 py-2.5">Date &amp; time</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-slate-800/60 transition-colors hover:bg-black/60 hover:text-white"
                >
                  <td className="px-5 py-3 font-mono text-xs text-aqua-300">{row.report_id}</td>
                  <td className="px-3 py-3 font-medium text-white">{row.user_name}</td>
                  {/* WHERE the sample was taken, as a place label broken into the
                      parts the brief asks for. The exact coordinates are never
                      sent to the console — see the backend's report_service,
                      which drops them for this reader. */}
                  <td className="px-3 py-3">
                    {[row.location_name || row.location_city, row.location_state].filter(Boolean).length ? (
                      <span className="block text-xs leading-relaxed">
                        <span className="block text-slate-200">
                          <LocationPinIcon
                            className="mr-1 inline-block h-3.5 w-3.5 shrink-0 align-[-0.1em] text-aqua-400"
                            animated={false}
                          />
                          {row.location_name || row.location_city}
                        </span>
                        <span className="block text-slate-400">
                          {row.location_district ? `${row.location_district} District` : null}
                        </span>
                        <span className="block text-slate-400">{row.location_state}</span>
                        <span className="block text-slate-400">{row.location_country}</span>
                        <span className="block text-slate-400">
                          {/* The exact stored pincode, or the honest "Not
                              Available" - never a guessed one. */}
                          {row.location_pincode
                            ? `Pincode: ${row.location_pincode}`
                            : 'Pincode: Not Available'}
                        </span>
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">
                        Not recorded
                        <span className="block">Pincode: Not Available</span>
                      </span>
                    )}
                  </td>
                  {/* PROMPT 4: the stored source type, else the nearest real
                      nearby source with its distance, else an explicit "unavailable". */}
                  <td className="px-3 py-3 text-xs capitalize text-slate-300">
                    {waterSourceLabel(row, { empty: 'Not recorded' })}
                    {row.nearby_water_source && row.water_source_type && (
                      <span className="block text-slate-400">
                        Nearest: {row.nearby_water_source}
                        {row.nearby_water_source_distance != null
                          ? ` — ${Number(row.nearby_water_source_distance)} km`
                          : ''}
                      </span>
                    )}
                  </td>
                  {/* ALL FIVE measured readings, not just three. */}
                  <td className="px-3 py-3 text-xs tabular leading-relaxed text-slate-300">
                    <span className="block">pH: {row.ph ?? '—'}</span>
                    <span className="block">Turbidity: {row.turbidity ?? '—'} NTU</span>
                    <span className="block">TDS: {row.tds ?? '—'} mg/L</span>
                    <span className="block">Temp: {row.temperature ?? '—'} °C</span>
                    <span className="block">DO: {row.dissolved_oxygen ?? '—'} mg/L</span>
                  </td>
                  <td className="px-3 py-3">
                    <Badge tone={row.category === 'unsafe' ? 'unsafe' : row.category === 'warning' ? 'moderate' : 'safe'}>
                      {String(row.prediction || '').toUpperCase()}
                    </Badge>
                  </td>
                  <td className="px-3 py-3 tabular text-slate-300">
                    {(Number(row.confidence || 0) * 100).toFixed(1)}%
                  </td>
                  {/* The RISK word, mapped from the model's own verdict - never a
                      separately invented level. */}
                  <td className="px-3 py-3 text-xs font-medium text-slate-300">
                    {row.category === 'unsafe' ? 'High' : row.category === 'warning' ? 'Moderate' : 'Low'}
                  </td>
                  <td className="px-5 py-3 text-xs tabular text-slate-300">
                    {formatDate(row.created_at, { dateStyle: 'medium', timeStyle: 'short' })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Parameter limits
// ---------------------------------------------------------------------------
function ParametersTab() {
  const limits = useApi(() => adminApi.parameterLimits(), [])
  const [draft, setDraft] = useState({})
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)

  const rows = limits.data?.data ?? limits.data ?? []

  function valueFor(row, field) {
    return draft[row.name]?.[field] ?? row[field]
  }

  function setValue(name, field, value) {
    setDraft((previous) => ({
      ...previous,
      [name]: { ...(previous[name] || {}), [field]: value },
    }))
  }

  async function save() {
    setSaving(true)
    setMessage(null)
    setSaveError(null)
    try {
      const payload = {}
      Object.entries(draft).forEach(([name, values]) => {
        payload[name] = { min: Number(values.min), max: Number(values.max) }
      })
      await adminApi.updateParameterLimits(payload)
      setDraft({})
      limits.refetch()
      setMessage('Parameter limits saved.')
    } catch (err) {
      setSaveError(errorMessage(err, 'Those limits could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel
      title="Parameter control"
      subtitle="The accepted range for each parameter. Limits may be tightened below the physical range, but never widened past it."
      actions={
        <Button
          className="px-3 py-1.5 text-xs"
          loading={saving}
          disabled={Object.keys(draft).length === 0}
          onClick={save}
        >
          Save limits
        </Button>
      }
    >
      {message && (
        <p role="status" className="mb-4 rounded-field bg-safe/15 px-3 py-2 text-xs text-safe-light">
          {message}
        </p>
      )}
      {saveError && (
        <p role="alert" className="mb-4 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
          {saveError}
        </p>
      )}

      <Section loading={limits.loading} error={limits.error} onRetry={limits.refetch} empty={rows.length === 0}>
        <ul className="space-y-3">
          {rows.map((row) => (
            <li
              key={row.name}
              className="grid items-center gap-3 rounded-field border-slate-700/60 bg-slate-950/60 px-4 py-3 sm:grid-cols-[1fr_auto_auto_auto]"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-white">{row.label}</p>
                <p className="text-xs text-slate-400">
                  {row.unit} · physical range {row.default_min}–{row.default_max}
                  {row.is_overridden && (
                    <span className="ml-2 rounded-full bg-aqua-500/20 px-2 py-0.5 text-aqua-300">
                      customised
                    </span>
                  )}
                </p>
              </div>

              <label className="text-2xs uppercase tracking-wider text-slate-400">
                Min
                <input
                  type="number"
                  step="0.01"
                  value={valueFor(row, 'min')}
                  onChange={(event) => setValue(row.name, 'min', event.target.value)}
                  className="mt-1 block w-24 rounded-field border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-white focus:border-aqua-400 focus:outline-none"
                />
              </label>

              <label className="text-2xs uppercase tracking-wider text-slate-400">
                Max
                <input
                  type="number"
                  step="0.01"
                  value={valueFor(row, 'max')}
                  onChange={(event) => setValue(row.name, 'max', event.target.value)}
                  className="mt-1 block w-24 rounded-field border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-white focus:border-aqua-400 focus:outline-none"
                />
              </label>

              <button
                type="button"
                onClick={() =>
                  setDraft((previous) => ({
                    ...previous,
                    [row.name]: { min: row.default_min, max: row.default_max },
                  }))
                }
                className="self-end rounded-field px-2.5 py-1.5 text-2xs text-slate-300 hover:text-white"
              >
                Reset
              </button>
            </li>
          ))}
        </ul>
      </Section>
    </Panel>
  )
}



// ---------------------------------------------------------------------------
// Location access scope (PROMPT 13)
// ---------------------------------------------------------------------------
/**
 * The Location Access Scope setting.
 *
 * The administrator fixes the area inside which water-quality checks are
 * allowed: a specific STATE, a whole COUNTRY, or OFF (no restriction). The scope
 * is enforced by the BACKEND on every location lookup, so this panel does not
 * "do" the restriction — it only sets it. A user who searches outside the scope
 * is refused by the API, not by their browser.
 *
 * PROMPT 13 ADDS FOUR THINGS to what this panel was:
 *
 *   1. THE AREA IS CHOSEN, NOT TYPED. The stored value has to be the
 *      geocoder's own spelling of a state, because that is what the scope is
 *      later compared against. A free-text box is how a scope ends up looking
 *      configured while matching nothing - and a scope that matches nothing is
 *      indistinguishable, to a user, from a broken feature. The picker offers
 *      resolved states for the chosen country, and the backend validates
 *      whatever arrives regardless of where it came from.
 *
 *   2. SAVING TAKES CONFIRMATION (requirement 11). This setting decides who can
 *      use the water-quality feature at all, and it takes effect immediately for
 *      every user. One click that silently locks or unlocks that is not a
 *      reasonable thing to allow, so the Save button reveals the change and
 *      states its effect, and only a second click commits it.
 *
 *   3. PROVENANCE IS SHOWN (requirement 12): who set the current scope and
 *      when, plus the append-only history beneath it, refused attempts included.
 *
 *   4. THE CURRENT CONFIGURATION IS ALWAYS ON SCREEN (requirement 11), above
 *      the form, so an admin is never editing a restriction they have not seen.
 */
function LocationScopeTab() {
  const scope = useApi(() => adminApi.locationScope(), [])
  const audits = useApi(() => adminApi.locationScopeAudits({ limit: 10 }), [])

  const [mode, setMode] = useState(null)
  const [state, setState] = useState('')
  const [country, setCountry] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)
  // Requirement 11: nothing is committed until the admin has seen the change.
  const [confirming, setConfirming] = useState(false)

  const current = scope.data?.data ?? scope.data ?? null

  // The states available for the country currently in the field. Loaded from
  // the backend, which resolves them from real map data — an empty list means
  // the source could not be reached, and the admin types the state instead.
  const stateOptions = useApi(
    () => (country ? adminApi.locationScopeOptions({ country }) : Promise.resolve({ data: { states: [] } })),
    [country],
  )
  const stateList = (stateOptions.data?.data ?? stateOptions.data ?? {}).states ?? []

  // Seed the form from the server's answer the first time it arrives. The draft
  // starts null, so a re-render after saving does not clobber typing.
  useEffect(() => {
    if (current && mode === null) {
      setMode(current.mode || 'off')
      setState(current.state || '')
      setCountry(current.country || '')
    }
  }, [current, mode])

  const effectiveMode = mode ?? 'off'

  // What this form would set, phrased for a human. Shown in the confirmation
  // BEFORE anything is saved, and never phrased as if it had already happened.
  const pendingLabel =
    effectiveMode === 'off'
      ? 'OFF — every location will be allowed'
      : effectiveMode === 'state'
        ? `STATE — ${state.trim() || '(no state chosen)'}`
        : `COUNTRY — ${country.trim() || '(no country chosen)'}`

  const effectNote =
    effectiveMode === 'off'
      ? 'This removes the restriction. Every location will become usable immediately, for every user.'
      : effectiveMode === 'state'
        ? 'Water-quality checks will be refused for any location that resolves to a different state. Existing reports and predictions are NOT deleted — they stay stored and are filtered on read.'
        : 'Water-quality checks will be refused for any location that resolves to a different country. Existing reports and predictions are NOT deleted — they stay stored and are filtered on read.'

  function describe(scopeValue) {
    if (!scopeValue || scopeValue.mode === 'off') return 'OFF — every location allowed'
    if (scopeValue.mode === 'state') return `STATE — ${scopeValue.state || 'not set'}`
    return `COUNTRY — ${scopeValue.country || 'not set'}`
  }

  async function commit() {
    setSaving(true)
    setMessage(null)
    setSaveError(null)
    try {
      await adminApi.updateLocationScope({
        mode: effectiveMode === 'off' ? null : effectiveMode,
        state: effectiveMode === 'state' ? state : null,
        country: effectiveMode === 'state' ? country : effectiveMode === 'country' ? country : null,
      })
      setConfirming(false)
      scope.refetch()
      audits.refetch()
      setMessage(`Location scope saved: ${pendingLabel}. It applies to every user immediately.`)
    } catch (err) {
      // The backend refuses an area that does not resolve. Its message names the
      // field, so it is shown verbatim rather than replaced with a generic one.
      setSaveError(errorMessage(err, 'The location scope could not be saved.'))
      setConfirming(false)
    } finally {
      setSaving(false)
    }
  }

  const options = [
    { value: 'off', label: 'Off', hint: 'No restriction — every location is allowed.' },
    { value: 'state', label: 'State', hint: 'Only locations inside one state are allowed.' },
    { value: 'country', label: 'Country', hint: 'Only locations inside one country are allowed.' },
  ]

  const auditRows = audits.data?.data ?? audits.data ?? []

  return (
    <Panel
      title="Location access scope"
      subtitle="Limit water-quality checks to one state or one country. Enforced by the backend on every lookup."
      actions={
        confirming ? (
          <>
            <Button
              variant="secondary"
              className="px-3 py-1.5 text-xs"
              disabled={saving}
              onClick={() => setConfirming(false)}
            >
              Cancel
            </Button>
            <Button className="px-3 py-1.5 text-xs" loading={saving} onClick={commit}>
              Yes, apply this scope
            </Button>
          </>
        ) : (
          <Button className="px-3 py-1.5 text-xs" onClick={() => setConfirming(true)}>
            Save scope
          </Button>
        )
      }
    >
      {message && (
        <p role="status" className="mb-4 rounded-field bg-safe/15 px-3 py-2 text-xs text-safe-light">
          {message}
        </p>
      )}
      {saveError && (
        <p role="alert" className="mb-4 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
          {saveError}
        </p>
      )}

      <Section loading={scope.loading} error={scope.error} onRetry={scope.refetch} empty={false}>
        {/* REQUIREMENT 11 + 12: THE CONFIGURATION IN FORCE, PROMINENTLY, ABOVE THE
            FORM. Shown before anything is edited so an admin is never changing a
            restriction they have not read, and carrying its provenance so an
            unexpected restriction can be traced to whoever set it. */}
        <div className="mb-5 rounded-field border-aqua-400/40 bg-aqua-400/10 px-4 py-3">
          <p className="text-2xs font-semibold uppercase tracking-wider text-aqua-200">
            Currently in force
          </p>
          <p className="mt-1 text-sm font-medium text-white">{describe(current)}</p>
          {current?.updated_by && (
            <p className="mt-1 text-xs text-aqua-200/80">
              Last changed by {current.updated_by}
              {current.updated_at
                ? ` · ${formatDate(current.updated_at, { dateStyle: 'medium', timeStyle: 'short' })}`
                : ''}
            </p>
          )}
          <p className="mt-1.5 text-xs text-slate-300">
            The backend refuses any lookup outside this area with “Water quality analysis is
            currently available only within the configured location area.”
          </p>
        </div>

        <fieldset>
          <legend className="mb-3 text-2xs font-semibold uppercase tracking-wider text-slate-400">
            Access scope
          </legend>
          <div className="grid gap-3 sm:grid-cols-3">
            {options.map((option) => {
              const active = effectiveMode === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => {
                    setMode(option.value)
                    // Any pending confirmation described the OLD draft, so it is
                    // withdrawn rather than left to commit something else.
                    setConfirming(false)
                  }}
                  aria-pressed={active}
                  className={`rounded-field border px-4 py-3 text-left transition-colors ${active
                      ? 'border-aqua-400 bg-aqua-500/15'
                      : 'border-slate-700/60 bg-slate-950/60 hover:border-slate-500'
                    }`}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className={`flex h-4 w-4 items-center justify-center rounded-full border ${active ? 'border-aqua-300' : 'border-slate-500'
                        }`}
                    >
                      {active && <span className="h-2 w-2 rounded-full bg-aqua-300" />}
                    </span>
                    <span className="text-sm font-medium text-white">{option.label}</span>
                  </span>
                  <span className="mt-1 block text-xs text-slate-400">{option.hint}</span>
                </button>
              )
            })}
          </div>
        </fieldset>

        {/* The area fields appear only for the mode that needs them, so a STATE
            scope can never be saved with an empty state, and vice versa. */}
        {(effectiveMode === 'state' || effectiveMode === 'country') && (
          <label className="mt-5 block max-w-md">
            <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-wider text-slate-400">
              Country
            </span>
            <input
              type="text"
              value={country}
              onChange={(event) => {
                setCountry(event.target.value)
                setConfirming(false)
              }}
              placeholder="e.g. India"
              className="block w-full rounded-field border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-aqua-400 focus:outline-none"
            />
            <span className="mt-1.5 block text-xs text-slate-500">
              {effectiveMode === 'state'
                ? 'The state must sit inside this country. Used to offer the state list.'
                : 'Only locations resolving to this country will be allowed.'}
            </span>
          </label>
        )}

        {effectiveMode === 'state' && (
          <label className="mt-5 block max-w-md">
            <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-wider text-slate-400">
              State
            </span>
            {stateList.length > 0 ? (
              <select
                value={state}
                onChange={(event) => {
                  setState(event.target.value)
                  setConfirming(false)
                }}
                className="block w-full rounded-field border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-aqua-400 focus:outline-none"
              >
                <option value="">Choose a state…</option>
                {stateList.map((option) => {
                  const value = option.state || option.name
                  return (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  )
                })}
              </select>
            ) : (
              <input
                type="text"
                value={state}
                onChange={(event) => {
                  setState(event.target.value)
                  setConfirming(false)
                }}
                placeholder="e.g. Tamil Nadu"
                className="block w-full rounded-field border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white focus:border-aqua-400 focus:outline-none"
              />
            )}
            <span className="mt-1.5 block text-xs text-slate-500">
              {stateList.length > 0
                ? 'Chosen from the real states of this country. Users may only check water quality for places that resolve to this state.'
                : stateOptions.loading
                  ? 'Loading the state list…'
                  : 'Enter a state. It must resolve to a real first-level administrative division, or the backend will refuse it.'}
            </span>
          </label>
        )}

        {/* REQUIREMENT 11: THE CONFIRMATION. States the change and its effect in
            plain words BEFORE it is committed, because this setting takes effect
            for every user at once. */}
        {confirming && (
          <div className="mt-5 rounded-field border-aqua-400/50 bg-aqua-400/10 px-4 py-3">
            <p className="text-2xs font-semibold uppercase tracking-wider text-aqua-200">
              Apply this change?
            </p>
            <p className="mt-1 text-sm font-medium text-white">{pendingLabel}</p>
            <p className="mt-1.5 text-xs text-slate-300">{effectNote}</p>
          </div>
        )}
      </Section>

      {/* REQUIREMENT 12: THE AUDIT TRAIL, newest first, refused attempts included.
          An attempt that was denied is exactly what an administrator reviewing
          this is looking for, so a log of successes only would hide it. */}
      <div className="mt-6">
        <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate-400">
          Scope change history
        </h3>
        <Section
          loading={audits.loading}
          error={audits.error}
          onRetry={audits.refetch}
          empty={auditRows.length === 0}
          emptyText="The scope has not been changed yet."
        >
          <ul className="space-y-2">
            {auditRows.map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-baseline justify-between gap-2 rounded-field border border-slate-700/60 bg-slate-950/60 px-3 py-2 text-xs"
              >
                <span className="text-slate-300">
                  <span className="font-medium text-white">{row.actor}</span>
                  {' changed '}
                  {describe({
                    mode: row.previous_mode,
                    state: row.previous_state,
                    country: row.previous_country,
                  })}
                  {' → '}
                  {describe({
                    mode: row.new_mode,
                    state: row.new_state,
                    country: row.new_country,
                  })}
                  {!row.success && (
                    <span className="ml-2 text-unsafe-light">REFUSED</span>
                  )}
                </span>
                <span className="tabular text-slate-400">
                  {formatDate(row.occurred_at, { dateStyle: 'medium', timeStyle: 'short' })}
                </span>
                {row.detail && <span className="w-full text-slate-500">{row.detail}</span>}
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// ML models
// ---------------------------------------------------------------------------
//
// PROMPT 7: THIS TAB IS EXTENDED, NOT REPLACED.
//
// Everything that was here still is. The "Active model" block, the artifact
// listing, the existing import button and its Activate action are all unchanged
// and still work exactly as before, against the same pre-existing endpoints.
//
// What is added BELOW them is the versioned, validated, audited path: what is
// deployed, what has been registered, how each version was validated, and the
// full trail of who changed what. The two views are shown together deliberately
// - an admin comparing them can see immediately that the registry's notion of
// the active model and the service's own pointer agree, and when they do not,
// which is the state worth catching immediately.
//
// NOTHING HERE DECIDES WHETHER A MODEL IS USABLE. Every button calls the backend
// and renders what the backend answered. A version is only shown as activatable
// when the SERVER has said its validation passed, and the buttons being visible
// is presentation rather than the control - the Flask routes re-check
// authorisation and re-check the validation verdict independently.
function ModelsTab() {
  const models = useApi(() => adminApi.models(), [])
  const active = useApi(() => adminApi.activeModel(), [])
  const [uploading, setUploading] = useState(false)
  const [busy, setBusy] = useState(null)
  const [message, setMessage] = useState(null)
  const [actionError, setActionError] = useState(null)

  const rows = models.data?.data ?? models.data ?? []
  const activeInfo = active.data?.data ?? active.data ?? {}

  async function upload(event) {
    const file = event.target.files?.[0]
    if (!file) return

    setUploading(true)
    setMessage(null)
    setActionError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      await adminApi.uploadModel(form)
      setMessage('Model imported. It is available to activate.')
      models.refetch()
    } catch (err) {
      // The server validates by loading the artifact and predicting on a probe,
      // so a rejection here means the file genuinely cannot be used.
      setActionError(errorMessage(err, 'That model file was rejected.'))
    } finally {
      setUploading(false)
      event.target.value = ''
    }
  }

  async function activate(row) {
    setBusy(row.name)
    setActionError(null)
    try {
      await adminApi.activateModel(row.name)
      setMessage(`'${row.name}' is now answering predictions.`)
      models.refetch()
      active.refetch()
    } catch (err) {
      setActionError(errorMessage(err, 'That model could not be activated.'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel
      title="ML model management"
      subtitle="Import a new model artifact and choose which one answers predictions. An upload is validated by loading it and scoring a sample before it is accepted."
      actions={
        <label className="cursor-pointer rounded-field bg-aqua-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-aqua-400">
          {uploading ? 'Validating…' : 'Import model (.joblib)'}
          <input type="file" accept=".joblib,.pkl" className="sr-only" onChange={upload} disabled={uploading} />
        </label>
      }
    >
      <div className="mb-4 rounded-field border-aqua-500/30 bg-aqua-500/10 px-4 py-3">
        <p className="text-2xs uppercase tracking-wider text-aqua-300">Active model</p>
        <p className="mt-1 text-sm font-medium text-white">
          {activeInfo.name || 'Named by ML_MODEL_FILENAME (no console override)'}
        </p>
        {activeInfo.missing && (
          <p className="mt-1 text-xs text-unsafe-light">
            This artifact is set as active but is not on disk — predictions will fail.
          </p>
        )}
        {activeInfo.detail && <p className="mt-1 text-xs text-slate-400">{activeInfo.detail}</p>}
      </div>

      {message && (
        <p role="status" className="mb-4 rounded-field bg-safe/15 px-3 py-2 text-xs text-safe-light">
          {message}
        </p>
      )}
      {actionError && (
        <p role="alert" className="mb-4 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
          {actionError}
        </p>
      )}

      <Section
        loading={models.loading}
        error={models.error}
        onRetry={models.refetch}
        empty={rows.length === 0}
        emptyText="No model artifacts were found in the model directory."
      >
        <ul className="space-y-3">
          {rows.map((row) => (
            <li
              key={row.filename}
              className="flex flex-wrap items-center justify-between gap-3 rounded-field border-slate-700/60 bg-slate-950/60 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-medium text-white">
                  {row.name}
                  {row.active && <Badge tone="aqua">Active</Badge>}
                  {row.imported && <Badge tone="slate">Imported</Badge>}
                  {!row.readable && <Badge tone="unsafe">Unreadable</Badge>}
                </p>
                <p className="mt-0.5 text-xs text-slate-400">
                  {(row.size_bytes / 1024).toFixed(0)} KB · modified {formatDate(row.modified_at)}
                  {row.model_version ? ` · ${row.model_version}` : ''}
                </p>
                {row.features?.length > 0 && (
                  <p className="mt-0.5 font-mono text-2xs text-slate-500">
                    {row.features.join(', ')}
                  </p>
                )}
              </div>

              <button
                type="button"
                disabled={row.active || busy === row.name || !row.readable}
                onClick={() => activate(row)}
                className="rounded-field border-aqua-500/50 px-3 py-1.5 text-xs font-medium text-aqua-300 transition-colors hover:bg-aqua-500/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {row.active ? 'In use' : busy === row.name ? 'Activating…' : 'Activate'}
              </button>
            </li>
          ))}
        </ul>
      </Section>

      {/* --- PROMPT 7: everything below is the ADDED section ------------------ */}
      <ProjectUpdatesPanel />

      <div className="mt-8 border-t border-slate-700/60 pt-6">
        <ModelRegistrySection
          onChanged={() => {
            models.refetch()
            active.refetch()
          }}
        />
      </div>
    </Panel>
  )
}

/* ---------------------------------------------------------------------------
 * Project updates — what is actually deployed right now
 * ------------------------------------------------------------------------ */

/**
 * The deployed state: project version, backend version, ML model version, the
 * artifact's own metadata, the deployment's status, and when it was last updated
 * successfully.
 *
 * EVERY VALUE HERE IS WHAT THE BACKEND REPORTED. There is no version string,
 * model name or timestamp in this component - not a fallback, not a placeholder.
 * When the call fails the panel says so and shows nothing, because a panel that
 * filled itself in with a plausible-looking version when the request failed is
 * worse than no panel: it would answer "what is deployed?" with a guess.
 */
function ProjectUpdatesPanel() {
  const status = useApi(() => adminApi.modelVersionsStatus(), [])
  const data = status.data?.data ?? status.data ?? null

  return (
    <Section
      loading={status.loading}
      error={status.error}
      onRetry={status.refetch}
      empty={!data}
      emptyText="The backend did not return a deployment status."
    >
      {data && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <VersionTile label="Project version" value={data.project?.version} />
            <VersionTile label="Backend version" value={data.backend?.version} />
            <VersionTile
              label="ML model version"
              value={data.model?.version || 'None deployed'}
              tone={data.model?.version ? undefined : 'muted'}
            />
            <div className="rounded-field border-slate-700/60 bg-slate-950/60 px-4 py-3">
              <p className="text-2xs uppercase tracking-wider text-slate-400">Deployment</p>
              <div className="mt-1.5 flex items-center gap-2">
                <Badge tone={deploymentTone(data.deployment?.status)}>
                  {deploymentLabel(data.deployment?.status)}
                </Badge>
                {data.model?.healthy === false && (
                  <span className="text-2xs text-unsafe-light">model not loadable</span>
                )}
              </div>
              <p className="mt-1.5 text-2xs text-slate-500">{data.deployment?.detail}</p>
            </div>
          </div>

          {/* The artifact's own metadata, so a deployment can be identified
              without opening the server's filesystem. */}
          <div className="rounded-field border-slate-700/60 bg-slate-950/60 px-4 py-3">
            <p className="text-2xs uppercase tracking-wider text-slate-400">
              Active model artifact
            </p>
            <dl className="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
              <MetaRow label="Selected from" value={data.model?.source || 'Not set'} />
              <MetaRow
                label="Declared version"
                value={data.model?.declared_version || 'Not stated by the artifact'}
              />
              <MetaRow label="Trained" value={data.model?.trained_at || 'Not stated'} />
              <MetaRow label="scikit-learn" value={data.model?.scikit_learn_version} />
              <MetaRow
                label="SHA-256"
                value={
                  data.model?.checksum_sha256
                    ? `${data.model.checksum_sha256.slice(0, 16)}…`
                    : 'Not recorded'
                }
              />
              <MetaRow
                label="Features"
                value={
                  data.model?.features?.length
                    ? data.model.features.join(', ')
                    : 'Not recorded for this model'
                }
              />
            </dl>
          </div>

          {/* "Last successful update" is the last SUCCESSFUL activation read
              from the audit log, deliberately not the artifact's modification
              time: a file's mtime moves for reasons that have nothing to do
              with a deployment, and reporting it as one would be a small lie
              that makes "when did this go live?" unanswerable. */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-field border-slate-700/60 bg-slate-950/60 px-4 py-3">
              <p className="text-2xs uppercase tracking-wider text-slate-400">
                Last successful update
              </p>
              <p className="mt-1 text-sm text-white">
                {data.deployment?.last_successful_update
                  ? formatDate(data.deployment.last_successful_update, {
                      dateStyle: 'medium',
                      timeStyle: 'medium',
                    })
                  : 'No model has been activated through the console yet'}
              </p>
              {data.deployment?.last_successful_update_by && (
                <p className="mt-0.5 text-2xs text-slate-500">
                  by {data.deployment.last_successful_update_by}
                </p>
              )}
            </div>
            <div className="rounded-field border-slate-700/60 bg-slate-950/60 px-4 py-3">
              <p className="text-2xs uppercase tracking-wider text-slate-400">Registry</p>
              <p className="mt-1 text-sm text-slate-200">
                {data.registered_versions} registered · {data.validated_versions} validated ·{' '}
                {data.rejected_versions} rejected
              </p>
              {data.deployment?.last_event && (
                <p className="mt-0.5 text-2xs text-slate-500">
                  Last activity: {data.deployment.last_event.action}{' '}
                  {data.deployment.last_event.model_version || ''} (
                  {data.deployment.last_event.success ? 'ok' : 'refused'})
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </Section>
  )
}

/** One version value. Renders nothing at all when the backend sent none. */
function VersionTile({ label, value, tone }) {
  return (
    <div className="rounded-field border-slate-700/60 bg-slate-950/60 px-4 py-3">
      <p className="text-2xs uppercase tracking-wider text-slate-400">{label}</p>
      <p
        className={`mt-1 text-sm font-medium ${tone === 'muted' ? 'text-slate-400' : 'text-white'}`}
      >
        {value || '—'}
      </p>
    </div>
  )
}

/** One label/value pair. Omits itself when the value is absent. */
function MetaRow({ label, value }) {
  if (!value) return null
  return (
    <div className="min-w-0">
      <dt className="text-2xs uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className="truncate text-xs text-slate-200">{value}</dd>
    </div>
  )
}

function deploymentTone(status) {
  if (status === 'healthy') return 'safe'
  if (status === 'degraded') return 'unsafe'
  return 'slate'
}

function deploymentLabel(status) {
  if (status === 'healthy') return 'Deployed'
  if (status === 'degraded') return 'Degraded'
  return 'Not configured'
}

/* ---------------------------------------------------------------------------
 * Model version registry — register, validate, activate, roll back
 * ------------------------------------------------------------------------ */

/** The state words, so a status is never rendered as a raw column value. */
const STATUS_TEXT = {
  registered: { label: 'Registered', tone: 'slate' },
  validating: { label: 'Validating', tone: 'aqua' },
  validated: { label: 'Validated', tone: 'safe' },
  rejected: { label: 'Rejected', tone: 'unsafe' },
  active: { label: 'Active', tone: 'aqua' },
  superseded: { label: 'Superseded', tone: 'slate' },
  rolled_back: { label: 'Rolled back', tone: 'caution' },
}

function ModelRegistrySection({ onChanged }) {
  const versions = useApi(() => adminApi.modelVersions(), [])
  const audit = useApi(() => adminApi.modelAuditLog({ limit: 40 }), [])
  const [busy, setBusy] = useState(null)
  const [message, setMessage] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [form, setForm] = useState({ version: '', name: '', notes: '', checksum: '' })
  const [file, setFile] = useState(null)

  const rows = versions.data?.data ?? versions.data ?? []
  const auditRows = audit.data?.data ?? audit.data ?? []

  /** Refresh every panel that depends on the registry. */
  function refreshAll() {
    versions.refetch()
    audit.refetch()
    onChanged?.()
  }

  /**
   * REGISTER A NEW VERSION.
   *
   * The response is reported VERBATIM, including a failure. A rejected artifact
   * produces a 200 with `validation_passed: false` and a report explaining
   * which check failed - the upload was accepted as a FILENAME and rejected as
   * a MODEL, which is different from the request being refused. The console says
   * so, and says the active model is unchanged, because that second half is the
   * part an admin needs to hear.
   */
  async function register(event) {
    event.preventDefault()
    if (!file) {
      setActionError('Choose a model artifact to register.')
      return
    }
    if (!form.version.trim()) {
      setActionError('Enter a version string — it is how this model is identified later.')
      return
    }

    setBusy('register')
    setMessage(null)
    setActionError(null)
    try {
      const body = new FormData()
      body.append('file', file)
      body.append('version', form.version.trim())
      if (form.name.trim()) body.append('name', form.name.trim())
      if (form.notes.trim()) body.append('notes', form.notes.trim())
      if (form.checksum.trim()) body.append('checksum', form.checksum.trim())

      const response = await adminApi.registerModelVersion(body)
      const result = response?.data?.data ?? response?.data ?? {}
      const passed = Boolean(result.validation_passed)

      setMessage(
        passed
          ? `Version '${result.version}' was registered and passed every validation check. It is ready to activate.`
          : `Version '${result.version}' was registered but FAILED validation, so it cannot be activated. The currently active model has not been changed.`,
      )
      setForm({ version: '', name: '', notes: '', checksum: '' })
      setFile(null)
      refreshAll()
    } catch (err) {
      setActionError(
        errorMessage(
          err,
          'That model version could not be registered. The active model, if there is one, has not been changed.',
        ),
      )
    } finally {
      setBusy(null)
    }
  }

  async function run(action, id, version) {
    setBusy(`${action}-${id}`)
    setMessage(null)
    setActionError(null)
    try {
      // Each of these waits for the BACKEND to confirm. Nothing is reported as
      // activated or rolled back on the strength of the button having been
      // pressed — a model is only ever described as deployed because the server
      // said so.
      const response =
        action === 'validate'
          ? await adminApi.validateModelVersion(id)
          : action === 'activate'
            ? await adminApi.activateModelVersion(id)
            : await adminApi.rollbackModelVersion(id)

      const result = response?.data?.data ?? response?.data ?? {}
      const verdict = result.validation_passed
      setMessage(
        action === 'validate'
          ? verdict
            ? `Version '${version}' passed validation and can be activated.`
            : `Version '${version}' failed validation: ${result.validation?.failure ?? 'no reason recorded'}. The active model has not been changed.`
          : action === 'activate'
            ? `Version '${version}' is now answering predictions — the backend confirmed the switch.`
            : `Rolled back to '${version}'. The backend confirmed it is active again.`,
      )
      refreshAll()
    } catch (err) {
      // A refusal is the backend protecting the running model. Its wording is
      // shown as-is, because the reason it refused is the useful part.
      setActionError(errorMessage(err, `That ${action} did not go through. The active model has not been changed.`))
      refreshAll()
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-white">Register a new model version</h3>
        <p className="mt-0.5 text-xs text-slate-400">
          The artifact is checked server-side: file type, size, SHA-256 checksum, then a
          compatibility check in an isolated process that proves it accepts the five
          configured water-quality features, returns supported classes, and can actually
          predict. Nothing here edits application source code.
        </p>
      </div>

      <form onSubmit={register} className="rounded-field border-slate-700/60 bg-slate-950/60 p-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-2xs uppercase tracking-wider text-slate-400">
            Model artifact (.joblib / .pkl)
            <input
              type="file"
              accept=".joblib,.pkl"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-xs text-slate-300 file:mr-3 file:rounded-field file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-xs file:text-white"
            />
          </label>
          <label className="block text-2xs uppercase tracking-wider text-slate-400">
            Version string (required)
            <input
              type="text"
              value={form.version}
              onChange={(event) => setForm({ ...form, version: event.target.value })}
              placeholder="rf-2026-04-retrained"
              className="mt-1 block w-full rounded-field border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
            />
          </label>
          <label className="block text-2xs uppercase tracking-wider text-slate-400">
            Display name
            <input
              type="text"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Optional"
              className="mt-1 block w-full rounded-field border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
            />
          </label>
          <label className="block text-2xs uppercase tracking-wider text-slate-400">
            SHA-256 to verify against
            <input
              type="text"
              value={form.checksum}
              onChange={(event) => setForm({ ...form, checksum: event.target.value })}
              placeholder="Optional — 64 hex characters"
              className="mt-1 block w-full rounded-field border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs text-white focus:border-aqua-400 focus:outline-none"
            />
          </label>
        </div>
        <label className="mt-3 block text-2xs uppercase tracking-wider text-slate-400">
          Notes
          <input
            type="text"
            value={form.notes}
            onChange={(event) => setForm({ ...form, notes: event.target.value })}
            placeholder="What changed in this version — optional, but it is what makes the registry readable"
            className="mt-1 block w-full rounded-field border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
          />
        </label>

        {message && (
          <p role="status" className="mt-3 rounded-field bg-safe/15 px-3 py-2 text-xs text-safe-light">
            {message}
          </p>
        )}
        {actionError && (
          <p role="alert" className="mt-3 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
            {actionError}
          </p>
        )}

        <div className="mt-4 flex items-center gap-3">
          <Button className="px-3 py-1.5 text-xs" loading={busy === 'register'} disabled={busy === 'register'}>
            Register &amp; validate
          </Button>
          <p className="text-2xs text-slate-500">
            Registering never changes the model that is running.
          </p>
        </div>
      </form>

      <Section
        loading={versions.loading}
        error={versions.error}
        onRetry={versions.refetch}
        empty={rows.length === 0}
        emptyText="No model versions have been registered yet. Register one above, or use the existing artifact list above."
      >
        <ul className="space-y-3">
          {rows.map((row) => {
            const status = STATUS_TEXT[row.status] ?? { label: row.status, tone: 'slate' }
            return (
              <li
                key={row.id ?? `external-${row.version}`}
                className="rounded-field border-slate-700/60 bg-slate-950/60 px-4 py-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-white">
                      {row.version}
                      <Badge tone={status.tone}>{status.label}</Badge>
                      {row.artifact_present === false && (
                        <Badge tone="unsafe">Artifact missing</Badge>
                      )}
                    </p>
                    {row.notes && <p className="mt-1 text-xs text-slate-300">{row.notes}</p>}
                    <p className="mt-1 text-2xs text-slate-500">
                      {row.size_bytes ? `${(row.size_bytes / 1024).toFixed(0)} KB · ` : ''}
                      {row.checksum_sha256 ? `sha256 ${row.checksum_sha256.slice(0, 12)}… · ` : ''}
                      registered {formatDate(row.created_at)}
                      {row.registered_by ? ` by ${row.registered_by}` : ''}
                      {row.scikit_learn_version ? ` · scikit-learn ${row.scikit_learn_version}` : ''}
                    </p>
                    {row.features?.length > 0 && (
                      <p className="mt-1 font-mono text-2xs text-slate-500">
                        {row.features.join(', ')}
                      </p>
                    )}

                    {/* The validation verdict, check by check. A failed validation
                        says WHICH check failed, because "it didn't validate" is not
                        something an admin can act on and "it expects six features
                        instead of five" is. */}
                    {row.validation && (row.validation.checks?.length > 0 || row.validation.failure) && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-2xs text-slate-400 hover:text-slate-200">
                          Validation report
                          {row.validation.passed ? ' — passed' : ' — failed'}
                        </summary>
                        {row.validation.failure && (
                          <p className="mt-1.5 text-2xs text-unsafe-light">{row.validation.failure}</p>
                        )}
                        <ul className="mt-1.5 space-y-1">
                          {(row.validation.checks ?? []).map((check) => (
                            <li key={check.name} className="flex items-start gap-2 text-2xs">
                              <span className={check.ok ? 'text-safe-light' : 'text-unsafe-light'}>
                                {check.ok ? '✓' : '✕'}
                              </span>
                              <span className="text-slate-400">
                                <span className="font-medium text-slate-300">{check.name}</span>{' '}
                                — {check.detail}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>

                  <div className="flex shrink-0 flex-wrap gap-2">
                    {!row.active && row.id && row.status !== 'active' && (
                      <button
                        type="button"
                        disabled={busy === `validate-${row.id}`}
                        onClick={() => run('validate', row.id, row.version)}
                        className="rounded-field border-slate-600 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:bg-slate-800 disabled:opacity-40"
                      >
                        {busy === `validate-${row.id}` ? 'Validating…' : 'Re-validate'}
                      </button>
                    )}

                    {!row.active && row.validation_passed && row.artifact_present !== false && (
                      <button
                        type="button"
                        disabled={busy === `activate-${row.id}`}
                        onClick={() => run('activate', row.id, row.version)}
                        className="rounded-field border-aqua-500/50 px-3 py-1.5 text-xs font-medium text-aqua-300 transition-colors hover:bg-aqua-500/20 disabled:opacity-40"
                      >
                        {busy === `activate-${row.id}` ? 'Activating…' : 'Activate'}
                      </button>
                    )}

                    {row.rollback_target && (
                      <button
                        type="button"
                        disabled={busy === `rollback-${row.id}`}
                        onClick={() => run('rollback', row.id, row.version)}
                        className="rounded-field border-caution-light/50 px-3 py-1.5 text-xs font-medium text-caution-light transition-colors hover:bg-caution-light/10 disabled:opacity-40"
                      >
                        {busy === `rollback-${row.id}` ? 'Rolling back…' : 'Roll back to this'}
                      </button>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </Section>

      {/* The audit trail. Every ATTEMPTED change is here, not just the ones that
          worked — "someone tried to activate the model that failed validation" is
          the row that matters most, and a log of successes alone could not show
          it. */}
      <div>
        <h3 className="text-sm font-semibold text-white">Model change audit log</h3>
        <p className="mt-0.5 text-xs text-slate-400">
          Every attempted change: who, which version, when, and whether it succeeded.
        </p>
      </div>

      <Section
        loading={audit.loading}
        error={audit.error}
        onRetry={audit.refetch}
        empty={auditRows.length === 0}
        emptyText="No model changes have been recorded yet."
      >
        <div className="-mx-1 overflow-x-auto">
          <table className="w-full min-w-[42rem] text-sm">
            <thead>
              <tr className="border-b border-slate-700/60 text-left text-2xs uppercase tracking-wider text-slate-400">
                <th className="px-3 py-2">When</th>
                <th className="px-3 py-2">Admin</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2">Version</th>
                <th className="px-3 py-2">Result</th>
              </tr>
            </thead>
            <tbody>
              {auditRows.map((entry) => (
                <tr key={entry.id} className="border-b border-slate-800/60">
                  <td className="whitespace-nowrap px-3 py-2 text-xs tabular text-slate-300">
                    {formatDate(entry.occurred_at, { dateStyle: 'medium', timeStyle: 'short' })}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-300">{entry.actor}</td>
                  <td className="px-3 py-2 text-xs text-slate-300">{entry.action}</td>
                  <td className="px-3 py-2 font-mono text-2xs text-slate-400">
                    {entry.model_version || '—'}
                    {entry.previous_active && entry.resulting_active && (
                      <span className="ml-2 text-slate-500">
                        {entry.previous_active} → {entry.resulting_active}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={entry.success ? 'safe' : 'unsafe'}>
                      {entry.success ? 'OK' : 'Failed'}
                    </Badge>
                    {entry.detail && (
                      <p className="mt-0.5 max-w-sm text-2xs text-slate-500">{entry.detail}</p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Notification settings
// ---------------------------------------------------------------------------
function NotificationsTab() {
  const config = useApi(() => adminApi.notifications(), [])
  const [draft, setDraft] = useState({})
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)

  const types = config.data?.data?.types ?? config.data?.types ?? []

  function templateFor(key) {
    const base = types.find((item) => item.key === key) || {}
    return {
      subject: draft[key]?.subject ?? base.subject ?? '',
      body: draft[key]?.body ?? base.body ?? '',
      enabled: draft[key]?.enabled ?? base.enabled ?? true,
    }
  }

  function edit(key, field, value) {
    setDraft((previous) => ({
      ...previous,
      [key]: { ...templateFor(key), ...(previous[key] || {}), [field]: value },
    }))
  }

  async function save() {
    setSaving(true)
    setMessage(null)
    setSaveError(null)
    try {
      const templates = {}
      const enabled = {}
      Object.keys(draft).forEach((key) => {
        const values = templateFor(key)
        templates[key] = { subject: values.subject, body: values.body }
        enabled[key] = values.enabled
      })

      await adminApi.updateNotifications({ templates, enabled })
      setDraft({})
      config.refetch()
      setMessage('Notification settings saved. The next notification will use this wording.')
    } catch (err) {
      setSaveError(errorMessage(err, 'Those notification settings could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel
      title="Notification settings"
      subtitle="Edit the wording of each notification type. Saved changes apply to the next notification raised."
      actions={
        <Button
          className="px-3 py-1.5 text-xs"
          loading={saving}
          disabled={Object.keys(draft).length === 0}
          onClick={save}
        >
          Save notifications
        </Button>
      }
    >
      {message && (
        <p role="status" className="mb-4 rounded-field bg-safe/15 px-3 py-2 text-xs text-safe-light">
          {message}
        </p>
      )}
      {saveError && (
        <p role="alert" className="mb-4 rounded-field bg-unsafe/15 px-3 py-2 text-xs text-unsafe-light">
          {saveError}
        </p>
      )}

      <Section loading={config.loading} error={config.error} onRetry={config.refetch} empty={types.length === 0}>
        <ul className="space-y-5">
          {types.map((item) => {
            const values = templateFor(item.key)
            return (
              <li key={item.key} className="rounded-field border-slate-700/60 bg-slate-950/60 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-white">{item.label}</p>
                    <p className="font-mono text-2xs text-slate-500">{item.key}</p>
                  </div>
                  <label className="flex items-center gap-2 text-xs text-slate-300">
                    <input
                      type="checkbox"
                      checked={values.enabled}
                      onChange={(event) => edit(item.key, 'enabled', event.target.checked)}
                      className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-aqua-500 focus:ring-aqua-400"
                    />
                    Enabled
                  </label>
                </div>

                <label className="mt-3 block text-2xs uppercase tracking-wider text-slate-400">
                  Subject
                  <input
                    type="text"
                    value={values.subject}
                    onChange={(event) => edit(item.key, 'subject', event.target.value)}
                    className="mt-1 block w-full rounded-field border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white focus:border-aqua-400 focus:outline-none"
                  />
                </label>

                <label className="mt-3 block text-2xs uppercase tracking-wider text-slate-400">
                  Body
                  <textarea
                    rows={4}
                    value={values.body}
                    onChange={(event) => edit(item.key, 'body', event.target.value)}
                    className="mt-1 block w-full resize-y rounded-field border-slate-700 bg-slate-900 px-3 py-2 text-xs leading-relaxed text-white focus:border-aqua-400 focus:outline-none"
                  />
                </label>

                {/* The placeholders, listed rather than left for the user to
                    discover. An unknown one is left visible in the output rather
                    than raising, so a typo is self-diagnosing. */}
                <p className="mt-2 font-mono text-2xs text-slate-500">
                  Available: {'{name} {verdict} {confidence} {readings} {when} {where}'}
                </p>
              </li>
            )
          })}
        </ul>
      </Section>
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// System (AI providers + mail)
// ---------------------------------------------------------------------------
function SystemTab() {
  const providers = useApi(() => adminApi.providers(), [])
  const [testState, setTestState] = useState(null)
  const [sending, setSending] = useState(false)

  const data = providers.data?.data ?? providers.data ?? {}
  const ai = data.ai ?? {}
  const mail = data.mail ?? {}

  async function sendTest() {
    setSending(true)
    setTestState(null)
    try {
      const response = await adminApi.sendTestEmail()
      const payload = response.data ?? response
      setTestState({ ok: true, ...(payload.data ?? payload) })
    } catch (err) {
      setTestState({ ok: false, message: errorMessage(err, 'The test message failed.') })
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="space-y-5">
      <Panel
        title="AI providers"
        subtitle="Aqua AI answers through the first configured provider and falls back to the next when one is unreachable. Presence is reported — never a key."
      >
        <Section loading={providers.loading} error={providers.error} onRetry={providers.refetch}>
          <ul className="space-y-3">
            {(ai.providers ?? []).map((item) => (
              <li
                key={item.name}
                className="flex flex-wrap items-center justify-between gap-3 rounded-field border-slate-700/60 bg-slate-950/60 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-medium capitalize text-white">
                    {item.name}
                    {ai.active === item.name && <Badge tone="aqua">Active</Badge>}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-400">
                    {item.configured ? `${item.model} · ${item.base_url}` : 'No key configured'}
                  </p>
                </div>
                <Badge tone={item.configured ? 'safe' : 'slate'}>
                  {item.configured ? 'Configured' : 'Not configured'}
                </Badge>
              </li>
            ))}
          </ul>
        </Section>
      </Panel>

      <Panel
        title="Email transport"
        subtitle="Registration, sign-in and admin notices are sent over SMTP. The credentials are never shown here."
      >
        <dl className="grid gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-2xs uppercase tracking-wider text-slate-400">Status</dt>
            <dd className="mt-1">
              <Badge tone={mail.configured ? 'safe' : 'unsafe'}>
                {mail.configured ? 'Configured' : 'Not configured'}
              </Badge>
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wider text-slate-400">Host</dt>
            <dd className="mt-1 text-sm text-white">{mail.host || '—'}</dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wider text-slate-400">Sender</dt>
            <dd className="mt-1 truncate text-sm text-white">{mail.sender || '—'}</dd>
          </div>
        </dl>

        {mail.suppressed && (
          <p className="mt-4 rounded-field bg-caution/15 px-3 py-2 text-xs text-caution-light">
            Sending is suppressed (MAIL_SUPPRESS_SEND), so no message will actually
            leave this machine. That is the normal setting for development.
          </p>
        )}

        <div className="mt-4 flex-wrap items-center gap-3">
          <Button
            variant="secondary"
            className="px-3 py-1.5 text-xs"
            loading={sending}
            onClick={sendTest}
          >
            Send a test message
          </Button>
          {testState && (
            <p
              role="status"
              className={`text-xs ${testState.ok && testState.status === 'sent' ? 'text-safe-light' : 'text-caution-light'}`}
            >
              {testState.ok
                ? `Mail status: ${testState.status}${testState.detail ? ` (${testState.detail})` : ''}`
                : testState.message}
            </p>
          )}
        </div>
      </Panel>
    </div>
  )
}
