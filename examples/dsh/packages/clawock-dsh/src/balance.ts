/**
 * Provider account balances for the session header chip — official endpoints
 * answered with the SAME keys the harness's adapters use (credentials seam
 * references, falling back to ambient environment variables):
 *
 *   - deepseek: `GET https://api.deepseek.com/user/balance` (money, CNY row)
 *   - minimax:  `GET {base}/v1/token_plan/remains` (Token Plan quota windows;
 *     `base_resp.status_code` is the business verdict — 0 ok, 1004 auth —
 *     and a HTTP-200 body can still be an auth failure)
 *   - claude:   `GET /api/oauth/usage` (subscription windows)
 *   - codex:    official `codex app-server` JSON-RPC
 *     `account/rateLimits/read` (ChatGPT subscription quota windows)
 *
 * Every quota provider is reduced to the same shape before it leaves this
 * file: a list of windows built by `quotaWindow` (label derived from the
 * window's length, one reset-stamp format) and a snapshot built by
 * `quotaSnapshot` (one note wording, one availability rule, one low rule).
 * The parsers below only translate each vendor's field names — they used to
 * each spell labels, notes and reset clocks their own way, which is how the
 * same 5-hour window read '5h' on one row and '会话' on the next.
 *
 * One cache per provider, one source of truth: the gateway instance owns
 * them, so a stale read, a failed refresh and a rotated key all resolve
 * against the same object. Upstream is hit at most once per TTL window
 * unless the client forces a refresh; a failed refresh keeps the last good
 * snapshot and reports 'stale' instead of dropping a real number for a
 * transient 429. Keys are never logged, shipped, or stored anywhere here.
 *
 * All error reporting is in-band: `get()` never throws — statuses
 * 'no-key' / 'failed' / 'stale' carry a Chinese `message` the view renders
 * verbatim.
 */

import { delimiter, join } from 'node:path'
import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { spawn } from 'node:child_process'
import type { BalanceResult, BalanceSnapshot, BalanceWindow } from './types.ts'

export const DEFAULT_BALANCE_BASE_URL = 'https://api.deepseek.com'
export const DEFAULT_BALANCE_THRESHOLD = 20
export const DEFAULT_BALANCE_REFRESH_MS = 60000
export const DEFAULT_MINIMAX_BASE_URL = 'https://api.minimaxi.com'
export const DEFAULT_MINIMAX_LOW_PCT = 20
/**
 * The three file-backed defaults hang off the ACTIVE user's home, never a
 * literal `/root/...`. This package is published to npm, so an absolute home
 * directory would ship one machine's layout as everyone's default (and would
 * read the wrong account under another uid). Each path stays overridable from
 * the profile row (see cordis.patch.yml); on this root-owned host they resolve
 * to exactly the previous literals.
 */
export const DEFAULT_OPENCLAW_CONFIG_PATH = join(homedir(), '.openclaw', 'openclaw.json')
export const DEFAULT_CLAUDE_CREDENTIALS_PATH = join(homedir(), '.claude', '.credentials.json')
export const DEFAULT_CLAUDE_USAGE_URL = 'https://api.anthropic.com/api/oauth/usage'
export const DEFAULT_CLAUDE_LOW_PCT = 20
export const DEFAULT_CODEX_COMMAND = join(homedir(), '.local', 'bin', 'codex')
export const DEFAULT_CODEX_LOW_PCT = 20
export const DEFAULT_CODEX_REFRESH_MS = 300000
const TTL_MS = 60000
const TIMEOUT_MS = 15000
const WEEK_MINS = 7 * 24 * 60

/**
 * Expand one leading `~` in a configured path. The defaults above are already
 * home-relative, and the profile row is hand-written YAML, so `~/.claude/...`
 * is the form a user naturally writes for an override — without this it would
 * be taken literally and read as a file named `~`. Only a leading `~` followed
 * by `/` or the end of the string expands; a `~` inside a path is a real name
 * and is left alone. Exported because the behaviour is worth pinning in tests.
 */
export function expandHome(value: string): string {
  if (value !== '~' && !value.startsWith('~/')) return value
  return value === '~' ? homedir() : join(homedir(), value.slice(2))
}

/** The credentials capability, narrowed to what these services use. */
export interface BalanceCredentials {
  resolve(ref: string): Promise<{ value: string } | undefined>
}

export interface BalanceConfig {
  /** DeepSeek upstream base; the service appends /user/balance. */
  baseUrl?: string
  /** Red-dot threshold in the displayed entry's currency (CNY/USD units). */
  threshold?: number
  /** Suggested client poll interval in ms. */
  refreshMs?: number
}

