import { useCallback, useEffect, useRef, useState } from 'react'

import { errorMessage } from '@/utils/format'

/**
 * Run an async request on mount (and whenever `deps` change).
 *
 * Returns `{ data, loading, error, refetch }`. Every data-driven page uses
 * this so loading and error states are handled consistently instead of being
 * reimplemented per screen.
 */
export function useApi(fetcher, deps = [], { immediate = true, onError } = {}) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(immediate)
  const [error, setError] = useState(null)

  // Kept in a ref so passing an inline arrow function does not retrigger the
  // request on every render.
  const onErrorRef = useRef(onError)
  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await fetcher())
    } catch (err) {
      setError(errorMessage(err))
      // Optional hook for callers that expect a failure and would rather not
      // render an error state for it (e.g. an endpoint not built yet).
      onErrorRef.current?.(err)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    let active = true
    if (immediate) {
      // Guard against setting state after unmount on slow requests.
      run().catch(() => active && undefined)
    }
    return () => {
      active = false
    }
  }, [run, immediate])

  return { data, loading, error, refetch: run }
}
