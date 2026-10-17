/**
 * OpenClaw entry: `/dispatch-list` prints the task chip's provider panel —
 * every provider's allowance, each agent's live tasks, what just ended,
 * patrol — as one chat message. The same balance services and queue reader as
 * the dsh gateway (desk.ts), the same view model as the sidebar (panel.ts),
 * drawn as text (text.ts). Glue only: nothing about the panel is decided here.
 *
 * OpenClaw loads this package through `plugins.load.paths` (the plugin manifest
 * beside package.json names the command; package.json lists this entry). A
 * registered command bypasses the model and answers only allowlisted senders.
 * Telegram's menu spells it /dispatch_list; OpenClaw matches `-` and `_` alike.
 *
 * Keys: the balance services resolve a credential reference (DEEPSEEK_API_KEY,
 * MINIMAX_API_KEY) against this seam first and then the environment; here the
 * seam is the gateway's own config `env` block. Claude and Codex read their
 * own login files, MiniMax falls back to the gateway config as in dsh.
 *
 * The same entry also registers a `message_sending` hook for WeChat: a phone
 * cannot show a table whose cells are sentences, so those tables are rewritten
 * into cards on the way out (src/weixin-tables.ts). It is the only outbound
 * seam the WeChat plugin exposes — its own markdown filter passes tables
 * through untouched. `weixinTables` in the plugin config picks the mode:
 * `auto` (compact tables stay native), `cards` (rewrite all), `off`.
 */
import { homedir } from 'node:os'
import { join } from 'node:path'
import { createTranslator, dictionaries, type Translate } from './copy.ts'
import { createBalanceReader, taskQueueConfig, type BalanceReader, type ClawockStudioConfig } from './desk.ts'
import { panelModel, type PanelInput } from './panel.ts'
import { createTaskQueueService, type TaskQueueService } from './taskqueue.ts'
import { panelText } from './text.ts'
import { formatWeixinTables, type WeixinTableMode } from './weixin-tables.ts'
import type { BalanceCredentials } from './balance.ts'

/** Test seam: the hook is three lines, the layout itself lives in src/weixin-tables.ts. */
export { formatWeixinTables }

/** What OpenClaw hands a `message_sending` handler (the fields this entry reads). */
export interface MessageSendingEvent {
  content: string
  to?: string
  metadata?: Record<string, unknown>
}

/** The slice of OpenClaw's plugin API this entry uses (the SDK's own types are not a dependency of this package). */
export interface OpenClawCommandApi {
  pluginConfig?: Record<string, unknown>
  registerCommand(command: {
    name: string
    description: string
    acceptsArgs?: boolean
    handler: (ctx: { args?: string; config?: { env?: unknown; agents?: { defaults?: { workspace?: string } } } }) => Promise<{ text: string }>
  }): void
  on?(
    name: 'message_sending',
    handler: (event: MessageSendingEvent) => { content?: string } | void,
  ): void
}

/** Channel id the WeChat plugin registers. Only its messages get the table rewrite. */
const WEIXIN_CHANNEL = 'openclaw-weixin'

/** `weixinTables` accepts the three modes (or a `{ mode }` object) and falls back to `auto`. */
export function weixinTableMode(value: unknown): WeixinTableMode {
  const mode = typeof value === 'string' ? value : (value as { mode?: unknown } | undefined)?.mode
  return mode === 'cards' || mode === 'off' ? mode : 'auto'
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
  const config = (api.pluginConfig ?? {}) as ClawockStudioConfig & { locale?: string; weixinTables?: unknown }
  const t = createTranslator(dictionaries[config.locale ?? 'zh'] ?? dictionaries.zh!)
  const tableMode = weixinTableMode(config.weixinTables)
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
  // Only WeChat, and only when the text actually changed: every other channel keeps its
  // own formatting, and a message without a bad table comes back untouched.
  api.on?.('message_sending', (event) => {
    if (tableMode === 'off' || event.metadata?.channel !== WEIXIN_CHANNEL) return
    if (typeof event.content !== 'string' || !event.content.includes('|')) return
    const content = formatWeixinTables(event.content, tableMode)
    return content === event.content ? undefined : { content }
  })
}
