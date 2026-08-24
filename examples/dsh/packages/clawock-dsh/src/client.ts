/**
 * clawock-dsh browser bundle: the Decision Mind conversation-view tab.
 *
 * One organic view — the decision trace: real fills as the spine, the shared
 * decision ledger (memory/decisions.jsonl) soft-paired (±3 days) as the "why"
 * layer, and canonical bar closes (memory/bars/, never snapshot current_price
 * — see readBarCloses) as the T+1 verdict. Fills without a decision say so
 * explicitly. Visual language: modern SaaS on DSH tokens, with the P&L
 * figure as the focal number and a GitHub-style vertical timeline in the
 * expandable detail.
 *
 * Official client discipline (`packages/client/AGENTS.md` in the Harness
 * tree), all four rules this file has to satisfy:
 *   - registration happens inside `apply` through `ctx.slots.register`, and
 *     the module body has no side effects — styles arrive as a CSS Modules
 *     import, whose `<style data-plugin>` tag the loader owns and removes on
 *     unload;
 *   - the store is an exported `createDecisionMindStore()` factory called in
 *     `apply`, never a module-level handle (a disguised singleton);
 *   - live data reaches render through the props shares only, so the trace
 *     cache lives in the apply closure and is read through `inject`;
 *   - components take named props and the wire types from `./types.ts`.
 */

import { TYPERT_REMOTE } from 'clawock-dsh/remote'
import type { Context } from '@deepseek-ai/cordis'
import type { TypertClientRemote, TypertRemoteContribution } from '@deepseek-ai/dsh-typert-protocol'
import type { PropsStore } from '@deepseek-ai/dsh-client-ui-slots'
import { defineStore } from '@deepseek-ai/dsh-client-runtime/client'
// The loader module table provides React at runtime; the types come from the
// @types/react devDependency.
import * as React from 'react'
import styles from './styles.module.css'
import type { BalanceResult, BalancesResult, EnrichedTrade, TraceDecision, TraceT1, TracesResult } from './types.ts'

const { createElement, useEffect, useRef, useState } = React

/**
 * The one React boundary in this file. `createElement` is variadic over
 * heterogeneous children and its overload set does not survive being taken as
 * a plain value; everything downstream of `h` is named and typed, and no
 * business type in this module is `any`.
 */
type ElementProps = Record<string, unknown> | null
const h = createElement as (type: unknown, props?: ElementProps, ...children: unknown[]) => React.ReactElement

/** Class tokens declared in styles.module.css, mapped to their hashed names. */
function cx(...tokens: (string | false | null | undefined)[]): string {
  const out: string[] = []
  for (const token of tokens) {
    if (token === '' || token === false || token === null || token === undefined) continue
    // A token with no rule renders verbatim (unhashed) instead of vanishing,
    // so a stale class name is visible in the DOM and in the spec that walks it.
    out.push(styles[token] ?? token)
  }
  return out.join(' ')
}

/** The four trace filters offered above the list. */
export type TraceFilter = 'all' | 'miss' | 'sold' | 'dec'

/** Newest date groups rendered expanded; older days arrive in batches. */
const DEFAULT_VISIBLE_DATES = 3
const BATCH_GROUPS = 5

/**
 * Per-session UI state that survives tab unmounts: the ring remounts the view
 * on every switch (`only: active.id`), so open row / filter / batch / folded
 * days / scroll position must live in the registration store (kept alive for
 * the registration's lifetime), not in component state.
 */
export interface DecisionMindState {
  filter: TraceFilter
  open: string | null
  visibleDateCount: number
  foldedDates: string[]
  scrollTop: number
}

/**
 * Store factory — called once inside `apply`. Never a module-level handle:
 * the module cache would make it a singleton shared across plugin reloads.
 */
export function createDecisionMindStore() {
  return defineStore({
    init: (): DecisionMindState => ({
      filter: 'all',
      open: null,
      visibleDateCount: DEFAULT_VISIBLE_DATES,
      foldedDates: [],
      scrollTop: 0,
    }),
    actions: {
      setFilter: (draft, value: TraceFilter) => { draft.filter = value },
      toggleOpen: (draft, key: string) => { draft.open = draft.open === key ? null : key },
      showMoreDates: (draft, count: number) => { draft.visibleDateCount = draft.visibleDateCount + count },
      resetDates: (draft) => { draft.visibleDateCount = DEFAULT_VISIBLE_DATES },
      toggleDate: (draft, date: string) => {
        draft.foldedDates = draft.foldedDates.indexOf(date) >= 0
          ? draft.foldedDates.filter((d) => d !== date)
          : draft.foldedDates.concat([date])
      },
      setScrollTop: (draft, value: number) => { draft.scrollTop = value },
    },
  })
}

/** The registration's store handle type — the props store share derives from it. */
export type DecisionMindStore = ReturnType<typeof createDecisionMindStore>

/** One fetched trace result, kept across tab mounts by the apply closure. */
export interface TraceSnapshot {
  workspaceKey: string
  signature: string
  trades: EnrichedTrade[]
  rate: number | null
}

/** What the registration's `inject` factory hands the view. */
export interface DecisionMindInjected {
  /** The last snapshot this registration fetched, or null on a cold mount. */
  cachedTraces: () => TraceSnapshot | null
  /** Fetch traces; `changed` is false when the host answered the same signature. */
  fetchTraces: () => Promise<{ snapshot: TraceSnapshot; changed: boolean }>
}

/**
 * The view's props. The store share is derived from the declared handle
 * (`PropsStore`); `sessionId` is the session-scope runtime seat, hand-declared
 * because deriving it would need `SlotMap['conversation.view']` from the
 * conversation package — a cross-plugin value/type import the client rules
 * forbid.
 */
export type DecisionMindProps = PropsStore<DecisionMindStore> & DecisionMindInjected & {
  sessionId: string
}

