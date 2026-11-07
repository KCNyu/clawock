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
import { defineStore } from '@deepseek-ai/dsh-client-store'
// The loader module table provides React at runtime; the types come from the
// @types/react devDependency.
import * as React from 'react'
import styles from './styles.module.css'
import { PROVIDER_JOIN } from './providers.ts'
import type { BalancesResult, DispatchTask, EnrichedTrade, QueueActionResult, T1VerdictKind, TaskQueueResult, TaskStats, TraceDecision, TraceT1, TracesResult } from './types.ts'
import { LOCALE_NS, dictionaries, resetStampOf, windowsOf, type Translate } from './copy.ts'
import { _slotOf, _slotLanes, durationOf, agoOf, _taskStatus, executionText, reportText, endedTone, _agentLabel, _modelView, modelLine, _notifyState, notifyChannels, STATE_ROLES, _endedState, FACT_ORDER, ROW_KINDS, _taskState, reorderable, _panelSources, _poolPosition, _costOf, sourceView, balanceRows, agentWindows, allowanceDetail, panelModel, panelNotices, opsFooter, _queueHeadline, statsView, patrolSection, compactCount, MINUS, signalView, workbenchCounts, providerAlerts, providerRowsView, historyRowsView, _fmtTokens, waitShort, waitLong, waitSpoken, waitedOf, isStuckTask, splitPending, firstSentence, taskTitle, type BalanceTone, type StatsView, type BalanceRow, type SlotLane, type ReceiptState, type StateRole, type SlotChip, type Fact, type RowLead, type RowView, type PanelSource, type AllowanceDetail, type PanelGroup, type PanelModel, type PatrolRhythm, type CoverageView, type StatsSeriesView, type ProviderRowView, type HistoryRowView } from './panel.ts'
export { LOCALE_NS, type Translate, dictionaries, createTranslator, windowLabelOf, resetStampOf, windowsOf } from './copy.ts'
export { _fmtTokens } from './panel.ts'
// Pure projections, re-exported so the spec can pin the fixed signal copy and
// the wait formatters without a browser.
export { signalView, waitShort, waitLong, waitSpoken, firstSentence, splitPending, taskTitle } from './panel.ts'
export { type BalanceTone, type UsedLevel, _usedLevel, _rowDisplay, _balanceNote, _slotOf, _slotLanes, _taskStatus, _queueHeadline, _agentLabel, _modelView, type ReceiptState, _notifyState, type StateRole, STATE_ROLES, _endedState, FACT_ORDER, type FactSlot, type RowKind, RESIDENT_CHIPS, FACT_CELL, ROW_KINDS, _taskState, type PanelSource, _panelSources, _poolPosition, _queueState, _patrolReason, _costOf, roundFiled, statsView, providerSignal, providerAlerts, providerRowsView } from './panel.ts'

const { createElement, useEffect, useId, useRef, useState } = React

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

/**
 * The T+1 verdict in the active locale. `verdictKind` is the stable code; a
 * host that predates it sends only the rendered text, which is passed through
 * rather than dropped — the same fallback rule as the balance windows.
 */
export function verdictOf(t: Translate, t1: { verdictKind?: T1VerdictKind | null; verdict: string }): string {
  const kind = t1.verdictKind
  if (kind == null) return t1.verdict
  return t('t1.' + kind)
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
  /** Who gave the rate and for which day (host-built label); null when unknown. */
  rateSource: string | null
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
  /** Dictionary seat from declaring `locale: LOCALE_NS` on the registration. */
  t: Translate
}

/** Action code → dictionary key. The words live in the dictionary, not here. */
const ACT: Record<string, string> = {
  buy: 'action.buy', add: 'action.add', trim: 'action.trim', sell: 'action.sell',
  cut: 'action.cut', hold: 'action.hold', hold_and_watch: 'action.hold',
  trim_on_rebound: 'action.trim_on_rebound', t_only: 'action.t_only',
  add_only_on_trigger: 'action.add_only_on_trigger', reject: 'action.reject',
  watch: 'action.watch', abstain: 'action.abstain',
}
const DRV: Record<string, string> = {
  technical: 'driver.technical', fundamental: 'driver.fundamental', sentiment: 'driver.sentiment',
  mixed: 'driver.mixed', risk_rule: 'driver.risk_rule',
  // The v2 plan-row words (docs/decision-mind-ledger.md), which is what the trace pairs with:
  // catalyst is the one the brief's catalyst gate requires on every active call (#2030).
  catalyst: 'driver.catalyst', influencer: 'driver.influencer', macro: 'driver.macro', peer: 'driver.peer',
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
  followed: 'exe.followed', not_followed: 'exe.not_followed', unknown: 'exe.unknown',
}
/** The plan-vs-fill relation, stated instead of left to be inferred. */
const ALIGN: Record<string, [key: string, tone: string]> = {
  same: ['align.same', 'follow'],
  opposite: ['align.opposite', 'skip'],
  other: ['align.other', ''],
}
const EMO: Record<string, string> = {
  fomo: 'emo.fomo', revenge: 'emo.revenge', averaging_down: 'emo.averaging_down', fear: 'emo.fear',
  euphoria: 'emo.euphoria', calm: 'emo.calm', mixed: 'emo.mixed',
}
const FILTER_LABEL: Record<TraceFilter, string> = {
  all: 'filter.all', miss: 'filter.miss', sold: 'filter.sold', dec: 'filter.dec',
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

/** Dashboard-parity money formatter (test seam). */
export function _fmtMoney(value: number | null, currency = ''): string {
  if (value === null || !isFinite(value)) return '—'
  const symbol = currency === 'USD' ? '$' : currency === 'HKD' ? 'HK$' : ''
  const formatted = Math.abs(value) >= 1000
    ? Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 0 })
    : Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 2 })
  return (value < 0 ? MINUS : '') + symbol + formatted
}

/** A fill price as written, or '—' when the ledger carried none (#1590). */
function fmtPrice(value: number | null, sym = ''): string {
  if (value === null || !isFinite(value)) return '—'
  return sym + value
}

/** Dashboard-parity percentage formatter (test seam). */
export function _fmtPct(value: number | null, digits = 2): string {
  if (value === null || !isFinite(value)) return '—'
  return (value >= 0 ? '+' : MINUS) + Math.abs(value).toFixed(digits) + '%'
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
  /** A pre-ledger opening lot, not a fill: labelled as such, never T+1-judged (#3118). */
  reconstructed: boolean
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
    reconstructed: trace.reconstructed === true,
  }
}

function Chip(props: { children?: React.ReactNode }): React.ReactElement {
  return h('span', { className: cx('tag') }, props.children)
}

function TraceDetail(props: { trace: DisplayEntry; t: Translate }): React.ReactElement {
  const t = props.t
  const trace = props.trace
  const decision = trace.decision
  const sym = trace.currency === 'HKD' ? 'HK$' : '$'
  /** Action code → the word, falling back to the raw code the host sent. */
  const act = (code: string | null): string => (code === null ? '' : (ACT[code] === undefined ? code : t(ACT[code] as string)))
  // The fill itself, in words — the one node on this row that is never inferred.
  const fillText = act(trace.action) + ' ' + trace.shares + t('trace.sharesAt') + fmtPrice(trace.price, sym)
  if (decision === null) {
    const t1miss = trace.t1 === null ? null : h('div', { className: cx('tnode', t1NodeClass(trace.t1.tone)) },
      h('div', { className: cx('tw') }, trace.t1.date),
      h('div', { className: cx('n') }, t('trace.t1Close')),
      h('div', { className: cx('v') }, _fmtPct(trace.t1.delta, 1) + ' · ' + verdictOf(t, trace.t1)))
    return h('div', { className: cx('dbody') },
      h('div', { className: cx('trhead') }, t('trace.titleNoPlan')),
      h('div', { className: cx('trace') },
        h('div', { className: cx('tnode', 'dec') },
          h('div', { className: cx('n') }, t('trace.planThen')),
          h('div', { className: cx('v'), style: { color: 'var(--cap)' } }, t('trace.noPlanRecord'))),
        h('div', { className: cx('tnode', 'follow') },
          h('div', { className: cx('tw') }, trace.date ?? ''),
          h('div', { className: cx('n') }, t(trace.reconstructed ? 'trace.reconstructedFill' : 'trace.realFill')),
          h('div', { className: cx('v') }, fillText)),
        t1miss),
      trace.note === null ? null : h('div', { className: cx('tnote') }, esc(trace.note)),
      // "成交是真的" is exactly what an opening lot is not; its note says what it is.
      trace.reconstructed ? null : h('div', { className: cx('tmiss') }, t('trace.unpaired')))
  }
  const [alignKey, alignTone] = ALIGN[decision.alignment ?? ''] ?? ['', '']
  const alignLabel = alignKey === '' ? '' : t(alignKey)
  const planned = act(decision.action)
    + (decision.sizeShares === null ? '' : ' ' + decision.sizeShares + t('trace.shares'))
    + (decision.plannedPrice === null ? '' : ' @ ' + decision.plannedPrice)
    + (decision.confidence === null ? '' : t('trace.confidence') + Math.round(decision.confidence * 100) + '%')
    + (decision.drivenBy === null ? '' : ' · ' + (DRV[decision.drivenBy] === undefined ? decision.drivenBy : t(DRV[decision.drivenBy] as string)))
  const why = decision.rationale ?? decision.bull ?? ''
  const emotion = decision.emotion !== null && decision.emotion !== 'calm'
    ? (EMO[decision.emotion] === undefined ? decision.emotion : t(EMO[decision.emotion] as string))
    : null
  const chips: React.ReactElement[] = []
  if (decision.condition !== null) chips.push(h('span', { className: cx('pc'), key: 'c' }, t('trace.trigger') + decision.condition))
  if (decision.execution !== null) {
    chips.push(h('span', { className: cx('pc'), key: 'e' },
      t('trace.selfGrade') + (EXE[decision.execution] === undefined ? decision.execution : t(EXE[decision.execution] as string))))
  }
  const t1node = trace.t1 === null ? null : h('div', { className: cx('tnode', t1NodeClass(trace.t1.tone)) },
    h('div', { className: cx('tw') }, trace.t1.date),
    h('div', { className: cx('n') }, t('trace.t1Close')),
    h('div', { className: cx('v') },
      _fmtPct(trace.t1.delta, 1) + ' · ' + verdictOf(t, trace.t1)))
  // 本笔已实现 and 该持仓浮动 are different quantities — one belongs to this
  // fill, the other to the whole position — so they never share a label.
  let pnlText: string
  let pnlTone: string
  let pnlLabel: string
  if (trace.realizedPnl !== null) {
    pnlText = _fmtMoney(trace.realizedPnl, trace.currency)
    pnlTone = trace.realizedPnl >= 0 ? 'win' : 'loss'
    pnlLabel = t('trace.realized')
  } else if (trace.holdPnl !== null) {
    pnlText = _fmtPct(trace.holdPnl, 1)
    pnlTone = trace.holdPnl >= 0 ? 'win' : 'loss'
    pnlLabel = t('trace.floating', { ticker: trace.ticker })
  } else {
    pnlText = t('trace.openPosition')
    pnlTone = ''
    pnlLabel = t('trace.pnl')
  }
  return h('div', { className: cx('dbody') },
    h('div', { className: cx('trhead') }, t('trace.titleWithPlan', { date: decision.planDate ?? '' })),
    h('div', { className: cx('trace') },
      h('div', { className: cx('tnode', 'dec') },
        h('div', { className: cx('tw') }, decision.planDate ?? ''),
        h('div', { className: cx('n') }, t('trace.planThen')),
        h('div', { className: cx('v') }, planned)),
      h('div', { className: cx('tnode', alignTone) },
        h('div', { className: cx('tw') }, trace.date ?? ''),
        h('div', { className: cx('n') }, t(trace.reconstructed ? 'trace.reconstructedFill' : 'trace.realFill')),
        h('div', { className: cx('v', 'fill-v') }, fillText,
          alignLabel === '' ? null : h('span', { className: cx('pc', alignTone) }, alignLabel))),
      t1node,
      h('div', { className: cx('tnode', pnlTone) },
        h('div', { className: cx('n') }, pnlLabel),
        h('div', { className: cx('v') }, pnlText))),
    chips.length === 0 ? null : h('div', { className: cx('pchips') }, chips),
    why === '' ? null : h('div', { className: cx('tnote', 'why') }, h('span', { className: cx('k') }, t('trace.why')), esc(why)),
    emotion === null ? null : h('div', { className: cx('tnote', 'emo') }, h('span', { className: cx('k') }, t('trace.emotion')), '⚡ ' + emotion),
    trace.note === null ? null : h('div', { className: cx('tnote') }, h('span', { className: cx('k') }, t('trace.note')), esc(trace.note)))
}

interface TraceCellProps {
  trace: DisplayEntry
  open: boolean
  onToggle: () => void
  onKeyDown: (event: React.KeyboardEvent) => void
  t: Translate
}

function TraceCell(props: TraceCellProps): React.ReactElement {
  const t = props.t
  const trace = props.trace
  let pnl: React.ReactElement
  if (trace.realizedPnl !== null) {
    pnl = h('span', { className: cx('pnl', trace.realizedPnl >= 0 ? 'up' : 'down') },
      _fmtMoney(trace.realizedPnl, trace.currency))
  } else if (trace.holdPnl !== null) {
    // A floating percent belongs to the whole position, not to this fill. The
    // 持仓 prefix is what stops it reading as "this trade lost 28%".
    pnl = h('span', { className: cx('pnl', trace.holdPnl >= 0 ? 'up' : 'down') },
      h('span', { className: cx('pnlk') }, t('trace.holding')), _fmtPct(trace.holdPnl, 1))
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
    const label = 'T+1 ' + _fmtPct(trace.t1.delta, 1) + ' ' + verdictOf(t, trace.t1)
    // data-tone carries the host's reading into the DOM: it is what the
    // regression spec reads, so hashed class names cannot hide a chip that
    // stopped following `t1.tone` (#713).
    t1tag = h('span', { className: cx('t1', tone), 'data-tone': tone }, label)
  } else {
    // Said out loud for every unjudged fill, not just sells: no canonical close
    // inside the T+1 window means there is no verdict, and silence there reads
    // like the fill was fine. An opening lot is not waiting for a close; it
    // has none to wait for.
    t1tag = h('span', { className: cx('t1', 'flat'), 'data-tone': 'flat' },
      t(trace.reconstructed ? 'trace.t1Reconstructed' : 'trace.t1Pending'))
  }
  // A fill that ran against its own plan is the single most load-bearing
  // signal on this board (SPCH: 37 planned cuts, 22 actual buys) — it must be
  // visible in the folded row, not only after expanding the timeline.
  let alignTag: React.ReactElement | null = null
  if (trace.decision?.alignment === 'opposite') {
    alignTag = h('span', { className: cx('al', 'opp'), 'data-align': 'opposite' }, t('trace.opposite'))
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
        h('span', { className: cx('mkt', trace.market === 'HK' && 'hk') }, trace.market === 'HK' ? t('trace.market.hk') : t('trace.market.us'))),
      h(Chip, null, ACT[trace.action] === undefined ? trace.action : t(ACT[trace.action] as string)),
      h('span', { className: cx('qty') }, trace.shares + ' @' + fmtPrice(trace.price)),
      h('span', { className: cx('sp') }),
      pnl),
    h('div', { className: cx('sub') },
      t1tag,
      alignTag,
      h('span', { className: cx('date') }, (trace.date ?? '').slice(5)),
      h('span', { className: cx('chev') }, '▾')),
    h('div', { className: cx('detail') },
      h('div', { className: cx('dinner') }, props.open ? h(TraceDetail, { trace, t }) : null)))
}

/** Stable row identities are derived before filtering, so switching filters
 * cannot remount the same trade and discard its expanded state (#1603). */
