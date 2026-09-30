/**
 * DSH tool plugin exposing the `ai-coding-workflow` helper CLI to models.
 *
 * ## Why this surface is narrow
 *
 * The helper's primitive operations (`begin` / `stage` / `finalize` /
 * `transition`) are the ones an orchestrator must monopolize: the helper
 * validates *what* an artifact is (ownership, path authorization, digests) but
 * cannot tell *who* produced it. Publishing those primitives as model-facing
 * tools would re-open exactly the "the harness wrote the child's result itself"
 * hole that the Skill contract forbids in prose.
 *
 * So the default surface is the orchestration and inspection layer — start a
 * run, read its state, propose a review, record a human acceptance, resume,
 * abort, search knowledge, run doctor. Run control is available only when a
 * deployment explicitly opts in with `exposeRunControl: true`, which keeps the
 * current Codex-style manual mode available inside DSH.
 *
 * Every tool returns the helper's JSON envelope verbatim, so the model routes
 * on `error.code` instead of guessing from prose.
 *
 * @module dsh-tool-aicoding-workflow
 */

import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import { defineTool, type ParameterSchemaSpec } from '@deepseek-ai/dsh-tools'
import { runHelper, type HelperEnvelope } from './cli.ts'

export const name = 'tool-aicoding-workflow'
export const inject = ['tools']

/** Deployment configuration. */
export interface Config {
  /**
   * argv prefix that launches the helper, e.g. `['ai-workflow']` or
   * `['/abs/path/.venv/bin/ai-workflow']`.
   */
  cli?: string[]
  /** Cooperative per-call timeout budget in milliseconds. */
  timeoutMs?: number
  /**
   * Also expose `begin` / `stage` / `stage-owned` / `finalize` / `transition`.
   * Leave false whenever a code-owned orchestrator drives runs, so run control
   * stays single-owner.
   */
  exposeRunControl?: boolean
}

/** Schemastery configuration for the plugin consumer. */
export const Config: z<Config> = z.object({
  cli: z.array(z.string()),
  timeoutMs: z.number(),
  exposeRunControl: z.boolean(),
})

const DEFAULT_CLI = ['ai-workflow'] as const
const DEFAULT_TIMEOUT_MS = 120_000

/**
 * The canonical output shape: the helper envelope, unchanged.
 *
 * `as const` is load-bearing: without it the schema literals widen to `string`,
 * the spec stops matching `ObjectValueSchemaSpec`, and `InferValue` collapses
 * the tool's declared output to `never`.
 */
const ENVELOPE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    ok: { type: 'boolean', required: true },
    data: { type: 'json' },
    error: {
      type: 'object',
      additionalProperties: false,
      properties: {
        code: { type: 'string', required: true },
        message: { type: 'string', required: true },
        details: { type: 'json' },
      },
    },
    transport: {
      type: 'object',
      additionalProperties: false,
      properties: {
        code: { type: 'string', required: true },
        message: { type: 'string', required: true },
      },
    },
  },
} as const

const ENVELOPE_OUTPUT = {
  schema: ENVELOPE_SCHEMA,
  render: (_args: unknown, value: unknown) => [
    { type: 'text' as const, text: JSON.stringify(value, null, 2) },
  ],
}

type Args = Record<string, unknown>

interface ToolSpec {
  name: string
  description: string
  parameters: ParameterSchemaSpec
  /** Build the helper argv for one validated call. */
  argv(args: Args): string[]
  /** Read-only tools may join a parallel group; mutating tools may not. */
  readOnly?: true
  /** Requires `exposeRunControl: true`. */
  runControl?: true
}

const REPO = { type: 'string', required: true, description: 'Absolute path to the repository that holds .ai-workflow.yaml.' } as const
const RUN_ID = { type: 'string', required: true, description: 'Run id, shaped RUN-YYYYMMDD-HHMMSS-hex6.' } as const
const RERUN = { type: 'array', items: { type: 'string' }, description: 'Repeatable NODE=REASON rerun proposal, e.g. verify.unit_test=flaky timeout in suite A.' } as const

