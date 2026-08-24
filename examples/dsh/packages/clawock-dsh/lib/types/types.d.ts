/**
 * Remote wire types for the clawock-dsh Typert face. Every type here is
 * JSON-representable and within the generator's Zod subset: plain objects,
 * arrays, primitives, unions, and the recursive JsonValue for the ledger's
 * heterogeneous records.
 */
/** JSON-compatible recursive value — the decisions.jsonl records are heterogeneous. */
export type JsonValue = string | number | boolean | null | JsonValue[] | {
    [key: string]: JsonValue;
};
export interface RunRow {
    runId: string;
    subject: string | null;
    decisionSubject: string | null;
    decisionAction: string | null;
    asOf: string | null;
    task: string | null;
    workflow: JsonValue | null;
    gates: JsonValue | null;
    documentCount: number;
    decisionPresent: boolean;
    receiptPresent: boolean;
    mtimeMs: number;
}
export interface ListRunsResult {
    runs: RunRow[];
}
export interface RunDetailResult {
    runId: string;
    request: JsonValue | null;
    decision: JsonValue | null;
    manifest: JsonValue | null;
}
export interface LedgerResult {
    entries: JsonValue[];
    path: string;
}
export interface Holding {
    ticker: string;
    shares: number;
    cost: number | null;
    price: number | null;
    pnlPct: number | null;
    pnlAbs: number | null;
}
export interface Trade {
    ticker: string;
    market: string;
    currency: string;
    date: string | null;
    action: string;
    shares: number;
    price: number | null;
    realizedPnl: number | null;
    note: string | null;
}
export interface Book {
    name: string;
    currency: string | null;
    truePrincipal: number | null;
    holdings: Holding[];
}
export interface PortfolioResult {
    books: Book[];
    trades: Trade[];
    lastUpdated: string | null;
}
/** One decision-ledger row indexed for soft pairing, with its plan date. */
export interface DecisionRow {
    date: string;
    entry: JsonValue;
}
export interface PlanRow {
    date: string;
    decisions: number;
    title: string | null;
}
export interface PlansResult {
    plans: PlanRow[];
}
export interface TraceT1 {
    date: string;
    price: number;
    delta: number;
    /** '涨' | '跌' | '卖飞' | '卖对' | '持平' — same dead zone as `tone`. */
    verdict: string;
    /**
     * Good/bad/flat reading, decided host-side so the chip and the trace node
     * cannot colour the same fill differently. Renderers must not re-derive it.
     */
    tone: 'win' | 'loss' | 'flat';
}
export interface TraceDecision {
    planDate: string | null;
    action: string | null;
    confidence: number | null;
    drivenBy: string | null;
    rationale: string | null;
    bull: string | null;
    bear: string | null;
    emotion: string | null;
    emotionNote: string | null;
    execution: string | null;
    condition: string | null;
    sizeShares: number | null;
    sizePct: number | null;
    plannedPrice: number | null;
    source: string | null;
    /**
     * How the plan's direction relates to the fill that actually happened.
     * 'same' | 'opposite' | 'other' (the plan pointed at neither side), or null
     * when either action is missing.
     *
     * Load-bearing, not decorative: on live data 22 of 40 traces were outright
     * reversals of their own plan, and the panel showed nothing about it — the
     * reader had to infer "risk said cut, I bought" from two adjacent lines.
     * `execution.status` does NOT answer this: it is the plan's own self-report
     * and stays available separately as 账本自评.
     */
    alignment: 'same' | 'opposite' | 'other' | null;
}
export interface EnrichedTrade extends Trade {
    holdPnl: number | null;
    t1: TraceT1 | null;
    decision: TraceDecision | null;
    /**
     * What this fill did to the position, decided host-side by `isSellAction`.
     *
     * Shipped so the browser half never keeps its own copy of the action set: the
     * client used to test `action === 'sell'`, which silently dropped the verdict
     * for cut / trim / trim_on_rebound, and a second copy of that set is how the
     * two implementations drifted in #739. Null means the action is in neither
     * bucket — the fill is kept out of both sides rather than guessed into one.
     */
    side: 'add' | 'reduce' | null;
}
export interface TracesResult {
    workspaceKey: string;
    signature: string;
    trades: EnrichedTrade[];
    rate: number | null;
    rateSource: string | null;
    lastUpdated: string | null;
}
/** One quota window worth its own line in the panel's per-window grid. */
export interface BalanceWindow {
    /** Short label rendered verbatim: '5h' | '周' | '会话' | '本周'. */
    label: string;
    /** Remaining percent of this window; null when the plan doesn't report it. */
    percent: number | null;
    /** Preformatted LOCAL reset stamp ('15:00' / '周四 21:00'); '' when unknown. */
    resetAt: string;
}
/**
 * One account/quota reading as answered by the provider's official endpoint,
 * with the entry the host picked to display. Numeric readings stay strings so
 * no rounding happens on the wire; the client formats for display only.
 */
export interface BalanceSnapshot {
    /** Whether the API reports the account usable (sufficient balance / quota left). */
    isAvailable: boolean;
    /**
     * How `totalBalance` reads: 'money' carries a currency symbol via
     * `currency` ('CNY' | 'USD' | ''), 'pct' carries a remaining-percent number
     * (quota windows). '' defaults to 'money'.
     */
    unit: string;
    /** 'CNY' | 'USD' | '' — the displayed entry's currency (money unit only). */
    currency: string;
    /** Total available balance ("110.00") or remaining percent ("62"). */
    totalBalance: string;
    /** Not-expired granted balance (DeepSeek money accounts; '' elsewhere). */
    grantedBalance: string;
    /** Topped-up balance (DeepSeek money accounts; '' elsewhere). */
    toppedUpBalance: string;
    /** ISO timestamp of the upstream fetch that produced this snapshot. */
    asOf: string;
    /** One context line for the panel (quota windows, resets); '' when none. */
    note: string;
    /** Per-window grid for the panel; money accounts send []. */
    windows: BalanceWindow[];
}
/** One provider's row in the balance panel: identity plus the same in-band answer. */
export interface ProviderBalance {
    /** Stable id: 'deepseek' | 'minimax'. */
    provider: string;
    /** Human label rendered verbatim ('DeepSeek', 'MiniMax'). */
    label: string;
    result: BalanceResult;
}
/**
 * The whole balance answer across providers. In-band by design: balance()
 * never throws — per-provider 'no-key' / 'failed' / 'stale' statuses carry a
 * Chinese message the view renders verbatim, and a stale read keeps the last
 * good snapshot so a transient 429 cannot erase a real number.
 */
export interface BalancesResult {
    /** Rows in stable display order (deepseek first). */
    providers: ProviderBalance[];
    /** Suggested client poll interval in ms. */
    refreshMs: number;
}
/** One provider's answer. Same in-band contract the single-provider box had. */
export interface BalanceResult {
    /** Whether this provider's API key is configured at all (seam or env). */
    configured: boolean;
    /** Last good snapshot, kept across failed refreshes (null on cold start). */
    snapshot: BalanceSnapshot | null;
    /** 'fresh' | 'cached' | 'stale' | 'failed' | 'no-key' — decided host-side. */
    status: 'fresh' | 'cached' | 'stale' | 'failed' | 'no-key';
    /** Balance/quota at or below the low threshold (only when readable). */
    low: boolean;
    /** Human-readable reason for failed/no-key, null while good. */
    message: string | null;
    /** Effective low threshold, in the displayed entry's unit. */
    threshold: number;
    /** Suggested client poll interval in ms. */
    refreshMs: number;
}