export interface MinimaxConfig {
  /** Upstream base; the service appends /v1/token_plan/remains. */
  baseUrl?: string
  /** Credentials seam reference for the MiniMax key (env fallback same name). */
  keyRef?: string
  /**
   * Red dot watermark in REMAINING terms: warn when a quota window's
   * remaining percent has fallen to/below this (default 20). The chip
   * displays the used direction (≥ `100 - lowPct`% used), but the config
   * keeps its original meaning so existing values stay valid.
   */
  lowPct?: number
  /**
   * openclaw gateway config to fall back to when the seam and env are both
   * unset — kcn keeps provider keys at models.providers.<name>.apiKey there.
   */
  openclawConfigPath?: string
}

export interface ClaudeConfig {
  /** Claude Code's OAuth credentials file (claudeAiOauth.accessToken). */
  credentialsPath?: string
  /** The undocumented /api/oauth/usage endpoint; overridable for tests. */
  usageUrl?: string
  /** Red dot watermark in REMAINING terms (default 20, i.e. ≥80% used). */
  lowPct?: number
}

export interface CodexConfig {
  /** Codex CLI executable that owns ChatGPT auth and the app-server protocol. */
  command?: string
  /** Red dot watermark in remaining terms (default 20 = ≥80% used). */
  lowPct?: number
  /** Codex app-server polling cadence; slower than HTTP-only providers by default. */
  refreshMs?: number
}

/**
 * The credentials seam reference the official DeepSeek adapter resolves.
 * A plain string on purpose, not credentialRef(): the branding helper is a
 * no-op at runtime, and importing @deepseek-ai/dsh-credentials would drag its
 * cordis Events augmentation into the typert analysis — which registers this
 * package in the host face with zero discoverable services (the protocol
 * lives in node_modules, where the generator's symbol checks cannot see it)
 * and fails the "publishes Remote artifacts" gate. The seam itself resolves
 * by name, so the reference needs no import to work.
 */
export const DEEPSEEK_KEY_REF = 'DEEPSEEK_API_KEY'

/** Same seam discipline for MiniMax: the harness's MiniMax adapter's ref. */
export const MINIMAX_KEY_REF = 'MINIMAX_API_KEY'

/** One balance_infos entry, as far as this service reads it. */
export interface BalanceInfoEntry {
  currency?: string
  total_balance?: string
  granted_balance?: string
  topped_up_balance?: string
}

/**
 * Pick the CNY entry case-insensitively; fall back to the first entry when
 * the account has no CNY row. Mirrors upstream DeepSeekMonitorWindows'
 * eq_ignore_ascii_case.
 */
export function pickCnyBalanceInfo(
  infos: readonly BalanceInfoEntry[] | undefined,
): BalanceInfoEntry | undefined {
  if (!Array.isArray(infos) || infos.length === 0) return undefined
  return infos.find((entry) => (entry.currency ?? '').toUpperCase() === 'CNY') ?? infos[0]
}

/** The upstream payload, as far as this service reads it. */
interface RawBalanceBody {
  is_available?: boolean
  balance_infos?: BalanceInfoEntry[]
}

/**
 * Tolerant parse: a missing field degrades to '' / false rather than throwing,
 * so a shape drift upstream reads as an empty box, never as a crashed tab.
 */
export function parseBalancePayload(body: unknown, asOf: string): BalanceSnapshot {
  const raw = (typeof body === 'object' && body !== null ? body : {}) as RawBalanceBody
  const entry = pickCnyBalanceInfo(raw.balance_infos)
  return {
    isAvailable: raw.is_available === true,
    unit: 'money',
    currency: typeof entry?.currency === 'string' ? entry.currency : '',
    totalBalance: typeof entry?.total_balance === 'string' ? entry.total_balance : '',
    grantedBalance: typeof entry?.granted_balance === 'string' ? entry.granted_balance : '',
    toppedUpBalance: typeof entry?.topped_up_balance === 'string' ? entry.topped_up_balance : '',
    asOf,
    note: '',
    windows: [],
  }
}

const finiteNumber = (value: unknown): number | null =>
  typeof value === 'number' && isFinite(value) ? value : null

const clampPercent = (value: number): number => Math.round(Math.min(100, Math.max(0, value)))

// ---------------------------------------------------------------------------
// The one quota-window vocabulary every provider below is translated into.
// ---------------------------------------------------------------------------

/** Epoch seconds, epoch milliseconds or an RFC3339 string → epoch ms; null when unreadable. */
export function toEpochMs(value: number | string | null | undefined): number | null {
  if (typeof value === 'number' && isFinite(value) && value > 0) {
    return value > 1e12 ? value : value * 1000
  }
  if (typeof value === 'string' && value !== '') {
    const at = new Date(value).getTime()
    return isNaN(at) ? null : at
  }
  return null
}

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const dayIndex = (at: Date): number => Math.floor(
  Date.UTC(at.getFullYear(), at.getMonth(), at.getDate()) / 86_400_000,
)

