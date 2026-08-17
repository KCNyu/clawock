/**
 * Read-only readers over the OpenClaw desk's produced data: the shared
 * decision ledger, the portfolio, and recent daily plans. Pure Node, no
 * Cordis/typert dependencies — unit-testable in isolation.
 *
 * These are the files the OpenClaw runtime produces every day, so whatever
 * OpenClaw writes, this DSH plugin can show.
 */
import type { LedgerResult, PlansResult, PortfolioRead, TracesResult } from './types.ts';
/**
 * Parse the decision ledger (memory/decisions.jsonl) — one JSON object per
 * line. Malformed lines are skipped, never fatal: the desk's own writer
 * round-trips the file and this view must survive any of its states.
 * @param workspace - desk workspace root.
 * @returns `{ entries, path }`; entries are in file order (oldest first).
 */
export declare function readLedger(workspace: string): LedgerResult;
/**
 * Summarize the portfolio (portfolio.json): per-book holdings with the desk's
 * own money fields, plus the flattened trade log (newest first).
 * @param workspace - desk workspace root.
 * @returns `{ books, trades, lastUpdated }`.
 */
export declare function readPortfolio(workspace: string): PortfolioRead;
/**
 * List recent daily plans (memory/YYYY-MM-DD-plan.json), newest first.
 * @param workspace - desk workspace root.
 * @param limit - how many plans to return.
 */
export declare function readPlans(workspace: string, limit?: number): PlansResult;
/** Signed calendar-day distance `to - from`; null when either side is unparseable. */
export declare function dayGap(from: string | null, to: string | null): number | null;
/**
 * How far after a fill a close may sit and still be called "T+1".
 * A Friday fill settles against Monday (3 calendar days); one intervening
 * public holiday makes 4. Anything beyond that is a different horizon and
 * must not be labelled T+1 — see the snapshot-coverage note on `futureClose`.
 */
export declare const T1_MAX_GAP_DAYS = 4;
/**
 * Shared dead zone for T+1 readings: a move smaller than this reads as flat
 * for every action. Host-side single source of truth so the chip, the trace
 * node and the verdict text can never disagree (they used to: three separate
 * thresholds coloured the same fill two different ways).
 */
export declare const T1_FLAT_BAND_PCT = 1;
export declare function isSellAction(action: string): boolean;
/**
 * 'same' | 'opposite' | 'other' — the plan's direction against the fill's.
 *
 * Mirrors `_plan_fill_alignment` in src/clawock/publish/dashboard.py; the two
 * implementations are pinned together by tests/test_decision_trace_parity.py.
 */
export declare function planFillAlignment(planAction: string | null | undefined, fillAction: string | null | undefined): 'same' | 'opposite' | 'other' | null;
/**
 * A rationale fit for a reader: the risk engine's internal breach ids stripped.
 *
 * The raw field carries things like "硬止损 -27.23% ≤ -18% (breach
 * risk-95ac7f6cd591 30d)" — the hash says nothing to anyone outside the
 * process, and it is sitting in the one field a reader opens to understand
 * *why*. Mirrors `_readable_rationale` in dashboard.py, minus the 140-char
 * truncation: that exists to fit a published payload cap, which this panel
 * (reading the workspace at runtime) does not have.
 */
export declare function readableRationale(text: string | null | undefined): string | null;
/** Good/bad/flat reading of a T+1 move, action-aware and dead-zoned. */
export declare function t1ToneOf(action: string, delta: number): 'win' | 'loss' | 'flat';
/** Chinese verdict text for a T+1 move, on the same dead zone as `t1ToneOf`. */
export declare function t1VerdictOf(action: string, delta: number): string;
/**
 * Session close per ticker from the canonical bar store: { ticker: { date: close } }.
 *
 * Reads `memory/bars/<ticker>.json`, the same store the Python settlement path
 * uses — deliberately NOT `memory/snapshots/*.json`.
 *
 * A snapshot is a *portfolio* file whose `current_price` carries the vintage of
 * whichever cron happened to write it. `src/clawock/market_data/bars.py`
 * measured it on 00100 across 15 snapshots: the previous close 7 times, that
 * day's close 3 times, an intraday print 5 times. Worse, the field is carried
 * forward once a position is closed — NVDA sat at a frozen 213 for five
 * straight sessions while its real closes ran 222.32 / 220.61 / 223.47 /
 * 219.51 / 215.33. Settlement migrated off snapshots for exactly this reason;
 * this view stayed behind and marked 82% of its T+1 deltas against a price the
 * rest of the system had already disowned, flipping 10 verdicts outright.
 *
 * Bars are session-dated, unadjusted, and never contain an unfinished session,
 * so a close read here is the same number the ledger settles against. Only the
 * tickers actually traded are read, which is also why this is cheaper than the
 * full snapshot scan it replaces.
 *
 * @param workspace - desk workspace root.
 * @param tickers - the tickers to load; anything else on disk is not read.
 */
export declare function readBarCloses(workspace: string, tickers: Iterable<string>): Record<string, Record<string, number>>;
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
export declare function readTraces(workspace: string): Omit<TracesResult, 'workspaceKey' | 'signature'>;
