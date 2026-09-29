/**
 * What feeds the task chip's provider panel, assembled once for every host that
 * shows it: the balance services in display order, and the task queue reader's
 * configuration. The dsh gateway (index.ts) serves these to the sidebar; the
 * OpenClaw `/dispatch-list` command (openclaw.ts) reads the same services in
 * its own process. Neither host builds its own list of providers or paths.
 */
import { join } from 'node:path'
import type { BalancesResult } from './types.ts'
import {
  createBalanceService,
  createClaudeService,
  createCodexService,
  createMinimaxService,
  type BalanceCredentials,
  type BalanceService,
} from './balance.ts'
import type { TaskQueueConfig } from './taskqueue.ts'

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
  /**
   * agent-dispatch task directories (default ~/logs/agent-dispatch). The task
   * chip exists only where this directory does.
   */
  dispatchLogDir?: string
  /** The dispatcher's shared slot policy (default ~/tools/agent-dispatch/limits.env). */
  dispatchLimitsPath?: string
  /** clawock-patrol state: current-round, rounds.tsv (default ~/logs/clawock-patrol). */
  patrolStateDir?: string
  /** Suggested client poll interval for the task chip in ms (default 15s). */
  taskQueueRefreshMs?: number
  /** How many recently ended tasks the chip lists (default 5). */
  taskQueueRecent?: number
  /**
   * The versioned queue ops entry every chip write goes through (default
   * ~/tools/agent-dispatch/task_queue_ops.py, installed by
   * ops/host/install_task_queue_ops.sh). Its hash is compared with the
   * workspace's ops/host/task_queue_ops.py so skew shows on the chip.
   */
  taskQueueOpsPath?: string
}

/**
 * The providers the balance chip lists, in display order. Adding one is one
 * row here plus its service in balance.ts — the gateway method below iterates
 * this table instead of naming each provider in four places (#1480 had to
 * touch the service map, the Promise.all, the row list and the refresh min).
 */
export const BALANCE_PROVIDERS: readonly {
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

/** Every provider's balance, read together (each service keeps its own cache and TTL). */
export type BalanceReader = { get(force: boolean): Promise<BalancesResult> }

export function createBalanceReader(credentials: BalanceCredentials, config: ClawockStudioConfig): BalanceReader {
  const services = BALANCE_PROVIDERS.map((provider) => provider.create({ credentials }, config))
  return {
    async get(force) {
      const results = await Promise.all(services.map((service) => service.get(force)))
      return {
        providers: BALANCE_PROVIDERS.map((provider, i) => ({ provider: provider.id, label: provider.label, result: results[i]! })),
        refreshMs: Math.min(...results.map((result) => result.refreshMs)),
      }
    },
  }
}

/** The task queue reader's (and write door's) configuration; `workspace` holds the repository's copy of the ops entry. */
export function taskQueueConfig(config: ClawockStudioConfig, workspace: string): TaskQueueConfig {
  return {
    logDir: config.dispatchLogDir,
    limitsPath: config.dispatchLimitsPath,
    patrolDir: config.patrolStateDir,
    refreshMs: config.taskQueueRefreshMs,
    recent: config.taskQueueRecent,
    opsPath: config.taskQueueOpsPath,
    repoOpsPath: join(workspace, 'ops', 'host', 'task_queue_ops.py'),
  }
}
