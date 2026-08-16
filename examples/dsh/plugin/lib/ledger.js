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
  const portfolios = doc.portfolios ?? {}
  for (const [name, book] of Object.entries(portfolios)) {
    if (book === null || typeof book !== 'object' || !Array.isArray(book.holdings)) continue
    const holdings = book.holdings
      .filter((h) => h !== null && typeof h === 'object')
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
  }
  return { books, lastUpdated: doc.last_updated ?? null }
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
