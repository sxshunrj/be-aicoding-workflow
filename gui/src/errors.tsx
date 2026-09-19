import { Component, useEffect, type ErrorInfo, type ReactNode } from 'react'

async function reportClientError(message: string, context: string, stack: string) {
  try {
    await fetch('/api/client-errors', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, context, stack }),
    })
  } catch {
    /* 上报失败静默，避免递归 */
  }
}

/** 全局未捕获异常/Promise 拒绝 → 上报后端日志。 */
export function useGlobalErrorReporting() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      void reportClientError(event.message, 'window.onerror', String(event.error ?? ''))
    }
    const onRejection = (event: PromiseRejectionEvent) => {
      void reportClientError(
        String(event.reason ?? 'unhandled rejection'),
        'unhandledrejection',
        '',
      )
    }
    window.addEventListener('error', onError)
    window.addEventListener('unhandledrejection', onRejection)
    return () => {
      window.removeEventListener('error', onError)
      window.removeEventListener('unhandledrejection', onRejection)
    }
  }, [])
}

interface BoundaryState {
  error: Error | null
}

export class ErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    void reportClientError(error.message, 'ErrorBoundary', String(info.componentStack ?? ''))
  }

  render() {
    if (this.state.error) {
      return (
        <div className="empty" style={{ minHeight: '100vh' }}>
          <div className="icon">💥</div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>界面渲染出错了</div>
          <div className="hint mono">{String(this.state.error.message)}</div>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            重新加载
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
