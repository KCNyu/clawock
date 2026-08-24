/**
 * Provider account balances for the session header chip — official endpoints
 * answered with the SAME keys the harness's adapters use (credentials seam
 * references, falling back to ambient environment variables):
 *
 *   - deepseek: `GET https://api.deepseek.com/user/balance` (money, CNY row)
 *   - minimax:  `GET {base}/v1/token_plan/remains` (Token Plan quota windows;
 *     `base_resp.status_code` is the business verdict — 0 ok, 1004 auth —
 *     and a HTTP-200 body can still be an auth failure)
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

import { homedir } from 'node:os'
import { join } from 'node:path'
import { readFileSync } from 'node:fs'
import type { BalanceResult, BalanceSnapshot, BalanceWindow } from './types.ts'

export const DEFAULT_BALANCE_BASE_URL = 'https://api.deepseek.com'
export const DEFAULT_BALANCE_THRESHOLD = 20
export const DEFAULT_BALANCE_REFRESH_MS = 60000
export const DEFAULT_MINIMAX_BASE_URL = 'https://api.minimaxi.com'
export const DEFAULT_MINIMAX_LOW_PCT = 20
export const DEFAULT_OPENCLAW_CONFIG_PATH = '/root/.openclaw/openclaw.json'
export const DEFAULT_CLAUDE_CREDENTIALS_PATH = '/root/.claude/.credentials.json'
export const DEFAULT_CLAUDE_USAGE_URL = 'https://api.anthropic.com/api/oauth/usage'
export const DEFAULT_CLAUDE_LOW_PCT = 20
const TTL_MS = 60000
const TIMEOUT_MS = 15000

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
  /** Red dot when a quota window's remaining percent drops to/below this. */
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
  /** Red dot when the session window's remaining percent drops to/below this. */
  lowPct?: number
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

/** The credentials capability, narrowed to what this service uses. */
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

/** One model_remains bucket, as far as this service reads it. */
export interface MinimaxRemainsEntry {
  model?: string
  current_interval_remaining_percent?: number
  current_interval_total_count?: number
  current_interval_usage_count?: number
  current_weekly_remaining_percent?: number
  end_time?: number
  [key: string]: unknown
}

interface RawRemainsBody {
  base_resp?: { status_code?: number; status_msg?: string }
  model_remains?: MinimaxRemainsEntry[]
}

const finiteNumber = (value: unknown): number | null =>
  typeof value === 'number' && isFinite(value) ? value : null

/**
 * Remaining percent of one quota window: the explicit percent field when the
 * plan reports one, otherwise derived from total/used counts (MiniMax ships
 * both shapes across plan generations). null = unreadable, never guessed.
 */
export function windowRemainingPercent(entry: MinimaxRemainsEntry): number | null {
  const direct = finiteNumber(entry.current_interval_remaining_percent)
  if (direct !== null) return Math.min(100, Math.max(0, direct))
  const total = finiteNumber(entry.current_interval_total_count)
  const used = finiteNumber(entry.current_interval_usage_count)
  if (total !== null && total > 0 && used !== null && used >= 0) {
    return Math.min(100, Math.max(0, ((total - used) / total) * 100))
  }
  return null
}

/**
 * Reset stamps the panel can lay out: within 48h a bare local clock,
 * farther out the weekday comes along ('周四 21:00'). Accepts epoch seconds,
 * epoch milliseconds and RFC3339 strings — MiniMax sends epochs while
 * Claude sends ISO.
 */
export function formatReset(epochOrIso: number | string | null | undefined): string {
  let ms: number | null = null
  if (typeof epochOrIso === 'number' && isFinite(epochOrIso) && epochOrIso > 0) {
    ms = epochOrIso > 1e12 ? epochOrIso : epochOrIso * 1000
  } else if (typeof epochOrIso === 'string' && epochOrIso !== '') {
    const at = new Date(epochOrIso)
    if (!isNaN(at.getTime())) ms = at.getTime()
  }
  if (ms === null) return ''
  const at = new Date(ms)
  const hhmm = String(at.getHours()).padStart(2, '0') + ':' + String(at.getMinutes()).padStart(2, '0')
  if (at.getTime() - Date.now() < 48 * 3600_000) return hhmm
  const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return week[at.getDay()] + ' ' + hhmm
}

