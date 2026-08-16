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

/** Request files are written under .clawock/work/<32-hex run id>/request.json. */
export const RUN_ID_PATTERN = /^[0-9a-f]{32}$/

/** Validate a run id; this is also the path-safety boundary for directory joins. */
export function runIdOf(value) {
  if (typeof value !== 'string' || !RUN_ID_PATTERN.test(value)) {
    throw new TypeError(`invalid clawock run id: ${String(value)}`)
  }
  return value
}

function readJson(path) {
  if (!existsSync(path)) return null
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return null
  }
}

function decisionOf(workspace) {
  return readJson(join(workspace, 'decision.json'))
}

function manifestOf(workspace, runId) {
  return readJson(join(workspace, '.clawock', 'runs', runId, 'manifest.json'))
}

/**
 * Snapshot every prepared run with enough to render a list row.
 * @param workspace - clawock workspace root.
 * @returns runs ordered by request file mtime, newest first.
 */
export function listRuns(workspace) {
  const workDir = join(workspace, '.clawock', 'work')
  let entries = []
  try {
    entries = readdirSync(workDir, { withFileTypes: true })
  } catch {
    return []
  }
  const runs = []
  const decision = decisionOf(workspace)
  for (const entry of entries) {
    if (!entry.isDirectory() || !RUN_ID_PATTERN.test(entry.name)) continue
    const requestPath = join(workDir, entry.name, 'request.json')
    if (!existsSync(requestPath)) continue
    const request = readJson(requestPath)
    if (request === null) continue
    let mtimeMs = 0
    try {
      mtimeMs = statSync(requestPath).mtimeMs
    } catch {
      /* keep 0 */
    }
    runs.push({
      runId: entry.name,
      subject: request.subject ?? null,
      decisionSubject: decision?.subject ?? null,
      decisionAction: decision?.decision?.action ?? null,
      asOf: request.as_of ?? null,
      task: request.task ?? null,
      workflow: request.workflow ?? null,
      gates: request.workflow?.parameters ?? null,
      documentCount: request.context?.documents?.length ?? 0,
      decisionPresent: decision !== null,
      receiptPresent: manifestOf(workspace, entry.name) !== null,
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
export function getRun(workspace, runId) {
  const id = runIdOf(runId)
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
