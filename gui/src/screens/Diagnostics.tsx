import { useEffect, useState } from 'react'
import { api } from '../api'
import { useApp } from '../App'
import { useToast } from '../toast'
import type { DoctorReport, InstallReport } from '../types'

type Tab = 'doctor' | 'install' | 'config' | 'agent'

export default function Diagnostics() {
  const [tab, setTab] = useState<Tab>('doctor')
  return (
    <div>
      <div className="page-head">
        <h2>装机与诊断</h2>
      </div>
      <div className="tabs" style={{ marginTop: -6 }}>
        <div className={`tab${tab === 'doctor' ? ' active' : ''}`} onClick={() => setTab('doctor')}>
          Doctor 检查
        </div>
        <div className={`tab${tab === 'install' ? ' active' : ''}`} onClick={() => setTab('install')}>
          Install 装机
        </div>
        <div className={`tab${tab === 'config' ? ' active' : ''}`} onClick={() => setTab('config')}>
          Repo 配置
        </div>
        <div className={`tab${tab === 'agent' ? ' active' : ''}`} onClick={() => setTab('agent')}>
          Agent 命令
        </div>
      </div>
      {tab === 'doctor' && <DoctorTab />}
      {tab === 'install' && <InstallTab />}
      {tab === 'config' && <ConfigTab />}
      {tab === 'agent' && <AgentTab />}
    </div>
  )
}