/** Epoch ms/sec heuristic → local reset stamp (legacy note helper). */
function resetClock(epoch: unknown): string | null {
  const raw = finiteNumber(epoch)
  if (raw === null || raw <= 0) return null
  return formatReset(raw)
}

/**
 * The successful Token Plan payload → snapshot. Percent-based by design:
 * plans report either percent fields or raw counts, and tokens are not money
 * — the chip reads "还剩多少窗口额度", never a fabricated ¥ figure.
 */
export function parseMinimaxRemains(body: unknown, asOf: string): BalanceSnapshot {
  const raw = (typeof body === 'object' && body !== null ? body : {}) as RawRemainsBody
  const buckets = Array.isArray(raw.model_remains) ? raw.model_remains : []
  // `general` is the text/coding bucket every plan carries; video et al are add-ons.
  const entry = buckets.find((b) => b.model === 'general') ?? buckets[0]
  if (entry === undefined) throw new Error('MiniMax 响应里没有 model_remains 数据')
  const pct = windowRemainingPercent(entry)
  const weekly = finiteNumber(entry.current_weekly_remaining_percent)
  const windows: BalanceWindow[] = []
  if (pct !== null) windows.push({ label: '5h', percent: Math.round(pct), resetAt: formatReset(entry.end_time as number | undefined) })
  if (weekly !== null) windows.push({ label: '周', percent: Math.round(weekly), resetAt: formatReset(entry.weekly_end_time as number | undefined) })
  const notes: string[] = []
  if (pct !== null) notes.push('5h 窗口剩余 ' + Math.round(pct) + '%')
  if (weekly !== null) notes.push('周窗口剩余 ' + Math.round(weekly) + '%')
  return {
    isAvailable: pct !== null && pct > 0,
    unit: 'pct',
    currency: '',
    totalBalance: pct === null ? '' : String(Math.round(pct)),
    grantedBalance: '',
    toppedUpBalance: '',
    asOf,
    note: notes.join(' · '),
    windows,
  }
}

/**
 * The shared cadence shell — TTL cache, in-flight join, stale-on-failure —
 * parameterized by provider. Both services below differ only in key
 * resolution, endpoint, parse and low-reading; everything temporal is here
 * once.
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
  fetchFresh(apiKey: string): Promise<BalanceSnapshot>
  /** The low reading in the snapshot's own unit (money amount / percent). */
  isLow(snapshot: BalanceSnapshot): boolean
}

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

