import type { ReactNode } from 'react'

export function Modal({
  title,
  onClose,
  children,
}: {
  title: ReactNode
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div className="modal-mask" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <span>{title}</span>
          <button className="modal-close" onClick={onClose} aria-label="close">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
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