/**
 * The single reset-stamp format, same for every provider and every window:
 * '今天 21:00' / '明天 09:00' when it lands within the next calendar day,
 * otherwise the full date '9/20 周日 20:00'. A weekly reset used to read just
 * '周日 20:00' — with no date, a week-long window's reset could be this
 * Sunday or the next, and it said nothing about which.
 */
export function formatReset(value: number | string | null | undefined, now: number = Date.now()): string {
  const ms = toEpochMs(value)
  if (ms === null) return ''
  const at = new Date(ms)
  const hhmm = String(at.getHours()).padStart(2, '0') + ':' + String(at.getMinutes()).padStart(2, '0')
  const days = dayIndex(at) - dayIndex(new Date(now))
  if (days === 0) return '今天 ' + hhmm
  if (days === 1) return '明天 ' + hhmm
  return `${at.getMonth() + 1}/${at.getDate()} ${WEEKDAYS[at.getDay()]} ${hhmm}`
}

/** A window's label from its length: 300 → '5h', 10080 → '周', 1440 → '1天'. */
export function windowLabel(durationMins: number | null, fallback: string): string {
  if (durationMins === null || durationMins <= 0) return fallback
  if (durationMins === WEEK_MINS) return '周'
  if (durationMins % 1440 === 0) return `${durationMins / 1440}天`
  if (durationMins % 60 === 0) return `${durationMins / 60}h`
  return `${Math.round(durationMins)}m`
}

/** What a provider parser knows about one window, in its own units. */
export interface QuotaWindowInput {
  /** Used percent (0-100); null when the plan does not report it this cycle. */
  usedPercent: number | null
  /** Window length in minutes, when the vendor says (or it can be derived). */
  durationMins: number | null
  /** When the window frees up: epoch s/ms or RFC3339. */
  resetsAt: number | string | null | undefined
  /** Label to use when the length is unknown ('5h' / '周'). */
  fallbackLabel: string
}

/** One vendor window → the wire window, or null when it carries no reading. */
export function quotaWindow(input: QuotaWindowInput, now: number = Date.now()): BalanceWindow | null {
  if (input.usedPercent === null) return null
  const durationMins = input.durationMins === null || input.durationMins <= 0 ? null : input.durationMins
  const resetAt = formatReset(input.resetsAt, now)
  return {
    label: windowLabel(input.durationMins, input.fallbackLabel),
    percent: clampPercent(input.usedPercent),
    resetAt,
    // The two structured fields behind `label` / `resetAt` (see BalanceWindow):
    // the client re-renders both in the active locale from these and only falls
    // back to the strings above when they are null.
    durationMins,
    resetAtMs: resetAt === '' ? null : toEpochMs(input.resetsAt),
  }
}

/**
 * Readable windows → the quota snapshot. The headline is the first window;
 * the note reads every window the same way ('5h 已用 12%,今天 21:00 重置');
 * a quota account is available only while no window is exhausted, unless the
 * vendor states availability itself (`isAvailable`).
 */
export function quotaSnapshot(
  windows: readonly (BalanceWindow | null)[],
  asOf: string,
  options: { isAvailable?: boolean; extraNotes?: readonly string[] } = {},
): BalanceSnapshot {
  const readable = windows.filter((window): window is BalanceWindow => window !== null)
  const notes = readable.map((window) => `${window.label} 已用 ${window.percent}%`
    + (window.resetAt !== '' ? `,${window.resetAt} 重置` : ''))
  notes.push(...(options.extraNotes ?? []))
  const headline = readable[0]?.percent
  return {
    isAvailable: options.isAvailable ?? (readable.length > 0 && readable.every((window) => (window.percent ?? 0) < 100)),
    unit: 'pct',
    currency: '',
    totalBalance: headline === null || headline === undefined ? '' : String(headline),
    grantedBalance: '',
    toppedUpBalance: '',
    asOf,
    note: notes.join(' · '),
    windows: readable,
  }
}

/**
 * The shared low rule for quota rows. `lowPct` keeps its original 「剩余水位」
 * meaning (warn when remaining ≤ lowPct), which in the used direction is any
 * window at ≥ 100 − lowPct — the weekly window counts as much as the short
 * one, because an exhausted week blocks work just as surely.
 */
export function quotaIsLow(snapshot: BalanceSnapshot, lowPct: number): boolean {
  if (snapshot.unit !== 'pct') return false
  if (!snapshot.isAvailable) return true
  return snapshot.windows.some((window) => window.percent !== null && window.percent >= 100 - lowPct)
}

// ---------------------------------------------------------------------------
// MiniMax
// ---------------------------------------------------------------------------

