/**
 * The task chip's provider panel as data: every row it shows (a provider's
 * allowance, a live task, an ended one, a patrol round), its words, its state
 * role and its place — without React or the DOM. client.ts draws these rows in
 * dsh's sidebar; text.ts prints the same rows for a chat (OpenClaw's
 * `/dispatch-list`). One view model, two renderers: the chat reply cannot say
 * something the chip does not, or say it in other words.
 *
 * The parts a renderer draws for itself are named, not built here: a row's lead
 * glyph (`RowLead`), the fallback mark and the delivery receipts (`Fact`).
 */
import { PROVIDER_JOIN, byAgentRank, sourceRank, type ProviderJoin } from './providers.ts'
import { resetStampOf, windowsOf, type Translate } from './copy.ts'
import type { AgentQueue, BalanceResult, BalancesResult, DispatchTask, PatrolRound, TaskQueueResult } from './types.ts'

/** The four visual states one provider's reading can take. */
export type BalanceTone = 'ok' | 'low' | 'stale' | 'none'

/** Usage-direction colour tier of a used-percent reading. */
export type UsedLevel = 'ok' | 'mid' | 'low'

/**
 * Colour tier for one used-percent reading against the REMAINING-watermark
 * threshold (lowPct). kcn 的配色口径:已使用低 = 正常绿(--ok),逼近额度
 * 上限先黄(--warn)再红(--bad)。档位从既有 lowPct 派生,不新增配置:
 * warn at 100−2·lowPct, red inside 100−lowPct(默认 20 → 60% 黄 / 80% 红)。
 * 档位只决定颜色,绝不增删信息(kcn 反馈 #908:变红不许吃掉任何字段)。
 */
export function _usedLevel(percent: number | null, threshold: number): UsedLevel {
  if (percent === null) return 'ok'
  if (percent >= 100 - threshold) return 'low'
  if (percent >= 100 - 2 * threshold) return 'mid'
  return 'ok'
}

/**
 * Display projection of ONE provider's answer (test seam, like _displayEntry):
 * the chip and panel render only these fields, so the view never keeps
 * a second copy of the tone rules — the host already decided status and low.
 * The title is the whole hover story: split, quota windows, stale reason,
 * fetch time. Quota rows ('pct' unit) read as USED percent (kcn: 「已使用」
 * 比「剩余」直观), not money, and carry the second window ('周'/'本周') as a
 * muted pill suffix — both limits visible at the header without opening the
 * panel. An exhausted window gets no caption at all (kcn 反馈: 文案只会重复):
 * the reading itself says 100% and `reset` carries when it frees up.
 */
export function _rowDisplay(result: BalanceResult | null, t: Translate, now: number = Date.now()): { tone: BalanceTone; value: string; sub: string | null; reset: string | null; level: UsedLevel | null; title: string } {
  if (result === null) return { tone: 'none', value: '—', sub: null, reset: null, level: null, title: t('balance.loading') }
  if (!result.configured) return { tone: 'none', value: t('balance.unconfigured'), sub: null, reset: null, level: null, title: result.message ?? t('balance.unconfiguredKey') }
  if (result.snapshot === null) return { tone: 'none', value: '—', sub: null, reset: null, level: null, title: result.message ?? t('balance.fetchFailed') }
  const snapshot = result.snapshot
  const isPct = snapshot.unit === 'pct'
  const symbol = isPct ? '' : snapshot.currency === 'USD' ? '$' : snapshot.currency === 'CNY' ? '¥' : ''
  // The headline reads the first window (parsers mirror it into totalBalance);
  // when the primary window is absent this cycle (Claude between sessions),
  // the first readable window steps up instead of rendering a bare '—'.
  const pctWins = isPct && Array.isArray(snapshot.windows)
    ? snapshot.windows.filter((w) => w.percent !== null)
    : []
  const parsed = Number.parseFloat(snapshot.totalBalance)
  const value = isFinite(parsed)
    ? (isPct ? String(Math.round(parsed)) + '%' : symbol + parsed.toLocaleString(undefined, { maximumFractionDigits: 2 }))
    : pctWins.length > 0
      ? String(Math.round(pctWins[0].percent as number)) + '%'
      : (snapshot.totalBalance === '' ? '—' : symbol + snapshot.totalBalance)
  const second = pctWins.length > 1 ? pctWins[1] : null
  // 头条窗口自己的重置时刻(↻ 前缀,面板每窗一行同款):额度用尽时用户要能
  // 看到「什么时候恢复」而不是一句「已用尽」。跟头条数字同一个窗——头条
  // 缺窗时步进到第一个可读窗,重置也跟着那一个走。
  const wins = windowsOf(t, result, now)
  const firstReset = wins.length > 0 ? wins[0]!.reset : ''
  const reset = pctWins.length > 0 && firstReset !== '' ? firstReset : null
  const secondWin = wins.length > 1 ? wins[1]! : null
  const sub = secondWin !== null && second !== null
    ? '· ' + secondWin.label + ' ' + Math.round(second.percent as number) + '%' + (secondWin.reset !== '' ? ' ↻' + secondWin.reset : '')
    : null
  const tone: BalanceTone = result.status === 'stale'
    ? 'stale'
    : (result.low || !snapshot.isAvailable ? 'low' : 'ok')
  // 更新时间不重复展示:轮询是静默的,手动刷新有 ✓ 反馈——时间戳只增加噪音。
  // The quota line is composed from the structured windows, not from the
  // host's `note`: that string is built in the host's language, and it is the
  // one place the panel would otherwise stay monolingual. A snapshot without
  // windows carries only vendor detail, so its note passes through verbatim.
  // quotaSnapshot appends provider status after one ` · ` segment per window.
  // Re-render the windows in the active locale, but keep that non-window tail:
  // it carries Codex's limited state and Claude's extra-usage reading.
  const quotaTail = wins.length === 0
    ? []
    : snapshot.note.split(' · ').slice(snapshot.windows.length).filter((note) => note !== '')
  const quotaLine = wins.length === 0
    ? (snapshot.note !== '' ? snapshot.note : t('balance.windowsUsed'))
    : [...wins
      .filter((w) => w.percent !== null)
      .map((w) => (w.reset === ''
        ? t('balance.windowNote', { label: w.label, percent: Math.round(w.percent as number) })
        : t('balance.windowNoteReset', { label: w.label, percent: Math.round(w.percent as number), reset: w.reset }))),
      ...quotaTail]
      .join(' · ')
  const parts = [
    snapshot.unit === 'pct' ? quotaLine : t('balance.apiBalance'),
    !isPct && snapshot.grantedBalance !== '' ? t('balance.granted') + symbol + snapshot.grantedBalance : null,
    !isPct && snapshot.toppedUpBalance !== '' ? t('balance.toppedUp') + symbol + snapshot.toppedUpBalance : null,
    // 用尽不再说话(kcn 反馈):配额行的进度条(100%)+重置时间自己会讲,
    // 一句「已用尽」只会把那两样顶掉。金额行没有条可讲,保留原句。
    snapshot.isAvailable || isPct ? null : t('balance.insufficient'),
    result.status === 'stale' && result.message !== null ? t('balance.staleWith', { message: result.message }) : null,
  ].filter((part): part is string => part !== null)
  // 头条数字的用量档位(染色用):配额行按实际显示的那个数取档;金额行
  // 没有用量语义,level 为 null,颜色仍走 tone(money low = 红)。
  const shownPct = isPct ? (isFinite(parsed) ? parsed : (pctWins.length > 0 ? pctWins[0].percent as number : null)) : null
  const level: UsedLevel | null = shownPct === null ? null : _usedLevel(Math.round(shownPct), result.threshold)
  return { tone, value, sub, reset, level, title: parts.join(' · ') }
}

/**
 * The one line a panel row says out loud when something is wrong — stale
 * reason, unconfigured key, insufficient money balance. A healthy number
 * earns no caption at all; null means silence. An exhausted quota window
 * is silence too (kcn 反馈): its 100% bar and reset stamp in the per-window
 * rows are the message; a caption would only replace them.
 */
