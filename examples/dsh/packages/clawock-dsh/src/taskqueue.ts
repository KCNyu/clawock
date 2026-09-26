/**
 * The dispatch queue behind the sidebar-foot task chip: which agent-dispatch
 * tasks are alive, what each one waits for, what just finished, and what the
 * clawock-patrol supervisor is doing (running a round, giving way, or waiting
 * for its next one). Everything is read from this host — files the runner and
 * the supervisor write, plus systemctl/journalctl — never the network.
 *
 *   <logDir>/<id>/meta.env, result.env   bash `printf %q` assignments
 *   <logDir>/<id>/run.log                `---- <ts> quota; sleeping until <ts>`,
 *                                        `<ts> <event>` lines, `final | <text>` (the agent's closing lines)
 *   <limitsPath>                         `MAX_RUNNING_<AGENT>=<n>` (each agent's own slots) and
 *                                        their display-only sum `MAX_RUNNING`, shared with both
 *   <patrolDir>/current-round, rounds.tsv
 *   agent-dispatch-<id>.service          active = the task is still alive
 *   clawock-patrol.service + its journal the supervisor's own last words
 *   <logDir>/<id>/override.env           PRIORITY / MODEL / EFFORT set from the chip (read only here)
 *   task_queue_ops.py --json list        per-agent lock holder and queue order
 *
 * Every WRITE (cancel, priority, model, retry, wrap-up) goes through the
 * versioned ops entry `task_queue_ops.py` (ops/host in the clawock repo,
 * installed next to the runner): this module never runs systemctl stop,
 * flock or edits a task directory. `runQueueAction` is that one door.
 *
 * The chip only exists on a host that runs the dispatcher: without `logDir`
 * the answer is `available: false` and the client renders nothing, so the
 * published plugin stays inert elsewhere. Same in-band contract as the
 * balance services: `get()` never throws, a failed read keeps the last good
 * snapshot as 'stale'.
 */

