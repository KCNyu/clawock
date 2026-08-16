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

const PLAN_PATTERN = /^(\d{4}-\d{2}-\d{2})-plan\.json$/

function readJson(path) {
  if (!existsSync(path)) return null
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
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
export function readLedger(workspace) {
  const path = join(workspace, 'memory', 'decisions.jsonl')
  const entries = []
  if (existsSync(path)) {
    const lines = readFileSync(path, 'utf8').split('\n')
    for (const line of lines) {
      if (!line.trim()) continue
      try {
        entries.push(JSON.parse(line))
      } catch {
        /* skip one malformed line */
      }
    }
  }
  return { entries, path }
}

/**
 * Summarize the portfolio (portfolio.json): per-book holdings with the desk's
 * own money fields and totals.
 * @param workspace - desk workspace root.
 * @returns `{ books, lastUpdated }`; books with no positive holdings are kept
 *          (a zeroed book is still information).
 */
export function readPortfolio(workspace) {
  const doc = readJson(join(workspace, 'portfolio.json'))
  if (doc === null) return { books: [], lastUpdated: null }
  const books = []
  const trades = []
  const portfolios = doc.portfolios ?? {}
  for (const [name, book] of Object.entries(portfolios)) {
    if (book === null || typeof book !== 'object' || !Array.isArray(book.holdings)) continue
    const rawHoldings = book.holdings.filter((h) => h !== null && typeof h === 'object')
    const holdings = rawHoldings
      .filter((h) => (h.shares ?? h.quantity ?? 0) > 0) // zero-share rows are not positions
      .map((h) => ({
        ticker: h.ticker ?? h.stock_name ?? h.name ?? '?',
        shares: h.shares ?? h.quantity ?? 0,
        cost: h.cost_basis ?? null,
        price: h.current_price ?? null,
        pnlPct: h.pnl_percent ?? null,
        pnlAbs: h.pnl_abs ?? null,
      }))
    if (holdings.length === 0) continue // a book with no positions is not shown
    books.push({
      name,
      currency: book.currency ?? null,
      truePrincipal: book.true_principal ?? null,
      holdings,
    })
    // Actual operations: every recorded trade across all holdings, newest
    // first. This is the "what did I actually do" surface — real fills with
    // notes and realized P&L, not plan simulations. Trades come from the raw
    // holdings (the summary rows above drop the trades field on purpose).
    const market = /^hk/i.test(name) ? 'HK' : 'US'
    const currency = book.currency ?? (market === 'HK' ? 'HKD' : 'USD')
    for (const holding of rawHoldings) {
      const rawTrades = holding.trades ?? []
      for (const tr of rawTrades) {
        if (tr === null || typeof tr !== 'object') continue
        trades.push({
          ticker: holding.ticker ?? holding.stock_name ?? holding.name ?? '?',
          market,
          currency,
          date: tr.date ?? null,
          action: tr.action ?? 'buy',
          shares: tr.shares ?? 0,
          price: tr.price ?? null,
          realizedPnl: tr.realized_pnl ?? null,
          note: typeof tr.note === 'string' ? tr.note : null,
        })
      }
    }
  }
  trades.sort((a, b) => ((a.date ?? '') < (b.date ?? '') ? 1 : -1))
  return { books, trades, lastUpdated: doc.last_updated ?? null }
}

/**
 * List recent daily plans (memory/YYYY-MM-DD-plan.json), newest first.
 * @param workspace - desk workspace root.
 * @param limit - how many plans to return.
 * @returns `{ plans }` with date and decision count per plan.
 */
export function readPlans(workspace, limit = 14) {
  const plans = []
  let files = []
  try {
    files = readdirSync(join(workspace, 'memory'))
  } catch {
    return { plans }
  }
  const dated = files
    .map((name) => PLAN_PATTERN.exec(name))
    .filter(Boolean)
    .map((m) => ({ date: m[1], name: m[0] }))
    .sort((a, b) => (a.date < b.date ? 1 : -1))
    .slice(0, limit)
  for (const file of dated) {
    const doc = readJson(join(workspace, 'memory', file.name))
    if (doc === null) continue
    plans.push({
      date: file.date,
      decisions: Array.isArray(doc.decisions) ? doc.decisions.length : 0,
      title: doc.title ?? null,
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

/** Day number for window arithmetic (no Date TZ pitfalls for ISO dates). */
function dayNum(iso) {
  if (typeof iso !== 'string') return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return null
  return Number(m[1]) * 400 + Number(m[2]) * 32 + Number(m[3])
}

/**
 * Price lookup per ticker across daily snapshots: { ticker: { date: price } }.
 * Snapshots carry `current_price` per holding; the newest day with a price
 * after a trade date is its T+1 close.
 */
function readSnapshotPrices(workspace) {
  const byTicker = {}
  let files = []
  try {
    files = readdirSync(join(workspace, 'memory', 'snapshots'))
  } catch {
    return byTicker
  }
  for (const name of files) {
    const m = SNAPSHOT_PATTERN.exec(name)
    if (!m) continue
    const doc = readJson(join(workspace, 'memory', 'snapshots', name))
    if (doc === null) continue
    const portfolios = doc.portfolios ?? {}
    for (const book of Object.values(portfolios)) {
      if (book === null || typeof book !== 'object') continue
      const holdings = Array.isArray(book.holdings) ? book.holdings : []
      for (const h of holdings) {
        if (h === null || typeof h !== 'object') continue
        const ticker = h.ticker
        const price = h.current_price
        if (typeof ticker === 'string' && typeof price === 'number') {
          byTicker[ticker] ??= {}
          byTicker[ticker][m[1]] = price
        }
      }
    }
  }
  return byTicker
}

/** First close at least `n` trading days after `date` for `ticker`. */
function futureClose(byTicker, ticker, date, n) {
  const days = byTicker[ticker]
  if (!days) return null
  const base = dayNum(date)
  if (base === null) return null
  const later = Object.keys(days).filter((d) => dayNum(d) > base).sort()
  const hit = later[n - 1]
  if (hit === undefined) return null
  return { date: hit, price: days[hit] }
}

/**
 * One real fill, enriched for the trace view: the soft-paired decision
 * (same ticker within ±3 days) and the T+1 close verdict.
 */
function enrichTrade(trade, byTicker, decByKey, books) {
  const out = { ...trade }
  // T+1 verdict: sell verdicts read "卖飞/卖对", buys read "涨/跌".
  const t1 = futureClose(byTicker, trade.ticker, trade.date, 1)
  if (t1 !== null && trade.price) {
    const delta = ((t1.price - trade.price) / trade.price) * 100
    out.t1 = {
      date: t1.date,
      price: Math.round(t1.price * 100) / 100,
      delta: Math.round(delta * 100) / 100,
      verdict: trade.action === 'sell' ? (delta > 1 ? '卖飞' : delta < -1 ? '卖对' : '持平') : (delta > 0 ? '涨' : '跌'),
    }
  }
  // Soft-pair the decision ledger: same ticker, plan date within ±3 days.
  const key = (tk) => Object.keys(decByKey).filter((k) => k.startsWith(tk + ':'))
  let best = null
  let bestDiff = 99
  for (const k of key(trade.ticker)) {
    const dt = k.slice(trade.ticker.length + 1)
    const diff = Math.abs(dayNum(dt) - dayNum(trade.date))
    if (diff <= 3 && diff < bestDiff) {
      const rows = decByKey[k]
      best = rows[rows.length - 1]
      bestDiff = diff
    }
  }
  if (best) {
    const subject = best.subject ?? {}
    const mind = best.mind ?? {}
    const emotion = best.emotion ?? {}
    const size = best.size ?? {}
    const evaluation = best.evaluation ?? {}
    out.decision = {
      planDate: best.plan_date ?? (best.decided_at ?? '').slice(0, 10) ?? null,
      action: best.action ?? null,
      confidence: best.confidence ?? null,
      drivenBy: best.driven_by ?? null,
      rationale: typeof best.rationale === 'string' ? best.rationale : null,
      thesis: mind.thesis ?? null,
      invalidation: Array.isArray(mind.invalidation) ? mind.invalidation : [],
      bull: (mind.bull ?? {}).summary ?? null,
      bear: (mind.bear ?? {}).summary ?? null,
      emotion: emotion.pressure ?? null,
      emotionNote: emotion.note ?? null,
      execution: (best.execution ?? {}).status ?? null,
      condition: (best.condition ?? {}).description ?? null,
      sizeShares: size.shares ?? null,
      sizePct: size.pct ?? null,
      plannedPrice: evaluation.execution_price ?? best.simulated_entry_price ?? null,
      source: best.source ?? 'brief',
    }
  }
  // Current position P&L (live data) for still-held tickers.
  const held = books.find((b) => b.holdings.some((h) => h.ticker === trade.ticker))
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
export function readTraces(workspace) {
  const { books, trades, lastUpdated } = readPortfolio(workspace)
  const byTicker = readSnapshotPrices(workspace)
  const decByKey = {}
  const { entries } = readLedger(workspace)
  for (const e of entries) {
    const tk = e.ticker ?? (e.subject ?? {}).ticker
    const dt = e.plan_date ?? (e.decided_at ?? '').slice(0, 10)
    if (typeof tk !== 'string' || typeof dt !== 'string' || !dt) continue
    decByKey[tk + ':' + dt] ??= []
    decByKey[tk + ':' + dt].push(e)
  }
  const enriched = trades.map((t) => enrichTrade(t, byTicker, decByKey, books))
  const doc = readJson(join(workspace, 'portfolio.json'))
  const marketContext = doc?.market_context ?? {}
  const rate = typeof marketContext.usdhk_rate === 'number' ? marketContext.usdhk_rate : null
  return { trades: enriched, rate, rateSource: marketContext.usdhk_source ?? null, lastUpdated }
}
