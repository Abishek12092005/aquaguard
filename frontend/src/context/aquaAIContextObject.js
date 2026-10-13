/**
 * The Aqua AI panel context object and its vocabulary.
 *
 * Kept out of the provider's module on purpose: a file that exports both a
 * component and plain values cannot be hot-reloaded by React Fast Refresh, so
 * the context object and the `AI_CONTEXT` keys live here and both the provider
 * and its hook import them. This mirrors `authContextObject.js`.
 *
 * It exists because of one specific case: "after a prediction" is a state
 * rather than a route. The Predict page knows whether a verdict has just been
 * returned; `AquaAIButton` is mounted once in `AppLayout` and cannot see that
 * local state. This is the seam between them.
 *
 * Deliberately minimal: a page announces WHAT is on screen, never any data the
 * assistant would answer from. The assistant answers from its own tool calls
 * against the backend, so nothing published here can become a number the model
 * quotes. It only selects which suggested questions to offer.
 */

import { createContext } from 'react'

/** The assistant's per-screen context keys. */
export const AI_CONTEXT = {
  dashboard: 'dashboard',
  prediction: 'prediction',
  predictionResult: 'prediction_result',
  history: 'history',
  alerts: 'alerts',
  profile: 'profile',
  general: 'general',
}

const AquaAIContext = createContext(null)

export default AquaAIContext
