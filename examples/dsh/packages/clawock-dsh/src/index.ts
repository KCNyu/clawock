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
  BalancesResult, LedgerResult, ListRunsResult, PlansResult, PortfolioResult, QueueActionResult, RunDetailResult, TaskQueueResult,
  TracesResult,
} from './types.ts'
import type { BalanceCredentials } from './balance.ts'
import { createBalanceReader, taskQueueConfig, type BalanceReader, type ClawockStudioConfig } from './desk.ts'
import { getRun, listRuns } from './scan.ts'
import { createQueueActionRunner, createTaskQueueService, type QueueActionRunner, type TaskQueueService } from './taskqueue.ts'

export type { ClawockStudioConfig } from './desk.ts'
import { readLedger, readPlans, readPortfolio, readTraces } from './ledger.ts'
import { createTraceCache, workspaceKeyOf, workspaceSignature } from './freshness.ts'

const workspaceOf = (): string => process.env.CLAWOCK_WORKSPACE || process.cwd()

export class ClawockStudioGateway extends TypertRemoteService {
  static inject = ['credentials'] as const

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
  private readonly tracesCache = createTraceCache()

  /**
   * Per-provider balance services, built lazily on first use — instance-scoped
   * like tracesCache, and constructed here rather than in the constructor so
   * the gateway constructor keeps the exact super(ctx, serviceKey) shape.
   */
  private balanceReader: BalanceReader | null = null

  /** The task chip's reader, lazily built and instance-scoped like the balance services. */
  private taskQueueService: TaskQueueService | null = null

  /** The task chip's write door (the ops entry), built with the reader. */
  private queueActionRunner: QueueActionRunner | null = null

  /**
   * The row config, owned by the instance. cordis constructs a class plugin as
   * `new Plugin(ctx, config)` (Fiber's runner), so the constructor already
   * receives it — no module-level handoff is involved, and two rows or a
   * plugin reload can never read each other's config.
   */
  private readonly config: ClawockStudioConfig

  constructor(ctx: Context, config: ClawockStudioConfig = {}) {
    super(ctx, 'clawockStudio')
    this.config = config
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
   * memory/bars / decisions.jsonl / memory/fx-rates.jsonl actually changed; a hit returns in µs.
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

  /**
   * The header chip's answer: every provider's official endpoint, each
   * answered with that adapter's own key. In-band by design — never throws;
   * per-provider statuses 'no-key' / 'failed' / 'stale' carry a Chinese
   * message and a stale read keeps the last good snapshot. A provider with
   * no key configured is an honest row, not a hidden one.
   * @param force - bypass the TTL caches (the manual refresh button).
   */
  @Remote
  async balance(force: boolean): Promise<BalancesResult> {
    if (this.balanceReader === null) this.balanceReader = createBalanceReader(credentialsOf(this.ctx), this.config)
    return this.balanceReader.get(force)
  }


  /**
   * The sidebar-foot task chip: live agent-dispatch tasks and what each waits
   * for, the recently ended ones, and the clawock-patrol supervisor's phase.
   * Local files and systemctl only; in-band like balance(), never throws.
   * @param force - bypass the short host cache (the manual refresh button).
   */
  @Remote
  async taskQueue(force: boolean): Promise<TaskQueueResult> {
    return this.queueServices().reader.get(force)
  }

  /**
   * One write from the task chip — cancel, priority, model, retry, wrapup,
   * deadline, attempts, resumes — or a read the chip needs on demand (choices,
   * log, brief, usage). Runs the versioned
   * ops entry with `--source ui` (it validates, serialises per task, audits
   * in the task directory); a double click shares one run. In-band like
   * taskQueue(): never throws, a refusal is `{ ok: false, code, message }`.
   * @param action - one of cancel | priority | model | choices | retry | wrapup | log | brief | usage | deadline | attempts | resumes.
   * @param id - the task id; anything that is not one is refused before any process runs.
   * @param arg - priority: top | up | down | reset | n; model: "<model>|<effort>" ('keep'/'default');
   *   deadline: +Nh | +Nm | "YYYY-MM-DD HH:MM" | reset; attempts/resumes: n | reset; else ''.
   */
  @Remote
  async queueAction(action: string, id: string, arg: string): Promise<QueueActionResult> {
    return this.queueServices().act(action, id, arg)
  }

  private queueServices(): { reader: TaskQueueService; act: QueueActionRunner } {
    if (this.taskQueueService === null || this.queueActionRunner === null) {
      const config = taskQueueConfig(this.config, workspaceOf())
      const reader = createTaskQueueService(config)
      this.taskQueueService = reader
      this.queueActionRunner = createQueueActionRunner(config, undefined, () => { reader.invalidate() })
    }
    return { reader: this.taskQueueService, act: this.queueActionRunner }
  }
}

/**
 * Services the profile mixes into this plugin's context (the function-
 * plugin form — the class's `static inject` is its type mirror). The
 * gateway reaches the credential seam through `this.ctx.credentials`.
 */
export const inject = ['credentials']

/**
 * Typed access to the injected credentials seam. Deliberately a cast, not
 * an import of @deepseek-ai/dsh-credentials: that package's cordis
 * augmentation would register this package in the typert host face and
 * fail the Remote-artifacts gate (see balance.ts).
 */
function credentialsOf(ctx: Context): BalanceCredentials {
  return (ctx as unknown as { credentials: BalanceCredentials }).credentials
}

export const name = 'clawock-dsh'

export function apply(ctx: Context, config: ClawockStudioConfig = {}): void {
  ctx.plugin(ClawockStudioGateway, config)
}
