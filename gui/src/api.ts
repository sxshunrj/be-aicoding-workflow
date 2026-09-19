import type {
  ApprovedEntry,
  DriveStatus,
  Candidate,
  CandidateReview,
  DoctorReport,
  InstallReport,
  RepoEntry,
  RunEvent,
  RunState,
} from './types'

export class ApiError extends Error {
  code: string
  status: number

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let code = 'http_error'
    let message = `HTTP ${response.status}`
    try {
      const body = await response.json()
      code = body.code ?? code
      message = body.message ?? message
    } catch {
      /* keep defaults */
    }
    throw new ApiError(response.status, code, message)
  }
  return (await response.json()) as T
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
}

export const api = {
  repos: () => request<{ repos: RepoEntry[]; reviewer: string }>('/api/repos'),
  registerRepo: (path: string) =>
    post<RepoEntry>('/api/repos', { path }),
  removeRepo: (id: string) => request<{ removed: string }>(`/api/repos/${id}`, { method: 'DELETE' }),
  repoConfig: (id: string) =>
    request<{ repo: RepoEntry; config: Record<string, unknown> }>(`/api/repos/${id}`),
  repoHead: (id: string) => request<{ head: string | null }>(`/api/repos/${id}/head`),
  setReviewer: (reviewer: string) =>
    request<{ reviewer: string }>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify({ reviewer }),
    }),

  runs: (repoId: string) =>
    request<{ runs: RunState[]; errors: Array<{ run_id: string; error: string }> }>(
      `/api/repos/${repoId}/runs`,
    ),
  initRun: (repoId: string, body: { requirement: string; profile: string; source_revision?: string }) =>
    post<RunState>(`/api/repos/${repoId}/runs`, body),
  run: (repoId: string, runId: string) =>
    request<RunState>(`/api/repos/${repoId}/runs/${runId}`),
  reviewAccept: (repoId: string, runId: string, expectedDigest: string) =>
    post<{ run: RunState; auto_resume: { resumed: boolean; reason?: string } }>(
      `/api/repos/${repoId}/runs/${runId}/review-accept`,
      { expected_digest: expectedDigest },
    ),
  block: (repoId: string, runId: string, reason: string) =>
    post<RunState>(`/api/repos/${repoId}/runs/${runId}/block`, { reason }),
  repairGate: (repoId: string, runId: string) =>
    post<RunState>(`/api/repos/${repoId}/runs/${runId}/repair-review-gate`),
  resume: (repoId: string, runId: string, reruns: Record<string, string>) =>
    post<RunState>(`/api/repos/${repoId}/runs/${runId}/resume`, { reruns }),
  abort: (repoId: string, runId: string) =>
    post<RunState>(`/api/repos/${repoId}/runs/${runId}/abort`),
  summary: (repoId: string, runId: string) =>
    request<Record<string, unknown>>(`/api/repos/${repoId}/runs/${runId}/summary`),
  events: (repoId: string, runId: string, limit = 50) =>
    request<{ events: RunEvent[] }>(
      `/api/repos/${repoId}/runs/${runId}/events?limit=${limit}`,
    ),
  runFiles: (repoId: string, runId: string) =>
    request<{ run_id: string; files: Array<{ path: string; size: number; suffix: string }> }>(
      `/api/repos/${repoId}/runs/${runId}/files`,
    ),
  runFile: (repoId: string, runId: string, path: string) =>
    request<{ path: string; size: number; truncated: boolean; content: string }>(
      `/api/repos/${repoId}/runs/${runId}/file?path=${encodeURIComponent(path)}`,
    ),
  gitStatus: (repoId: string) =>
    request<{ status: string; stat: string }>(`/api/repos/${repoId}/git-status`),
  gitDiff: (repoId: string) =>
    request<{ diff: string }>(`/api/repos/${repoId}/git-diff`),
  meta: () => request<{ version: string; python: string }>('/api/meta'),
  agentConfig: () => request<{ command: string }>('/api/agent-config'),
  saveAgentConfig: (command: string) =>
    request<{ command: string }>('/api/agent-config', {
      method: 'PUT',
      body: JSON.stringify({ command }),
    }),
  drive: (repoId: string, runId: string) =>
    post<DriveStatus>(`/api/repos/${repoId}/runs/${runId}/drive`),
  driveStop: (repoId: string, runId: string) =>
    request<DriveStatus>(`/api/repos/${repoId}/runs/${runId}/drive`, {
      method: 'DELETE',
    }),
  driveStatus: (repoId: string, runId: string) =>
    request<DriveStatus>(`/api/repos/${repoId}/runs/${runId}/drive`),

  candidates: (repoId: string) =>
    request<{ candidates: Candidate[] }>(`/api/repos/${repoId}/wiki/candidates`),
  approved: (repoId: string) =>
    request<{ approved: ApprovedEntry[] }>(`/api/repos/${repoId}/wiki/approved`),
  approvedDetail: (repoId: string, entryId: string) =>
    request<ApprovedEntry & { body: string; path: string }>(
      `/api/repos/${repoId}/wiki/approved/${entryId}`,
    ),
  candidateReview: (repoId: string, entryId: string) =>
    request<CandidateReview>(`/api/repos/${repoId}/wiki/candidates/${entryId}`),
  promote: (repoId: string, entryId: string, expectedDigest: string) =>
    post<{ id: string; status: string }>(
      `/api/repos/${repoId}/wiki/candidates/${entryId}/promote`,
      { expected_digest: expectedDigest },
    ),
  reject: (repoId: string, entryId: string, reason: string, expectedDigest: string) =>
    post<{ id: string; status: string }>(
      `/api/repos/${repoId}/wiki/candidates/${entryId}/reject`,
      { reason, expected_digest: expectedDigest },
    ),
  archive: (repoId: string, entryId: string, reason: string, expectedDigest: string) =>
    post<{ id: string; status: string }>(
      `/api/repos/${repoId}/wiki/candidates/${entryId}/archive`,
      { reason, expected_digest: expectedDigest },
    ),

  doctor: (params: { repo?: string; client?: string; source_root?: string }) => {
    const query = new URLSearchParams()
    if (params.repo) query.set('repo', params.repo)
    if (params.client) query.set('client', params.client)
    if (params.source_root) query.set('source_root', params.source_root)
    const suffix = query.toString()
    return request<DoctorReport>(`/api/doctor${suffix ? `?${suffix}` : ''}`)
  },
  install: (body: {
    client: string
    scope: string
    mode: string
    repo?: string
    source_root?: string
  }) => post<InstallReport>('/api/install', body),
}