import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import { closeSync, existsSync, fstatSync, openSync, readFileSync, readSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import type {
  AgentQueue, AgentSlotLimit, DispatchTask, OpsStatus, PatrolRound, PatrolStatus, QueueActionResult, TaskQueueResult,
} from './types.ts'
import { expandHome } from './balance.ts'

export const DEFAULT_DISPATCH_LOG_DIR = join(homedir(), 'logs', 'agent-dispatch')
export const DEFAULT_DISPATCH_LIMITS_PATH = join(homedir(), 'tools', 'agent-dispatch', 'limits.env')
export const DEFAULT_PATROL_STATE_DIR = join(homedir(), 'logs', 'clawock-patrol')
export const DEFAULT_TASK_QUEUE_OPS_PATH = join(homedir(), 'tools', 'agent-dispatch', 'task_queue_ops.py')
export const DEFAULT_TASK_QUEUE_REFRESH_MS = 15000
export const DEFAULT_TASK_QUEUE_RECENT = 5
/** Host-side cache: every open tab polls, the files are read once per window. */
const TTL_MS = 5000
const COMMAND_TIMEOUT_MS = 5000
/** How much of a run log's end is read: every line the queue shows sits in its last few KB. */
const LOG_TAIL_BYTES = 65536
/** The detail panel's cap on the closing report (the runner already keeps only six lines). */
const SUMMARY_MAX_CHARS = 800
const PATROL_UNIT = 'clawock-patrol'

export interface TaskQueueConfig {
  logDir?: string
  limitsPath?: string
  patrolDir?: string
  refreshMs?: number
  recent?: number
  /** The installed ops entry (default ~/tools/agent-dispatch/task_queue_ops.py). */
  opsPath?: string
  /** The repository's copy of it, hashed to show a merged-but-not-installed entry ('' = skip). */
  repoOpsPath?: string
}

/** The host commands, injectable so tests run without systemd. */
export interface TaskQueueDeps {
  /** Ids of the active `agent-dispatch-<id>.service` units. */
  activeTaskIds(): Promise<string[]>
  /** `systemctl is-active clawock-patrol` ('' when systemctl is unavailable). */
  patrolService(): Promise<string>
  /** The supervisor's most recent journal lines, oldest first, timestamps kept. */
  patrolLog(): Promise<string[]>
  /** Run the ops entry: `python3 <opsPath> --json …`. Optional: tests without it get no queue order. */
  runOps?(opsPath: string, args: string[], timeoutMs: number): Promise<OpsRun>
}

/** One run of the ops entry. `code` is its exit status (-1: it did not run or timed out). */
export interface OpsRun { code: number; stdout: string; stderr: string }

function runOpsProcess(opsPath: string, args: string[], timeoutMs: number): Promise<OpsRun> {
  return new Promise((resolve) => {
    execFile('python3', [opsPath, '--json', ...args], { timeout: timeoutMs, maxBuffer: 4 << 20 }, (error, stdout, stderr) => {
      const code = error === null ? 0 : typeof (error as { code?: unknown }).code === 'number' ? (error as { code: number }).code : -1
      resolve({ code, stdout: String(stdout ?? ''), stderr: String(stderr ?? '') })
    })
  })
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
  runOps: runOpsProcess,
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

/** The end of a task's run.log (a cut first line dropped); '' when there is none. */
function logTail(dir: string): string {
  let fd: number
  try { fd = openSync(join(dir, 'run.log'), 'r') } catch { return '' }
  try {
    const size = fstatSync(fd).size
    const start = Math.max(0, size - LOG_TAIL_BYTES)
    const buffer = Buffer.alloc(size - start)
    readSync(fd, buffer, 0, buffer.length, start)
    const text = buffer.toString('utf8')
    return start === 0 ? text : text.slice(text.indexOf('\n') + 1)
  } catch { return '' } finally { closeSync(fd) }
}

/** When a quota/retry wait ends: the last `sleeping until` line of the run log. */
function wakeAt(log: string): number | null {
  const matches = [...log.matchAll(/sleeping until (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/g)]
  const last = matches[matches.length - 1]
  return last === undefined ? null : localStampMs(last[1])
}

/**
 * The agent's closing words: the last run of `final | ` lines the runner
 * echoes after an attempt (its final report's tail, already redacted), minus
 * blank lines and the STATUS line the outcome field carries anyway.
 */
export function finalSummary(log: string): string {
  const lines = log.split('\n')
  const isFinal = (line: string): boolean => /^final \|( |$)/.test(line)
  let end = lines.length - 1
  while (end >= 0 && !isFinal(lines[end]!)) end -= 1
  if (end < 0) return ''
  let start = end
  while (start > 0 && isFinal(lines[start - 1]!)) start -= 1
  return lines.slice(start, end + 1)
    .map((line) => line.replace(/^final \| ?/, '').trimEnd())
    .filter((line) => line.trim() !== '' && !/^STATUS:\s/.test(line.trim()))
    .join('\n')
    .slice(0, SUMMARY_MAX_CHARS)
}

/** The runner's latest stamped event (`<ts> got run slot 1`, `---- <ts> attempt 2/3 …`). */
export function lastLogEvent(log: string): { text: string; atMs: number | null } {
  const lines = log.split('\n')
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const match = /^(?:---- )?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.+)$/.exec(lines[i]!)
    if (match) return { text: match[2]!.trim(), atMs: localStampMs(match[1]) }
  }
  return { text: '', atMs: null }
}

/** `weixin,telegram` → ['weixin', 'telegram']; 'none' and blanks dropped, each once. */
export function channelList(raw: string | undefined): string[] {
  return [...new Set((raw ?? '').split(',').map((part) => part.trim().toLowerCase()).filter((part) => part !== '' && part !== 'none'))]
}

const epochMs = (raw: string | undefined): number | null => {
  const value = Number.parseInt(raw ?? '', 10)
  return Number.isFinite(value) && value > 0 ? value * 1000 : null
}

function readTask(logDir: string, id: string, alive: boolean): DispatchTask {
  const dir = join(logDir, id)
  const meta = readEnvFile(join(dir, 'meta.env'))
  const result = readEnvFile(join(dir, 'result.env'))
  const override = readEnvFile(join(dir, 'override.env'))
  const waiting = alive ? (result.WAITING ?? '') : ''
  const log = logTail(dir)
  // A live task shows where it is now; an ended one shows how it closed.
  const event = alive ? lastLogEvent(log) : { text: '', atMs: null }
  let cancelling = false
  if (alive) {
    try { cancelling = Date.now() - statSync(join(dir, 'cancel-requested')).mtimeMs < 60000 } catch { /* none */ }
  }
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
    stalls: Number.parseInt(result.STALLS ?? '0', 10) || 0,
    outcome: result.OUTCOME ?? '',
    startedAtMs: localStampMs(result.STARTED ?? meta.CREATED),
    updatedAtMs: localStampMs(result.UPDATED),
    wakeAtMs: alive && (waiting === 'quota' || waiting === 'retry') ? epochMs(result.WAKE_AT) ?? wakeAt(log) : null,
    patrol: id.startsWith('patrol-'),
    summary: alive ? '' : finalSummary(log),
    lastEvent: event.text,
    lastEventAtMs: event.atMs,
    queuedAtMs: epochMs(result.QUEUED_AT),
    position: null,
    priority: Number.parseInt(override.PRIORITY ?? '0', 10) || 0,
    protected: false,
    modelRequested: override.MODEL || meta.MODEL || '',
    modelUsed: result.MODEL_USED ?? '',
    effortRequested: override.EFFORT || meta.EFFORT || '',
    effortUsed: result.EFFORT_USED ?? '',
    notify: channelList(meta.NOTIFY),
    notified: channelList(result.NOTIFIED),
    notifyFailed: channelList(result.NOTIFY_FAILED),
    notifyAtMs: localStampMs(result.NOTIFY_AT),
    runnerApi: Number.parseInt(result.RUNNER_API ?? '1', 10) || 1,
    legacy: (Number.parseInt(result.RUNNER_API ?? '1', 10) || 1) < 2,
    session: result.SESSION ?? '',
    cancelling,
  }
}

