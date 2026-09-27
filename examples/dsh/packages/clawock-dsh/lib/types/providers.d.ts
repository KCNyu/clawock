/**
 * The provider panel's join table (2026-09-27): which balance provider pays
 * for which dispatch agent, what kind of allowance it is, and where its key
 * comes from. Declarative, no runtime imports, so the host and the client
 * bundle read the same rows.
 *
 * Adding a provider stays one row in index.ts's BALANCE_PROVIDERS (its
 * service): a provider without a row here still renders, after the agents,
 * under its own label. A row here only adds what the balance answer cannot
 * say by itself — the agent whose queue hangs under it, and the plan caption.
 * An agent with no provider (opencode's free pool) is a row with
 * `provider: null`. The chip names nothing else: order and captions come
 * from here and from BALANCE_PROVIDERS' order.
 */
export interface ProviderJoin {
    /** BALANCE_PROVIDERS id, or null for an agent no provider bills (a free pool). */
    provider: string | null;
    /** The dispatch agent (agent-dispatch AGENT=) this allowance feeds, or null. */
    agent: string | null;
    /** What the allowance is: 'windows' (5h + week quota), 'money' (a balance), 'pool' (free rotation, no windows). */
    kind: 'windows' | 'money' | 'pool';
    /** Dictionary key of the caption under the group title ("Anthropic subscription", …). */
    plan: string;
    /** Dictionary key of the short source label a row without an agent shows in its last column. */
    source?: string;
}
/** Rows with an agent first, in the order the panel lists them; the rest follow BALANCE_PROVIDERS. */
export declare const PROVIDER_JOIN: readonly ProviderJoin[];