/** One model_remains bucket, as far as this service reads it. */
export interface MinimaxRemainsEntry {
  /** Bucket name. The live API calls it `model_name`; older payloads `model`. */
  model_name?: string
  model?: string
  start_time?: number
  end_time?: number
  current_interval_remaining_percent?: number
  current_interval_total_count?: number
  current_interval_usage_count?: number
  weekly_start_time?: number
  weekly_end_time?: number
  current_weekly_remaining_percent?: number
  current_weekly_total_count?: number
  current_weekly_usage_count?: number
  [key: string]: unknown
}

interface RawRemainsBody {
  base_resp?: { status_code?: number; status_msg?: string }
  model_remains?: MinimaxRemainsEntry[]
}

/**
 * Used percent from MiniMax's two shapes: an explicit REMAINING percent
 * (complemented here) or raw counts (already consumption). null =
 * unreadable, never guessed.
 */
function minimaxUsed(remaining: unknown, total: unknown, usage: unknown): number | null {
  const direct = finiteNumber(remaining)
  if (direct !== null) return Math.min(100, Math.max(0, 100 - direct))
  const t = finiteNumber(total)
  const u = finiteNumber(usage)
  if (t !== null && t > 0 && u !== null && u >= 0) return Math.min(100, Math.max(0, (u / t) * 100))
  return null
}

/** The interval window's used percent (kept exported: the tests pin both shapes). */
export function windowUsedPercent(entry: MinimaxRemainsEntry): number | null {
  return minimaxUsed(entry.current_interval_remaining_percent,
    entry.current_interval_total_count, entry.current_interval_usage_count)
}

const spanMins = (start: unknown, end: unknown): number | null => {
  const a = toEpochMs(finiteNumber(start))
  const b = toEpochMs(finiteNumber(end))
  return a !== null && b !== null && b > a ? Math.round((b - a) / 60000) : null
}

/**
 * The successful Token Plan payload → snapshot. Percent-based by design:
 * tokens are not money — the chip reads "窗口额度用了多少", never a ¥ figure.
 */
export function parseMinimaxRemains(body: unknown, asOf: string, now: number = Date.now()): BalanceSnapshot {
  const raw = (typeof body === 'object' && body !== null ? body : {}) as RawRemainsBody
  const buckets = Array.isArray(raw.model_remains) ? raw.model_remains : []
  // `general` is the text/coding bucket every plan carries; video et al are add-ons.
  const entry = buckets.find((b) => (b.model_name ?? b.model) === 'general') ?? buckets[0]
  if (entry === undefined) throw new Error('MiniMax 响应里没有 model_remains 数据')
  return quotaSnapshot([
    quotaWindow({
      usedPercent: windowUsedPercent(entry),
      durationMins: spanMins(entry.start_time, entry.end_time),
      resetsAt: entry.end_time,
      fallbackLabel: '5h',
    }, now),
    quotaWindow({
      usedPercent: minimaxUsed(entry.current_weekly_remaining_percent,
        entry.current_weekly_total_count, entry.current_weekly_usage_count),
      durationMins: spanMins(entry.weekly_start_time, entry.weekly_end_time) ?? WEEK_MINS,
      resetsAt: entry.weekly_end_time,
      fallbackLabel: '周',
    }, now),
  ], asOf)
}

// ---------------------------------------------------------------------------
// Claude
// ---------------------------------------------------------------------------

/** One usage window: utilization is the % already consumed (0-100). */
export interface ClaudeUsageWindow {
  utilization?: number
  resets_at?: string | null
}

interface RawClaudeUsage {
  five_hour?: ClaudeUsageWindow | null
  seven_day?: ClaudeUsageWindow | null
  extra_usage?: { is_enabled?: boolean; utilization?: number | null } | null
  [key: string]: unknown
}

/**
 * Successful usage payload → snapshot. utilization already IS consumption,
 * so it passes through untouched; any bucket may be absent/null by plan.
 */
export function parseClaudeUsage(body: unknown, asOf: string, now: number = Date.now()): BalanceSnapshot {
  const raw = (typeof body === 'object' && body !== null ? body : {}) as RawClaudeUsage
  const u5 = finiteNumber(raw.five_hour?.utilization)
  const u7 = finiteNumber(raw.seven_day?.utilization)
  if (u5 === null && u7 === null) throw new Error('Claude 响应里没有可用的用量窗口')
  const extraUtil = raw.extra_usage?.is_enabled === true ? finiteNumber(raw.extra_usage?.utilization ?? undefined) : null
  return quotaSnapshot([
    quotaWindow({ usedPercent: u5, durationMins: 300, resetsAt: raw.five_hour?.resets_at, fallbackLabel: '5h' }, now),
    quotaWindow({ usedPercent: u7, durationMins: WEEK_MINS, resetsAt: raw.seven_day?.resets_at, fallbackLabel: '周' }, now),
  ], asOf, { extraNotes: extraUtil === null ? [] : ['附加额度已用 ' + Math.round(extraUtil) + '%'] })
}

