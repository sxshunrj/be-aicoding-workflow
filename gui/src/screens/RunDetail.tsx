import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../App'
import { usePolling, useRunStream } from '../hooks'
import { useToast } from '../toast'
import {
  parseRunTime,
  pendingGate,
  PHASE_LABEL,
  PHASE_ORDER,
  VALIDITY_LABEL,
  type DriveStatus,
  type RunState,
} from '../types'
import { LiveIndicator, Modal, StatusPill, useConfirm } from '../ui'
import { Term } from '../Term'

const ARTIFACT_META: Record<string, { label: string; icon: string; color: string }> = {
  _run_policy: { label: '运行策略（run 创建时固化的规则快照）', icon: '📜', color: '#5b6472' },
  run_policy: { label: '运行策略（run 创建时固化的规则快照）', icon: '📜', color: '#5b6472' },
  review_gate: { label: '审批 Gate（等你决定是否继续）', icon: '⚖️', color: '#d64545' },
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
  const navigate = useNavigate()
  const { selectedRepo } = useApp()
  const [tab, setTab] = useState<'overview' | 'approval' | 'files'>('overview')
  const [, setTick] = useState(0)
  const stream = useRunStream(selectedRepo?.id ?? '', runId, Boolean(selectedRepo))
  const run = stream.run
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
        <div className="hint">{stream.fatal ? stream.fatal : stream.connected ? '加载中…' : '连接中…'}</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <button className="btn btn-ghost btn-sm" onClick={() => navigate('/')}>
          ‹ 返回 Runs
        </button>
      </div>
      <div className="tabs" style={{ marginBottom: 0, marginTop: -6 }}>
        <div className={`tab${tab === 'overview' ? ' active' : ''}`} onClick={() => setTab('overview')}>
          概览
        </div>
        <div className={`tab${tab === 'approval' ? ' active' : ''}`} onClick={() => setTab('approval')}>
          审批{gate ? <span className="badge">1</span> : null}
        </div>
        <div className={`tab${tab === 'files' ? ' active' : ''}`} onClick={() => setTab('files')}>
          运行文件
        </div>
      </div>
      {tab === 'overview' ? (
        <Overview repoId={selectedRepo.id} run={run} lastUpdated={stream.receivedAt} connected={stream.connected} drive={stream.drive} />
      ) : tab === 'approval' ? (
        <Approval repoId={selectedRepo.id} run={run} gate={gate} />
      ) : (
        <FilesTab repoId={selectedRepo.id} runId={run.run_id} />
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
  connected,
  drive,
}: {
  repoId: string
  run: RunState
  lastUpdated: number | null
  connected: boolean
  drive: DriveStatus | null
}) {
  const toast = useToast()
  const confirm = useConfirm()
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

  function confirmAbort() {
    confirm.confirm(
      '中止 Run',
      `确认中止 run ${run.run_id}？该 run 将进入 aborted 终态。`,
      async () => {
        setBusy(true)
        try {
          await api.abort(repoId, run.run_id)
          toast.info('已中止该 run')
            } catch (error) {
          toast.error(error instanceof Error ? error.message : String(error))
        } finally {
          setBusy(false)
        }
      },
      { confirmText: '中止', danger: true },
    )
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

  const operable = run.status !== 'completed' && run.status !== 'aborted'

  return (
    <div>
      <div className="meta-bar">
        <LiveIndicator lastUpdated={lastUpdated} />
        {!connected && <span style={{ color: 'var(--danger)' }}>实时连接断开，重连中…</span>}
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
              <button className="btn btn-danger btn-sm" disabled={busy} onClick={() => confirmAbort()}>
                中止 Run
              </button>
            </>
          )}
        </span>
      </div>

      <DriverCard repoId={repoId} run={run} drive={drive} />

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
            <div className="phase-name">{PHASE_LABEL[phase] ?? phase} <span className="muted small">{phase}</span></div>
            {nodes.map((node) => (
              <div className="node-row" key={node.key} title={node.key}>
                <span className={`dot dot-${node.validity}`} />
                <span>{node.child}</span>
                <span className="muted" style={{ marginLeft: 'auto' }}>
                  {node.validity === 'rerun' ? `${VALIDITY_LABEL.rerun}（理由：${node.reason}）` : VALIDITY_LABEL[node.validity as 'pending' | 'valid']}
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
                <div
                  className="event row-link"
                  key={index}
                  title="点击查看完整事件数据"
                  onClick={() => setArtifact({ key: `${event.type} @ ${event.timestamp ?? index}`, value: event })}
                >
                  <span className="type">{EVENT_LABEL[event.type] ?? event.type}</span>
                  <span className="muted" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {eventSummary(event.type, event.data)}
                  </span>
                  <span className="ts">{(event.timestamp ?? '').replace('T', ' ').slice(0, 19)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="muted">暂无事件</div>
          ))}
      </div>

      <RepoChanges repoId={repoId} />

      {confirm.dialog}
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
}: {
  repoId: string
  run: RunState
  gate: ReturnType<typeof pendingGate>
}) {
  const toast = useToast()
  const confirm = useConfirm()
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
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  function confirmAccept() {
    if (!gate) return
    confirm.confirm(
      '接受 gate',
      '接受后 GUI 会自动继续驱动 agent 执行后续阶段（无需回终端）。',
      async () => {
        setBusy(true)
        try {
          const data = await api.reviewAccept(repoId, run.run_id, gate.digest)
          if (data.auto_resume?.resumed) {
            toast.success('已接受，agent 已自动继续执行')
          } else if (data.auto_resume?.reason === 'queued_after_exit') {
            toast.info('已接受；当前 agent 退出后将自动继续接力')
          } else if (data.auto_resume?.reason === 'gate_pending') {
            toast.info('已接受；gate 状态尚未就绪，请手动点「驱动 agent」')
          } else if (data.auto_resume?.reason) {
            toast.error(`已接受，但自动驱动失败：${data.auto_resume.reason}`)
          } else {
            toast.success('已接受')
          }
        } catch (error) {
          toast.error(error instanceof Error ? error.message : String(error))
        } finally {
          setBusy(false)
        }
      },
      { confirmText: '接受并继续' },
    )
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
          <h5><Term term="review gate">Pending Review Gate</Term>（等待你审批）</h5>
          <div className="kv"><b>decision</b><span className="pill pill-blocked">{gate.decision}</span></div>
          <div className="kv"><b>phase</b><span>{gate.phase}</span></div>
          <div className="kv">
            <b><Term term="rerun">proposed_reruns</Term></b>
            <span className="mono">
              {gate.proposed_reruns.length
                ? gate.proposed_reruns.map(([node, r]) => `${node} → ${r}`).join('; ')
                : '（无）'}
            </span>
          </div>
          <div className="kv"><b>state_version（内容版本）</b><span>{gate.state_version}</span></div>
          <div className="kv"><b><Term term="digest">digest</Term></b><span className="mono">{gate.digest.slice(0, 16)}…</span></div>
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
              onClick={confirmAccept}
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
          {confirm.dialog}
        </div>
      </div>
    </div>
  )
}


const EVENT_LABEL: Record<string, string> = {
  run_created: 'run 创建',
  phase_begun: '阶段开始',
  child_result_staged: '子任务结果提交',
  phase_finalized: '阶段聚合完成',
  review_proposed: '生成审批 gate，等待人工',
  review_accepted: '人工审批接受',
  workflow_transitioned: '流转到下一阶段',
  run_resumed: '恢复 run（rerun 标记）',
  run_blocked: 'run 被阻止',
  run_aborted: 'run 中止',
  reflection_submitted: '反思提交',
}

function eventSummary(type: string, data: Record<string, unknown> | undefined): string {
  if (!data) return ''
  const pick = (...keys: string[]) => {
    for (const key of keys) {
      const value = data[key]
      if (typeof value === 'string' && value) return value
    }
    return null
  }
  switch (type) {
    case 'phase_begun':
      return [pick('phase'), pick('attempt_id') ?? pick('attempt')].filter(Boolean).join(' · ')
    case 'child_result_staged':
      return [pick('node'), pick('child'), pick('status')].filter(Boolean).join(' · ')
    case 'phase_finalized':
      return [pick('phase'), pick('attempt_id'), pick('status')].filter(Boolean).join(' · ')
    case 'review_proposed':
    case 'review_accepted':
      return [pick('decision'), `phase=${pick('phase')}`, `v${pick('state_version') ?? ''}`].filter((part) => part && !part.endsWith('=')).join(' · ')
    case 'workflow_transitioned':
      return data.accepted === true ? `已接受 → ${pick('phase') ?? '下一阶段'}` : pick('phase') ?? ''
    case 'run_resumed':
      return pick('reason') ?? '恢复执行'
    case 'run_blocked':
      return pick('reason') ?? ''
    case 'reflection_submitted':
      return pick('outcome') ?? ''
    default: {
      const text = JSON.stringify(data)
      return text.length > 90 ? `${text.slice(0, 90)}…` : text
    }
  }
}

function FilesTab({ repoId, runId }: { repoId: string; runId: string }) {
  const [file, setFile] = useState<{ path: string; content: string; truncated: boolean } | null>(null)
  const [filter, setFilter] = useState('')
  const polling = usePolling(() => api.runFiles(repoId, runId), 15000)

  const files = (polling.data?.files ?? []).filter((item) =>
    item.path.toLowerCase().includes(filter.trim().toLowerCase()),
  )

  async function open(path: string) {
    try {
      setFile(await api.runFile(repoId, runId, path))
    } catch (error) {
      setFile({ path, content: `读取失败：${error instanceof Error ? error.message : String(error)}`, truncated: false })
    }
  }

  return (
    <div>
      <div className="meta-bar">
        <span className="muted">该 run 目录下的全部产物：dispatch 包、给 agent 的 prompt、staged 结果、反思包等（只读）</span>
        <input
          className="input"
          style={{ width: 220, marginLeft: 'auto' }}
          placeholder="按路径过滤…"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </div>
      <table className="data">
        <thead>
          <tr>
            <th>文件</th>
            <th style={{ width: 110 }}>大小</th>
          </tr>
        </thead>
        <tbody>
          {files.map((item) => (
            <tr key={item.path} className="row-link" onClick={() => void open(item.path)}>
              <td className="mono">{item.path}</td>
              <td className="muted">{item.size} B</td>
            </tr>
          ))}
          {files.length === 0 && (
            <tr>
              <td colSpan={2} className="muted" style={{ textAlign: 'center', padding: 26 }}>
                {polling.error ? `拉取失败：${polling.error}` : '没有匹配的文件'}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {file && (
        <Modal title={file.path} onClose={() => setFile(null)}>
          {file.truncated && <div className="note note-warn">文件过大，内容被截断</div>}
          <pre className="code">{file.content}</pre>
        </Modal>
      )}
    </div>
  )
}

const NOISE_PATTERN = /(^|\/)(__pycache__|\.DS_Store|\.mimosa|\.zcode|\.venv|node_modules|build|dist|uv\.lock|\.pytest_cache)($|\/)/

function isNoise(line: string): boolean {
  const path = line.slice(3).trim().replace(/^"|"$/g, '')
  if (NOISE_PATTERN.test(path)) return true
  // 二进制/导出产物：按后缀过滤
  return /\.(zip|png|jpg|jpeg|gif|pdf|mp4|mov|woff2?|ttf|jar|class|DS_Store)$/i.test(path)
}

function RepoChanges({ repoId }: { repoId: string }) {
  const polling = usePolling(() => api.gitStatus(repoId), 10000)
  const [diff, setDiff] = useState<string | null>(null)
  const [loadingDiff, setLoadingDiff] = useState(false)
  const [showNoise, setShowNoise] = useState(false)
  const git = polling.data
  if (!git) return null

  async function showDiff() {
    setLoadingDiff(true)
    try {
      const data = await api.gitDiff(repoId)
      setDiff(
        data.diff ||
          '（无已跟踪文件的文本差异。上方列表里的 "？?" 是未跟踪文件——它们还没进 git，diff 不可见；若这些是 agent 的产出，让 agent 正常提交后即可在此审查）',
      )
    } catch (error) {
      setDiff(`读取 diff 失败：${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setLoadingDiff(false)
    }
  }
  const allLines = git.status.trim() ? git.status.trim().split('\n') : []
  const signal = allLines.filter((line) => !isNoise(line))
  const noise = allLines.filter(isNoise)
  const lines = showNoise ? allLines : signal
  return (
    <div className="card">
      <h5>
        仓库变更（git，工作树 vs HEAD）
        {noise.length > 0 && (
          <button className="btn btn-ghost btn-sm" style={{ float: 'right' }} onClick={() => setShowNoise((v) => !v)}>
            {showNoise ? '隐藏产物噪音' : `显示 ${noise.length} 条噪音`}
          </button>
        )}
      </h5>
      {lines.length === 0 ? (
        <div className="muted">{noise.length > 0 ? `仅 ${noise.length} 条产物噪音（未跟踪文件/构建产物），无有效变更` : '工作树干净，没有未提交变更'}</div>
      ) : (
        <>
          <div style={{ marginBottom: 6 }} className="small muted">
            {signal.length} 个有效变更{noise.length ? `（另有 ${noise.length} 条噪音已折叠）` : ''}：
          </div>
          {lines.slice(0, 12).map((line) => (
            <div className="mono" key={line} style={{ padding: '2px 0' }}>
              {line}
            </div>
          ))}
          {lines.length > 12 && <div className="muted small">…还有 {lines.length - 12} 个</div>}
          {git.stat.trim() && <pre className="code" style={{ marginTop: 8 }}>{git.stat}</pre>}
          <button
            className="btn btn-ghost btn-sm"
            style={{ marginTop: 8 }}
            disabled={loadingDiff}
            onClick={() => void showDiff()}
          >
            {loadingDiff ? '加载中…' : '查看完整 diff'}
          </button>
        </>
      )}
      {diff !== null && (
        <Modal title="完整 diff（工作树 vs HEAD）" onClose={() => setDiff(null)}>
          <pre className="code diff">
            {diff.split('\n').map((line, index) => (
              <div
                key={index}
                className={
                  line.startsWith('+') ? 'diff-add' : line.startsWith('-') ? 'diff-del' : line.startsWith('@@') ? 'diff-hunk' : undefined
                }
              >
                {line || ' '}
              </div>
            ))}
          </pre>
        </Modal>
      )}
    </div>
  )
}


function DriverCard({
  repoId,
  run,
  drive,
}: {
  repoId: string
  run: RunState
  drive: DriveStatus | null
}) {
  const toast = useToast()
  const confirm = useConfirm()
  const operable = run.status !== 'completed' && run.status !== 'aborted'
  const [showConsole, setShowConsole] = useState(false)
  const consoleRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (consoleRef.current) consoleRef.current.scrollTop = consoleRef.current.scrollHeight
  }, [drive?.tail?.length])

  async function start() {
    try {
      const config = await api.agentConfig()
      const preview = config.command.replace(
        '{prompt}',
        `接管 ${run.run_id}（需求：${run.requirement.slice(0, 40)}…）`,
      )
      confirm.confirm(
        '驱动 agent（无人值守）',
        <div style={{ lineHeight: 1.8 }}>
          将在仓库目录启动 agent，<b>全自动读写文件、执行命令</b>，直到 run 到达终态或等待审批：
          <pre className="code" style={{ margin: '8px 0' }}>{preview}</pre>
          随时可在本页停止。
        </div>,
        async () => {
          try {
            await api.drive(repoId, run.run_id)
            toast.success('agent 已启动，输出见下方控制台')
            setShowConsole(true)
          } catch (error) {
            toast.error(error instanceof Error ? error.message : String(error))
          }
        },
        { confirmText: '启动 agent', danger: true },
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  async function stop() {
    try {
      await api.driveStop(repoId, run.run_id)
      toast.info('已发送停止信号')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  function statusPill(): { cls: string; text: string } {
    if (!drive || drive.state === 'idle') return { cls: 'pill-pending', text: '未启动' }
    if (drive.state === 'running')
      return { cls: 'pill-running', text: `● 运行中 · pid ${drive.pid}${drive.adopted ? '（重启接管）' : ''}` }
    if (drive.state === 'unknown') return { cls: 'pill-blocked', text: '✕ 已结束（GUI 重启期间，退出码未知）' }
    if (drive.exit_code === 0) return { cls: 'pill-completed', text: '✓ 已正常退出' }
    return { cls: 'pill-blocked', text: `✕ 已退出（code ${drive.exit_code}）` }
  }
  const pill = statusPill()

  return (
    <div className="card" style={{ borderLeft: drive?.active ? '4px solid var(--brand)' : undefined }}>
      <h5>
        Agent 驱动（GUI 直接指挥 agent 干活）
        <span className={`pill ${pill.cls}`} style={{ float: 'right' }}>{pill.text}</span>
      </h5>
      {drive?.command && (
        <div className="muted small mono" style={{ marginBottom: 8, wordBreak: 'break-all' }}>
          命令模板：{drive.command}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {operable && !drive?.active && (
          <button className="btn btn-primary" onClick={() => void start()}>
            ▶ 驱动 agent
          </button>
        )}
        {drive?.active && (
          <button className="btn btn-danger" onClick={() => void stop()}>
            ⏹ 停止 agent
          </button>
        )}
        {drive && drive.tail.length > 0 && (
          <button className="btn btn-ghost btn-sm" onClick={() => setShowConsole((value) => !value)}>
            {showConsole ? '收起控制台' : `控制台（${drive.tail.length} 行）`}
          </button>
        )}
        <button
          className="btn btn-ghost btn-sm"
          style={{ marginLeft: 'auto' }}
          title="改为自己在终端跑"
          onClick={() => {
            const cmd = `$${run.profile === 'grill' ? 'ai-workflow-harness-grill' : 'ai-workflow-harness'} resume ${run.run_id}`
            void navigator.clipboard.writeText(cmd).then(
              () => toast.success('已复制，去终端粘贴即可'),
              () => toast.error('复制失败，请手动选择复制'),
            )
          }}
        >
          偏好终端？复制命令
        </button>
      </div>
      {!operable && (
        <div className="muted small" style={{ marginTop: 8 }}>
          run 已终态（{run.status}），无需驱动。
        </div>
      )}
      {drive?.active && !showConsole && (
        <div className="muted small" style={{ marginTop: 8 }}>
          agent 正在执行，点「控制台」查看实时输出。它会在到达审批 gate 时停下——届时到「审批」Tab 处理。
        </div>
      )}
      {showConsole && drive && (
        <pre className="code" ref={consoleRef} style={{ marginTop: 10, maxHeight: 300 }}>
          {drive.tail.length ? drive.tail.join('\n') : '（暂无输出）'}
        </pre>
      )}
      {confirm.dialog}
    </div>
  )
}