function readLimits(path: string): { maxRunning: number; slotLimits: AgentSlotLimit[] } {
  const env = readEnvFile(path)
  const count = (raw: string | undefined): number => {
    const value = Number.parseInt(raw ?? '', 10)
    return Number.isFinite(value) && value > 0 ? value : 0
  }
  const slotLimits = Object.keys(env).filter((key) => /^MAX_RUNNING_[A-Z0-9]+$/.test(key))
    .map((key) => ({ agent: key.slice('MAX_RUNNING_'.length).toLowerCase(), max: count(env[key]) }))
  return { maxRunning: count(env.MAX_RUNNING), slotLimits }
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

/** sha256 of a file, 12 hex — the same hash the ops entry reports as its ops_version. */
export function fileVersion(path: string): string {
  if (path === '') return ''
  try { return createHash('sha256').update(readFileSync(path)).digest('hex').slice(0, 12) } catch { return '' }
}

type OpsList = {
  ops_version?: string; api?: number; fair_wait_sec?: number; runner?: { api?: number | null }
  agents?: Record<string, {
    holder?: { held?: boolean; id?: string | null; legacy?: boolean; note?: string }
    queue?: Array<{ id: string; position: number; priority: number; protected: boolean; legacy?: boolean; queued_at?: number }>
    quota?: { until: number; by: string } | null
  }>
}

/** The ops entry's `list`, or why it could not be read. */
async function readOps(config: Required<TaskQueueConfig>, deps: TaskQueueDeps): Promise<{ ops: OpsStatus; list: OpsList | null }> {
  const base: OpsStatus = {
    available: false, version: '', repoVersion: fileVersion(config.repoOpsPath), api: 0, runnerApi: 0, fairWaitSec: 0, error: '',
  }
  if (deps.runOps === undefined) return { ops: { ...base, error: 'no ops runner' }, list: null }
  if (!existsSync(config.opsPath)) return { ops: { ...base, error: `ops entry not installed at ${config.opsPath}` }, list: null }
  const r = await deps.runOps(config.opsPath, ['list'], COMMAND_TIMEOUT_MS)
  let list: OpsList | null = null
  try { list = JSON.parse(r.stdout) as OpsList } catch { list = null }
  if (r.code !== 0 || list === null) {
    return { ops: { ...base, error: (r.stderr || r.stdout).trim().slice(-300) || `ops list exited ${r.code}` }, list: null }
  }
  return {
    ops: {
      ...base, available: true, version: list.ops_version ?? '', api: list.api ?? 0,
      runnerApi: list.runner?.api ?? 0, fairWaitSec: list.fair_wait_sec ?? 0,
    },
    list,
  }
}

export async function readTaskQueue(config: Required<TaskQueueConfig>, deps: TaskQueueDeps): Promise<QueueRead> {
  const asOf = new Date().toISOString()
  const empty: PatrolStatus = { service: 'unknown', phase: 'unknown', round: '', detail: '', untilMs: null, rounds: [] }
  if (!existsSync(config.logDir)) {
    return { available: false, asOf, maxRunning: 0, slotLimits: [], running: 0, active: [], recent: [], patrol: empty }
  }
  const [activeIds, service, log, opsRead] = await Promise.all([
    deps.activeTaskIds(), deps.patrolService(), deps.patrolLog(), readOps(config, deps),
  ])
  const alive = new Set(activeIds.filter((id) => existsSync(join(config.logDir, id))))
  // QUEUED_AT is the order tasks started waiting in (directory mtime is not: a task that was
  // written to later sorted after one that queued later, 2026-09-26); runners from before it
  // fall back to their start stamp.
  const since = (task: DispatchTask): number => task.queuedAtMs ?? task.startedAtMs ?? Number.MAX_SAFE_INTEGER
  const active = [...alive].map((id) => readTask(config.logDir, id, true)).sort((a, b) => since(a) - since(b))
  const queues: AgentQueue[] = []
  for (const [agent, group] of Object.entries(opsRead.list?.agents ?? {})) {
    const order = (group.queue ?? []).map((row) => row.id)
    for (const row of group.queue ?? []) {
      const task = active.find((candidate) => candidate.id === row.id)
      if (task !== undefined) {
        Object.assign(task, { position: row.position, protected: row.protected, priority: row.priority, legacy: row.legacy === true })
        // An older runner writes no QUEUED_AT; the ops entry dates its wait from run.log.
        if (task.queuedAtMs == null && typeof row.queued_at === 'number') task.queuedAtMs = row.queued_at * 1000
      }
    }
    queues.push({
      agent, held: group.holder?.held === true, holder: group.holder?.id ?? '', order,
      holderLegacy: group.holder?.legacy === true, holderNote: group.holder?.note ?? '',
      quotaUntilMs: group.quota ? group.quota.until * 1000 : null, quotaBy: group.quota?.by ?? '',
    })
  }
  active.sort((a, b) => since(a) - since(b))
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
    ...readLimits(config.limitsPath),
    running: active.filter((task) => task.slot !== '').length,
    active,
    recent: ended,
    patrol: { ...patrolPhase(service, round, alive.has(round), log), rounds: readRounds(config.patrolDir, 3) },
    queues,
    ops: opsRead.ops,
  }
}

