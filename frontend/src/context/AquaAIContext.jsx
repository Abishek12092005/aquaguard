/**
 * Aqua AI panel context provider.
 *
 * Supplies the value a page publishes into and the assistant panel reads from.
 * The context object and its keys live in `aquaAIContextObject.js` and the hook
 * in `useAquaAIContext.js`, so this module exports only the component and React
 * Fast Refresh keeps working — the same split `AuthContext` uses.
 *
 * The state is reset on every route change, so "after a prediction" cannot leak
 * onto the History screen and offer the wrong prompts.
 *
 * It carries screen state only. No answer is ever derived from it: the
 * assistant answers from its own tool calls against the backend.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'

import AquaAIContext, { AI_CONTEXT } from '@/context/aquaAIContextObject'

export default function AquaAIProvider({ children }) {
  const location = useLocation()

  // What a page has announced about itself, if anything.
  const [announced, setAnnounced] = useState(null)

  // A route change invalidates a previous page's announcement. Without this the
  // Predict screen's "a result exists" would still be true on the next screen.
  useEffect(() => {
    setAnnounced(null)
  }, [location.pathname])

  const announce = useCallback((next) => setAnnounced(next), [])
  const clear = useCallback(() => setAnnounced(null), [])

  // The route decides the base context; a page announcement can refine it
  // (Predict -> a result exists). Unknown routes fall back to `general`.
  const context = useMemo(() => {
    const byPath = {
      '/dashboard': AI_CONTEXT.dashboard,
      '/predict': AI_CONTEXT.prediction,
      '/history': AI_CONTEXT.history,
      '/alerts': AI_CONTEXT.alerts,
    }
    const base = byPath[location.pathname] || AI_CONTEXT.general
    if (base === AI_CONTEXT.prediction && announced === AI_CONTEXT.predictionResult) {
      return AI_CONTEXT.predictionResult
    }
    return base
  }, [location.pathname, announced])

  const value = useMemo(
    () => ({ context, announce, clear }),
    [context, announce, clear],
  )

  return <AquaAIContext.Provider value={value}>{children}</AquaAIContext.Provider>
}
