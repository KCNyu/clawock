#!/usr/bin/env node
// node quota.mjs claude|codex|dsh — one line of the agent's remaining allowance for the finish /
// quota-wait notifications: subscription quota for claude/codex, the DeepSeek money balance for
// dsh. Reuses the clawock-dsh balance chip's readers (Claude OAuth usage endpoint, `codex
// app-server` account/rateLimits/read, DeepSeek /user/balance) and its window vocabulary (label
// from window length, one reset-stamp format), so WeChat and the chip read the same.
// Never throws, never prints a token: failures come back as one in-band Chinese line.
//
// A one-shot probe cannot reuse the chip's in-process cache, so every call hit the endpoint with
// force=true. Anthropic answers 429 ("请求过于频繁") once that endpoint is polled too often — the
// runner probes twice in a row per event (quota wait + finish) and every task adds more, so the
// quota line went unreadable for a whole stretch on 2026-09-23. Cache the rendered line on disk
// (SHORT_TTL) and only refresh when it is older; a stale line beats no line, and the probe must
// never be the reason a task's quota cannot be read.
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const LIB = process.env.AGENT_DISPATCH_BALANCE_LIB
  ?? '/root/.dsh/profiles/web/node_modules/clawock-dsh/lib/balance.js'
const CACHE_DIR = process.env.AGENT_DISPATCH_QUOTA_CACHE_DIR ?? '/root/.cache/agent-dispatch'
// dsh's headless attempt exports `refs:` from this file into its own subshell (run-agent.sh
// dsh_env); the finish probe runs in the runner's process, where those exports do not exist.
// Read the same seam here, with the same precedence: an already-set variable first, then the file.
const DSH_CREDENTIALS = process.env.AGENT_DISPATCH_DSH_CREDENTIALS ?? '/root/.dsh/.credentials.yaml'
const agent = process.argv[2]
// Long enough to absorb the runner's immediate second probe and repeated status checks, short
// enough that a notification during a quota wait still quotes a current window.
const TTL_MS = Number(process.env.AGENT_DISPATCH_QUOTA_TTL_MS ?? 90_000)
// An unreadable read is cached far more briefly: it may be a transient 429 worth retrying, but
// not on every caller in the same minute.
const ERROR_TTL_MS = Number(process.env.AGENT_DISPATCH_QUOTA_ERROR_TTL_MS ?? 30_000)
// A failed read repeats the last good line, marked with its age, while it is younger than this;
// the windows move slowly and the notification is still more useful than "读取失败".
const LAST_GOOD_MS = Number(process.env.AGENT_DISPATCH_QUOTA_LAST_GOOD_MS ?? 6 * 3600_000)

const cacheFile = () => `${CACHE_DIR}/quota-${agent}.json`

function loadCache() {
  try {
    const raw = JSON.parse(readFileSync(cacheFile(), 'utf8'))
    return typeof raw?.line === 'string' && typeof raw?.at === 'number' ? raw : null
  } catch { return null }
}

function readCache(raw) {
  if (raw === null) return null
  const ttl = raw.ok === false ? ERROR_TTL_MS : TTL_MS
  return Date.now() - raw.at < ttl ? raw.line : null
}

// `good` carries the last successful line across failures. Written via rename: two runners
// probing at once must never leave (or read) a half-written file.
function writeCache(line, ok, good) {
  try {
    mkdirSync(CACHE_DIR, { recursive: true })
    const tmp = `${cacheFile()}.${process.pid}.tmp`
    writeFileSync(tmp, JSON.stringify({ line, at: Date.now(), ok, good }))
    renameSync(tmp, cacheFile())
  } catch { /* a read-only cache dir must not break the probe */ }
}

function lastGood(raw) {
  if (raw?.ok === true) return { line: raw.line, at: raw.at }
  const good = raw?.good
  return typeof good?.line === 'string' && typeof good?.at === 'number' ? good : null
}

function settle(line, ok, raw) {
  if (ok) {
    writeCache(line, true, null)
    return line
  }
  const good = lastGood(raw)
  const shown = good !== null && Date.now() - good.at < LAST_GOOD_MS
    ? `${good.line}（${Math.max(1, Math.round((Date.now() - good.at) / 60_000))} 分钟前的读数；刚才没读到，额度读不到不代表任务异常）`
    : line
  writeCache(shown, false, good)
  return shown
}