function createQuotaService(
  deps: { credentials: BalanceCredentials },
  spec: QuotaServiceSpec,
): { get(force: boolean): Promise<BalanceResult> } {
  let snapshot: BalanceSnapshot | null = null
  let fetchedAt = 0
  let inFlight: Promise<BalanceResult> | null = null

  const resolveKey = async (): Promise<string | undefined> => spec.resolveApiKey(deps)

  const run = async (apiKey: string): Promise<BalanceResult> => {
    try {
      snapshot = await spec.fetchFresh(apiKey)
      fetchedAt = Date.now()
      return {
        configured: true,
        snapshot,
        status: 'fresh',
        low: spec.isLow(snapshot),
        message: null,
        threshold: spec.threshold,
        refreshMs: spec.refreshMs,
      }
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      if (snapshot !== null) {
        return {
          configured: true,
          snapshot,
          status: 'stale',
          low: spec.isLow(snapshot),
          message,
          threshold: spec.threshold,
          refreshMs: spec.refreshMs,
        }
      }
      return { configured: true, snapshot: null, status: 'failed', low: false, message, threshold: spec.threshold, refreshMs: spec.refreshMs }
    }
  }

  const exec = async (force: boolean): Promise<BalanceResult> => {
    const apiKey = await resolveKey()
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
    if (!force && snapshot !== null && Date.now() - fetchedAt < TTL_MS) {
      return {
        configured: true,
        snapshot,
        status: 'cached',
        low: spec.isLow(snapshot),
        message: null,
        threshold: spec.threshold,
        refreshMs: spec.refreshMs,
      }
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
      if (inFlight !== null) return inFlight
      // The guard is claimed synchronously, BEFORE exec's first await: a
      // caller that checks inFlight while the first one is suspended at
      // resolveKey() must still join instead of starting a second fetch.
      const pending = exec(force)
      inFlight = pending
      try {
        return await pending
      } finally {
        inFlight = null
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
): { get(force: boolean): Promise<BalanceResult> } {
  const baseUrl = config.baseUrl ?? DEFAULT_BALANCE_BASE_URL
  const threshold = typeof config.threshold === 'number' && isFinite(config.threshold)
    ? config.threshold
    : DEFAULT_BALANCE_THRESHOLD
  return createQuotaService(deps, {
    resolveApiKey: resolveSeamThenEnv(deps, DEEPSEEK_KEY_REF),
    noKeyMessage: '未配置 DeepSeek API Key(设置 → 模型 → DeepSeek)',
    threshold,
    refreshMs: typeof config.refreshMs === 'number' && isFinite(config.refreshMs)
      ? config.refreshMs
      : DEFAULT_BALANCE_REFRESH_MS,
    async fetchFresh(apiKey) {
      let response: Response
      try {
        response = await fetch(`${baseUrl}/user/balance`, {
          headers: { authorization: `Bearer ${apiKey}`, accept: 'application/json' },
          signal: AbortSignal.timeout(TIMEOUT_MS),
        })
      } catch (cause) {
        throw new Error(`网络请求失败:${cause instanceof Error ? cause.message : String(cause)}`)
      }
      if (response.status === 401) throw new Error('API Key 无效或已过期')
      if (response.status === 429) throw new Error('请求过于频繁,请稍后再试')
      if (!response.ok) throw new Error(`余额接口返回 HTTP ${response.status}`)
      let body: unknown
      try {
        body = await response.json()
      } catch {
        throw new Error('解析余额数据失败')
      }
      return parseBalancePayload(body, new Date().toISOString())
    },
    isLow: (snapshot) => snapshot.unit === 'pct'
      ? numOrInfinity(snapshot.totalBalance) <= threshold
      : snapshot.isAvailable && numOrInfinity(snapshot.totalBalance) <= threshold,
  })
}

/** MiniMax row: official Token Plan quota windows, percent-based. */
export function createMinimaxService(
  deps: { credentials: BalanceCredentials },
  config: MinimaxConfig = {},
): { get(force: boolean): Promise<BalanceResult> } {
  const baseUrl = config.baseUrl ?? DEFAULT_MINIMAX_BASE_URL
  const lowPct = typeof config.lowPct === 'number' && isFinite(config.lowPct)
    ? config.lowPct
    : DEFAULT_MINIMAX_LOW_PCT
  const seamEnv = resolveSeamThenEnv(deps, config.keyRef ?? MINIMAX_KEY_REF)
  const openclawPath = config.openclawConfigPath ?? DEFAULT_OPENCLAW_CONFIG_PATH
  return createQuotaService(deps, {
    // kcn keeps the real key in the openclaw gateway's own config — that file
    // is the working fallback when the dsh seam and env are both unset.
    resolveApiKey: async () => (await seamEnv()) ?? readOpenclawProviderKey(openclawPath, 'minimax'),
    noKeyMessage: '未配置 MiniMax API Key(凭据缝 / 环境变量 / openclaw 配置均无)',
    threshold: lowPct,
    refreshMs: DEFAULT_BALANCE_REFRESH_MS,
    async fetchFresh(apiKey) {
      let response: Response
      try {
        response = await fetch(`${baseUrl}/v1/token_plan/remains`, {
          headers: { authorization: `Bearer ${apiKey}`, accept: 'application/json' },
          signal: AbortSignal.timeout(TIMEOUT_MS),
        })
      } catch (cause) {
        throw new Error(`网络请求失败:${cause instanceof Error ? cause.message : String(cause)}`)
      }
      if (!response.ok) throw new Error(`MiniMax 接口返回 HTTP ${response.status}`)
      let body: unknown
      try {
        body = await response.json()
      } catch {
        throw new Error('解析 MiniMax 数据失败')
      }
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
    isLow: (snapshot) => snapshot.unit === 'pct'
      ? numOrInfinity(snapshot.totalBalance) <= lowPct
      : false,
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

/** One usage window: utilization is the % already consumed (0-100). */
export interface ClaudeUsageWindow {
  utilization?: number
  resets_at?: string
}

interface RawClaudeUsage {
  five_hour?: ClaudeUsageWindow | null
  seven_day?: ClaudeUsageWindow | null
  extra_usage?: { is_enabled?: boolean; utilization?: number | null } | null
  [key: string]: unknown
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

const localClock = (iso: string): string | null => {
  const at = new Date(iso)
  if (isNaN(at.getTime())) return null
  return String(at.getHours()).padStart(2, '0') + ':' + String(at.getMinutes()).padStart(2, '0')
}

/**
 * Successful usage payload → snapshot, in REMAINING percent (utilization is
 * consumption). five_hour gates active sessions so it is the headline; any
 * bucket may be absent/null depending on plan.
 */
export function parseClaudeUsage(body: unknown, asOf: string): BalanceSnapshot {
  const raw = (typeof body === 'object' && body !== null ? body : {}) as RawClaudeUsage
  const u5 = finiteNumber(raw.five_hour?.utilization)
  const u7 = finiteNumber(raw.seven_day?.utilization)
  if (u5 === null && u7 === null) throw new Error('Claude 响应里没有可用的用量窗口')
  const remaining = u5 === null ? null : Math.round(Math.min(100, Math.max(0, 100 - u5)))
  const windows: BalanceWindow[] = []
  if (u5 !== null) windows.push({ label: '会话', percent: remaining, resetAt: formatReset(raw.five_hour?.resets_at ?? null) })
  if (u7 !== null) windows.push({ label: '本周', percent: Math.round(Math.min(100, Math.max(0, 100 - u7))), resetAt: formatReset(raw.seven_day?.resets_at ?? null) })
  const notes: string[] = []
  if (u5 !== null) notes.push('会话窗口剩余 ' + remaining + '%')
  if (u7 !== null) notes.push('本周剩余 ' + Math.round(100 - u7) + '%')
  const extraUtil = raw.extra_usage?.is_enabled === true ? finiteNumber(raw.extra_usage?.utilization ?? undefined) : null
  if (extraUtil !== null) notes.push('附加额度已用 ' + Math.round(extraUtil) + '%')
  return {
    isAvailable: remaining === null ? false : remaining > 0,
    unit: 'pct',
    currency: '',
    totalBalance: remaining === null ? '' : String(remaining),
    grantedBalance: '',
    toppedUpBalance: '',
    asOf,
    note: notes.join(' · '),
    windows,
  }
}

/** Claude row: subscription rate-limit windows via the OAuth usage endpoint. */
export function createClaudeService(
  deps: { credentials: BalanceCredentials },
  config: ClaudeConfig = {},
): { get(force: boolean): Promise<BalanceResult> } {
  const credentialsPath = config.credentialsPath ?? DEFAULT_CLAUDE_CREDENTIALS_PATH
  const usageUrl = config.usageUrl ?? DEFAULT_CLAUDE_USAGE_URL
  const lowPct = typeof config.lowPct === 'number' && isFinite(config.lowPct)
    ? config.lowPct
    : DEFAULT_CLAUDE_LOW_PCT
  // The seam plays no role here — the secret is Claude Code's own login file.
  void deps
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
      let response: Response
      try {
        response = await fetch(usageUrl, {
          headers: {
            authorization: `Bearer ${creds.accessToken}`,
            accept: 'application/json',
            'anthropic-beta': 'oauth-2025-04-20',
          },
          signal: AbortSignal.timeout(TIMEOUT_MS),
        })
      } catch (cause) {
        throw new Error(`网络请求失败:${cause instanceof Error ? cause.message : String(cause)}`)
      }
      if (response.status === 401 || response.status === 403) throw new Error('Claude 登录无效或已过期')
      if (response.status === 429) throw new Error('请求过于频繁,请稍后再试')
      if (!response.ok) throw new Error(`Claude 用量接口返回 HTTP ${response.status}`)
      let body: unknown
      try {
        body = await response.json()
      } catch {
        throw new Error('解析 Claude 数据失败')
      }
      return parseClaudeUsage(body, new Date().toISOString())
    },
    isLow: (snapshot) => snapshot.unit === 'pct'
      ? numOrInfinity(snapshot.totalBalance) <= lowPct
      : false,
  })
}
