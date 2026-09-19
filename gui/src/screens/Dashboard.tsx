import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../App'
import { usePolling } from '../hooks'
import { useToast } from '../toast'
import { parseRunTime, pendingGate, type RunState } from '../types'
import { LiveIndicator, Modal, StatusPill, TableSkeleton } from '../ui'
import { Term } from '../Term'

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

const ONBOARDING_STEPS = [
  { icon: '📁', title: '① 注册仓库', text: '左栏「＋ 添加仓库」，选择一个已配置 .ai-workflow.yaml 的项目目录' },
  { icon: '🚀', title: '② 发起 Run', text: '点「＋ 发起 Run」写下需求——这相当于给 AI 开一张工单' },
  { icon: '💻', title: '③ 回终端跑 agent', text: '在项目目录用 Codex/ZCode 加载 $ai-workflow-harness 技能，按 Run ID 执行 spec → plan → implement → verify' },
  { icon: '✅', title: '④ 回这里看与批', text: 'GUI 实时显示阶段进度；卡在"待处理"时回来审批 gate、治理知识' },
]

function EmptyState() {
  const hasRepos = false
  return (
    <div style={{ maxWidth: 760, margin: '4vh auto 0' }}>
      <div className="empty" style={{ minHeight: 'auto', marginBottom: 8 }}>
        <div className="icon">🗂️</div>
        <div style={{ fontSize: 16, fontWeight: 700 }}>四步开始使用</div>
        <div className="hint">
          这个 GUI 是 AI 编码工作流的「驾驶舱」：agent 在终端写代码，你在这里发起任务、盯进度、做审批。
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        {ONBOARDING_STEPS.map((step) => (
          <div className="card" key={step.title} style={{ margin: 0 }}>
            <div style={{ fontSize: 18 }}>{step.icon}</div>
            <div style={{ fontWeight: 700, margin: '4px 0' }}>{step.title}</div>
            <div className="muted small" style={{ lineHeight: 1.7 }}>{step.text}</div>
          </div>
        ))}
      </div>
      <div className="card" style={{ marginTop: 10 }}>
        <h5>工作流是什么？30 秒版</h5>
        <div className="small" style={{ lineHeight: 1.9, color: 'var(--ink-2)' }}>
          每个 Run（任务）会经过四个阶段：<b>spec</b>（写需求规格）→ <b>plan</b>（拆实施计划）→ <b>implement</b>（写代码）→{' '}
          <b>verify</b>（跑构建和测试）。阶段产出由 agent 提交、系统做确定性校验；关键节点会生成{' '}
          <b>审批 gate</b>——需要你看过产出、点「接受」之后流程才能继续。过程中 agent 产出的经验会沉淀为{' '}
          <b>候选知识</b>，由你批准后进入知识库，供后续 run 复用。
          {hasRepos ? '' : ' 现在从左栏「＋ 添加仓库」开始。'}
        </div>
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

      {polling.data === null && polling.error === null ? (
        <TableSkeleton rows={5} />
      ) : (
      <>
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
              <td colSpan={7} style={{ textAlign: 'center', padding: 30 }}>
                {runs.length === 0 ? (
                  <div>
                    <div style={{ fontWeight: 700, marginBottom: 6 }}>还没有任何 Run</div>
                    <div className="muted small" style={{ lineHeight: 1.8 }}>
                      点右上角「＋ 发起 Run」写下需求 → 回终端让 agent 执行（$ai-workflow-harness）→ 回这里看进度。<br />
                      一个 Run = 一次"给 AI 的完整任务"，四个阶段自动推进，卡住时等你审批。
                    </div>
                  </div>
                ) : (
                  <span className="muted">当前筛选没有匹配的 run——试试点「全部」chip 或清空搜索框</span>
                )}
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

      </>
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
        <label>需求描述——「给 AI 的工单」，写清楚要做什么</label>
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
          <label><Term term="profile">Profile</Term>（流程模板）</label>
          <select className="select" value={profile} onChange={(event) => setProfile(event.target.value)}>
            <option value="full">full（四阶段）</option>
            <option value="grill">grill（三阶段，PRD 驱动）</option>
          </select>
        </div>
        <div className="field" style={{ flex: 2 }}>
          <label><Term term="source revision">源 revision</Term>{head === null ? '（该仓库不是 git 仓库，必填）' : '（留空自动取当前 HEAD）'}</label>
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
