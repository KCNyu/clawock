/**
 * The dispatch queue behind the sidebar-foot task chip: which agent-dispatch
 * tasks are alive, what each one waits for, what just finished, and what the
 * clawock-patrol supervisor is doing (running a round, giving way, or waiting
 * for its next one). Everything is read from this host — files the runner and
 * the supervisor write, plus systemctl/journalctl — never the network.
 *
 *   <logDir>/<id>/meta.env, result.env   bash `printf %q` assignments
 *   <logDir>/<id>/run.log                `---- <ts> quota; sleeping until <ts>`
 *   <limitsPath>                         `MAX_RUNNING=<n>`, shared with both
 *   <patrolDir>/current-round, rounds.tsv
 *   agent-dispatch-<id>.service          active = the task is still alive
 *   clawock-patrol.service + its journal the supervisor's own last words
 *
 * The chip only exists on a host that runs the dispatcher: without `logDir`
 * the answer is `available: false` and the client renders nothing, so the
 * published plugin stays inert elsewhere. Same in-band contract as the
 * balance services: `get()` never throws, a failed read keeps the last good
 * snapshot as 'stale'.
 */

import { execFile } from 'node:child_process'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import type { DispatchTask, PatrolRound, PatrolStatus, TaskQueueResult } from './types.ts'
import { expandHome } from './balance.ts'

export const DEFAULT_DISPATCH_LOG_DIR = join(homedir(), 'logs', 'agent-dispatch')
export const DEFAULT_DISPATCH_LIMITS_PATH = join(homedir(), 'tools', 'agent-dispatch', 'limits.env')
export const DEFAULT_PATROL_STATE_DIR = join(homedir(), 'logs', 'clawock-patrol')
export const DEFAULT_TASK_QUEUE_REFRESH_MS = 15000
export const DEFAULT_TASK_QUEUE_RECENT = 5
/** Host-side cache: every open tab polls, the files are read once per window. */
const TTL_MS = 5000
const COMMAND_TIMEOUT_MS = 5000
const PATROL_UNIT = 'clawock-patrol'

export interface TaskQueueConfig {
  logDir?: string
  limitsPath?: string
  patrolDir?: string
  refreshMs?: number
  recent?: number
}

/** The host commands, injectable so tests run without systemd. */
export interface TaskQueueDeps {
  /** Ids of the active `agent-dispatch-<id>.service` units. */
  activeTaskIds(): Promise<string[]>
  /** `systemctl is-active clawock-patrol` ('' when systemctl is unavailable). */
  patrolService(): Promise<string>
  /** The supervisor's most recent journal lines, oldest first, timestamps kept. */
  patrolLog(): Promise<string[]>
}

function run(command: string, args: string[]): Promise<string> {
  return new Promise((resolve) => {
    execFile(command, args, { timeout: COMMAND_TIMEOUT_MS }, (_error, stdout) => { resolve(String(stdout ?? '')) })
  })
}

export const systemDeps: TaskQueueDeps = {
  async activeTaskIds() {
    const out = await run('systemctl', ['list-units', 'agent-dispatch-*', '--state=active', '--no-legend', '--plain'])
    return out.split('\n').map((line) => line.trim().split(/\s+/)[0] ?? '')
      .filter((unit) => unit.startsWith('agent-dispatch-') && unit.endsWith('.service'))
      .map((unit) => unit.slice('agent-dispatch-'.length, -'.service'.length))
  },
  async patrolService() {
    return (await run('systemctl', ['is-active', PATROL_UNIT])).trim()
  },
  async patrolLog() {
    const out = await run('journalctl', ['-u', PATROL_UNIT, '-n', '12', '-o', 'cat', '--no-pager'])
    return out.split('\n').filter((line) => line.trim() !== '')
  },
}

/** One `printf %q` value: '' / $'…' / backslash escapes. */
export function unquoteShell(raw: string): string {
  if (raw === "''") return ''
  if (raw.startsWith("$'") && raw.endsWith("'")) {
    return raw.slice(2, -1).replace(/\\(.)/g, (_, c: string) => ({ n: '\n', t: '\t' } as Record<string, string>)[c] ?? c)
  }
  if (raw.length >= 2 && raw.startsWith("'") && raw.endsWith("'")) return raw.slice(1, -1)
  return raw.replace(/\\(.)/g, '$1')
}