export function _balanceNote(result: BalanceResult | null, t: Translate): string | null {
  if (result === null) return null
  if (!result.configured) return result.message ?? t('balance.unconfiguredKey')
  if (result.snapshot === null) return result.message ?? t('balance.fetchFailed')
  if (result.status === 'stale') {
    return result.message !== null
      ? t('balance.staleWith', { message: result.message })
      : t('balance.stale')
  }
  if (!result.snapshot.isAvailable) {
    return result.snapshot.unit === 'pct' ? null : t('balance.insufficient')
  }
  if (result.low) {
    // threshold 是「剩余水位」(lowPct),已使用方向 = 100 − threshold。
    if (result.snapshot.unit === 'pct') {
      // With per-window lines the panel already shows which window crossed
      // the line — its label, percent and a red bar (kcn:「5h已用 周已用这些
      // 没必要重复显示,进度条都看得到」). The row's red dot and value carry
      // the warning; a caption would only repeat a line printed right below.
      // A snapshot without windows has nothing below it, so it keeps the line.
      return (result.snapshot.windows ?? []).length > 0
        ? null
        : t('balance.windowAt', { percent: 100 - result.threshold })
    }
    const symbol = result.snapshot.currency === 'USD' ? '$' : result.snapshot.currency === 'CNY' ? '¥' : ''
    return t('balance.lowMoney', { amount: symbol + result.threshold })
  }
  return null
}

/** One provider row as the chip, the foot button and the panel render it. */
export type BalanceRow = BalancesResult['providers'][number] & {
  view: ReturnType<typeof _rowDisplay>
  note: string | null
}

/** A live task queued for something another task of its agent holds (the backlog patrol yields to). */
export const queuedFor = (task: DispatchTask): boolean =>
  task.waiting === 'lock' || task.waiting === 'slot'

/**
 * Which run slot a live task holds: `SLOT=<agent>-<n>` (slots are per agent).
 * Anything else is shown verbatim under the task's own agent. (The shared
 * `slot-1..2` of the runners from before 2026-09-25, a bare number, had a
 * bucket of its own until 2026-09-27, when none was left.)
 */
export function _slotOf(task: DispatchTask): { agent: string; slot: string } | null {
  if (task.slot === '') return null
  const lane = /^([a-z][a-z0-9]*)-(\d+)$/.exec(task.slot)
  return lane ? { agent: lane[1]!, slot: lane[2]! } : { agent: task.agent, slot: task.slot }
}

export type SlotLane = { agent: string; used: number; max: number | null; tone: BalanceTone }

/**
 * Each agent's run slots, in the panel's order (providers.ts), limits.env's
 * agents and any agent seen holding one that limits.env does not name. A full lane with a task of that agent queued
 * is amber: that is the queue's reason at a glance. A host older than
 * slotLimits sends none: the lanes then come from the held slots alone,
 * without a maximum.
 */
export function _slotLanes(result: TaskQueueResult): SlotLane[] {
  const held = result.active.map(_slotOf).filter((slot): slot is NonNullable<ReturnType<typeof _slotOf>> => slot !== null)
  const limits = new Map((result.slotLimits ?? []).map((limit) => [limit.agent, limit.max] as const))
  for (const slot of held) if (!limits.has(slot.agent)) limits.set(slot.agent, -1)
  return byAgentRank([...limits].map(([agent, limit]) => ({ agent, limit }))).map(({ agent, limit }) => {
    const used = held.filter((slot) => slot.agent === agent).length
    const max = limit >= 0 ? limit : null
    const queued = result.active.some((task) => task.agent === agent && queuedFor(task))
    const tone: BalanceTone = max !== null && used >= max && queued ? 'stale' : used > 0 ? 'ok' : 'none'
    return { agent, used, max, tone }
  })
}

export function laneText(t: Translate, lane: SlotLane): string {
  return lane.max === null
    ? t('queue.laneNoMax', { agent: lane.agent, used: lane.used })
    : t('queue.lane', { agent: lane.agent, used: lane.used, max: lane.max })
}

export function durationOf(t: Translate, ms: number): string {
  const mins = Math.max(0, Math.floor(ms / 60000))
  return mins < 60
    ? t('queue.duration.minutes', { m: mins })
    : t('queue.duration.hours', { h: Math.floor(mins / 60), m: mins % 60 })
}

export function agoOf(t: Translate, ms: number): string {
  const mins = Math.max(0, Math.floor(ms / 60000))
  if (mins < 1) return t('queue.ago.now')
  if (mins < 60) return t('queue.ago.minutes', { m: mins })
  if (mins < 48 * 60) return t('queue.ago.hours', { h: Math.floor(mins / 60) })
  return t('queue.ago.days', { d: Math.floor(mins / 1440) })
}

/**
 * One live task's status phrase and its tone. One colour, one meaning:
 * 'ok' (the host's business blue) = holding its agent's lock and running,
 * 'stale' (the host's warn) = waiting for something (the lock, a slot,
 * memory, a quota reset, a retry), 'none' = neither yet (starting).
 */
export function _taskStatus(task: DispatchTask, t: Translate, now: number = Date.now(),
  windows?: ReadonlyArray<{ resetAtMs?: number | null }>): { tone: BalanceTone; text: string } {
  const stamp = (ms: number): string => resetStampOf(t, { resetAt: '', resetAtMs: ms }, now)
  const at = (key: string, ms: number | null): string => ms === null
    ? t(key + 'NoTime')
    : t(key, { time: stamp(ms) })
  if (task.cancelling) return { tone: 'none', text: t('queue.state.cancelling') }
  switch (task.waiting) {
    case 'lock': return {
      tone: 'stale',
      text: task.position ? t('queue.wait.lockAt', { agent: task.agent, n: task.position }) : t('queue.wait.lock', { agent: task.agent }),
    }
    case 'slot': return { tone: 'stale', text: t('queue.wait.slot', { agent: task.agent }) }
    case 'memory': return { tone: 'stale', text: t('queue.wait.memory') }
    case 'quota': {
      // Two facts, both shown (never one standing in for the other): when the runner wakes, and
      // the provider window's reset it waits for — the one that resets last at or before the wake.
      if (task.wakeAtMs === null || windows === undefined) return { tone: 'stale', text: at('queue.wait.quota', task.wakeAtMs) }
      const wake = task.wakeAtMs
      const resets = windows.map((w) => w.resetAtMs ?? null)
        .filter((ms): ms is number => ms !== null && ms <= wake + 60000 && wake - ms < 6 * 3600000)
      if (resets.length === 0) return { tone: 'stale', text: t('queue.wait.quotaNoWindow', { time: stamp(wake) }) }
      const reset = Math.max(...resets)
      return { tone: 'stale', text: t('queue.wait.quotaBoth', { time: stamp(wake), reset: stamp(reset), pad: Math.max(0, Math.round((wake - reset) / 60000)) }) }
    }
    case 'retry': return { tone: 'stale', text: at('queue.wait.retry', task.wakeAtMs) }
    default: break
  }
  const slot = _slotOf(task)
  if (slot === null) return { tone: 'none', text: t('queue.state.starting') }
  // One slot per agent: the group header already says whose it is.
  return { tone: 'ok', text: slot.slot === '1' ? t('queue.state.running') : t('queue.state.runningSlot', { slot: slot.slot }) }
}

/** Keep the runner's execution verdict and the model's report in separate, named slots. */
export function executionText(state: string, t: Translate): string {
  const key = ({ ok: 'ok', partial: 'ok', unverified: 'ok', failed: 'failed', cancelled: 'cancelled',
    timeout: 'timeout', blocked: 'blocked', quota: 'quota', queued: 'queued' } as Record<string, string>)[state] ?? 'unknown'
  return t('queue.execution.' + key)
}

export function reportText(outcome: string, t: Translate, executionState = 'ok'): string {
  if (outcome === 'DONE' && !['ok', 'partial', 'unverified'].includes(executionState)) return t('queue.report.claimedDone')
  const key = ['DONE', 'PARTIAL', 'BLOCKED'].includes(outcome) ? outcome : 'unknown'
  return t('queue.report.' + key)
}

/**
 * An ended task's tone. Done is not blue (blue means running now) and not a
 * dot at all: ended rows speak in words. Not-done amber, failed red.
 */
export function endedTone(task: DispatchTask): BalanceTone {
  if (task.state === 'failed' || task.state === 'timeout') return 'low'
  if (['partial', 'unverified', 'blocked', 'quota'].includes(task.state)
    || (task.state === 'ok' && task.outcome !== 'DONE') || task.outcome === 'BLOCKED') return 'stale'
  return 'none'
}

export function patrolPhraseOf(result: TaskQueueResult, t: Translate, now: number): string {
  const patrol = result.patrol
  if (patrol.phase === 'waiting' && patrol.untilMs !== null) {
    return t('queue.patrol.waitingUntil', { time: resetStampOf(t, { resetAt: '', resetAtMs: patrol.untilMs }, now) })
  }
  return t('queue.patrol.' + patrol.phase)
}

