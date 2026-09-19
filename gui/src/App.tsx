import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
import { NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { api } from './api'
import type { RepoEntry } from './types'
import { useToast } from './toast'
import { Modal, useConfirm } from './ui'
import { ErrorBoundary, useGlobalErrorReporting } from './errors'
import Dashboard from './screens/Dashboard'
import RunDetail from './screens/RunDetail'
import Knowledge from './screens/Knowledge'
import Diagnostics from './screens/Diagnostics'

interface AppCtx {
  repos: RepoEntry[]
  reviewer: string
  selectedRepo: RepoEntry | null
  selectRepo: (id: string) => void
  reloadRepos: () => Promise<void>
}

const AppContext = createContext<AppCtx>({
  repos: [],
  reviewer: '',
  selectedRepo: null,
  selectRepo: () => {},
  reloadRepos: async () => {},
})

export function useApp(): AppCtx {
  return useContext(AppContext)
}

export default function App() {
  const toast = useToast()
  const navigate = useNavigate()
  const [repos, setRepos] = useState<RepoEntry[]>([])
  const [reviewer, setReviewerState] = useState('')
  const [selectedId, setSelectedId] = useState<string>(
    () => window.localStorage.getItem('aiw.selectedRepo') ?? '',
  )
  const [adding, setAdding] = useState(false)
  const [candidatePath, setCandidatePath] = useState('')
  const [reviewerDraft, setReviewerDraft] = useState<string | null>(null)
  const [version, setVersion] = useState('')
  const confirm = useConfirm()

  useGlobalErrorReporting()

  const reloadRepos = useCallback(async () => {
    try {
      const data = await api.repos()
      setRepos(data.repos)
      setReviewerState(data.reviewer)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }, [toast])

  useEffect(() => {
    void reloadRepos()
    void api.meta().then((data) => setVersion(`v${data.version} · py${data.python}`)).catch(() => {})
  }, [reloadRepos])

  const selectedRepo = repos.find((repo) => repo.id === selectedId) ?? null

  const selectRepo = useCallback((id: string) => {
    setSelectedId(id)
    window.localStorage.setItem('aiw.selectedRepo', id)
  }, [])

  useEffect(() => {
    if (!selectedRepo && repos.length > 0) selectRepo(repos[0].id)
  }, [repos, selectedRepo, selectRepo])

  async function registerRepo() {
    const path = candidatePath.trim()
    if (!path) return
    try {
      const entry = await api.registerRepo(path)
      await reloadRepos()
      selectRepo(entry.id)
      setAdding(false)
      setCandidatePath('')
      toast.success(`已注册仓库：${entry.name}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  async function removeRepo(id: string, name: string) {
    confirm.confirm(
      '移除仓库',
      `移除已注册的仓库「${name}」？（不会动磁盘上的任何文件）`,
      async () => {
        try {
          await api.removeRepo(id)
          await reloadRepos()
          toast.info(`已移除：${name}`)
        } catch (error) {
          toast.error(error instanceof Error ? error.message : String(error))
        }
      },
      { confirmText: '移除', danger: true },
    )
  }

  async function saveReviewer() {
    if (reviewerDraft === null) return
    const value = reviewerDraft.trim()
    if (!value) {
      toast.error('审批人名不能为空')
      return
    }
    try {
      await api.setReviewer(value)
      setReviewerState(value)
      setReviewerDraft(null)
      toast.success(`审批人已设置为 ${value}`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <ErrorBoundary>
    <AppContext.Provider
      value={{ repos, reviewer, selectedRepo, selectRepo, reloadRepos }}
    >
      <div className="shell">
        <aside className="sidebar">
          <div className="logo">⌘ ai-workflow</div>
          <NavLink to="/" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            Runs
          </NavLink>
          <NavLink to="/knowledge" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            知识治理
          </NavLink>
          <NavLink to="/diagnostics" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            装机与诊断
          </NavLink>
          <div className="nav-group">仓库</div>
          {repos.map((repo) => (
            <div
              key={repo.id}
              className={`repo-item${repo.id === selectedRepo?.id ? ' active' : ''}`}
              onClick={() => {
                selectRepo(repo.id)
                navigate('/')
              }}
              title={repo.path}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{repo.name}</span>
              <button
                className="repo-del"
                title="移除注册"
                onClick={(event) => {
                  event.stopPropagation()
                  void removeRepo(repo.id, repo.name)
                }}
              >
                ✕
              </button>
            </div>
          ))}
          <button className="repo-add" onClick={() => setAdding(true)}>
            ＋ 添加仓库
          </button>
          <div style={{ marginTop: 'auto', padding: '10px 16px 0' }}>
            <div className="nav-group" style={{ padding: 0, marginBottom: 4 }}>
              审批人
            </div>
            {reviewerDraft === null ? (
              <div
                className="small"
                style={{ color: reviewer ? 'var(--side-ink)' : 'var(--danger)', cursor: 'pointer' }}
                onClick={() => setReviewerDraft(reviewer)}
                title="点击修改"
              >
                {reviewer || '⚠ 未设置（点击设置）'}
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 4 }}>
                <input
                  className="input"
                  style={{ padding: '3px 6px', fontSize: 11.5 }}
                  value={reviewerDraft}
                  onChange={(event) => setReviewerDraft(event.target.value)}
                  onKeyDown={(event) => event.key === 'Enter' && void saveReviewer()}
                  autoFocus
                />
                <button className="btn btn-primary btn-sm" onClick={() => void saveReviewer()}>
                  存
                </button>
              </div>
            )}
          </div>
          <div className="small" style={{ color: "#5d6577", marginTop: 6 }}>{version}</div>
        </aside>
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/runs/:runId" element={<RunDetail />} />
            <Route path="/knowledge" element={<Knowledge />} />
            <Route path="/diagnostics" element={<Diagnostics />} />
          </Routes>
        </main>
      </div>
      {confirm.dialog}
      {adding && (
        <Modal title="添加仓库" onClose={() => setAdding(false)}>
          <div className="field">
            <label>仓库路径（需包含 .ai-workflow.yaml）</label>
            <input
              className="input mono"
              placeholder="/Users/you/work/code/git/your-repo"
              value={candidatePath}
              onChange={(event) => setCandidatePath(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && void registerRepo()}
              autoFocus
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <button className="btn btn-ghost" onClick={() => setAdding(false)}>
              取消
            </button>
            <button className="btn btn-primary" onClick={() => void registerRepo()}>
              校验并注册
            </button>
          </div>
        </Modal>
      )}
    </AppContext.Provider>
    </ErrorBoundary>
  )
}
