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
  BalancesResult, LedgerResult, ListRunsResult, PlansResult, PortfolioResult, RunDetailResult, TracesResult,
} from './types.ts'
import {
  createBalanceService,
  createClaudeService,
  createCodexService,
  createMinimaxService,
  type BalanceCredentials,
  type BalanceService,
} from './balance.ts'
import { getRun, listRuns } from './scan.ts'
import { readLedger, readPlans, readPortfolio, readTraces } from './ledger.ts'
import { createTraceCache, workspaceKeyOf, workspaceSignature } from './freshness.ts'

const workspaceOf = (): string => process.env.CLAWOCK_WORKSPACE || process.cwd()

/**
 * Row-level config the profile patch may set (see cordis.patch.yml).
 */
export interface ClawockStudioConfig {
  /** DeepSeek upstream root for the balance chip; /user/balance is appended. */
  balanceBaseUrl?: string
  /** Red-dot threshold in the displayed entry's currency (CNY/USD units). */
  balanceThreshold?: number
  /** Suggested client poll interval in ms. */
  balanceRefreshMs?: number
  /** MiniMax upstream root; /v1/token_plan/remains is appended. */
  minimaxBaseUrl?: string
  /** Credentials seam reference for the MiniMax key (env fallback same name). */
  minimaxKeyRef?: string
  /**
   * Red dot watermark in REMAINING terms: warn when MiniMax windows'
   * remaining percent falls to/below this (default 20 = ≥80% used). The
   * chip displays used percent; this field's meaning is unchanged.
   */
  minimaxLowPct?: number
  /** openclaw gateway config fallback for provider keys (models.providers.*). */
  minimaxOpenclawConfigPath?: string
  /** Claude Code OAuth credentials file (claudeAiOauth.accessToken). */
  claudeCredentialsPath?: string
  /** The undocumented /api/oauth/usage endpoint; overridable for tests. */
  claudeUsageUrl?: string
  /**
   * Red dot watermark in REMAINING terms for the Claude session window
   * (default 20 = ≥80% used); displayed number is used percent.
   */
  claudeLowPct?: number
  /** Codex CLI executable used for the official app-server quota RPC. */
  codexCommand?: string
  /** Red dot watermark in REMAINING terms (default 20 = >=80% used). */
  codexLowPct?: number
  /** Codex app-server polling/cache cadence in ms (default 5 minutes). */
  codexRefreshMs?: number
}

/**
 * The providers the balance chip lists, in display order. Adding one is one
 * row here plus its service in balance.ts — the gateway method below iterates
 * this table instead of naming each provider in four places (#1480 had to
 * touch the service map, the Promise.all, the row list and the refresh min).
 */
const BALANCE_PROVIDERS: readonly {
  id: string
  label: string
  create(deps: { credentials: BalanceCredentials }, config: ClawockStudioConfig): BalanceService
}[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    create: (deps, config) => createBalanceService(deps, {
      baseUrl: config.balanceBaseUrl, threshold: config.balanceThreshold, refreshMs: config.balanceRefreshMs,
    }),
  },
  {
    id: 'minimax',
    label: 'MiniMax',
    create: (deps, config) => createMinimaxService(deps, {
      baseUrl: config.minimaxBaseUrl,
      keyRef: config.minimaxKeyRef,
      lowPct: config.minimaxLowPct,
      openclawConfigPath: config.minimaxOpenclawConfigPath,
    }),
  },
  {
    id: 'claude',
    label: 'Claude',
    create: (deps, config) => createClaudeService(deps, {
      credentialsPath: config.claudeCredentialsPath, usageUrl: config.claudeUsageUrl, lowPct: config.claudeLowPct,
    }),
  },
  {
    id: 'codex',
    label: 'Codex',
    create: (deps, config) => createCodexService(deps, {
      command: config.codexCommand, lowPct: config.codexLowPct, refreshMs: config.codexRefreshMs,
    }),
  },
]

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
  private balanceServices: BalanceService[] | null = null

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
    if (this.balanceServices === null) {
      const deps = { credentials: credentialsOf(this.ctx) }
      this.balanceServices = BALANCE_PROVIDERS.map((provider) => provider.create(deps, this.config))
    }
    const services = this.balanceServices
    const results = await Promise.all(services.map((service) => service.get(force)))
    return {
      providers: BALANCE_PROVIDERS.map((provider, i) => ({ provider: provider.id, label: provider.label, result: results[i] })),
      refreshMs: Math.min(...results.map((result) => result.refreshMs)),
    }
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