const ACT: Record<string, string> = {
  buy: '买入', add: '加仓', trim: '减仓', sell: '卖出', cut: '割肉', hold: '持有',
  hold_and_watch: '持有', trim_on_rebound: '反弹减仓', t_only: '仅T+0',
  add_only_on_trigger: '触发加仓', reject: '不加', watch: '观望', abstain: '弃权',
}
const DRV: Record<string, string> = {
  technical: '技术面', fundamental: '基本面', sentiment: '情绪面', mixed: '混合', risk_rule: '风控规则',
}
/**
 * The ledger's `execution.status`, in words.
 *
 * This grades the PLAN — "was this plan followed" — and it is not a statement
 * about the fill on the row, which happened either way. Rendering 「未执行」 as
 * that row's 执行 verdict read as a flat contradiction on a completed buy, and
 * on live data 8 rows said 已遵守 while the plan's action still differed from
 * the fill's. So it renders as 账本自评 and never as the fill's own status; the
 * plan-vs-fill relation is `decision.alignment` below.
 */
const EXE: Record<string, string> = {
  followed: '遵守了计划', not_followed: '没按计划', unknown: '未标注',
}
/** The plan-vs-fill relation, stated instead of left to be inferred. */
const ALIGN: Record<string, [label: string, tone: string]> = {
  same: ['与计划同向', 'follow'],
  opposite: ['与计划反向', 'skip'],
  other: ['计划未指向买卖', ''],
}
const EMO: Record<string, string> = {
  fomo: '追高冲动', revenge: '报复性', averaging_down: '摊薄冲动', fear: '恐慌',
  euphoria: '亢奋', calm: '平静', mixed: '混合',
}
const FILTER_LABEL: Record<TraceFilter, string> = {
  all: '全部', miss: '无当日计划', sold: '卖出复盘', dec: '有当日计划',
}

/**
 * React escapes string children itself; the old extra `<` → `&lt;` pass here
 * double-escaped (the literal text "&lt;" once React escaped the ampersand).
 * String coercion is all a text slot needs.
 */
function esc(value: unknown): string {
  return String(value === null || value === undefined ? '' : value)
}

/**
 * The T+1 tone is decided host-side (`t1ToneOf` in ledger.ts) and shipped on
 * the trace as `t1.tone`. These two helpers only map that single reading onto
 * the two CSS vocabularies used here — the trace node's win/loss and the
 * chip's up/down. They deliberately take no thresholds: three independent
 * dead zones used to colour the same fill grey-"持平" in the chip and red in
 * the node, and to paint a buy at exactly 0% green while the text read 跌.
 */
export function t1NodeClass(tone: TraceT1['tone']): string {
  return tone === 'win' || tone === 'loss' ? tone : ''
}
export function t1ChipClass(tone: TraceT1['tone']): 'up' | 'down' | 'flat' {
  // Anything other than the two known verdicts falls back to neutral, never
  // to 'down'. A trace that somehow arrives without a tone is a bug, and the
  // honest way to render a bug is grey — not a confident red verdict on a
  // fill that was never judged.
  if (tone === 'win') return 'up'
  if (tone === 'loss') return 'down'
  return 'flat'
}

