import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../App'
import { usePolling } from '../hooks'
import { useToast } from '../toast'
import { parseRunTime, pendingGate, type RunState } from '../types'
import { LiveIndicator, Modal, StatusPill } from '../ui'

type Filter = 'all' | 'active' | 'blocked' | 'completed' | 'aborted'

const FILTERS: Array<{ key: Filter; label: string; hot?: boolean }> = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '进行中' },
  { key: 'blocked', label: '待处理', hot: true },
  { key: 'completed', label: '已完成' },
  { key: 'aborted', label: '已中止' },
]

function matchesFilter(run: RunState, filter: Filter): boolean {
  if (filter === 'all') return true
  if (filter === 'active') return run.status === 'pending' || run.status === 'running'
  return run.status === filter
}

export default function Dashboard() {
  const { repos, selectedRepo } = useApp()
  const navigate = useNavigate()

  if (repos.length === 0) return <EmptyState />
  if (!selectedRepo) return null
  return <RunList repoId={selectedRepo.id} repoName={selectedRepo.name} onOpen={(runId) => navigate(`/runs/${runId}`)} />
}

function EmptyState() {
  return (
    <div className="empty">
      <div className="icon">🗂️</div>
      <div style={{ fontSize: 15, fontWeight: 700 }}>还没有注册任何仓库</div>
      <div className="hint">
        点击左侧「＋ 添加仓库」，输入一个包含{' '}
        <span className="mono">.ai-workflow.yaml</span> 的仓库路径开始使用。注册时会自动校验配置文件。
      </div>
    </div>
  )
}

function RunList({
  repoId,
  repoName,
  onOpen,
}: {
  repoId: string
  repoName: string
  onOpen: (runId: string) => void
}) {
  const toast = useToast()
  const [filter, setFilter] = useState<Filter>('all')
  const [creating, setCreating] = useState(false)
  const polling = usePolling(() => api.runs(repoId), 5000)

  const runs = polling.data?.runs ?? []
  const counts = useMemo(() => {
    const base: Record<Filter, number> = { all: runs.length, active: 0, blocked: 0, completed: 0, aborted: 0 }
    for (const run of runs) {
      for (const key of FILTERS) {
        if (key.key !== 'all' && matchesFilter(run, key.key)) base[key.key] += 1
      }
    }
    return base
  }, [runs])

  const visible = runs
    .filter((run) => matchesFilter(run, filter))
    .slice()
    .sort((a, b) => {
      const hotA = a.status === 'blocked' ? 1 : 0
      const hotB = b.status === 'blocked' ? 1 : 0
      if (hotA !== hotB) return hotB - hotA
      return a.run_id < b.run_id ? 1 : -1
    })

  return (
    <div>
      <div className="page-head">
        <h2>
          {repoName} · Runs{' '}
          {polling.refreshing && <span className="spinner" style={{ verticalAlign: -1 }} />}
        </h2>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          ＋ 发起 Run
        </button>
      </div>

      <div className="meta-bar">
        <LiveIndicator lastUpdated={polling.lastUpdated} />
        {polling.error && <span style={{ color: 'var(--danger)' }}>拉取失败：{polling.error}</span>}
      </div>

      <div className="chips">
        {FILTERS.map((item) => (
          <button
            key={item.key}
            className={`chip${item.key === filter ? ' active' : ''}${item.hot ? ' hot' : ''}`}
            onClick={() => setFilter(item.key)}
          >
            {item.label} <span className="muted">{counts[item.key]}</span>
          </button>
        ))}
      </div>

      <table className="data">
        <thead>
          <tr>
            <th>Run ID</th>
            <th>需求</th>
            <th>当前阶段</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>Profile</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {visible.map((run) => {
            const gate = pendingGate(run)
            const hot = run.status === 'blocked'
            return (
              <tr
                key={run.run_id}
                className={`row-link${hot ? ' row-hot' : ''}`}
                onClick={() => onOpen(run.run_id)}
              >
                <td className="mono">{run.run_id}</td>
                <td style={{ maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {gate ? '⚑ ' : ''}
                  {run.requirement}
                </td>
                <td>{run.current_phase}</td>
                <td>
                  <StatusPill status={run.status} />
                </td>
                <td className="muted">{parseRunTime(run.run_id)}</td>
                <td className="muted">{run.profile}</td>
                <td className="chev">›</td>
              </tr>
            )
          })}
          {visible.length === 0 && (
            <tr>
              <td colSpan={7} className="muted" style={{ textAlign: 'center', padding: 26 }}>
                没有符合条件的 run
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {polling.data?.errors && polling.data.errors.length > 0 && (
        <div className="note note-warn" style={{ marginTop: 12 }}>
          {polling.data.errors.length} 个 run 状态文件损坏已跳过：
          {polling.data.errors.map((item) => ` ${item.run_id}`).join(',')}
        </div>
      )}

      {creating && (
        <CreateRunModal
          repoId={repoId}
          repoName={repoName}
          onClose={() => setCreating(false)}
          onCreated={(runId) => {
            setCreating(false)
            void polling.refresh()
            onOpen(runId)
            toast.success('Run 已创建')
          }}
        />
      )}
    </div>
  )
}

function CreateRunModal({
  repoId,
  repoName,
  onClose,
  onCreated,
}: {
  repoId: string
  repoName: string
  onClose: () => void
  onCreated: (runId: string) => void
}) {
  const toast = useToast()
  const [requirement, setRequirement] = useState('')
  const [profile, setProfile] = useState('full')
  const [head, setHead] = useState<string | null | undefined>(undefined)
  const [sourceRevision, setSourceRevision] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    void api
      .repoHead(repoId)
      .then((data) => {
        if (cancelled) return
        setHead(data.head)
        if (data.head) setSourceRevision(data.head.slice(0, 12))
      })
      .catch(() => {
        if (!cancelled) setHead(null)
      })
    return () => {
      cancelled = true
    }
  }, [repoId])

  async function submit() {
    if (!requirement.trim()) {
      toast.error('需求描述不能为空')
      return
    }
    setBusy(true)
    try {
      const run = await api.initRun(repoId, {
        requirement: requirement.trim(),
        profile,
        source_revision: sourceRevision.trim() || undefined,
      })
      onCreated(run.run_id)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`发起 Run — ${repoName}`} onClose={onClose}>
      <div className="field">
        <label>需求描述（requirement）</label>
        <textarea
          className="textarea"
          placeholder="用一段话描述这次要完成的需求…"
          value={requirement}
          onChange={(event) => setRequirement(event.target.value)}
          autoFocus
        />
      </div>
      <div style={{ display: 'flex', gap: 12 }}>
        <div className="field" style={{ flex: 1 }}>
          <label>Profile</label>
          <select className="select" value={profile} onChange={(event) => setProfile(event.target.value)}>
            <option value="full">full（四阶段）</option>
            <option value="grill">grill（三阶段，PRD 驱动）</option>
          </select>
        </div>
        <div className="field" style={{ flex: 2 }}>
          <label>源 revision{head === null ? '（该仓库不是 git 仓库，必填）' : '（留空自动取当前 HEAD）'}</label>
          <input
            className="input mono"
            value={sourceRevision}
            onChange={(event) => setSourceRevision(event.target.value)}
            placeholder={head ? head.slice(0, 12) : '如 cad3901 或完整 SHA'}
          />
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button className="btn btn-ghost" onClick={onClose}>
          取消
        </button>
        <button className="btn btn-primary" disabled={busy} onClick={() => void submit()}>
          {busy ? '创建中…' : '发起 Run'}
        </button>
      </div>
    </Modal>
  )
}
