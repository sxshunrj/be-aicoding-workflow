import { useEffect, useRef, useState, type ReactNode } from 'react'

export function Modal({
  title,
  onClose,
  children,
}: {
  title: ReactNode
  onClose: () => void
  children: ReactNode
}) {
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const box = boxRef.current
    const preferred = box
      ? (box.querySelector<HTMLElement>('[autofocus]') ??
        box.querySelector<HTMLElement>('input, textarea, select') ??
        box.querySelector<HTMLElement>('button:not(.modal-close)'))
      : null
    preferred?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !boxRef.current) return
      const focusables = Array.from(
        boxRef.current.querySelectorAll<HTMLElement>(
          'button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !((el as HTMLButtonElement).disabled ?? false))
      if (focusables.length === 0) return
      const firstEl = focusables[0]
      const lastEl = focusables[focusables.length - 1]
      if (event.shiftKey && document.activeElement === firstEl) {
        event.preventDefault()
        lastEl.focus()
      } else if (!event.shiftKey && document.activeElement === lastEl) {
        event.preventDefault()
        firstEl.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      previous?.focus()
    }
  }, [onClose])

  return (
    <div
      className="modal-mask"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="modal" role="dialog" aria-modal="true" ref={boxRef}>
        <div className="modal-head">
          <span>{title}</span>
          <button className="modal-close" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

export function ConfirmDialog({
  title,
  message,
  confirmText = '确认',
  danger,
  onConfirm,
  onCancel,
}: {
  title: string
  message: ReactNode
  confirmText?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <div style={{ marginBottom: 14, lineHeight: 1.7 }}>{message}</div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button className="btn btn-ghost" onClick={onCancel}>
          取消
        </button>
        <button
          className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
          onClick={onConfirm}
          autoFocus
        >
          {confirmText}
        </button>
      </div>
    </Modal>
  )
}

export function useConfirm() {
  const [state, setState] = useState<{
    title: string
    message: ReactNode
    confirmText: string
    danger: boolean
    action: () => void
  } | null>(null)

  const confirm = (
    title: string,
    message: ReactNode,
    action: () => void,
    options?: { confirmText?: string; danger?: boolean },
  ) => setState({ title, message, action, confirmText: options?.confirmText ?? '确认', danger: options?.danger ?? false })

  const dialog = state ? (
    <ConfirmDialog
      title={state.title}
      message={state.message}
      confirmText={state.confirmText}
      danger={state.danger}
      onConfirm={() => {
        state.action()
        setState(null)
      }}
      onCancel={() => setState(null)}
    />
  ) : null

  return { confirm, dialog }
}

export function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div aria-busy="true">
      {Array.from({ length: lines }).map((_, index) => (
        <div key={index} className="skeleton" style={{ width: `${88 - index * 9}%` }} />
      ))}
    </div>
  )
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="card" aria-busy="true">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} style={{ display: 'flex', gap: 12, padding: '9px 0' }}>
          <div className="skeleton" style={{ width: '28%' }} />
          <div className="skeleton" style={{ width: '40%' }} />
          <div className="skeleton" style={{ width: '14%' }} />
        </div>
      ))}
    </div>
  )
}

export function StatusPill({ status }: { status: string }) {
  return <span className={`pill pill-${status}`}>{statusLabel(status)}</span>
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '○ 待启动',
    running: '● 运行中',
    blocked: '⚑ 待处理',
    completed: '✓ 已完成',
    aborted: '✕ 已中止',
  }
  return map[status] ?? status
}

export function LiveIndicator({ lastUpdated }: { lastUpdated: number | null }) {
  if (!lastUpdated) return null
  const seconds = Math.max(0, Math.round((Date.now() - lastUpdated) / 1000))
  const text = seconds < 5 ? '刚刚' : seconds < 60 ? `${seconds} 秒前` : `${Math.round(seconds / 60)} 分钟前`
  return <span className="live">● {text}自动刷新</span>
}