const SPECS: readonly ToolSpec[] = [
  {
    name: 'aiworkflow_status',
    description: 'Read one ai-coding-workflow run state. This is the only recovery entry point: never rebuild attempt, digest, or phase from chat history.',
    parameters: { repo: REPO, run_id: RUN_ID },
    readOnly: true,
    argv: (args) => ['workflow', 'status', '--repo', required(args, 'repo'), '--run-id', required(args, 'run_id')],
  },
  {
    name: 'aiworkflow_summary',
    description: 'Read the derived summary of a terminal run: phase durations, attempt and rerun counts, review gate decisions, cited knowledge ids.',
    parameters: { repo: REPO, run_id: RUN_ID },
    readOnly: true,
    argv: (args) => ['workflow', 'summary', '--repo', required(args, 'repo'), '--run-id', required(args, 'run_id')],
  },
  {
    name: 'aiworkflow_start',
    description: 'Create a new run: persists an immutable run policy and the profile-aware run graph. Use profile grill when requirements still need a PRD loop.',
    parameters: {
      repo: REPO,
      source_revision: { type: 'string', required: true, description: 'Git revision the run is anchored to, usually the current HEAD sha.' },
      requirement: { type: 'string', required: true, description: 'The requirement text this run must satisfy.' },
      profile: { type: 'string', enum: ['full', 'grill'], description: 'full = spec->plan->implement->verify; grill = PRD-driven plan->implement->verify.' },
    },
    argv: (args) => [
      'workflow', 'init',
      '--repo', required(args, 'repo'),
      '--source-revision', required(args, 'source_revision'),
      '--requirement', required(args, 'requirement'),
      ...flag('--profile', optional(args, 'profile')),
    ],
  },
  {
    name: 'aiworkflow_review',
    description: 'Propose the review gate for the finalized current phase. Reruns must be an actionable NODE=REASON mapping; verify phases always require a human decision.',
    parameters: { repo: REPO, run_id: RUN_ID, rerun: RERUN },
    argv: (args) => [
      'workflow', 'review',
      '--repo', required(args, 'repo'),
      '--run-id', required(args, 'run_id'),
      ...flags('--rerun', reruns(args)),
    ],
  },
  {
    name: 'aiworkflow_approve',
    description: 'Record human acceptance of a review gate. The expected digest is mandatory and must be the digest returned by aiworkflow_review; a mismatch means the gate is stale and must be re-proposed.',
    parameters: {
      repo: REPO,
      run_id: RUN_ID,
      expected_digest: { type: 'string', required: true, description: 'sha256 digest of the review gate being accepted.' },
    },
    argv: (args) => [
      'workflow', 'review-accept',
      '--repo', required(args, 'repo'),
      '--run-id', required(args, 'run_id'),
      '--expected-digest', required(args, 'expected_digest'),
    ],
  },
  {
    name: 'aiworkflow_block',
    description: 'Mark the run blocked with an actionable reason. Blocked runs only leave that state through an explicit human aiworkflow_resume or aiworkflow_abort.',
    parameters: { repo: REPO, run_id: RUN_ID, reason: { type: 'string', required: true, description: 'Blocking fact, its evidence source, and what must change to unblock.' } },
    argv: (args) => [
      'workflow', 'block',
      '--repo', required(args, 'repo'),
      '--run-id', required(args, 'run_id'),
      '--reason', required(args, 'reason'),
    ],
  },
  {
    name: 'aiworkflow_resume',
    description: 'Leave the blocked state. Pass rerun proposals when the resume also changes which nodes must run again; omit them to simply unblock.',
    parameters: { repo: REPO, run_id: RUN_ID, rerun: RERUN },
    argv: (args) => [
      'workflow', 'resume',
      '--repo', required(args, 'repo'),
      '--run-id', required(args, 'run_id'),
      ...flags('--rerun', reruns(args)),
    ],
  },
  {
    name: 'aiworkflow_abort',
    description: 'Terminate the run as aborted. Irreversible for that run; knowledge reflection and Git handoff still require their own human decisions.',
    parameters: { repo: REPO, run_id: RUN_ID },
    argv: (args) => ['workflow', 'abort', '--repo', required(args, 'repo'), '--run-id', required(args, 'run_id')],
  },
  {
    name: 'aiworkflow_reflect',
    description: 'Build the immutable reflection packet for a completed or aborted run and return its path and evidence digest.',
    parameters: { repo: REPO, run_id: RUN_ID },
    argv: (args) => ['workflow', 'reflect', '--repo', required(args, 'repo'), '--run-id', required(args, 'run_id')],
  },
  {
    name: 'aiworkflow_wiki_search',
    description: 'Search approved knowledge only. Results carry no file body: read bounded knowledge through a packet, never by opening wiki Markdown directly.',
    parameters: {
      wiki: { type: 'string', required: true, description: 'Absolute path to the wiki root containing taxonomy.yaml and approved/.' },
      text: { type: 'string', description: 'Free-text query tokens.' },
      repository: { type: 'string', description: 'Scope filter: repository name.' },
      phase: { type: 'string', description: 'Scope filter: spec, plan, implement, or verify.' },
      type: { type: 'array', items: { type: 'string' }, description: 'Repeatable knowledge type filter.' },
      tag: { type: 'array', items: { type: 'string' }, description: 'Repeatable tag filter.' },
      max_entries: { type: 'integer', description: 'Maximum number of entries to return.' },
      max_characters: { type: 'integer', description: 'Maximum characters budget for the result set.' },
    },
    readOnly: true,
    argv: (args) => [
      'wiki', 'search',
      '--wiki', required(args, 'wiki'),
      ...flag('--text', optional(args, 'text')),
      ...flag('--repository', optional(args, 'repository')),
      ...flag('--phase', optional(args, 'phase')),
      ...flags('--type', list(args, 'type')),
      ...flags('--tag', list(args, 'tag')),
      ...flag('--max-entries', optionalNumber(args, 'max_entries')),
      ...flag('--max-characters', optionalNumber(args, 'max_characters')),
    ],
  },
  {
    name: 'aiworkflow_doctor',
    description: 'Diagnose the helper environment: python version, skill layout and install digests, repository config, wiki lint.',
    parameters: {
      source_root: { type: 'string', required: true, description: 'Absolute path of the skills/ directory being installed.' },
      repo: { type: 'string', description: 'Repository to also check config and wiki lint for.' },
      client: { type: 'string', enum: ['codex', 'claude', 'all'], description: 'Client install roots to verify.' },
    },
    readOnly: true,
    argv: (args) => [
      'doctor',
      '--source-root', required(args, 'source_root'),
      ...flag('--repo', optional(args, 'repo')),
      ...flag('--client', optional(args, 'client')),
    ],
  },
  {
    name: 'aiworkflow_begin',
    description: 'Run control: start or resume the current phase attempt and return the dispatch plan. Requires exposeRunControl.',
    parameters: {
      repo: REPO,
      run_id: RUN_ID,
      phase: { type: 'string', required: true, enum: ['spec', 'plan', 'implement', 'verify'], description: 'Phase to begin; must equal the run current_phase.' },
      skill_dir: { type: 'string', description: 'Absolute path of the skill directory holding references/agents contracts; required for child-backed phases.' },
    },
    runControl: true,
    argv: (args) => [
      'workflow', 'begin',
      '--repo', required(args, 'repo'),
      '--run-id', required(args, 'run_id'),
      '--phase', required(args, 'phase'),
      ...flag('--skill-dir', optional(args, 'skill_dir')),
    ],
  },
  {
    name: 'aiworkflow_stage',
    description: 'Run control: record one schema-v2 ChildResult for a child of the current attempt. Requires exposeRunControl.',
    parameters: {
      repo: REPO,
      run_id: RUN_ID,
      attempt_id: { type: 'string', required: true, description: 'Attempt id returned by aiworkflow_begin.' },
      child: { type: 'string', required: true, description: 'Child name from the dispatch plan, e.g. spec, solution, code, unit_test.' },
      result: { type: 'string', required: true, description: 'Absolute path of the raw ChildResult JSON produced by that child.' },
    },
    runControl: true,
    argv: (args) => [
      'workflow', 'stage',
      '--repo', required(args, 'repo'),
      '--run-id', required(args, 'run_id'),
      '--attempt-id', required(args, 'attempt_id'),
      '--child', required(args, 'child'),
      '--result', required(args, 'result'),
    ],
  },
  {
    name: 'aiworkflow_finalize',
    description: 'Run control: settle the phase barrier and aggregate staged children. This never advances the phase. Requires exposeRunControl.',
    parameters: {
      repo: REPO,
      run_id: RUN_ID,
      attempt_id: { type: 'string', required: true, description: 'Attempt id returned by aiworkflow_begin.' },
    },
    runControl: true,
    argv: (args) => [
      'workflow', 'finalize',
      '--repo', required(args, 'repo'),
      '--run-id', required(args, 'run_id'),
      '--attempt-id', required(args, 'attempt_id'),
    ],
  },
  {
    name: 'aiworkflow_transition',
    description: 'Run control: consume the accepted review gate and advance the phase or apply reruns. Requires exposeRunControl.',
    parameters: { repo: REPO, run_id: RUN_ID },
    runControl: true,
    argv: (args) => ['workflow', 'transition', '--repo', required(args, 'repo'), '--run-id', required(args, 'run_id')],
  },
]

