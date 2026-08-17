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
import type { LedgerResult, ListRunsResult, PlansResult, PortfolioResult, RunDetailResult, TracesResult } from './types.ts';
export declare class ClawockStudioGateway extends TypertRemoteService {
    static inject: readonly [];
    constructor(ctx: Context);
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
}
export declare const name = "clawock-dsh";
export declare function apply(ctx: Context): void;
