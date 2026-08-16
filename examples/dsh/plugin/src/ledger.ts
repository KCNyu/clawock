/**
 * Read-only readers over the OpenClaw desk's produced data: the shared
 * decision ledger, the portfolio, and recent daily plans. Pure Node, no
 * Cordis/typert dependencies — unit-testable in isolation.
 *
 * These are the files the OpenClaw runtime produces every day, so whatever
 * OpenClaw writes, this DSH plugin can show.
 */

import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import type {
  Book, DecisionRow, EnrichedTrade, Holding, JsonValue, LedgerResult, PlanRow, PlansResult,
  PortfolioRead, TraceDecision, TraceT1, TracesResult, Trade,
} from './types.ts'

const PLAN_PATTERN = /^(\d{4}-\d{2}-\d{2})-plan\.json$/

function readJson(path: string): JsonValue | null {
  if (!existsSync(path)) return null
  try {
    return JSON.parse(readFileSync(path, 'utf8')) as JsonValue
  } catch {
    return null
  }
}

/**
 * Parse the decision ledger (memory/decisions.jsonl) — one JSON object per
 * line. Malformed lines are skipped, never fatal: the desk's own writer
 * round-trips the file and this view must survive any of its states.
 * @param workspace - desk workspace root.
 * @returns `{ entries, path }`; entries are in file order (oldest first).
 */
export function readLedger(workspace: string): LedgerResult {
  const path = join(workspace, 'memory', 'decisions.jsonl')
  const entries: JsonValue[] = []
  if (existsSync(path)) {
    const lines = readFileSync(path, 'utf8').split('\n')
    for (const line of lines) {
      if (!line.trim()) continue
      try {
        entries.push(JSON.parse(line) as JsonValue)
      } catch {
        /* skip one malformed line */
      }
    }
  }
  return { entries, path }
}

/**
 * Summarize the portfolio (portfolio.json): per-book holdings with the desk's
 * own money fields, plus the flattened trade log (newest first).
 * @param workspace - desk workspace root.
 * @returns `{ books, trades, lastUpdated }`.
 */
export function readPortfolio(workspace: string): PortfolioRead {
  const doc = readJson(join(workspace, 'portfolio.json'))
  if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) {
    return { books: [], trades: [], lastUpdated: null, marketContext: {} }
  }
  const books: Book[] = []
  const trades: Trade[] = []
  const portfolios = (doc as { portfolios?: unknown })['portfolios']
  if (portfolios !== null && typeof portfolios === 'object' && !Array.isArray(portfolios)) {
    for (const [name, book] of Object.entries(portfolios as Record<string, unknown>)) {
      if (book === null || typeof book !== 'object' || Array.isArray(book)) continue
      const bookObj = book as { holdings?: unknown; currency?: unknown; true_principal?: unknown }
      if (!Array.isArray(bookObj['holdings'])) continue
      const rawHoldings = bookObj['holdings'].filter((h): h is Record<string, unknown> => h !== null && typeof h === 'object')
      const holdings: Holding[] = rawHoldings
        .filter((h) => (Number(h['shares'] ?? h['quantity'] ?? 0)) > 0) // zero-share rows are not positions
        .map((h) => ({
          ticker: String(h['ticker'] ?? h['stock_name'] ?? h['name'] ?? '?'),
          shares: Number(h['shares'] ?? h['quantity'] ?? 0),
          cost: h['cost_basis'] == null ? null : Number(h['cost_basis']),
          price: h['current_price'] == null ? null : Number(h['current_price']),
          pnlPct: h['pnl_percent'] == null ? null : Number(h['pnl_percent']),
          pnlAbs: h['pnl_abs'] == null ? null : Number(h['pnl_abs']),
        }))
      if (holdings.length === 0) continue // a book with no positions is not shown
      const market = /^hk/i.test(name) ? 'HK' : 'US'
      const currency = typeof bookObj['currency'] === 'string'
        ? bookObj['currency']
        : (market === 'HK' ? 'HKD' : 'USD')
      books.push({
        name,
        currency,
        truePrincipal: bookObj['true_principal'] == null ? null : Number(bookObj['true_principal']),
        holdings,
      })
      // Actual operations: every recorded trade across all holdings, newest
      // first. This is the "what did I actually do" surface — real fills with
      // notes and realized P&L, not plan simulations.
      for (const holding of rawHoldings) {
        const rawTrades = holding['trades']
        if (!Array.isArray(rawTrades)) continue
        for (const tr of rawTrades) {
          if (tr === null || typeof tr !== 'object') continue
          const trObj = tr as Record<string, unknown>
          trades.push({
            ticker: String(holding['ticker'] ?? holding['stock_name'] ?? holding['name'] ?? '?'),
            market,
            currency,
            date: typeof trObj['date'] === 'string' ? trObj['date'] : null,
            action: typeof trObj['action'] === 'string' ? trObj['action'] : 'buy',
            shares: Number(trObj['shares'] ?? 0),
            price: trObj['price'] == null ? null : Number(trObj['price']),
            realizedPnl: trObj['realized_pnl'] == null ? null : Number(trObj['realized_pnl']),
            note: typeof trObj['note'] === 'string' ? trObj['note'] : null,
          })
        }
      }
    }
  }
  trades.sort((a, b) => ((a.date ?? '') < (b.date ?? '') ? 1 : -1))
  const lastUpdated = typeof (doc as { last_updated?: unknown })['last_updated'] === 'string'
    ? (doc as { last_updated?: unknown })['last_updated'] as string
    : null
  // Returned so `readTraces` does not have to read and parse portfolio.json a
  // second time just to reach `market_context`.
  const marketContext = ((doc as { market_context?: unknown })['market_context'] ?? {}) as { [key: string]: JsonValue }
  return { books, trades, lastUpdated, marketContext }
}