export type TaskQueueService = {
  get(force: boolean): Promise<TaskQueueResult>
  /** Forget the cached read: the next get() reads the files again (after a write). */
  invalidate(): void
}

/** TTL cache + in-flight join + stale-on-failure, the balance services' cadence shell in miniature. */
export function createTaskQueueService(config: TaskQueueConfig = {}, deps: TaskQueueDeps = systemDeps): TaskQueueService {
  const resolved: Required<TaskQueueConfig> = {
    logDir: expandHome(config.logDir ?? DEFAULT_DISPATCH_LOG_DIR),
    limitsPath: expandHome(config.limitsPath ?? DEFAULT_DISPATCH_LIMITS_PATH),
    patrolDir: expandHome(config.patrolDir ?? DEFAULT_PATROL_STATE_DIR),
    refreshMs: config.refreshMs ?? DEFAULT_TASK_QUEUE_REFRESH_MS,
    recent: config.recent ?? DEFAULT_TASK_QUEUE_RECENT,
    opsPath: expandHome(config.opsPath ?? DEFAULT_TASK_QUEUE_OPS_PATH),
    repoOpsPath: config.repoOpsPath ?? '',
  }
  let last: QueueRead | null = null
  let fetchedAt = 0
  // The last read's failure, cleared only by a successful one: `fetchedAt`
  // dates the last SUCCESS, so a poll inside the TTL after a failed forced
  // refresh would otherwise answer 'cached' (the balance services' #1546).
  let lastError: string | null = null
  let inFlight: Promise<TaskQueueResult> | null = null
  const answer = (status: TaskQueueResult['status'], message: string | null): TaskQueueResult => ({
    available: false, asOf: '', maxRunning: 0, slotLimits: [], running: 0, active: [], recent: [],
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
      lastError = null
      return answer('fresh', null)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      if (last !== null) lastError = message
      return answer(last !== null ? 'stale' : 'failed', message)
    }
  }
  return {
    invalidate(): void { fetchedAt = 0 },
    async get(force: boolean): Promise<TaskQueueResult> {
      if (!force && last !== null && Date.now() - fetchedAt < TTL_MS) {
        return lastError !== null ? answer('stale', lastError) : answer('cached', null)
      }
      if (inFlight !== null) return inFlight
      inFlight = exec()
      try { return await inFlight } finally { inFlight = null }
    },
  }
}


// ---------------------------------------------------------------------------
// Writes: one door, the versioned ops entry.
// ---------------------------------------------------------------------------

/** The actions the chip may run, and how each maps onto the ops entry's arguments. */
export const QUEUE_ACTIONS = ['cancel', 'priority', 'model', 'choices', 'retry', 'wrapup', 'log'] as const
export type QueueAction = typeof QUEUE_ACTIONS[number]

