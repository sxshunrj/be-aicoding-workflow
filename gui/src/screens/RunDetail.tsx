import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../App'
import { usePolling } from '../hooks'
import { useToast } from '../toast'
import {
  parseRunTime,
  pendingGate,
  PHASE_LABEL,
  PHASE_ORDER,
  VALIDITY_LABEL,
  type RunState,
} from '../types'
import { LiveIndicator, Modal, StatusPill } from '../ui'

const ARTIFACT_META: Record<string, { label: string; icon: string; color: string }> = {
  run_policy: { label: '运行策略', icon: '📜', color: '#5b6472' },
  review_gate: { label: '审批 Gate', icon: '⚖️', color: '#d64545' },
}

function artifactMeta(key: string) {
  const known = ARTIFACT_META[key]
  if (known) return known
  const phase = key.split('.')[0]
  return {
    label: PHASE_LABEL[phase] ? `${PHASE_LABEL[phase]} · ${key}` : key,
    icon: '📄',
    color: '#2f6fed',
  }
}

export default function RunDetail() {
  const { runId = '' } = useParams()
  const { selectedRepo } = useApp()
  const [tab, setTab] = useState<'overview' | 'approval'>('overview')
  const [, setTick] = useState(0)
  const polling = usePolling(
    () => api.run(selectedRepo!.id, runId),
    5000,
    Boolean(selectedRepo),
  )
  const run = polling.data
  const gate = run ? pendingGate(run) : null

  // 让 LiveIndicator 的“N 秒前”随时间刷新
  useEffect(() => {
    const timer = window.setInterval(() => setTick((value) => value + 1), 10000)
    return () => window.clearInterval(timer)
  }, [])

  if (!selectedRepo) {
    return <div className="muted">请先在左侧选择一个仓库</div>
  }
  if (!run) {
    return (
      <div className="empty">
        <div className="icon">⏳</div>
        <div className="hint">{polling.error ? `加载失败：${polling.error}` : '加载中…'}</div>
      </div>
    )
  }

  return (
    <div>
      <div className="tabs" style={{ marginBottom: 0, marginTop: -6 }}>
        <div className={`tab${tab === 'overview' ? ' active' : ''}`} onClick={() => setTab('overview')}>
          概览
        </div>
        <div className={`tab${tab === 'approval' ? ' active' : ''}`} onClick={() => setTab('approval')}>
          审批{gate ? <span className="badge">1</span> : null}
        </div>
      </div>
      {tab === 'overview' ? (
        <Overview repoId={selectedRepo.id} run={run} lastUpdated={polling.lastUpdated} onChanged={() => void polling.refresh()} />
      ) : (
        <Approval repoId={selectedRepo.id} run={run} gate={gate} onChanged={() => void polling.refresh()} />
      )}
    </div>
  )
}

function phaseCards(run: RunState) {
  const groups = new Map<string, Array<{ key: string; child: string; validity: string; reason: string | null }>>()
  for (const [key, node] of Object.entries(run.run_graph)) {
    const list = groups.get(node.phase) ?? []
    list.push({ key, child: node.child, validity: node.validity, reason: node.reason })
    groups.set(node.phase, list)
  }
  return PHASE_ORDER.filter((phase) => groups.has(phase)).map((phase) => ({
    phase,
    nodes: groups.get(phase)!,
  }))
}

function phaseState(run: RunState, phase: string): 'current' | 'done' | 'todo' {
  const order = PHASE_ORDER.indexOf(phase as (typeof PHASE_ORDER)[number])
  const current = PHASE_ORDER.indexOf(run.current_phase as (typeof PHASE_ORDER)[number])
  if (phase === run.current_phase) return 'current'
  return order < current ? 'done' : 'todo'
}

