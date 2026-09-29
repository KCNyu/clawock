/**
 * OpenClaw entry: `/dispatch-list` prints the task chip's provider panel —
 * every provider's allowance, each agent's live tasks, what just ended,
 * patrol — as one chat message. The same balance services and queue reader as
 * the dsh gateway (desk.ts), the same view model as the sidebar (panel.ts),
 * drawn as text (text.ts). Glue only: nothing about the panel is decided here.
 *
 * OpenClaw loads this package through `plugins.load.paths` (manifest:
 * openclaw.plugin.json; entry: package.json `openclaw.extensions`). A
 * registered command bypasses the model and answers only allowlisted senders.
 * Telegram's menu spells it /dispatch_list; OpenClaw matches `-` and `_` alike.
 *
 * Keys: the balance services resolve a credential reference (DEEPSEEK_API_KEY,
 * MINIMAX_API_KEY) against this seam first and then the environment; here the
 * seam is the gateway's own config `env` block. Claude and Codex read their
 * own login files, MiniMax falls back to the gateway config as in dsh.
 */
import { homedir } from 'node:os'
import { join } from 'node:path'
import { createTranslator, dictionaries, type Translate } from './copy.ts'
import { createBalanceReader, taskQueueConfig, type BalanceReader, type ClawockStudioConfig } from './desk.ts'
import { panelModel, type PanelInput } from './panel.ts'
import { createTaskQueueService, type TaskQueueService } from './taskqueue.ts'
import { panelText } from './text.ts'
import type { BalanceCredentials } from './balance.ts'

/** The slice of OpenClaw's plugin API this entry uses (the SDK's own types are not a dependency of this package). */
export interface OpenClawCommandApi {
  pluginConfig?: Record<string, unknown>
  registerCommand(command: {
    name: string
    description: string
    acceptsArgs?: boolean
    handler: (ctx: { args?: string; config?: { env?: unknown; agents?: { defaults?: { workspace?: string } } } }) => Promise<{ text: string }>
  }): void
}

type GatewayConfig = { env?: unknown; agents?: { defaults?: { workspace?: string } } }

/** Credential references resolved against the gateway config's `env` block (the balance services then fall back to process env). */
function gatewayCredentials(config: GatewayConfig | undefined): BalanceCredentials {
  return {
    async resolve(ref) {
      const env = config?.env
      const value = env !== null && typeof env === 'object' ? (env as Record<string, unknown>)[ref] : undefined
      return typeof value === 'string' && value !== '' ? { value } : undefined
    },
  }
}

/** The reply for one read of both halves (the test seam: tests/decision_studio_plugin.spec.js compares it with the panel). */
export function dispatchListText(input: PanelInput, t: Translate, now: number): string {
  return panelText(panelModel(input, t, now), t)
}

export default function register(api: OpenClawCommandApi): void {
  const config = (api.pluginConfig ?? {}) as ClawockStudioConfig & { locale?: string }
  const t = createTranslator(dictionaries[config.locale ?? 'zh'] ?? dictionaries.zh!)
  // One set of services per gateway, like the dsh gateway's instance: their caches and TTLs
  // keep a burst of commands from hitting every provider each time.
  let balances: BalanceReader | null = null
  let queue: TaskQueueService | null = null
  api.registerCommand({
    name: 'dispatch-list',
    description: t('panel.title'),
    acceptsArgs: true,
    handler: async (ctx) => {
      const force = (ctx.args ?? '').trim() === 'refresh'
      const workspace = ctx.config?.agents?.defaults?.workspace ?? process.env.CLAWOCK_WORKSPACE ?? join(homedir(), '.openclaw', 'workspace')
      balances ??= createBalanceReader(gatewayCredentials(ctx.config), config)
      queue ??= createTaskQueueService(taskQueueConfig(config, workspace))
      const [balance, tasks] = await Promise.allSettled([balances.get(force), queue.get(force)])
      const why = (reason: unknown): string => (reason instanceof Error ? reason.message : String(reason)) || t('balance.unknownError')
      return {
        text: dispatchListText({
          balances: balance.status === 'fulfilled' ? balance.value : null,
          balanceError: balance.status === 'rejected' ? why(balance.reason) : null,
          queue: tasks.status === 'fulfilled' ? tasks.value : null,
          queueError: tasks.status === 'rejected' ? why(tasks.reason) : null,
        }, t, Date.now()),
      }
    },
  })
}
