/**
 * Read-only Typert Remote gateway over a clawock workspace, powering the
 * Decision Mind conversation-view tab in the DSH web GUI.
 *
 * Official Cordis service plugin: `apply` registers the service through
 * `ctx.plugin` (the profile patch layer inserts the plugin row), `@Remote`
 * decorators mark the Remote face, and the Typert generator emits the Host
 * reflection + client Remote contribution at build time. The workspace root
 * is `$CLAWOCK_WORKSPACE` when set, otherwise the dsh process cwd.
 */
import { TypertRemoteService } from '@deepseek-ai/dsh-typert-protocol';
import type { Context } from '@deepseek-ai/cordis';
import type { BalancesResult, LedgerResult, ListRunsResult, PlansResult, PortfolioResult, RunDetailResult, TracesResult } from './types.ts';
/**
 * Row-level config the profile patch may set (see cordis.patch.yml).
 */
export interface ClawockStudioConfig {
    /** DeepSeek upstream root for the balance chip; /user/balance is appended. */
    balanceBaseUrl?: string;
    /** Red-dot threshold in the displayed entry's currency (CNY/USD units). */
    balanceThreshold?: number;
    /** Suggested client poll interval in ms. */
    balanceRefreshMs?: number;
    /** MiniMax upstream root; /v1/token_plan/remains is appended. */
    minimaxBaseUrl?: string;
    /** Credentials seam reference for the MiniMax key (env fallback same name). */
    minimaxKeyRef?: string;
    /**
     * Red dot watermark in REMAINING terms: warn when MiniMax windows'
     * remaining percent falls to/below this (default 20 = ≥80% used). The
     * chip displays used percent; this field's meaning is unchanged.
     */
    minimaxLowPct?: number;
    /** openclaw gateway config fallback for provider keys (models.providers.*). */
    minimaxOpenclawConfigPath?: string;
    /** Claude Code OAuth credentials file (claudeAiOauth.accessToken). */
    claudeCredentialsPath?: string;
    /** The undocumented /api/oauth/usage endpoint; overridable for tests. */
    claudeUsageUrl?: string;
    /**
     * Red dot watermark in REMAINING terms for the Claude session window
     * (default 20 = ≥80% used); displayed number is used percent.
     */
    claudeLowPct?: number;
}
export declare class ClawockStudioGateway extends TypertRemoteService {
    static inject: readonly ['credentials'];
    /**
     * cordis mixes the injected services onto the instance at construction;
     * this type-only declaration types `this.credentials` without a cast,
     * and `declare` fields emit nothing at runtime.
     */
    /**
     * Signature-keyed trace cache per workspace (see freshness.ts). Owned by the
     * service instance rather than module scope: a module-level cache would
     * outlive plugin stop/update (the module stays in the process cache), so a
     * stopped plugin could keep serving a stale enriched view through a new
     * instance. Instance lifetime follows the fiber; a hit still costs µs.
     */
    private readonly tracesCache;
    /**
     * Per-provider balance services, built lazily on first use — instance-scoped
     * like tracesCache, and constructed here rather than in the constructor so
     * the gateway constructor keeps the exact super(ctx, serviceKey) shape.
     */
    private balanceServices;
    constructor(ctx: Context, config?: ClawockStudioConfig);
    /** @returns Prepared runs (newest first), with decision/receipt presence flags. */
    list(): ListRunsResult;
    /**
     * Full detail of one run.
     * @param runId - 32-hex run id; anything else is rejected before any path use.
     * @returns Certified request, current decision artifact and receipt manifest (null when absent).
     */
    get(runId: string): RunDetailResult;
    /** @returns The shared decision ledger (memory/decisions.jsonl), file order. */
    ledger(): LedgerResult;
    /** @returns Portfolio summary per book, with the desk's money fields. */
    portfolio(): PortfolioResult;
    /** @returns Recent daily plans, newest first. */
    plans(): PlansResult;
    /**
     * The decision-trace view: real fills as the spine with soft-paired
     * decisions (±3 days) and T+1 verdicts. Cached by workspace-freshness
     * signature — the enriched result is rebuilt only when portfolio.json /
     * snapshots / decisions.jsonl actually changed; a hit returns in µs.
     * Every result carries `workspaceKey` (opaque hash) and `signature` so the
     * client can cache across tab mounts and re-fetch only on a real change.
     */
    traces(): TracesResult;
    /**
     * The header chip's answer: every provider's official endpoint, each
     * answered with that adapter's own key. In-band by design — never throws;
     * per-provider statuses 'no-key' / 'failed' / 'stale' carry a Chinese
     * message and a stale read keeps the last good snapshot. A provider with
     * no key configured is an honest row, not a hidden one.
     * @param force - bypass the TTL caches (the manual refresh button).
     */
    balance(force: boolean): Promise<BalancesResult>;
}
/**
 * Services the profile mixes into this plugin's context (the function-
 * plugin form — the class's `static inject` is its type mirror). The
 * gateway reaches the credential seam through `this.ctx.credentials`.
 */
export declare const inject: string[];
export declare const name = "clawock-dsh";
export declare function apply(ctx: Context, config?: ClawockStudioConfig): void;