function Overview({
  repoId,
  run,
  lastUpdated,
  onChanged,
}: {
  repoId: string
  run: RunState
  lastUpdated: number | null
  onChanged: () => void
}) {
  const toast = useToast()
  const [showEvents, setShowEvents] = useState(false)
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null)
  const [artifact, setArtifact] = useState<{ key: string; value: unknown } | null>(null)
  const [resuming, setResuming] = useState(false)
  const [rerunRows, setRerunRows] = useState<Array<{ node: string; reason: string }>>([])
  const [blocking, setBlocking] = useState(false)
  const [blockReason, setBlockReason] = useState('')
  const [busy, setBusy] = useState(false)
  const events = usePolling(
    () => api.events(repoId, run.run_id, 100),
    showEvents ? 5000 : 0,
    showEvents,
  )
  const terminal = `$${run.profile === 'grill' ? 'ai-workflow-harness-grill' : 'ai-workflow-harness'} resume ${run.run_id}`

  async function abort() {
    if (!window.confirm(`确认中止 run ${run.run_id}？`)) return
    setBusy(true)
    try {
      await api.abort(repoId, run.run_id)
      toast.info('已中止该 run')
      onChanged()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function submitResume() {
    const reruns: Record<string, string> = {}
    for (const row of rerunRows) {
      if (row.node && row.reason.trim()) reruns[row.node] = row.reason.trim()
    }
    setBusy(true)
    try {
      await api.resume(repoId, run.run_id, reruns)
      toast.success(rerunRows.length ? '已恢复并标记 rerun 节点' : '已恢复该 run')
      setResuming(false)
      setRerunRows([])
      onChanged()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function submitBlock() {
    if (!blockReason.trim()) {
      toast.error('阻止理由必填')
      return
    }
    setBusy(true)
    try {
      await api.block(repoId, run.run_id, blockReason.trim())
      toast.info('已阻止该 run')
      setBlocking(false)
      setBlockReason('')
      onChanged()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function loadSummary() {
    try {
      setSummary(await api.summary(repoId, run.run_id))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  function copyTerminal() {
    void navigator.clipboard.writeText(terminal).then(
      () => toast.success('已复制，去终端粘贴即可'),
      () => toast.error('复制失败，请手动选择复制'),
    )
  }

  const operable = run.status !== 'completed' && run.status !== 'aborted'

  return (
    <div>
      <div className="meta-bar">
        <LiveIndicator lastUpdated={lastUpdated} />
        <StatusPill status={run.status} />
        <span>
          profile <b style={{ color: 'var(--ink-2)' }}>{run.profile}</b>
        </span>
        <span>
          source <span className="mono">{run.source_revision}</span>
        </span>
        <span>创建 {parseRunTime(run.run_id)}</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => void loadSummary()}>
            查看摘要
          </button>
          {operable && (
            <>
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setResuming((value) => !value)}>
                恢复 / Rerun
              </button>
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setBlocking((value) => !value)}>
                阻止
              </button>
              <button className="btn btn-danger btn-sm" disabled={busy} onClick={() => void abort()}>
                中止 Run
              </button>
            </>
          )}
        </span>
      </div>

      <div className="note" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span>
          Agent 在终端继续本 run：<span className="mono">{terminal}</span>
        </span>
        <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={copyTerminal}>
          复制命令
        </button>
      </div>

      {resuming && operable && (
        <div className="card">
          <h5>恢复 / 标记 Rerun（NODE=REASON，理由必填）</h5>
          {rerunRows.map((row, index) => (
            <div key={index} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              <select
                className="select"
                style={{ width: 220 }}
                value={row.node}
                onChange={(event) =>
                  setRerunRows((rows) => rows.map((item, i) => (i === index ? { ...item, node: event.target.value } : item)))
                }
              >
                <option value="">（选择节点）</option>
                {Object.keys(run.run_graph).map((node) => (
                  <option key={node} value={node}>
                    {node}
                  </option>
                ))}
              </select>
              <input
                className="input"
                placeholder="rerun 理由"
                value={row.reason}
                onChange={(event) =>
                  setRerunRows((rows) => rows.map((item, i) => (i === index ? { ...item, reason: event.target.value } : item)))
                }
              />
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setRerunRows((rows) => rows.filter((_, i) => i !== index))}
              >
                删
              </button>
            </div>
          ))}
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setRerunRows((rows) => [...rows, { node: '', reason: '' }])}
            >
              ＋ 添加 rerun 节点（可选）
            </button>
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void submitResume()}>
              确认恢复
            </button>
            <span className="muted small" style={{ alignSelf: 'center' }}>
              不选节点 = 直接恢复，不标记任何 rerun
            </span>
          </div>
        </div>
      )}

      {blocking && operable && (
        <div className="card">
          <h5>阻止该 run（需理由）</h5>
          <textarea
            className="textarea"
            style={{ minHeight: 48 }}
            placeholder="说明阻止原因，等待后续处理…"
            value={blockReason}
            onChange={(event) => setBlockReason(event.target.value)}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn btn-danger btn-sm" disabled={busy || !blockReason.trim()} onClick={() => void submitBlock()}>
              确认阻止
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => setBlocking(false)}>
              取消
            </button>
          </div>
        </div>
      )}

      <div className="muted small" style={{ marginBottom: 3 }}>需求</div>
      <div style={{ fontWeight: 600, marginBottom: 14 }}>{run.requirement}</div>

      <div className="phases">
        {phaseCards(run).map(({ phase, nodes }) => (
          <div
            key={phase}
            className={`phase-card ${phaseState(run, phase) === 'current' ? 'current' : phaseState(run, phase) === 'done' ? 'done' : ''}`}
          >
            <div className="phase-title">
              <span>{phase.toUpperCase()}</span>
              <span>{phaseState(run, phase) === 'current' ? '● 当前' : ''}</span>
            </div>
            <div className="phase-name">{PHASE_LABEL[phase] ?? phase}</div>
            {nodes.map((node) => (
              <div className="node-row" key={node.key} title={node.key}>
                <span className={`dot dot-${node.validity}`} />
                <span>{node.child}</span>
                <span className="muted" style={{ marginLeft: 'auto' }}>
                  {node.validity === 'rerun' ? `${VALIDITY_LABEL.rerun}·${node.reason}` : VALIDITY_LABEL[node.validity as 'pending' | 'valid']}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {summary && (
        <div className="card">
          <h5>Run 摘要</h5>
          <pre className="code">{JSON.stringify(summary, null, 2)}</pre>
        </div>
      )}

      <div className="card">
        <h5>Run 产物（artifacts）</h5>
        {Object.entries(run.artifacts).length === 0 && <div className="muted">暂无</div>}
        {Object.entries(run.artifacts).map(([key, value]) => {
          const meta = artifactMeta(key)
          return (
            <div className="art-row" key={key}>
              <span className="art-ic" style={{ background: meta.color }}>
                {meta.icon}
              </span>
              <span>
                <span className="art-title">{meta.label}</span>
                <br />
                <span className="art-sub mono">{key}</span>
              </span>
              <span className="art-link" onClick={() => setArtifact({ key, value })}>
                查看
              </span>
            </div>
          )
        })}
      </div>

      <div className="card">
        <h5>
          事件时间线（events.jsonl）
          <button className="btn btn-ghost btn-sm" style={{ float: 'right' }} onClick={() => setShowEvents((value) => !value)}>
            {showEvents ? '收起' : '展开'}
          </button>
        </h5>
        {showEvents &&
          (events.data?.events.length ? (
            <div className="timeline">
              {events.data.events.map((event, index) => (
                <div className="event" key={index}>
                  <span className="type">{event.type}</span>
                  <span className="muted" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {JSON.stringify(event.data)}
                  </span>
                  <span className="ts">{event.timestamp ?? ''}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="muted">暂无事件</div>
          ))}
      </div>

      {artifact && (
        <Modal title={`产物 · ${artifact.key}`} onClose={() => setArtifact(null)}>
          <pre className="code">{JSON.stringify(artifact.value, null, 2)}</pre>
        </Modal>
      )}
    </div>
  )
}

function Approval({
  repoId,
  run,
  gate,
  onChanged,
}: {
  repoId: string
  run: RunState
  gate: ReturnType<typeof pendingGate>
  onChanged: () => void
}) {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [blocking, setBlocking] = useState(false)
  const [busy, setBusy] = useState(false)

  async function act(action: () => Promise<unknown>, done: string) {
    setBusy(true)
    try {
      await action()
      toast.success(done)
      setBlocking(false)
      setReason('')
      onChanged()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  if (!gate) {
    const stale = run.artifacts['review_gate'] as Record<string, unknown> | undefined
    return (
      <div className="empty" style={{ minHeight: '40vh' }}>
        <div className="icon">✅</div>
        <div className="hint">
          当前没有等待人工审批的 gate。
          {stale?.accepted_at ? '（上一次 gate 已接受）' : ''}
          {run.status === 'blocked' ? ' 该 run 为手动 block，可等待 agent 侧 resume 或在终端处理。' : ''}
        </div>
      </div>
    )
  }

  const rerunCount = Object.values(run.run_graph).filter((node) => node.validity === 'rerun').length
  return (
    <div>
      <div className="note">
        ⚠ 该 run 在 <b>{gate.phase}</b> 阶段等待人工审批（状态 {run.status}）。接受后请在终端继续运行 agent 的对应阶段。
      </div>
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div className="card" style={{ flex: '1.6', minWidth: 320, borderLeft: '4px solid var(--danger)' }}>
          <h5>Pending Review Gate</h5>
          <div className="kv"><b>decision</b><span className="pill pill-blocked">{gate.decision}</span></div>
          <div className="kv"><b>phase</b><span>{gate.phase}</span></div>
          <div className="kv">
            <b>proposed_reruns</b>
            <span className="mono">
              {gate.proposed_reruns.length
                ? gate.proposed_reruns.map(([node, r]) => `${node} → ${r}`).join('; ')
                : '（无）'}
            </span>
          </div>
          <div className="kv"><b>state_version</b><span>{gate.state_version}</span></div>
          <div className="kv"><b>digest</b><span className="mono">{gate.digest.slice(0, 16)}…</span></div>
          <div className="kv"><b>proposed_at</b><span>{gate.proposed_at ?? '—'}</span></div>
          <div style={{ borderTop: '1px solid var(--line-soft)', margin: '9px 0', paddingTop: 9 }}>
            <h5>本阶段产出摘要</h5>
            <div style={{ fontSize: 12.5, lineHeight: 1.7, color: 'var(--ink-2)' }}>
              当前阶段 <b>{gate.phase}</b>；节点 {Object.values(run.run_graph).filter((n) => n.phase === gate.phase).length} 个
              （rerun {rerunCount} 个）；run 版本 v{run.version}。完整产物见「概览」Tab。
            </div>
          </div>
        </div>
        <div className="card" style={{ flex: 1, minWidth: 280 }}>
          <h5>审批操作</h5>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button
              className="btn btn-ok"
              disabled={busy}
              onClick={() => void act(() => api.reviewAccept(repoId, run.run_id, gate.digest), '已接受，可回终端继续')}
            >
              ✓ 接受并继续（digest 自动校验）
            </button>
            <button className="btn btn-danger" disabled={busy} onClick={() => setBlocking((value) => !value)}>
              ✕ 驳回
            </button>
            {blocking && (
              <div className="field" style={{ marginTop: 4 }}>
                <label>驳回理由（必填）</label>
                <textarea
                  className="textarea"
                  style={{ minHeight: 54 }}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="说明驳回原因与期望的重跑方向…"
                />
                <button
                  className="btn btn-danger"
                  style={{ marginTop: 8 }}
                  disabled={busy || !reason.trim()}
                  onClick={() => void act(() => api.block(repoId, run.run_id, reason.trim()), '已驳回')}
                >
                  确认驳回
                </button>
              </div>
            )}
            <button
              className="btn btn-ghost"
              disabled={busy}
              onClick={() => void act(() => api.repairGate(repoId, run.run_id), 'gate 已修复')}
            >
              修复 review gate
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