/** The ops entry answered, and its installed copy is the repository's. '' when fine, else why not. */
export function opsProblem(result: TaskQueueResult, t: Translate): string {
  const ops = result.ops
  if (ops === undefined) return ''
  if (!ops.available) return t('queue.ops.missing', { error: ops.error })
  if (ops.repoVersion !== '' && ops.version !== ops.repoVersion) return t('queue.ops.skew', { host: ops.version, repo: ops.repoVersion })
  return ''
}

/**
 * The chip's headline, the host badge's two parts: the label, and a count
 * (running · queued) at the trailing edge. No n/max: slots are per agent, so a
 * free slot of one agent is no room for another's task — the per-agent lanes
 * are in the title and on each group of the panel. The glyph badge carries
 * the one tone that matters most: red when the read failed, amber when a task
 * waits, blue when something runs.
 */
export function _queueHeadline(result: TaskQueueResult, t: Translate, now: number = Date.now()): { tone: BalanceTone; value: string; sub: string; busy: boolean; title: string } {
  const queued = result.active.filter(queuedFor).length
  // Only patrol admission waits for memory: a reason of its own, not a queue behind a task.
  const memory = result.active.filter((task) => task.waiting === 'memory').length
  const quota = result.active.filter((task) => task.waiting === 'quota').length
  // A retry back-off holds nothing either, but it is still a live task waiting (#1772).
  const retry = result.active.filter((task) => task.waiting === 'retry').length
  // Every kind of wait is counted on the row itself (a retry back-off hidden from it was #1772);
  // the patrol phase is context, so it lives in the title and the panel.
  const waits = [
    queued > 0 ? t('queue.queued', { n: queued }) : null,
    memory > 0 ? t('queue.memoryWait', { n: memory }) : null,
    quota > 0 ? t('queue.quotaWait', { n: quota }) : null,
    retry > 0 ? t('queue.retryWait', { n: retry }) : null,
  ].filter((part): part is string => part !== null)
  const parts = [...waits, patrolPhraseOf(result, t, now)]
  const value = result.active.length === 0 ? t('queue.idle') : t('queue.running', { n: result.running })
  const slots = _slotLanes(result).map((lane) => laneText(t, lane)).join(' · ')
  const waiting = queued + memory + quota + retry
  const tone: BalanceTone = result.status === 'stale' || result.status === 'failed'
    ? 'low'
    : waiting > 0 ? 'stale' : result.running > 0 ? 'ok' : 'none'
  const ops = result.ops?.available ? t('queue.ops.version', { v: result.ops.version }) : ''
  return {
    tone, value, sub: waits.join(' · '), busy: queued > 0,
    title: [t('queue.name'), value, slots, parts.join(' · '), opsProblem(result, t) || ops]
      .filter((part) => part !== '').join(' · '),
  }
}

/** Executor names as their makers write them. */
export const AGENT_LABELS: Record<string, string> = { claude: 'Claude Code', codex: 'Codex', opencode: 'OpenCode' }

export const _agentLabel = (agent: string): string => AGENT_LABELS[agent] ?? agent

/**
 * The model layer, read off the model id itself (never a hand-kept model
 * list), as its maker names it in full: `claude-opus-5-5` → Claude Opus 5.5 ·
 * `claude-haiku-4-5-20251001` → Claude Haiku 4.5 · `gpt-6-sol` → GPT-6 Sol ·
 * `opencode/nemotron-3-ultra-free` → Nemotron 3 Ultra. No letter tile in
 * front (kcn, 2026-09-27: the two-letter stand-in was noise); the room goes
 * to the whole name.
 */
export function _modelView(id: string): { label: string; family: string } {
  if (id === '') return { label: '—', family: '' }
  const bare = id.includes('/') ? id.slice(id.lastIndexOf('/') + 1) : id
  const title = (word: string): string => word.charAt(0).toUpperCase() + word.slice(1)
  const claude = /^claude-([a-z]+)(?:-(\d+))?(?:-(\d{1,2}))?(?:-\d{8})?$/.exec(bare)
  if (claude) {
    const version = [claude[2], claude[3]].filter(Boolean).join('.')
    return { label: 'Claude ' + title(claude[1]!) + (version ? ' ' + version : ''), family: 'claude' }
  }
  const gpt = /^gpt-([\d.]+)(?:-([a-z]+))?$/.exec(bare)
  if (gpt) return { label: 'GPT-' + gpt[1] + (gpt[2] ? ' ' + title(gpt[2]) : ''), family: 'gpt' }
  if (/^[a-z]+$/.test(bare) && !id.includes('/')) return { label: title(bare), family: bare }
  const words = bare.replace(/-(free|contributor)(?=-|$)/g, '').split('-').filter((word) => word !== '')
  const label = words.map((word) => /^[a-z]/.test(word) ? title(word) : word).join(' ')
  return { label, family: words[0] ?? bare }
}

/** "Opus 5.5 · high", with the model the task will run on while it waits and the one it ran on after. */
export function modelLine(task: DispatchTask, _live: boolean): { model: string; effort: string; fallback: boolean } {
  const requested = task.modelRequested ?? task.model
  // MODEL_USED is written before the first attempt too (the default), so it only says what ran
  // once an attempt has: a task cancelled while queued never "switched" anything.
  const ran = task.attempts > 0 && (task.modelUsed ?? '') !== ''
  const used = ran ? task.modelUsed ?? '' : ''
  const model = ran ? used : requested || task.model
  const effort = (ran ? task.effortUsed : '') || task.effortRequested || ''
  return { model, effort, fallback: ran && requested !== '' && used !== requested }
}

/**
 * The notification layer: one receipt mark per channel the task asked for,
 * the channel's glyph followed by what its receipt says. Delivered = the
 * runner's NOTIFIED list (`openclaw message send` returned success for that
 * leg), failed = NOTIFY_FAILED, unknown = the task asked for the channel but
 * result.env holds no receipt for it (a runner older than the receipts, or a
 * leg that never ran). Colour is only the paint: the mark's glyph (✓ ✕ ?)
 * and its words say the same thing, and a mark is green only because a
 * receipt says so — never inferred from the task's own state.
 */
export type ReceiptState = 'sent' | 'failed' | 'unknown' | 'planned'

export function _notifyState(task: DispatchTask, ch: string, live: boolean): ReceiptState {
  if ((task.notifyFailed ?? []).includes(ch)) return 'failed'
  if ((task.notified ?? []).includes(ch)) return 'sent'
  return live ? 'planned' : 'unknown'
}

export function notifyChannels(task: DispatchTask): string[] {
  return [...new Set([...(task.notify ?? []), ...(task.notified ?? []), ...(task.notifyFailed ?? [])])]
}

/**
 * A state's ROLE (2026-09-28 redesign, kcn: 「都是灰色 chip 没有区分度」). A role
 * is a colour AND a bed AND a glyph AND its word, so it survives a dark
 * theme and a greyscale screen: fill vs outline vs dashed edge, and a shape
 * per role. The colours are the host's role tokens (styles.module.css
 * `--tq-run|wait|bad` and the panel's text roles), nothing plugin-picked.
 *
 *   run       blue, filled bed, solid dot      holds its slot and runs
 *   queue     blue, outlined, ring             in line for its agent's lock or a slot
 *   sleep     amber, filled bed, moon          asleep until a quota window resets
 *   wait      amber, outlined, hourglass       any other wait (memory, retry, starting)
 *   done      neutral bed, check               ended, and the model reported done
 *   partial   amber, filled bed, half disc     ended but the work is not done (partial, blocked, no quota)
 *   fail      red, filled bed, cross           execution failed or timed out
 *   off       neutral, outlined, bar           cancelled / not running (patrol between rounds)
 *   unknown   neutral, dashed, question mark   nothing recorded to judge by
 *   fallback  amber, outlined, return arrow    ran on a fallback model (a mark on the model line)
 *
 * Done is deliberately NOT green: it rests on the model's own report. The one
 * green on a row is a delivery receipt (renderNotifyIcons).
 */
export type StateRole = 'run' | 'queue' | 'sleep' | 'wait' | 'done' | 'partial' | 'fail' | 'off' | 'unknown' | 'fallback'

export type GlyphPart = { d: string; paint: 'fill' | 'stroke' }