// ---------------------------------------------------------------------------
// Codex
// ---------------------------------------------------------------------------

/** One Codex app-server quota window (`account/rateLimits/read`). */
export interface CodexRateLimitWindow {
  usedPercent?: number
  windowDurationMins?: number | null
  resetsAt?: number | null
}

interface CodexRateLimitBucket {
  primary?: CodexRateLimitWindow | null
  secondary?: CodexRateLimitWindow | null
  rateLimitReachedType?: string | null
}

interface RawCodexRateLimits {
  ordinaryUsageAllowed?: boolean | null
  rateLimits?: CodexRateLimitBucket
  rateLimitsByLimitId?: Record<string, CodexRateLimitBucket> | null
}

/** Official app-server response → the chip's used-percent snapshot. */
export function parseCodexRateLimits(body: unknown, asOf: string, now: number = Date.now()): BalanceSnapshot {
  const raw = (typeof body === 'object' && body !== null ? body : {}) as RawCodexRateLimits
  const buckets = raw.rateLimitsByLimitId
  const bucket = buckets !== null && typeof buckets === 'object' && buckets.codex !== undefined
    ? buckets.codex
    : raw.rateLimits
  if (bucket === undefined || bucket === null) throw new Error('Codex 响应里没有额度数据')
  const toInput = (window: CodexRateLimitWindow | null | undefined, fallbackLabel: string): QuotaWindowInput => ({
    usedPercent: finiteNumber(window?.usedPercent),
    durationMins: finiteNumber(window?.windowDurationMins),
    resetsAt: window?.resetsAt,
    fallbackLabel,
  })
  const windows = [quotaWindow(toInput(bucket.primary, '5h'), now), quotaWindow(toInput(bucket.secondary, '周'), now)]
  if (windows.every((window) => window === null)) throw new Error('Codex 响应里没有可用的额度窗口')
  const limited = raw.ordinaryUsageAllowed === false || typeof bucket.rateLimitReachedType === 'string'
  // The backend-owned permission is authoritative. An absent value means
  // unavailable, never an inferred recovery from reset clocks/percentages.
  return quotaSnapshot(windows, asOf, {
    isAvailable: raw.ordinaryUsageAllowed === true,
    extraNotes: limited ? ['当前额度受限'] : [],
  })
}

// ---------------------------------------------------------------------------
// The shared cadence shell and the four services.
// ---------------------------------------------------------------------------

/**
 * TTL cache, in-flight join, stale-on-failure — parameterized by provider.
 * The services below differ only in key resolution, endpoint, parse and
 * low-reading; everything temporal is here once.
 */
interface QuotaServiceSpec {
  /**
   * Where this provider's secret comes from. Returning undefined means
   * "not configured" → the in-band no-key row; the message is spec-level.
   */
  resolveApiKey(deps: { credentials: BalanceCredentials }): Promise<string | undefined>
  noKeyMessage: string
  threshold: number
  refreshMs: number
  /** Host-side cache lifetime; defaults to the historical one-minute cadence. */
  ttlMs?: number
  fetchFresh(apiKey: string): Promise<BalanceSnapshot>
  /** The low reading in the snapshot's own unit (money amount / percent). */
  isLow(snapshot: BalanceSnapshot): boolean
}

export type BalanceService = { get(force: boolean): Promise<BalanceResult> }

/** Seam reference first, then the ambient environment variable of the same name. */
function resolveSeamThenEnv(
  deps: { credentials: BalanceCredentials },
  ref: string,
): () => Promise<string | undefined> {
  return async () => {
    const resolved = await deps.credentials.resolve(ref)
    if (resolved !== undefined && typeof resolved.value === 'string' && resolved.value !== '') {
      return resolved.value
    }
    const ambient = process.env[ref]
    return ambient !== undefined && ambient !== '' ? ambient : undefined
  }
}

/** Tolerant JSON file read: missing/unreadable/invalid all yield undefined. */
export function readJsonFile(path: string): Record<string, unknown> | undefined {
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8'))
    return typeof parsed === 'object' && parsed !== null ? parsed as Record<string, unknown> : undefined
  } catch {
    return undefined
  }
}

/** kcn keeps provider keys in the openclaw gateway config at this pointer. */
function readOpenclawProviderKey(configPath: string, provider: string): string | undefined {
  const cfg = readJsonFile(configPath)
  const providers = cfg?.models as Record<string, unknown> | undefined ?? {}
  const list = providers.providers as Record<string, Record<string, unknown>> | undefined ?? {}
  const entry = list[provider] ?? {}
  const key = entry.apiKey
  return typeof key === 'string' && key !== '' ? key : undefined
}

const numberOr = (value: number | undefined, fallback: number): number =>
  typeof value === 'number' && isFinite(value) ? value : fallback

