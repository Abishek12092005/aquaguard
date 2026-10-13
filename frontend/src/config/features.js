/**
 * Feature availability flags.
 *
 * The backend exposes routes for every feature, but several service bodies are
 * still stubs that return 501. The UI must not fire requests it knows will fail:
 * a console full of red errors makes a working application look broken, and it
 * trains the reader to ignore the console — which is where the real failures
 * would appear.
 *
 * Each flag is flipped as its backend lands. They are deliberately explicit
 * rather than inferred from a failed response, because a 501 and a genuine
 * server error look identical from the client and only one of them is expected.
 */

export const FEATURES = {
  /** GET /alerts/summary, GET /alerts — alert_service */
  alerts: true,

  /** POST /predictions and the Random Forest pipeline */
  predictions: true,

  /** GET /predictions, /predictions/stats */
  history: true,

  /** GET /dashboard/overview, /dashboard/charts */
  dashboardData: true,

  /** POST /ai/chat and the Aqua AI assistant */
  aquaAI: true,
}

/** True when every flag a feature depends on is enabled. */
export function isEnabled(...names) {
  return names.every((name) => FEATURES[name] === true)
}