export const STATE_ROLES: Record<StateRole, { bed: 'fill' | 'edge' | 'dashed'; glyph: readonly GlyphPart[] }> = {
  run: { bed: 'fill', glyph: [{ d: 'M5 2a3 3 0 1 1 0 6a3 3 0 1 1 0-6Z', paint: 'fill' }] },
  queue: { bed: 'edge', glyph: [{ d: 'M5 2.2a2.8 2.8 0 1 1 0 5.6a2.8 2.8 0 1 1 0-5.6Z', paint: 'stroke' }] },
  sleep: { bed: 'fill', glyph: [{ d: 'M6.6 1.8A3.4 3.4 0 1 0 8.4 7.6A2.8 2.8 0 0 1 6.6 1.8Z', paint: 'fill' }] },
  wait: { bed: 'edge', glyph: [{ d: 'M2.8 1.8H7.2M2.8 8.2H7.2M3.4 1.8C3.4 4 6.6 4 6.6 5S3.4 6 3.4 8.2M6.6 1.8C6.6 4 3.4 4 3.4 5S6.6 6 6.6 8.2', paint: 'stroke' }] },
  done: { bed: 'fill', glyph: [{ d: 'M2.3 5.2L4.2 7.1L7.8 3', paint: 'stroke' }] },
  partial: { bed: 'fill', glyph: [{ d: 'M5 2.2a2.8 2.8 0 1 1 0 5.6a2.8 2.8 0 1 1 0-5.6Z', paint: 'stroke' }, { d: 'M5 2.2A2.8 2.8 0 0 0 5 7.8Z', paint: 'fill' }] },
  fail: { bed: 'fill', glyph: [{ d: 'M2.8 2.8L7.2 7.2M7.2 2.8L2.8 7.2', paint: 'stroke' }] },
  off: { bed: 'edge', glyph: [{ d: 'M2.6 5H7.4', paint: 'stroke' }] },
  unknown: { bed: 'dashed', glyph: [{ d: 'M3.5 3.6a1.6 1.6 0 1 1 2.2 1.5C5.2 5.3 5 5.6 5 6.1M5 7.9V8', paint: 'stroke' }] },
  fallback: { bed: 'edge', glyph: [{ d: 'M7.6 5.6A2.7 2.7 0 1 1 6.9 2.9M7.4 1.4V3.3H5.5', paint: 'stroke' }] },
}

export type SlotChip = { text: string; role: StateRole; title?: string }

/** A BalanceTone (the dots, the rail badge) as the role it means. */
export const TONE_ROLE: Record<BalanceTone, StateRole> = { ok: 'run', stale: 'wait', low: 'fail', none: 'off' }

/**
 * An ended task's (or round's) ONE state: the runner's verdict and the
 * model's report folded into the role that most needs the reader. Both axes
 * stay readable: the chip's title says both, the detail layer shows both.
 */
export function _endedState(state: string, outcome: string, t: Translate): SlotChip {
  const title = executionText(state, t) + (outcome === '' && state !== 'ok' ? '' : ' · ' + reportText(outcome, t, state))
  const word = state === 'failed' ? 'failed' : state === 'timeout' ? 'timeout' : state === 'cancelled' ? 'cancelled'
    : state === 'queued' ? 'notStarted' : state === 'quota' ? 'quota' : state === 'blocked' || outcome === 'BLOCKED' ? 'blocked'
      : !['ok', 'partial', 'unverified'].includes(state) ? 'unknown'
        : outcome === 'DONE' ? 'done' : outcome === 'PARTIAL' ? 'partial' : 'noReport'
  const role: StateRole = ({ failed: 'fail', timeout: 'fail', cancelled: 'off', notStarted: 'off', quota: 'partial', blocked: 'partial',
    done: 'done', partial: 'partial', noReport: 'unknown', unknown: 'unknown' } as Record<string, StateRole>)[word]!
  return { text: t('queue.verdict.' + word), role, title }
}

/**
 * THE row grid (2026-09-28 redesign, kcn: 「很多地方都没有对齐显示导致 chip 过多显示杂乱」).
 * Every line of the open panel — a source's head, a section head, a live
 * task, an ended task, a patrol round — sits on the same five tracks
 * (styles.module.css `--tq-grid`), and every fact has ONE fixed cell:
 *
 *            lead   when       took       rest        aside
 *   line 1   glyph  name ─────────────────────────   state chip | value
 *   line 2          model (+ fallback mark) ───────   receipts | tries
 *   line 3          when       took                    cost
 *
 * `when`, `took` and `aside` are fixed widths, so a time, a duration, a cost,
 * a state are on one vertical line in every row that has them; a row without
 * a fact leaves its cell empty, never shifts the next one in. A head
 * (source/section) has a caption line in line 2 instead of facts.
 *
 * RESIDENT_CHIPS: a row carries at most ONE chip, its state. Everything else
 * is words in a fixed cell or a mark (receipts, fallback). What has no cell
 * here is not squeezed in, wrapped or ellipsised: it lives in the detail layer
 * one tap away (the report axis on its own, attempts' budget, the first queue
 * wait, the patrol tag, the session). ROW_KINDS says which facts each kind
 * shows; FACT_CELL where each one sits; the spec checks every rendered row
 * against both, and that no row has a second chip.
 */
export const FACT_ORDER = ['model', 'filed', 'tries', 'receipt', 'when', 'took', 'cost'] as const

export type FactSlot = typeof FACT_ORDER[number]

export type RowKind = 'source' | 'head' | 'task' | 'ended' | 'round'

export const RESIDENT_CHIPS = 1

/** Each fact's one cell: its line and its track (styles.module.css places `[data-tq-fact=…]` accordingly). */
export const FACT_CELL: Record<FactSlot, { line: 2 | 3; track: 'main' | 'full' | 'when' | 'took' | 'aside' }> = {
  model: { line: 2, track: 'main' },
  filed: { line: 2, track: 'full' },
  tries: { line: 2, track: 'aside' },
  receipt: { line: 2, track: 'aside' },
  when: { line: 3, track: 'when' },
  took: { line: 3, track: 'took' },
  cost: { line: 3, track: 'aside' },
}

export const ROW_KINDS: Record<RowKind, { lead: boolean; value: boolean; facts: readonly FactSlot[] }> = {
  // A provider/agent: the sidebar's folded line, and the same line heading its group in the panel.
  source: { lead: true, value: true, facts: [] },
  // A section of the panel (what just ended, patrol).
  head: { lead: true, value: false, facts: [] },
  // Every row fills the shared lead track; a task repeats its executor for scanning within a group.
  task: { lead: true, value: false, facts: ['model', 'tries', 'when', 'took', 'cost'] },
  // Ended tasks are listed across agents, so each carries its executor.
  ended: { lead: true, value: false, facts: ['model', 'receipt', 'when', 'took', 'cost'] },
  // A round uses the patrol section's glyph, just as an ended task carries its executor. Its line 2
  // is what it routed through the filing gate (issues with their severity, digest, comments).
  round: { lead: true, value: false, facts: ['filed', 'when', 'took'] },
}

/** A fact: its words, what a reader hears (the words with their unit), and a voice when it is a warning. */
export type Fact = {
  text: string; said?: string; title?: string; voice?: 'warn' | 'quiet'
  /** Filing evidence: words/links, not additional state chips. Same text in chat. */
  parts?: Array<{ text: string; severity?: string; href?: string }>
  /** A mark after the words: the fallback model's return arrow (a role glyph, drawn by the renderer). */
  mark?: { role: StateRole; text: string; title: string } | null
  /** Delivery receipts, one per channel, in place of words (the renderer draws each channel's glyph). */
  receipts?: Array<{ ch: string; state: ReceiptState }> | null
}

/** What the lead track shows: an executor, a section, or a source's own glyph. Drawn by the renderer. */
export type RowLead = { agent: string; size?: number } | { section: 'recent' | 'patrol' } | { source: PanelSource }

export type RowView = {
  kind: RowKind
  key: string
  lead?: RowLead | null
  name: string
  value?: { text: string; tone: BalanceTone; level: UsedLevel | null } | null
  state: SlotChip | null
  facts: Partial<Record<FactSlot, Fact | null>>
  /** A head's line 2: what the source is (plan · slots · pool) or what a section is doing. Words, never chips. */
  caption?: Array<{ text: string; voice?: 'warn'; title?: string }>
  /** Opens the detail layer; a row without one is not a button. */
  open?: () => void
  attrs?: Record<string, string | undefined>
}

