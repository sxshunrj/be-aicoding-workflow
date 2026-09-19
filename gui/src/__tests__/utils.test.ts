import { describe, expect, it } from 'vitest'
import { parseRunTime, pendingGate, type RunState } from '../types'

describe('parseRunTime', () => {
  it('解析 run_id 中的时间戳', () => {
    expect(parseRunTime('RUN-20260919-101524-9f3c1a')).toBe('2026-09-19 10:15:24')
  })

  it('非 run_id 返回空串', () => {
    expect(parseRunTime('not-a-run')).toBe('')
  })
})

describe('pendingGate', () => {
  const base: RunState = {
    run_id: 'RUN-20260919-101524-9f3c1a',
    version: 3,
    status: 'blocked',
    current_phase: 'verify',
    source_revision: 'abc',
    requirement: 'r',
    profile: 'full',
    run_graph: {},
    artifacts: {},
  }

  it('human_review 且未接受 → pending', () => {
    const gate = { decision: 'human_review', accepted_at: null, digest: 'd', phase: 'verify', run_id: base.run_id, state_version: 4, proposed_reruns: [], effective_reruns: [] }
    expect(pendingGate({ ...base, artifacts: { review_gate: gate } })?.digest).toBe('d')
  })

  it('已接受的 gate 不算 pending', () => {
    const gate = { decision: 'human_review', accepted_at: '2026-09-19T10:00:00', digest: 'd', phase: 'verify', run_id: base.run_id, state_version: 4, proposed_reruns: [], effective_reruns: [] }
    expect(pendingGate({ ...base, artifacts: { review_gate: gate } })).toBeNull()
  })

  it('auto_accept 的 decision 不算 pending', () => {
    const gate = { decision: 'accept', accepted_at: null, digest: 'd', phase: 'verify', run_id: base.run_id, state_version: 4, proposed_reruns: [], effective_reruns: [] }
    expect(pendingGate({ ...base, artifacts: { review_gate: gate } })).toBeNull()
  })

  it('无 artifacts → null', () => {
    expect(pendingGate(base)).toBeNull()
  })
})
