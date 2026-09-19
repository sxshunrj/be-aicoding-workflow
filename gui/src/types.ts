export interface RepoEntry {
  id: string
  name: string
  path: string
}

export type NodeValidity = 'pending' | 'valid' | 'rerun'

export interface RunGraphNode {
  phase: string
  child: string
  validity: NodeValidity
  reason: string | null
}

export interface ReviewGate {
  decision: 'human_review' | 'accept'
  run_id: string
  phase: string
  state_version: number
  proposed_reruns: [string, string][]
  effective_reruns: [string, string][]
  digest: string
  policy_digest?: string
  proposed_at?: string | null
  accepted_version?: number | null
  accepted_at?: string | null
}

export interface RunState {
  run_id: string
  version: number
  status: string
  current_phase: string
  source_revision: string
  requirement: string
  profile: string
  run_graph: Record<string, RunGraphNode>
  artifacts: Record<string, unknown>
}

export interface RunEvent {
  type: string
  version?: number
  data?: Record<string, unknown>
  timestamp?: string | null
}

export interface Candidate {
  id: string
  title: string
  type: string
  status: string
  summary: string
  tags: string[]
  created_at: string
  path: string
  digest: string
}

export interface CandidateReview {
  candidate: {
    id: string
    title: string
    type: string
    digest: string
    status: string
  }
  related_approved: Array<Record<string, unknown>>
  declared_conflicts: string[]
  declared_supersedes: string[]
}

export interface InstallItem {
  name: string
  client: string
  source: string
  target: string
  digest: string
  status: 'installed' | 'updated' | 'skipped' | 'failed'
  message: string
}

export interface InstallReport {
  ok: boolean
  data: { items: InstallItem[]; manifest_path: string; failed: InstallItem[] }
}

export interface DoctorCheck {
  name: string
  status: 'pass' | 'fail' | string
  message: string
}

export interface DoctorReport {
  ok: boolean
  data: { checks: DoctorCheck[]; failed: DoctorCheck[] }
}

export interface ApprovedEntry {
  id: string
  title: string
  type: string
  status: string
  summary: string
  tags: string[]
  created_at: string
  reviewed_at: string | null
  review_after: string
  digest: string
}

export interface DriveStatus {
  active: boolean
  state: 'running' | 'exited' | 'unknown' | 'idle'
  adopted: boolean
  command: string | null
  pid: number | null
  exit_code: number | null
  started_at: number | null
  finished_at: number | null
  tail: string[]
}

export const PHASE_ORDER = ['spec', 'plan', 'implement', 'verify'] as const

export const PHASE_LABEL: Record<string, string> = {
  spec: '需求规格',
  plan: '实施计划',
  implement: '实现',
  verify: '验证',
}

export const RUN_STATUS_LABEL: Record<string, string> = {
  pending: '○ 待启动',
  running: '● 运行中',
  blocked: '⚑ 待处理',
  completed: '✓ 已完成',
  aborted: '✕ 已中止',
}

export const VALIDITY_LABEL: Record<NodeValidity, string> = {
  pending: '待执行',
  valid: '通过',
  rerun: '重跑',
}

export function parseRunTime(runId: string): string {
  const match = runId.match(/^RUN-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-/)
  if (!match) return ''
  const [, y, mo, d, h, mi, s] = match
  return `${y}-${mo}-${d} ${h}:${mi}:${s}`
}

export function pendingGate(run: RunState): ReviewGate | null {
  const gate = run.artifacts['review_gate'] as ReviewGate | undefined
  if (!gate || gate.decision !== 'human_review') return null
  if (gate.accepted_at) return null
  return gate
}
