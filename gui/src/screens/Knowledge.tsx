import { useState } from 'react'
import { api } from '../api'
import { useApp } from '../App'
import { usePolling } from '../hooks'
import { useToast } from '../toast'
import { TableSkeleton } from '../ui'
import type { ApprovedEntry, Candidate } from '../types'

export default function Knowledge() {
  const { selectedRepo, reviewer } = useApp()
  const [selected, setSelected] = useState<string | null>(null)
  const [section, setSection] = useState<'candidates' | 'approved'>('candidates')

  const polling = usePolling(
    () => api.candidates(selectedRepo!.id),
    10000,
    Boolean(selectedRepo) && section === 'candidates',
  )
  const approvedPolling = usePolling(
    () => api.approved(selectedRepo!.id),
    30000,
    Boolean(selectedRepo) && section === 'approved',
  )

  if (!selectedRepo) {
    return <div className="muted">请先在左侧选择一个仓库</div>
  }

  const candidates = polling.data?.candidates ?? []

  return (
    <div>
      <div className="page-head">
        <h2>
          知识治理 · {selectedRepo.name}
          {(polling.refreshing || approvedPolling.refreshing) && (
            <span className="spinner" style={{ verticalAlign: -1, marginLeft: 8 }} />
          )}
        </h2>
        <span className="muted small">
          审批人：{reviewer || <span style={{ color: 'var(--danger)' }}>未设置（见左栏底部）</span>}
        </span>
      </div>

      <div className="tabs" style={{ marginTop: -6 }}>
        <div
          className={`tab${section === 'candidates' ? ' active' : ''}`}
          onClick={() => {
            setSection('candidates')
            setSelected(null)
          }}
        >
          候选 {candidates.length > 0 && <span className="badge">{candidates.length}</span>}
        </div>
        <div
          className={`tab${section === 'approved' ? ' active' : ''}`}
          onClick={() => {
            setSection('approved')
            setSelected(null)
          }}
        >
          已批准
        </div>
      </div>

      {section === 'candidates' ? (
        selected ? (
          <CandidateDetail
            repoId={selectedRepo.id}
            entryId={selected}
            onBack={() => setSelected(null)}
            onChanged={() => void polling.refresh()}
          />
        ) : (
          polling.data === null && polling.error === null ? (
          <TableSkeleton rows={3} />
        ) : (
          <CandidatesTable candidates={candidates} error={polling.error} onOpen={setSelected} />
        )
        )
      ) : selected ? (
        <ApprovedDetail repoId={selectedRepo.id} entryId={selected} onBack={() => setSelected(null)} />
      ) : (
        <ApprovedTable
          entries={approvedPolling.data?.approved ?? []}
          error={approvedPolling.error}
          onOpen={setSelected}
        />
      )}
    </div>
  )
}