/**
 * List recent daily plans (memory/YYYY-MM-DD-plan.json), newest first.
 * @param workspace - desk workspace root.
 * @param limit - how many plans to return.
 */
export function readPlans(workspace: string, limit = 14): PlansResult {
  const plans: PlanRow[] = []
  let files: string[] = []
  try {
    files = readdirSync(join(workspace, 'memory'))
  } catch {
    return { plans }
  }
  const dated = files
    .map((name) => PLAN_PATTERN.exec(name))
    .filter((m): m is RegExpExecArray => m !== null)
    .map((m) => ({ date: m[1]!, name: m[0]! }))
    .sort((a, b) => (a.date < b.date ? 1 : -1))
    .slice(0, limit)
  for (const file of dated) {
    const doc = readJson(join(workspace, 'memory', file.name))
    if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) continue
    const docObj = doc as { decisions?: unknown; title?: unknown }
    plans.push({
      date: file.date,
      decisions: Array.isArray(docObj['decisions']) ? docObj['decisions'].length : 0,
      title: typeof docObj['title'] === 'string' ? docObj['title'] : null,
    })
  }
  return { plans }
}

/* ------------------------------------------------------------------ */
/* Decision trace view: the organic "one view" — real fills as the     */
/* spine, decision ledger soft-paired (±3 days) as the "why" layer,    */
/* snapshot closes (memory/snapshots/*.json) for T+1 verdicts.         */
/* ------------------------------------------------------------------ */

const SNAPSHOT_PATTERN = /^(\d{4}-\d{2}-\d{2})\.json$/

/**
 * Ordering key for ISO dates (no Date TZ pitfalls). Monotonic, so it is safe
 * for `<`/`>` comparison and sorting — but the *difference* between two of
 * these is NOT a day count (2026-08-31 → 2026-09-01 differs by 2, not 1).
 * Use `dayGap` whenever a real distance is needed.
 */
function dayNum(iso: string | null): number | null {
  if (typeof iso !== 'string') return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return null
  return Number(m[1]) * 400 + Number(m[2]) * 32 + Number(m[3])
}

