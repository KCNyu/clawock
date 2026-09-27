/**
 * The provider panel's join table (2026-09-27): which balance provider pays
 * for which dispatch agent, what kind of allowance it is, and where its key
 * comes from. Declarative, no runtime imports, so the host and the client
 * bundle read the same rows.
 *
 * Adding a provider stays one row in index.ts's BALANCE_PROVIDERS (its
 * service): a provider without a row here still renders, under its own
 * label, among the paid rows (see sourceRank). A row here only adds what the
 * balance answer cannot say by itself — the agent whose queue hangs under it,
 * the plan caption, and its place in the order. An agent with no provider
 * (opencode's free pool) is a row with `provider: null`. The chip names
 * nothing else: every order the panel shows (the folded lines, the groups,
 * the lanes, what just ended) comes from here.
 */
export interface ProviderJoin {
    /** BALANCE_PROVIDERS id, or null for an agent no provider bills (a free pool). */
    provider: string | null;
    /** The dispatch agent (agent-dispatch AGENT=) this allowance feeds, or null. */
    agent: string | null;
    /** What the allowance is: 'windows' (5h + week quota), 'money' (a balance), 'pool' (free rotation, no windows). */
    kind: 'windows' | 'money' | 'pool';
    /**
     * What spending it costs: 'paid' (a subscription's windows or a balance —
     * scarce, each one its own) or 'free' (a pool of free models that stand in
     * for one another). The order's one criterion; not how capable the agent is.
     */
    tier: 'paid' | 'free';
    /** Dictionary key of the caption under the group title ("Anthropic subscription", …). */
    plan: string;
    /** Dictionary key of the short source label a row without an agent shows in its last column. */
    source?: string;
}
/**
 * Rows in the order the panel lists them (kcn, 2026-09-27): the paid,
 * exclusive allowances first — the two subscriptions, then the balance and
 * the token plan — and the free pool last. opencode sits low not because it
 * is weaker but because it is free and interchangeable: its models replace
 * one another inside the pool, so it is one line for the whole pool, never a
 * line per model.
 */
export declare const PROVIDER_JOIN: readonly ProviderJoin[];
/**
 * A source's place: its row's index, times two. A provider or agent without a
 * row costs an unknown amount, so it is treated as scarce: after the known
 * paid rows, before the free ones (the odd slot between them).
 */
export declare function sourceRank(key: {
    provider?: string | null;
    agent?: string | null;
}): number;
/** Items that belong to an agent (tasks, slot lanes) in the panel's order; stable, so newest-first stays newest-first within an agent. */
export declare function byAgentRank<T extends {
    agent: string;
}>(items: readonly T[]): T[];