function CandidatesTable({
  candidates,
  error,
  onOpen,
}: {
  candidates: Candidate[]
  error: string | null
  onOpen: (id: string) => void
}) {
  return (
    <div>
      {error && <div className="note note-warn">拉取失败：{error}</div>}
      <table className="data">
        <thead>
          <tr>
            <th>ID</th>
            <th>标题</th>
            <th>类型</th>
            <th>提交时间</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => (
            <tr key={candidate.id} className="row-link" onClick={() => onOpen(candidate.id)}>
              <td className="mono">{candidate.id}</td>
              <td>{candidate.title}</td>
              <td>
                <span className="pill pill-type">{candidate.type}</span>
              </td>
              <td className="muted">{candidate.created_at}</td>
              <td className="chev">›</td>
            </tr>
          ))}
          {candidates.length === 0 && (
            <tr>
              <td colSpan={5} className="muted" style={{ textAlign: 'center', padding: 30 }}>
                暂无候选知识（run 结束后由 agent 的 reflect 流程产出）
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function ApprovedTable({
  entries,
  error,
  onOpen,
}: {
  entries: ApprovedEntry[]
  error: string | null
  onOpen: (id: string) => void
}) {
  return (
    <div>
      {error && <div className="note note-warn">拉取失败：{error}</div>}
      <table className="data">
        <thead>
          <tr>
            <th>ID</th>
            <th>标题</th>
            <th>类型</th>
            <th>摘要</th>
            <th>复审期限</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id} className="row-link" onClick={() => onOpen(entry.id)}>
              <td className="mono">{entry.id}</td>
              <td>{entry.title}</td>
              <td>
                <span className="pill pill-type">{entry.type}</span>
              </td>
              <td style={{ maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {entry.summary}
              </td>
              <td className="muted">{entry.review_after}</td>
              <td className="chev">›</td>
            </tr>
          ))}
          {entries.length === 0 && (
            <tr>
              <td colSpan={6} className="muted" style={{ textAlign: 'center', padding: 30 }}>
                知识库还是空的（候选被批准后会出现在这里）
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function ApprovedDetail({
  repoId,
  entryId,
  onBack,
}: {
  repoId: string
  entryId: string
  onBack: () => void
}) {
  const polling = usePolling(() => api.approvedDetail(repoId, entryId), 0, true)
  const entry = polling.data

  if (polling.error) {
    return (
      <div className="empty">
        <div className="icon">⚠️</div>
        <div className="hint">{polling.error}</div>
        <button className="btn btn-ghost" onClick={onBack}>
          ‹ 返回列表
        </button>
      </div>
    )
  }
  if (!entry) return <div className="muted">加载中…</div>

  return (
    <div>
      <div style={{ marginBottom: 10 }}>
        <button className="btn btn-ghost btn-sm" onClick={onBack}>
          ‹ 返回已批准列表
        </button>
      </div>
      <div className="card">
        <h5>{entry.title}</h5>
        <div className="kv"><b>id</b><span className="mono">{entry.id}</span></div>
        <div className="kv"><b>type</b><span className="pill pill-type">{entry.type}</span></div>
        <div className="kv"><b>tags</b><span>{entry.tags.join(', ') || '—'}</span></div>
        <div className="kv"><b>批准时间</b><span>{entry.reviewed_at ?? '—'}</span></div>
        <div className="kv"><b>复审期限</b><span>{entry.review_after}</span></div>
        <div className="kv"><b>digest</b><span className="mono">{entry.digest.slice(0, 20)}…</span></div>
      </div>
      <div className="card">
        <h5>内容</h5>
        <pre className="code">{entry.body}</pre>
      </div>
    </div>
  )
}

function CandidateDetail({
  repoId,
  entryId,
  onBack,
  onChanged,
}: {
  repoId: string
  entryId: string
  onBack: () => void
  onChanged: () => void
}) {
  const toast = useToast()
  const { reviewer } = useApp()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const polling = usePolling(() => api.candidateReview(repoId, entryId), 0, true)
  const review = polling.data

  if (polling.error) {
    return (
      <div className="empty">
        <div className="icon">⚠️</div>
        <div className="hint">{polling.error}</div>
        <button className="btn btn-ghost" onClick={onBack}>
          ‹ 返回列表
        </button>
      </div>
    )
  }
  if (!review) return <div className="muted">加载中…</div>

  async function act(action: () => Promise<unknown>, done: string) {
    if (!reviewer) {
      toast.error('请先在左栏底部设置审批人')
      return
    }
    setBusy(true)
    try {
      await action()
      toast.success(done)
      onChanged()
      onBack()
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(false)
    }
  }

  const candidateDigest = review.candidate.digest

  return (
    <div>
      <div style={{ marginBottom: 10 }}>
        <button className="btn btn-ghost btn-sm" onClick={onBack}>
          ‹ 返回候选列表
        </button>
      </div>
      <div className="note note-warn">
        批准后进入 approved/ 并可被后续 run 检索；驳回/归档进入 archive/。操作以「{reviewer || '未设置'}」身份执行，带 digest 乐观锁。
      </div>
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: 1.6, minWidth: 320 }}>
          <div className="card">
            <h5>候选 · {review.candidate.title}</h5>
            <div className="kv"><b>id</b><span className="mono">{review.candidate.id}</span></div>
            <div className="kv"><b>type</b><span className="pill pill-type">{review.candidate.type}</span></div>
            <div className="kv"><b>status</b><span className="pill pill-candidate">{review.candidate.status}</span></div>
            <div className="kv"><b>digest</b><span className="mono">{review.candidate.digest.slice(0, 20)}…</span></div>
          </div>
          <div className="card">
            <h5>相关已批准条目（去重对照）</h5>
            {review.related_approved.length === 0 && <div className="muted">无相关条目</div>}
            {review.related_approved.map((item, index) => (
              <div className="kv" key={index}>
                <b className="mono">{String(item.id ?? index)}</b>
                <span className="muted">{String(item.title ?? '')}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="card" style={{ flex: 1, minWidth: 280 }}>
          <h5>治理操作</h5>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button
              className="btn btn-ok"
              disabled={busy}
              onClick={() => void act(() => api.promote(repoId, entryId, candidateDigest), '已批准进入 approved')}
            >
              ✓ 批准（promote）
            </button>
            <div className="field" style={{ margin: 0 }}>
              <label>驳回/归档理由（必填）</label>
              <textarea
                className="textarea"
                style={{ minHeight: 44 }}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </div>
            <button
              className="btn btn-danger"
              disabled={busy || !reason.trim()}
              onClick={() => void act(() => api.reject(repoId, entryId, reason.trim(), candidateDigest), '已驳回')}
            >
              ✕ 驳回（reject）
            </button>
            <button
              className="btn btn-ghost"
              disabled={busy || !reason.trim()}
              onClick={() => void act(() => api.archive(repoId, entryId, reason.trim(), candidateDigest), '已归档')}
            >
              归档（archive）
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
