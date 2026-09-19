import { useCallback, useEffect, useRef, useState } from 'react'

export interface Polling<T> {
  data: T | null
  error: string | null
  refreshing: boolean
  lastUpdated: number | null
  refresh: () => Promise<void>
}

/** 固定间隔轮询；页面隐藏时暂停；refresh() 供操作后立即刷新。 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  enabled: boolean = true,
): Polling<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<number | null>(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const result = await fetcherRef.current()
      setData(result)
      setError(null)
      setLastUpdated(Date.now())
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      setError(message)
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    void refresh()
    if (intervalMs <= 0) return
    const timer = window.setInterval(() => {
      if (document.hidden) return
      void refresh()
    }, intervalMs)
    return () => window.clearInterval(timer)
  }, [enabled, intervalMs, refresh])

  return { data, error, refreshing, lastUpdated, refresh }
}

export function timeAgo(timestamp: number | null): string {
  if (!timestamp) return ''
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000))
  if (seconds < 5) return '刚刚'
  if (seconds < 60) return `${seconds} 秒前`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟前`
  return `${Math.round(minutes / 60)} 小时前`
}

/** SSE 实时流：run 状态 + agent 驱动状态，断线自动重连。 */
export function useRunStream(repoId: string, runId: string, enabled: boolean) {
  const [run, setRun] = useState<import('./types').RunState | null>(null)
  const [drive, setDrive] = useState<import('./types').DriveStatus | null>(null)
  const [connected, setConnected] = useState(false)
  const [receivedAt, setReceivedAt] = useState<number | null>(null)
  const [fatal, setFatal] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled) return
    const source = new EventSource(`/api/repos/${repoId}/runs/${runId}/stream`)
    source.onopen = () => {
      setConnected(true)
      setFatal(null)
    }
    source.onerror = () => setConnected(false)
    source.addEventListener('run', (event) => {
      setRun(JSON.parse((event as MessageEvent).data))
      setReceivedAt(Date.now())
    })
    source.addEventListener('drive', (event) => {
      setDrive(JSON.parse((event as MessageEvent).data))
    })
    source.addEventListener('fatal', (event) => {
      const data = JSON.parse((event as MessageEvent).data)
      setFatal(data.message ?? 'run 不存在')
    })
    return () => source.close()
  }, [repoId, runId, enabled])

  return { run, drive, connected, receivedAt, fatal }
}