/** A clock for a fixed cell: "19:40" today, "10/4 19:40" another day. */
export function clockOf(ms: number, now: number): string {
  const d = new Date(ms)
  const n = new Date(now)
  const hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
  return d.toDateString() === n.toDateString() ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

/**
 * A live task's state chip: the short word (the group head already names the
 * agent), its role, and the whole phrase (_taskStatus: which lock, the wake
 * and the window it waits for) as the chip's title. A wake time is the 'when'
 * cell, where an ended task keeps when it ended.
 */
export function _taskState(task: DispatchTask, t: Translate, now: number = Date.now(),
  windows?: ReadonlyArray<{ resetAtMs?: number | null }>): { chip: SlotChip; when: Fact | null } {
  const status = _taskStatus(task, t, now, windows)
  const stamp = (ms: number): string => resetStampOf(t, { resetAt: '', resetAtMs: ms }, now)
  // The when cell: the wake of a sleeping task, else when it started (or joined the queue).
  const since = task.startedAtMs ?? task.queuedAtMs
  const when: Fact | null = (task.waiting === 'quota' || task.waiting === 'retry') && task.wakeAtMs !== null
    ? { text: clockOf(task.wakeAtMs, now), said: t('queue.fact.wakes', { time: stamp(task.wakeAtMs) }), voice: 'warn' }
    : since != null ? { text: clockOf(since, now), said: t(_slotOf(task) === null ? 'queue.fact.queuedAt' : 'queue.fact.startedAt', { time: stamp(since) }) } : null
  const slot = _slotOf(task)
  const word = task.cancelling ? 'cancelling'
    : task.waiting === 'lock' ? (task.position ? 'queuedAt' : 'queued')
      : task.waiting === 'slot' ? 'slot' : task.waiting === 'memory' ? 'memory'
        : task.waiting === 'quota' ? 'quota' : task.waiting === 'retry' ? 'retry'
          : slot === null ? 'starting' : slot.slot === '1' ? 'running' : 'runningSlot'
  const role: StateRole = word === 'running' || word === 'runningSlot' ? 'run'
    : word === 'queued' || word === 'queuedAt' || word === 'slot' ? 'queue'
      : word === 'quota' ? 'sleep' : word === 'cancelling' ? 'off' : 'wait'
  return { chip: { text: t('queue.tag.' + word, { n: task.position ?? 0, slot: slot?.slot ?? '' }), role, title: status.text }, when }
}

/** The model cell: the full model name and effort, and the fallback mark when it ran on another model. */
export function modelFact(task: DispatchTask, live: boolean, t: Translate): Fact | null {
  const m = modelLine(task, live)
  if (m.model === '') return null
  const text = _modelView(m.model).label + (m.effort ? ' · ' + m.effort : '')
  const requested = task.modelRequested ?? ''
  return {
    text, title: m.model,
    said: text + (m.fallback ? ' · ' + t('queue.fallbackTitle', { requested: _modelView(requested).label }) : ''),
    mark: m.fallback ? { role: 'fallback', text: t('queue.fallbackMark'), title: t('queue.fallbackTitle', { requested: _modelView(requested).label }) } : null,
  }
}

/** The cost cell: the API-price estimate, 'free', or '—' when the model has no price row (title says which). */
export function costFact(task: DispatchTask, t: Translate, live: boolean): Fact | null {
  const cost = _costOf(task)
  if (cost === null) return null
  const legend = t('queue.chip.cost') + (live ? ' · ' + t('queue.d.costLive') : '')
  return cost.kind === 'unpriced'
    ? { text: '—', said: t('queue.chip.unpriced'), title: t('queue.chip.unpriced') + ' · ' + legend, voice: 'quiet' }
    : { text: cost.kind === 'free' ? t('queue.chip.free') : cost.short, said: legend + ' ' + cost.short, title: legend }
}

/** A live task as a row: state chip; model, tries; when it wakes, how long, cost so far. */
export function taskRow(task: DispatchTask, t: Translate, now: number, open: (id: string) => void,
  windows?: ReadonlyArray<{ resetAtMs?: number | null }>): RowView {
  const state = _taskState(task, t, now, windows)
  const since = task.queuedAtMs ?? task.startedAtMs
  const running = _slotOf(task) !== null
  const tries = [task.attempts > 1 ? t('queue.attempt', { n: task.attempts }) : null, task.stalls ? t('queue.stalls', { n: task.stalls }) : null]
    .filter((part): part is string => part !== null)
  return {
    kind: 'task',
    key: task.id,
    lead: { agent: task.agent, size: 12 },
    name: task.name,
    state: state.chip,
    facts: {
      model: modelFact(task, true, t),
      tries: tries.length === 0 ? null : { text: tries.join(' · '), voice: task.stalls ? 'warn' : undefined },
      when: state.when,
      took: since == null ? null
        : { text: durationOf(t, now - since), said: t(running ? 'queue.chip.elapsed' : 'queue.chip.waiting', { time: durationOf(t, now - since) }) },
      cost: costFact(task, t, true),
    },
    open: () => { open(task.id) },
    attrs: { 'data-tq-task': task.id, 'data-tq-waiting': task.waiting },
  }
}

/** An ended task as a row: its one verdict; model and receipts; when, how long, what it cost. */
export function endedRow(task: DispatchTask, t: Translate, now: number, open: (id: string) => void): RowView {
  const stamp = (ms: number): string => resetStampOf(t, { resetAt: '', resetAtMs: ms }, now)
  return {
    kind: 'ended',
    key: task.id,
    lead: { agent: task.agent, size: 12 },
    name: task.name,
    state: _endedState(task.state, task.outcome, t),
    facts: {
      model: modelFact(task, false, t),
      receipt: notifyChannels(task).length === 0 ? null : { text: '', receipts: notifyChannels(task).map((ch) => ({ ch, state: _notifyState(task, ch, false) })),
        said: notifyChannels(task).map((ch) => t('queue.notify.' + _notifyState(task, ch, false), { ch: t('queue.ch.' + ch) })).join(' · ') },
      when: task.updatedAtMs === null ? null : { text: agoOf(t, now - task.updatedAtMs), title: t('queue.d.endedAt') + ' ' + stamp(task.updatedAtMs) },
      took: task.startedAtMs === null || task.updatedAtMs === null ? null
        : { text: durationOf(t, task.updatedAtMs - task.startedAtMs), said: t('queue.chip.took', { time: durationOf(t, task.updatedAtMs - task.startedAtMs) }) },
      cost: costFact(task, t, false),
    },
    open: () => { open(task.id) },
    attrs: { 'data-tq-task': task.id, 'data-tq-waiting': '' },
  }
}

/**
 * What a round routed through the filing gate, from the third `/` field patrol.sh writes
 * (`P1#2240 P2#2241 +2 digest +1 comment`, 2026-10-01): each issue with its severity, how many
 * findings went to the digest, how many were added to an issue on the same root cause. A P0 is
 * said as a warning. Null when the round filed nothing (or ran before the field existed).
 */
export function roundFiled(filed: string, t: Translate): Fact | null {
  const issues = [...filed.matchAll(/\b(P[0-3])#(\d+)/g)].map((m) => ({ sev: m[1]!, n: m[2]! }))
  const digest = Number(/\+(\d+) digest\b/.exec(filed)?.[1] ?? 0)
  const comment = Number(/\+(\d+) comment\b/.exec(filed)?.[1] ?? 0)
  const parts: NonNullable<Fact['parts']> = [
    ...(issues.length > 0 ? [{ text: t('queue.round.issueCount', { n: issues.length }) }] : []),
    ...issues.map(({ sev, n }) => ({ text: `${sev} #${n}`, severity: sev, href: `https://github.com/KCNyu/clawock/issues/${n}` })),
    ...(digest > 0 ? [{ text: t('queue.round.digest', { n: String(digest) }) }] : []),
    ...(comment > 0 ? [{ text: t('queue.round.comment', { n: String(comment) }) }] : []),
  ]
  if (parts.length === 0) return null
  return {
    text: parts.map((part) => part.text).join(' · '),
    parts,
    said: t('queue.round.filed', { what: parts.map((part) => part.text).join(', ') }),
    title: filed,
    voice: issues.some(({ sev }) => sev === 'P0') ? 'warn' : undefined,
  }
}

/** A finished patrol round as a row (rounds.tsv: `[preempted:|yielded:]STATE[/OUTCOME[/FILED]]`). */
export function roundRow(round: PatrolRound, t: Translate, now: number): RowView {
  const how = /^(preempted|yielded):/.exec(round.result)?.[1] ?? ''
  const [state = '', outcome = '', filed = ''] = round.result.slice(how === '' ? 0 : how.length + 1).split('/')
  const ended = localStampMs(round.endedAt)
  return {
    kind: 'round',
    key: 'round-' + round.endedAt + round.round,
    lead: { section: 'patrol' },
    name: round.axis === '' ? round.round : t('queue.round.name', { round: round.round, axis: round.axis }),
    state: how === 'preempted' ? { text: t('queue.round.preempted'), role: 'partial', title: round.result }
      : how === 'yielded' ? { text: t('queue.round.yielded'), role: 'off', title: round.result }
        : { ..._endedState(state, outcome, t), title: round.result },
    facts: {
      filed: roundFiled(filed, t),
      when: ended === null ? null : { text: agoOf(t, now - ended), title: t('queue.d.endedAt') + ' ' + round.endedAt },
      took: round.seconds === null ? null : { text: durationOf(t, round.seconds * 1000), said: t('queue.chip.took', { time: durationOf(t, round.seconds * 1000) }) },
    },
    attrs: { 'data-tq-round': round.round },
  }
}

/** Patrol history is one semantic group, regardless of individual outcomes.
 * Up to four rounds stay visible; longer history keeps the newest round and
 * one disclosure for all older rounds, preserving chronological order.
 * Distinct ended tasks remain visible (the host already caps that list).
 */
export const FLAT_ROUNDS = 4
export const RESIDENT_ROUNDS = 1

/** A task the queue may reorder: waiting for the lock, current runner, not patrol, not protected. */
export const reorderable = (task: DispatchTask): boolean =>
  task.waiting === 'lock' && !task.patrol && !task.protected && (task.runnerApi ?? 1) >= 2

/** Live tasks of one agent in the order they hold / will take its lock. */
export function groupOrder(tasks: DispatchTask[], queue: AgentQueue | undefined): DispatchTask[] {
  const rank = (task: DispatchTask): number => {
    if (task.slot !== '' || (queue?.holder === task.id)) return 0
    const at = queue?.order.indexOf(task.id) ?? -1
    return at >= 0 ? 1 + at : 1000
  }
  return [...tasks].sort((a, b) => rank(a) - rank(b) || (a.queuedAtMs ?? a.startedAtMs ?? 0) - (b.queuedAtMs ?? b.startedAtMs ?? 0))
}

// ---- The provider panel (2026-09-27): quota and queue as one cell -------------------------

/** One line of the fused cell: a provider, an agent, or both joined (see providers.ts). */
export type PanelSource = {
  /** Stable key: the provider id, else the agent id. */
  key: string
  label: string
  join: ProviderJoin | null
  provider: BalancesResult['providers'][number] | null
  agent: string | null
}

/**
 * The panel's sources in providers.ts's order (sourceRank: the paid,
 * exclusive allowances first, the free pool last, anything without a row
 * among the paid ones). A joined row with a dispatch agent renders with its
 * queue; an agent the queue reports that no row names gets a line of its own;
 * a provider without an agent renders when the balance answer has it. Agent
 * rows need a dispatcher (C3 ②: without one only providers render); a
 * provider row needs its provider.
 */
export function _panelSources(providers: BalancesResult['providers'], queue: TaskQueueResult | null): PanelSource[] {
  const dispatcher = queue !== null && queue.available
  const byId = new Map(providers.map((row) => [row.provider, row] as const))
  const out: PanelSource[] = []
  const placed = new Set<string>()
  for (const join of PROVIDER_JOIN) {
    const provider = join.provider === null ? null : byId.get(join.provider) ?? null
    if (join.agent === null ? provider === null : provider === null && !dispatcher) continue
    const key = join.provider ?? join.agent!
    out.push({ key, label: provider?.label ?? _agentLabel(join.agent ?? key), join, provider, agent: dispatcher ? join.agent : null })
    placed.add(key)
  }
  if (dispatcher) {
    const agents = [...new Set([...(queue!.slotLimits ?? []).map((l) => l.agent), ...queue!.active.map((t) => t.agent)])]
    for (const agent of agents) {
      if (agent === '' || placed.has(agent) || PROVIDER_JOIN.some((j) => j.agent === agent)) continue
      out.push({ key: agent, label: _agentLabel(agent), join: null, provider: null, agent })
      placed.add(agent)
    }
  }
  for (const provider of providers) {
    if (placed.has(provider.provider)) continue
    out.push({ key: provider.provider, label: provider.label, join: null, provider, agent: null })
  }
  return out.map((source, at) => ({ source, at, rank: sourceRank({ provider: source.provider?.provider ?? source.join?.provider, agent: source.agent ?? source.join?.agent }) }))
    .sort((a, b) => a.rank - b.rank || a.at - b.at)
    .map(({ source }) => source)
}

/** Where the free pool is: the model the latest opencode task used, and the next one in file order. */
export function _poolPosition(result: TaskQueueResult | null): { current: string; next: string; fromOrder: boolean } | null {
  const pool = result?.opencodePool ?? []
  const tasks = [...(result?.active ?? []), ...(result?.recent ?? [])].filter((task) => task.agent === 'opencode')
  const latest = tasks.find((task) => (task.modelUsed ?? '') !== '' && task.attempts > 0)
  const used = latest?.modelUsed ?? ''
  if (pool.length === 0) return used === '' ? null : { current: used, next: '', fromOrder: false }
  const at = pool.indexOf(used)
  if (at < 0) return { current: pool[0]!, next: pool[1] ?? pool[0]!, fromOrder: true }
  return { current: used, next: pool[(at + 1) % pool.length]!, fromOrder: false }
}

/**
 * A queue's state chip, the same on the folded line and on its group's head:
 * the ONE state that most needs the reader, with its count — asleep on quota,
 * then queued behind the lock or a slot, then another wait, then running. A
 * wait outranks running because a queue implies its holder runs. Idle is no
 * chip at all. `text` is every count (the line's aria-label and title).
 */
export function _queueState(t: Translate, tasks: DispatchTask[]): { text: string; chip: SlotChip | null } {
  const run = tasks.filter((task) => task.slot !== '').length
  const queued = tasks.filter(queuedFor).length
  const quota = tasks.filter((task) => task.waiting === 'quota').length
  const other = tasks.filter((task) => task.waiting === 'retry' || task.waiting === 'memory').length
  const parts: Array<[string, number, StateRole]> = [
    ['panel.q.quota', quota, 'sleep'], ['panel.q.queued', queued, 'queue'], ['panel.q.wait', other, 'wait'], ['panel.q.run', run, 'run'],
  ]
  const present = parts.filter(([, n]) => n > 0)
  const text = present.length === 0 ? t('panel.q.idle') : present.map(([key, n]) => t(key, { n })).join(' · ')
  const top = present[0]
  return { text, chip: top === undefined ? null : { text: t(top[0], { n: top[1] }), role: top[2], title: text } }
}

/**
 * A source's value column: the allowance headline (used % of the first
 * window, or the balance) and its tone; for the free pool, "free" — where
 * the rotation stands is a fact of its group. `reset` (the headline window's,
 * resetStampOf) is read out in the line's label; the clocks themselves are
 * drawn once, on the group's window bars.
 */
export function sourceReading(source: PanelSource, row: BalanceRow | undefined, queue: TaskQueueResult | null, t: Translate): {
  value: string; reset: string | null; tone: BalanceTone; level: UsedLevel | null; title: string
} {
  if (row !== undefined) return { value: row.view.value, reset: row.view.reset === null ? null : '↻ ' + row.view.reset, tone: row.view.tone, level: row.view.level, title: row.view.title }
  if (source.join?.kind === 'pool') {
    const pos = _poolPosition(queue)
    const size = queue?.opencodePool?.length ?? 0
    return { value: t('panel.free'), reset: null, tone: 'none', level: null,
      title: (pos === null ? t('panel.poolUnread') : t('panel.pool', { current: pos.current, next: pos.next || '—' }) + (pos.fromOrder ? t('panel.poolOrder') : ''))
        + (size > 1 ? ' · ' + t('panel.poolSwap', { n: size }) : '') }
  }
  return { value: '—', reset: null, tone: 'none', level: null, title: '' }
}

/** The patrol phase's role: running blue, giving way amber (a wait), between rounds off, stopped red. */
export const PATROL_ROLE: Record<string, StateRole> = { running: 'run', yielding: 'wait', waiting: 'off', stopped: 'fail', unknown: 'unknown' }

/** rounds.tsv's local "YYYY-MM-DD HH:MM:SS" as epoch ms, null when it is not one. */
export function localStampMs(stamp: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(stamp.trim())
  return m ? new Date(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]!, +(m[6] ?? 0)).getTime() : null
}

/**
 * Why the supervisor gives way, read off its journal line. The patterns are
 * the reasons the supervisor can actually write — `others_need_slot` and
 * `round_blocks_someone` in ops/host/patrol.sh, `memory_pressure_reason` in
 * ops/host/agent-dispatch/resource-pressure.sh — and the spec instantiates
 * every one of those templates from the files themselves (#2071):
 *   manual = a manual task waits for the lock or a slot the patrol would use
 *            (the id is that task, shown so the reader knows whom it waits for);
 *   slot   = the patrol's own admission: its agent's run slots are all taken;
 *   memory = admission deferred on memory headroom, pressure or telemetry.
 * `asking <round> to wrap up …: <demand>` is the grace before a preemption.
 */
export function _patrolReason(detail: string): { kind: 'manual' | 'slot' | 'memory' | 'memoryUnread' | 'other'; task: string; wrapUp: boolean } {
  const wrap = /^asking \S+ to wrap up within \d+s: (.*)$/.exec(detail)
  const why = wrap?.[1] ?? detail.replace(/^(?:waiting: |preempting \S+?(?: after a \d+s wrap-up grace)?: )/, '')
  const manual = /^(\S+) is (?:waiting for (?:an \S+ run slot|its agent lock|the \S+ lock)|queued behind the round's \S+ lock)/.exec(why)
  const kind = manual ? 'manual'
    : /^the \S+ run slot is busy$/.test(why) ? 'slot'
      : /^memory telemetry unavailable/.test(why) ? 'memoryUnread'
        : /^memory (?:headroom low|pressure):/.test(why) ? 'memory' : 'other'
  return { kind, task: manual?.[1] ?? '', wrapUp: wrap !== null }
}

/** The supervisor's live status as the patrol head's caption: when the next round is, what it runs now, or why it gives way. */
export function patrolCaption(result: TaskQueueResult, t: Translate, now: number): NonNullable<RowView['caption']> {
  const patrol = result.patrol
  const reason = _patrolReason(patrol.detail)
  const current = result.active.find((task) => task.id === patrol.round)
  const dispatched = /round (\S+) \(([^)]+)\)/.exec(patrol.detail)
  const axis = dispatched?.[2] ?? /^patrol-(.+)-\d{8}-\d{6}$/.exec(patrol.round)?.[1] ?? ''
  const out: NonNullable<RowView['caption']> = []
  if (patrol.phase === 'waiting' && patrol.untilMs !== null) {
    out.push({ text: t('queue.patrolState.waitingUntil', { time: resetStampOf(t, { resetAt: '', resetAtMs: patrol.untilMs }, now) }) })
    out.push({ text: t(patrol.untilMs > now ? 'queue.patrol.remaining' : 'queue.patrol.due', {
      time: durationOf(t, Math.max(0, patrol.untilMs - now)),
    }) })
  }
  if (patrol.phase === 'yielding' || reason.wrapUp) {
    const why = reason.kind === 'manual' ? t('queue.patrol.giveWay') : reason.kind === 'slot' ? t('queue.patrol.waitSlot')
      : reason.kind === 'memory' ? t('queue.patrol.memory') : reason.kind === 'memoryUnread' ? t('queue.patrol.memoryUnread')
        : t('queue.patrol.otherReason')
    if (reason.wrapUp) out.push({ text: t('queue.patrol.wrapUp'), voice: 'warn' })
    out.push({ text: why, voice: 'warn', title: patrol.detail })
    if (reason.task !== '') out.push({ text: reason.task, title: t('queue.patrol.forTask', { id: reason.task }) })
  }
  if (patrol.phase === 'running' || (patrol.phase === 'yielding' && current !== undefined)) {
    if (dispatched || axis) out.push({ text: dispatched ? t('queue.round.name', { round: dispatched[1]!, axis }) : axis, title: patrol.round })
    if (current?.startedAtMs != null) out.push({ text: t('queue.chip.elapsed', { time: durationOf(t, now - current.startedAtMs) }) })
    // The executor's row already shows the model. Use this space for an actual wait.
    if (current !== undefined && current.waiting !== '') out.push({ text: _taskStatus(current, t, now).text, voice: 'warn' })
  }
  return out
}

/** The cost cell: an API-price estimate, 'free', or '—' when the model is unpriced; null when nothing was recorded. */
export function _costOf(task: DispatchTask): { short: string; kind: 'usd' | 'free' | 'unpriced' } | null {
  if (task.tokensTotal == null) return null
  const cost = task.costUsd ?? ''
  if (cost === 'free') return { short: 'free', kind: 'free' }
  if (/^\d+(\.\d+)?$/.test(cost)) return { short: '$' + cost, kind: 'usd' }
  return { short: '—', kind: 'unpriced' }
}

/**
 * A source as a row: the sidebar's folded line and its group's head in the
 * panel are this one view (the same glyph, name and value in the same
 * columns), so the line a reader taps is the line the panel opens on. The
 * folded line adds the queue's one state chip (its tasks are not on screen);
 * the head adds its caption — the plan, the run slots, the pool — in words.
 */
export function sourceView(source: PanelSource, row: BalanceRow | undefined, result: TaskQueueResult | null, t: Translate): RowView & { reading: ReturnType<typeof sourceReading>; queue: ReturnType<typeof _queueState> | null } {
  const reading = sourceReading(source, row, result, t)
  const queue = source.agent === null || result === null || !result.available ? null
    : _queueState(t, result.active.filter((task) => task.agent === source.agent))
  const lane = source.agent === null || result === null || !result.available ? undefined : _slotLanes(result).find((l) => l.agent === source.agent)
  const pool = source.join?.kind === 'pool' ? _poolPosition(result) : null
  const poolSize = result?.opencodePool?.length ?? 0
  return {
    kind: 'source',
    key: source.key,
    lead: { source },
    name: source.label,
    value: { text: reading.value, tone: reading.tone, level: reading.level },
    state: queue?.chip ?? null,
    facts: {},
    caption: [
      { text: source.join?.plan === undefined ? '' : t(source.join.plan) },
      lane === undefined ? { text: '' }
        : { text: t('queue.slotCount', { used: lane.used, max: lane.max ?? '—' }), voice: lane.tone === 'stale' ? 'warn' : undefined, title: t('queue.lanesTitle') },
      // The free pool is one source for all its models: where the rotation is, and how many stand in for one another.
      source.join?.kind !== 'pool' ? { text: '' } : pool === null ? { text: t('panel.poolUnread') }
        : { text: t('panel.pool', { current: _modelView(pool.current).label, next: pool.next === '' ? '—' : _modelView(pool.next).label }) + (pool.fromOrder ? t('panel.poolOrder') : ''), title: reading.title },
      poolSize > 1 && source.join?.kind === 'pool' ? { text: t('panel.poolSize', { n: poolSize }), title: t('panel.poolSwap', { n: poolSize }) } : { text: '' },
    ],
    reading,
    queue,
  }
}

// ---- The open panel as data (2026-09-29) -------------------------------------------------
// Everything the provider panel shows, decided once: which groups in which order, each
// group's head, allowance, notes and task rows; what just ended; patrol; the ops footer.
// client.ts draws it in the sidebar; text.ts prints the same model as plain text for chat
// (the OpenClaw `/dispatch-list` command). A rule about WHAT the cell says belongs here,
// never in one of the two renderers.

/** Provider rows with their display projection: what every surface of the cell reads. */
export function balanceRows(result: BalancesResult | null, t: Translate, now: number): BalanceRow[] {
  return (result?.providers ?? []).map((provider) => ({
    ...provider,
    view: _rowDisplay(provider.result, t, now),
    note: _balanceNote(provider.result, t),
  }))
}

/** The provider windows of an agent (a quota wait names the reset it waits for). */
export function agentWindows(rows: ReadonlyMap<string, BalanceRow>, agent: string): ReadonlyArray<{ resetAtMs?: number | null }> | undefined {
  const join = PROVIDER_JOIN.find((j) => j.agent === agent)
  const row = join?.provider ? rows.get(join.provider) : undefined
  return row?.result.snapshot?.windows
}

/**
 * The per-provider detail under its headline: quota providers get one line
 * per window — label / used / reset — so the 5h and week resets scan as a
 * column instead of drowning in a sentence. Money rows keep their
 * granted/topped-up split. A note does NOT suppress this detail when
 * readable windows exist (kcn 反馈 #908: 变色只改颜色,绝不动信息量)——
 * the watermark/stale caption rides along; only data-less abnormal rows
 * (unconfigured / fetch-failed) speak through the note alone.
 */
export type AllowanceDetail =
  | { kind: 'windows'; windows: Array<{ label: string; percent: number | null; fill: number | null; reset: string; state: UsedLevel | 'stale' }> }
  | { kind: 'text'; text: string }
  | null

export function allowanceDetail(row: BalanceRow, t: Translate, now: number): AllowanceDetail {
  const wins = row.result.snapshot === null ? [] : windowsOf(t, row.result, now)
  if (wins.length > 0) {
    // percent 是已使用方向(kcn 定的口径),填充按用量档位走(kcn 配色):低=绿、≥60% 黄、
    // ≥80% 红,stale 黄盖过(数字不可信优先于用量档)。档位只染色——label/百分比/reset
    // 在任何档位都完整保留。
    return {
      kind: 'windows',
      windows: wins.map((w) => {
        const fill = w.percent === null ? null : Math.max(0, Math.min(100, Math.round(w.percent)))
        return { label: w.label, percent: w.percent, fill, reset: w.reset, state: row.view.tone === 'stale' ? 'stale' : _usedLevel(fill, row.result.threshold) }
      }),
    }
  }
  // 无窗的异常行(未配置/拉取失败)note 即全部内容,不再走正文重复一遍。
  if (row.note !== null) return null
  const title = row.view.title
  if (title === '') return null
  // Money rows: drop the leading 'API 余额' label — the row already says who.
  const prefix = t('balance.apiBalance') + ' · '
  return { kind: 'text', text: title.startsWith(prefix) ? title.slice(prefix.length) : title }
}

/**
 * One provider group of the open panel (2026-09-28, kcn: 「任务现在和 provider
 * 那个上下好像都不明显了」). Two levels, never mixed: the allowance is the
 * group's head (name and reading, the caption, the window lines); the queue
 * that allowance feeds is a list below it, one step down.
 */
export type PanelGroup = {
  source: PanelSource
  /** The group's head row: the source's folded line without its state chip (its tasks are right below). */
  head: RowView
  row: BalanceRow | undefined
  /** Abnormal balance rows say so, with the last good reading and when it was taken (① stale). */
  balanceNote: string | null
  detail: AllowanceDetail
  /** The lock held by a task of another listing, a quota stop: words under the head. */
  notes: string[]
  /** Live tasks of the agent, in the order they hold / will take its lock. */
  tasks: Array<{ task: DispatchTask; row: RowView }>
}

export function panelGroup(source: PanelSource, result: TaskQueueResult | null, rows: ReadonlyMap<string, BalanceRow>, t: Translate, now: number,
  open: (id: string) => void): PanelGroup {
  const row = source.provider === null ? undefined : rows.get(source.provider.provider)
  const agent = source.agent
  const tasks = agent === null || result === null ? [] : result.active.filter((task) => task.agent === agent)
  const queue = agent === null ? undefined : (result?.queues ?? []).find((q) => q.agent === agent)
  const notes: string[] = []
  if (queue?.held && tasks.every((task) => task.id !== queue.holder)) {
    notes.push(queue.holder !== '' ? t('queue.holderOther', { id: queue.holder }) : t('queue.holderUnnamed'))
  }
  if (queue?.quotaUntilMs) notes.push(t('queue.quotaHint', { time: resetStampOf(t, { resetAt: '', resetAtMs: queue.quotaUntilMs }, now), by: queue.quotaBy }))
  const snapshotAt = row?.result.snapshot?.asOf ? Date.parse(row.result.snapshot.asOf) : NaN
  const balanceNote = row === undefined || row.note === null ? null
    : row.result.status === 'stale' && Number.isFinite(snapshotAt)
      ? t('panel.staleAt', { message: row.result.message ?? '—', time: resetStampOf(t, { resetAt: '', resetAtMs: snapshotAt }, now) })
      : row.note
  const { reading: _reading, queue: _queue, ...view } = sourceView(source, row, result, t)
  return {
    source,
    head: { ...view, state: null, key: 'head-' + source.key, attrs: { 'data-pp-head': source.key } },
    row,
    balanceNote,
    detail: row === undefined ? null : allowanceDetail(row, t, now),
    notes,
    tasks: groupOrder(tasks, queue).map((task) => ({ task, row: taskRow(task, t, now, open, agentWindows(rows, task.agent)) })),
  }
}

/** Ended work, newest first across agents: every ended task is resident (see RESIDENT_ROUNDS). */
export function recentSection(result: TaskQueueResult | null, t: Translate, now: number, open: (id: string) => void): { head: RowView; rows: RowView[] } | null {
  if (result === null || !result.available || result.recent.length === 0) return null
  return {
    head: { kind: 'head', key: 'head-recent', lead: { section: 'recent' }, name: t('queue.recentHeading'), state: null, facts: {} },
    rows: result.recent.map((task) => endedRow(task, t, now, open)),
  }
}

/**
 * Patrol: a section head (the phase as its state chip, the live status as its
 * caption), and one chronological history group. The raw supervisor journal
 * is not a task conclusion; the head already projects its useful status.
 */
export function patrolSection(result: TaskQueueResult | null, t: Translate, now: number): { head: RowView; rounds: RowView[] } | null {
  if (result === null || !result.available) return null
  const patrol = result.patrol
  return {
    head: {
      kind: 'head', key: 'head-patrol', lead: { section: 'patrol' }, name: t('queue.patrolHeading'),
      state: { text: t('queue.patrolState.' + patrol.phase), role: PATROL_ROLE[patrol.phase] ?? 'unknown', title: patrolPhraseOf(result, t, now) },
      facts: {},
      caption: patrolCaption(result, t, now),
      attrs: { 'data-tq-patrol': patrol.phase },
    },
    rounds: (patrol.rounds ?? []).map((round) => roundRow(round, t, now)),
  }
}

/** The ops entry's footer: its version and runner api, or why it is missing / skewed. */
export function opsFooter(result: TaskQueueResult | null, t: Translate): { text: string; bad: boolean; version: string } | null {
  if (result === null || !result.available || result.ops === undefined) return null
  const skew = opsProblem(result, t)
  const ops = result.ops
  return { text: skew !== '' ? skew : t('queue.ops.footer', { v: ops.version, runner: ops.runnerApi }), bad: skew !== '', version: ops.available ? ops.version : 'missing' }
}

/**
 * Why a half of the cell is not (fully) there: a failed or stale queue read, a
 * host without the dispatcher, a failed balance read. `error` is a transport
 * failure (the fetch never answered); an in-band failure arrives in the result.
 */
export function panelNotices(input: { queue: TaskQueueResult | null; queueError: string | null; balances: BalancesResult | null; balanceError: string | null; rowCount: number },
  t: Translate): Array<{ key: string; text: string; bad: boolean }> {
  const { queue, queueError, balances, balanceError, rowCount } = input
  const queueProblem = queueError ?? (queue !== null && (queue.status === 'stale' || queue.status === 'failed') ? queue.message : null)
  const out: Array<{ key: string; text: string; bad: boolean }> = []
  if (queueProblem !== null && queueProblem !== '') {
    // 'failed' is a cold in-band failure: nothing was ever read, so there is no "last read" to show (#2053).
    out.push({ key: 'qerr', bad: true, text: t(queue === null || queue.status === 'failed' ? 'queue.readFailed' : 'queue.staleWith', { message: queueProblem }) })
  }
  if (queueProblem === null && queue === null) out.push({ key: 'qloading', bad: false, text: t('panel.queueLoading') })
  if (queueProblem === null && queue !== null && !queue.available) out.push({ key: 'qunavailable', bad: false, text: t('panel.queueUnavailable') })
  if (balanceError !== null) {
    out.push({ key: 'berr', bad: true, text: rowCount === 0 ? t('balance.readFailed', { message: balanceError }) : t('balance.staleWith', { message: balanceError }) })
  }
  return out
}

/** The whole open panel as data: title, notices, a group per source, recent, patrol, footer. */
export type PanelModel = {
  title: string
  notices: Array<{ key: string; text: string; bad: boolean }>
  /** Nothing to show yet (or at all) — said instead of the groups. */
  empty: string | null
  groups: PanelGroup[]
  recent: ReturnType<typeof recentSection>
  patrol: ReturnType<typeof patrolSection>
  footer: ReturnType<typeof opsFooter>
}

/** Both halves of the cell as one read left them: an answer, or why there is none. */
export type PanelInput = { balances: BalancesResult | null; balanceError: string | null; queue: TaskQueueResult | null; queueError: string | null }

export function panelModel(input: PanelInput,
  t: Translate, now: number, open: (id: string) => void = () => {}): PanelModel {
  const rows = balanceRows(input.balances, t, now)
  const byProvider = new Map(rows.map((row) => [row.provider, row] as const))
  const sources = _panelSources(input.balances?.providers ?? [], input.queue)
  return {
    title: t('panel.title'),
    notices: panelNotices({ ...input, rowCount: rows.length }, t),
    empty: sources.length === 0 && input.balanceError === null ? (input.balances === null ? t('balance.reading') : t('panel.noSources')) : null,
    groups: sources.map((source) => panelGroup(source, input.queue, byProvider, t, now, open)),
    recent: recentSection(input.queue, t, now, open),
    patrol: patrolSection(input.queue, t, now),
    footer: opsFooter(input.queue, t),
  }
}