/** UTC midnight epoch for an ISO date, for real calendar-day arithmetic. */
function utcDay(iso: string | null): number | null {
  if (typeof iso !== 'string') return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return null
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
}

/** Signed calendar-day distance `to - from`; null when either side is unparseable. */
export function dayGap(from: string | null, to: string | null): number | null {
  const a = utcDay(from)
  const b = utcDay(to)
  if (a === null || b === null) return null
  return Math.round((b - a) / 86_400_000)
}

/**
 * How far after a fill a close may sit and still be called "T+1".
 * A Friday fill settles against Monday (3 calendar days); one intervening
 * public holiday makes 4. Anything beyond that is a different horizon and
 * must not be labelled T+1 — see the snapshot-coverage note on `futureClose`.
 */
export const T1_MAX_GAP_DAYS = 4

/**
 * Shared dead zone for T+1 readings: a move smaller than this reads as flat
 * for every action. Host-side single source of truth so the chip, the trace
 * node and the verdict text can never disagree (they used to: three separate
 * thresholds coloured the same fill two different ways).
 */
export const T1_FLAT_BAND_PCT = 1

/** Actions that reduce a position — a rising price is bad news for these. */
const SELL_ACTIONS = new Set(['sell', 'cut', 'trim', 'trim_on_rebound'])

export function isSellAction(action: string): boolean {
  return SELL_ACTIONS.has(action)
}

/** Good/bad/flat reading of a T+1 move, action-aware and dead-zoned. */
export function t1ToneOf(action: string, delta: number): 'win' | 'loss' | 'flat' {
  if (Math.abs(delta) < T1_FLAT_BAND_PCT) return 'flat'
  const up = delta > 0
  return isSellAction(action) ? (up ? 'loss' : 'win') : (up ? 'win' : 'loss')
}

/** Chinese verdict text for a T+1 move, on the same dead zone as `t1ToneOf`. */
export function t1VerdictOf(action: string, delta: number): string {
  if (Math.abs(delta) < T1_FLAT_BAND_PCT) return '持平'
  const up = delta > 0
  return isSellAction(action) ? (up ? '卖飞' : '卖对') : (up ? '涨' : '跌')
}

/**
 * Price lookup per ticker across daily snapshots: { ticker: { date: price } }.
 * Snapshots carry `current_price` per holding; the newest day with a price
 * after a trade date is its T+1 close.
 */
export function readSnapshotPrices(workspace: string): Record<string, Record<string, number>> {
  const byTicker: Record<string, Record<string, number>> = {}
  let files: string[] = []
  try {
    files = readdirSync(join(workspace, 'memory', 'snapshots'))
  } catch {
    return byTicker
  }
  for (const name of files) {
    const m = SNAPSHOT_PATTERN.exec(name)
    if (!m) continue
    const doc = readJson(join(workspace, 'memory', 'snapshots', name))
    if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) continue
    const portfolios = (doc as { portfolios?: unknown })['portfolios']
    if (portfolios === null || typeof portfolios !== 'object' || Array.isArray(portfolios)) continue
    for (const book of Object.values(portfolios as Record<string, unknown>)) {
      if (book === null || typeof book !== 'object' || Array.isArray(book)) continue
      const holdings = (book as { holdings?: unknown })['holdings']
      if (!Array.isArray(holdings)) continue
      for (const h of holdings) {
        if (h === null || typeof h !== 'object') continue
        const hObj = h as { ticker?: unknown; current_price?: unknown }
        const ticker = hObj['ticker']
        const price = hObj['current_price']
        if (typeof ticker === 'string' && typeof price === 'number') {
          byTicker[ticker] ??= {}
          byTicker[ticker]![m[1]!] = price
        }
      }
    }
  }
  return byTicker
}