/** GET a JSON endpoint with the shared timeout and the shared Chinese error wording. */
async function fetchJson(
  url: string,
  headers: Record<string, string>,
  vendor: string,
  statusMessages: Partial<Record<number, string>> = {},
): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(url, { headers: { accept: 'application/json', ...headers }, signal: AbortSignal.timeout(TIMEOUT_MS) })
  } catch (cause) {
    throw new Error(`网络请求失败:${cause instanceof Error ? cause.message : String(cause)}`)
  }
  const known = statusMessages[response.status]
  if (known !== undefined) throw new Error(known)
  if (!response.ok) throw new Error(`${vendor} 接口返回 HTTP ${response.status}`)
  try {
    return await response.json()
  } catch {
    throw new Error(`解析 ${vendor} 数据失败`)
  }
}

function createQuotaService(
  deps: { credentials: BalanceCredentials },
  spec: QuotaServiceSpec,
): BalanceService {
  let snapshot: BalanceSnapshot | null = null
  let fetchedAt = 0
  // The last refresh's failure, cleared only by a successful one. `fetchedAt`
  // dates the last SUCCESS, so without this a non-forced read inside the TTL
  // after a failed forced refresh answered 'cached' and repainted the stale
  // snapshot as healthy (#1546).
  let lastError: string | null = null
  // The run a concurrent caller joins, and whether it was forced: only a forced
  // run is guaranteed to reach upstream (#1567).
  let inFlight: { pending: Promise<BalanceResult>; force: boolean } | null = null

  const answer = (status: BalanceResult['status'], message: string | null): BalanceResult => ({
    configured: true,
    snapshot,
    status,
    low: snapshot === null ? false : spec.isLow(snapshot),
    message,
    threshold: spec.threshold,
    refreshMs: spec.refreshMs,
  })

  const run = async (apiKey: string): Promise<BalanceResult> => {
    try {
      snapshot = await spec.fetchFresh(apiKey)
      fetchedAt = Date.now()
      lastError = null
      return answer('fresh', null)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      if (snapshot !== null) lastError = message
      return answer(snapshot !== null ? 'stale' : 'failed', message)
    }
  }

  const exec = async (force: boolean): Promise<BalanceResult> => {
    const apiKey = await spec.resolveApiKey(deps)
    if (apiKey === undefined) {
      return {
        configured: false,
        snapshot: null,
        status: 'no-key',
        low: false,
        message: spec.noKeyMessage,
        threshold: spec.threshold,
        refreshMs: spec.refreshMs,
      }
    }
    if (!force && snapshot !== null && Date.now() - fetchedAt < (spec.ttlMs ?? TTL_MS)) {
      return lastError !== null ? answer('stale', lastError) : answer('cached', null)
    }
    return run(apiKey)
  }

  return {
    /**
     * Cached-or-fetch read. A concurrent caller (a poll tick racing a manual
     * click) JOINS the in-flight run instead of stampeding the upstream —
     * one request per window, however many faces ask.
     */
    async get(force: boolean): Promise<BalanceResult> {
      if (inFlight !== null && (inFlight.force || !force)) return inFlight.pending
      // A forced read never joins a non-forced run: that one may answer from
      // the TTL cache, which would turn a manual refresh into 'cached' (#1567).
      // It waits for the running one to settle, then fetches itself — still
      // one upstream request at a time.
      const prior = inFlight?.pending
      // The guard is claimed synchronously, BEFORE exec's first await: a
      // caller that checks inFlight while the first one is suspended at
      // resolveApiKey() must still join instead of starting a second fetch.
      const pending = prior === undefined
        ? exec(force)
        : prior.then(() => exec(true), () => exec(true))
      const claim = { pending, force }
      inFlight = claim
      try {
        return await pending
      } finally {
        // A forced run may have replaced this claim while it was pending.
        if (inFlight === claim) inFlight = null
      }
    },
  }
}

const numOrInfinity = (value: string): number => {
  const parsed = Number.parseFloat(value)
  return isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY
}

/** DeepSeek row: official money balance, CNY entry preferred. */
export function createBalanceService(
  deps: { credentials: BalanceCredentials },
  config: BalanceConfig = {},
): BalanceService {
  const baseUrl = config.baseUrl ?? DEFAULT_BALANCE_BASE_URL
  const threshold = numberOr(config.threshold, DEFAULT_BALANCE_THRESHOLD)
  return createQuotaService(deps, {
    resolveApiKey: resolveSeamThenEnv(deps, DEEPSEEK_KEY_REF),
    noKeyMessage: '未配置 DeepSeek API Key(设置 → 模型 → DeepSeek)',
    threshold,
    refreshMs: numberOr(config.refreshMs, DEFAULT_BALANCE_REFRESH_MS),
    async fetchFresh(apiKey) {
      const body = await fetchJson(`${baseUrl}/user/balance`, { authorization: `Bearer ${apiKey}` }, '余额', {
        401: 'API Key 无效或已过期',
        429: '请求过于频繁,请稍后再试',
      })
      return parseBalancePayload(body, new Date().toISOString())
    },
    // DeepSeek is money, not quota — its snapshots are always unit 'money'
    // (parseBalancePayload), so the low check stays a plain balance floor.
    isLow: (snapshot) => snapshot.unit === 'money'
      && snapshot.isAvailable
      && numOrInfinity(snapshot.totalBalance) <= threshold,
  })
}

