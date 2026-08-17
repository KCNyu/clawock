/**
 * Read-only scanner over a clawock workspace: prepared runs, the current
 * decision artifact, and published receipts. Pure Node, no Cordis/typert
 * dependencies — unit-testable in isolation.
 *
 * Layout (from the clawock contract):
 *   <workspace>/.clawock/work/<run_id>/request.json   certified request
 *   <workspace>/decision.json                         current artifact
 *   <workspace>/.clawock/runs/<run_id>/               receipt store (manifest.json + artifacts)
 */

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import type { JsonValue, ListRunsResult, RunDetailResult, RunRow } from './types.ts'

/** Request files are written under .clawock/work/<32-hex run id>/request.json. */
export const RUN_ID_PATTERN = /^[0-9a-f]{32}$/

/** Validate a run id; this is also the path-safety boundary for directory joins. */
export function runIdOf(value: unknown): string {
  if (typeof value !== 'string' || !RUN_ID_PATTERN.test(value)) {
    throw new TypeError(`invalid clawock run id: ${String(value)}`)
  }
  return value
}

function readJson(path: string): JsonValue | null {
  if (!existsSync(path)) return null
  try {
    return JSON.parse(readFileSync(path, 'utf8')) as JsonValue
  } catch {
    return null
  }
}

function decisionOf(workspace: string): JsonValue | null {
  return readJson(join(workspace, 'decision.json'))
}

function manifestOf(workspace: string, runId: string): JsonValue | null {
  return readJson(join(workspace, '.clawock', 'runs', runId, 'manifest.json'))
}

/**
 * Snapshot every prepared run with enough to render a list row.
 * @param workspace - clawock workspace root.
 * @returns runs ordered by request file mtime, newest first.
 */
export function listRuns(workspace: string): ListRunsResult['runs'] {
  const workDir = join(workspace, '.clawock', 'work')
  let entries: string[] = []
  try {
    entries = readdirSync(workDir, { withFileTypes: true })
      .filter((e) => e.isDirectory() && RUN_ID_PATTERN.test(e.name))
      .map((e) => e.name)
  } catch {
    return []
  }
  const runs: RunRow[] = []
  const decision = decisionOf(workspace)
  for (const entry of entries) {
    const requestPath = join(workDir, entry, 'request.json')
    if (!existsSync(requestPath)) continue
    const request = readJson(requestPath)
    if (request === null || typeof request !== 'object' || Array.isArray(request)) continue
    const req = request as { [key: string]: JsonValue }
    const subject = typeof req['subject'] === 'string' ? req['subject'] : null
    const decisionSubject = decision !== null && typeof decision === 'object' && !Array.isArray(decision)
      && typeof (decision as { subject?: unknown })['subject'] === 'string'
      ? ((decision as { subject?: unknown })['subject'] as string)
      : null
    const decisionAction = decision !== null && typeof decision === 'object' && !Array.isArray(decision)
      && (decision as { decision?: unknown })['decision'] !== null
      && typeof (decision as { decision?: unknown })['decision'] === 'object'
      && (decision as { decision?: { action?: unknown } })['decision'] !== undefined
      && typeof ((decision as { decision?: { action?: unknown } })['decision'] as { action?: unknown })['action'] === 'string'
      ? ((decision as { decision?: { action?: unknown } })['decision'] as { action?: unknown })['action'] as string
      : null
    const asOf = typeof req['as_of'] === 'string' ? req['as_of'] : null
    const task = typeof req['task'] === 'string' ? req['task'] : null
    const workflow = (req['workflow'] ?? null) as JsonValue | null
    const gates = ((req['workflow'] !== null && typeof req['workflow'] === 'object')
      ? (req['workflow'] as { [key: string]: JsonValue })['parameters'] ?? null
      : null)
    let mtimeMs = 0
    try {
      mtimeMs = statSync(requestPath).mtimeMs
    } catch {
      /* keep 0 */
    }
    runs.push({
      runId: entry,
      subject,
      decisionSubject,
      decisionAction,
      asOf,
      task,
      workflow,
      gates,
      documentCount: Array.isArray(((req['context'] as { [key: string]: JsonValue } | null) ?? {})['documents'])
        ? ((req['context'] as { [key: string]: JsonValue })['documents'] as JsonValue[]).length
        : 0,
      decisionPresent: decision !== null,
      receiptPresent: manifestOf(workspace, entry) !== null,
      mtimeMs,
    })
  }
  runs.sort((a, b) => b.mtimeMs - a.mtimeMs)
  return runs
}

/**
 * Full detail of one run: certified request, current decision artifact and
 * receipt manifest. Missing pieces stay null — a prepared-but-unpublished
 * run is a valid state.
 * @param workspace - clawock workspace root.
 * @param runId - 32-hex run id; anything else is rejected before any path use.
 */
export function getRun(workspace: string, runIdValue: unknown): RunDetailResult {
  const id = runIdOf(runIdValue)
  const request = readJson(join(workspace, '.clawock', 'work', id, 'request.json'))
  if (request === null) {
    return { runId: id, request: null, decision: null, manifest: null }
  }
  return {
    runId: id,
    request,
    decision: decisionOf(workspace),
    manifest: manifestOf(workspace, id),
  }
}