/**
 * The n-th snapshot close strictly after `date` for `ticker` — but only when
 * it actually lands inside `maxGapDays` calendar days of the fill.
 *
 * The snapshot series is not a trading calendar: it starts the day the desk
 * began writing `memory/snapshots/`, and it has holes whenever the daily job
 * missed a run. Without the gap ceiling this function happily returns "the
 * next close we happen to own", which for fills predating the series is
 * months later — those were being rendered under a literal "T+1" label. A
 * horizon we cannot actually observe must read as unknown, not as a verdict.
 */
function futureClose(
  byTicker: Record<string, Record<string, number>>,
  ticker: string,
  date: string | null,
  n: number,
  maxGapDays: number = T1_MAX_GAP_DAYS,
): { date: string; price: number } | null {
  const days = byTicker[ticker]
  if (!days) return null
  const base = dayNum(date)
  if (base === null) return null
  const later = Object.keys(days).filter((d) => (dayNum(d) ?? 0) > base).sort()
  const hit = later[n - 1]
  if (hit === undefined) return null
  const gap = dayGap(date, hit)
  if (gap === null || gap > maxGapDays) return null
  return { date: hit, price: days[hit]! }
}

/** One real fill, enriched for the trace view. */
function enrichTrade(
  trade: Trade,
  byTicker: Record<string, Record<string, number>>,
  decByTicker: Record<string, DecisionRow[]>,
  books: Book[],
): EnrichedTrade {
  const out = { ...trade, holdPnl: null, t1: null, decision: null } as EnrichedTrade
  // T+1 reading: tone and verdict both come from the shared dead zone in
  // `t1ToneOf`/`t1VerdictOf`, so the chip, the trace node and the text can
  // never disagree about the same fill.
  const t1 = futureClose(byTicker, trade.ticker, trade.date, 1)
  if (t1 !== null && trade.price != null) {
    const delta = Math.round(((t1.price - trade.price) / trade.price) * 100 * 100) / 100
    out.t1 = {
      date: t1.date,
      price: Math.round(t1.price * 100) / 100,
      delta,
      verdict: t1VerdictOf(trade.action, delta),
      tone: t1ToneOf(trade.action, delta),
    } satisfies TraceT1
  }
  // Soft-pair the decision ledger: same ticker, plan date within ±3 *calendar*
  // days. Indexed by ticker so this stays O(decisions for this ticker) instead
  // of rescanning every ledger key for every fill.
  let best: JsonValue | null = null
  let bestDiff = Number.POSITIVE_INFINITY
  for (const row of decByTicker[trade.ticker] ?? []) {
    const gap = dayGap(row.date, trade.date)
    if (gap === null) continue
    const diff = Math.abs(gap)
    if (diff <= 3 && diff < bestDiff) {
      best = row.entry
      bestDiff = diff
    }
  }
  if (best !== null && typeof best === 'object' && !Array.isArray(best)) {
    const b = best as { [key: string]: unknown }
    const mind = (b['mind'] ?? {}) as { [key: string]: unknown }
    const emotion = (b['emotion'] ?? {}) as { [key: string]: unknown }
    const size = (b['size'] ?? {}) as { [key: string]: unknown }
    const evaluation = (b['evaluation'] ?? {}) as { [key: string]: unknown }
    const bull = (mind['bull'] ?? {}) as { [key: string]: unknown }
    const bear = (mind['bear'] ?? {}) as { [key: string]: unknown }
    const execution = (b['execution'] ?? {}) as { [key: string]: unknown }
    const condition = (b['condition'] ?? {}) as { [key: string]: unknown }
    const planDate = typeof b['plan_date'] === 'string'
      ? b['plan_date']
      : (typeof b['decided_at'] === 'string' ? b['decided_at'].slice(0, 10) : null)
    const decision: TraceDecision = {
      planDate: planDate as string | null,
      action: typeof b['action'] === 'string' ? b['action'] : null,
      confidence: b['confidence'] == null ? null : Number(b['confidence']),
      drivenBy: typeof b['driven_by'] === 'string' ? b['driven_by'] : null,
      rationale: typeof b['rationale'] === 'string' ? b['rationale'] : null,
      bull: typeof bull['summary'] === 'string' ? bull['summary'] : null,
      bear: typeof bear['summary'] === 'string' ? bear['summary'] : null,
      emotion: typeof emotion['pressure'] === 'string' ? emotion['pressure'] : null,
      emotionNote: typeof emotion['note'] === 'string' ? emotion['note'] : null,
      execution: typeof execution['status'] === 'string' ? execution['status'] : null,
      condition: typeof condition['description'] === 'string' ? condition['description'] : null,
      sizeShares: size['shares'] == null ? null : Number(size['shares']),
      sizePct: size['pct'] == null ? null : Number(size['pct']),
      plannedPrice: evaluation['execution_price'] != null ? Number(evaluation['execution_price'])
        : (b['simulated_entry_price'] != null ? Number(b['simulated_entry_price']) : null),
      source: typeof b['source'] === 'string' ? b['source'] : 'brief',
    }
    out.decision = decision
  }
  // Current position P&L (live data) for still-held tickers.
  const held = books.find((bk) => bk.holdings.some((h) => h.ticker === trade.ticker))
  const row = held?.holdings.find((h) => h.ticker === trade.ticker)
  if (row) out.holdPnl = row.pnlPct
  return out
}

