import { API_BASE_URL } from '@/utils/constants'

/**
 * Backend warm-up ping.
 *
 * Render's free tier spins the API down after ~15 minutes of no traffic, and a
 * cold start then takes 30-60 s — which is what a visitor feels when they click
 * a data-driven button first. Firing one cheap liveness request the moment the
 * page opens starts that boot while the UI renders, so by the time the user
 * actually touches the app the API is already answering.
 *
 * Deliberately fire-and-forget:
 *   * `/api/health` never touches a dependency (see health_routes.py), so it
 *     answers as soon as the process is up — it is the ideal wake signal.
 *   * The promise is ignored on purpose; failure just means the API is down or
 *     still waking, and the first real user action will retry naturally.
 *   * `keepalive` lets the request survive even if the visitor closes the tab
 *     within the first seconds.
 */
export function warmUpBackend() {
  const url = `${API_BASE_URL}/health`
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      navigator.sendBeacon(url)
      return
    }
    fetch(url, { method: 'GET', keepalive: true, mode: 'cors' }).catch(() => { })
  } catch {
    /* A failed warm-up must never break the page: the next real call retries. */
  }
}