function fmtMoney(value: number | null): string {
  if (value === null || !isFinite(value)) return '—'
  return (value > 0 ? '+' : '') + value.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

function fmtPct(value: number | null, digits = 1): string {
  if (value === null || !isFinite(value)) return '—'
  return (value > 0 ? '+' : '') + value.toFixed(digits) + '%'
}

/** One row of the list: the wire trade projected onto what the view renders. */
export interface DisplayEntry {
  ticker: string
  market: string
  currency: string
  date: string | null
  action: string
  shares: number
  price: number | null
  realizedPnl: number | null
  note: string | null
  t1: TraceT1 | null
  holdPnl: number | null
  decision: TraceDecision | null
  /**
   * 'add' | 'reduce' decided host-side (see EnrichedTrade.side), or null when
   * the payload carried no side at all.
   *
   * Nullable on purpose. Defaulting an unknown side to 'add' silently files
   * every sell under buys and the sell scorecard then reads a confident
   * "判出 0/0 笔卖出" — wrong, not degraded. Null keeps those fills out of both
   * sides and makes the header say how many it could not place.
   */
  side: 'add' | 'reduce' | null
}

/** Display projection of one trace (test seam). */
export function _displayEntry(trace: EnrichedTrade): DisplayEntry {
  return {
    ticker: trace.ticker || '?',
    market: trace.market || 'US',
    currency: trace.currency || 'USD',
    date: trace.date ?? null,
    // A missing action must not read as "hold": the renderers already fall
    // back to the raw value through ACT lookup, and 'hold' would label an
    // unclassified fill as a deliberate decision (#836).
    action: trace.action || '?',
    shares: trace.shares || 0,
    price: trace.price ?? null,
    realizedPnl: trace.realizedPnl ?? null,
    note: trace.note ?? null,
    t1: trace.t1 ?? null,
    holdPnl: trace.holdPnl ?? null,
    decision: trace.decision ?? null,
    // Passed through, never recomputed and never defaulted: the browser must
    // not own a second copy of the action set (#739), and an absent side is
    // reported as absent rather than guessed.
    side: trace.side === 'reduce' || trace.side === 'add' ? trace.side : null,
  }
}

function Chip(props: { children?: React.ReactNode }): React.ReactElement {
  return h('span', { className: cx('tag') }, props.children)
}

function TraceDetail(props: { trace: DisplayEntry }): React.ReactElement {
  const trace = props.trace
  const decision = trace.decision
  const sym = trace.currency === 'HKD' ? 'HK$' : '$'
  // The fill itself, in words — the one node on this row that is never inferred.
  const fillText = (ACT[trace.action] ?? trace.action) + ' ' + trace.shares + ' 股 @ ' + sym + trace.price
  if (decision === null) {
    const t1miss = trace.t1 === null ? null : h('div', { className: cx('tnode', t1NodeClass(trace.t1.tone)) },
      h('div', { className: cx('tw') }, trace.t1.date),
      h('div', { className: cx('n') }, 'T+1 收盘'),
      h('div', { className: cx('v') }, (trace.t1.delta >= 0 ? '+' : '') + trace.t1.delta + '% · ' + trace.t1.verdict))
    return h('div', { className: cx('dbody') },
      h('div', { className: cx('trhead') }, '决策轨迹 · 无当日计划'),
      h('div', { className: cx('trace') },
        h('div', { className: cx('tnode', 'dec') },
          h('div', { className: cx('n') }, '当时的计划'),
          h('div', { className: cx('v'), style: { color: 'var(--cap)' } }, '这一天没有该标的的计划记录')),
        h('div', { className: cx('tnode', 'follow') },
          h('div', { className: cx('tw') }, trace.date ?? ''),
          h('div', { className: cx('n') }, '真实成交'),
          h('div', { className: cx('v') }, fillText)),
        t1miss),
      trace.note === null ? null : h('div', { className: cx('tnote') }, esc(trace.note)),
      h('div', { className: cx('tmiss') },
        '这笔成交在决策账本里找不到前后 3 天的同标的计划:成交是真的,当时的判断没有留下记录。'))
  }
  const [alignLabel, alignTone] = ALIGN[decision.alignment ?? ''] ?? ['', '']
  const planned = (ACT[decision.action ?? ''] ?? decision.action ?? '')
    + (decision.sizeShares === null ? '' : ' ' + decision.sizeShares + ' 股')
    + (decision.plannedPrice === null ? '' : ' @ ' + decision.plannedPrice)
    + (decision.confidence === null ? '' : ' · 信心 ' + Math.round(decision.confidence * 100) + '%')
    + (decision.drivenBy === null ? '' : ' · ' + (DRV[decision.drivenBy] ?? decision.drivenBy))
  const why = decision.rationale ?? decision.bull ?? ''
  const emotion = decision.emotion !== null && decision.emotion !== 'calm'
    ? (EMO[decision.emotion] ?? decision.emotion)
    : null
  const chips: React.ReactElement[] = []
  if (decision.condition !== null) chips.push(h('span', { className: cx('pc'), key: 'c' }, '触发条件: ' + decision.condition))
  if (decision.execution !== null) {
    chips.push(h('span', { className: cx('pc'), key: 'e' },
      '账本自评: ' + (EXE[decision.execution] ?? decision.execution)))
  }
  const t1node = trace.t1 === null ? null : h('div', { className: cx('tnode', t1NodeClass(trace.t1.tone)) },
    h('div', { className: cx('tw') }, trace.t1.date),
    h('div', { className: cx('n') }, 'T+1 收盘'),
    h('div', { className: cx('v') },
      (trace.t1.delta >= 0 ? '+' : '') + trace.t1.delta + '% · ' + trace.t1.verdict))
  // 本笔已实现 and 该持仓浮动 are different quantities — one belongs to this
  // fill, the other to the whole position — so they never share a label.
  let pnlText: string
  let pnlTone: string
  let pnlLabel: string
  if (trace.realizedPnl !== null) {
    pnlText = (trace.realizedPnl >= 0 ? '+' : '') + trace.realizedPnl.toFixed(2) + ' ' + sym
    pnlTone = trace.realizedPnl >= 0 ? 'win' : 'loss'
    pnlLabel = '本笔已实现'
  } else if (trace.holdPnl !== null) {
    pnlText = fmtPct(trace.holdPnl)
    pnlTone = trace.holdPnl >= 0 ? 'win' : 'loss'
    pnlLabel = '该持仓当前浮动 (' + trace.ticker + ' 全仓,非本笔)'
  } else {
    pnlText = '— 未平仓'
    pnlTone = ''
    pnlLabel = '本笔盈亏'
  }
  return h('div', { className: cx('dbody') },
    h('div', { className: cx('trhead') }, '决策轨迹 · ' + (decision.planDate ?? '')),
    h('div', { className: cx('trace') },
      h('div', { className: cx('tnode', 'dec') },
        h('div', { className: cx('tw') }, decision.planDate ?? ''),
        h('div', { className: cx('n') }, '当时的计划'),
        h('div', { className: cx('v') }, planned)),
      h('div', { className: cx('tnode', alignTone) },
        h('div', { className: cx('tw') }, trace.date ?? ''),
        h('div', { className: cx('n') }, '真实成交'),
        h('div', { className: cx('v') }, fillText,
          alignLabel === '' ? null : h('span', { className: cx('pc', alignTone) }, alignLabel))),
      t1node,
      h('div', { className: cx('tnode', pnlTone) },
        h('div', { className: cx('n') }, pnlLabel),
        h('div', { className: cx('v') }, pnlText))),
    chips.length === 0 ? null : h('div', { className: cx('pchips') }, chips),
    why === '' ? null : h('div', { className: cx('tnote', 'why') }, h('span', { className: cx('k') }, '为什么 '), esc(why)),
    emotion === null ? null : h('div', { className: cx('tnote', 'emo') }, h('span', { className: cx('k') }, '情绪 '), '⚡ ' + emotion),
    trace.note === null ? null : h('div', { className: cx('tnote') }, h('span', { className: cx('k') }, '备注 '), esc(trace.note)))
}

interface TraceCellProps {
  trace: DisplayEntry
  open: boolean
  onToggle: () => void
  onKeyDown: (event: React.KeyboardEvent) => void
}

function TraceCell(props: TraceCellProps): React.ReactElement {
  const trace = props.trace
  const sym = trace.currency === 'HKD' ? 'HK$' : '$'
  let pnl: React.ReactElement
  if (trace.realizedPnl !== null) {
    pnl = h('span', { className: cx('pnl', trace.realizedPnl >= 0 ? 'up' : 'down') },
      (trace.realizedPnl >= 0 ? '+' : '') + trace.realizedPnl.toFixed(2) + ' ' + sym)
  } else if (trace.holdPnl !== null) {
    // A floating percent belongs to the whole position, not to this fill. The
    // 持仓 prefix is what stops it reading as "this trade lost 28%".
    pnl = h('span', { className: cx('pnl', trace.holdPnl >= 0 ? 'up' : 'down') },
      h('span', { className: cx('pnlk') }, '持仓'), fmtPct(trace.holdPnl))
  } else {
    pnl = h('span', { className: cx('pnl', 'na') }, '—')
  }
  let t1tag: React.ReactElement
  if (trace.t1 !== null) {
    const tone = t1ChipClass(trace.t1.tone)
    // The verdict word already carries the side (卖飞/卖对/持平 for a reducing
    // fill, 涨/跌 for an adding one), so it is always shown. Gating it on
    // `action === 'sell'` used to drop it for cut/trim/trim_on_rebound and
    // forced the client to keep its own copy of the action set — the kind of
    // duplicate that drifted apart in #739.
    const label = 'T+1 ' + (trace.t1.delta >= 0 ? '+' : '') + trace.t1.delta + '% ' + trace.t1.verdict
    // data-tone carries the host's reading into the DOM: it is what the
    // regression spec reads, so hashed class names cannot hide a chip that
    // stopped following `t1.tone` (#713).
    t1tag = h('span', { className: cx('t1', tone), 'data-tone': tone }, label)
  } else {
    // Said out loud for every unjudged fill, not just sells: no canonical close
    // inside the T+1 window means there is no verdict, and silence there reads
    // like the fill was fine.
    t1tag = h('span', { className: cx('t1', 'flat'), 'data-tone': 'flat' }, 'T+1 未判')
  }
  // A fill that ran against its own plan is the single most load-bearing
  // signal on this board (SPCH: 37 planned cuts, 22 actual buys) — it must be
  // visible in the folded row, not only after expanding the timeline.
  let alignTag: React.ReactElement | null = null
  if (trace.decision?.alignment === 'opposite') {
    alignTag = h('span', { className: cx('al', 'opp'), 'data-align': 'opposite' }, '反向')
  }
  return h('div', {
    className: cx('cell', trace.decision !== null && 'hasdec', props.open && 'open'),
    'data-cell': 'trace',
    role: 'button',
    tabIndex: 0,
    'aria-expanded': props.open,
    onClick: props.onToggle,
    onKeyDown: props.onKeyDown,
  },
    h('div', { className: cx('main') },
      h('span', { className: cx('dotm') }),
      h('span', { className: cx('tk') }, trace.ticker,
        h('span', { className: cx('mkt', trace.market === 'HK' && 'hk') }, trace.market === 'HK' ? '港' : '美')),
      h(Chip, null, ACT[trace.action] ?? trace.action),
      h('span', { className: cx('qty') }, trace.shares + ' @' + trace.price),
      h('span', { className: cx('sp') }),
      pnl),
    h('div', { className: cx('sub') },
      t1tag,
      alignTag,
      h('span', { className: cx('date') }, (trace.date ?? '').slice(5)),
      h('span', { className: cx('chev') }, '▾')),
    h('div', { className: cx('detail') },
      h('div', { className: cx('dinner') }, props.open ? h(TraceDetail, { trace }) : null)))
}

/** Skeleton row for the cold-start loading state (no cache yet). */
function SkeletonRow(): React.ReactElement {
  return h('div', { className: cx('skel') },
    h('div', { className: cx('skel-dot') }),
    h('div', { className: cx('skel-bar', 'w40') }),
    h('div', { className: cx('skel-bar', 'w20') }))
}

interface DataState {
  trades: EnrichedTrade[]
  rate: number | null
  loading: boolean
  error: string | null
  stale: boolean
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function todayIso(): string {
  const now = new Date()
  return now.getFullYear()
    + '-' + String(now.getMonth() + 1).padStart(2, '0')
    + '-' + String(now.getDate()).padStart(2, '0')
}

function relativeDay(iso: string, today: string): string {
  if (iso === today) return '今天'
  const at = (date: string): number => new Date(date + 'T00:00:00').getTime()
  const days = Math.round((at(today) - at(iso)) / 86400000)
  if (days === 1) return '昨天'
  if (days >= 2 && days <= 7) return days + '天前'
  return parseInt(iso.slice(5, 7)) + '月' + parseInt(iso.slice(8, 10)) + '日'
}

/** The four visual states one provider's reading can take. */
export type BalanceTone = 'ok' | 'low' | 'stale' | 'none'

/**
 * Display projection of ONE provider's answer (test seam, like _displayEntry):
 * the chip and panel render only these fields, so the view never keeps
 * a second copy of the tone rules — the host already decided status and low.
 * The title is the whole hover story: split, quota windows, stale reason,
 * fetch time. Quota rows ('pct' unit) read as remaining percent, not money,
 * and carry the second window ('周'/'本周') as a muted pill suffix — both
 * limits visible at the header without opening the panel.
 */
export function _rowDisplay(result: BalanceResult | null): { tone: BalanceTone; value: string; sub: string | null; title: string } {
  if (result === null) return { tone: 'none', value: '—', sub: null, title: '余额加载中' }
  if (!result.configured) return { tone: 'none', value: '未配置', sub: null, title: result.message ?? '未配置 API Key' }
  if (result.snapshot === null) return { tone: 'none', value: '—', sub: null, title: result.message ?? '余额获取失败' }
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
  const sub = second !== null ? '· ' + second.label + ' ' + Math.round(second.percent as number) + '%' : null
  const tone: BalanceTone = result.status === 'stale'
    ? 'stale'
    : (result.low || !snapshot.isAvailable ? 'low' : 'ok')
  // 更新时间不重复展示:轮询是静默的,手动刷新有 ✓ 反馈——时间戳只增加噪音。
  const parts = [
    snapshot.unit === 'pct'
      ? (snapshot.note !== '' ? snapshot.note : '配额窗口余量')
      : 'API 余额',
    !isPct && snapshot.grantedBalance !== '' ? '赠金 ' + symbol + snapshot.grantedBalance : null,
    !isPct && snapshot.toppedUpBalance !== '' ? '充值 ' + symbol + snapshot.toppedUpBalance : null,
    snapshot.isAvailable ? null : (isPct ? '该窗口额度已用尽' : '官方接口判定余额不足'),
    result.status === 'stale' && result.message !== null ? '刷新失败,显示最近一次: ' + result.message : null,
  ].filter((part): part is string => part !== null)
  return { tone, value, sub, title: parts.join(' · ') }
}

/**
 * The one line a panel row says out loud when something is wrong — stale
 * reason, unconfigured key, insufficient balance/quota. A healthy number
 * earns no caption at all; null means silence.
 */
export function _balanceNote(result: BalanceResult | null): string | null {
  if (result === null) return null
  if (!result.configured) return result.message ?? '未配置 API Key'
  if (result.snapshot === null) return result.message ?? '余额获取失败'
  if (result.status === 'stale') {
    return '刷新失败,显示最近一次' + (result.message !== null ? ':' + result.message : '')
  }
  if (!result.snapshot.isAvailable) {
    return result.snapshot.unit === 'pct' ? '该窗口额度已用尽' : '官方接口判定余额不足'
  }
  if (result.low) {
    if (result.snapshot.unit === 'pct') return '窗口余量不足 ' + result.threshold + '%'
    const symbol = result.snapshot.currency === 'USD' ? '$' : result.snapshot.currency === 'CNY' ? '¥' : ''
    return '余额偏低,低于阈值 ' + symbol + result.threshold
  }
  return null
}

/** What the header chip's `inject` factory hands the component. */
export interface BalancesInjected {
  /** The last multi-provider answer this registration fetched, or null cold. */
  cachedBalances: () => BalancesResult | null
  /** Fetch all providers; `force` bypasses the host TTLs (the manual refresh). */
  fetchBalances: (force: boolean) => Promise<BalancesResult>
}

/**
 * Which provider the pill headlines. null = auto (first configured row);
 * a click on a panel row pins that provider. Registration-store state, so
 * the choice survives the ring's remounts.
 */
export interface BalanceUiState {
  selected: string | null
}

/** Store factory — called inside `apply`, never a module-level handle. */
export function createBalanceStore() {
  return defineStore({
    init: (): BalanceUiState => ({ selected: null }),
    actions: {
      select: (draft, provider: string) => { draft.selected = provider },
    },
  })
}

/** The chip's registration store handle type (derived, like DecisionMind's). */
export type BalanceStore = ReturnType<typeof createBalanceStore>

export type BalanceChipProps = BalancesInjected & PropsStore<BalanceStore> & { sessionId: string }

/**
 * The session-header chip (#871's final home): account status is app chrome,
 * not decision data and not its own tab. The pill headlines ONE provider —
 * the pinned one (registration store) or the first configured row — and the
 * panel lists every provider; clicking a row pins it as the headline, which
 * reads as "the balance of whichever service I'm actually burning". Same
 * contracts: [data-balance-state], [data-pb-provider], [data-pb-role],
 * [data-refresh], no emoji.
 */
/**
 * The per-provider detail under its headline: quota providers get one line
 * per window — label / remaining / reset right-aligned — so the 5h and week
 * resets scan as a column instead of drowning in a sentence. Money rows keep
 * their granted/topped-up split. Abnormal notes render above this path.
 */
function renderRowDetail(row: {
  provider: string
  result: BalanceResult
  view: { tone: BalanceTone; value: string; title: string }
  note: string | null
}): React.ReactElement | null {
  if (row.note !== null) return null
  const wins = row.result.snapshot?.windows ?? []
  if (wins.length > 0) {
    // 每窗一行:文字读数 + 发丝进度条。条的语义=剩余量,低水位换警示色;
    // 静态渲染不做 width 动画(宽度动画在审校里是红线),数据刷新整帧替换。
    return h('div', { className: cx('bp-wins') },
      wins.map((w) => {
        const pct = w.percent === null ? null : Math.max(0, Math.min(100, Math.round(w.percent)))
        const low = pct !== null && row.result.snapshot?.unit === 'pct' && pct <= row.result.threshold
        const state = low ? 'low' : row.view.tone === 'stale' ? 'stale' : 'ok'
        return h('div', { className: cx('bp-win'), key: w.label },
          h('div', { className: cx('bp-win-line') },
            h('span', { className: cx('bp-win-label') }, w.label),
            h('span', { className: cx('bp-win-pct') }, w.percent === null ? '—' : Math.round(w.percent) + '%'),
            h('span', { className: cx('bp-win-reset') }, w.resetAt === '' ? '' : '↻ ' + w.resetAt)),
          h('div', { className: cx('bp-win-bar') },
            h('div', {
              className: cx('bp-win-fill'),
              style: pct === null ? { width: '0%' } : { width: pct + '%' },
              'data-balance-state': state,
            })))
      }))
  }
  const title = row.view.title
  if (title === '') return null
  // Money rows: drop the leading 'API 余额' label — the row already says who.
  const body = title.startsWith('API 余额 · ') ? title.slice('API 余额 · '.length) : title
  return h('div', { className: cx('bp-sub') }, body)
}

export function ProviderBalanceChip(props: BalanceChipProps): React.ReactElement {
  const mountedRef = useRef(true)
  const [data, setData] = useState<{ result: BalancesResult | null; loading: boolean }>(
    () => ({ result: props.cachedBalances(), loading: false }),
  )
  const selected = props.useStore((state) => state.selected)
  const select = (provider: string): void => { props.actions.select(provider) }
  const [open, setOpen] = useState(false)
  const [flash, setFlash] = useState<'ok' | 'same' | null>(null)
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rootRef = useRef<HTMLSpanElement | null>(null)

  const runBalances = (force: boolean): void => {
    props.fetchBalances(force).then((result) => {
      if (!mountedRef.current) return
      setData({ result, loading: false })
      if (force) {
        // #870 语义:拉到新数据 → ✓(品牌色),命中缓存 → ↻ 变绿,1.2s 回落。
        setFlash(result.providers.some((p) => p.result.status === 'fresh') ? 'ok' : 'same')
        if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current)
        flashTimerRef.current = setTimeout(() => { setFlash(null) }, 1200)
      }
    }, () => {
      if (mountedRef.current) setData((current) => ({ ...current, loading: false }))
    })
  }

  useEffect(() => {
    mountedRef.current = true
    runBalances(false)
    return () => {
      mountedRef.current = false
      if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current)
    }
  }, [props.sessionId])

  useEffect(() => {
    const intervalMs = Math.max(60000, data.result?.refreshMs ?? 60000)
    const timer = setInterval(() => { runBalances(false) }, intervalMs)
    return () => clearInterval(timer)
  }, [data.result?.refreshMs, props.sessionId])

  // 打开时:Escape 关闭,点外面关闭(document 存在才挂——测试环境无 DOM)。
  useEffect(() => {
    if (!open || typeof document === 'undefined') return undefined
    const onKey = (event: KeyboardEvent): void => { if (event.key === 'Escape') setOpen(false) }
    const onDown = (event: MouseEvent): void => {
      const root = rootRef.current
      if (root !== null && event.target instanceof Node && !root.contains(event.target)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  const rows = (data.result?.providers ?? []).map((provider) => ({
    ...provider,
    view: _rowDisplay(provider.result),
    note: _balanceNote(provider.result),
  }))
  // 胶囊只讲一个 provider:选中的优先,否则第一行(稳定的 deepseek-first 序)。
  const primary = rows.find((row) => row.provider === selected) ?? rows[0]
  const refresh = (): void => {
    setData((current) => ({ ...current, loading: true }))
    runBalances(true)
  }

  return h('span', { className: cx('pbc'), ref: rootRef },
    h('button', {
      type: 'button',
      className: cx('bchip'),
      'data-balance-state': primary !== undefined ? primary.view.tone : 'none',
      'data-pb-provider': primary !== undefined ? primary.provider : '',
      'aria-expanded': open,
      'aria-haspopup': 'dialog',
      'aria-label': '各模型服务余额',
      title: primary !== undefined
        ? primary.label + ' · ' + primary.view.title + (rows.length > 1 ? '(点击查看其他服务)' : '')
        : '余额加载中',
      onClick: () => { setOpen(!open) },
    },
      primary === undefined
        ? h('span', { className: cx('bchip-item') }, h('span', { className: cx('bchip-dot') }), '—')
        : h('span', { className: cx('bchip-item'), 'data-pb-provider': primary.provider, 'data-pb-role': 'chip', 'data-balance-state': primary.view.tone },
          h('span', { className: cx('bchip-dot') }),
          h('span', { className: cx('bchip-v'), 'data-balance-state': primary.view.tone }, primary.view.value),
          // 周限额副读数:装饰性重复(面板/悬浮里有完整版),对读屏静音。
          primary.view.sub === null
            ? null
            : h('span', { className: cx('bchip-sub'), 'aria-hidden': 'true' }, primary.view.sub))),
    h('div', { className: cx('bp'), 'data-open': open ? 'true' : 'false', role: open ? 'dialog' : 'none', 'aria-label': '各模型服务余额' },
      h('div', { className: cx('bp-head') },
        h('span', { className: cx('bp-title') }, 'API 余额'),
        h('button', {
          type: 'button',
          className: cx('bal-rf', data.loading && 'spin', flash === 'ok' && 'flash-ok', flash === 'same' && 'flash-same'),
          'data-refresh': 'true',
          'aria-label': '刷新全部余额',
          title: '立即刷新',
          onClick: refresh,
        }, flash === 'ok' ? '✓' : '↻')),
      rows.length === 0
        ? h('div', { className: cx('bp-empty') }, '正在读取各服务余额…')
        : rows.map((row) => h('button', {
          type: 'button',
          key: row.provider,
          className: cx('bp-row'),
          'data-pb-provider': row.provider,
          'data-pb-role': 'panel',
          // 点行=把该 provider 钉成胶囊头条;当前头条行带 aria-pressed。
          'aria-pressed': row.provider === (primary !== undefined ? primary.provider : ''),
          onClick: () => { select(row.provider) },
        },
          h('span', { className: cx('bp-dot'), 'data-balance-state': row.view.tone }),
          h('span', { className: cx('bp-label') },
            row.label,
            row.provider === (primary !== undefined ? primary.provider : '')
              ? h('span', { className: cx('bp-pin') })
              : null),
          h('span', { className: cx('bp-v', row.view.tone === 'low' ? 'bad' : ''), 'data-balance-state': row.view.tone }, row.view.value),
          row.note !== null
            ? h('div', { className: cx('bp-note', row.view.tone === 'stale' ? 'warn' : 'bad') }, row.note)
            : renderRowDetail(row)))))
}

export function DecisionMind(props: DecisionMindProps): React.ReactElement {
  const filter = props.useStore((state) => state.filter)
  const open = props.useStore((state) => state.open)
  const visibleDateCount = props.useStore((state) => state.visibleDateCount)
  const foldedDates = props.useStore((state) => state.foldedDates)
  const scrollTop = props.useStore((state) => state.scrollTop)
  const actions = props.actions
  const rootRef = useRef<HTMLDivElement | null>(null)
  // 缓存命中:同步渲染上一次快照,零 loading 帧。
  const [data, setData] = useState<DataState>(() => {
    const cached = props.cachedTraces()
    return cached === null
      ? { trades: [], rate: null, loading: true, error: null, stale: false }
      : { trades: cached.trades, rate: cached.rate, loading: false, error: null, stale: false }
  })

  useEffect(() => {
    let alive = true
    props.fetchTraces().then((fetched) => {
      if (!alive || !fetched.changed) return // 同一份数据,跳过重渲染
      setData({ trades: fetched.snapshot.trades, rate: fetched.snapshot.rate, loading: false, error: null, stale: false })
    }, (error: unknown) => {
      if (!alive) return
      if (props.cachedTraces() !== null) setData((current) => ({ ...current, stale: true }))
      else setData({ trades: [], rate: null, loading: false, error: messageOf(error), stale: false })
    })
    return () => { alive = false }
  }, [props.sessionId])

  // 滚动位置:存进注册 store,列表渲染后恢复,滚动时回写。容器从自己的
  // element ref 往上找,不用全局选择器 —— 同一页可以有第二个实例。
  useEffect(() => {
    if (data.loading) return
    const root = rootRef.current
    if (root === null) return
    let scroller: HTMLElement = root
    while (scroller.parentElement !== null && scroller.scrollHeight <= scroller.clientHeight + 1) {
      scroller = scroller.parentElement
    }
    if (scrollTop > 0 && scroller.scrollHeight > scroller.clientHeight + 1) {
      scroller.scrollTop = scrollTop
    }
    const onScroll = (): void => { actions.setScrollTop(scroller.scrollTop) }
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => { scroller.removeEventListener('scroll', onScroll) }
  }, [data.loading])

  if (data.error !== null) {
    return h('div', { className: cx('dmt'), ref: rootRef },
      h('div', { className: cx('empty') }, 'Decision Mind: ' + data.error))
  }
  if (data.loading) {
    return h('div', { className: cx('dmt'), ref: rootRef },
      h('div', { className: cx('top') },
        h('div', { className: cx('tin') },
          h('div', { className: cx('tt') }, '决策轨迹',
            h('span', { className: cx('ts') }, '一笔真实成交 + 当时写下的计划 + 官方收盘给的结果')))),
      h('div', { className: cx('list') },
        h(SkeletonRow, { key: 'sk1' }),
        h(SkeletonRow, { key: 'sk2' }),
        h(SkeletonRow, { key: 'sk3' })))
  }

  const traces = data.trades.map(_displayEntry)
  let filtered = traces
  if (filter === 'miss') filtered = traces.filter((trace) => trace.decision === null)
  // The sell filter follows the host-computed `side`, not a client-side copy of
  // the action set: `action === 'sell'` silently missed cut/trim/trim_on_rebound
  // and is exactly the duplicate that drifted in #739.
  if (filter === 'sold') filtered = traces.filter((trace) => trace.side === 'reduce')
  if (filter === 'dec') filtered = traces.filter((trace) => trace.decision !== null)

  const sumRealized = (currency: string): number => traces
    .filter((trace) => trace.realizedPnl !== null && trace.currency === currency)
    .reduce((sum, trace) => sum + (trace.realizedPnl ?? 0), 0)
  const rate = data.rate
  const hkdRealized = sumRealized('HKD')
  const totalUsd = sumRealized('USD') + (rate === null ? 0 : hkdRealized / rate)
  // No rate means the HKD side cannot be converted; the label says so instead
  // of silently presenting the USD half as the whole (#835).
  const totalLabel = rate === null && hkdRealized !== 0
    ? '已实现 (USD 等值 · HKD 未折算)'
    : '已实现 (USD 等值)'
  // Only fills whose T+1 close actually landed inside the T+1 window carry a
  // `t1` at all (the host drops the rest rather than labelling a months-later
  // close "T+1"). The denominator is rendered so the ratio can be read for
  // what it is instead of looking like it covers every fill.
  // Every count carries the denominator it is actually a fraction of. The old
  // label read "T+1 卖飞/卖对 · 基于 39 笔" while only sell-side verdicts were
  // shown and those 39 counted buys as well.
  const sells = traces.filter((trace) => trace.side === 'reduce')
  const sideless = traces.filter((trace) => trace.side === null).length
  const sellsRated = sells.filter((trace) => trace.t1 !== null).length
  const soldEarly = sells.filter((trace) => trace.t1?.verdict === '卖飞').length
  const soldRight = sells.filter((trace) => trace.t1?.verdict === '卖对').length
  const matched = traces.filter((trace) => trace.decision !== null).length
  const reversed = traces.filter((trace) => trace.decision?.alignment === 'opposite').length

  const groups: Record<string, DisplayEntry[]> = {}
  for (const trace of filtered) {
    const day = (trace.date ?? '').slice(0, 10)
    ;(groups[day] ??= []).push(trace)
  }
  const dates = Object.keys(groups).sort().reverse()
  const today = todayIso()

  // Batch reveal + per-day accordion (plan #702 Phase 2): the newest
  // DEFAULT_VISIBLE_DATES groups render expanded; older days load in batches
  // behind "show earlier" (trajectory loadOlder, same shape), and any day
  // header folds its rows — so "see everything" never means one 100-cell wall
  // at once. Stats stay computed over ALL fills.
  const visibleDates = dates.slice(0, visibleDateCount)
  const moreFills = dates.slice(visibleDateCount, visibleDateCount + BATCH_GROUPS)
    .reduce((sum, date) => sum + (groups[date]?.length ?? 0), 0)

  const renderDate = (date: string): React.ReactElement => {
    const folded = foldedDates.indexOf(date) >= 0
    const rows = groups[date] ?? []
    return h('div', { key: date },
      h('div', {
        className: cx('day', 'fold'),
        // The day header's identity in the DOM: hashed class names are not a
        // contract, this attribute is (the spec folds a day through it).
        'data-day': date,
        role: 'button',
        tabIndex: 0,
        'aria-expanded': folded ? 'false' : 'true',
        onClick: () => { actions.toggleDate(date) },
        onKeyDown: (event: React.KeyboardEvent) => {
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); actions.toggleDate(date) }
        },
      },
        h('span', { className: cx('chev') }, folded ? '▸' : '▾'),
        relativeDay(date, today),
        h('span', null, date),
        h('span', { className: cx('n') }, rows.length)),
      folded ? null : h('div', { className: cx('group') }, rows.map((trace, index) => {
        // 下标兜底:ticker+date+shares 在同股同日同量时会撞 key。
        const key = trace.ticker + trace.date + trace.shares + ':' + index
        return h(TraceCell, {
          key,
          trace,
          open: open === key,
          onToggle: () => { actions.toggleOpen(key) },
          onKeyDown: (event: React.KeyboardEvent) => {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); actions.toggleOpen(key) }
          },
        })
      })))
  }

  let moreButton: React.ReactElement | null = null
  if (visibleDates.length < dates.length) {
    moreButton = h('button', {
      key: 'more', className: cx('trace-more'), onClick: () => { actions.showMoreDates(BATCH_GROUPS) },
    }, '显示更早的 ' + moreFills + ' 笔成交')
  } else if (visibleDateCount > DEFAULT_VISIBLE_DATES) {
    moreButton = h('button', {
      key: 'more', className: cx('trace-more'), onClick: () => { actions.resetDates() },
    }, '收起,只显示最近 ' + DEFAULT_VISIBLE_DATES + ' 组')
  }

  let body: React.ReactElement
  if (filtered.length === 0) {
    body = h('div', { className: cx('empty') }, '没有符合条件的成交')
  } else {
    const kids: React.ReactElement[] = visibleDates.map(renderDate)
    if (moreButton !== null) kids.push(moreButton)
    body = h('div', null, kids)
  }

  const stats = h('div', { className: cx('stats') },
    h('div', { className: cx('sg') },
      h('span', { className: cx('sl') }, totalLabel),
      h('span', { className: cx('sv', 'focus', totalUsd >= 0 ? 'up' : 'down') }, fmtMoney(totalUsd))),
    h('div', { className: cx('sg') },
      h('span', { className: cx('sl') }, 'T+1 卖飞/卖对 · 判出 ' + sellsRated + '/' + sells.length
        + ' 笔卖出' + (sideless === 0 ? '' : ' · ' + sideless + ' 笔无侧向')),
      h('span', { className: cx('sv') },
        h('span', { className: cx('down') }, soldEarly), ' / ', h('span', { className: cx('up') }, soldRight))),
    h('div', { className: cx('sg') },
      h('span', { className: cx('sl') }, '有当日计划' + (reversed === 0 ? '' : ' · 反向 ' + reversed)),
      h('span', { className: cx('sv') }, matched + '/' + traces.length)))

  // The filter row is the only part of the header that stays on screen while
  // the list scrolls; the stat card above it scrolls away with the content.
  const filters = h('div', { className: cx('filters') },
    (['all', 'miss', 'sold', 'dec'] as const).map((value) => h('button', {
      key: value,
      className: cx('ft', filter === value && 'on'),
      // The selected filter is state, not navigation: aria-pressed is the
      // machine-readable "which one is on" (#834).
      'aria-pressed': filter === value,
      onClick: () => { actions.setFilter(value) },
    }, FILTER_LABEL[value])))

  // The header rides the host's content column (`--dsh-chat-content-width`),
  // so the sticky bar lines up with the rows instead of running full-bleed
  // over them; only its background and rule span the view.
  return h('div', { className: cx('dmt'), ref: rootRef },
    h('div', { className: cx('top') },
      h('div', { className: cx('tin') },
        h('div', { className: cx('tt') }, '决策轨迹',
          h('span', { className: cx('ts') }, '一笔真实成交 + 当时写下的计划 + 官方收盘给的结果' + (data.stale ? ' · 更新失败,显示此前快照' : '')),
          h('span', { className: cx('rate') },
            traces.length + ' 笔成交' + (rate === null ? '' : ' · @' + rate))),
        stats)),
    h('div', { className: cx('bar') },
      h('div', { className: cx('bin') }, filters)),
    h('div', { className: cx('list') }, body))
}