/**
 * The decision trace data: every real fill as a trace node with its
 * soft-paired decision and T+1 verdict, newest first. This is the organic
 * view the plugin shows — one list, one spine (real fills), decisions as
 * the "why" layer, no parallel tabs.
 * @param workspace - desk workspace root.
 * @returns `{ trades, rate, rateSource, lastUpdated }` — `trades` is the
 *          enriched fill list; `rate` is the USD/HKD FX rate when the desk
 *          published one in portfolio.json market_context (else null).
 */
export function readTraces(workspace: string): Omit<TracesResult, 'workspaceKey' | 'signature'> {
  const { books, trades, lastUpdated, marketContext } = readPortfolio(workspace)
  const byTicker = readSnapshotPrices(workspace)
  const decByKey: Record<string, JsonValue[]> = {}
  const { entries } = readLedger(workspace)
  for (const e of entries) {
    if (e === null || typeof e !== 'object' || Array.isArray(e)) continue
    const eObj = e as { [key: string]: unknown }
    const subject = eObj['subject'] as { ticker?: unknown } | null | undefined
    const tk = typeof eObj['ticker'] === 'string'
      ? eObj['ticker']
      : (subject !== null && subject !== undefined && typeof subject['ticker'] === 'string' ? subject['ticker'] : undefined)
    const dt = typeof eObj['plan_date'] === 'string'
      ? eObj['plan_date']
      : (typeof eObj['decided_at'] === 'string' ? eObj['decided_at'].slice(0, 10) : undefined)
    if (typeof tk !== 'string' || typeof dt !== 'string' || !dt) continue
    decByKey[tk + ':' + dt] ??= []
    decByKey[tk + ':' + dt]!.push(e)
  }
  // Flatten `ticker:date` keys into a per-ticker index, keeping the previous
  // semantics exactly: the last ledger row wins for a given ticker+date, and
  // among equally-distant dates the earliest-seen one wins.
  const decByTicker: Record<string, DecisionRow[]> = {}
  for (const [key, rows] of Object.entries(decByKey)) {
    const sep = key.lastIndexOf(':')
    const ticker = key.slice(0, sep)
    const entry = rows[rows.length - 1]
    if (entry === undefined) continue
    ;(decByTicker[ticker] ??= []).push({ date: key.slice(sep + 1), entry })
  }
  const enriched = trades.map((t) => enrichTrade(t, byTicker, decByTicker, books))
  const rate = typeof marketContext['usdhk_rate'] === 'number' ? marketContext['usdhk_rate'] : null
  return {
    trades: enriched,
    rate,
    rateSource: typeof marketContext['usdhk_source'] === 'string' ? marketContext['usdhk_source'] : null,
    lastUpdated,
  }
}