const TASK_ID = /^[a-z0-9][a-z0-9-]{0,80}$/
const PRIORITY_ARG = /^(top|up|down|reset|-?\d{1,2})$/
const MODEL_TOKEN = /^[A-Za-z0-9._/:@-]{1,120}$/
/** Queued, not interrupting: the task finishes its current step, then lands what it has. */
export const WRAPUP_TEXT = '请体面收尾：不要再开新的工作。把已经完成的部分提交/推送（按原任务的流程），' +
  '写清楚做了什么、没做什么和下一步，然后输出 STATUS 行（没做完就是 STATUS: PARTIAL）。'

/** The ops arguments for one chip action, or why the input is refused before anything runs. */
export function opsArgsFor(action: string, id: string, arg: string): string[] | string {
  if (!(QUEUE_ACTIONS as readonly string[]).includes(action)) return `unknown action ${JSON.stringify(action)}`
  if (!TASK_ID.test(id)) return `not a task id: ${JSON.stringify(id)}`
  switch (action as QueueAction) {
    case 'priority':
      return PRIORITY_ARG.test(arg) ? ['priority', id, arg] : `priority takes top, up, down, reset or an integer (got ${JSON.stringify(arg)})`
    case 'model': {
      const [model = '', effort = 'keep'] = arg.split('|')
      if (!MODEL_TOKEN.test(model) || !MODEL_TOKEN.test(effort)) return `model takes "<model|keep|default>|<effort|keep|default>" (got ${JSON.stringify(arg)})`
      return ['model', id, model, effort]
    }
    case 'wrapup': return ['append', id, '--queue', '--text', WRAPUP_TEXT]
    case 'log': return ['log', id, '--lines', '80']
    default: return [action, id]
  }
}

const ACTION_TIMEOUT_MS = 30000
/** A second identical write inside this window returns the first one's answer (a double click). */
const REPEAT_WINDOW_MS = 2000

export type QueueActionRunner = (action: string, id: string, arg: string) => Promise<QueueActionResult>

/**
 * The chip's write path: validate, then run the ops entry with --source ui.
 * Identical calls in flight share one run, and a repeat within 2 s gets the
 * same answer, so a double click can never cancel or reorder twice (the ops
 * entry also serialises writes per task and treats a repeat cancel as a no-op).
 * Never throws: every failure is an in-band `{ ok: false, code, message }`.
 */
export function createQueueActionRunner(config: TaskQueueConfig = {}, deps: Pick<TaskQueueDeps, 'runOps'> = systemDeps,
  onWrite: () => void = () => {}): QueueActionRunner {
  const opsPath = expandHome(config.opsPath ?? DEFAULT_TASK_QUEUE_OPS_PATH)
  const inFlight = new Map<string, Promise<QueueActionResult>>()
  const recent = new Map<string, { at: number; result: QueueActionResult }>()
  const exec = async (action: string, id: string, args: string[]): Promise<QueueActionResult> => {
    const fail = (code: number, message: string): QueueActionResult => ({ ok: false, code, action, id, message, detail: '' })
    if (deps.runOps === undefined) return fail(-1, 'no ops runner')
    if (!existsSync(opsPath)) return fail(-1, `ops entry not installed at ${opsPath} (ops/host/install_task_queue_ops.sh)`)
    const r = await deps.runOps(opsPath, ['--source', 'ui', ...args], ACTION_TIMEOUT_MS)
    type Answer = { ok?: boolean; error?: string; message?: string }
    const answer = ((): Answer | null => { try { return JSON.parse(r.stdout) as Answer } catch { return null } })()
    if (answer === null) return fail(r.code === 0 ? -1 : r.code, (r.stderr || r.stdout).trim().slice(-300) || `ops entry exited ${r.code}`)
    const ok = r.code === 0 && answer.ok === true
    return { ok, code: r.code, action, id, message: (ok ? answer.message : answer.error ?? answer.message) ?? '', detail: r.stdout.trim() }
  }
  return async (action, id, arg) => {
    const args = opsArgsFor(action, id, arg)
    if (typeof args === 'string') return { ok: false, code: 2, action, id, message: args, detail: '' }
    const key = [action, id, arg].join('\u0000')
    const read = action === 'choices' || action === 'log'
    const last = recent.get(key)
    if (!read && last !== undefined && Date.now() - last.at < REPEAT_WINDOW_MS) return last.result
    const pending = inFlight.get(key)
    if (pending !== undefined) return pending
    const job = exec(action, id, args).then((result) => {
      if (!read) { recent.set(key, { at: Date.now(), result }); onWrite() }
      return result
    }).finally(() => { inFlight.delete(key) })
    inFlight.set(key, job)
    return job
  }
}