export function _traceKeys(traces: DisplayEntry[]): Map<DisplayEntry, string> {
  const occurrences = new Map<string, number>()
  const keys = new Map<DisplayEntry, string>()
  for (const trace of traces) {
    const base = trace.ticker + trace.date + trace.shares + ':' + trace.action
    const occurrence = occurrences.get(base) ?? 0
    occurrences.set(base, occurrence + 1)
    keys.set(trace, base + ':' + occurrence)
  }
  return keys
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
  rateSource: string | null
  loading: boolean
  error: string | null
  stale: boolean
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/**
 * The host answered, but read no ledger. `readPortfolio` reports a missing or
 * unparseable portfolio.json as an empty book with `lastUpdated: null`, and
 * every ledger writer stamps `last_updated`, so a null there is "could not
 * read", not "no fills" — which the tab used to print as $0 and 0/0 (#2180).
 */
class LedgerUnreadable extends Error {}

function todayIso(): string {
  const now = new Date()
  return now.getFullYear()
    + '-' + String(now.getMonth() + 1).padStart(2, '0')
    + '-' + String(now.getDate()).padStart(2, '0')
}

function relativeDay(iso: string, today: string, t: Translate): string {
  if (iso === today) return t('time.today')
  const at = (date: string): number => new Date(date + 'T00:00:00').getTime()
  const days = Math.round((at(today) - at(iso)) / 86400000)
  if (days === 1) return t('time.yesterday')
  if (days >= 2 && days <= 7) return t('time.daysAgo', { days })
  return t('time.date', { month: parseInt(iso.slice(5, 7)), day: parseInt(iso.slice(8, 10)) })
}

/** What the header chip's `inject` factory hands the component. */
export interface BalancesInjected {
  /** The last multi-provider answer this registration fetched, or null cold. */
  cachedBalances: () => BalancesResult | null
  /** Fetch all providers; `force` bypasses the host TTLs (the manual refresh). */
  fetchBalances: (force: boolean) => Promise<BalancesResult>
  /** Hear answers fetched by a sibling surface; returns the unsubscribe. */
  subscribeBalances?: (listener: (result: BalancesResult) => void) => () => void
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

export type BalanceChipProps = BalancesInjected & PropsStore<BalanceStore> & {
  sessionId: string
  /** Dictionary seat from declaring `locale: LOCALE_NS` on the registration. */
  t: Translate
}

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
 * their granted/topped-up split. A note does NOT suppress this detail when
 * readable windows exist (kcn 反馈 #908: 变色只改颜色,绝不动信息量)——
 * the watermark/stale caption rides along; only data-less abnormal rows
 * (unconfigured / fetch-failed) speak through the note alone.
 */
function renderRowDetail(row: BalanceRow, t: Translate, now: number): React.ReactElement | null {
  return renderAllowance(allowanceDetail(row, t, now), t)
}

/** panel.ts's AllowanceDetail as the window lines (label · used · reset over a hairline bar) or the money split. */
function renderAllowance(detail: AllowanceDetail, t: Translate): React.ReactElement | null {
  if (detail === null) return null
  if (detail.kind === 'text') return h('div', { className: cx('bp-sub') }, detail.text)
  // 每窗一行:文字读数 + 发丝进度条。静态渲染不做 width 动画,数据刷新整帧替换。
  return h('div', { className: cx('bp-wins') },
    detail.windows.map((w) => h('div', { className: cx('bp-win'), key: w.label },
      h('div', { className: cx('bp-win-line') },
        h('span', { className: cx('bp-win-label') }, w.label),
        // 百分比与条形同源(w.percent→fill),而且写明方向:面板历史上一处 used
        // 一处 remaining,统一为已用后仍只印裸数字;kcn 2026-11-06 对到 CLI 的
        // “剩 12%”才确认缺的是这个标签。
        h('span', { className: cx('bp-win-pct') }, w.percent === null ? '—' : t('balance.usedValue', { percent: Math.round(w.percent) + '%' })),
        h('span', { className: cx('bp-win-reset') }, w.reset === '' ? '' : '↻ ' + w.reset)),
      h('div', { className: cx('bp-win-bar') },
        h('div', {
          className: cx('bp-win-fill'),
          style: w.fill === null ? { width: '0%' } : { width: w.fill + '%' },
          'data-balance-state': w.state,
        })))))
}

/** How often the rail's badge is checked while no reading is on screen (see `useProviderBalances`). */
export const BALANCE_BADGE_MS = 15 * 60000

/** The poll interval for a surface: the host's cadence while its numbers are read, the badge's otherwise. */
export function _balanceCadence(reading: boolean, refreshMs: number | undefined): number {
  const host = Math.max(60000, refreshMs ?? 60000)
  return reading ? host : Math.max(BALANCE_BADGE_MS, host)
}

/**
 * The balance channel every surface shares: cached-first state, the mount
 * fetch, the refreshMs poll, the #870 refresh flash and the pinned headline.
 * Lifted out of the header chip verbatim so the sidebar button and the
 * global panel keep exactly its behaviour. `pollKey` re-arms the fetch the
 * way the chip's `sessionId` dependency did; root-scoped surfaces pass a
 * constant. A registration that supplies `subscribeBalances` also hears
 * answers fetched by its sibling surface (the panel's manual refresh updates
 * the foot button at once).
 *
 * `reading` is whether a number is on screen for someone to read. A surface
 * that prints the readings (the folded lines, the open panel, the header chip)
 * keeps them current at the host's cadence. The 56px rail prints none — one
 * glyph and a threshold badge — so it only keeps the badge honest, at
 * `BALANCE_BADGE_MS`: on a phone the rail is on screen for as long as the page
 * is, and polling it every minute read all four providers 480 times in eight
 * hours nobody opened the panel (measured, 2026-10-11). Becoming read (the
 * panel opens, the sidebar widens) reads at once, so what is looked at is the
 * host's current answer rather than the badge's last one.
 */
function useBalanceData(props: BalancesInjected & { t: Translate }, pollKey: string, reading: boolean) {
  const mountedRef = useRef(true)
  // When the last answer arrived (any surface's), and whether the previous render was read:
  // together they turn "became read" into one fetch, and only when the answer on hand is
  // older than the host would serve anyway.
  const answeredAtRef = useRef(0)
  const wasReadingRef = useRef(reading)
  // `error` is why the last fetch never answered (transport/RPC failure — a
  // provider's own failure arrives inside `result` as a stale/failed row).
  // Without it a cold panel whose fetch failed kept saying 正在读取 forever,
  // and a warm one silently kept its old numbers (#1553).
  const [data, setData] = useState<{ result: BalancesResult | null; loading: boolean; error: string | null }>(
    () => ({ result: props.cachedBalances(), loading: false, error: null }),
  )
  const [flash, setFlash] = useState<'ok' | 'same' | null>(null)
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const runBalances = (force: boolean): void => {
    props.fetchBalances(force).then((result) => {
      if (!mountedRef.current) return
      answeredAtRef.current = Date.now()
      setData({ result, loading: false, error: null })
      if (force) {
        // #870 语义:拉到新数据 → ✓(品牌色),命中缓存 → ↻ 变绿,1.2s 回落。
        setFlash(result.providers.some((p) => p.result.status === 'fresh') ? 'ok' : 'same')
        if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current)
        flashTimerRef.current = setTimeout(() => { setFlash(null) }, 1200)
      }
    }, (err: unknown) => {
      if (!mountedRef.current) return
      const error = (err instanceof Error ? err.message : String(err)) || props.t('balance.unknownError')
      setData((current) => ({ ...current, loading: false, error }))
    })
  }

  useEffect(() => {
    mountedRef.current = true
    runBalances(false)
    const unsubscribe = props.subscribeBalances === undefined
      ? null
      : props.subscribeBalances((result) => {
        if (!mountedRef.current) return
        answeredAtRef.current = Date.now()
        setData((current) => ({ ...current, result, error: null }))
      })
    return () => {
      mountedRef.current = false
      if (unsubscribe !== null) unsubscribe()
      if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current)
    }
  }, [pollKey])

  useEffect(() => {
    const intervalMs = _balanceCadence(reading, data.result?.refreshMs)
    // Hidden tabs do not poll; on return the host's per-provider TTL decides whether a fetch
    // happens at all (non-forced), so coming back never refreshes every provider at once.
    const visible = (): boolean => typeof document === 'undefined' || document.visibilityState === 'visible'
    // Became read: fetch now unless the answer on hand is as young as a poll would leave it —
    // opening and closing the panel repeatedly costs one request per host window, not one each.
    if (reading && !wasReadingRef.current && Date.now() - answeredAtRef.current >= _balanceCadence(true, data.result?.refreshMs)) {
      setData((current) => ({ ...current, loading: true }))
      runBalances(false)
    }
    wasReadingRef.current = reading
    let hiddenSince = 0
    const timer = setInterval(() => { if (visible()) runBalances(false) }, intervalMs)
    const onVisibility = (): void => {
      if (!visible()) { hiddenSince = Date.now(); return }
      if (hiddenSince !== 0 && Date.now() - hiddenSince >= intervalMs) runBalances(false)
      hiddenSince = 0
    }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility)
    return () => {
      clearInterval(timer)
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [data.result?.refreshMs, pollKey, reading])

  const refresh = (): void => {
    setData((current) => ({ ...current, loading: true }))
    runBalances(true)
  }
  return { data, flash, refresh }
}

/** The read side every allowance surface shares: cached-first rows, poll, manual refresh. */
function useProviderReadings(props: BalancesInjected & { t: Translate }, pollKey: string, reading = true) {
  const core = useBalanceData(props, pollKey, reading)
  const rows = balanceRows(core.data.result, props.t, Date.now())
  return { ...core, rows }
}

function useProviderBalances(props: BalancesInjected & PropsStore<BalanceStore> & { t: Translate }, pollKey: string, reading = true) {
  const core = useProviderReadings(props, pollKey, reading)
  const selected = props.useStore((state) => state.selected)
  const select = (provider: string): void => { props.actions.select(provider) }
  // 胶囊只讲一个 provider:选中的优先,否则第一行(稳定的 deepseek-first 序)。
  const primary = core.rows.find((row) => row.provider === selected) ?? core.rows[0]
  // What the trigger says before any provider row exists: loading, or the
  // fetch failed (the hollow stale badge, not the blank "nothing to judge").
  const failed = core.rows.length === 0 && core.data.error !== null && !core.data.loading
  const empty = failed
    ? { tone: 'stale' as BalanceTone, title: props.t('balance.readFailed', { message: core.data.error }) }
    : { tone: 'none' as BalanceTone, title: props.t(core.data.result === null ? 'balance.loading' : 'balance.noProviders') }
  return { ...core, primary, select, empty }
}

/**
 * The sidebar-foot glyph: a quota gauge drawn with the geometry and stroke of
 * the host's own `IconGaugeOutline16` (ui-primitives, MIT; redrawn inline
 * because client bundles may not import another plugin's modules), so it sits
 * in the same icon language as Settings and the Cordis badge beside it.
 * Status rides a small badge notched out of the bottom-right corner instead
 * of the whole icon being a coloured disc: round = ok, rounded square = low,
 * hollow ring = stale (the number is not trustworthy), no badge while there
 * is nothing to judge. Each state remains legible without relying on hue.
 * The notch is an SVG mask, not a painted ring, so it stays clean over the
 * host's plain row and its hover wash.
 */
function renderFootStatusBadge(tone: BalanceTone): React.ReactElement | null {
  const attrs = { className: cx('bal-badge'), 'data-balance-state': tone }
  if (tone === 'low') return h('rect', { ...attrs, x: 10.15, y: 10.15, width: 5.2, height: 5.2, rx: 1.1 })
  if (tone === 'ok' || tone === 'stale') {
    return h('circle', { ...attrs, cx: 12.75, cy: 12.75, r: tone === 'stale' ? 2.05 : 2.6 })
  }
  return null
}

function renderBalanceGlyph(tone: BalanceTone, size: number, instanceId: string): React.ReactElement {
  const badge = tone === 'ok' || tone === 'low' || tone === 'stale'
  // Per-instance, not a fixed string: an SVG `mask` is referenced by a document
  // -global id, so two mounted glyphs sharing one id would have the second
  // reuse the first's mask node (and `url(#...)` would resolve to whichever
  // came first). Only one surface mounts today, which is exactly why a fixed id
  // would go unnoticed until a second one existed.
  const notch = 'clawock-balance-notch-' + instanceId
  return h('svg', {
    className: cx('bal-glyph'), width: size, height: size, viewBox: '0 0 16 16', fill: 'none', 'aria-hidden': 'true',
  },
    badge
      ? h('defs', null,
        h('mask', { id: notch, maskUnits: 'userSpaceOnUse', x: 0, y: 0, width: 16, height: 16 },
          h('rect', { x: 0, y: 0, width: 16, height: 16, fill: 'white' }),
          h('circle', { cx: 12.75, cy: 12.75, r: 3.9, fill: 'black' })))
      : null,
    h('g', { mask: badge ? 'url(#' + notch + ')' : undefined },
      h('path', { d: 'M3.49 13.26A6.375 6.375 0 1 1 12.51 13.26', stroke: 'currentColor', strokeWidth: 1.25, strokeLinecap: 'round' }),
      h('path', { d: 'M8 8.75L11.4 5.35', stroke: 'currentColor', strokeWidth: 1.25, strokeLinecap: 'round' }),
      h('circle', { cx: 8, cy: 8.75, r: 1.55, fill: 'currentColor' })),
    renderFootStatusBadge(tone))
}

/** The headline reading: dot (or the foot glyph) · value · reset · weekly sub-reading. */
function renderBalanceHeadline(primary: BalanceRow | undefined, withLabel: boolean, glyph = false, emptyTone: BalanceTone = 'none', instanceId = ''): React.ReactElement {
  const lead = (tone: BalanceTone): React.ReactElement => glyph
    ? h('span', { className: cx('bal-lead') }, renderBalanceGlyph(tone, 16, instanceId))
    : h('span', { className: cx('bchip-dot') })
  return primary === undefined
    ? h('span', { className: cx('bchip-item') }, lead(emptyTone), '—')
    : h('span', { className: cx('bchip-item'), 'data-pb-provider': primary.provider, 'data-pb-role': 'chip', 'data-balance-state': primary.view.tone },
      lead(primary.view.tone),
      withLabel ? h('span', { className: cx('bchip-name') }, primary.label) : null,
      h('span', {
        className: cx('bchip-v'),
        'data-balance-state': primary.view.tone,
        // 用量档位染色(kcn 配色口径,恢复):配额行 ok 绿/mid 黄/low 红;
        // 金额行 level=null 不带属性,保持墨色、low 红走 tone。
        'data-used-level': primary.view.level === null ? undefined : primary.view.level,
      }, primary.view.value),
      // 头条窗口的重置时刻(kcn 反馈:额度用尽要知道什么时候恢复),
      // 面板每窗一行里有完整版,这里是小字同款。
      primary.view.reset === null
        ? null
        : h('span', { className: cx('bchip-reset') }, '↻ ' + primary.view.reset),
      // 周限额副读数(含它自己的重置时刻):装饰性重复(面板/悬浮里有
      // 完整版),对读屏静音。
      primary.view.sub === null
        ? null
        : h('span', { className: cx('bchip-sub'), 'aria-hidden': 'true' }, primary.view.sub))
}

/** The panel body: title + refresh, then every provider row (click = pin). */
function renderBalancePanelBody(state: ReturnType<typeof useProviderBalances>, t: Translate): Array<React.ReactElement | null> {
  const { data, rows, primary, select, flash, refresh } = state
  return [
    h('div', { className: cx('bp-head'), key: 'head' },
      h('span', { className: cx('bp-title') }, t('balance.panelHeading')),
      h('button', {
        type: 'button',
        className: cx('bal-rf', data.loading && 'spin', flash === 'ok' && 'flash-ok', flash === 'same' && 'flash-same'),
        'data-refresh': 'true',
        'aria-label': t('balance.refreshAll'),
        title: t('balance.refreshNow'),
        onClick: refresh,
      }, flash === 'ok' ? '✓' : '↻')),
    rows.length > 0 && data.error !== null && !data.loading
      ? h('div', { className: cx('bp-note', 'warn'), key: 'error', role: 'status' }, t('balance.staleWith', { message: data.error }))
      : null,
    rows.length === 0
      ? h('div', { className: cx('bp-empty'), key: 'empty', role: 'status' },
        data.error !== null && !data.loading ? t('balance.readFailed', { message: data.error }) : t('balance.reading'))
      : h('div', { key: 'rows' }, rows.map((row) => h('button', {
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
        h('span', {
          className: cx('bp-v', row.view.tone === 'low' ? 'bad' : ''),
          'data-balance-state': row.view.tone,
          // 旧版页头 popover 的面板行也走同一套已使用档位;金额行 level=null,
          // 仍由 tone 的 low 决定红色。
          'data-used-level': row.view.level === null ? undefined : row.view.level,
        }, row.view.value),
        // note 与明细并存,不再二选一(#908 根因:互斥三元让水位/stale
        // 警示句把每窗读数、进度条、重置时间整个顶掉)。无窗的异常行由
        // renderRowDetail 自己返回 null,仍是「只讲一句」。
        [
          row.note !== null
            ? h('div', { className: cx('bp-note', row.view.tone === 'stale' ? 'warn' : 'bad'), key: 'note' }, row.note)
            : null,
          renderRowDetail(row, t, Date.now()),
        ]))),
  ]
}

export function ProviderBalanceChip(props: BalanceChipProps): React.ReactElement {
  const t = props.t
  const state = useProviderBalances(props, props.sessionId)
  const { rows, primary } = state
  const [open, setOpen] = useState(false)
  // Stable per mount; React 18's useId is what keeps two glyphs' SVG masks
  // apart without threading a counter through the render helpers.
  const instanceId = useId()
  const rootRef = useRef<HTMLSpanElement | null>(null)

  // 打开时:Escape 关闭,点外面关闭(document 存在才挂——测试环境无 DOM)。
  useEffect(() => {
    if (!open || typeof document === 'undefined') return undefined
    const onKey = (event: KeyboardEvent): void => { if (event.key === 'Escape') setOpen(false) }
    const onDown = (event: MouseEvent): void => {
      const root = rootRef.current
      if (root !== null && event.target instanceof Node && !root.contains(event.target)) setOpen(false)
    }
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  return h('span', { className: cx('pbc'), ref: rootRef },
    h('button', {
      type: 'button',
      className: cx('bchip'),
      'data-balance-state': primary !== undefined ? primary.view.tone : state.empty.tone,
      'data-pb-provider': primary !== undefined ? primary.provider : '',
      'aria-expanded': open,
      'aria-haspopup': 'dialog',
      'aria-label': t('balance.panelTitle'),
      title: primary !== undefined
        ? primary.label + ' · ' + primary.view.title + (rows.length > 1 ? t('balance.otherProviders') : '')
        : state.empty.title,
      onClick: () => { setOpen(!open) },
    }, renderBalanceHeadline(primary, false, false, state.empty.tone, instanceId)),
    h('div', panelAttrs(open, t('balance.panelTitle')), renderBalancePanelBody(state, t)))
}

/** The main panel key and the panellist id are the same id (the host contract). */
export const WORKBENCH_PANEL = 'clawock-workbench'

/** The prop contract both balance surfaces' popover panel renders (see `panelAttrs`). */
type PanelAttrs = {
  className: string
  ref?: React.Ref<HTMLDivElement>
  'data-open': string
  role: 'dialog' | 'none'
  'aria-label': string
  /** Empty string = present (React 18's attribute form); undefined = absent. */
  inert: '' | undefined
  style?: Record<string, string>
  'data-clawock-popover'?: string
}

/**
 * The shared popover attributes. The closed panel is hidden with opacity +
 * `pointer-events:none` (so the open/close transition keeps working), and
 * `inert` is what actually removes it from interaction: opacity alone leaves
 * every row button and the refresh control in the tab order, so a keyboard
 * user tabbing through the sidebar used to land on five invisible controls.
 *
 * `inert` is written as `''`, never `true`. The host ships React 18
 * (@types/react ~18.3, react ^18.2), where `inert` is not yet a known boolean
 * attribute: `inert={true}` is dropped without a warning in the production
 * build, which is how the first version of this fix rendered an attribute-less
 * panel and changed nothing. React 19 added the boolean form; the empty-string
 * form works on both, and is the idiom already used for `data-active` below.
 */
function panelAttrs(open: boolean, label: string, extra?: Partial<PanelAttrs>): PanelAttrs {
  return {
    className: cx('bp'),
    'data-open': open ? 'true' : 'false',
    role: open ? 'dialog' : 'none',
    'aria-label': label,
    inert: open ? undefined : '',
    ...extra,
  }
}

// ---------------------------------------------------------------------------
// Dispatch task queue: the shared read behind the workbench's queue and the
// provider rows. The old footer cell is gone (2026-11-07).
// ---------------------------------------------------------------------------

/** What the task chip's `inject` factory hands the component. */
export interface TaskQueueInjected {
  /** The last answer this registration fetched, or null cold. */
  cachedTaskQueue: () => TaskQueueResult | null
  /** Read the queue; `force` bypasses the short host cache (the manual refresh). */
  fetchTaskQueue: (force: boolean) => Promise<TaskQueueResult>
  /**
   * Frozen task/token totals, read only when the panel opens. Optional: a host
   * half older than the `taskStats` method has no stats card.
   */
  fetchTaskStats?: (query: { days: number | null; since: string | null; patrol: boolean }) => Promise<TaskStats>
  /**
   * One write (or on-demand read) through the host's versioned ops entry.
   * Optional: without it the panel is read-only.
   */
  runQueueAction?: (action: string, id: string, arg: string) => Promise<QueueActionResult>
}

/** The chip's stats window: last seven local days, today included (task_queue_ops.py summary). */
const STATS_DAYS = 7

/** Cached-first read, the mount fetch and the poll, like useProviderBalances in miniature. */
function useTaskQueue(props: TaskQueueInjected & { t: Translate }) {
  const mountedRef = useRef(true)
  const [data, setData] = useState<{ result: TaskQueueResult | null; loading: boolean; error: string | null }>(
    () => ({ result: props.cachedTaskQueue(), loading: false, error: null }),
  )
  const read = (force: boolean): void => {
    props.fetchTaskQueue(force).then((result) => {
      if (mountedRef.current) setData({ result, loading: false, error: null })
    }, (err: unknown) => {
      if (!mountedRef.current) return
      const error = (err instanceof Error ? err.message : String(err)) || props.t('balance.unknownError')
      setData((current) => ({ ...current, loading: false, error }))
    })
  }
  useEffect(() => {
    mountedRef.current = true
    read(false)
    return () => { mountedRef.current = false }
  }, [])
  useEffect(() => {
    // Not visible, not polled (C12): a hidden tab skips its ticks, and coming back reads once
    // through the host's 5s TTL instead of catching up on every tick it missed.
    const visible = (): boolean => typeof document === 'undefined' || document.visibilityState === 'visible'
    const timer = setInterval(() => { if (visible()) read(false) }, Math.max(5000, data.result?.refreshMs ?? 15000))
    const onVisible = (): void => { if (visible()) read(false) }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(timer)
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible)
    }
  }, [data.result?.refreshMs])
  const refresh = (): void => {
    setData((current) => ({ ...current, loading: true }))
    read(true)
  }
  return { data, refresh }
}

// ---- The four layers: executor, model, slot, notification ------------------

/**
 * The executor layer: a 14px outline glyph in the host's icon stroke, one
 * shape per CLI. All three are plugin-drawn pictograms, not vendor marks:
 * Claude a spark, Codex a terminal prompt, OpenCode brackets. The Codex
 * prompt identifies the coding CLI without pretending a generic hexagon is
 * OpenAI artwork. Monochrome label ink keeps these separate from status.
 */
function renderAgentGlyph(agent: string, size = 14): React.ReactElement {
  if (agent === 'dsh') return renderWhale(size, { 'data-tq-agent': agent })
  const stroke = { stroke: 'currentColor', strokeWidth: 1.25, strokeLinecap: 'round', strokeLinejoin: 'round', fill: 'none' }
  const shape = agent === 'claude'
    ? h('path', { ...stroke, d: 'M7 1.8V12.2M1.8 7H12.2M3.3 3.3L10.7 10.7M10.7 3.3L3.3 10.7' })
    : agent === 'codex'
      ? h('path', { ...stroke, d: 'M2.5 3.5L6.3 7L2.5 10.5M7.5 10.5H11.5' })
      : agent === 'opencode'
        ? h('path', { ...stroke, d: 'M5 2H2.5V12H5M9 2H11.5V12H9' })
        : h('circle', { ...stroke, cx: 7, cy: 7, r: 5 })
  return h('svg', {
    className: cx('tq-agent-glyph'), width: size, height: size, viewBox: '0 0 14 14', 'aria-hidden': 'true', 'data-tq-agent': agent,
  }, shape)
}

const RECEIPT_GLYPH: Record<ReceiptState, string> = {
  sent: 'M1.6 5.2L3.6 7.2L8.4 2.4', failed: 'M2.2 2.2L7.8 7.8M7.8 2.2L2.2 7.8',
  unknown: 'M3.3 3.4a1.7 1.7 0 1 1 2.3 1.6C5.1 5.2 5 5.5 5 6M5 8v.1', planned: 'M2.2 5H7.8',
}

function renderNotifyIcons(task: DispatchTask, t: Translate, live: boolean): React.ReactElement | null {
  return renderReceipts(notifyChannels(task).map((ch) => ({ ch, state: _notifyState(task, ch, live) })), t)
}

function renderReceipts(receipts: ReadonlyArray<{ ch: string; state: ReceiptState }>, t: Translate): React.ReactElement | null {
  if (receipts.length === 0) return null
  const said = receipts.map(({ ch, state }) => t('queue.notify.' + state, { ch: t('queue.ch.' + ch) })).join(' · ')
  return h('span', { className: cx('tq-notify'), role: 'img', 'aria-label': said, title: said + ' — ' + t('queue.receiptLegend') },
    receipts.map(({ ch, state }) => {
      return h('span', { key: ch, className: cx('tq-receipt'), 'data-tq-notify': ch, 'data-state': state },
        h('svg', { className: cx('tq-notify-glyph'), width: 12, height: 12, viewBox: '0 0 12 12', 'aria-hidden': 'true' },
          ch === 'telegram'
            ? h('path', { d: 'M1.5 5.6L10.5 2L8.9 10L6.1 7.9L4.8 9.3L4.7 7L8.4 3.9L3.9 6.5Z', fill: 'currentColor' })
            : ch === 'weixin'
              ? h('path', { d: 'M4.6 2C2.6 2 1 3.3 1 5c0 .9.5 1.7 1.2 2.3L1.9 8.6l1.5-.8c.4.1.8.2 1.2.2h.2A2.8 2.8 0 0 1 7.6 5.3c.5 0 .9.1 1.3.2C8.6 3.5 6.8 2 4.6 2ZM7.6 6.1c-1.5 0-2.7 1-2.7 2.2s1.2 2.2 2.7 2.2c.3 0 .6 0 .9-.1l1.2.6-.3-1c.6-.4 1-1 1-1.7 0-1.2-1.2-2.2-2.8-2.2Z', fill: 'currentColor' })
              : h('circle', { cx: 6, cy: 6, r: 3, fill: 'currentColor' })),
        h('svg', { className: cx('tq-receipt-glyph'), width: 10, height: 10, viewBox: '0 0 10 10', 'aria-hidden': 'true' },
          h('path', { d: RECEIPT_GLYPH[state], stroke: 'currentColor', strokeWidth: 1.4, fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' })))
    }))
}

// ---- Rows: one grid for every line of the cell -----------------------------------

function renderRoleGlyph(role: StateRole): React.ReactElement {
  return h('svg', { className: cx('tq-role-glyph'), width: 10, height: 10, viewBox: '0 0 10 10', 'aria-hidden': 'true' },
    STATE_ROLES[role].glyph.map((part, i) => part.paint === 'fill'
      ? h('path', { key: i, d: part.d, fill: 'currentColor' })
      : h('path', { key: i, d: part.d, stroke: 'currentColor', strokeWidth: 1.3, fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' })))
}

/** THE chip: a row's one state, in its role (bed + glyph + word). */
function renderChip(chip: SlotChip, opts: { key?: string; slot?: string } = {}): React.ReactElement {
  return h('span', {
    className: cx('tq-chip'), key: opts.key ?? opts.slot ?? chip.text,
    'data-role': chip.role, 'data-bed': STATE_ROLES[chip.role].bed, 'data-tq-chip': opts.slot, title: chip.title ?? chip.text,
  }, renderRoleGlyph(chip.role), h('span', { className: cx('tq-chip-text') }, chip.text))
}
/** The one chevron the raw-log fold and the coverage link share. */
function foldChevron(): React.ReactElement {
  // One chevron glyph for the workbench folds and the old detail's folds;
  // only the class that owns the rotation differs.
  return renderWorkbenchChevron(12, 'tq-fold-chev')
}

/**
 * The chart's four roles, the same mapping as the stats card's completion bar: done is the
 * business blue, a partial/preempted round is warn amber, a failed round is error red, and
 * anything with no verdict is idle grey. The chip beside a row keeps its own role; the chart
 * is a summary and uses the chart scale, exactly as the stats bar does.
 */
function chartRole(role: StateRole | null | undefined): 'done' | 'partial' | 'fail' | 'idle' {
  return role === 'done' ? 'done' : role === 'partial' ? 'partial' : role === 'fail' ? 'fail' : 'idle'
}

/**
 * The raw supervisor log's fold inside a task's detail. It is the only fold left on the panel:
 * a native <details> whose summary is a hairline capsule. The patrol history is one list and the
 * coverage is a page; neither is a fold. Opening is immediate; the content fades in.
 */
function renderFold(kind: string, label: string, children: Array<React.ReactElement | null>): React.ReactElement {
  return h('details', { className: cx('tq-fold', 'tq-fold-pill'), key: 'fold-' + kind, 'data-tq-fold': kind },
    h('summary', { className: cx('tq-fold-summary') },
      foldChevron(),
      h('span', { className: cx('tq-fold-label') }, label)),
    h('div', { className: cx('tq-fold-body') }, ...children))
}

type QueueUi = {
  open: (id: string) => void
  act: (action: string, task: DispatchTask, arg?: string) => void
  busy: string | null
  writable: boolean
}

/**
 * Brand marks the host itself ships, drawn in the glyph ink: DeepSeek's whale
 * is dsh's own logo (the same path its sidebar header draws), so the plugin
 * carries no artwork the host does not already show.
 */
const DEEPSEEK_WHALE = 'M22.9168 1.43018C22.6713 1.31018 22.5658 1.53918 22.4223 1.65519C22.3733 1.69269 22.3318 1.74169 22.2903 1.78669C21.9317 2.1697 21.5127 2.42121 20.9657 2.39121C20.1657 2.34621 19.4827 2.59771 18.8787 3.20973C18.7502 2.45521 18.3236 2.0047 17.6746 1.71569C17.3351 1.56568 16.9916 1.41518 16.7536 1.08867C16.5876 0.856163 16.5421 0.597155 16.4591 0.341647C16.4061 0.187643 16.3536 0.0301382 16.1761 0.00363739C15.9836 -0.0263635 15.9081 0.135141 15.8326 0.270145C15.5306 0.822162 15.4136 1.43018 15.4251 2.0462C15.4516 3.43174 16.0366 4.53527 17.1991 5.3203C17.3311 5.4103 17.3651 5.5003 17.3236 5.63181C17.2441 5.90231 17.1501 6.16482 17.0671 6.43533C17.0141 6.60784 16.9351 6.64584 16.7501 6.57033C16.1121 6.30383 15.5611 5.90931 15.074 5.4328C14.2475 4.63328 13.5 3.75075 12.568 3.05973C12.349 2.89822 12.13 2.74822 11.9034 2.60522C10.9524 1.68169 12.028 0.923165 12.277 0.833162C12.5375 0.739159 12.3675 0.41615 11.5259 0.42015C10.6844 0.42365 9.91439 0.705658 8.93286 1.08117C8.78935 1.13767 8.63835 1.17867 8.48384 1.21267C7.59332 1.04367 6.66829 1.00617 5.70226 1.11517C3.88321 1.31768 2.43016 2.1777 1.36213 3.64575C0.0790928 5.4103 -0.222916 7.41536 0.146595 9.50642C0.535106 11.7105 1.66014 13.535 3.38869 14.9616C5.18125 16.4406 7.24581 17.1657 9.60138 17.0266C11.0319 16.9441 12.6245 16.7526 14.421 15.2321C14.874 15.4576 15.3496 15.5476 16.1381 15.6151C16.7456 15.6716 17.3306 15.5851 17.7836 15.4911C18.4931 15.3411 18.4441 14.6841 18.1876 14.5636C16.1081 13.595 16.5646 13.9891 16.1496 13.67C17.2061 12.42 18.8202 10.1979 19.3182 7.17235C19.3672 6.83834 19.4297 6.36783 19.4222 6.09732C19.4182 5.93231 19.4562 5.86831 19.6447 5.84931C20.1657 5.78931 20.6712 5.64681 21.1357 5.3913C22.4833 4.65528 23.0268 3.44624 23.1548 1.9972C23.1738 1.77569 23.1508 1.54668 22.9168 1.43018ZM11.1749 14.4736C9.15936 12.889 8.18184 12.3675 7.77832 12.39C7.40081 12.4125 7.46881 12.8445 7.55182 13.126C7.63882 13.404 7.75182 13.5955 7.91033 13.8396C8.01983 14.0011 8.09533 14.2411 7.80083 14.4216C7.15181 14.8231 6.02327 14.2866 5.97027 14.2601C4.65673 13.4865 3.5587 12.4655 2.78467 11.069C2.03715 9.72493 1.60314 8.28289 1.53164 6.74384C1.51264 6.37233 1.62214 6.24082 1.99215 6.17332C2.47916 6.08332 2.98118 6.06432 3.46769 6.13582C5.52476 6.43633 7.27581 7.35586 8.74385 8.8129C9.58188 9.64243 10.2159 10.634 10.8689 11.6025C11.5634 12.631 12.3105 13.611 13.262 14.4146C13.598 14.6961 13.866 14.9101 14.1225 15.0681C13.349 15.1546 12.058 15.1731 11.1749 14.4746L11.1749 14.4736ZM12.141 8.25988C12.141 8.09488 12.273 7.96338 12.439 7.96338C12.4765 7.96338 12.5105 7.97088 12.541 7.98188C12.5825 7.99688 12.6205 8.01938 12.6505 8.05338C12.7035 8.10588 12.7335 8.18088 12.7335 8.25988C12.7335 8.42489 12.6015 8.55639 12.4355 8.55639C12.2695 8.55639 12.141 8.42489 12.141 8.25988ZM15.1415 9.79893C14.949 9.87793 14.7565 9.94544 14.5715 9.95294C14.2845 9.96794 13.9715 9.85143 13.8015 9.70893C13.5375 9.48742 13.3485 9.36342 13.2695 8.97691C13.2355 8.8119 13.2545 8.55639 13.2845 8.40989C13.3525 8.09438 13.277 7.89187 13.0545 7.70787C12.8735 7.55786 12.643 7.51636 12.39 7.51636C12.2955 7.51636 12.209 7.47486 12.1445 7.44136C12.039 7.38886 11.9519 7.25735 12.035 7.09585C12.0615 7.04335 12.19 6.91584 12.22 6.89334C12.5635 6.69784 12.9595 6.76184 13.326 6.90834C13.6655 7.04735 13.9225 7.30236 14.292 7.66287C14.6695 8.09838 14.7375 8.21838 14.9525 8.54539C15.1225 8.8009 15.277 9.06341 15.3831 9.36392C15.4471 9.55142 15.3641 9.70493 15.1415 9.79893Z'

/** The whale in the glyph ink: the DeepSeek balance row and dsh's own tasks (the agent it pays for). */
function renderWhale(size: number, data: Record<string, string>): React.ReactElement {
  return h('svg', {
    className: cx('tq-agent-glyph'), width: size, height: size, viewBox: '0 -3.06 23.16 23.16', 'aria-hidden': 'true', ...data,
  }, h('path', { d: DEEPSEEK_WHALE, fill: 'currentColor' }))
}

/**
 * The provider identity layer for a row: 14px, the executor glyphs' ink.
 * DeepSeek is its whale (its queue is dsh's, whose glyph is the same whale);
 * a row with an agent wears the agent's glyph; the rest keep a letterform-free
 * outline — MiniMax a wave, anything else a plain ring.
 */
function renderSourceGlyph(source: PanelSource): React.ReactElement {
  if (source.key === 'deepseek') return renderWhale(14, { 'data-pp-provider': source.key })
  if (source.agent !== null || source.join?.agent) return renderAgentGlyph(source.agent ?? source.join!.agent!)
  const stroke = { stroke: 'currentColor', strokeWidth: 1.25, strokeLinecap: 'round', strokeLinejoin: 'round', fill: 'none' }
  const shape = source.join?.kind === 'windows'
    ? h('path', { ...stroke, d: 'M1.8 9.5L4 4.5L7 9.5L10 4.5L12.2 9.5' })
    : h('circle', { ...stroke, cx: 7, cy: 7, r: 5 })
  return h('svg', {
    className: cx('tq-agent-glyph'), width: 14, height: 14, viewBox: '0 0 14 14', 'aria-hidden': 'true', 'data-pp-provider': source.key,
  }, shape)
}


/**
 * The patrol summary: the same rounds as the list below, drawn once. One thin segment per round,
 * newest first (the list's order), colour on the stats chart's four roles. The counts underneath
 * are the legend in words; the bar itself is decorative for a screen reader.
 *
 * This is a tinted strip, not the 14px wall of solid tiles the first pass used: the solid token
 * is reserved for the 5px count dots, and the bar takes the 35% chart tint. That keeps the same
 * semantic roles while dropping the saturated area by ~80%.
 */
function renderPatrolRhythm(rhythm: PatrolRhythm): React.ReactElement {
  return h('div', { className: cx('tq-rhythm'), 'data-tq-rhythm': 'true' },
    h('div', { className: cx('tq-rhythm-bar'), 'aria-hidden': 'true' },
      ...rhythm.bars.map((bar, at) => h('span', {
        key: bar.key,
        className: cx('tq-rhythm-seg'),
        'data-role': chartRole(bar.role),
        'data-tq-rhythm-round': bar.round,
        title: bar.title,
        style: { transitionDelay: (at * 30) + 'ms' },
      }))),
    h('div', { className: cx('tq-rhythm-summary') },
      ...rhythm.summary.flatMap((item, at) => [
        at === 0 ? null : h('span', { key: 'sep-' + item.role, className: cx('tq-rhythm-sep') }, ' · '),
        h('span', { key: item.role, className: cx('tq-rhythm-item'), 'data-role': chartRole(item.role) },
          h('span', { className: cx('tq-rhythm-dot'), 'aria-hidden': 'true' }), item.text),
      ].filter((part): part is React.ReactElement => part !== null))))
}

/** The coverage tables, shared by the page; the page's scroll and back bar are the layer's. */
function renderCoverageTables(view: CoverageView, t: Translate): Array<React.ReactElement | null> {
  const link = (name: string, href: string): React.ReactElement => h('a', { className: cx('tq-cov-name'), href, target: '_blank', rel: 'noopener noreferrer' }, name)
  const heading = (text: string, note: string): React.ReactElement[] => [
    h('h3', { className: cx('tq-cov-head'), key: 'h' }, text),
    h('p', { className: cx('tq-cov-note'), key: 'n' }, note),
  ]
  const nothing = h('p', { className: cx('tq-cov-note') }, view.empty)
  const badge = (open: string, hasOpen: boolean | null): React.ReactElement =>
    h('span', { className: cx('tq-cov-open'), 'data-open': hasOpen === null ? 'unknown' : String(hasOpen) }, open)
  const needs = view.lenses.filter((l) => l.hasOpen === true || l.last?.state?.role === 'fail')
  const rest = view.lenses.filter((l) => !needs.includes(l))
  let lensAt = 0
  const lensRow = (l: (typeof view.lenses)[number]): React.ReactElement => {
    const delay = (Math.min(lensAt++, 7) * 30) + 'ms'
    return h('li', { key: l.name, className: cx('tq-cov-lens'), 'data-coverage-lens': l.name },
      h('div', { className: cx('tq-cov-lens-head') },
        h('span', { className: cx('tq-cov-lens-name') },
          h('span', { className: cx('tq-cov-lens-dot'), 'data-role': chartRole(l.last?.state?.role), 'aria-hidden': 'true' }),
          link(l.name, l.href)),
        badge(l.open, l.hasOpen)),
      h('div', { className: cx('tq-cov-lens-meta') },
        l.last === null
          ? h('span', { className: cx('tq-cov-last') }, l.none)
          : h('span', { className: cx('tq-cov-last') },
            h('span', { key: 'r' }, l.last.round),
            l.last.state === null ? null : h('span', { key: 's', className: cx('tq-cov-state'), 'data-role': l.last.state.role, title: l.last.state.title },
              renderRoleGlyph(l.last.state.role), l.last.state.text),
            l.when === null ? null : h('span', { key: 'w' }, l.when.text)),
        h('span', { className: cx('tq-cov-runs') },
          h('span', { className: cx('tq-cov-runs-bar'), 'aria-hidden': 'true' },
            l.runsShare === null ? null : h('span', { className: cx('tq-cov-runs-fill'), style: {
              width: Math.max(2, Math.round(l.runsShare * 28)) + 'px', transitionDelay: delay } })),
          h('span', { className: cx('tq-cov-runs-num') }, l.runs + ' ' + view.columns.runs))))
  }
  const band = (kind: 'needs' | 'rotation', label: string): React.ReactElement =>
    h('div', { key: 'band-' + kind, className: cx('tq-cov-band'), 'data-band': kind, role: 'heading', 'aria-level': 5 },
      h('span', { className: cx('tq-cov-band-dot'), 'aria-hidden': 'true' }),
      h('span', null, label))
  return [
    ...view.alerts.map((text) => h('div', { key: text, className: cx('tq-cov-alert'), role: 'status' }, text)),
    h('section', { className: cx('tq-cov-block'), 'data-coverage': 'areas' },
      ...heading(view.areaHeading, view.areaNote),
      view.areas.length === 0 && view.clear.names.length === 0 ? nothing : null,
      view.areas.length === 0 ? null : h('ul', { className: cx('tq-cov-list') }, ...view.areas.map((a, at) =>
        h('li', { key: a.name, className: cx('tq-cov-area'), 'data-coverage-area': a.name },
          h('div', { className: cx('tq-cov-area-head') },
            link(a.name, a.href),
            badge(a.open, a.hasOpen)),
          h('span', { className: cx('tq-cov-bar'), 'aria-hidden': 'true' },
            a.share === null ? null : h('span', { className: cx('tq-cov-fill'), style: {
              width: Math.round(a.share * 100) + '%', transitionDelay: (Math.min(at, 7) * 30) + 'ms' } }))))),
      view.clear.names.length === 0 ? null : h('div', { className: cx('tq-cov-clear') },
        h('span', { className: cx('tq-cov-clear-label') }, h('span', { className: cx('tq-cov-clear-mark') }, renderRoleGlyph('done')), view.clear.label),
        ...view.clear.names.map((a) => h('span', { key: a.name, 'data-coverage-area': a.name }, link(a.name, a.href))))),
    h('section', { className: cx('tq-cov-block'), 'data-coverage': 'lenses' },
      ...heading(view.lensHeading, view.lensNote),
      view.lenses.length === 0 ? nothing : [
        needs.length === 0 ? null : band('needs', t('queue.coverage.needsLook')),
        h('ul', { key: 'needs-list', className: cx('tq-cov-list') }, ...needs.map(lensRow)),
        rest.length === 0 ? null : band('rotation', t('queue.coverage.byRotation')),
        h('ul', { key: 'rest-list', className: cx('tq-cov-list') }, ...rest.map(lensRow)),
      ]),
    view.footnote === '' ? null : h('p', { className: cx('tq-cov-foot') }, view.footnote),
  ]
}

/** One read-only dashboard tile: label (with its mark), value, caption. */
function renderPatrolKpi(kind: string, label: string, value: string, caption: string,
  dot: React.ReactElement | null): React.ReactElement {
  return h('div', { className: cx('tq-patrol-kpi'), 'data-tq-patrol-kpi': kind },
    h('div', { className: cx('tq-patrol-kpi-label') }, dot, h('span', null, label)),
    h('div', { className: cx('tq-patrol-kpi-value') }, value),
    h('div', { className: cx('tq-patrol-kpi-caption') }, caption))
}

/** The patrol page opens with four tiles: latest verdict, open areas, open lenses, rounds. */
function renderPatrolKpis(patrol: NonNullable<PanelModel['patrol']>, t: Translate): React.ReactElement {
  const latest = patrol.rounds[0] ?? null
  const progress = patrol.progress
  const latestCaption = latest === null
    ? t('queue.patrol.kpi.none')
    : [latest.state?.text ?? '', latest.facts.when?.text ?? ''].filter((part) => part !== '').join(' · ')
  const latestDot = latest === null || latest.state === null ? null
    : h('span', { className: cx('tq-patrol-kpi-dot'), 'data-role': chartRole(latest.state.role), 'aria-hidden': 'true' })
  const openAreas = progress === null ? null : progress.areas.length
  const openLenses = progress === null ? null : progress.lenses.filter((lens) => lens.hasOpen === true).length
  const areaTone = progress === null ? 'unknown' : progress.tone
  const lensTone = progress === null ? 'unknown' : openLenses! > 0 ? 'open' : 'none'
  const areaCaption = progress === null
    ? t('queue.patrol.kpi.unknown')
    : areaTone === 'none' ? t('queue.patrol.kpi.noneOpen') : t('queue.patrol.kpi.open')
  const lensCaption = progress === null
    ? t('queue.patrol.kpi.unknown')
    : openLenses! > 0 ? t('queue.patrol.kpi.open') : t('queue.patrol.kpi.noneOpen')
  return h('div', { className: cx('tq-patrol-kpis'), 'data-tq-patrol-dashboard': 'true' },
    renderPatrolKpi('latest', t('queue.patrol.kpi.latest'), latest === null ? '—' : latest.name,
      latestCaption, latestDot),
    renderPatrolKpi('areas', t('queue.patrol.kpi.areas'), openAreas === null ? '—' : String(openAreas),
      areaCaption, h('span', { className: cx('tq-patrol-kpi-dot'), 'data-coverage-state': areaTone, 'aria-hidden': 'true' })),
    renderPatrolKpi('lenses', t('queue.patrol.kpi.lenses'), openLenses === null ? '—' : String(openLenses),
      lensCaption, h('span', { className: cx('tq-patrol-kpi-dot'), 'data-coverage-state': lensTone, 'aria-hidden': 'true' })),
    renderPatrolKpi('rounds', t('queue.patrol.kpi.rounds'), String(patrol.rounds.length),
      t('queue.patrol.kpi.roundsCaption'), null))
}

/** One patrol round: round · state · time · duration, on one line, right edges aligned. */
function renderPatrolRounds(patrol: NonNullable<PanelModel['patrol']>, t: Translate): React.ReactElement {
  if (patrol.rounds.length === 0) return h('p', { className: cx('wb-ov-note') }, t('queue.patrol.kpi.none'))
  return h('ul', { className: cx('wb-ov-rounds') }, ...patrol.rounds.map((round) => h('li', {
    key: round.key, className: cx('wb-ov-round'), 'data-wb-round': round.key,
  },
    h('span', { className: cx('wb-ov-round-name') }, round.name),
    round.state === null ? h('span', { className: cx('wb-ov-round-state') }, '—')
      : h('span', { className: cx('wb-ov-round-state'), 'data-role': round.state.role, title: round.state.title },
        renderRoleGlyph(round.state.role), round.state.text),
    h('span', { className: cx('wb-ov-round-when') }, round.facts.when?.text ?? '—'),
    h('span', { className: cx('wb-ov-round-took') }, round.facts.took?.text ?? '—'))))
}

/** The patrol fold's body: the four summary rows, KPI tiles, outcome strip, rounds and coverage. */
function renderPatrolBody(summary: React.ReactNode, patrol: NonNullable<PanelModel['patrol']>, t: Translate): React.ReactElement {
  return h('div', { className: cx('wb-ov-body', 'pbc', 'tqf') },
    summary,
    renderPatrolKpis(patrol, t),
    patrol.rhythm === null ? null : h('section', { className: cx('wb-ov-sec'), 'data-wb-ov-sec': 'outcome' },
      h('div', { className: cx('wb-ov-sec-head') },
        h('h3', { className: cx('wb-ov-sec-title') }, t('queue.patrol.section.outcome')),
        h('span', { className: cx('wb-ov-sec-count') }, t('queue.patrol.count.rounds', { n: patrol.rounds.length }))),
      renderPatrolRhythm(patrol.rhythm)),
    h('section', { className: cx('wb-ov-sec'), 'data-wb-ov-sec': 'rounds' },
      h('div', { className: cx('wb-ov-sec-head') },
        h('h3', { className: cx('wb-ov-sec-title') }, t('queue.patrol.section.rounds')),
        h('span', { className: cx('wb-ov-sec-count') }, t('queue.patrol.count.records', { n: patrol.rounds.length }))),
      renderPatrolRounds(patrol, t)),
    patrol.progress === null ? null : h('section', { className: cx('wb-ov-sec', 'tq-cov'), 'data-wb-ov-sec': 'coverage' },
      h('div', { className: cx('wb-ov-sec-head') },
        h('h3', { className: cx('wb-ov-sec-title') }, t('queue.patrol.section.coverage')),
        h('span', { className: cx('wb-ov-sec-count') }, patrol.progress.conclusion)),
      ...renderCoverageTables(patrol.progress, t)))
}

/** The stats fold's body: the old per-agent tables and stacked chart, full width. */
function renderStatsBody(stats: StatsView, t: Translate): React.ReactElement {
  const legend = [
    { kind: 'done', label: t('stats.legend.done') },
    { kind: 'partial', label: t('stats.legend.partial') },
    { kind: 'unfinished', label: t('stats.legend.unfinished') },
    ...(stats.totals.live > 0 ? [{ kind: 'live', label: t('stats.legend.live') }] : []),
  ]
  const tokenRow = (agent: StatsView['agents'][number]): React.ReactElement => h('div', {
    className: cx('tq-stats-row'), 'data-tq-stats-token': agent.agent, key: 't-' + agent.agent,
  },
    h('div', { className: cx('tq-stats-row-head') },
      h('span', { className: cx('tq-stats-agent') }, renderAgentGlyph(agent.agent, 14),
        h('span', { className: cx('tq-stats-agent-name') }, agent.label)),
      h('span', { className: cx('tq-stats-numbers') }, agent.tokensText + ' · ' + agent.costText)),
    h('div', { className: cx('tq-stats-track') },
      h('div', { className: cx('tq-stats-fill'), style: { width: Math.round(agent.share * 100) + '%' } })))
  const doneRow = (agent: StatsView['agents'][number]): React.ReactElement => h('div', {
    className: cx('tq-stats-row'), 'data-tq-stats-done': agent.agent, key: 'd-' + agent.agent,
  },
    h('div', { className: cx('tq-stats-row-head') },
      h('span', { className: cx('tq-stats-agent') }, renderAgentGlyph(agent.agent, 14),
        h('span', { className: cx('tq-stats-agent-name') }, agent.label)),
      h('span', { className: cx('tq-stats-numbers') }, t('stats.card.done', { done: agent.done, settled: agent.settled }))),
    renderStatsBar(agent, true),
    h('div', { className: cx('tq-stats-breakdown') },
      t('stats.partial', { n: agent.partial }), ' · ', t('stats.unfinished', { n: agent.unfinished }),
      agent.live > 0 ? ' · ' + t('stats.live', { n: agent.live }) : ''))
  return h('div', { className: cx('wb-ov-body', 'pbc', 'tqf') },
    stats.series === null ? h('div', { className: cx('wb-ov-note') }, t('workbench.overview.noData'))
      : h('div', { className: cx('tq-stats-chart-wrap') }, renderStatsSeries(stats.series, t)),
    h('section', { className: cx('wb-ov-sec') },
      h('h3', { className: cx('wb-ov-sec-title') }, t('stats.tokenHeading')),
      ...stats.agents.map(tokenRow)),
    h('section', { className: cx('wb-ov-sec') },
      h('h3', { className: cx('wb-ov-sec-title') }, t('stats.doneHeading')),
      h('div', { className: cx('tq-stats-legend') },
        ...legend.map((item) => h('span', { className: cx('tq-stats-legend-item'), key: item.kind },
          h('span', { className: cx('tq-stats-swatch', 'tq-stats-seg-' + item.kind), 'aria-hidden': 'true' }),
          item.label))),
      ...stats.agents.map(doneRow)),
    h('p', { className: cx('tq-stats-foot') }, stats.footnote))
}

/** The history fold: one button per ended task; the detail it opens is the Tasks detail. */
function renderHistoryBody(rows: HistoryRowView[], t: Translate, open: (id: string, element: HTMLElement | null) => void): React.ReactElement {
  if (rows.length === 0) return h('p', { className: cx('wb-ov-note') }, t('workbench.history.empty'))
  const row = (item: HistoryRowView): React.ReactElement => h('li', { key: item.id },
    h('button', {
      type: 'button', className: cx('wb-hist-row'), 'data-wb-history': item.id,
      'data-wb-tone': item.tone, 'aria-label': item.aria,
      onClick: (event?: { currentTarget?: HTMLElement }) => { open(item.id, event?.currentTarget ?? null) },
    },
      h('span', { className: cx('wb-hist-main') },
        h('span', { className: cx('wb-hist-title') }, item.title),
        item.meta === '' ? null : h('span', { className: cx('wb-hist-meta') }, item.meta)),
      h('span', { className: cx('wb-hist-state'), 'data-role': item.stateRole }, item.stateText),
      item.cost === '' ? null : h('span', { className: cx('wb-hist-cost') }, item.cost)))
  return h('ul', { className: cx('wb-hist') }, ...rows.map(row))
}

type StatsBarCounts = { done: number; partial: number; unfinished: number; live: number }

/** The one stacked bar: done · partial · unfinished · live, each segment proportional to its count. */
function renderStatsBar(counts: StatsBarCounts, large = false): React.ReactElement {
  const part = (n: number, kind: string): React.ReactElement | null => n > 0
    ? h('span', { className: cx('tq-stats-seg', 'tq-stats-seg-' + kind), style: { flexGrow: String(n) }, key: kind })
    : null
  return h('span', { className: cx('tq-stats-bar', large && 'tq-stats-bar-lg'), 'aria-hidden': 'true' },
    part(counts.done, 'done'), part(counts.partial, 'partial'), part(counts.unfinished, 'unfinished'), part(counts.live, 'live'))
}

/** A clean axis top: 1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8 or 10 × 10^n. */
function statsNiceMax(n: number): number {
  if (!(n > 0)) return 1
  const base = Math.pow(10, Math.floor(Math.log10(n)))
  const x = n / base
  const step = x <= 1 ? 1 : x <= 1.25 ? 1.25 : x <= 1.5 ? 1.5 : x <= 2 ? 2 : x <= 2.5 ? 2.5
    : x <= 3 ? 3 : x <= 4 ? 4 : x <= 5 ? 5 : x <= 6 ? 6 : x <= 8 ? 8 : 10
  return step * base
}

/**
 * The daily chart: one stacked provider bar per day on a single left axis. Stacking makes the
 * bar's full height the day total by construction, so there is no separate total line and no
 * second axis. A 1px gap keeps the provider segments readable; the legend and the note carry
 * the unknown/lower-bound caveat without a "+".
 */
function renderStatsSeries(series: StatsSeriesView, t: Translate): React.ReactElement {
  const W = 320
  const H = 172
  const L = 34
  const R = 10
  const T = 12
  const B = 30
  const plotW = W - L - R
  const plotH = H - T - B
  const max = statsNiceMax(series.maxTotal)
  const groupW = plotW / Math.max(1, series.days.length)
  const barW = Math.min(18, Math.max(10, groupW * 0.5))
  const center = (i: number): number => L + groupW * (i + 0.5)
  const grid = [0, 0.5, 1]
  const dayText = series.days.map((day) => day.label + ' ' + compactCount(day.total)).join('；')
  const unknownText = series.unknown > 0 ? '（' + t('stats.chart.unknown', { n: series.unknown }) + '）' : ''
  const aria = t('stats.chart.aria', { days: dayText, total: compactCount(series.total), unknown: unknownText })
  const bars: React.ReactElement[] = []
  for (const [at, day] of series.days.entries()) {
    let used = 0
    const x = L + groupW * at + (groupW - barW) / 2
    for (const provider of series.providers) {
      const value = day.tokens[provider.agent] ?? 0
      if (value <= 0) continue
      const height = (value / max) * plotH
      const unrecorded = day.unknowns[provider.agent] ?? 0
      const y = T + plotH - used - height
      const segH = Math.max(0.8, height - 0.8)
      bars.push(h('rect', {
        key: 'b-' + day.date + '-' + provider.agent, className: cx('tq-stats-chart-bar'),
        'data-tq-stats-bar': 'true', 'data-day': day.date, 'data-provider': provider.agent,
        'data-tokens': value, 'data-unknown': unrecorded > 0 ? 'true' : undefined,
        x, y, width: barW, height: segH, rx: 1,
        style: { fill: 'var(' + provider.colorVar + ')' },
      }, h('title', null,
        provider.label + ' · ' + day.label + ' · ' + compactCount(value) + ' token'
        + (unrecorded > 0 ? ' · ' + t('stats.chart.unknownShort', { n: unrecorded }) : ''))))
      used += height
    }
  }
  const notes: React.ReactElement[] = []
  if (series.emptyDays > 0) notes.push(h('div', { key: 'zero', className: cx('tq-stats-chart-note') }, t('stats.chart.zero', { n: series.emptyDays })))
  return h('section', { className: cx('tq-d-sec', 'tq-stats-chart-sec'), 'data-tq-stats-chart': 'true' },
    h('div', { className: cx('tq-d-sec-title') }, t('stats.chart.title')),
    h('div', { className: cx('tq-stats-chart-sub') }, t('stats.chart.sub')),
    h('div', { className: cx('tq-stats-chart-wrap') },
      h('svg', {
        className: cx('tq-stats-chart-svg'), viewBox: '0 0 ' + W + ' ' + H,
        role: 'img', 'aria-label': aria,
      },
        ...grid.map((frac) => h('line', {
          key: 'g-' + frac, className: cx('tq-stats-chart-grid'),
          x1: L, x2: W - R, y1: T + plotH - frac * plotH, y2: T + plotH - frac * plotH,
        })),
        ...grid.map((frac) => h('text', {
          key: 'l-' + frac, x: L - 5, y: T + plotH - frac * plotH + 3, textAnchor: 'end',
        }, compactCount(max * frac))),
        ...series.days.map((day, i) => h('text', {
          key: 'x-' + day.date, x: center(i), y: T + plotH + 15, textAnchor: 'middle',
        }, day.label)),
        ...bars),
    ),
    h('div', { className: cx('tq-stats-chart-legend') },
      ...series.providers.map((provider) => h('span', {
        key: 'p-' + provider.agent, className: cx('tq-stats-chart-legend-item'),
      },
        h('span', {
          className: cx('tq-stats-chart-swatch'), 'aria-hidden': 'true',
          style: { background: 'var(' + provider.colorVar + ')' },
        }),
        provider.label, ' ', compactCount(provider.tokens)))),
    ...notes)
}

/**
 * The stats read: fired once when the panel opens, never on the queue's 15s poll. A late
 * answer after the panel closed is dropped (the request counter), the same shape as the
 * detail layer's reads. A host without the taskStats method has no card.
 */
function useTaskStats(props: TaskQueueInjected & { t: Translate }, open: boolean): {
  data: TaskStats | null
  loading: boolean
  error: string | null
  refresh: () => void
} {
  const [state, setState] = useState<{ data: TaskStats | null; loading: boolean; error: string | null }>(
    () => ({ data: null, loading: false, error: null }),
  )
  const request = useRef(0)
  // The effect below runs once per open in React (deps [open]); the test renderer
  // replays effects on every render, so guard the one-shot read explicitly too.
  const fetchedForOpen = useRef(false)
  const read = (): void => {
    if (!open || props.fetchTaskStats === undefined) return
    const id = request.current + 1
    request.current = id
    setState((current) => ({ ...current, loading: true, error: null }))
    props.fetchTaskStats({ days: STATS_DAYS, since: null, patrol: false }).then((data) => {
      if (request.current !== id) return
      setState({ data, loading: false, error: null })
    }, (err: unknown) => {
      if (request.current !== id) return
      const message = (err instanceof Error ? err.message : String(err)) || props.t('balance.unknownError')
      setState((current) => ({ ...current, loading: false, error: message }))
    })
  }
  useEffect(() => {
    if (!open) { fetchedForOpen.current = false; return }
    if (fetchedForOpen.current) return
    fetchedForOpen.current = true
    read()
    return () => { request.current += 1 }
  }, [open])
  return { ...state, refresh: read }
}

type ModelPicker = { models: string[]; efforts: Record<string, string[]>; flag: string; model: string; effort: string; allowed: boolean; reason: string }

/** What `brief <id>` answered, for the detail layer's list of files (null until asked). */
type BriefView = {
  id: string
  path: string
  bytes: number
  truncated: boolean
  /** The prompt.md text the ops entry already returns (≤48 KB); read in place, no preview needed. */
  text: string
  appends: Array<{ file: string; path: string; stamp: string; delivered: boolean; dropped?: boolean; bytes: number; text?: string }>
  /** The host half predates `brief` (a dsh restart is pending): only prompt.md can be listed. */
  needsHost: boolean
}

type TaskTimeline = {
  events: Array<{ stamp: string; kind: string; text: string }>
  omitted_bytes: number
  omitted_events: number
  audit_truncated: boolean
  log_missing: boolean
}

type DetailUi = QueueUi & {
  confirm: string | null
  askConfirm: (key: string | null) => void
  picker: ModelPicker | null
  openPicker: (task: DispatchTask) => void
  setPicker: (picker: ModelPicker | null) => void
  log: string[] | null
  loadLog: (task: DispatchTask) => void
  timeline: TaskTimeline | 'older' | null
  loadTimeline: (task: DispatchTask) => void
  brief: BriefView | null
  readPending: string | null
  openBrief: (task: DispatchTask) => void
  openFullLog: (task: DispatchTask) => void
  openPath: (path: string) => void
  /** The provider windows of an agent (the quota wait names the reset it waits for). */
  windowsOf: (agent: string) => ReadonlyArray<{ resetAtMs?: number | null }> | undefined
  /** What pays for an agent's work (providers.ts join): the plan, its balance row, the free pool, its slots and quota stop. */
  sourceOf: (agent: string) => DetailSource
}

/** The allowance an agent burns, as the detail layer's allowance section reads it. */
type DetailSource = {
  plan: string | null
  row: BalanceRow | undefined
  /** undefined: not a pool; null: a pool whose position is unread. */
  pool: ReturnType<typeof _poolPosition> | undefined
  poolSize: number
  lane: SlotLane | undefined
  quotaUntilMs: number | null
  quotaBy: string
}

/** What opening a file through dsh's own preview answered. */
type OpenFile = (path: string) => { ok: true } | { ok: false; reason: 'no-session' | 'no-service' | 'error'; message?: string }

/**
 * The file-preview address of a path read through one session — dsh-util-workspace-path's
 * `sessionFileAddress` grammar (an absolute path keeps its leading `/`, hence `…/<id>//root/…`).
 * The preview claims only this scope: `file/absolute/…` answered "no registered tab type claims"
 * on the live host (2026-09-27), so the brief opens in the conversation's own sidebar.
 */
export function _sessionFileAddress(sessionId: string, path: string): string {
  const seg = (part: string): string => encodeURIComponent(part).replace(/%3A/gi, ':')
  return 'dsh-resource://file/session/' + seg(sessionId) + '/' + path.split('/').map(seg).join('/')
}

/**
 * The detail layer's order (2026-09-28, kcn: 「问题在详情页……信息没有秩序」). The layer
 * holds what the row cannot: the whole status sentence, the allowance the task
 * burns and when it resets, where the free pool stands, the first queue wait,
 * the budgets and the raw record. It is read top-down in SECTIONS order; a
 * section with nothing to say is not drawn. Each section is a caption and a
 * list of fields on THE row grid (--tq-grid): the label on the `when` track
 * (the name's edge), the value over took…rest, and — for a fact a task can
 * change — its control on the `aside` track, where the list keeps the state
 * chip. So a control sits beside the number it changes, and its confirmation
 * directly under that line.
 *
 *   status     glyph · name · the row's own state chip; the full sentence under it
 *   summary    (ended) the closing report — what happened comes before how
 *   view       read-only: the brief and the log; what they open unfolds right here
 *   run        what the next attempt runs with — model, place in line, deadline,
 *              retries, quota resumes — each with its control when writable
 *   allowance  who runs it and what pays: agent and slot, the plan; while live also the
 *              windows with their resets (the list's own window lines), the free pool's
 *              position and a quota stop — they describe now, not an ended run
 *   time       queued, first queue wait, started, running for / took, wakes, ended
 *   usage      tries (when no budget says it), stalls, cost, tokens
 *   notify     one line per channel, the list's receipt mark and its words (one field, no caption)
 *   end        the task-ending writes (wrap up, cancel), or retry once it ended
 *   raw        FOLDED (the list's one disclosure rule: raw source folds): the
 *              runner's latest log line, the runner api, session and task ids
 *
 * DETAIL_ACTIONS says what each action is — `view` reads (a filled, quiet
 * pill), `write` changes the queue (an outlined control beside its fact),
 * `danger` ends work (red, last) — and where it lives. The spec checks every
 * rendered section, field and pill against these tables.
 */
export type DetailSection = 'status' | 'summary' | 'view' | 'run' | 'allowance' | 'time' | 'usage' | 'notify' | 'end' | 'raw'
export const DETAIL_SECTIONS: Record<'live' | 'ended', readonly DetailSection[]> = {
  live: ['status', 'view', 'run', 'allowance', 'time', 'usage', 'notify', 'end', 'raw'],
  ended: ['status', 'summary', 'view', 'run', 'allowance', 'time', 'usage', 'notify', 'end', 'raw'],
}
export const DETAIL_FIELDS: Partial<Record<DetailSection, readonly string[]>> = {
  run: ['model', 'place', 'deadline', 'retries', 'resumes'],
  allowance: ['agent', 'source', 'windows', 'pool', 'quota'],
  time: ['queued', 'waited', 'started', 'took', 'wakes', 'ended'],
  usage: ['attempts', 'stalls', 'cost', 'tokens'],
  notify: ['notify'],
  raw: ['latest', 'runner', 'session', 'id'],
}
export const DETAIL_FOLDED: readonly DetailSection[] = ['raw']
export type ActionKind = 'view' | 'write' | 'danger'
export const DETAIL_ACTIONS: Record<string, { kind: ActionKind; home: string }> = {
  brief: { kind: 'view', home: 'view' },
  log: { kind: 'view', home: 'view' },
  timeline: { kind: 'view', home: 'view' },
  'summary-log': { kind: 'view', home: 'summary' },
  'raw-log': { kind: 'view', home: 'raw.id' },
  model: { kind: 'write', home: 'run.model' },
  top: { kind: 'write', home: 'run.place' },
  up: { kind: 'write', home: 'run.place' },
  down: { kind: 'write', home: 'run.place' },
  deadline: { kind: 'write', home: 'run.deadline' },
  attempts: { kind: 'write', home: 'run.retries' },
  resumes: { kind: 'write', home: 'run.resumes' },
  wrapup: { kind: 'write', home: 'end' },
  cancel: { kind: 'danger', home: 'end' },
  retry: { kind: 'write', home: 'end' },
}

/** A control in the detail layer: its kind (DETAIL_ACTIONS) is its look; a confirmation arms it. */
function actionPill(key: string, label: string, onClick: () => void,
  opts: { disabled?: boolean; title?: string; said?: string; armed?: boolean; kind?: ActionKind } = {}): React.ReactElement {
  const kind = opts.kind ?? DETAIL_ACTIONS[key]?.kind ?? 'write'
  return h('button', {
    type: 'button', key, className: cx('tq-pill', kind === 'danger' && 'tq-danger'), 'data-tq-action': key, 'data-tq-kind': kind,
    'data-armed': opts.armed ? 'true' : undefined, disabled: opts.disabled === true, title: opts.title,
    'aria-label': opts.said, onClick,
  }, key === 'brief' || key === 'log' || key.endsWith('-log') ? renderViewGlyph(key === 'brief' ? 'brief' : 'log') : null, h('span', null, label))
}

/** The read-only pills' glyphs, in the executor glyphs' outline: a page (the brief), lines (the log). */
function renderViewGlyph(key: string): React.ReactElement {
  const stroke = { stroke: 'currentColor', strokeWidth: 1.2, strokeLinecap: 'round', strokeLinejoin: 'round', fill: 'none' }
  return h('svg', { className: cx('tq-pill-glyph'), width: 12, height: 12, viewBox: '0 0 12 12', 'aria-hidden': 'true' },
    key === 'brief'
      ? h('path', { ...stroke, d: 'M3 1.5H7.2L9.5 3.8V10.5H3ZM7 1.6V4H9.4M4.6 6.2H7.9M4.6 8.2H7.9' })
      : h('path', { ...stroke, d: 'M2 3H10M2 6H10M2 9H7' }))
}

type DetailField = {
  key: string
  label: string
  value: React.ReactNode
  /** A second line under the value (a breakdown, a qualifier), in caption ink. */
  sub?: string | null
  /** The control(s) on the aside track; `wide` puts them on their own line under the value. */
  control?: React.ReactElement[] | null
  wide?: boolean
  /** Under the whole line: a confirmation, the picker, a note. */
  after?: React.ReactNode
  mono?: boolean
  voice?: 'warn' | 'bad'
}

/** One field on the row grid: dt on the name's edge, dd over took…rest, its control in aside. */
function renderField(field: DetailField): React.ReactElement {
  const control = field.control == null || field.control.length === 0 ? null : field.control
  return h('div', {
    className: cx('tq-d-field', control !== null && !field.wide && 'tq-d-has-control'), key: field.key, 'data-tq-field': field.key,
  },
    h('dt', { className: cx('tq-d-k') }, field.label),
    h('dd', { className: cx('tq-d-v', field.mono === true && 'tq-mono'), 'data-voice': field.voice }, field.value),
    field.sub == null || field.sub === '' ? null : h('dd', { className: cx('tq-d-sub') }, field.sub),
    control === null ? null : h('dd', { className: cx('tq-d-control', field.wide && 'tq-d-control-wide') }, ...control),
    field.after == null ? null : h('dd', { className: cx('tq-d-after') }, field.after))
}

/** A section: its caption (a heading for a screen reader's rotor) and its fields as one description list. */
function renderSection(id: DetailSection, title: string | null, body: Array<React.ReactNode>): React.ReactElement | null {
  const present = body.filter((node) => node !== null && node !== undefined && node !== false)
  if (present.length === 0) return null
  return h('div', { className: cx('tq-d-sec'), key: id, 'data-tq-section': id },
    title === null ? null : h('div', { className: cx('tq-d-sec-title'), role: 'heading', 'aria-level': 3 }, title),
    ...present)
}

function renderFields(fields: Array<DetailField | null>): React.ReactElement | null {
  const present = fields.filter((field): field is DetailField => field !== null && field.value != null && field.value !== '')
  return present.length === 0 ? null : h('dl', { className: cx('tq-d-fields'), key: 'dl' }, ...present.map(renderField))
}

/**
 * The detail layer one task row opens, laid over the list inside the same
 * popover: the back bar stays put; everything else scrolls, in DETAIL_SECTIONS
 * order. Dangerous writes confirm in place and say what they cost: cancelling
 * a queued task is free; a running one loses the step in flight (its session
 * can be resumed); a model change applies to the next attempt. The answer to
 * a write lands in the layer's resident foot, in view wherever the reader
 * scrolled to.
 */
function renderTaskDetail(found: { task: DispatchTask; live: boolean }, t: Translate, now: number,
  ui: DetailUi, notice: { ok: boolean; text: string } | null,
  extras: { top?: React.ReactNode; bottom?: React.ReactNode; titleRef?: React.Ref<HTMLElement> } = {}): React.ReactElement {
  const { task, live } = found
  const stamp = (ms: number | null | undefined): string | null => ms == null ? null : resetStampOf(t, { resetAt: '', resetAtMs: ms }, now)
  const status = live ? _taskStatus(task, t, now, ui.windowsOf(task.agent)) : { tone: endedTone(task), text: executionText(task.state, t) + ' · ' + reportText(task.outcome, t, task.state) }
  const chip = live ? _taskState(task, t, now, ui.windowsOf(task.agent)).chip : _endedState(task.state, task.outcome, t)
  const cost = _costOf(task)
  const m = modelLine(task, live)
  const requested = task.modelRequested ?? ''
  const slot = _slotOf(task)
  const busy = ui.busy !== null
  const reading = ui.readPending !== null
  const running = live && (slot !== null || (task.attempts > 0 && task.waiting !== 'lock'))
  const writable = ui.writable && live && !task.cancelling
  const budgets = writable && !task.patrol
  const old = (task.runnerApi ?? 1) < 3
  const confirming = (action: string): boolean => ui.confirm === action + ':' + task.id
  const when = running ? t('queue.a.whenNext') : t('queue.a.whenNow')
  const confirmNote = (action: string, text: string): React.ReactElement | null => !confirming(action) ? null
    : h('div', { className: cx('tq-note', 'tq-warn', 'tq-confirm'), role: 'alert', 'data-tq-confirm': task.id },
      h('span', null, text),
      actionPill('dismiss-confirm', t('queue.a.dismissConfirm'), () => { ui.askConfirm(null) }, { kind: 'view' }))
  // A budget: one tap arms it (the pill says 确认, the line under it what it costs), the second writes.
  const budget = (action: string, label: string, short: string, arg: string): React.ReactElement[] | null => !budgets ? null : [
    actionPill(action, confirming(action) ? t('queue.a.confirm') : short, () => {
      if (confirming(action)) { ui.askConfirm(null); ui.act(action, task, arg) } else ui.askConfirm(action + ':' + task.id)
    }, { disabled: busy || old, armed: confirming(action), said: confirming(action) ? t('queue.a.confirmLabel', { label }) : label }),
  ]
  const picker = ui.picker
  const pickerView = picker === null ? null : h('div', { className: cx('tq-picker'), 'data-tq-picker': task.id },
    picker.allowed
      ? [
        h('label', { className: cx('tq-field'), key: 'm' }, h('span', null, t('queue.d.model')),
          h('select', {
            value: picker.model,
            onChange: (event: { target: { value: string } }) => {
              const model = event.target.value
              const efforts = picker.efforts[model] ?? []
              ui.setPicker({ ...picker, model, effort: efforts.includes(picker.effort) ? picker.effort : '' })
            },
          }, picker.models.map((model) => h('option', { key: model, value: model }, _modelView(model).label + ' (' + model + ')')))),
        h('label', { className: cx('tq-field'), key: 'e' }, h('span', null, picker.flag),
          h('select', {
            value: picker.effort,
            disabled: (picker.efforts[picker.model] ?? []).length === 0,
            onChange: (event: { target: { value: string } }) => { ui.setPicker({ ...picker, effort: event.target.value }) },
          }, [h('option', { key: '', value: '' }, t('queue.d.effortDefault')),
            ...(picker.efforts[picker.model] ?? []).map((effort) => h('option', { key: effort, value: effort }, effort))])),
        h('div', { className: cx('tq-picker-actions'), key: 'save' },
          actionPill('save', t('queue.a.save'), () => {
            ui.setPicker(null)
            ui.act('model', task, picker.model + '|' + (picker.effort === '' ? 'default' : picker.effort))
          }, { disabled: busy }),
          actionPill('close', t('queue.a.close'), () => { ui.setPicker(null) }, { kind: 'view' })),
        h('div', { className: cx('tq-caption'), key: 'hint' }, t('queue.a.modelHint')),
      ]
      : h('div', { className: cx('tq-note') }, picker.reason))

  // ---- run: what the next attempt runs with, each beside its control.
  const place = live && task.waiting === 'lock' && task.position ? t('queue.d.placeValue', { n: task.position, agent: task.agent }) : null
  const placeSub = [task.protected ? t('queue.d.protected') : null, task.priority ? t('queue.d.priorityValue', { n: task.priority }) : null]
    .filter((part): part is string => part !== null).join(' · ')
  const reorder = writable && reorderable(task)
  const run = renderFields([
    m.model === '' ? null : {
      key: 'model', label: t('queue.d.model'),
      value: h('span', null, _modelView(m.model).label + (m.effort ? ' · ' + m.effort : ''),
        m.fallback ? h('span', { className: cx('tq-mark'), 'data-role': 'fallback' }, renderRoleGlyph('fallback'),
          t('queue.d.fallbackFrom', { model: _modelView(requested).label })) : null),
      control: writable && (task.runnerApi ?? 2) >= 2 && !task.patrol
        ? [actionPill('model', ui.readPending === 'choices' ? t('queue.a.reading') : t('queue.a.model'), () => { ui.openPicker(task) }, { disabled: busy || reading })]
        : null,
      after: pickerView,
    },
    place === null ? null : {
      key: 'place', label: t('queue.d.place'), value: place, sub: placeSub, wide: true,
      control: !reorder ? null : [
        actionPill('top', t('queue.a.top'), () => { ui.act('priority', task, 'top') }, { disabled: busy || task.position === 1 }),
        actionPill('up', t('queue.a.up'), () => { ui.act('priority', task, 'up') }, { disabled: busy || task.position === 1 }),
        actionPill('down', t('queue.a.down'), () => { ui.act('priority', task, 'down') }, { disabled: busy }),
      ],
    },
    live && (task.deadlineAtMs || budgets) ? {
      key: 'deadline', label: t('queue.d.deadline'), value: stamp(task.deadlineAtMs) ?? t('queue.d.notRecorded'),
      control: budget('deadline', t('queue.a.deadline'), t('queue.a.deadlineShort'), '+2h'),
      after: confirmNote('deadline', t('queue.a.deadlineConfirm', { when })),
    } : null,
    task.maxAttempts != null || budgets ? {
      key: 'retries', label: t('queue.d.retries'),
      value: task.maxAttempts == null ? t('queue.d.notRecorded') : t('queue.d.usedOf', { used: task.attempts, max: task.maxAttempts }),
      control: budget('attempts', t('queue.a.attempts'), t('queue.a.attemptsShort'), String((task.maxAttempts ?? 3) + 1)),
      after: confirmNote('attempts', t('queue.a.attemptsConfirm', { when })),
    } : null,
    task.quotaResumes != null || budgets ? {
      key: 'resumes', label: t('queue.d.quotaResumes'),
      value: task.quotaResumes == null ? t('queue.d.notRecorded') : t('queue.d.usedOf', { used: task.quotaResumesUsed ?? 0, max: task.quotaResumes }),
      control: budget('resumes', t('queue.a.resumes'), t('queue.a.resumesShort'), String((task.quotaResumes ?? 3) + 1)),
      after: confirmNote('resumes', t('queue.a.resumesConfirm', { when })),
    } : null,
  ])
  const budgetOld = budgets && old ? h('div', { className: cx('tq-note', 'tq-d-note'), key: 'old' }, t('queue.a.budgetOld', { api: task.runnerApi ?? 1 })) : null

  // ---- allowance: who runs it and what pays for it.
  const source = ui.sourceOf(task.agent)
  // The windows, the pool and a quota stop are the allowance NOW: they belong to a live task only.
  const windows = !live || source.row === undefined ? null : renderRowDetail(source.row, t, now)
  const allowance = renderFields([
    { key: 'agent', label: t('queue.d.agent'), value: h('span', { className: cx('tq-inline') }, renderAgentGlyph(task.agent, 12), _agentLabel(task.agent)),
      sub: slot === null ? null : source.lane?.max ? t('queue.d.slotOf', { slot: slot.slot, max: source.lane.max }) : t('queue.d.slotValue', { slot: slot.slot }) },
    source.plan === null ? null : { key: 'source', label: t('queue.d.source'), value: t(source.plan), sub: source.row?.note ?? null,
      voice: source.row?.note ? 'warn' : undefined },
    windows === null ? null : { key: 'windows', label: t('queue.d.windows'), value: h('div', { className: cx('pp-allowance', 'tq-d-windows') }, windows) },
    !live || source.pool === undefined ? null : {
      key: 'pool', label: t('queue.d.pool'),
      value: source.pool === null ? t('panel.poolUnread')
        : t('panel.pool', { current: _modelView(source.pool.current).label, next: source.pool.next === '' ? '—' : _modelView(source.pool.next).label })
          + (source.pool.fromOrder ? t('panel.poolOrder') : ''),
      sub: source.poolSize > 1 ? t('panel.poolSwap', { n: source.poolSize }) : null,
    },
    live && source.quotaUntilMs ? { key: 'quota', label: t('queue.d.quotaOut'), voice: 'warn',
      value: t('queue.quotaHint', { time: stamp(source.quotaUntilMs) ?? '', by: source.quotaBy }) } : null,
  ])

  // ---- time: the task's clock, oldest first.
  const took = live ? (task.startedAtMs === null ? null : durationOf(t, now - task.startedAtMs))
    : task.startedAtMs !== null && task.updatedAtMs !== null ? durationOf(t, task.updatedAtMs - task.startedAtMs) : null
  const time = renderFields([
    { key: 'queued', label: t('queue.d.queued'), value: stamp(task.queuedAtMs) },
    live ? (task.waitMs == null ? null : { key: 'waited', label: t('queue.d.waited'), value: durationOf(t, task.waitMs) })
      : { key: 'waited', label: t('queue.d.waited'), value: task.waitMs == null ? t('queue.waitUnknown') : durationOf(t, task.waitMs) },
    { key: 'started', label: t('queue.d.started'), value: stamp(task.startedAtMs) },
    { key: 'took', label: t(live ? 'queue.d.elapsed' : 'queue.d.took'), value: took },
    live ? { key: 'wakes', label: t('queue.d.resumes'), value: stamp(task.wakeAtMs) } : null,
    live || task.updatedAtMs === null ? null
      : { key: 'ended', label: t('queue.d.endedAt'), value: stamp(task.updatedAtMs) + ' · ' + agoOf(t, now - task.updatedAtMs) },
  ])

  // ---- usage.
  const usage = renderFields([
    task.maxAttempts == null ? { key: 'attempts', label: t('queue.d.attempts'), value: String(task.attempts) } : null,
    task.stalls ? { key: 'stalls', label: t('queue.d.stalls'), value: t('queue.d.stallsValue', { n: task.stalls }), voice: 'warn' } : null,
    cost === null ? null : {
      key: 'cost', label: t('queue.d.cost'),
      value: cost.kind === 'usd' ? '$' + (task.costUsd ?? '') : cost.kind === 'free' ? t('queue.d.costFreeShort') : '—',
      sub: (cost.kind === 'usd' ? t('queue.d.costEstimate') : cost.kind === 'free' ? t('queue.d.costFree') : t('queue.d.costUnpriced'))
        + (live ? ' · ' + t('queue.d.costLive') : ''),
    },
    task.tokensTotal == null ? null : {
      key: 'tokens', label: t('queue.d.tokens'), value: t('queue.d.tokensTotal', { total: _fmtTokens(task.tokensTotal) }),
      sub: t('queue.d.tokensSplit', { in: _fmtTokens(task.tokensIn ?? 0), w: _fmtTokens(task.tokensCacheW ?? 0),
        r: _fmtTokens(task.tokensCacheR ?? 0), out: _fmtTokens(task.tokensOut ?? 0) }),
    },
  ])

  // ---- notify: one line per channel.
  const channels = notifyChannels(task)
  const notify = renderFields([{
    key: 'notify', label: t('queue.d.notify'),
    value: channels.length === 0 ? t('queue.d.notifyNone') : h('span', { className: cx('tq-d-lines') }, channels.map((ch) => {
      const only = { ...task, notify: [ch], notified: (task.notified ?? []).filter((c) => c === ch), notifyFailed: (task.notifyFailed ?? []).filter((c) => c === ch) }
      const said = t('queue.notify.' + _notifyState(task, ch, live), { ch: t('queue.ch.' + ch) })
      return h('span', { className: cx('tq-inline'), key: ch, 'data-tq-channel': ch }, renderNotifyIcons(only, t, live), h('span', { 'aria-hidden': 'true' }, said))
    })),
  }])

  // ---- end: the writes that end or restart the task.
  const end: React.ReactElement[] = []
  if (writable && running && task.session) end.push(actionPill('wrapup', t('queue.a.wrapup'), () => { ui.act('wrapup', task) }, { disabled: busy, title: t('queue.a.wrapupTitle') }))
  if (writable) {
    end.push(actionPill('cancel', confirming('cancel') ? t('queue.a.cancelConfirm') : t('queue.a.cancel'), () => {
      if (confirming('cancel')) { ui.askConfirm(null); ui.act('cancel', task) } else ui.askConfirm('cancel:' + task.id)
    }, { disabled: busy, armed: confirming('cancel') }))
  }
  if (ui.writable && !live && task.session && !(task.state === 'ok' && (task.outcome === 'DONE' || task.outcome === ''))) {
    end.push(actionPill('retry', t('queue.a.retry'), () => { ui.act('retry', task) }, { disabled: busy }))
  }
  const cancelText = running ? t('queue.a.cancelRunning', { session: task.session || '—' })
    : task.waiting === 'quota' || task.waiting === 'retry' ? t('queue.a.cancelSleeping') : t('queue.a.cancelQueued')

  // ---- view: the brief and the log, read-only; what they open unfolds under them.
  const view: React.ReactElement[] = [
    actionPill('brief', ui.readPending === 'brief' ? t('queue.a.reading') : t('queue.a.brief'), () => { ui.openBrief(task) }, { disabled: reading, title: t('queue.a.briefTitle') }),
  ]
  if (ui.writable) {
    view.push(actionPill('log', ui.readPending === 'log' ? t('queue.a.reading') : t('queue.a.log'), () => { ui.loadLog(task) }, { disabled: reading }))
    view.push(actionPill('timeline', ui.readPending === 'timeline' ? t('queue.a.reading') : t('queue.timeline.heading'), () => { ui.loadTimeline(task) }, { disabled: reading }))
  }
  const brief = ui.brief !== null && ui.brief.id === task.id ? ui.brief : null
  const kb = (bytes: number): string => (bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)

  // ---- raw: folded, the source lines the fields above were read from.
  const raw = renderFields([
    live && task.lastEvent ? { key: 'latest', label: t('queue.d.latest'), value: task.lastEvent + (task.lastEventAtMs == null ? '' : ' · ' + stamp(task.lastEventAtMs)), mono: true } : null,
    { key: 'runner', label: t('queue.d.runner'), value: live && (task.runnerApi ?? 2) < 2 ? t('queue.noRunnerApi') : task.runnerApi == null ? null : 'api ' + task.runnerApi,
      voice: live && (task.runnerApi ?? 2) < 2 ? 'warn' : undefined },
    { key: 'session', label: t('queue.d.session'), value: task.session || null, mono: true },
    { key: 'id', label: t('queue.d.id'), value: task.id, mono: true,
      control: [actionPill('raw-log', t('queue.a.fullLog'), () => { ui.openFullLog(task) }, { title: t('queue.a.fullLogTitle') })] },
  ])

  // Read-only view blocks. The brief text comes back with the `brief` action, so
  // a global workbench (no conversation to preview into) still reads it here.
  const kbOf = (bytes: number): string => (bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)
  const briefBlock = brief === null ? null : h('div', {
    className: cx('tq-brief'), key: 'brief', 'data-tq-brief': task.id, role: 'group', 'aria-label': t('queue.brief.heading'),
  },
    h('div', { className: cx('tq-caption') }, t('queue.brief.heading') + ' · ' + t('queue.brief.readOnly')),
    h('button', { type: 'button', className: cx('tq-file'), 'data-tq-file': brief.path, onClick: () => { ui.openPath(brief.path) } },
      h('span', { className: cx('tq-file-name') }, brief.needsHost ? 'prompt.md' : t('queue.brief.prompt', { kb: kbOf(brief.bytes) })),
      brief.truncated ? h('span', { className: cx('tq-tag') }, t('queue.brief.big', { kb: kbOf(brief.bytes) })) : null),
    brief.needsHost ? h('div', { className: cx('tq-note') }, t('queue.brief.needsHost'))
      : brief.appends.length === 0 ? h('div', { className: cx('tq-empty') }, t('queue.brief.none'))
        : brief.appends.map((append, index) => h('button', {
          type: 'button', key: append.file, className: cx('tq-file'), 'data-tq-file': append.path,
          onClick: () => { ui.openPath(append.path) },
        },
          h('span', { className: cx('tq-file-label') },
            h('span', { className: cx('tq-file-name') }, t('queue.brief.append', { number: index + 1, stamp: append.stamp || append.file })),
            append.text?.trim() ? h('span', { className: cx('tq-file-excerpt') }, append.text.trim().split('\n').find((line) => line.trim() !== '')?.replace(/^#+\s*/, '').slice(0, 160)) : null),
          h('span', { className: cx('tq-tag'), 'data-tq-delivered': append.delivered ? 'true' : 'false' },
            t(append.delivered ? 'queue.brief.delivered' : (append.dropped || !live) ? 'queue.brief.undelivered' : 'queue.brief.pending')))))
  const briefText = brief === null || brief.text === '' ? null : h('details', {
    className: cx('tq-fold'), key: 'brief-text', 'data-tq-brief-text': task.id,
  },
    h('summary', { className: cx('tq-fold-summary') },
      foldChevron(),
      h('span', { className: cx('tq-fold-label') }, t('queue.brief.prompt', { kb: kbOf(brief.bytes) }))),
    h('pre', {
      className: cx('tq-log'), tabIndex: 0, role: 'region',
      'aria-label': t('queue.brief.prompt', { kb: kbOf(brief.bytes) }),
    }, brief.text))
  const timelineBlock = ui.timeline === null ? null : h('div', {
    className: cx('tq-timeline'), key: 'timeline', 'data-tq-timeline': task.id,
  },
    h('div', { className: cx('tq-caption') }, t('queue.timeline.heading')),
    ui.timeline === 'older' ? h('div', { className: cx('tq-note') }, t('queue.timeline.older')) : [
      h('div', { className: cx('tq-note'), key: 'source' }, t('queue.timeline.source')),
      ui.timeline.log_missing ? h('div', { className: cx('tq-note'), key: 'missing' }, t('queue.timeline.missing')) : null,
      ui.timeline.omitted_bytes > 0 || ui.timeline.omitted_events > 0 || ui.timeline.audit_truncated
        ? h('div', { className: cx('tq-note'), key: 'cut' }, t('queue.timeline.cut', { bytes: ui.timeline.omitted_bytes, count: ui.timeline.omitted_events })) : null,
      ui.timeline.events.length === 0 ? h('div', { className: cx('tq-empty'), key: 'empty' }, t('queue.timeline.empty'))
        : h('ol', { key: 'events' }, ...ui.timeline.events.map((event, index) => h('li', { key: index },
          h('time', null, event.stamp),
          h('strong', null, t('queue.timeline.' + event.kind)),
          event.text ? h('div', null, event.text) : null))),
    ])
  const logBlock = ui.log === null ? null : h('pre', {
    className: cx('tq-log'), key: 'log', 'data-tq-log': task.id, tabIndex: 0, role: 'region',
    'aria-label': t('queue.a.log'),
  }, ui.log.join('\n'))

  const sections: Record<DetailSection, React.ReactElement | null> = {
    status: h('div', { className: cx('tq-d-sec', 'tq-d-hero'), key: 'status', 'data-tq-section': 'status' },
      h('span', { className: cx('tq-lead'), 'aria-hidden': 'true' }, renderAgentGlyph(task.agent)),
      h('span', { className: cx('tq-d-name'), role: 'heading', 'aria-level': 2, tabIndex: -1, ref: extras.titleRef }, task.name),
      renderChip(chip, { slot: 'status' }),
      status.text === chip.text ? null : h('div', {
        className: cx('tq-d-status'), 'data-balance-state': status.tone, title: live ? undefined : t('queue.statusLegend'),
      }, status.text)),
    summary: live || !task.summary ? null : renderSection('summary', t('queue.d.summary'), [
      h('div', { className: cx('tq-d-summary'), key: 'summary' }, task.summary),
      h('div', { className: cx('tq-actions'), key: 'summary-log' },
        actionPill('summary-log', t('queue.a.fullLog'), () => { ui.openFullLog(task) }, { title: t('queue.a.fullLogTitle') })),
    ]),
    view: renderSection('view', null, [
      h('div', { className: cx('tq-actions'), key: 'pills', role: 'group', 'aria-label': t('queue.a.viewGroup') }, ...view),
      briefBlock,
      briefText,
      timelineBlock,
      logBlock,
    ]),
    run: renderSection('run', t('queue.d.sec.run'), [run, budgetOld]),
    allowance: renderSection('allowance', t('queue.d.sec.allowance'), [allowance]),
    time: renderSection('time', t('queue.d.sec.time'), [time]),
    usage: renderSection('usage', t('queue.d.sec.usage'), [usage]),
    // One field: its label is the section's name, so the section has no caption of its own.
    notify: renderSection('notify', null, [notify]),
    end: renderSection('end', t(live ? 'queue.d.sec.end' : 'queue.d.sec.again'), end.length === 0 ? [] : [
      h('div', { className: cx('tq-actions'), key: 'pills', role: 'group', 'aria-label': t(live ? 'queue.d.sec.end' : 'queue.d.sec.again') }, ...end),
      confirming('cancel') ? h('div', { className: cx('tq-note', 'tq-warn', 'tq-confirm'), key: 'confirm', role: 'alert', 'data-tq-confirm': task.id },
        h('span', null, cancelText),
        actionPill('dismiss-confirm', t('queue.a.dismissConfirm'), () => { ui.askConfirm(null) }, { kind: 'view' })) : null,
    ]),
    raw: raw === null ? null : h('div', { className: cx('tq-d-sec'), key: 'raw', 'data-tq-section': 'raw' },
      renderFold('raw', t('queue.d.sec.raw'), [raw])),
  }
  return h('div', { className: cx('tq-detail'), 'data-tq-detail': task.id, role: 'group', 'aria-label': task.name },
    h('div', { className: cx('tq-scroll', 'tq-d-scroll'), role: 'region', 'aria-label': t('queue.d.region', { name: task.name }) },
      extras.top ?? null,
      ...DETAIL_SECTIONS[live ? 'live' : 'ended'].map((id) => sections[id]),
      extras.bottom ?? null),
    // Resident: the answer to a write, wherever the reader had scrolled to. Always mounted, so a
    // screen reader hears it when it fills.
    h('div', { className: cx('tq-d-notice', notice !== null && (notice.ok ? 'tq-ok' : 'tq-bad')), role: 'status', 'data-tq-notice': notice === null ? undefined : 'true' },
      notice === null ? null : notice.text))
}

/** What one action's answer says, in the reader's words (the ops entry's own message otherwise). */
export function _describeAction(result: QueueActionResult, t: Translate): string {
  let detail: Record<string, unknown> = {}
  try { detail = JSON.parse(result.detail || '{}') as Record<string, unknown> } catch { detail = {} }
  if (!result.ok) return t('queue.r.failed', { message: result.message || String(result.code) })
  switch (result.action) {
    case 'cancel':
      if (detail.was === 'queued') return t('queue.r.cancelledQueued')
      return detail.session ? t('queue.r.cancelledRunning', { resume: String(detail.resume ?? '') }) : t('queue.r.cancelledNoSession')
    case 'priority': {
      const queue = Array.isArray(detail.queue) ? detail.queue as string[] : []
      return detail.changed === false ? String(detail.message ?? '') : t('queue.r.priority', { n: String(detail.position ?? '—'), total: queue.length })
    }
    case 'model': return t('queue.r.model', { model: String(detail.model_next ?? ''), effort: String(detail.effort_next || '—') })
    case 'retry': return t('queue.r.retry', { id: String(detail.new_id ?? '') })
    case 'wrapup': return t('queue.r.wrapup')
    default: return result.message
  }
}

/** How long an in-place confirmation waits for its second tap. */


// ---------------------------------------------------------------------------
// The workbench page and its two sidebar entries (2026-11-07).
//
// One main panel, two views: the queue (default) and one task's focus view.
// Below 768px only one view is mounted at a time; at 768px and up the queue is
// a fixed 340px column and the detail sits beside it. The signal row is the
// only footer presence, and it exists only while a task needs a person; the
// panellist icon is the permanent entry.
// ---------------------------------------------------------------------------

/** dsh's own breakpoint for the drawer main column (ui-layout: width<=767px). */
const WORKBENCH_WIDE = '(min-width: 768px)'
/** Two-tap destructive confirmation, in place, then it reverts. */
const WORKBENCH_CONFIRM_MS = 3000
/** The detail layer's write confirmations (cancel, budgets) revert after 5s. */
const DETAIL_CONFIRM_MS = 5000
/** How long "刚刚更新" stays after a silent refresh. */
const WORKBENCH_UPDATED_MS = 1600
/** Per-device group fold memory (the design review fixed this key). */
const WORKBENCH_GROUPS_KEY = 'workbench.groups.v2'
type WorkbenchGroup = 'stuck' | 'pending' | 'live'
type WorkbenchTab = 'tasks' | 'providers' | 'overview'
type WorkbenchGroups = Record<WorkbenchGroup, boolean>
/** The alarm group is open until the reader folds it; the other two start closed. */
const WORKBENCH_GROUPS_DEFAULT: WorkbenchGroups = { stuck: true, pending: true, live: false }

function readWorkbenchGroups(): WorkbenchGroups {
  const fallback = { ...WORKBENCH_GROUPS_DEFAULT }
  try {
    if (typeof window === 'undefined' || window.localStorage === undefined) return fallback
    const raw = window.localStorage.getItem(WORKBENCH_GROUPS_KEY)
    if (raw === null || raw === '') return fallback
    const parsed: unknown = JSON.parse(raw)
    if (parsed === null || typeof parsed !== 'object') return fallback
    const value = parsed as Partial<Record<WorkbenchGroup, unknown>>
    return {
      stuck: typeof value.stuck === 'boolean' ? value.stuck : WORKBENCH_GROUPS_DEFAULT.stuck,
      pending: typeof value.pending === 'boolean' ? value.pending : WORKBENCH_GROUPS_DEFAULT.pending,
      live: typeof value.live === 'boolean' ? value.live : WORKBENCH_GROUPS_DEFAULT.live,
    }
  } catch {
    return fallback
  }
}

function saveWorkbenchGroups(groups: WorkbenchGroups): void {
  try {
    if (typeof window === 'undefined' || window.localStorage === undefined) return
    window.localStorage.setItem(WORKBENCH_GROUPS_KEY, JSON.stringify(groups))
  } catch {
    // A blocked storage (private mode) keeps the in-memory fold for this visit.
  }
}

function useMedia(query: string): boolean {
  const read = (): boolean => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(query).matches
    : false
  const [match, setMatch] = useState<boolean>(read)
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined
    const mq = window.matchMedia(query)
    const onChange = (): void => { setMatch(mq.matches) }
    setMatch(mq.matches)
    if (typeof mq.addEventListener === 'function') mq.addEventListener('change', onChange)
    else if (typeof mq.addListener === 'function') mq.addListener(onChange)
    return () => {
      if (typeof mq.removeEventListener === 'function') mq.removeEventListener('change', onChange)
      else if (typeof mq.removeListener === 'function') mq.removeListener(onChange)
    }
  }, [query])
  return match
}

/** Local HH:MM for the header's patrol stamp and the recorded-at line. */
function hhmmOf(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '—'
  const d = new Date(ms)
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
}

/** The patrol's latest round end, else its progress stamp; null when neither is known. */
function lastPatrolAt(result: TaskQueueResult | null): number | null {
  const stamp = result?.patrol?.rounds?.[0]?.endedAt ?? ''
  if (stamp !== '') {
    const parsed = new Date(stamp.replace(' ', 'T')).getTime()
    if (Number.isFinite(parsed)) return parsed
  }
  const fallback = result?.patrol?.progress?.issuesAt ?? ''
  const parsed = fallback === '' ? NaN : new Date(fallback).getTime()
  return Number.isFinite(parsed) ? parsed : null
}

function renderWorkbenchGlyph(size = 16): React.ReactElement {
  return h('svg', {
    width: size, height: size, viewBox: '0 0 16 16', fill: 'none', 'aria-hidden': 'true',
    stroke: 'currentColor', strokeWidth: 1.35, strokeLinecap: 'round', strokeLinejoin: 'round',
  },
    h('path', { d: 'M2.2 9.2h3l1 1.6h3.6l1-1.6h3' }),
    h('path', { d: 'M3.1 3.4h9.8l1.2 5.8v2.9a1 1 0 0 1-1 1H2.9a1 1 0 0 1-1-1V9.2z' }))
}

function renderWorkbenchChevron(size = 12, className?: string): React.ReactElement {
  return h('svg', {
    className: className === undefined ? undefined : cx(className),
    width: size, height: size, viewBox: '0 0 12 12', 'aria-hidden': 'true',
  },
    h('path', {
      d: 'M4.5 2.5L8 6l-3.5 3.5', stroke: 'currentColor', strokeWidth: 1.4,
      fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round',
    }))
}

/** The stuck group's warning glyph: the red text alone should not carry the alarm. */
function renderWorkbenchAlert(size = 12): React.ReactElement {
  return h('svg', { width: size, height: size, viewBox: '0 0 12 12', 'aria-hidden': 'true', className: cx('wb-group-alert') },
    h('path', {
      d: 'M6 1.5 11 10.5H1z', fill: 'none', stroke: 'currentColor', strokeWidth: 1.2, strokeLinejoin: 'round',
    }),
    h('path', {
      d: 'M6 4.4v2.8M6 8.9v.1', stroke: 'currentColor', strokeWidth: 1.3, strokeLinecap: 'round',
    }))
}

/** The one group header the queue's three sections share: label, count, chevron. */
function WorkbenchGroupHeader(props: {
  id: string
  label: string
  open: boolean
  tone: 'danger' | 'neutral'
  bodyId: string
  summary?: string
  lead?: React.ReactNode
  buttonRef: (element: HTMLButtonElement | null) => void
  onToggle: () => void
}): React.ReactElement {
  return h('button', {
    type: 'button', className: cx('wb-group'), 'data-wb-group-button': props.id, 'data-wb-tone': props.tone,
    'aria-expanded': props.open,
    // The body is always mounted so grid-template-rows can animate; the
    // closed state removes it from the accessibility tree and interaction.
    'aria-controls': props.bodyId,
    ref: props.buttonRef,
    onClick: props.onToggle,
  },
    props.tone === 'danger' ? renderWorkbenchAlert() : null,
    props.lead ?? null,
    h('span', { className: cx('wb-group-title') }, props.label),
    props.summary === undefined || props.summary === '' ? null : h('span', { className: cx('wb-group-summary') }, props.summary),
    h('span', { className: cx('wb-group-chev'), 'aria-hidden': 'true' }, renderWorkbenchChevron()))
}

/** The panellist icon: a permanent entry; the badge exists only with pending tasks. */
export type WorkbenchIconInjected = TaskQueueInjected & BalancesInjected & {
  rememberTrigger: (element: HTMLElement | null) => void
}

export type WorkbenchIconProps = WorkbenchIconInjected & {
  size: number
  active: boolean
  t: Translate
}

export function WorkbenchIcon(props: WorkbenchIconProps): React.ReactElement {
  const queue = useTaskQueue(props)
  const balances = useProviderReadings(props, 'workbench-icon', false)
  const tasks = queue.data.result?.pending ?? []
  const view = tasks.length === 0 ? null : signalView(tasks, props.t, Date.now())
  const alerts = providerAlerts(balances.rows)
  const alertNames = alerts.map((row) => row.label).join(', ')
  const alertCount = alerts.length === 0 ? '' : alerts.length === 1
    ? props.t('workbench.provider.alertCountOne')
    : props.t('workbench.provider.alertCount', { n: alerts.length })
  const alertLabel = alertNames === '' ? null : props.t('workbench.provider.alertAria', { names: alertNames })
  const iconRef = useRef<HTMLSpanElement | null>(null)
  // The host owns the row's button and its visible label. An alert is written
  // into that label ("Workbench · 1 alert"), never left as a colour-only dot:
  // no legend, no hover and no width assumption can make a bare dot explain
  // itself, and the rail keeps the same words in its title/aria-label.
  const label = view?.aria ?? props.t('signal.icon')
  const spoken = alertLabel === null ? label : label + ' · ' + alertLabel
  useEffect(() => {
    const button = iconRef.current?.closest('button')
    if (typeof HTMLElement === 'undefined' || !(button instanceof HTMLElement)) return undefined
    const previous = button.getAttribute('aria-label')
    const title = button.querySelector<HTMLElement>('[class*="panelTitle"]')
    const previousText = title?.textContent ?? null
    const updateRail = (): void => {
      const width = button.getBoundingClientRect().width
      if (width > 0 && width < 60) button.setAttribute('data-wb-rail', 'true')
      else button.removeAttribute('data-wb-rail')
    }
    updateRail()
    const railFrame = typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function'
      ? window.requestAnimationFrame(updateRail) : null
    if (typeof window !== 'undefined') window.addEventListener('resize', updateRail)
    const railObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(updateRail)
    railObserver?.observe(button)
    button.setAttribute('aria-label', spoken)
    button.setAttribute('title', spoken)
    if (title !== null) {
      title.textContent = alertCount === ''
        ? previousText ?? title.textContent
        : props.t('workbench.labelAlert', { alerts: alertCount })
    }
    return () => {
      if (previous === null) button.removeAttribute('aria-label')
      else button.setAttribute('aria-label', previous)
      button.removeAttribute('title')
      button.removeAttribute('data-wb-rail')
      if (title !== null && previousText !== null) title.textContent = previousText
      if (typeof window !== 'undefined') window.removeEventListener('resize', updateRail)
      railObserver?.disconnect()
      if (railFrame !== null && typeof window !== 'undefined') window.cancelAnimationFrame(railFrame)
    }
  }, [spoken, alertCount, alertNames])
  return h('span', {
    className: cx('wb-icon', props.active && 'wb-icon-on'),
    'data-wb-icon': 'true',
    ...(alertNames === '' ? {} : { 'data-wb-provider-alert': alertNames }),
    ref: iconRef,
    onClick: (event: { currentTarget: HTMLElement }) => {
      const button = event.currentTarget.closest('button')
      props.rememberTrigger(button instanceof HTMLElement ? button : null)
    },
  },
    renderWorkbenchGlyph(props.size),
    view === null
      ? null
      : h('span', {
        className: cx('wb-badge'),
        'data-wb-badge': 'true',
        'data-wb-tone': view.tone,
        'aria-hidden': 'true',
        'aria-live': 'polite',
      }, view.badge),
    alertNames === '' ? null : h('span', {
      className: cx('wb-rail-alert'), 'data-wb-rail-alert': 'true', 'aria-hidden': 'true', title: alertLabel ?? '',
    }, '!'))
}

export type WorkbenchInjected = TaskQueueInjected & BalancesInjected & {
  /** Return to the conversation and put focus back on the control that opened the page. */
  closeWorkbench: () => void
  /** One preset through the host's dispatcher entry; absent on an older host half. */
  runWorkbenchAction?: (action: string, id: string) => Promise<QueueActionResult>
  /** Open a brief/log in dsh's own preview; absent on a host without the sidebar service. */
  openFile?: OpenFile
}

export type WorkbenchProps = WorkbenchInjected & { t: Translate }

/** One queue row: title, NEEDS first sentence, wait. No icon, no dot, no pill. */
function WorkbenchRow(props: {
  task: DispatchTask
  now: number
  selected: boolean
  t: Translate
  buttonRef: (element: HTMLButtonElement | null) => void
  onOpen: () => void
  onMove: (delta: number) => void
}): React.ReactElement {
  const { task, t } = props
  const sub = firstSentence(task.needs ?? '') || t('workbench.needs.empty')
  return h('button', {
    type: 'button',
    ref: props.buttonRef,
    className: cx('wb-row', props.selected && 'wb-row-on'),
    'data-wb-task': task.id,
    'aria-label': t('workbench.rowAria', { title: taskTitle(task), time: waitSpoken(waitedOf(task, props.now), t) }),
    onClick: props.onOpen,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); event.stopPropagation(); props.onOpen(); return
      }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault(); event.stopPropagation(); props.onMove(event.key === 'ArrowDown' ? 1 : -1)
      }
    },
  },
    h('span', { className: cx('wb-row-main') },
      h('span', { className: cx('wb-row-title') }, taskTitle(task)),
      sub === '' ? null : h('span', { className: cx('wb-row-sub') }, sub)),
    h('span', { className: cx('wb-row-age') }, waitShort(waitedOf(task, props.now))))
}

/**
 * One provider in the Providers segment: a two-line, always-visible data row
 * (72px, the task row's rhythm). Line 1 is the state dot, name and used %, with
 * the week share muted on the right; line 2 is the window end and, for money
 * providers, the balance/credit split. A 3px bar at the bottom uses the same
 * state predicate as the drawer dot.
 */
function WorkbenchProviderRow(props: {
  row: ProviderRowView
  t: Translate
  now: number
  detailRow: BalanceRow | undefined
}): React.ReactElement {
  const { row, t, detailRow } = props
  const snapshot = detailRow?.result.snapshot ?? null
  const money = snapshot?.unit === 'money'
  const free = row.state === 'free'
  const unknown = row.state === 'unknown'
  const state = row.state
  const stateLabel = state === 'stale' ? t('balance.staleShort') : t('workbench.provider.state.' + state)
  const left = free ? t('workbench.provider.noWindow')
    : unknown ? t('workbench.provider.state.unknown')
      : money ? '' : row.reset === null ? '—'
        : t('workbench.provider.to', { time: [row.reset.date, row.reset.detail].filter((part) => part !== '').join(' ') })
  const credit = money && Number(snapshot?.grantedBalance) > 0
    ? t('workbench.provider.credit', { amount: (snapshot?.currency === 'CNY' ? '¥' : '$') + snapshot?.grantedBalance })
    : null
  const right = money && !free && !unknown
    ? [t('workbench.provider.balance', { amount: row.primary }), credit].filter((part): part is string => part !== null).join(' · ')
    : null
  return h('div', {
    className: cx('wb-prov', 'wb-prov-' + state), role: 'listitem',
    'data-wb-provider': row.key, 'data-wb-provider-signal': row.signal, 'data-wb-provider-state': state,
    'data-wb-tone': row.tone, 'aria-label': row.aria, title: row.title === '' ? undefined : row.title,
  },
    h('div', { className: cx('wb-prov-line') },
      h('span', {
        className: cx('wb-prov-glyph'), 'data-pp-provider': row.provider ?? row.agent ?? '',
        'aria-hidden': 'true',
      }, renderSourceGlyph(row.source)),
      h('span', { className: cx('wb-prov-name') }, row.label),
      h('span', { className: cx('wb-prov-metrics') },
        row.primary === '' ? null : h('span', { className: cx('wb-prov-primary'), 'data-wb-tone': row.primaryTone }, row.primary),
        row.secondary === null ? null : h('span', { className: cx('wb-prov-secondary'), 'data-wb-tone': row.secondaryTone }, row.secondary))),
    h('div', { className: cx('wb-prov-meta') },
      h('span', { className: cx('wb-prov-left') },
        state === 'stale' && row.chip !== null ? h('span', { className: cx('wb-prov-stale') }, row.chip.text) : null,
        left),
      right === null ? null : h('span', { className: cx('wb-prov-right') }, right)),
    row.bar === null ? null : h('div', { className: cx('wb-prov-track'), 'data-wb-provider-bar': row.bar.state, 'aria-hidden': 'true' },
      h('span', {
        className: cx('wb-prov-fill'), 'data-wb-provider-fill': String(row.bar.pct), 'data-role': row.bar.state,
        style: { width: row.bar.pct + '%' },
      })))
}

/** A native details fold; the summary carries the whole row, the body the existing tables. */
function WorkbenchFold(props: { id: string; label: string; open?: boolean; children: React.ReactNode }): React.ReactElement {
  return h('details', { className: cx('wb-fold'), 'data-wb-fold': props.id, open: props.open },
    h('summary', { className: cx('wb-fold-summary') },
      h('span', null, props.label),
      h('span', { className: cx('wb-fold-chev'), 'aria-hidden': 'true' }, renderWorkbenchChevron())),
    h('div', { className: cx('wb-fold-body') }, props.children))
}

/** The focus view's body, shared by the phone page and the desktop right column. */
function WorkbenchDetail(props: {
  task: DispatchTask
  now: number
  t: Translate
  desktop: boolean
  live: boolean
  titleRef: React.Ref<HTMLElement>
  ui: DetailUi
  notice: { ok: boolean; text: string } | null
  top?: React.ReactNode
  bottom?: React.ReactNode
}): React.ReactElement {
  return h('div', {
    className: cx('wb-detail', props.desktop && 'wb-detail-desktop'),
    'data-wb-detail': props.task.id,
  },
    h('div', { className: cx('wb-detail-tq', 'pbc', 'tqf') },
      renderTaskDetail(
        { task: props.task, live: props.live }, props.t, props.now, props.ui, props.notice,
        { top: props.top, bottom: props.bottom, titleRef: props.titleRef })))
}

export function WorkbenchPage(props: WorkbenchProps): React.ReactElement {
  const { t } = props
  const queue = useTaskQueue(props)
  const [tab, setTab] = useState<WorkbenchTab>('tasks')
  const [view, setView] = useState<'queue' | 'focus'>('queue')
  const [selected, setSelected] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<DispatchTask | null>(null)
  const [groups, setGroups] = useState<WorkbenchGroups>(readWorkbenchGroups)
  const [showAll, setShowAll] = useState<Partial<Record<WorkbenchGroup, boolean>>>({})
  // The old panel grouped tasks under their provider/agent source. The new
  // work queue groups by what the reader must do (status); source stays one
  // toggle away instead of being a second permanent list.
  const [groupBy, setGroupBy] = useState<'status' | 'source'>('status')
  const [sourceOpen, setSourceOpen] = useState<Record<string, boolean>>({})
  const [overviewPatrolOpen, setOverviewPatrolOpen] = useState(false)
  const [overviewStatsOpen, setOverviewStatsOpen] = useState(false)
  const [overviewHistoryOpen, setOverviewHistoryOpen] = useState(false)
  const [updated, setUpdated] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null)
  const [confirmStop, setConfirmStop] = useState(false)
  const [submittedAt, setSubmittedAt] = useState<string | null>(null)
  // The old task-detail layer's own state (writes, reads, pickers). It is kept
  // per selected task; a late read may never paint another task's panel.
  const [confirm, setConfirm] = useState<string | null>(null)
  const [picker, setPicker] = useState<ModelPicker | null>(null)
  const [log, setLog] = useState<string[] | null>(null)
  const [timeline, setTimeline] = useState<TaskTimeline | 'older' | null>(null)
  const [brief, setBrief] = useState<BriefView | null>(null)
  const [readPending, setReadPending] = useState<string | null>(null)
  const desktop = useMedia(WORKBENCH_WIDE)
  const narrow = useMedia('(max-width: 359px)')
  const balances = useProviderReadings(props, 'workbench-page', tab === 'providers')
  const stats = useTaskStats(props, tab === 'overview')
  const titleRef = useRef<HTMLElement | null>(null)
  const rowRefs = useRef(new Map<string, HTMLButtonElement>())
  const groupRefs = useRef(new Map<WorkbenchGroup, HTMLButtonElement>())
  const openedInitial = useRef(false)
  const hasStoredFold = useRef<boolean>((() => {
    try {
      return typeof window !== 'undefined' && window.localStorage !== undefined
        && window.localStorage.getItem(WORKBENCH_GROUPS_KEY) !== null
    } catch {
      return false
    }
  })())
  const narrowSettled = useRef(false)
  const tabRefs = useRef(new Map<WorkbenchTab, HTMLButtonElement>())
  const updatedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const detailRequest = useRef(0)
  const activeDetail = useRef<string | null>(null)
  const historyReturn = useRef<string | null>(null)
  const groupId = useId()
  const now = Date.now()
  const result = queue.data.result
  const pending = result?.pending ?? []
  const counts = workbenchCounts(pending, now)
  const split = splitPending(pending)
  const live = (result?.active ?? []).filter((task) => !task.patrol)
  const sources = _panelSources(balances.data.result?.providers ?? [], result)
  const rowMap = new Map(balances.rows.map((row) => [row.provider, row] as const))
  const providers = providerRowsView(sources, rowMap, result, t, now)
  const alerts = providerAlerts(balances.rows)
  const alertNames = alerts.map((row) => row.label).join(', ')
  const statsData = stats.data === null ? null : statsView(stats.data, t)
  const patrol = result === null ? null : patrolSection(result, t, now)
  const panelId = groupId + '-panel'
  const tabId = (id: WorkbenchTab): string => groupId + '-tab-' + id
  const capRows = narrow ? 4 : 6
  const maxOpen = narrow ? 1 : 2
  const rowsOf = (id: WorkbenchGroup): DispatchTask[] => id === 'stuck' ? split.stuck : id === 'pending' ? split.review : live
  const visibleRows = (id: WorkbenchGroup): DispatchTask[] => {
    const rows = rowsOf(id)
    return showAll[id] === true ? rows : rows.slice(0, capRows)
  }
  // Only the rows actually mounted take part in the desktop arrow order; the
  // "more" row is a pointer-only escape hatch for the cap.
  const rendered = [
    ...(groups.stuck ? visibleRows('stuck') : []),
    ...(groups.pending ? visibleRows('pending') : []),
    ...(groups.live ? visibleRows('live') : []),
  ]
  const shown = selected === null ? null : pending.find((task) => task.id === selected) ?? snapshot
  const patrolAt = lastPatrolAt(result)
  const stamp = hhmmOf(patrolAt)
  const rawProgress = result?.patrol?.progress ?? null
  const overviewOpenValues = (rawProgress?.areas ?? []).map((area) => {
    const value = (area as { open?: unknown }).open
    return value === null || value === undefined || value === '' || !Number.isFinite(Number(value))
      ? null : Number(value)
  })
  const overviewOpen = overviewOpenValues.length > 0 && overviewOpenValues.every((value) => value !== null)
    ? overviewOpenValues.reduce<number>((sum, value) => sum + (value ?? 0), 0) : null
  const firstRendered = rendered[0]?.id ?? null

  // Opening the page must show task rows: if the stored fold choice leaves
  // every non-empty group closed (e.g. only a running task), open the first
  // group that has something to show. This runs once per mount.
  useEffect(() => {
    if (openedInitial.current) return
    if (hasStoredFold.current) { openedInitial.current = true; return }
    if (pending.length === 0 && live.length === 0) return
    const visible = (groups.stuck && split.stuck.length > 0)
      || (groups.pending && split.review.length > 0)
      || (groups.live && live.length > 0)
    if (visible) { openedInitial.current = true; return }
    openedInitial.current = true
    const first: WorkbenchGroup = split.stuck.length > 0 ? 'stuck'
      : split.review.length > 0 ? 'pending' : 'live'
    const next = { stuck: first === 'stuck', pending: first === 'pending', live: first === 'live' }
    setGroups(next)
    saveWorkbenchGroups(next)
  }, [pending.length, live.length, groups.stuck, groups.pending, groups.live])

  // Under 360px only one group may stay open. The v2 default opens both alarm
  // and review; keep the first one with rows and close the other.
  useEffect(() => {
    if (!narrow || narrowSettled.current) return
    if (pending.length === 0 && live.length === 0) return
    narrowSettled.current = true
    const open = (['stuck', 'pending', 'live'] as const).filter((group) => groups[group])
    if (open.length <= 1) return
    const keep: WorkbenchGroup = split.stuck.length > 0 ? 'stuck'
      : split.review.length > 0 ? 'pending' : 'live'
    const next = { stuck: keep === 'stuck', pending: keep === 'pending', live: keep === 'live' }
    setGroups(next)
    saveWorkbenchGroups(next)
  }, [narrow, pending.length, live.length, groups.stuck, groups.pending, groups.live])

  // The desktop column needs a selection; pick the oldest rendered task once,
  // never steal a selection the reader made while data was arriving.
  useEffect(() => {
    if (!desktop || selected !== null || rendered.length === 0) return
    setSelected(rendered[0]!.id)
    setSnapshot(rendered[0]!)
  }, [desktop, selected, firstRendered])
  // A focus view's title takes focus; the browser's focus ring is the host's.
  useEffect(() => {
    if (desktop || view !== 'focus') return
    const timer = setTimeout(() => { titleRef.current?.focus({ preventScroll: true }) }, 0)
    return () => clearTimeout(timer)
  }, [desktop, view, selected])
  useEffect(() => {
    if (confirmStop) {
      if (confirmTimer.current !== null) clearTimeout(confirmTimer.current)
      confirmTimer.current = setTimeout(() => { setConfirmStop(false) }, WORKBENCH_CONFIRM_MS)
    }
    return () => { if (confirmTimer.current !== null) clearTimeout(confirmTimer.current) }
  }, [confirmStop])
  useEffect(() => {
    if (confirm === null) return undefined
    const timer = setTimeout(() => { setConfirm(null) }, DETAIL_CONFIRM_MS)
    return () => clearTimeout(timer)
  }, [confirm])
  useEffect(() => () => {
    if (updatedTimer.current !== null) clearTimeout(updatedTimer.current)
    if (confirmTimer.current !== null) clearTimeout(confirmTimer.current)
  }, [])

  const focusGroup = (id: WorkbenchGroup): void => {
    const focus = (): void => { groupRefs.current.get(id)?.focus({ preventScroll: true }) }
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') window.requestAnimationFrame(focus)
    else focus()
  }
  const scrollerOf = (element: HTMLElement | null): HTMLElement | null =>
    element === null ? null : element.closest<HTMLElement>('[data-wb-scroll]')
  const contentTop = (header: HTMLElement, scroller: HTMLElement): number =>
    header.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
  const toggleGroup = (id: WorkbenchGroup): void => {
    const header = groupRefs.current.get(id) ?? null
    const scroller = scrollerOf(header)
    const closing = groups[id]
    let before: number | null = null
    if (closing && header !== null && scroller !== null) before = contentTop(header, scroller)
    let next = { ...groups, [id]: !groups[id] }
    if (!closing) {
      // Keep at most one open group under 360px and two above it. Opening a
      // third closes the oldest open one, so the page never grows past a screen.
      const others = (['stuck', 'pending', 'live'] as const).filter((group) => group !== id && next[group])
      if (others.length >= maxOpen) {
        for (const group of others.slice(0, others.length - (maxOpen - 1))) next = { ...next, [group]: false }
      }
    } else {
      setShowAll((current) => ({ ...current, [id]: false }))
    }
    setGroups(next)
    saveWorkbenchGroups(next)
    focusGroup(id)
    if (closing && before !== null && header !== null && scroller !== null) {
      // The finger is on the header: after the 200ms fold, put the header
      // back where it was instead of letting the list jump under it.
      const at = before
      setTimeout(() => {
        const nowTop = contentTop(header, scroller)
        scroller.scrollTop += nowTop - at
      }, 220)
      return
    }
    if (!closing && header !== null && scroller !== null
      && typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(() => {
        const hb = header.getBoundingClientRect()
        const sb = scroller.getBoundingClientRect()
        if (hb.bottom > sb.bottom) header.scrollIntoView({ block: 'start' })
      })
    }
  }
  const selectTab = (id: WorkbenchTab): void => {
    if (id === tab) return
    setTab(id)
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(() => { tabRefs.current.get(id)?.focus({ preventScroll: true }) })
    }
  }
  const onTabKey = (event: React.KeyboardEvent, id: WorkbenchTab): void => {
    const order: WorkbenchTab[] = ['tasks', 'providers', 'overview']
    const at = order.indexOf(id)
    let next: WorkbenchTab | null = null
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = order[(at + order.length - 1) % order.length]!
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = order[(at + 1) % order.length]!
    if (event.key === 'Home') next = order[0]!
    if (event.key === 'End') next = order[order.length - 1]!
    if (next === null) return
    event.preventDefault()
    selectTab(next)
  }
  const choose = (task: DispatchTask): void => {
    detailRequest.current += 1
    activeDetail.current = task.id
    setSelected(task.id)
    setSnapshot(task)
    setSubmittedAt(null)
    setNotice(null)
    setConfirmStop(false)
    setPicker(null); setLog(null); setTimeline(null); setBrief(null); setReadPending(null); setConfirm(null)
  }
  const open = (task: DispatchTask): void => {
    choose(task)
    if (!desktop) setView('focus')
    else setTimeout(() => { titleRef.current?.focus({ preventScroll: true }) }, 0)
  }
  const back = (): void => {
    const id = selected
    const task = shown
    const returnHistory = tab === 'overview' ? historyReturn.current : null
    historyReturn.current = null
    setView('queue')
    setNotice(null)
    setConfirmStop(false)
    detailRequest.current += 1
    activeDetail.current = null
    setPicker(null); setLog(null); setTimeline(null); setBrief(null); setReadPending(null); setConfirm(null)
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(() => {
        if (returnHistory !== null) {
          const historyRow = document.querySelector<HTMLElement>('[data-wb-history="' + CSS.escape(returnHistory) + '"]')
          if (historyRow !== null) { historyRow.focus({ preventScroll: false }); return }
        }
        const row = id === null ? undefined : rowRefs.current.get(id)
        if (row !== undefined) {
          row.focus({ preventScroll: false })
          return
        }
        if (task !== null) groupRefs.current.get(isStuckTask(task) ? 'stuck' : 'pending')?.focus({ preventScroll: false })
      })
    }
  }
  const move = (from: DispatchTask, delta: number): void => {
    const index = rendered.findIndex((task) => task.id === from.id)
    if (index < 0) return
    const next = rendered[Math.max(0, Math.min(rendered.length - 1, index + delta))]
    if (next === undefined) return
    choose(next)
    const element = rowRefs.current.get(next.id)
    if (element !== undefined) element.focus()
  }
  // Esc closes a focus view, then folds the group it is in. It never leaves the
  // workbench from the queue: that would read as "the page ate my session".
  // Arrow/Enter own the desktop list while the page is up, so a click that did
  // not move DOM focus (WebKit) still navigates.
  useEffect(() => {
    const typing = (target: EventTarget | null): boolean => target instanceof HTMLElement
      && target.closest('input, textarea, select, [contenteditable=""], [contenteditable=true]') !== null
    const onKey = (event: KeyboardEvent): void => {
      const root = document.querySelector('[data-wb]')
      if (root === null || root.getClientRects().length === 0) return
      if (event.key === 'Escape') {
        if (confirmStop) { event.preventDefault(); setConfirmStop(false); return }
        if (!desktop && view === 'focus') { event.preventDefault(); back(); return }
        const target = event.target instanceof HTMLElement ? event.target.closest('[data-wb-group]') : null
        const focused = target?.getAttribute('data-wb-group')
        if (focused !== 'stuck' && focused !== 'pending' && focused !== 'live') return
        if (!groups[focused]) return
        event.preventDefault()
        toggleGroup(focused)
        return
      }
      if (!desktop || tab !== 'tasks' || typing(event.target)) return
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        const index = rendered.findIndex((task) => task.id === selected)
        const delta = event.key === 'ArrowDown' ? 1 : -1
        const next = index < 0
          ? (delta > 0 ? rendered[0] : rendered[rendered.length - 1])
          : rendered[Math.max(0, Math.min(rendered.length - 1, index + delta))]
        if (next === undefined) return
        event.preventDefault()
        choose(next)
        rowRefs.current.get(next.id)?.focus()
        return
      }
      if (event.key === 'Enter' && shown !== null) {
        const target = event.target
        if (target instanceof HTMLElement && target.closest('button, a')) return
        event.preventDefault()
        titleRef.current?.focus({ preventScroll: true })
      }
    }
    if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return undefined
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey) }
  }, [confirmStop, desktop, view, selected, rendered, shown, groups, tab])

  const refresh = (): void => {
    setUpdated(false)
    const done = (): void => {
      setUpdated(true)
      if (updatedTimer.current !== null) clearTimeout(updatedTimer.current)
      updatedTimer.current = setTimeout(() => { setUpdated(false) }, WORKBENCH_UPDATED_MS)
    }
    if (tab === 'providers') balances.refresh()
    else queue.refresh()
    setTimeout(done, 350)
  }
  const advance = (): void => {
    const index = rendered.findIndex((task) => task.id === selected)
    const next = rendered.find((task, at) => task.id !== selected && at >= index + 1) ?? rendered.find((task) => task.id !== selected)
    if (next === undefined) { setView('queue'); return }
    choose(next)
    if (!desktop) setView('focus')
  }
  const act = (action: 'continue' | 'modify' | 'stop'): void => {
    if (shown === null || props.runWorkbenchAction === undefined || busy !== null) return
    if (action === 'stop' && !confirmStop) { setConfirmStop(true); return }
    setBusy(action)
    setNotice(null)
    props.runWorkbenchAction(action, shown.id).then((answer) => {
      setBusy(null)
      if (!answer.ok) {
        setNotice({ ok: false, text: t('workbench.actionFailed', { message: answer.message || String(answer.code) }) })
        return
      }
      setConfirmStop(false)
      setSubmittedAt(hhmmOf(Date.now()))
      queue.refresh()
    }, (error: unknown) => {
      setBusy(null)
      setNotice({ ok: false, text: t('workbench.actionFailed', { message: error instanceof Error ? error.message : String(error) }) })
    })
  }
  // ---- The old detail layer's reads and writes ---------------------------------
  // These are the pre-fold task-detail capabilities (brief, log, timeline,
  // model picker, priority, budgets, wrap-up/cancel/retry). They all call the
  // host's existing queueAction; this page only owns their state.
  const resetDetailReads = (): void => {
    detailRequest.current += 1
    setPicker(null); setLog(null); setTimeline(null); setBrief(null); setReadPending(null); setConfirm(null)
  }
  const needsHost = (answer: QueueActionResult): boolean => !answer.ok && /unknown action/.test(answer.message)
  const runAction = props.runQueueAction
  const writable = runAction !== undefined && result?.ops?.available === true
  const queueAct = (action: string, task: DispatchTask, arg = ''): void => {
    if (runAction === undefined || busy !== null) return
    setBusy(action + ':' + task.id)
    setNotice(null)
    runAction(action, task.id, arg).then((answer) => {
      setBusy(null)
      setNotice({ ok: answer.ok, text: needsHost(answer) ? t('queue.r.needsHost') : _describeAction(answer, t) })
      queue.refresh()
    }, (error: unknown) => {
      setBusy(null)
      setNotice({ ok: false, text: t('queue.r.failed', { message: error instanceof Error ? error.message : String(error) }) })
    })
  }
  const openPath = (path: string): void => {
    const opened = props.openFile === undefined ? { ok: false as const, reason: 'no-service' as const } : props.openFile(path)
    const file = path.slice(path.lastIndexOf('/') + 1)
    setNotice(opened.ok ? { ok: true, text: t('queue.brief.opened', { file }) }
      : { ok: false, text: opened.reason === 'no-session' ? t('queue.brief.noSession', { path })
        : opened.reason === 'no-service' ? t('queue.brief.noService', { path })
          : t('queue.brief.failed', { message: opened.message ?? '', path }) })
  }
  const openBrief = (task: DispatchTask): void => {
    const logDir = result?.logDir
    const fallback = logDir ? logDir.replace(/\/+$/, '') + '/' + task.id + '/prompt.md' : null
    setConfirm(null)
    const noDir = (): void => { setNotice({ ok: false, text: t('queue.brief.noDir') }) }
    if (runAction === undefined) {
      if (fallback === null) { noDir(); return }
      setBrief({ id: task.id, path: fallback, bytes: 0, truncated: false, appends: [], needsHost: true, text: '' }); return
    }
    const request = detailRequest.current
    setReadPending('brief')
    runAction('brief', task.id, '').then((answer) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      type Answer = { path?: string; brief?: string; brief_bytes?: number; truncated?: boolean; appends?: BriefView['appends'] }
      let detail: Answer = {}
      try { detail = JSON.parse(answer.detail || '{}') as Answer } catch { detail = {} }
      if (!answer.ok && !needsHost(answer)) {
        setNotice({ ok: false, text: t('queue.a.readFailed', { message: answer.message }) })
        return
      }
      const path = (answer.ok ? detail.path : undefined) ?? fallback
      if (path === null) { noDir(); return }
      const view: BriefView = answer.ok
        ? { id: task.id, path, bytes: detail.brief_bytes ?? 0, truncated: detail.truncated === true, appends: detail.appends ?? [], needsHost: false, text: detail.brief ?? '' }
        : { id: task.id, path, bytes: 0, truncated: false, appends: [], needsHost: true, text: '' }
      setBrief(view)
    }, (error: unknown) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      setNotice({ ok: false, text: t('queue.a.readFailed', { message: error instanceof Error ? error.message : String(error) }) })
    })
  }
  const openFullLog = (task: DispatchTask): void => {
    const logDir = result?.logDir
    if (!logDir) { setNotice({ ok: false, text: t('queue.a.logNoDir') }); return }
    const path = logDir.replace(/\/+$/, '') + '/' + task.id + '/run.log'
    const opened = props.openFile === undefined ? { ok: false as const } : props.openFile(path)
    // The workbench is a global main panel, so dsh has no conversation to
    // preview into. Fall back to the same ops-read log, inline.
    if (!opened.ok) loadLog(task)
  }
  const openPicker = (task: DispatchTask): void => {
    if (runAction === undefined) return
    setConfirm(null)
    const request = detailRequest.current
    setLog(null)
    setPicker(null)
    setReadPending('choices')
    runAction('choices', task.id, '').then((answer) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      type Answer = { models?: string[]; efforts?: Record<string, string[]>; effort_flag?: string; allowed?: boolean; reason?: string; requested?: { model?: string; effort?: string } }
      let detail: Answer = {}
      try { detail = JSON.parse(answer.detail || '{}') as Answer } catch { detail = {} }
      setPicker({
        models: detail.models ?? [], efforts: detail.efforts ?? {}, flag: detail.effort_flag ?? 'effort',
        model: detail.requested?.model ?? task.modelRequested ?? task.model, effort: detail.requested?.effort ?? '',
        allowed: answer.ok && detail.allowed === true, reason: answer.ok ? detail.reason ?? '' : answer.message,
      })
    }, (error: unknown) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      setNotice({ ok: false, text: t('queue.a.readFailed', { message: error instanceof Error ? error.message : String(error) }) })
    })
  }
  const loadLog = (task: DispatchTask): void => {
    if (runAction === undefined) return
    setConfirm(null)
    const request = detailRequest.current
    setPicker(null)
    setReadPending('log')
    runAction('log', task.id, '').then((answer) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      let lines: string[] = []
      try { lines = (JSON.parse(answer.detail || '{}') as { lines?: string[] }).lines ?? [] } catch { lines = [] }
      setLog(answer.ok ? lines : [answer.message])
    }, (error: unknown) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      setNotice({ ok: false, text: t('queue.a.readFailed', { message: error instanceof Error ? error.message : String(error) }) })
    })
  }
  const loadTimeline = (task: DispatchTask): void => {
    if (runAction === undefined) return
    const request = detailRequest.current
    setReadPending('timeline')
    runAction('log', task.id, '').then((answer) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      if (!answer.ok) { setNotice({ ok: false, text: t('queue.a.readFailed', { message: answer.message }) }); return }
      let reply: { timeline?: TaskTimeline } = {}
      try { reply = JSON.parse(answer.detail || '{}') as typeof reply } catch { /* older ops */ }
      setTimeline(reply.timeline ?? 'older')
    }, (error: unknown) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      setNotice({ ok: false, text: t('queue.a.readFailed', { message: error instanceof Error ? error.message : String(error) }) })
    })
  }
  const windowsOf = (agent: string): ReadonlyArray<{ resetAtMs?: number | null }> | undefined => agentWindows(rowMap, agent)
  const sourceOf = (agent: string): DetailSource => {
    const join = PROVIDER_JOIN.find((row) => row.agent === agent)
    const queueRow = (result?.queues ?? []).find((row) => row.agent === agent)
    return {
      plan: join?.plan ?? null,
      row: join?.provider ? rowMap.get(join.provider) : undefined,
      pool: join?.kind === 'pool' ? _poolPosition(result) : undefined,
      poolSize: join?.kind === 'pool' ? result?.opencodePool?.length ?? 0 : 0,
      lane: result === null ? undefined : _slotLanes(result).find((lane) => lane.agent === agent),
      quotaUntilMs: queueRow?.quotaUntilMs ?? null,
      quotaBy: queueRow?.quotaBy ?? '',
    }
  }
  const detailUi = (): DetailUi => ({
    open: (id: string) => {
      const task = pending.find((row) => row.id === id) ?? live.find((row) => row.id === id)
      if (task !== undefined) choose(task)
    },
    act: queueAct, busy, writable,
    confirm, askConfirm: setConfirm, picker, openPicker, setPicker, log, loadLog, brief, readPending,
    openBrief, openFullLog, openPath, windowsOf, sourceOf, timeline, loadTimeline,
  })

  const renderQueue = (): React.ReactElement => {
    if (pending.length === 0 && live.length === 0) {
      return h('div', { className: cx('wb-empty'), 'data-wb-empty': 'true' },
        h('div', { className: cx('wb-empty-title') }, t('workbench.empty.title')),
        h('div', { className: cx('wb-empty-body') }, t('workbench.empty.body')),
        h('div', { className: cx('wb-empty-meta') }, t('workbench.empty.meta', { time: stamp })),
        h('button', {
          type: 'button', className: cx('wb-empty-link'), 'data-wb-empty-providers': 'true',
          onClick: () => { selectTab('providers') },
        }, t('workbench.tab.providers') + ' ›'))
    }
    const bodyId = (id: WorkbenchGroup): string => groupId + '-' + id
    const renderRow = (task: DispatchTask): React.ReactElement => h(WorkbenchRow, {
      key: task.id, task, now, t, selected: selected === task.id,
      buttonRef: (element: HTMLButtonElement | null) => {
        if (element === null) rowRefs.current.delete(task.id)
        else rowRefs.current.set(task.id, element)
      },
      onOpen: () => { open(task) },
      onMove: (delta: number) => { move(task, delta) },
    })
    const renderLive = (task: DispatchTask): React.ReactElement => renderRow(task)
    const group = (id: WorkbenchGroup, label: string, rows: DispatchTask[], tone: 'danger' | 'neutral', render: (task: DispatchTask) => React.ReactElement): React.ReactElement => {
      const isOpen = groups[id]
      const shownRows = showAll[id] === true ? rows : rows.slice(0, capRows)
      const rest = rows.length - shownRows.length
      return h('section', {
        className: cx('wb-group-section'), 'data-wb-group': id, 'data-wb-open': isOpen ? 'true' : 'false',
      },
        h(WorkbenchGroupHeader, {
          id, label, tone, open: isOpen, bodyId: bodyId(id),
          buttonRef: (element: HTMLButtonElement | null) => {
            if (element === null) groupRefs.current.delete(id)
            else groupRefs.current.set(id, element)
          },
          onToggle: () => { toggleGroup(id) },
        }),
        h('div', {
          className: cx('wb-group-body'), id: bodyId(id), 'data-wb-group-body': id,
          'aria-hidden': isOpen ? undefined : 'true', inert: isOpen ? undefined : '',
        },
          h('div', { className: cx('wb-group-body-inner') },
            ...shownRows.map(render),
            rest > 0
              ? h('button', {
                type: 'button', className: cx('wb-more'), 'data-wb-more': id,
                onClick: () => { setShowAll((current) => ({ ...current, [id]: true })) },
              }, t('workbench.group.more', { n: rest }))
              : null)))
    }
    const headline = result === null ? null : _queueHeadline(result, t, now)
    const notices = panelNotices({ queue: result, queueError: queue.data.error, balances: null, balanceError: null, rowCount: 0 }, t)
    const allTasks = [...pending, ...live]
    const claimed = new Set<string>()
    const bySource = sources.map((source) => {
      const agents = new Set([source.agent, source.join?.agent].filter((agent): agent is string => agent !== null && agent !== undefined && agent !== ''))
      const rows = allTasks.filter((task) => agents.has(task.agent)).sort((a, b) => (a.queuedAtMs ?? a.startedAtMs ?? 0) - (b.queuedAtMs ?? b.startedAtMs ?? 0))
      for (const task of rows) claimed.add(task.id)
      return { source, rows }
    }).filter((entry) => entry.rows.length > 0)
    const otherTasks = allTasks.filter((task) => !claimed.has(task.id))
    const sourceSection = (key: string, label: string, rows: DispatchTask[], glyph: React.ReactNode): React.ReactElement => {
      const open = sourceOpen[key] !== false
      const bodyId = groupId + '-source-' + key
      return h('section', {
        className: cx('wb-group-section'), 'data-wb-group': 'source-' + key, 'data-wb-source': key, 'data-wb-open': open ? 'true' : 'false',
      },
        h(WorkbenchGroupHeader, {
          id: 'source-' + key, label, open, tone: 'neutral', bodyId, summary: String(rows.length), lead: glyph,
          buttonRef: () => {},
          onToggle: () => { setSourceOpen((current) => ({ ...current, [key]: !open })) },
        }),
        h('div', {
          className: cx('wb-group-body'), id: bodyId, 'aria-hidden': open ? undefined : 'true', inert: open ? undefined : '',
        }, h('div', { className: cx('wb-group-body-inner') },
          ...rows.map(renderRow))))
    }
    const sourceGroups = h('div', { className: cx('wb-source-groups'), 'data-wb-source-groups': 'true' },
      ...bySource.map(({ source, rows }) => sourceSection(source.key, source.label, rows, h('span', { className: cx('wb-source-glyph'), 'aria-hidden': 'true' }, renderSourceGlyph(source)))),
      otherTasks.length === 0 ? null : sourceSection('other', t('workbench.groupBy.other'), otherTasks, null))
    const groupByBar = h('div', {
      className: cx('wb-groupby'), role: 'group', 'aria-label': t('workbench.groupBy.aria'), 'data-wb-groupby': groupBy,
    },
      h('button', {
        type: 'button', className: cx('wb-groupby-btn', groupBy === 'status' && 'wb-groupby-on'),
        'aria-pressed': groupBy === 'status', onClick: () => { setGroupBy('status') },
      }, t('workbench.groupBy.status')),
      h('button', {
        type: 'button', className: cx('wb-groupby-btn', groupBy === 'source' && 'wb-groupby-on'),
        'aria-pressed': groupBy === 'source', onClick: () => { setGroupBy('source') },
      }, t('workbench.groupBy.source')))
    return h('div', { className: cx('wb-queue-body') },
      notices.length === 0 ? null : h('div', { className: cx('wb-notices'), 'data-wb-notices': 'true' },
        ...notices.map((notice) => h('p', {
          key: notice.key, className: cx('wb-notice', notice.bad && 'wb-notice-bad'), role: notice.bad ? 'status' : undefined,
        }, notice.text))),
      headline === null ? null : h('div', {
        className: cx('wb-headline'), 'data-wb-headline': 'true', 'data-wb-tone': headline.tone, title: headline.title,
      },
        h('span', { className: cx('wb-headline-value') }, headline.value),
        headline.sub === '' ? null : h('span', { className: cx('wb-headline-sub') }, headline.sub)),
      groupByBar,
      groupBy === 'source' ? sourceGroups : h('div', { className: cx('wb-status-groups') },
        split.stuck.length === 0 ? null : group('stuck', t('workbench.group.stuck', { n: split.stuck.length }), split.stuck, 'danger', renderRow),
        split.review.length === 0 ? null : group('pending', t('workbench.group.pendingOldest', {
          n: split.review.length, age: waitShort(counts.oldestPendingMs),
        }), split.review, 'neutral', renderRow),
        live.length === 0 ? null : group('live', t('workbench.group.live', { n: live.length }), live, 'neutral', renderLive)))
  }
  const renderOverview = (): React.ReactElement => {
    const lastRound = result?.patrol.rounds?.[0] ?? null
    const lastView = patrol?.rounds?.[0] ?? null
    const lastTime = hhmmOf(lastPatrolAt(result))
    const lastTook = lastRound?.seconds == null ? '' : waitShort(lastRound.seconds * 1000)
    const progress = patrol?.progress ?? null
    const areaCount = result?.patrol.progress?.areas.length ?? progress?.areas.length ?? 0
    const lensCount = result?.patrol.progress?.lenses.length ?? progress?.lenses.length ?? 0
    const openValues = (result?.patrol.progress?.areas ?? progress?.areas ?? []).map((area) => {
      const value = (area as { open?: unknown }).open
      return value === null || value === undefined || value === '' || !Number.isFinite(Number(value))
        ? null : Number(value)
    })
    const openKnown = openValues.length > 0 && openValues.every((value) => value !== null)
    const openCount = openKnown ? openValues.reduce<number>((sum, value) => sum + (value ?? 0), 0) : null
    const nextTime = hhmmOf(result?.patrol.untilMs ?? null)
    const overviewGroup = (id: string, label: string, open: boolean, onToggle: () => void, summary: string | undefined, body: React.ReactNode): React.ReactElement =>
      h('section', {
        className: cx('wb-group-section', 'wb-ov-group'), 'data-wb-overview-group': id,
        'data-wb-open': open ? 'true' : 'false',
      },
        h(WorkbenchGroupHeader, {
          id: 'overview-' + id, label, open, tone: 'neutral', bodyId: groupId + '-ov-' + id, summary,
          buttonRef: () => {},
          onToggle,
        }),
        h('div', {
          className: cx('wb-group-body'), id: groupId + '-ov-' + id, 'aria-hidden': open ? undefined : 'true',
          inert: open ? undefined : '',
        }, h('div', { className: cx('wb-group-body-inner') }, body)))
    const patrolSummary = lastRound === null
      ? h('div', { className: cx('wb-ov-row') },
        h('span', { className: cx('wb-ov-label') }, t('workbench.overview.lastRound')),
        h('span', { className: cx('wb-ov-value', 'wb-ov-muted') }, t('workbench.overview.noPatrol', { time: nextTime })))
      : h('div', null,
        h('div', { className: cx('wb-ov-row') },
          h('span', { className: cx('wb-ov-label') }, t('workbench.overview.lastRound')),
          h('span', { className: cx('wb-ov-value') },
            lastTime + (lastTook === '' ? '' : ' · ' + lastTook),
            lastView?.state == null ? null : h('span', {
              className: cx('wb-ov-chip'), 'data-role': lastView.state.role,
            }, lastView.state.text))),
        h('div', { className: cx('wb-ov-row') },
          h('span', { className: cx('wb-ov-label') }, t('workbench.overview.coverage')),
          h('span', { className: cx('wb-ov-value') },
            progress === null ? '—' : [
              h('span', { className: cx('wb-ov-chip'), key: 'a' }, t('workbench.overview.areaCount', { n: areaCount })),
              h('span', { className: cx('wb-ov-chip'), key: 'l' }, t('workbench.overview.lensCount', { n: lensCount })),
            ])),
        h('div', { className: cx('wb-ov-row') },
          h('span', { className: cx('wb-ov-label') }, t('workbench.overview.unresolved')),
          h('span', {
            className: cx('wb-ov-value', openCount === null ? 'wb-ov-muted' : openCount > 0 ? 'wb-ov-alert' : 'wb-ov-quiet'),
            'data-wb-overview-open': openCount === null ? 'unknown' : String(openCount),
          }, openCount === null ? '—' : openCount > 0 ? String(openCount) : h('span', null, '0 ', h('span', { className: cx('wb-ov-check'), 'aria-hidden': 'true' }, '✓')))),
        h('div', { className: cx('wb-ov-row') },
          h('span', { className: cx('wb-ov-label') }, t('workbench.overview.cadence')),
          h('span', { className: cx('wb-ov-value', 'wb-ov-muted') }, t('workbench.overview.every', { every: '6h', time: nextTime }))))
    const statsFailed = stats.data !== null && !stats.data.available
    const totals = statsFailed ? null : statsData?.totals ?? null
    const metrics: Array<[string, string]> = [
      [t('stats.metric.tasks'), totals === null ? '—' : String(totals.tasks)],
      [t('stats.metric.tokens'), totals === null ? '—' : totals.tokensText],
      [t('stats.metric.cost'), totals === null ? '—' : totals.costText],
    ]
    const doneN = totals?.done ?? 0
    const unfinishedN = totals === null ? 0 : Math.max(0, totals.settled - totals.done)
    const settledN = doneN + unfinishedN
    const statsMessage = statsData === null
      ? stats.error !== null ? t('workbench.overview.unavailable', { message: stats.error })
        : props.fetchTaskStats === undefined ? t('workbench.overview.noHost') : t('workbench.overview.loading')
      : statsFailed ? t('workbench.overview.unavailable', { message: stats.data?.error ?? '' }) : null
    const statsTop = h('div', { className: cx('wb-ov-stats') },
      h('div', { className: cx('wb-ov-metrics') },
        ...metrics.map(([label, value], at) => h('div', { className: cx('wb-ov-metric'), key: 'm' + at },
          h('span', { className: cx('wb-ov-metric-label') }, label),
          h('span', { className: cx('wb-ov-metric-value') }, value)))),
      h('div', { className: cx('wb-ov-done'), 'data-wb-overview-done': String(doneN) },
        h('div', { className: cx('wb-ov-done-bar') },
          h('span', { className: cx('wb-ov-done-fill'), style: { width: (settledN > 0 ? doneN / settledN * 100 : 0) + '%' } }),
          h('span', { className: cx('wb-ov-open-fill'), style: { width: (settledN > 0 ? unfinishedN / settledN * 100 : 0) + '%' } })),
        h('div', { className: cx('wb-ov-done-labels') },
          h('span', null, t('workbench.overview.done', { n: doneN })),
          h('span', null, t('workbench.overview.open', { n: unfinishedN })))))
    const statsBody = statsMessage !== null
      ? h('div', { className: cx('wb-ov-body', 'pbc') }, h('p', { className: cx('wb-ov-note') }, statsMessage))
      : h('div', null, statsTop, statsData === null ? null : renderStatsBody(statsData, t))
    const statsSummary = statsFailed ? t('workbench.overview.unavailable', { message: stats.data?.error ?? '' })
      : statsData?.summaryLine ?? (stats.loading ? t('workbench.overview.loading') : '—')
    const historyRows = historyRowsView(result, t, now)
    const footer = opsFooter(result, t)
    const openHistory = (id: string, _element: HTMLElement | null): void => {
      const task = (result?.recent ?? []).find((row) => row.id === id)
      if (task === undefined) return
      historyReturn.current = id
      choose(task)
      if (!desktop) setView('focus')
      else setTimeout(() => { titleRef.current?.focus({ preventScroll: true }) }, 0)
    }
    return h('div', { className: cx('wb-ov'), 'data-wb-overview': 'true' },
      overviewGroup('patrol', t('workbench.overview.patrol'), overviewPatrolOpen,
        () => { setOverviewPatrolOpen((open) => !open) },
        lastRound === null ? t('workbench.overview.noPatrol', { time: nextTime })
          : lastTime + (lastView?.state == null ? '' : ' · ' + lastView.state.text),
        patrol === null ? h('p', { className: cx('wb-ov-note') }, t('workbench.overview.noPatrol', { time: nextTime }))
          : renderPatrolBody(patrolSummary, patrol, t)),
      overviewGroup('stats', t('workbench.overview.stats'), overviewStatsOpen,
        () => { setOverviewStatsOpen((open) => !open) }, statsSummary, statsBody),
      overviewGroup('history', t('workbench.overview.history'), overviewHistoryOpen,
        () => { setOverviewHistoryOpen((open) => !open) },
        t('workbench.overview.historySummary', { n: historyRows.length }),
        renderHistoryBody(historyRows, t, openHistory)),
      footer === null ? null : h('p', {
        className: cx('wb-ov-foot', footer.bad && 'wb-ov-foot-bad'), 'data-wb-ops': footer.version,
      }, footer.text))
  }
  const renderProviders = (): React.ReactElement => {
    if (providers.length === 0) {
      if (balances.data.result === null && balances.data.error === null) {
        return h('div', { className: cx('wb-providers-empty'), 'data-wb-providers-loading': 'true' },
          h('div', { className: cx('wb-empty-body') }, t('balance.loading')))
      }
      const failed = balances.data.error !== null && !balances.data.loading
      return h('div', { className: cx('wb-providers-empty'), 'data-wb-providers-empty': 'true' },
        h('span', { className: cx('wb-empty-glyph'), 'aria-hidden': 'true' }, renderWorkbenchGlyph(24)),
        h('div', { className: cx('wb-empty-title') }, failed ? t('workbench.provider.readFailed', { message: balances.data.error }) : t('workbench.provider.empty')),
        failed ? null : h('div', { className: cx('wb-empty-body') }, t('workbench.provider.emptyHint')))
    }
    return h('div', { className: cx('wb-providers', 'pbc'), role: 'list', 'aria-label': t('workbench.tab.providers'), 'data-wb-providers': 'true' },
      balances.data.error !== null && !balances.data.loading
        ? h('div', { className: cx('wb-providers-error'), role: 'status', 'data-wb-providers-error': 'true' },
          t('workbench.provider.readFailed', { message: balances.data.error }))
        : null,
      ...providers.map((row) => h(WorkbenchProviderRow, {
        key: row.key, row, t, now,
        detailRow: row.provider === null ? undefined : rowMap.get(row.provider),
      })))
  }
  const shownLive = shown !== null && (result?.active ?? []).some((task) => task.id === shown.id)
  const showPresets = shown !== null && (!shownLive || shown.question === true)
  const coverage = patrol?.progress ?? null
  const areasOpen = rawProgress === null ? null : rawProgress.areas.filter((area) => (area.open ?? 0) > 0).length
  const coverageLabel = areasOpen === null
    ? t('workbench.fold.coverageUnknown')
    : t('workbench.fold.coverage', { n: areasOpen })
  const needsBlock = shown === null ? null : h('div', { className: cx('wb-needs-block') },
    h('div', { className: cx('wb-needs-label') }, t('workbench.needs')),
    shown.needs === undefined || shown.needs.trim() === ''
      ? h('div', { className: cx('wb-needs-empty') }, t('workbench.needs.empty'))
      : h('p', { className: cx('wb-needs') }, shown.needs),
    showPresets ? h('div', { className: cx('wb-actions') },
      h('button', {
        type: 'button', className: cx('wb-act', 'wb-act-primary'),
        disabled: busy !== null,
        onClick: () => { act('continue') },
      }, busy === 'continue' ? t('workbench.busy') : t('workbench.act.continue')),
      h('button', {
        type: 'button', className: cx('wb-act', 'wb-act-secondary'),
        disabled: busy !== null,
        onClick: () => { act('modify') },
      }, busy === 'modify' ? t('workbench.busy') : t('workbench.act.modify')),
      h('div', { className: cx('wb-danger') },
        h('button', {
          type: 'button', className: cx('wb-act', 'wb-act-danger'),
          disabled: busy !== null,
          'data-wb-confirm': confirmStop ? 'true' : undefined,
          'aria-live': 'polite',
          onClick: () => { act('stop') },
        }, busy === 'stop' ? t('workbench.busy')
          : confirmStop ? t('workbench.act.confirm') : t('workbench.act.stop'))))
      : null,
    submittedAt === null ? null : h('div', { className: cx('wb-recorded'), role: 'status', 'data-wb-recorded': 'true' },
      h('span', { className: cx('wb-recorded-line') },
        t('workbench.recorded'), ' · ',
        h('button', { type: 'button', className: cx('wb-next'), onClick: advance }, t('workbench.next'))),
      h('span', { className: cx('wb-recorded-time') }, submittedAt)))
  const detail = shown === null
    ? h('div', { className: cx('wb-detail-empty') }, t('workbench.select'))
    : h(WorkbenchDetail, {
      task: shown, now, t, desktop, live: shownLive, titleRef, ui: detailUi(), notice,
      top: needsBlock,
      bottom: h(WorkbenchFold, { id: 'coverage', label: coverageLabel },
        coverage === null
          ? h('div', { className: cx('wb-fold-empty') }, t('workbench.info.none'))
          : h('div', { className: cx('wb-cov', 'pbc', 'tqf') }, ...renderCoverageTables(coverage, t))),
    })

  if (!desktop && view === 'focus') {
    return h('div', { className: cx('wb'), 'data-wb': 'true', 'data-wb-view': 'focus' },
      h('div', { className: cx('wb-returnbar') },
        h('button', {
          type: 'button', className: cx('wb-back'), 'data-wb-back': 'true',
          'aria-label': t('workbench.back'), title: t('workbench.back'), onClick: back,
        }, h('span', { className: cx('wb-back-chev'), 'aria-hidden': 'true' }, '‹'), t('workbench.back'))),
      h('div', { className: cx('wb-view'), key: 'focus' }, detail))
  }
  const tabs = h('div', { className: cx('wb-tabs'), role: 'tablist', 'aria-label': t('workbench.tab.aria'), 'data-wb-tabs': 'true' },
    h('button', {
      type: 'button', role: 'tab', id: tabId('tasks'), className: cx('wb-tab', tab === 'tasks' && 'wb-tab-on'),
      'aria-selected': tab === 'tasks', 'aria-controls': panelId, tabIndex: tab === 'tasks' ? 0 : -1,
      'aria-label': t('workbench.tab.tasksAria', { n: counts.total }),
      ref: (element: HTMLButtonElement | null) => {
        if (element === null) tabRefs.current.delete('tasks')
        else tabRefs.current.set('tasks', element)
      },
      onClick: () => { selectTab('tasks') },
      onKeyDown: (event: React.KeyboardEvent) => { onTabKey(event, 'tasks') },
    },
      h('span', null, t('workbench.tab.tasks')),
      counts.total === 0 ? null : h('span', { className: cx('wb-tab-count') }, counts.total)),
    h('button', {
      type: 'button', role: 'tab', id: tabId('providers'), className: cx('wb-tab', tab === 'providers' && 'wb-tab-on'),
      'aria-selected': tab === 'providers', 'aria-controls': panelId, tabIndex: tab === 'providers' ? 0 : -1,
      'aria-label': alerts.length === 0 ? t('workbench.tab.providersClear') : alerts.length === 1 ? t('workbench.tab.providersOne') : t('workbench.tab.providersAria', { n: alerts.length }),
      ref: (element: HTMLButtonElement | null) => {
        if (element === null) tabRefs.current.delete('providers')
        else tabRefs.current.set('providers', element)
      },
      onClick: () => { selectTab('providers') },
      onKeyDown: (event: React.KeyboardEvent) => { onTabKey(event, 'providers') },
    },
      h('span', { className: cx('wb-tab-label') }, t('workbench.tab.providers')),
      alerts.length === 0 ? null : h('span', {
        className: cx('wb-tab-alert'), 'data-wb-tab-alert': 'true', 'aria-hidden': 'true',
        title: alertNames,
      }, '!')),
    h('button', {
      type: 'button', role: 'tab', id: tabId('overview'), className: cx('wb-tab', tab === 'overview' && 'wb-tab-on'),
      'aria-selected': tab === 'overview', 'aria-controls': panelId, tabIndex: tab === 'overview' ? 0 : -1,
      'aria-label': t('workbench.tab.overview'),
      ref: (element: HTMLButtonElement | null) => {
        if (element === null) tabRefs.current.delete('overview')
        else tabRefs.current.set('overview', element)
      },
      onClick: () => { selectTab('overview') },
      onKeyDown: (event: React.KeyboardEvent) => { onTabKey(event, 'overview') },
    }, h('span', { className: cx('wb-tab-label') }, t('workbench.tab.overview'))))
  const panel = tab === 'tasks' ? renderQueue() : tab === 'providers' ? renderProviders() : renderOverview()
  const mainPanel = h('div', {
    className: cx('wb-view'), key: tab, 'data-wb-scroll': 'true', 'data-wb-panel': tab,
  },
    tabs,
    h('div', { role: 'tabpanel', id: panelId, 'aria-labelledby': tabId(tab), className: cx('wb-tabpanel'), 'data-wb-panel': tab }, panel))
  return h('div', { className: cx('wb'), 'data-wb': 'true', 'data-wb-view': 'queue', 'data-wb-tab': tab },
    h('header', { className: cx('wb-head') },
      h('div', { className: cx('wb-head-row') },
        h('button', {
          type: 'button', className: cx('wb-back'), 'data-wb-close': 'true',
          'aria-label': t('workbench.close'), title: t('workbench.close'),
          onClick: () => { props.closeWorkbench() },
        }, h('span', { className: cx('wb-back-chev'), 'aria-hidden': 'true' }, '‹')),
        h('h1', { className: cx('wb-title') }, t('workbench.title')),
        h('span', { className: cx('wb-updated'), 'aria-live': 'polite' }, updated ? t('workbench.updated') : ''),
        h('button', {
          type: 'button', className: cx('wb-refresh'), 'data-wb-refresh': 'true',
          'aria-label': tab === 'providers' ? t('workbench.refresh.providers') : t('workbench.refresh.tasks'),
          title: tab === 'providers' ? t('workbench.refresh.providers') : t('workbench.refresh.tasks'),
          onClick: refresh,
        }, h('svg', { width: 16, height: 16, viewBox: '0 0 16 16', fill: 'none', 'aria-hidden': 'true' },
          h('path', {
            d: 'M13 8a5 5 0 1 1-1.6-3.7M13 2.6V5h-2.4', stroke: 'currentColor', strokeWidth: 1.35,
            strokeLinecap: 'round', strokeLinejoin: 'round',
          })))),
      h('div', { className: cx('wb-sub') }, tab === 'tasks'
        ? t('workbench.sub.tasks', { n: counts.total, age: counts.total === 0 ? '—' : waitShort(counts.oldestPendingMs) })
        : tab === 'providers'
          ? alerts.length === 1
            ? t('workbench.sub.providersOne', { n: providers.length })
            : t('workbench.sub.providers', { n: providers.length, alerts: alerts.length })
          : t('workbench.sub.overview', { time: stamp, n: overviewOpen ?? '—' }))),
    h('div', { className: cx('wb-main') },
      desktop
        ? h('div', { className: cx('wb-grid') },
          h('aside', { className: cx('wb-queue'), 'data-wb-queue': 'true' }, mainPanel),
          h('div', { className: cx('wb-pane'), 'data-wb-pane': 'true' }, detail))
        : mainPanel))
}
export function DecisionMind(props: DecisionMindProps): React.ReactElement {
  const t = props.t
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
      ? { trades: [], rate: null, rateSource: null, loading: true, error: null, stale: false }
      : { trades: cached.trades, rate: cached.rate, rateSource: cached.rateSource, loading: false, error: null, stale: false }
  })

  useEffect(() => {
    let alive = true
    props.fetchTraces().then((fetched) => {
      if (!alive || !fetched.changed) return // 同一份数据,跳过重渲染
      setData({ trades: fetched.snapshot.trades, rate: fetched.snapshot.rate, rateSource: fetched.snapshot.rateSource, loading: false, error: null, stale: false })
    }, (error: unknown) => {
      if (!alive) return
      if (props.cachedTraces() !== null) setData((current) => ({ ...current, stale: true }))
      else {
        const message = error instanceof LedgerUnreadable ? t('trace.unreadable') : messageOf(error)
        setData({ trades: [], rate: null, rateSource: null, loading: false, error: message, stale: false })
      }
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
          h('div', { className: cx('tt') }, t('trace.title'),
            h('span', { className: cx('ts') }, t('trace.subtitle'))))),
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
    ? t('trace.realizedUsdNoRate')
    : t('trace.realizedUsd')
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
  // Counted on the STABLE kind, never on the rendered verdict. Matching the
  // host's Chinese text here made display copy load-bearing logic: translating
  // it would have quietly zeroed both tallies. `verdict` stays read as the
  // fallback for a host that predates `verdictKind`.
  const verdictIs = (trace: DisplayEntry, kind: string, text: string): boolean =>
    trace.t1 === null ? false
      : trace.t1.verdictKind == null ? trace.t1.verdict === text : trace.t1.verdictKind === kind
  const soldEarly = sells.filter((trace) => verdictIs(trace, 'soldEarly', '卖飞')).length
  const soldRight = sells.filter((trace) => verdictIs(trace, 'soldRight', '卖对')).length
  // The dead band's third verdict is counted too, so the three numbers add up to `sellsRated` (#2064).
  const soldFlat = sells.filter((trace) => verdictIs(trace, 'flat', '持平')).length
  const matched = traces.filter((trace) => trace.decision !== null).length
  const reversed = traces.filter((trace) => trace.decision?.alignment === 'opposite').length

  const groups: Record<string, DisplayEntry[]> = {}
  const traceKeys = _traceKeys(traces)
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
        relativeDay(date, today, t),
        h('span', null, date),
        h('span', { className: cx('n') }, rows.length)),
      folded ? null : h('div', { className: cx('group') }, rows.map((trace) => {
        const key = traceKeys.get(trace) as string
        return h(TraceCell, {
          key,
          trace,
          t,
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
    }, t('trace.more', { fills: moreFills }))
  } else if (visibleDateCount > DEFAULT_VISIBLE_DATES) {
    moreButton = h('button', {
      key: 'more', className: cx('trace-more'), onClick: () => { actions.resetDates() },
    }, t('trace.less', { groups: DEFAULT_VISIBLE_DATES }))
  }

  let body: React.ReactElement
  if (filtered.length === 0) {
    body = h('div', { className: cx('empty') }, t('trace.empty'))
  } else {
    const kids: React.ReactElement[] = visibleDates.map(renderDate)
    if (moreButton !== null) kids.push(moreButton)
    body = h('div', null, kids)
  }

  const stats = h('div', { className: cx('stats') },
    h('div', { className: cx('sg') },
      h('span', { className: cx('sl') }, totalLabel),
      h('span', { className: cx('sv', 'focus', totalUsd >= 0 ? 'up' : 'down') }, _fmtMoney(totalUsd, 'USD'))),
    h('div', { className: cx('sg') },
      h('span', { className: cx('sl') }, t('trace.t1Tally', { rated: sellsRated, sells: sells.length })
        + (sideless === 0 ? '' : t('trace.t1Sideless', { sideless }))),
      h('span', { className: cx('sv') },
        h('span', { className: cx('down') }, soldEarly), ' / ', h('span', { className: cx('up') }, soldRight), ' / ', h('span', null, soldFlat))),
    h('div', { className: cx('sg') },
      h('span', { className: cx('sl') }, t('trace.matched') + (reversed === 0 ? '' : t('trace.reversed', { reversed }))),
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
    }, t(FILTER_LABEL[value] as string))))

  // The header rides the host's content column (`--dsh-chat-content-width`),
  // so the sticky bar lines up with the rows instead of running full-bleed
  // over them; only its background and rule span the view.
  return h('div', { className: cx('dmt'), ref: rootRef },
    h('div', { className: cx('top') },
      h('div', { className: cx('tin') },
        h('div', { className: cx('tt') }, t('trace.title'),
          h('span', { className: cx('ts') }, t('trace.subtitle') + (data.stale ? t('trace.staleSuffix') : '')),
          h('span', { className: cx('rate') },
            t('trace.fillCount', { count: traces.length }) + (rate === null ? '' : ' · @' + rate
              + (data.rateSource ? ' · ' + data.rateSource : '')))),
        stats)),
    h('div', { className: cx('bar') },
      h('div', { className: cx('bin') }, filters)),
    h('div', { className: cx('list') }, body))
}