/**
 * Register the model-facing tool surface.
 * @param ctx - Cordis context providing the tool registry.
 * @param config - deployment configuration.
 */
export function apply(ctx: Context, config: Config): void {
  const cli = config.cli ?? [...DEFAULT_CLI]
  const timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const exposeRunControl = config.exposeRunControl === true
  const specs = exposeRunControl ? SPECS : SPECS.filter((spec) => spec.runControl !== true)

  for (const spec of specs) {
    ctx.tools.register(defineTool({
      name: spec.name,
      description: spec.description,
      parameters: spec.parameters,
      output: ENVELOPE_OUTPUT,
      ...(spec.readOnly === true ? { isConcurrencySafe: () => true } : {}),
      async execute(args: Args, exec): Promise<HelperEnvelope> {
        const argv = spec.argv(args)
        const result = await runHelper(argv, { argv: cli, timeoutMs, signal: exec.signal })
        return result.envelope
      },
    }))
  }

  ctx.logger.info(
    `tool-aicoding-workflow: registered ${specs.length} tools `
    + `(cli=${cli.join(' ')}, run control=${exposeRunControl})`,
  )
}

function required(args: Args, key: string): string {
  const value = args[key]
  if (typeof value !== 'string' || value.length === 0) {
    // The registry rejects missing required parameters first; this guards direct callers.
    throw new Error(`ai-workflow tool argument "${key}" must be a non-empty string`)
  }
  return value
}

