import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type PollingState<T> = {
  data: T | null
  loading: boolean
  error: string | null
  lastUpdatedAt: number | null
  refresh: () => void
}

export function usePollingQuery<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
): PollingState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const refreshIndex = useRef(0)

  const doFetch = useCallback(async () => {
    refreshIndex.current += 1
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    try {
      const result = await fetcher(controller.signal)
      setData(result)
      setError(null)
      setLastUpdatedAt(Date.now())
    } catch (err) {
      if (controller.signal.aborted) return
      const message = err instanceof Error ? err.message : 'Fetch failed'
      setError(message)
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [fetcher])

  useEffect(() => {
    void doFetch()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  useEffect(() => {
    const id = window.setInterval(() => {
      void doFetch()
    }, intervalMs)
    return () => window.clearInterval(id)
  }, [doFetch, intervalMs])

  const refresh = useMemo(() => () => void doFetch(), [doFetch])

  return { data, loading, error, lastUpdatedAt, refresh }
}