/**
 * `layout` is listed even though the plugin only *probes* it, and that is not
 * an oversight — it is the one thing `ctx.get` cannot do here. The probe runs
 * inside `apply`, and `ctx.get` does not wait: it returns `undefined` when the
 * providing fiber has not activated yet, so the chip silently fell back to the
 * session-header seat (verified live, 2026-09-19 — `[data-clawock-action]`
 * count 0 while the header chip rendered). `inject` is the mechanism that
 * holds the plugin until the service exists.
 *
 * The cost is real and accepted: on a host with no `layout` at all, the whole
 * client half waits and the Decision Mind tab does not mount either. Every
 * shipped host provides it, and the alternative trades a hypothetical
 * older-host degradation for a measured one on the host we run.
 */
export const inject = ['slots', 'remote', 'layout', 'locale']

/** Client contribution context: the face the slot renderer hands us. */
interface ClientContributionContext {
  slots: {
    inject: (name: string, register: () => unknown) => unknown
    register: (definition: Record<string, unknown>, component: unknown) => unknown
  }
  remote: TypertClientRemote
  /** Locale registry: this bundle owns one dictionary namespace (see LOCALE_NS). */
  locale: {
    register: (ns: string, dicts: Record<string, Record<string, string>>) => () => void
    /** Optional only for the test harness and a host older than this service face. */
    bind?: (ns: string) => Translate
  }
  /** Injected host layout face; `selectPanel` exists only where `main` is keyed (DSH >= 0.1.5-rc.1). */
  layout?: LayoutProbe
  /** Service lookup; each call site narrows the face it asked for. */
  get: (name: string) => unknown
}

