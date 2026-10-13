/**
 * Access the Aqua AI panel context.
 *
 * Kept out of the provider's module for the same reason as the other hooks: a
 * file
 * exporting both a component and a plain function breaks React Fast Refresh.
 *
 * Returns a safe default when no provider is mounted, so a component rendered
 * outside the layout (a test, a future standalone screen) does not crash — it
 * simply gets the general suggestion set and no-op publishers.
 */

import { useContext } from 'react'

import AquaAIContext, { AI_CONTEXT } from '@/context/aquaAIContextObject'

export function useAquaAIContext() {
  return (
    useContext(AquaAIContext) ?? {
      context: AI_CONTEXT.general,
      announce: () => { },
      clear: () => { },
    }
  )
}
