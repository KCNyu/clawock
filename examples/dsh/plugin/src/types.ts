/**
 * Remote wire types for the clawock-dsh Typert face. Every type here is
 * JSON-representable and within the generator's Zod subset: plain objects,
 * arrays, primitives, unions, and the recursive JsonValue for the ledger's
 * heterogeneous records.
 */

/** JSON-compatible recursive value — the decisions.jsonl records are heterogeneous. */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

export interface RunRow {
  runId: string
  subject: string | null
  decisionSubject: string | null
  decisionAction: string | null
  asOf: string | null
  task: string | null
  workflow: JsonValue | null
  gates: JsonValue | null
  documentCount: number
  decisionPresent: boolean
  receiptPresent: boolean
  mtimeMs: number
}

export interface ListRunsResult {
  runs: RunRow[]
}

export interface RunDetailResult {
  runId: string
  request: JsonValue | null
  decision: JsonValue | null
  manifest: JsonValue | null
}

export interface LedgerResult {
  entries: JsonValue[]
  path: string
}

export interface Holding {
  ticker: string
  shares: number
  cost: number | null
  price: number | null
  pnlPct: number | null
  pnlAbs: number | null
}

export interface Trade {
  ticker: string
  market: string
  currency: string
  date: string | null
  action: string
  shares: number
  price: number | null
  realizedPnl: number | null
  note: string | null
}

export interface Book {
  name: string
  currency: string | null
  truePrincipal: number | null
  holdings: Holding[]
}

export interface PortfolioResult {
  books: Book[]
  trades: Trade[]
  lastUpdated: string | null
}

export interface PlanRow {
  date: string
  decisions: number
  title: string | null
}

export interface PlansResult {
  plans: PlanRow[]
}

export interface TraceT1 {
  date: string
  price: number
  delta: number
  verdict: string
}

export interface TraceDecision {
  planDate: string | null
  action: string | null
  confidence: number | null
  drivenBy: string | null
  rationale: string | null
  bull: string | null
  bear: string | null
  emotion: string | null
  emotionNote: string | null
  execution: string | null
  condition: string | null
  sizeShares: number | null
  sizePct: number | null
  plannedPrice: number | null
  source: string | null
}

export interface EnrichedTrade extends Trade {
  holdPnl: number | null
  t1: TraceT1 | null
  decision: TraceDecision | null
}

export interface TracesResult {
  workspaceKey: string
  signature: string
  trades: EnrichedTrade[]
  rate: number | null
  rateSource: string | null
  lastUpdated: string | null
}