// The dsh credentials seam's `refs:` block is a flat NAME: value mapping at the top level; the
// file also holds other blocks. An already-set environment variable wins, exactly like dsh_env.
function dshRef(name) {
  const ambient = process.env[name]
  if (ambient !== undefined && ambient !== '') return ambient
  try {
    let inRefs = false
    for (const line of readFileSync(DSH_CREDENTIALS, 'utf8').split(/\r?\n/)) {
      if (/^refs:\s*$/.test(line)) { inRefs = true; continue }
      if (!inRefs) continue
      if (/^\S/.test(line)) break
      const match = /^\s+([A-Z][A-Z0-9_]*):\s*(.*?)\s*$/.exec(line)
      if (match === null || match[1] !== name) continue
      const value = match[2].replace(/^(['"])(.*)\1$/, '$2')
      return value === '' ? undefined : value
    }
  } catch { /* no readable seam file: the library then falls back to the environment */ }
  return undefined
}

// The library asks the seam by name (`resolve`); the old placeholder answered only `get`, which
// Claude and Codex happened not to call. dsh is the first caller that uses this object.
const credentials = {
  resolve: async (ref) => {
    const value = dshRef(ref)
    return value === undefined ? undefined : { value }
  },
}

async function probe() {
  if (!existsSync(LIB)) return { line: `额度：读取失败（找不到余额芯片模块 ${LIB}）`, ok: false }
  const balance = await import(pathToFileURL(LIB).href)
  let service
  if (agent === 'claude') {
    const home = process.env.CLAUDE_CONFIG_DIR ?? '/root/.claude'
    service = balance.createClaudeService({ credentials }, { credentialsPath: `${home}/.credentials.json` })
  } else if (agent === 'codex') {
    service = balance.createCodexService({ credentials }, { command: process.env.CODEX_COMMAND ?? 'codex' })
  } else if (agent === 'dsh') {
    service = balance.createBalanceService({ credentials })
  } else {
    return { line: '', ok: true }
  }
  const result = await service.get(true)
  if (agent === 'dsh') return moneyLine(result)
  const windows = result.snapshot?.windows ?? []
  if (result.status !== 'fresh' || windows.length === 0) {
    return { line: `额度：读取失败（${result.message ?? '没有额度窗口'}）`, ok: false }
  }
  // The chip speaks in used percent; the notification answers "how much is left".
  const parts = windows.map((w) => `${w.label} 剩 ${100 - w.percent}%` + (w.resetAt ? `（${w.resetAt} 重置）` : ''))
  return { line: '额度：' + parts.join(' · ') + (result.snapshot.isAvailable ? '' : ' · ' + unavailable(windows)), ok: true }
}

// DeepSeek is money, not quota: its snapshot has unit 'money' and no windows, so the window path
// above would call a perfectly good balance "没有额度窗口". The panel's _rowDisplay reads the same
// three amounts; this is the notification-shaped version, keeping the vendor's raw cents (「0.00」
// stays 「0.00」). The service gets no lastGoodPath on purpose: quota.mjs's disk cache is the one
// place a stale line is marked with its age, and a panel snapshot reused here would read as fresh.
function moneyLine(result) {
  const snapshot = result.snapshot
  const total = snapshot?.unit === 'money' ? snapshot.totalBalance : ''
  if (result.status !== 'fresh' || !isFinite(Number.parseFloat(total))) {
    return { line: `额度：读取失败（${result.message ?? '没有余额读数'}）`, ok: false }
  }
  const symbol = snapshot.currency === 'USD' ? '$' : snapshot.currency === 'CNY' ? '¥' : ''
  const amount = (value) => {
    const parsed = Number.parseFloat(value)
    if (!isFinite(parsed)) return null
    return (parsed < 0 ? '−' : '') + symbol + value.replace(/^-/, '')
  }
  const parts = ['余额 ' + amount(snapshot.totalBalance)]
  for (const [label, value] of [['赠金', snapshot.grantedBalance], ['充值', snapshot.toppedUpBalance]]) {
    const shown = amount(value)
    if (shown !== null) parts.push(`${label} ${shown}`)
  }
  if (!snapshot.isAvailable) parts.push('官方接口判定余额不足')
  return { line: '额度：' + parts.join(' · '), ok: true }
}

// Why the account cannot be used right now. This line used to end in a bare 「当前不可用」, which
// reads like a broken login; the windows were just read with that login, so say what it is.
function unavailable(windows) {
  const spent = windows.filter((w) => w.percent >= 100)
  if (spent.length === 0) return '当前不可用（窗口未用尽，是账号侧限用；登录正常）'
  // The account is back when the LAST exhausted window resets.
  const last = spent.reduce((a, b) => ((b.resetAtMs ?? 0) > (a.resetAtMs ?? 0) ? b : a))
  return `${spent.map((w) => w.label).join('、')}额度已用尽` + (last.resetAt ? `，${last.resetAt} 恢复` : '') + '（登录正常，不用重新登录）'
}

const raw = loadCache()
const cached = readCache(raw)
if (cached !== null) {
  console.log(cached)
} else {
  probe()
    .then(({ line, ok }) => { if (line) console.log(settle(line, ok, raw)) })
    .catch((cause) => {
      console.log(settle(`额度：读取失败（${cause instanceof Error ? cause.message : String(cause)}）`, false, raw))
    })
}