/** Services required by the registration and the mounted Remote face. */
export const inject = ['slots', 'remote']

/** Client contribution context: the face the slot renderer hands us. */
interface ClientContributionContext {
  slots: {
    inject: (name: string, register: () => unknown) => unknown
    register: (definition: Record<string, unknown>, component: unknown) => unknown
  }
  remote: TypertClientRemote
  get: (name: string) => Record<string, (...args: unknown[]) => Promise<unknown>>
}

/** Remote answer shape: the gateway's ok/error envelope. */
type RemoteResult<T> = { ok: true; value: T } | { ok: false; error: { code: string; message: string } }

/** Register the Decision Mind tab into the conversation view ring. */
export async function apply(ctx: Context & ClientContributionContext): Promise<void> {
  await ctx.remote.$mount(TYPERT_REMOTE as TypertRemoteContribution)
  const studioRemote = ctx.get('remote.clawockStudio')
  // Live data channel + its cache both live in the apply closure: business
  // data belongs to this plugin instance, never to a module-level singleton
  // (which would leak across plugin reloads) and never to the UI store.
  let cached: TraceSnapshot | null = null
  let cachedBalances: BalancesResult | null = null
  const call = async <T>(method: string, args: unknown[] = []): Promise<T> => {
    const result = await studioRemote[method]!(...args) as RemoteResult<T>
    if (!result.ok) {
      throw new Error('clawockStudio.' + method + ' failed: ' + result.error.code + ': ' + result.error.message)
    }
    return result.value
  }
  const injected = (): DecisionMindInjected => ({
    cachedTraces: () => cached,
    fetchTraces: async () => {
      const result = await call<TracesResult>('traces')
      const snapshot: TraceSnapshot = {
        workspaceKey: result.workspaceKey,
        signature: result.signature,
        trades: result.trades,
        rate: result.rate,
      }
      // The host answers a signature hit in µs from its own cache; an
      // unchanged signature means the rendered snapshot is still current.
      const changed = cached === null
        || cached.workspaceKey !== snapshot.workspaceKey
        || cached.signature !== snapshot.signature
      cached = snapshot
      return { snapshot, changed }
    },
  })
  // The chip is app-level account chrome, not decision data — it lives in the
  // session header's utilities seat with its own inject face and cache, so
  // the Decision Mind view carries trading semantics only.
  const balancesInjected = (): BalancesInjected => ({
    cachedBalances: () => cachedBalances,
    fetchBalances: async (force) => {
      const result = await call<BalancesResult>('balance', [force])
      cachedBalances = result
      return result
    },
  })
  const store = createDecisionMindStore()
  ctx.slots.inject('conversation.view', () => ctx.slots.register({
    name: 'conversation.view',
    id: 'decision-studio',
    order: 30,
    label: () => 'Decision Mind',
    store,
    inject: injected,
  }, DecisionMind))
  const balancesStore = createBalanceStore()
  ctx.slots.inject('conversation.session.header.utilities', () => ctx.slots.register({
    name: 'conversation.session.header.utilities',
    id: 'provider-balance',
    order: 90,
    store: balancesStore,
    inject: balancesInjected,
  }, ProviderBalanceChip))
}