/** KEY=value lines as the runner writes them; unreadable file → {}. */
export function readEnvFile(path: string): Record<string, string> {
  let text: string
  try { text = readFileSync(path, 'utf8') } catch { return {} }
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const match = /^([A-Z_][A-Z0-9_]*)=(.*)$/.exec(line)
    if (match) out[match[1]!] = unquoteShell(match[2]!)
  }
  return out
}

/** `2026-09-23 02:54:09` in the writer's local time (the runner and dsh share this host's zone). */
export function localStampMs(stamp: string | undefined): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/.exec((stamp ?? '').trim())
  if (!match) return null
  const [, y, mo, d, h, mi, s] = match.map(Number) as number[]
  return new Date(y!, mo! - 1, d!, h!, mi!, s!).getTime()
}

/** When a quota/retry wait ends: the last `sleeping until` line of the run log. */
function wakeAt(dir: string): number | null {
  let text: string
  try {
    text = readFileSync(join(dir, 'run.log'), 'utf8')
  } catch { return null }
  const matches = [...text.slice(-65536).matchAll(/sleeping until (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/g)]
  const last = matches[matches.length - 1]
  return last === undefined ? null : localStampMs(last[1])
}

function readTask(logDir: string, id: string, alive: boolean): DispatchTask {
  const dir = join(logDir, id)
  const meta = readEnvFile(join(dir, 'meta.env'))
  const result = readEnvFile(join(dir, 'result.env'))
  const waiting = alive ? (result.WAITING ?? '') : ''
  return {
    id,
    name: meta.NAME ?? id,
    agent: meta.AGENT ?? '',
    model: result.MODEL_USED || meta.MODEL || '',
    state: result.STATE ?? 'queued',
    // An ended task waits for nothing, whatever an interrupted runner left behind.
    waiting,
    slot: alive ? (result.SLOT ?? '') : '',
    attempts: Number.parseInt(result.ATTEMPTS ?? '0', 10) || 0,
    outcome: result.OUTCOME ?? '',
    startedAtMs: localStampMs(result.STARTED ?? meta.CREATED),
    updatedAtMs: localStampMs(result.UPDATED),
    wakeAtMs: alive && (waiting === 'quota' || waiting === 'retry') ? wakeAt(dir) : null,
    patrol: id.startsWith('patrol-'),
  }
}

function readMaxRunning(path: string): number {
  const value = Number.parseInt(readEnvFile(path).MAX_RUNNING ?? '', 10)
  return Number.isFinite(value) && value > 0 ? value : 0
}

function readRounds(patrolDir: string, limit: number): PatrolRound[] {
  let text: string
  try { text = readFileSync(join(patrolDir, 'rounds.tsv'), 'utf8') } catch { return [] }
  return text.split('\n').filter((line) => line.trim() !== '').slice(-limit).reverse().map((line) => {
    const [endedAt = '', round = '', axis = '', , result = '', took = ''] = line.split('\t')
    const seconds = Number.parseInt(took, 10)
    return { endedAt, round, axis, result, seconds: Number.isFinite(seconds) ? seconds : null }
  })
}

/**
 * What the supervisor is doing, from its own last log line: `waiting: <why>`
 * (giving way before a round), `preempting …` (cancelling one for a user
 * task), `next round in Ns` (gap or backoff), a dispatched/adopted round.
 */
export function patrolPhase(service: string, round: string, roundAlive: boolean, log: string[]): Omit<PatrolStatus, 'rounds'> {
  const lines = log.map((line) => /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$/.exec(line))
    .filter((match): match is RegExpExecArray => match !== null)
  const last = lines[lines.length - 1]
  const detail = last?.[2] ?? ''
  const base = { service: service || 'unknown', round, detail, untilMs: null as number | null }
  if (service !== 'active') return { ...base, phase: 'stopped' }
  if (round !== '' && roundAlive && !/^preempting /.test(detail)) return { ...base, phase: 'running' }
  if (last === undefined) return { ...base, phase: 'unknown' }
  if (/^(waiting: |preempting )/.test(detail)) return { ...base, phase: 'yielding' }
  const gap = /^next round in (\d+)s$/.exec(detail)
  if (gap) {
    const from = localStampMs(last[1])
    return { ...base, phase: 'waiting', untilMs: from === null ? null : from + Number(gap[1]) * 1000 }
  }
  return { ...base, phase: round !== '' ? 'running' : 'unknown' }
}

/** One full read. Throws only when the dispatch log directory itself is unreadable. */
type QueueRead = Omit<TaskQueueResult, 'status' | 'message' | 'refreshMs'>

export async function readTaskQueue(config: Required<TaskQueueConfig>, deps: TaskQueueDeps): Promise<QueueRead> {
  const asOf = new Date().toISOString()
  const empty: PatrolStatus = { service: 'unknown', phase: 'unknown', round: '', detail: '', untilMs: null, rounds: [] }
  if (!existsSync(config.logDir)) {
    return { available: false, asOf, maxRunning: 0, running: 0, active: [], recent: [], patrol: empty }
  }
  const [activeIds, service, log] = await Promise.all([deps.activeTaskIds(), deps.patrolService(), deps.patrolLog()])
  const alive = new Set(activeIds.filter((id) => existsSync(join(config.logDir, id))))
  const active = [...alive].map((id) => readTask(config.logDir, id, true))
    .sort((a, b) => (a.startedAtMs ?? Number.MAX_SAFE_INTEGER) - (b.startedAtMs ?? Number.MAX_SAFE_INTEGER))
  // Newest first by the runner's own UPDATED stamp (file mtime only preselects, so a hand
  // edit to an old result.env cannot float it up); patrol rounds have their own section.
  const ended = readdirSync(config.logDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && !alive.has(entry.name) && !entry.name.startsWith('patrol-'))
    .map((entry) => {
      try { return { id: entry.name, at: statSync(join(config.logDir, entry.name, 'result.env')).mtimeMs } } catch { return null }
    })
    .filter((row): row is { id: string; at: number } => row !== null)
    .sort((a, b) => b.at - a.at)
    .slice(0, config.recent * 3)
    .map((row) => readTask(config.logDir, row.id, false))
    .sort((a, b) => (b.updatedAtMs ?? 0) - (a.updatedAtMs ?? 0))
    .slice(0, config.recent)
  let round = ''
  try { round = readFileSync(join(config.patrolDir, 'current-round'), 'utf8').trim() } catch { /* no round */ }
  return {
    available: true,
    asOf,
    maxRunning: readMaxRunning(config.limitsPath),
    running: active.filter((task) => task.slot !== '').length,
    active,
    recent: ended,
    patrol: { ...patrolPhase(service, round, alive.has(round), log), rounds: readRounds(config.patrolDir, 3) },
  }
}

export type TaskQueueService = { get(force: boolean): Promise<TaskQueueResult> }

/** TTL cache + in-flight join + stale-on-failure, the balance services' cadence shell in miniature. */
export function createTaskQueueService(config: TaskQueueConfig = {}, deps: TaskQueueDeps = systemDeps): TaskQueueService {
  const resolved: Required<TaskQueueConfig> = {
    logDir: expandHome(config.logDir ?? DEFAULT_DISPATCH_LOG_DIR),
    limitsPath: expandHome(config.limitsPath ?? DEFAULT_DISPATCH_LIMITS_PATH),
    patrolDir: expandHome(config.patrolDir ?? DEFAULT_PATROL_STATE_DIR),
    refreshMs: config.refreshMs ?? DEFAULT_TASK_QUEUE_REFRESH_MS,
    recent: config.recent ?? DEFAULT_TASK_QUEUE_RECENT,
  }
  let last: QueueRead | null = null
  let fetchedAt = 0
  let inFlight: Promise<TaskQueueResult> | null = null
  const answer = (status: TaskQueueResult['status'], message: string | null): TaskQueueResult => ({
    available: false, asOf: '', maxRunning: 0, running: 0, active: [], recent: [],
    patrol: { service: 'unknown', phase: 'unknown', round: '', detail: '', untilMs: null, rounds: [] },
    ...(last ?? {}),
    status,
    message,
    refreshMs: resolved.refreshMs,
  })
  const exec = async (): Promise<TaskQueueResult> => {
    try {
      last = await readTaskQueue(resolved, deps)
      fetchedAt = Date.now()
      return answer('fresh', null)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      return answer(last !== null ? 'stale' : 'failed', message)
    }
  }
  return {
    async get(force: boolean): Promise<TaskQueueResult> {
      if (!force && last !== null && Date.now() - fetchedAt < TTL_MS) return answer('cached', null)
      if (inFlight !== null) return inFlight
      inFlight = exec()
      try { return await inFlight } finally { inFlight = null }
    },
  }
}
