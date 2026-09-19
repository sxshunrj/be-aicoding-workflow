import { useEffect, useMemo, useRef, useState } from 'react'
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

function StatCard({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius)',
        padding: '9px 16px',
        minWidth: 88,
      }}
    >
      <div className="muted small">{label}</div>
      <div style={{ fontSize: 19, fontWeight: 700, color: color ?? 'var(--ink)' }}>{value}</div>
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
  const [query, setQuery] = useState('')
  const [profile, setProfile] = useState('all')
  const [creating, setCreating] = useState(false)
  const polling = usePolling(() => api.runs(repoId), 5000)

  const runs = polling.data?.runs ?? []
  const seenBlocked = useRef<Set<string> | null>(null)

  useEffect(() => {
    if (!('Notification' in window)) return
    if (Notification.permission === 'default') void Notification.requestPermission()
  }, [])

  useEffect(() => {
    const blocked = new Set(runs.filter((run) => run.status === 'blocked').map((run) => run.run_id))
    if (seenBlocked.current !== null) {
      for (const runId of blocked) {
        if (!seenBlocked.current.has(runId)) {
          const run = runs.find((item) => item.run_id === runId)
          const title = '⚑ 有 run 等待处理'
          const body = `${runId}\n${run?.requirement.slice(0, 60) ?? ''}`
          toast.info(`${title}：${runId}`)
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(title, { body })
          }
        }
      }
    }
    seenBlocked.current = blocked
  }, [runs, toast])

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
    .filter((run) => profile === 'all' || run.profile === profile)
    .filter((run) => {
      const needle = query.trim().toLowerCase()
      if (!needle) return true
      return run.requirement.toLowerCase().includes(needle) || run.run_id.toLowerCase().includes(needle)
    })
    .slice()
    .sort((a, b) => {
      const hotA = a.status === 'blocked' ? 1 : 0
      const hotB = b.status === 'blocked' ? 1 : 0
      if (hotA !== hotB) return hotB - hotA
      return a.run_id < b.run_id ? 1 : -1
    })

  const completion = runs.length ? Math.round((counts.completed / runs.length) * 100) : 0

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

      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <StatCard label="总数" value={counts.all} />
        <StatCard label="进行中" value={counts.active} color="var(--brand)" />
        <StatCard label="待处理" value={counts.blocked} color="var(--danger)" />
        <StatCard label="已完成" value={counts.completed} color="var(--ok)" />
        <StatCard label="完成率" value={`${completion}%`} color="var(--ok)" />
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            className="input"
            style={{ width: 220 }}
            placeholder="搜索需求 / Run ID…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <select className="select" style={{ width: 110 }} value={profile} onChange={(event) => setProfile(event.target.value)}>
            <option value="all">全部 profile</option>
            <option value="full">full</option>
            <option value="grill">grill</option>
          </select>
        </div>
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
