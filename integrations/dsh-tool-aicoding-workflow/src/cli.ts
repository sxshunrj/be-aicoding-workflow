/**
 * Bridge from the DSH tool plugin to the Python `ai-workflow` helper CLI.
 *
 * The helper owns every state mutation and answers with exactly one JSON
 * envelope per call: `{"ok":true,"data":…}` or
 * `{"ok":false,"error":{code,message,details}}`.
 *
 * Two deliberate properties:
 *
 * 1. This module never throws for helper failures. It returns the envelope so
 *    the model routes on `error.code`, exactly as the Skill contract requires
 *    ("Helper error 只按 error.code 路由，不按 message 猜").
 * 2. A stdout that is not a JSON envelope is reported as
 *    `helper_transport_error` instead of being parsed loosely. The CLI catches
 *    `AppError` only, so an unhandled exception prints a traceback; treating
 *    that as a transport failure keeps the envelope contract intact at the
 *    tool boundary.
 *
 * @module dsh-tool-aicoding-workflow/cli
 */

import { execFile } from 'node:child_process'

/** Lossless JSON value, matching the wire type shared with the helper. */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }

/** One helper response envelope, plus the transport marker this bridge adds. */
export interface HelperEnvelope {
  ok: boolean
  data?: Json
  error?: { code: string; message: string; details?: Json }
  /** Present only when the helper could not be reached or did not answer with an envelope. */
  transport?: { code: string; message: string }
}

/** A helper invocation: the argv prefix, the cooperative timeout, and cancellation. */
export interface HelperInvocation {
  /** argv prefix, e.g. `['ai-workflow']` or `['/abs/.venv/bin/ai-workflow']`. */
  argv: readonly string[]
  timeoutMs: number
  signal?: AbortSignal
}

/** The helper's answer plus its exit status. */
export interface HelperResult {
  envelope: HelperEnvelope
  exitCode: number | null
}

const MAX_BUFFER_BYTES = 8 * 1024 * 1024
const STDERR_TAIL_CHARS = 2000

/**
 * Run the helper CLI once and normalize its answer into an envelope.
 * @param args - helper arguments, appended after the configured argv prefix.
 * @param invocation - argv prefix, timeout, and cancellation signal.
 * @returns the envelope and the observed exit status.
 */
export async function runHelper(
  args: readonly string[],
  invocation: HelperInvocation,
): Promise<HelperResult> {
  const argv = [...invocation.argv, ...args]
  const executable = argv[0]
  if (executable === undefined || executable.length === 0) {
    return transportFailure('helper_not_configured', 'the helper argv prefix is empty')
  }

  return await new Promise<HelperResult>((resolve) => {
    execFile(
      executable,
      argv.slice(1),
      {
        timeout: invocation.timeoutMs,
        signal: invocation.signal,
        maxBuffer: MAX_BUFFER_BYTES,
        encoding: 'utf8',
      },
      (error, stdout, stderr) => {
        const exitCode = exitStatusOf(error)
        if (error !== null && (error as NodeJS.ErrnoException).code === 'ENOENT') {
          resolve(transportFailure('helper_not_found', `helper executable not found: ${executable}`))
          return
        }
        const envelope = parseEnvelope(stdout)
        if (envelope === undefined) {
          resolve(
            transportFailure(
              'helper_transport_error',
              `ai-workflow did not emit a JSON envelope (exit ${exitCode ?? 'unknown'}): ${tail(stderr)}`,
            ),
          )
          return
        }
        resolve({ envelope, exitCode })
      },
    )
  })
}

/**
 * Parse the helper's single-line JSON envelope.
 * @param stdout - raw stdout of the helper process.
 * @returns the parsed envelope, or `undefined` when stdout is not an envelope.
 */
export function parseEnvelope(stdout: string): HelperEnvelope | undefined {
  const lines = stdout.split('\n').map((line) => line.trim()).filter((line) => line.length > 0)
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const candidate = lines[index]
    if (candidate === undefined || !candidate.startsWith('{')) continue
    try {
      const parsed: unknown = JSON.parse(candidate)
      if (typeof parsed === 'object' && parsed !== null && typeof (parsed as { ok?: unknown }).ok === 'boolean') {
        return parsed as HelperEnvelope
      }
    } catch {
      // Not this line; keep looking for an envelope-shaped line.
    }
  }
  return undefined
}

function transportFailure(code: string, message: string): HelperResult {
  return {
    envelope: { ok: false, error: { code, message }, transport: { code, message } },
    exitCode: null,
  }
}

function exitStatusOf(error: unknown): number | null {
  if (error === null || error === undefined) return 0
  const code = (error as { code?: unknown }).code
  return typeof code === 'number' ? code : null
}

function tail(text: string): string {
  const trimmed = text.trim()
  return trimmed.length <= STDERR_TAIL_CHARS ? trimmed : trimmed.slice(-STDERR_TAIL_CHARS)
}