/** MiniMax row: official Token Plan quota windows, percent-based. */
export function createMinimaxService(
  deps: { credentials: BalanceCredentials },
  config: MinimaxConfig = {},
): BalanceService {
  const baseUrl = config.baseUrl ?? DEFAULT_MINIMAX_BASE_URL
  const lowPct = numberOr(config.lowPct, DEFAULT_MINIMAX_LOW_PCT)
  const seamEnv = resolveSeamThenEnv(deps, config.keyRef ?? MINIMAX_KEY_REF)
  const openclawPath = expandHome(config.openclawConfigPath ?? DEFAULT_OPENCLAW_CONFIG_PATH)
  return createQuotaService(deps, {
    // kcn keeps the real key in the openclaw gateway's own config — that file
    // is the working fallback when the dsh seam and env are both unset.
    resolveApiKey: async () => (await seamEnv()) ?? readOpenclawProviderKey(openclawPath, 'minimax'),
    noKeyMessage: '未配置 MiniMax API Key(凭据缝 / 环境变量 / openclaw 配置均无)',
    threshold: lowPct,
    refreshMs: DEFAULT_BALANCE_REFRESH_MS,
    async fetchFresh(apiKey) {
      const body = await fetchJson(`${baseUrl}/v1/token_plan/remains`, { authorization: `Bearer ${apiKey}` }, 'MiniMax')
      // A HTTP-200 body can still be a business failure (auth=1004); the
      // envelope's status_code is the verdict, status_msg the reason.
      const raw = (typeof body === 'object' && body !== null ? body : {}) as RawRemainsBody
      const code = raw.base_resp?.status_code
      if (code !== undefined && code !== 0) {
        const msg = typeof raw.base_resp?.status_msg === 'string' && raw.base_resp.status_msg !== ''
          ? raw.base_resp.status_msg
          : `错误码 ${code}`
        throw new Error(code === 1004 ? `MiniMax API Key 无效或已过期(${msg})` : `MiniMax 接口错误:${msg}`)
      }
      return parseMinimaxRemains(body, new Date().toISOString())
    },
    isLow: (snapshot) => quotaIsLow(snapshot, lowPct),
  })
}

const resolveExecutable = (command: string): string | undefined => {
  if (command.includes('/')) return existsSync(command) ? command : undefined
  for (const dir of (process.env.PATH ?? '').split(delimiter)) {
    if (dir === '') continue
    const candidate = join(dir, command)
    if (existsSync(candidate)) return candidate
  }
  return undefined
}

/**
 * Ask Codex itself for ChatGPT limits. The CLI owns auth and refresh; this
 * plugin never reads or forwards tokens. One short-lived JSONL app-server is
 * cheaper and safer than duplicating Codex's private HTTP/auth behavior.
 */
export function readCodexRateLimits(
  command: string,
  timeoutMs: number = TIMEOUT_MS,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, ['app-server'], { stdio: ['pipe', 'pipe', 'pipe'] })
    let settled = false
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => finish(new Error(`Codex app-server ${timeoutMs}ms 内未返回`)), timeoutMs)

    const finish = (error?: Error, result?: unknown): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      child.stdin.end()
      if (!child.killed) child.kill()
      if (error !== undefined) reject(error)
      else resolve(result)
    }
    const send = (message: unknown): void => {
      if (!settled) child.stdin.write(`${JSON.stringify(message)}\n`)
    }
    const handleLine = (line: string): void => {
      if (line.trim() === '' || settled) return
      let message: { id?: number; result?: unknown; error?: { message?: string } }
      try {
        message = JSON.parse(line) as typeof message
      } catch {
        return
      }
      if (message.id === 0) {
        if (message.error !== undefined) {
          finish(new Error(`Codex app-server 初始化失败:${message.error.message ?? '未知错误'}`))
          return
        }
        send({ method: 'initialized', params: {} })
        send({ method: 'account/rateLimits/read', id: 1, params: { excludeResetCreditDetails: true } })
      } else if (message.id === 1) {
        if (message.error !== undefined) {
          finish(new Error(`Codex 额度读取失败:${message.error.message ?? '未知错误'}`))
          return
        }
        finish(undefined, message.result)
      }
    }

    child.on('spawn', () => send({
      method: 'initialize',
      id: 0,
      params: { clientInfo: { name: 'clawock_dsh', title: 'Clawock DSH', version: '0.1.0' } },
    }))
    child.on('error', (cause) => finish(new Error(`Codex CLI 启动失败:${cause.message}`)))
    child.on('exit', (code, signal) => {
      if (settled) return
      const detail = stderr.trim() !== '' ? `:${stderr.trim()}` : ''
      finish(new Error(`Codex app-server 提前退出(${signal ?? code ?? '未知'})${detail}`))
    })
    child.stdin.on('error', (cause) => finish(new Error(`Codex app-server 写入失败:${cause.message}`)))
    child.stderr.on('data', (chunk: Buffer) => {
      if (stderr.length < 4096) stderr += chunk.toString('utf8').slice(0, 4096 - stderr.length)
    })
    child.stdout.on('data', (chunk: Buffer) => {
      stdout += chunk.toString('utf8')
      if (stdout.length > 1024 * 1024) {
        finish(new Error('Codex app-server 输出超过 1MiB'))
        return
      }
      const lines = stdout.split('\n')
      stdout = lines.pop() ?? ''
      for (const line of lines) handleLine(line)
    })
  })
}

