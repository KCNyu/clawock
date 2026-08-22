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

import { Remote, TypertRemoteService } from '@deepseek-ai/dsh-typert-protocol'
import type { Context } from '@deepseek-ai/cordis'
import type {
  LedgerResult, ListRunsResult, PlansResult, PortfolioResult, RunDetailResult, TracesResult,
} from './types.ts'
import { getRun, listRuns } from './scan.ts'
import { readLedger, readPlans, readPortfolio, readTraces } from './ledger.ts'
import { createTraceCache, workspaceKeyOf, workspaceSignature } from './freshness.ts'

const workspaceOf = (): string => process.env.CLAWOCK_WORKSPACE || process.cwd()

export class ClawockStudioGateway extends TypertRemoteService {
  static inject = [] as const

  /**
   * Signature-keyed trace cache per workspace (see freshness.ts). Owned by the
   * service instance rather than module scope: a module-level cache would
   * outlive plugin stop/update (the module stays in the process cache), so a
   * stopped plugin could keep serving a stale enriched view through a new
   * instance. Instance lifetime follows the fiber; a hit still costs µs.
   */
  private readonly tracesCache = createTraceCache()

  constructor(ctx: Context) {
    super(ctx, 'clawockStudio')
  }

  /** @returns Prepared runs (newest first), with decision/receipt presence flags. */
  @Remote
  list(): ListRunsResult {
    return { runs: listRuns(workspaceOf()) }
  }

  /**
   * Full detail of one run.
   * @param runId - 32-hex run id; anything else is rejected before any path use.
   * @returns Certified request, current decision artifact and receipt manifest (null when absent).
   */
  @Remote
  get(runId: string): RunDetailResult {
    return getRun(workspaceOf(), runId)
  }

  /** @returns The shared decision ledger (memory/decisions.jsonl), file order. */
  @Remote
  ledger(): LedgerResult {
    return readLedger(workspaceOf())
  }

  /** @returns Portfolio summary per book, with the desk's money fields. */
  @Remote
  portfolio(): PortfolioResult {
    return readPortfolio(workspaceOf())
  }

  /** @returns Recent daily plans, newest first. */
  @Remote
  plans(): PlansResult {
    return readPlans(workspaceOf())
  }

  /**
   * The decision-trace view: real fills as the spine with soft-paired
   * decisions (±3 days) and T+1 verdicts. Cached by workspace-freshness
   * signature — the enriched result is rebuilt only when portfolio.json /
   * snapshots / decisions.jsonl actually changed; a hit returns in µs.
   * Every result carries `workspaceKey` (opaque hash) and `signature` so the
   * client can cache across tab mounts and re-fetch only on a real change.
   */
  @Remote
  traces(): TracesResult {
    const ws = workspaceOf()
    const signature = workspaceSignature(ws)
    const hit = this.tracesCache.get(ws, signature)
    if (hit !== undefined) return hit as TracesResult
    const value: TracesResult = {
      workspaceKey: workspaceKeyOf(ws),
      signature,
      ...readTraces(ws),
    }
    this.tracesCache.set(ws, signature, value)
    return value
  }
}

export const name = 'clawock-dsh'

export function apply(ctx: Context): void {
  ctx.plugin(ClawockStudioGateway)
}