function DoctorTab() {
  const toast = useToast()
  const { repos } = useApp()
  const [repo, setRepo] = useState('')
  const [client, setClient] = useState('all')
  const [report, setReport] = useState<DoctorReport | null>(null)
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    try {
      setReport(await api.doctor({ repo: repo || undefined, client }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="card">
        <h5>检查范围</h5>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="field" style={{ flex: 1, minWidth: 180, margin: 0 }}>
            <label>Repo（可选，选中后检查 config 与 wiki lint）</label>
            <select className="select" value={repo} onChange={(event) => setRepo(event.target.value)}>
              <option value="">（不检查仓库）</option>
              {repos.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ width: 140, margin: 0 }}>
            <label>Client</label>
            <select className="select" value={client} onChange={(event) => setClient(event.target.value)}>
              <option value="all">all</option>
              <option value="codex">codex</option>
              <option value="claude">claude</option>
            </select>
          </div>
          <button className="btn btn-primary" disabled={busy} onClick={() => void run()}>
            {busy ? '检查中…' : '运行检查'}
          </button>
        </div>
      </div>
      {report && (
        <div className="card">
          <h5>
            检查结果{' '}
            <span className={report.ok ? 'pill pill-valid' : 'pill pill-blocked'}>
              {report.ok ? '全部通过' : `${report.data.failed.length} 项失败`}
            </span>
          </h5>
          {report.data.checks.map((check) => (
            <div className="check" key={check.name}>
              <span className={`st ${check.status === 'pass' ? 'st-pass' : check.status === 'fail' ? 'st-fail' : 'st-other'}`}>
                {check.status === 'pass' ? '✓' : check.status === 'fail' ? '✕' : '⚠'}
              </span>
              <span>
                <span style={{ fontWeight: 600 }}>{check.name}</span>
                <br />
                <span className="muted small">{check.message}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function InstallTab() {
  const toast = useToast()
  const { repos } = useApp()
  const [client, setClient] = useState('all')
  const [scope, setScope] = useState('user')
  const [mode, setMode] = useState('auto')
  const [repo, setRepo] = useState('')
  const [sourceRoot, setSourceRoot] = useState('')
  const [report, setReport] = useState<InstallReport | null>(null)
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    try {
      setReport(
        await api.install({
          client,
          scope,
          mode,
          repo: scope === 'repo' ? repo : undefined,
          source_root: sourceRoot.trim() || undefined,
        }),
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const statusPill: Record<string, string> = {
    installed: 'pill-valid',
    updated: 'pill-running',
    skipped: 'pill-pending',
    failed: 'pill-blocked',
  }
  const counts = report?.data.items.reduce<Record<string, number>>((acc, item) => {
    acc[item.status] = (acc[item.status] ?? 0) + 1
    return acc
  }, {})

  return (
    <div>
      <div className="card">
        <h5>装机参数</h5>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="field" style={{ width: 150, margin: 0 }}>
            <label>Client</label>
            <select className="select" value={client} onChange={(event) => setClient(event.target.value)}>
              <option value="all">all (codex+claude)</option>
              <option value="codex">codex</option>
              <option value="claude">claude</option>
            </select>
          </div>
          <div className="field" style={{ width: 120, margin: 0 }}>
            <label>Scope</label>
            <select className="select" value={scope} onChange={(event) => setScope(event.target.value)}>
              <option value="user">user</option>
              <option value="repo">repo</option>
            </select>
          </div>
          <div className="field" style={{ width: 170, margin: 0 }}>
            <label>模式</label>
            <select className="select" value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="auto">auto</option>
              <option value="copy">copy</option>
              <option value="link">link</option>
            </select>
          </div>
          {scope === 'repo' && (
            <div className="field" style={{ width: 180, margin: 0 }}>
              <label>目标 Repo</label>
              <select className="select" value={repo} onChange={(event) => setRepo(event.target.value)}>
                <option value="">（选择仓库）</option>
                {repos.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="field" style={{ flex: 1, minWidth: 220, margin: 0 }}>
            <label>Skills 源（留空自动发现）</label>
            <input
              className="input mono"
              placeholder="…/be-aicoding-workflow/skills"
              value={sourceRoot}
              onChange={(event) => setSourceRoot(event.target.value)}
            />
          </div>
          <button className="btn btn-primary" disabled={busy || (scope === 'repo' && !repo)} onClick={() => void run()}>
            {busy ? '执行中…' : '执行安装'}
          </button>
        </div>
      </div>
      {report && (
        <div className="card">
          <h5>
            结果{' '}
            <span className={report.ok ? 'pill pill-valid' : 'pill pill-blocked'}>
              {Object.entries(counts ?? {})
                .map(([status, count]) => `${count} ${status}`)
                .join(' · ') || '无条目'}
            </span>
          </h5>
          {report.data.items.map((item, index) => (
            <div className="report-row" key={index}>
              <span className={`pill ${statusPill[item.status] ?? 'pill-pending'}`}>{item.status}</span>
              <span style={{ fontWeight: 600 }}>{item.name}</span>
              <span className="muted">{item.client}</span>
              <span className="target">{item.message === item.status ? '' : item.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ConfigTab() {
  const toast = useToast()
  const { repos } = useApp()
  const [repo, setRepo] = useState(repos[0]?.id ?? '')
  const [config, setConfig] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    if (!repo) return
    let cancelled = false
    void api
      .repoConfig(repo)
      .then((data) => {
        if (!cancelled) setConfig(data.config)
      })
      .catch((error: unknown) => {
        toast.error(error instanceof Error ? error.message : String(error))
      })
    return () => {
      cancelled = true
    }
  }, [repo, toast])

  if (repos.length === 0) return <div className="muted">尚未注册任何仓库</div>

  return (
    <div>
      <div className="field" style={{ maxWidth: 280 }}>
        <label>仓库</label>
        <select
          className="select"
          value={repo}
          onChange={(event) => {
            setRepo(event.target.value)
            setConfig(null)
          }}
        >
          {repos.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      {config && (
        <div className="card">
          <h5>.ai-workflow.yaml（只读）</h5>
          {Object.entries(config).map(([key, value]) => (
            <div className="kv" key={key}>
              <b>{key}</b>
              <span className="mono" style={{ textAlign: 'right', wordBreak: 'break-all' }}>
                {typeof value === 'object' ? JSON.stringify(value) : String(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function AgentTab() {
  const toast = useToast()
  const [command, setCommand] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    void api
      .agentConfig()
      .then((data) => setCommand(data.command))
      .catch((error: unknown) => toast.error(error instanceof Error ? error.message : String(error)))
      .finally(() => setLoaded(true))
  }, [toast])

  async function save() {
    setBusy(true)
    try {
      await api.saveAgentConfig(command.trim())
      toast.success('已保存，下次驱动 agent 生效')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  if (!loaded) return <div className="muted">加载中…</div>
  return (
    <div>
      <div className="note">
        「驱动 agent」会用这里的命令模板在仓库目录<b>无人值守</b>启动 AI agent（全自动读写文件、执行命令）。
        模板必须包含 <span className="mono">{'{prompt}'}</span> 占位符——GUI 会把任务指令填进去。
      </div>
      <div className="card">
        <h5>命令模板</h5>
        <div className="field">
          <label>当前模板</label>
          <input
            className="input mono"
            value={command}
            onChange={(event) => setCommand(event.target.value)}
            placeholder="claude -p {prompt} --dangerously-skip-permissions"
          />
        </div>
        <div className="chips">
          <button className="chip" onClick={() => setCommand('claude -p {prompt} --model {model} --dangerously-skip-permissions')}>
            Claude Code 无头模式
          </button>
          <button className="chip" onClick={() => setCommand('caffeinate claude -p {prompt} --model {model} --dangerously-skip-permissions')}>
            Claude + 防休眠
          </button>
          <button className="chip" onClick={() => setCommand('codex exec --full-auto -m {model} {prompt}')}>
            Codex exec
          </button>
        </div>
        <button className="btn btn-primary" disabled={busy || command === ''} onClick={() => void save()}>
          {busy ? '保存中…' : '保存模板'}
        </button>
      </div>
    </div>
  )
}