function optional(args: Args, key: string): string | undefined {
  const value = args[key]
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function optionalNumber(args: Args, key: string): number | undefined {
  const value = args[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function list(args: Args, key: string): string[] {
  const value = args[key]
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string' && item.length > 0)
}

/**
 * Validate the repeatable `NODE=REASON` shape before spending a helper call.
 * The helper re-validates; this only gives the model an immediate, specific error.
 * @param args - validated call arguments.
 * @returns well-formed `NODE=REASON` entries.
 */
function reruns(args: Args): string[] {
  const entries = list(args, 'rerun')
  const seen = new Set<string>()
  for (const entry of entries) {
    const separator = entry.indexOf('=')
    const node = separator === -1 ? '' : entry.slice(0, separator).trim()
    const reason = separator === -1 ? '' : entry.slice(separator + 1).trim()
    if (node.length === 0 || reason.length === 0) {
      throw new Error(`rerun entry "${entry}" must use NODE=REASON with a non-empty node and reason`)
    }
    if (seen.has(node)) {
      throw new Error(`rerun node "${node}" was proposed twice; merge the reasons into one entry`)
    }
    seen.add(node)
  }
  return entries
}

function flag(name: string, value: string | number | undefined): string[] {
  return value === undefined ? [] : [name, String(value)]
}

function flags(name: string, values: readonly string[]): string[] {
  return values.flatMap((value) => [name, value])
}