/** Codex row: ChatGPT subscription quota through the official app-server. */
export function createCodexService(
  deps: { credentials: BalanceCredentials },
  config: CodexConfig = {},
): BalanceService {
  const command = expandHome(config.command ?? DEFAULT_CODEX_COMMAND)
  const lowPct = numberOr(config.lowPct, DEFAULT_CODEX_LOW_PCT)
  const refreshMs = numberOr(config.refreshMs, DEFAULT_CODEX_REFRESH_MS)
  return createQuotaService(deps, {
    resolveApiKey: async () => resolveExecutable(command),
    noKeyMessage: `未找到 Codex CLI(${command})`,
    threshold: lowPct,
    refreshMs,
    ttlMs: refreshMs,
    async fetchFresh(executable) {
      return parseCodexRateLimits(await readCodexRateLimits(executable), new Date().toISOString())
    },
    isLow: (snapshot) => quotaIsLow(snapshot, lowPct),
  })
}

/** Claude Code's stored OAuth identity — token plus the plan it belongs to. */
interface ClaudeCredentials {
  accessToken?: string
  refreshToken?: string
  expiresAt?: number
  subscriptionType?: string
  rateLimitTier?: string
}

/**
 * Read Claude Code's OAuth credentials. The file belongs to Claude Code —
 * this service only READS it; rotating/refreshing stays their job, so an
 * expired token surfaces as a failed row telling kcn to run claude once.
 */
export function readClaudeCredentials(path: string): { creds: ClaudeCredentials } | undefined {
  const parsed = readJsonFile(path)
  const creds = parsed?.claudeAiOauth as ClaudeCredentials | undefined
  if (creds === undefined || typeof creds !== 'object') return undefined
  return { creds }
}

/** Claude row: subscription rate-limit windows via the OAuth usage endpoint. */
export function createClaudeService(
  deps: { credentials: BalanceCredentials },
  config: ClaudeConfig = {},
): BalanceService {
  const credentialsPath = expandHome(config.credentialsPath ?? DEFAULT_CLAUDE_CREDENTIALS_PATH)
  const usageUrl = config.usageUrl ?? DEFAULT_CLAUDE_USAGE_URL
  const lowPct = numberOr(config.lowPct, DEFAULT_CLAUDE_LOW_PCT)
  // The seam plays no role here — the secret is Claude Code's own login file.
  return createQuotaService(deps, {
    resolveApiKey: async () => readClaudeCredentials(credentialsPath)?.creds.accessToken,
    noKeyMessage: '未找到 Claude 登录(~/.claude/.credentials.json)',
    threshold: lowPct,
    refreshMs: DEFAULT_BALANCE_REFRESH_MS,
    async fetchFresh() {
      const entry = readClaudeCredentials(credentialsPath)
      if (entry === undefined) throw new Error('Claude 登录文件不存在或已损坏')
      const { creds } = entry
      if (typeof creds.accessToken !== 'string' || creds.accessToken === '') {
        throw new Error('Claude 登录文件里没有 accessToken')
      }
      if (typeof creds.expiresAt === 'number' && Date.now() > creds.expiresAt) {
        throw new Error('Claude 登录已过期,请在终端跑一次 claude 刷新登录')
      }
      const body = await fetchJson(usageUrl, {
        authorization: `Bearer ${creds.accessToken}`,
        'anthropic-beta': 'oauth-2025-04-20',
      }, 'Claude 用量', {
        401: 'Claude 登录无效或已过期',
        403: 'Claude 登录无效或已过期',
        429: '请求过于频繁,请稍后再试',
      })
      return parseClaudeUsage(body, new Date().toISOString())
    },
    isLow: (snapshot) => quotaIsLow(snapshot, lowPct),
  })
}