/** Remote face of the gateway: one async method per `@Remote`, ok/error wrapped. */
type StudioRemoteFace = Record<string, (...args: unknown[]) => Promise<unknown>>

/** `selectPanel` exists only where `main` is keyed (DSH >= 0.1.5-rc.1). */
type LayoutProbe = {
  selectPanel?: (panelId: string | null) => void
  /** Open/close the left column; below 768px that is the drawer. */
  toggleSidebar?: () => void
}

/** Remote answer shape: the gateway's ok/error envelope. */
type RemoteResult<T> = { ok: true; value: T } | { ok: false; error: { code: string; message: string } }

/** Register the Decision Mind tab into the conversation view ring. */
export async function apply(ctx: Context & ClientContributionContext): Promise<void> {
  // One dictionary registration for the whole bundle, owned by this fiber:
  // `ctx.effect` is what removes it when the plugin unloads. Declaring
  // `locale: LOCALE_NS` on a registration is what puts the `t` seat on that
  // component's props.
  ctx.effect(() => ctx.locale.register(LOCALE_NS, dictionaries), 'clawock-dsh: dictionaries')
  await ctx.remote.$mount(TYPERT_REMOTE as TypertRemoteContribution)
  const studioRemote = ctx.get('remote.clawockStudio') as StudioRemoteFace
  // The capability probe reads the INJECTED face, not a `ctx.get`: see `inject`.
  const layout = ctx.layout
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
      // Not cached: a later mount retries instead of replaying the empty book.
      if (result.lastUpdated === null) throw new LedgerUnreadable('portfolio.json unreadable')
      const snapshot: TraceSnapshot = {
        workspaceKey: result.workspaceKey,
        signature: result.signature,
        trades: result.trades,
        rate: result.rate,
        // An older host half omits nothing here, but tolerate one that does.
        rateSource: result.rateSource ?? null,
      }
      // The host answers a signature hit in µs from its own cache; an
      // unchanged signature means the rendered snapshot is still current,
      // except for the one field that moves with the clock: the FX provenance
      // label gains its staleness warning while the signature stays put (#2670).
      const changed = cached === null
        || cached.workspaceKey !== snapshot.workspaceKey
        || cached.signature !== snapshot.signature
        || cached.rateSource !== snapshot.rateSource
      cached = snapshot
      return { snapshot, changed }
    },
  })
  // The chip is app-level account chrome, not decision data, and belongs to
  // no session. On hosts with global panels (`ctx.layout.selectPanel`) the
  // readings moved into the workbench's Providers segment (2026-11-07); only
  // an older host with no main-panel slot still gets the header chip.
  const balanceListeners = new Set<(result: BalancesResult) => void>()
  const balancesInjected = (): BalancesInjected => ({
    cachedBalances: () => cachedBalances,
    fetchBalances: async (force) => {
      const result = await call<BalancesResult>('balance', [force])
      cachedBalances = result
      for (const listener of balanceListeners) listener(result)
      return result
    },
    subscribeBalances: (listener) => {
      balanceListeners.add(listener)
      return () => { balanceListeners.delete(listener) }
    },
  })
  const store = createDecisionMindStore()
  ctx.slots.inject('conversation.view', () => ctx.slots.register({
    name: 'conversation.view',
    id: 'decision-studio',
    order: 30,
    label: () => 'Decision Mind',
    store,
    locale: LOCALE_NS,
    inject: injected,
  }, DecisionMind))
  const balancesStore = createBalanceStore()
  if (typeof layout?.selectPanel === 'function') {
    // The workbench's data channels: queue + balances share the same remote
    // answer and the same cache, so the icon and the page cannot disagree.
    let cachedTaskQueue: TaskQueueResult | null = null
    const queueInjected = (): TaskQueueInjected => ({
      cachedTaskQueue: () => cachedTaskQueue,
      fetchTaskQueue: async (force) => {
        cachedTaskQueue = await call<TaskQueueResult>('taskQueue', [force])
        return cachedTaskQueue
      },
      // A host installed before taskStats existed has no stats card; the queue is unaffected.
      fetchTaskStats: typeof studioRemote.taskStats === 'function'
        ? (query) => call<TaskStats>('taskStats', [query.days, query.since, query.patrol])
        : undefined,
      // A host installed before queueAction existed has no such method: stay read-only.
      runQueueAction: typeof studioRemote.queueAction === 'function'
        ? (action, id, arg) => call<QueueActionResult>('queueAction', [action, id, arg])
        : undefined,
    })
    // dsh's own file preview (the right sidebar). Looked up at click time — long after apply, so
    // the service exists when there is one — and never injected: a host without it keeps the page.
    const openFile: OpenFile = (path) => {
      const sidebar = ctx.get('sidebarRight') as { openResource?: (address: string, options?: unknown) => void; mounted?: { getSnapshot(): unknown } } | undefined
      if (sidebar === undefined || typeof sidebar.openResource !== 'function') return { ok: false, reason: 'no-service' }
      const session = sidebar.mounted?.getSnapshot()
      if (typeof session !== 'string' || session === '') return { ok: false, reason: 'no-session' }
      try {
        sidebar.openResource(_sessionFileAddress(session, path))
        return { ok: true }
      } catch (error) {
        return { ok: false, reason: 'error', message: error instanceof Error ? error.message : String(error) }
      }
    }
    // The two entries and the page share one remembered trigger: whichever
    // control opened the workbench gets focus back when it closes.
    let workbenchTrigger: HTMLElement | null = null
    const rememberTrigger = (element: HTMLElement | null): void => { workbenchTrigger = element }
    const closeWorkbench = (): void => {
      layout.selectPanel!(null)
      if (typeof window === 'undefined') return
      // On a phone the drawer closes when a main panel is selected, taking
      // the trigger out of the focus order. Reopening it is what makes
      // "focus returns to the row/icon that opened the page" true there as
      // well; on desktop the column never left.
      const narrow = typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 767px)').matches
      if (narrow) layout.toggleSidebar?.()
      const focus = (): void => { workbenchTrigger?.focus({ preventScroll: true }) }
      if (typeof window.requestAnimationFrame === 'function') window.requestAnimationFrame(focus)
      if (narrow) setTimeout(focus, 260)
    }
    const workbenchInjected = (): WorkbenchInjected => ({
      ...queueInjected(),
      ...balancesInjected(),
      closeWorkbench,
      openFile,
      // A host half older than this method gives the page a read-only focus view.
      runWorkbenchAction: typeof studioRemote.workbenchAction === 'function'
        ? (action, id) => call<QueueActionResult>('workbenchAction', [action, id])
        : undefined,
    })
    const label = (): string =>
      typeof ctx.locale.bind === 'function' ? ctx.locale.bind(LOCALE_NS)('signal.icon') : dictionaries.en['signal.icon'] ?? ''
    // The permanent entry: the icon is a main-panel launcher, never a second
    // block in the sidebar; the host owns its button and selected state.
    ctx.slots.inject('main', () => ctx.slots.register({
      name: 'main', key: WORKBENCH_PANEL, locale: LOCALE_NS, inject: workbenchInjected,
    }, WorkbenchPage))
    ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
      name: 'sidebar.panellist', id: WORKBENCH_PANEL, order: 10, label, locale: LOCALE_NS,
      inject: (): WorkbenchIconInjected => ({ ...queueInjected(), ...balancesInjected(), rememberTrigger }),
    }, WorkbenchIcon))
  } else {
    ctx.slots.inject('conversation.session.header.utilities', () => ctx.slots.register({
      name: 'conversation.session.header.utilities',
      id: 'provider-balance',
      order: 90,
      store: balancesStore,
      locale: LOCALE_NS,
      inject: balancesInjected,
    }, ProviderBalanceChip))
  }
}
