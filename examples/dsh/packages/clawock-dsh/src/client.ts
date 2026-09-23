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
import type { BalanceResult, BalancesResult, DispatchTask, EnrichedTrade, T1VerdictKind, TaskQueueResult, TraceDecision, TraceT1, TracesResult } from './types.ts'

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

// ---------------------------------------------------------------------------
// Copy. Every string this plugin renders comes from one dictionary namespace so
// the host's locale service can pick the language; the module owns no display
// text of its own beyond the vendor detail it reports verbatim.
// ---------------------------------------------------------------------------

/** Dictionary namespace declared by every registration in this bundle. */
export const LOCALE_NS = 'clawock'

/**
 * Translate one dictionary key with optional `{name}` params. Hand-declared
 * rather than derived from the host's `TranslateNS<NS>`: that type needs the
 * `LocaleNamespaceMap` merge the locale plugin owns, and this file's rule is to
 * hand-declare what cannot be derived without a cross-plugin type import (the
 * same reason `sessionId` is declared, not derived).
 */
export type Translate = (key: string, params?: Record<string, unknown>) => string

/**
 * This plugin's copy, in the locales the browser client ships (`zh`, `en` —
 * `dsh-client-locale`'s LOCALE_IDS). Keys are grouped by surface; the two
 * dictionaries must carry the same key set, which `tests/decision_studio_plugin.spec.js`
 * enforces so a missing translation cannot ship.
 */
export const dictionaries: Record<string, Record<string, string>> = {
  zh: {
    'action.buy': '买入', 'action.add': '加仓', 'action.trim': '减仓', 'action.sell': '卖出',
    'action.cut': '割肉', 'action.hold': '持有', 'action.trim_on_rebound': '反弹减仓',
    'action.t_only': '仅T+0', 'action.add_only_on_trigger': '触发加仓', 'action.reject': '不加',
    'action.watch': '观望', 'action.abstain': '弃权',
    'driver.technical': '技术面', 'driver.fundamental': '基本面', 'driver.sentiment': '情绪面',
    'driver.mixed': '混合', 'driver.risk_rule': '风控规则',
    'exe.followed': '遵守了计划', 'exe.not_followed': '没按计划', 'exe.unknown': '未标注',
    'align.same': '与计划同向', 'align.opposite': '与计划反向', 'align.other': '计划未指向买卖',
    'emo.fomo': '追高冲动', 'emo.revenge': '报复性', 'emo.averaging_down': '摊薄冲动',
    'emo.fear': '恐慌', 'emo.euphoria': '亢奋', 'emo.calm': '平静', 'emo.mixed': '混合',
    'filter.all': '全部', 'filter.miss': '无当日计划', 'filter.sold': '卖出复盘', 'filter.dec': '有当日计划',
    't1.up': '涨', 't1.down': '跌', 't1.soldEarly': '卖飞', 't1.soldRight': '卖对', 't1.flat': '持平',
    'time.today': '今天', 'time.yesterday': '昨天', 'time.daysAgo': '{days}天前',
    'time.date': '{month}月{day}日',
    'time.weekday.0': '周日', 'time.weekday.1': '周一', 'time.weekday.2': '周二', 'time.weekday.3': '周三',
    'time.weekday.4': '周四', 'time.weekday.5': '周五', 'time.weekday.6': '周六',
    'trace.title': '决策轨迹', 'trace.subtitle': '一笔真实成交 + 当时写下的计划 + 官方收盘给的结果',
    'trace.staleSuffix': ' · 更新失败,显示此前快照',
    'trace.titleWithPlan': '决策轨迹 · {date}', 'trace.titleNoPlan': '决策轨迹 · 无当日计划',
    'trace.planThen': '当时的计划', 'trace.noPlanRecord': '这一天没有该标的的计划记录',
    'trace.realFill': '真实成交', 'trace.t1Close': 'T+1 收盘', 'trace.t1Pending': 'T+1 未判',
    'trace.unpaired': '这笔成交在决策账本里找不到前后 3 天的同标的计划:成交是真的,当时的判断没有留下记录。',
    'trace.sharesAt': ' 股 @ ', 'trace.shares': ' 股', 'trace.confidence': ' · 信心 ',
    'trace.trigger': '触发条件: ', 'trace.selfGrade': '账本自评: ',
    'trace.realized': '本笔已实现', 'trace.pnl': '本笔盈亏', 'trace.openPosition': '— 未平仓',
    'trace.floating': '该持仓当前浮动 ({ticker} 全仓,非本笔)',
    'trace.why': '为什么 ', 'trace.emotion': '情绪 ', 'trace.note': '备注 ',
    'trace.holding': '持仓', 'trace.opposite': '反向', 'trace.market.hk': '港', 'trace.market.us': '美',
    'trace.realizedUsd': '已实现 (USD 等值)', 'trace.realizedUsdNoRate': '已实现 (USD 等值 · HKD 未折算)',
    'trace.t1Tally': 'T+1 卖飞/卖对 · 判出 {rated}/{sells} 笔卖出',
    'trace.t1Sideless': ' · {sideless} 笔无侧向',
    'trace.matched': '有当日计划', 'trace.reversed': ' · 反向 {reversed}',
    'trace.more': '显示更早的 {fills} 笔成交', 'trace.less': '收起,只显示最近 {groups} 组',
    'trace.empty': '没有符合条件的成交', 'trace.fillCount': '{count} 笔成交',
    'balance.loading': '余额加载中', 'balance.unconfigured': '未配置',
    'balance.unconfiguredKey': '未配置 API Key', 'balance.fetchFailed': '余额获取失败',
    'balance.windowsUsed': '配额窗口已使用', 'balance.apiBalance': 'API 余额',
    'balance.granted': '赠金 ', 'balance.toppedUp': '充值 ',
    'balance.insufficient': '官方接口判定余额不足',
    'balance.staleWith': '刷新失败,显示最近一次: {message}',
    'balance.stale': '刷新失败,显示最近一次',
    'balance.windowAt': '窗口已使用达 {percent}%',
    'balance.lowMoney': '余额偏低,低于阈值 {amount}',
    'balance.panelTitle': '各模型服务余额', 'balance.panelHeading': 'API 余额',
    'balance.refreshAll': '刷新全部余额', 'balance.refreshNow': '立即刷新',
    'balance.readFailed': '余额读取失败:{message}', 'balance.reading': '正在读取各服务余额…',
    'balance.otherProviders': '(点击查看其他服务)',
    'balance.unknownError': '未知错误',
    'balance.windowNote': '{label} 已用 {percent}%',
    'balance.windowNoteReset': '{label} 已用 {percent}%,{reset} 重置',
    'balance.window.week': '周', 'balance.window.days': '{n}天', 'balance.window.hours': '{n}h',
    'balance.window.minutes': '{n}m',
    'balance.reset.today': '今天 {time}', 'balance.reset.tomorrow': '明天 {time}',
    'balance.reset.dated': '{date} {weekday} {time}',
    'queue.name': '任务', 'queue.panelTitle': '派发任务队列', 'queue.panelHeading': '派发队列',
    'queue.refresh': '刷新任务队列', 'queue.slots': '槽 {used}/{max}', 'queue.slotsHeading': '运行槽', 'queue.slotsCount': '{used}/{max}',
    'queue.queued': '排队 {n}', 'queue.quotaWait': '等额度 {n}', 'queue.retryWait': '等重试 {n}', 'queue.idle': '没有在跑的任务',
    'queue.readFailed': '任务队列读取失败:{message}', 'queue.staleWith': '刷新失败,显示最近一次: {message}',
    'queue.state.running': '运行中 · 槽 {slot}', 'queue.state.starting': '启动中',
    'queue.wait.lock': '等 {agent} 锁', 'queue.wait.slot': '等运行槽', 'queue.wait.memory': '等内存',
    'queue.wait.quota': '等额度 · {time} 续跑', 'queue.wait.quotaNoTime': '等额度',
    'queue.wait.retry': '重试等待 · {time}', 'queue.wait.retryNoTime': '重试等待',
    'queue.meta': '{agent} · {model}', 'queue.run': '已跑 {elapsed} · 第 {attempts} 次',
    'queue.waitHeading': '排队 / 等待', 'queue.noneRunning': '没有占用运行槽的任务', 'queue.noneWaiting': '没有排队或等待的任务',
    'queue.recentHeading': '最近结束',
    'queue.patrolHeading': '巡检', 'queue.patrolRound': '当前轮次 {round}', 'queue.roundsHeading': '最近几轮',
    'queue.patrol.running': '巡检运行中', 'queue.patrol.yielding': '巡检让路中',
    'queue.patrol.waiting': '巡检等待下一轮', 'queue.patrol.waitingUntil': '巡检 {time} 开下一轮',
    'queue.patrol.stopped': '巡检已停', 'queue.patrol.unknown': '巡检状态未知',
    'queue.duration.minutes': '{m} 分', 'queue.duration.hours': '{h} 小时 {m} 分',
    'queue.ago.minutes': '{m} 分钟前', 'queue.ago.hours': '{h} 小时前', 'queue.ago.days': '{d} 天前',
    'queue.back': '返回队列', 'queue.d.open': '查看任务详情', 'queue.d.live': '进行中', 'queue.d.ended': '已结束',
    'queue.d.agent': 'Agent', 'queue.d.model': '模型', 'queue.d.started': '开始', 'queue.d.elapsed': '已运行',
    'queue.d.took': '用时', 'queue.d.endedAt': '结束', 'queue.d.resumes': '续跑', 'queue.d.attempts': '尝试次数',
    'queue.d.latest': '最近事件', 'queue.d.id': '任务 ID', 'queue.d.summary': '结果摘要', 'queue.d.noSummary': '没有留下结果摘要',
  },
  en: {
    'action.buy': 'Buy', 'action.add': 'Add', 'action.trim': 'Trim', 'action.sell': 'Sell',
    'action.cut': 'Cut', 'action.hold': 'Hold', 'action.trim_on_rebound': 'Trim on rebound',
    'action.t_only': 'T+0 only', 'action.add_only_on_trigger': 'Add on trigger', 'action.reject': 'No add',
    'action.watch': 'Watch', 'action.abstain': 'Abstain',
    'driver.technical': 'Technical', 'driver.fundamental': 'Fundamental', 'driver.sentiment': 'Sentiment',
    'driver.mixed': 'Mixed', 'driver.risk_rule': 'Risk rule',
    'exe.followed': 'Followed the plan', 'exe.not_followed': 'Did not follow', 'exe.unknown': 'Unmarked',
    'align.same': 'Same side as plan', 'align.opposite': 'Against the plan', 'align.other': 'Plan was not a trade',
    'emo.fomo': 'FOMO', 'emo.revenge': 'Revenge', 'emo.averaging_down': 'Averaging down',
    'emo.fear': 'Fear', 'emo.euphoria': 'Euphoria', 'emo.calm': 'Calm', 'emo.mixed': 'Mixed',
    'filter.all': 'All', 'filter.miss': 'No plan that day', 'filter.sold': 'Sell reviews', 'filter.dec': 'Had a plan',
    't1.up': 'up', 't1.down': 'down', 't1.soldEarly': 'sold too early', 't1.soldRight': 'sold well', 't1.flat': 'flat',
    'time.today': 'today', 'time.yesterday': 'yesterday', 'time.daysAgo': '{days}d ago',
    'time.date': '{month}/{day}',
    'time.weekday.0': 'Sun', 'time.weekday.1': 'Mon', 'time.weekday.2': 'Tue', 'time.weekday.3': 'Wed',
    'time.weekday.4': 'Thu', 'time.weekday.5': 'Fri', 'time.weekday.6': 'Sat',
    'trace.title': 'Decision trace', 'trace.subtitle': 'A real fill + the plan written at the time + the official close',
    'trace.staleSuffix': ' · refresh failed, showing the previous snapshot',
    'trace.titleWithPlan': 'Decision trace · {date}', 'trace.titleNoPlan': 'Decision trace · no plan that day',
    'trace.planThen': 'The plan at the time', 'trace.noPlanRecord': 'No plan recorded for this ticker that day',
    'trace.realFill': 'Real fill', 'trace.t1Close': 'T+1 close', 'trace.t1Pending': 'T+1 unjudged',
    'trace.unpaired': 'No plan for this ticker within ±3 days in the decision ledger: the fill is real, the thinking left no record.',
    'trace.sharesAt': ' shares @ ', 'trace.shares': ' shares', 'trace.confidence': ' · confidence ',
    'trace.trigger': 'Trigger: ', 'trace.selfGrade': 'Ledger self-grade: ',
    'trace.realized': 'Realized on this fill', 'trace.pnl': 'P&L on this fill', 'trace.openPosition': '— still open',
    'trace.floating': 'This position is floating ({ticker} whole book, not this fill)',
    'trace.why': 'Why ', 'trace.emotion': 'Emotion ', 'trace.note': 'Note ',
    'trace.holding': 'Position', 'trace.opposite': 'Against plan', 'trace.market.hk': 'HK', 'trace.market.us': 'US',
    'trace.realizedUsd': 'Realized (USD equivalent)', 'trace.realizedUsdNoRate': 'Realized (USD equivalent · HKD unconverted)',
    'trace.t1Tally': 'T+1 sold-early/sold-well · {rated}/{sells} sells judged',
    'trace.t1Sideless': ' · {sideless} with no side',
    'trace.matched': 'Had a plan that day', 'trace.reversed': ' · {reversed} against plan',
    'trace.more': 'Show {fills} earlier fills', 'trace.less': 'Collapse to the latest {groups} groups',
    'trace.empty': 'No fill matches this filter', 'trace.fillCount': '{count} fills',
    'balance.loading': 'Loading balance', 'balance.unconfigured': 'Not set',
    'balance.unconfiguredKey': 'No API key configured', 'balance.fetchFailed': 'Balance unavailable',
    'balance.windowsUsed': 'Quota windows in use', 'balance.apiBalance': 'API balance',
    'balance.granted': 'Granted ', 'balance.toppedUp': 'Topped up ',
    'balance.insufficient': 'The provider reports insufficient balance',
    'balance.staleWith': 'Refresh failed, showing the last reading: {message}',
    'balance.stale': 'Refresh failed, showing the last reading',
    'balance.windowAt': 'A window is at {percent}% used',
    'balance.lowMoney': 'Balance low, below the {amount} threshold',
    'balance.panelTitle': 'Model service balances', 'balance.panelHeading': 'API balance',
    'balance.refreshAll': 'Refresh all balances', 'balance.refreshNow': 'Refresh now',
    'balance.readFailed': 'Balance read failed: {message}', 'balance.reading': 'Reading balances…',
    'balance.otherProviders': '(click for other services)',
    'balance.unknownError': 'unknown error',
    'balance.windowNote': '{label} {percent}% used',
    'balance.windowNoteReset': '{label} {percent}% used, resets {reset}',
    'balance.window.week': 'week', 'balance.window.days': '{n}d', 'balance.window.hours': '{n}h',
    'balance.window.minutes': '{n}m',
    'balance.reset.today': 'today {time}', 'balance.reset.tomorrow': 'tomorrow {time}',
    'balance.reset.dated': '{date} {weekday} {time}',
    'queue.name': 'Tasks', 'queue.panelTitle': 'Dispatch task queue', 'queue.panelHeading': 'Dispatch queue',
    'queue.refresh': 'Refresh the task queue', 'queue.slots': 'slots {used}/{max}', 'queue.slotsHeading': 'Run slots', 'queue.slotsCount': '{used}/{max}',
    'queue.queued': '{n} queued', 'queue.quotaWait': '{n} waiting on quota', 'queue.retryWait': '{n} waiting to retry', 'queue.idle': 'No task running',
    'queue.readFailed': 'Task queue read failed: {message}', 'queue.staleWith': 'Refresh failed, showing the last read: {message}',
    'queue.state.running': 'running · slot {slot}', 'queue.state.starting': 'starting',
    'queue.wait.lock': 'waiting for the {agent} lock', 'queue.wait.slot': 'waiting for a run slot', 'queue.wait.memory': 'waiting for memory',
    'queue.wait.quota': 'quota wait · resumes {time}', 'queue.wait.quotaNoTime': 'quota wait',
    'queue.wait.retry': 'retry wait · {time}', 'queue.wait.retryNoTime': 'retry wait',
    'queue.meta': '{agent} · {model}', 'queue.run': '{elapsed} · attempt {attempts}',
    'queue.waitHeading': 'Queued / waiting', 'queue.noneRunning': 'No task holds a slot', 'queue.noneWaiting': 'Nothing queued or waiting',
    'queue.recentHeading': 'Recently ended',
    'queue.patrolHeading': 'Patrol', 'queue.patrolRound': 'current round {round}', 'queue.roundsHeading': 'Recent rounds',
    'queue.patrol.running': 'patrol running', 'queue.patrol.yielding': 'patrol giving way',
    'queue.patrol.waiting': 'patrol between rounds', 'queue.patrol.waitingUntil': 'patrol next round {time}',
    'queue.patrol.stopped': 'patrol stopped', 'queue.patrol.unknown': 'patrol state unknown',
    'queue.duration.minutes': '{m}m', 'queue.duration.hours': '{h}h {m}m',
    'queue.ago.minutes': '{m}m ago', 'queue.ago.hours': '{h}h ago', 'queue.ago.days': '{d}d ago',
    'queue.back': 'Back to the queue', 'queue.d.open': 'Show task details', 'queue.d.live': 'Live', 'queue.d.ended': 'Ended',
    'queue.d.agent': 'Agent', 'queue.d.model': 'Model', 'queue.d.started': 'Started', 'queue.d.elapsed': 'Running for',
    'queue.d.took': 'Took', 'queue.d.endedAt': 'Finished', 'queue.d.resumes': 'Resumes', 'queue.d.attempts': 'Attempts',
    'queue.d.latest': 'Latest event', 'queue.d.id': 'Task ID', 'queue.d.summary': 'Closing report', 'queue.d.noSummary': 'No closing report was left',
  },
}

/**
 * Bind a dictionary to a lookup shaped exactly like the host's `t` seat, with
 * `{name}` interpolation. The host supplies the real one through the slot
 * registration (`locale: LOCALE_NS`); this factory exists so a render can be
 * exercised without a locale service — the same seam the tests use.
 */
export function createTranslator(dict: Record<string, string>): Translate {
  return (key, params) => {
    const template = dict[key]
    if (template === undefined) return key
    if (params === undefined) return template
    return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
      (Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : whole))
  }
}

/**
 * Window length in minutes → the label in the active locale, host string as
 * fallback. The structured fields are typed `| null` but read `== null`: a
 * host that predates them omits the key entirely, so the value that actually
 * arrives is `undefined`. Checking only for null rendered `NaN m` against a
 * previous-version host — the exact half-deployed case this fallback exists
 * for, caught by the projection test rather than in the browser.
 */
export function windowLabelOf(t: Translate, window: { label: string; durationMins?: number | null }): string {
  const mins = window.durationMins
  if (mins == null || mins <= 0) return window.label
  if (mins === 7 * 24 * 60) return t('balance.window.week')
  if (mins % 1440 === 0) return t('balance.window.days', { n: mins / 1440 })
  if (mins % 60 === 0) return t('balance.window.hours', { n: mins / 60 })
  return t('balance.window.minutes', { n: Math.round(mins) })
}

/** The reset instant → the stamp in the active locale, host string as fallback. */
export function resetStampOf(t: Translate, window: { resetAt: string; resetAtMs?: number | null }, now: number): string {
  const ms = window.resetAtMs
  if (ms == null) return window.resetAt
  const at = new Date(ms)
  const time = String(at.getHours()).padStart(2, '0') + ':' + String(at.getMinutes()).padStart(2, '0')
  // Calendar days apart, local midnight to local midnight — the same rule the
  // host's `formatReset` used, so the client and the fallback agree.
  const startOfDay = (d: Date): number => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((startOfDay(at) - startOfDay(new Date(now))) / 86400000)
  if (days === 0) return t('balance.reset.today', { time })
  if (days === 1) return t('balance.reset.tomorrow', { time })
  return t('balance.reset.dated', {
    date: (at.getMonth() + 1) + '/' + at.getDate(),
    weekday: t('time.weekday.' + at.getDay()),
    time,
  })
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

/** Every window of a snapshot, named and stamped for the active locale. */
export function windowsOf(t: Translate, result: BalanceResult, now: number): { label: string; percent: number | null; reset: string }[] {
  return (result.snapshot?.windows ?? []).map((w) => ({
    label: windowLabelOf(t, w),
    percent: w.percent,
    reset: resetStampOf(t, w, now),
  }))
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
    ? value.toLocaleString('en-US', { maximumFractionDigits: 0 })
    : value.toLocaleString('en-US', { maximumFractionDigits: 2 })
  return symbol + formatted
}

/** A fill price as written, or '—' when the ledger carried none (#1590). */
function fmtPrice(value: number | null, sym = ''): string {
  if (value === null || !isFinite(value)) return '—'
  return sym + value
}

/** Dashboard-parity percentage formatter (test seam). */
export function _fmtPct(value: number | null, digits = 2): string {
  if (value === null || !isFinite(value)) return '—'
  return (value >= 0 ? '+' : '') + value.toFixed(digits) + '%'
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
      h('div', { className: cx('v') }, (trace.t1.delta >= 0 ? '+' : '') + trace.t1.delta + '% · ' + verdictOf(t, trace.t1)))
    return h('div', { className: cx('dbody') },
      h('div', { className: cx('trhead') }, t('trace.titleNoPlan')),
      h('div', { className: cx('trace') },
        h('div', { className: cx('tnode', 'dec') },
          h('div', { className: cx('n') }, t('trace.planThen')),
          h('div', { className: cx('v'), style: { color: 'var(--cap)' } }, t('trace.noPlanRecord'))),
        h('div', { className: cx('tnode', 'follow') },
          h('div', { className: cx('tw') }, trace.date ?? ''),
          h('div', { className: cx('n') }, t('trace.realFill')),
          h('div', { className: cx('v') }, fillText)),
        t1miss),
      trace.note === null ? null : h('div', { className: cx('tnote') }, esc(trace.note)),
      h('div', { className: cx('tmiss') }, t('trace.unpaired')))
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
      (trace.t1.delta >= 0 ? '+' : '') + trace.t1.delta + '% · ' + verdictOf(t, trace.t1)))
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
    pnlText = _fmtPct(trace.holdPnl)
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
        h('div', { className: cx('n') }, t('trace.realFill')),
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
      h('span', { className: cx('pnlk') }, t('trace.holding')), _fmtPct(trace.holdPnl))
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
    const label = 'T+1 ' + (trace.t1.delta >= 0 ? '+' : '') + trace.t1.delta + '% ' + verdictOf(t, trace.t1)
    // data-tone carries the host's reading into the DOM: it is what the
    // regression spec reads, so hashed class names cannot hide a chip that
    // stopped following `t1.tone` (#713).
    t1tag = h('span', { className: cx('t1', tone), 'data-tone': tone }, label)
  } else {
    // Said out loud for every unjudged fill, not just sells: no canonical close
    // inside the T+1 window means there is no verdict, and silence there reads
    // like the fill was fine.
    t1tag = h('span', { className: cx('t1', 'flat'), 'data-tone': 'flat' }, t('trace.t1Pending'))
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

function relativeDay(iso: string, today: string, t: Translate): string {
  if (iso === today) return t('time.today')
  const at = (date: string): number => new Date(date + 'T00:00:00').getTime()
  const days = Math.round((at(today) - at(iso)) / 86400000)
  if (days === 1) return t('time.yesterday')
  if (days >= 2 && days <= 7) return t('time.daysAgo', { days })
  return t('time.date', { month: parseInt(iso.slice(5, 7)), day: parseInt(iso.slice(8, 10)) })
}

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
function renderRowDetail(row: {
  provider: string
  result: BalanceResult
  view: { tone: BalanceTone; value: string; title: string }
  note: string | null
}, t: Translate, now: number): React.ReactElement | null {
  const wins = row.result.snapshot === null ? [] : windowsOf(t, row.result, now)
  if (wins.length > 0) {
    // 每窗一行:文字读数 + 发丝进度条。percent 是已使用方向(kcn 定的口径),
    // 填充按用量档位走(kcn 配色,恢复):低=绿、≥60% 黄、≥80% 红,stale 黄
    // 盖过(数字不可信优先于用量档)。档位只染色——label/百分比/条/reset
    // 在任何档位都完整保留。静态渲染不做 width 动画,数据刷新整帧替换。
    return h('div', { className: cx('bp-wins') },
      wins.map((w) => {
        const pct = w.percent === null ? null : Math.max(0, Math.min(100, Math.round(w.percent)))
        const state = row.view.tone === 'stale' ? 'stale' : _usedLevel(pct, row.result.threshold)
        return h('div', { className: cx('bp-win'), key: w.label },
          h('div', { className: cx('bp-win-line') },
            h('span', { className: cx('bp-win-label') }, w.label),
            h('span', { className: cx('bp-win-pct') }, w.percent === null ? '—' : Math.round(w.percent) + '%'),
            h('span', { className: cx('bp-win-reset') }, w.reset === '' ? '' : '↻ ' + w.reset)),
          h('div', { className: cx('bp-win-bar') },
            h('div', {
              className: cx('bp-win-fill'),
              style: pct === null ? { width: '0%' } : { width: pct + '%' },
              'data-balance-state': state,
            })))
      }))
  }
  // 无窗的异常行(未配置/拉取失败)note 即全部内容,不再走正文重复一遍。
  if (row.note !== null) return null
  const title = row.view.title
  if (title === '') return null
  // Money rows: drop the leading 'API 余额' label — the row already says who.
  const prefix = t('balance.apiBalance') + ' · '
  const body = title.startsWith(prefix) ? title.slice(prefix.length) : title
  return h('div', { className: cx('bp-sub') }, body)
}

/** One provider row as the chip, the foot button and the panel render it. */
type BalanceRow = BalancesResult['providers'][number] & {
  view: ReturnType<typeof _rowDisplay>
  note: string | null
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
 */
function useProviderBalances(props: BalancesInjected & PropsStore<BalanceStore> & { t: Translate }, pollKey: string) {
  const mountedRef = useRef(true)
  // `error` is why the last fetch never answered (transport/RPC failure — a
  // provider's own failure arrives inside `result` as a stale/failed row).
  // Without it a cold panel whose fetch failed kept saying 正在读取 forever,
  // and a warm one silently kept its old numbers (#1553).
  const [data, setData] = useState<{ result: BalancesResult | null; loading: boolean; error: string | null }>(
    () => ({ result: props.cachedBalances(), loading: false, error: null }),
  )
  const selected = props.useStore((state) => state.selected)
  const select = (provider: string): void => { props.actions.select(provider) }
  const [flash, setFlash] = useState<'ok' | 'same' | null>(null)
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const runBalances = (force: boolean): void => {
    props.fetchBalances(force).then((result) => {
      if (!mountedRef.current) return
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
        if (mountedRef.current) setData((current) => ({ ...current, result, error: null }))
      })
    return () => {
      mountedRef.current = false
      if (unsubscribe !== null) unsubscribe()
      if (flashTimerRef.current !== null) clearTimeout(flashTimerRef.current)
    }
  }, [pollKey])

  useEffect(() => {
    const intervalMs = Math.max(60000, data.result?.refreshMs ?? 60000)
    const timer = setInterval(() => { runBalances(false) }, intervalMs)
    return () => clearInterval(timer)
  }, [data.result?.refreshMs, pollKey])

  const now = Date.now()
  const rows: BalanceRow[] = (data.result?.providers ?? []).map((provider) => ({
    ...provider,
    view: _rowDisplay(provider.result, props.t, now),
    note: _balanceNote(provider.result, props.t),
  }))
  // 胶囊只讲一个 provider:选中的优先,否则第一行(稳定的 deepseek-first 序)。
  const primary = rows.find((row) => row.provider === selected) ?? rows[0]
  const refresh = (): void => {
    setData((current) => ({ ...current, loading: true }))
    runBalances(true)
  }
  // What the trigger says before any provider row exists: loading, or the
  // fetch failed (the hollow stale badge, not the blank "nothing to judge").
  const failed = rows.length === 0 && data.error !== null && !data.loading
  const empty = failed
    ? { tone: 'stale' as BalanceTone, title: props.t('balance.readFailed', { message: data.error }) }
    : { tone: 'none' as BalanceTone, title: props.t('balance.loading') }
  return { data, rows, primary, select, flash, refresh, empty }
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
        h('span', { className: cx('bp-v', row.view.tone === 'low' ? 'bad' : ''), 'data-balance-state': row.view.tone }, row.view.value),
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
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
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

/** Foot-action id of the balance surface (a stable DOM contract for probes). */
export const BALANCE_PANEL = 'clawock-provider-balance'

/** The foot button's owner share plus its inject face. */
export type BalanceSidebarActionProps = BalancesInjected & PropsStore<BalanceStore> & {
  /** Sidebar column state: false is the 56px rail (dot only). */
  wide: boolean
  /** Dictionary seat from declaring `locale: LOCALE_NS` on the registration. */
  t: Translate
}

/** The prop contract both balance surfaces' popover panel renders (see `panelAttrs`). */
type PanelAttrs = {
  className: string
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

/** Fixed-position anchor for the popover: left edge of the row, just above it, and the room up to the viewport top. */
type PopoverAnchor = { left: number; bottom: number; room: number }

/** Gap the popover keeps from the viewport top, and the least room it is ever given. */
const POPOVER_TOP_GAP = 12
const POPOVER_MIN_ROOM = 240

/**
 * The foot popover's open state and anchor, shared by every foot row. While
 * open: re-anchor on resize, Escape closes, a pointerdown outside the root
 * closes (document/window exist only in the browser — tests have no DOM).
 * `back` lets a popover with a nested layer take Escape first: it returns
 * true when it closed that layer, and the popover stays open.
 */
function useFootPopover(back?: () => boolean) {
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<PopoverAnchor | null>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)
  // The listener is attached once per opening; the ref hands it this render's `back`.
  const backRef = useRef(back)
  backRef.current = back

  const place = (): void => {
    const root = rootRef.current
    if (root === null || typeof window === 'undefined') return
    const rect = root.getBoundingClientRect()
    setAnchor({
      left: rect.left,
      bottom: window.innerHeight - rect.top + 8,
      room: Math.max(POPOVER_MIN_ROOM, rect.top - 8 - POPOVER_TOP_GAP),
    })
  }

  useEffect(() => {
    if (!open || typeof document === 'undefined') return undefined
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      if (backRef.current?.() === true) return
      setOpen(false)
    }
    const onDown = (event: PointerEvent): void => {
      const root = rootRef.current
      if (root !== null && event.target instanceof Node && !root.contains(event.target)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    // Capture phase, unlike the host hook: the composer stops pointerdown from
    // bubbling, so a bubble listener never hears a tap on the input box.
    document.addEventListener('pointerdown', onDown, true)
    window.addEventListener('resize', place)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown, true)
      window.removeEventListener('resize', place)
    }
  }, [open])

  return { open, setOpen, anchor, place, rootRef }
}

/**
 * The sidebar-foot home of the balance chip: always mounted, independent of
 * any session. It headlines the same one provider (pinned or first row) with
 * the same dot/tier/stale colours and polls on the same cadence.
 *
 * The provider list opens as a trigger-owned popover, the interaction the
 * host's own foot occupant uses (ui-cordis `CordisPanel`): the row toggles it,
 * it is `position:fixed` above the row so the clipped sidebar column cannot
 * cut it, and only a pointerdown outside the row+popover root or Escape
 * dismisses it (ui-primitives `useDismissOnOutsidePointer`, heard in the
 * capture phase — see the effect). It used to select
 * a keyed `main` panel instead, which swapped the whole conversation column
 * for a mostly empty page — one click and the chat you were reading was gone
 * (and on a phone the panel opened squeezed beside the still-open drawer).
 * Pinning a row and the manual refresh happen inside the root, so they can
 * never close it.
 */
export function ProviderBalanceSidebarAction(props: BalanceSidebarActionProps): React.ReactElement {
  const t = props.t
  const state = useProviderBalances(props, BALANCE_PANEL)
  const { rows, primary } = state
  const { open, setOpen, anchor, place, rootRef } = useFootPopover()
  const instanceId = useId()

  const summary = primary !== undefined
    ? primary.label + ' · ' + primary.view.title + (rows.length > 1 ? t('balance.otherProviders') : '')
    : state.empty.title
  return h('div', { className: cx('pbc', 'pbf', !props.wide && 'rail'), ref: rootRef },
    h('button', {
      type: 'button',
      className: cx('bchip'),
      'data-balance-state': primary !== undefined ? primary.view.tone : state.empty.tone,
      'data-pb-provider': primary !== undefined ? primary.provider : '',
      'data-clawock-action': BALANCE_PANEL,
      'data-active': open ? '' : undefined,
      'aria-expanded': open,
      'aria-haspopup': 'dialog',
      'aria-label': t('balance.panelTitle'),
      title: summary,
      onClick: () => {
        // Anchor from the row's live rect at the moment it opens (the rail and
        // the wide column put it in different places).
        if (!open) place()
        setOpen(!open)
      },
    }, props.wide
      ? renderBalanceHeadline(primary, true, true, state.empty.tone, instanceId)
      : h('span', { className: cx('bal-lead'), 'data-balance-state': primary !== undefined ? primary.view.tone : state.empty.tone },
        renderBalanceGlyph(primary !== undefined ? primary.view.tone : state.empty.tone, 18, instanceId))),
    h('div', panelAttrs(open, t('balance.panelTitle'), {
      'data-clawock-popover': BALANCE_PANEL,
      ...(anchor === null ? {} : { style: { left: anchor.left + 'px', bottom: anchor.bottom + 'px' } }),
    }), renderBalancePanelBody(state, t)))
}

// ---------------------------------------------------------------------------
// Dispatch task queue: the foot row above the balance, same chip language.
// ---------------------------------------------------------------------------

/** Foot-action id of the task-queue surface (a stable DOM contract for probes). */
export const TASK_QUEUE_PANEL = 'clawock-task-queue'

/** What the task chip's `inject` factory hands the component. */
export interface TaskQueueInjected {
  /** The last answer this registration fetched, or null cold. */
  cachedTaskQueue: () => TaskQueueResult | null
  /** Read the queue; `force` bypasses the short host cache (the manual refresh). */
  fetchTaskQueue: (force: boolean) => Promise<TaskQueueResult>
}

export type TaskQueueSidebarActionProps = TaskQueueInjected & {
  /** Sidebar column state: false is the 56px rail (glyph only). */
  wide: boolean
  t: Translate
}

/** A live task queued for something another task holds (the backlog patrol yields to). */
const queuedFor = (task: DispatchTask): boolean =>
  task.waiting === 'lock' || task.waiting === 'slot' || task.waiting === 'memory'

function durationOf(t: Translate, ms: number): string {
  const mins = Math.max(0, Math.floor(ms / 60000))
  return mins < 60
    ? t('queue.duration.minutes', { m: mins })
    : t('queue.duration.hours', { h: Math.floor(mins / 60), m: mins % 60 })
}

function agoOf(t: Translate, ms: number): string {
  const mins = Math.max(0, Math.floor(ms / 60000))
  if (mins < 60) return t('queue.ago.minutes', { m: mins })
  if (mins < 48 * 60) return t('queue.ago.hours', { h: Math.floor(mins / 60) })
  return t('queue.ago.days', { d: Math.floor(mins / 1440) })
}

/** One live task's status phrase: what it holds or what it waits for. */
export function _taskStatus(task: DispatchTask, t: Translate, now: number = Date.now()): { tone: BalanceTone; text: string } {
  const at = (key: string, ms: number | null): string => ms === null
    ? t(key + 'NoTime')
    : t(key, { time: resetStampOf(t, { resetAt: '', resetAtMs: ms }, now) })
  switch (task.waiting) {
    case 'lock': return { tone: 'stale', text: t('queue.wait.lock', { agent: task.agent }) }
    case 'slot': return { tone: 'stale', text: t('queue.wait.slot') }
    case 'memory': return { tone: 'stale', text: t('queue.wait.memory') }
    case 'quota': return { tone: 'none', text: at('queue.wait.quota', task.wakeAtMs) }
    case 'retry': return { tone: 'none', text: at('queue.wait.retry', task.wakeAtMs) }
    default: break
  }
  return task.slot !== ''
    ? { tone: 'ok', text: t('queue.state.running', { slot: task.slot }) }
    : { tone: 'none', text: t('queue.state.starting') }
}

/** An ended task's status words: the runner's state, then the agent's own STATUS. */
function endedText(task: DispatchTask): string {
  return task.state + (task.outcome !== '' ? ' / ' + task.outcome : '')
}

/** An ended task's dot: done green, not-done amber, failed red, stopped grey. */
function endedTone(task: DispatchTask): BalanceTone {
  if (task.state === 'ok' && (task.outcome === 'DONE' || task.outcome === '')) return 'ok'
  if (task.state === 'failed') return 'low'
  if (task.state === 'ok' || task.state === 'partial' || task.state === 'unverified') return 'stale'
  return 'none'
}

function patrolPhraseOf(result: TaskQueueResult, t: Translate, now: number): string {
  const patrol = result.patrol
  if (patrol.phase === 'waiting' && patrol.untilMs !== null) {
    return t('queue.patrol.waitingUntil', { time: resetStampOf(t, { resetAt: '', resetAtMs: patrol.untilMs }, now) })
  }
  return t('queue.patrol.' + patrol.phase)
}

/** The chip's headline: dot tone, slots value, and the one-line "who waits" sub-reading. */
export function _queueHeadline(result: TaskQueueResult, t: Translate, now: number = Date.now()): { tone: BalanceTone; value: string; sub: string; busy: boolean; title: string } {
  const queued = result.active.filter(queuedFor).length
  const quota = result.active.filter((task) => task.waiting === 'quota').length
  // A retry back-off holds nothing either, but it is still a live task waiting (#1772).
  const retry = result.active.filter((task) => task.waiting === 'retry').length
  const parts = [
    queued > 0 ? t('queue.queued', { n: queued }) : null,
    quota > 0 ? t('queue.quotaWait', { n: quota }) : null,
    retry > 0 ? t('queue.retryWait', { n: retry }) : null,
    patrolPhraseOf(result, t, now),
  ].filter((part): part is string => part !== null)
  const value = t('queue.slots', { used: result.running, max: result.maxRunning })
  const tone: BalanceTone = result.status === 'stale' || result.status === 'failed'
    ? 'stale'
    : result.active.length > 0 ? 'ok' : 'none'
  const idle = result.active.length === 0 ? t('queue.idle') + ' · ' : ''
  return { tone, value, sub: parts.join(' · '), busy: queued > 0, title: t('queue.name') + ' · ' + value + ' · ' + idle + parts.join(' · ') }
}

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
    const timer = setInterval(() => { read(false) }, Math.max(5000, data.result?.refreshMs ?? 15000))
    return () => clearInterval(timer)
  }, [data.result?.refreshMs])
  const refresh = (): void => {
    setData((current) => ({ ...current, loading: true }))
    read(true)
  }
  return { data, refresh }
}

/** The foot glyph: three queue lines in the host's 16px icon geometry, badge notched like the gauge. */
function renderQueueGlyph(tone: BalanceTone, size: number, instanceId: string): React.ReactElement {
  const badge = tone === 'ok' || tone === 'low' || tone === 'stale'
  const notch = 'clawock-queue-notch-' + instanceId
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
      h('path', { d: 'M2.5 4H13.5M2.5 8H13.5M2.5 12H13.5', stroke: 'currentColor', strokeWidth: 1.25, strokeLinecap: 'round' })),
    renderFootStatusBadge(tone))
}

/** What a task row shows: status on the right of the name, facts left and numbers right below. */
type TaskRowView = { tone: BalanceTone; text: string; meta: string; num: string }

/**
 * One task: dot · name (ellipsis) · status, then agent/model under the name
 * and the numbers under the status, so every row lines up on the same three
 * columns. A click opens the task's detail layer over the list.
 */
function renderTaskRow(task: DispatchTask, view: TaskRowView, openDetail: (id: string) => void, t: Translate): React.ReactElement {
  return h('button', {
    type: 'button',
    key: task.id,
    className: cx('bp-row', 'tq-row'),
    'data-tq-task': task.id,
    'data-tq-waiting': task.waiting,
    'aria-label': [task.name, view.text, view.meta, view.num, t('queue.d.open')].join(' · '),
    title: task.name,
    onClick: () => { openDetail(task.id) },
  },
    h('span', { className: cx('bp-dot'), 'data-balance-state': view.tone }),
    h('span', { className: cx('tq-name') }, task.name),
    h('span', { className: cx('tq-v'), 'data-balance-state': view.tone }, view.text),
    h('span', { className: cx('tq-meta') }, view.meta),
    h('span', { className: cx('tq-num') }, view.num),
    h('span', { className: cx('tq-chev'), 'aria-hidden': 'true' }))
}

/** A section heading: title left, its count right-aligned. */
function renderQueueSection(key: string, title: string, count: string | null): React.ReactElement {
  return h('div', { className: cx('tq-sec'), key: key + '-head' },
    h('span', { className: cx('bp-title') }, title),
    count === null ? null : h('span', { className: cx('tq-count') }, count))
}

/** Patrol's dot: running green, giving way amber, otherwise quiet grey. */
function patrolTone(phase: string): BalanceTone {
  if (phase === 'running') return 'ok'
  if (phase === 'yielding') return 'stale'
  return 'none'
}

/**
 * The panel, in the order the questions come: who holds a run slot → who is
 * queued and for what (lock / slot / memory / quota with its wake time) →
 * what just ended → what patrol is doing and its last rounds.
 */
function renderQueuePanelBody(state: ReturnType<typeof useTaskQueue>, t: Translate, now: number, openDetail: (id: string) => void): Array<React.ReactElement | null> {
  const { data, refresh } = state
  const result = data.result
  const head = h('div', { className: cx('bp-head'), key: 'head' },
    h('span', { className: cx('bp-title') }, t('queue.panelHeading')),
    h('button', {
      type: 'button',
      className: cx('bal-rf', data.loading && 'spin'),
      'data-refresh': 'true',
      'aria-label': t('queue.refresh'),
      title: t('queue.refresh'),
      onClick: refresh,
    }, '↻'))
  if (result === null) {
    return [head, h('div', { className: cx('bp-empty'), key: 'empty', role: 'status' },
      data.error !== null ? t('queue.readFailed', { message: data.error }) : t('balance.reading'))]
  }
  const problem = data.error ?? (result.status === 'stale' || result.status === 'failed' ? result.message : null)
  const patrol = result.patrol
  const liveView = (task: DispatchTask): TaskRowView => ({
    ..._taskStatus(task, t, now),
    meta: t('queue.meta', { agent: task.agent, model: task.model || '—' }),
    num: t('queue.run', {
      attempts: task.attempts,
      elapsed: task.startedAtMs === null ? '—' : durationOf(t, now - task.startedAtMs),
    }),
  })
  const holding = result.active.filter((task) => task.slot !== '')
  const waiting = result.active.filter((task) => task.slot === '')
  const rows = (key: string, tasks: DispatchTask[], empty: string, view: (task: DispatchTask) => TaskRowView) => tasks.length === 0
    ? h('div', { className: cx('bp-sub', 'tq-empty'), key }, empty)
    : h('div', { className: cx('tq-rows'), key }, tasks.map((task) => renderTaskRow(task, view(task), openDetail, t)))
  // The head stays put; everything under it scrolls when the panel meets the viewport top.
  return [head, h('div', { className: cx('tq-scroll'), key: 'scroll' }, [
    problem !== null && problem !== ''
      ? h('div', { className: cx('bp-note', 'warn'), key: 'error', role: 'status' }, t('queue.staleWith', { message: problem }))
      : null,
    renderQueueSection('slots', t('queue.slotsHeading'), t('queue.slotsCount', { used: result.running, max: result.maxRunning })),
    rows('holding', holding, t('queue.noneRunning'), liveView),
    renderQueueSection('waiting', t('queue.waitHeading'), String(waiting.length)),
    rows('waiting', waiting, t('queue.noneWaiting'), liveView),
    result.recent.length === 0 ? null : renderQueueSection('recent', t('queue.recentHeading'), String(result.recent.length)),
    result.recent.length === 0 ? null : rows('recent', result.recent, '', (task) => ({
      tone: endedTone(task),
      text: endedText(task),
      meta: task.agent,
      num: task.updatedAtMs === null ? '—' : agoOf(t, now - task.updatedAtMs),
    })),
    renderQueueSection('patrol', t('queue.patrolHeading'), null),
    h('div', { className: cx('tq-patrol'), key: 'patrol', 'data-tq-patrol': patrol.phase },
      h('span', { className: cx('bp-dot'), 'data-balance-state': patrolTone(patrol.phase) }),
      h('span', { className: cx('tq-name') }, patrolPhraseOf(result, t, now)),
      patrol.round !== '' ? h('span', { className: cx('tq-meta'), title: patrol.round }, t('queue.patrolRound', { round: patrol.round })) : null,
      patrol.detail !== '' ? h('span', { className: cx('tq-meta', 'tq-wrap') }, patrol.detail) : null),
    patrol.rounds.length === 0 ? null : h('div', { className: cx('bp-sub', 'tq-caption'), key: 'rounds-head' }, t('queue.roundsHeading')),
    patrol.rounds.length === 0 ? null : h('div', { className: cx('tq-rounds'), key: 'rounds' },
      patrol.rounds.flatMap((round) => {
        const key = 'round-' + round.endedAt + round.round
        return [
          h('span', { className: cx('tq-round-id'), key: key + '-id' }, round.round),
          h('span', { className: cx('tq-round-axis'), key: key + '-axis' }, round.axis),
          h('span', { className: cx('tq-round-result'), key: key + '-result' }, round.result),
          h('span', { className: cx('tq-num'), key: key + '-took' }, round.seconds === null ? '—' : durationOf(t, round.seconds * 1000)),
        ]
      })),
  ])]
}

/** A task's current copy by id: live first, then recently ended (it may have just finished). */
function findTask(result: TaskQueueResult, id: string): { task: DispatchTask; live: boolean } | null {
  const live = result.active.find((task) => task.id === id)
  if (live !== undefined) return { task: live, live: true }
  const ended = result.recent.find((task) => task.id === id)
  return ended === undefined ? null : { task: ended, live: false }
}

/**
 * The detail layer one task row opens, laid over the list inside the same
 * popover: back · live/ended on top, then the name, its status in the row's
 * tone, a label/value grid (agent, model, when it started, how long, attempts,
 * what the runner last logged or when it ended) and, for an ended task, the
 * agent's closing report. The id sits last in mono — it is what the dispatch
 * commands take.
 */
function renderTaskDetail(
  found: { task: DispatchTask; live: boolean },
  t: Translate,
  now: number,
  back: () => void,
  backRef: { current: HTMLButtonElement | null },
): React.ReactElement {
  const { task, live } = found
  const status = live ? _taskStatus(task, t, now) : { tone: endedTone(task), text: endedText(task) }
  const stamp = (ms: number | null): string | null => ms === null ? null : resetStampOf(t, { resetAt: '', resetAtMs: ms }, now)
  const took = task.startedAtMs !== null && task.updatedAtMs !== null ? durationOf(t, task.updatedAtMs - task.startedAtMs) : null
  const fields: Array<[key: string, value: string | null, mono?: boolean]> = [
    ['queue.d.agent', task.agent || null],
    ['queue.d.model', task.model || null],
    ['queue.d.started', stamp(task.startedAtMs)],
    live
      ? ['queue.d.elapsed', task.startedAtMs === null ? null : durationOf(t, now - task.startedAtMs)]
      : ['queue.d.took', took],
    live ? ['queue.d.resumes', stamp(task.wakeAtMs)] : ['queue.d.endedAt', task.updatedAtMs === null ? null
      : stamp(task.updatedAtMs) + ' · ' + agoOf(t, now - task.updatedAtMs)],
    ['queue.d.attempts', String(task.attempts)],
    // Falsy checks: a host older than these fields sends none of them.
    live && task.lastEvent ? ['queue.d.latest', task.lastEvent + (task.lastEventAtMs == null ? '' : ' · ' + stamp(task.lastEventAtMs))] : ['', null],
    ['queue.d.id', task.id, true],
  ]
  return h('div', { className: cx('tq-detail'), 'data-tq-detail': task.id, role: 'group', 'aria-label': task.name },
    h('div', { className: cx('bp-head', 'tq-d-head') },
      h('button', {
        type: 'button',
        className: cx('tq-back'),
        'data-tq-back': 'true',
        'aria-label': t('queue.back'),
        title: t('queue.back'),
        ref: backRef,
        onClick: back,
      }, h('span', { className: cx('tq-back-chev'), 'aria-hidden': 'true' }), t('queue.panelHeading')),
      h('span', { className: cx('bp-title') }, t(live ? 'queue.d.live' : 'queue.d.ended'))),
    h('div', { className: cx('tq-scroll') },
      h('div', { className: cx('tq-d-title') },
        h('span', { className: cx('bp-dot'), 'data-balance-state': status.tone }),
        h('span', { className: cx('tq-d-name') }, task.name)),
      h('div', { className: cx('tq-d-status'), 'data-balance-state': status.tone }, status.text),
      h('div', { className: cx('tq-d-grid') },
        fields.filter(([, value]) => value !== null).flatMap(([key, value, mono]) => [
          h('span', { className: cx('tq-d-k'), key: key + '-k' }, t(key)),
          h('span', { className: cx('tq-d-v', mono === true && 'tq-mono'), key: key + '-v' }, value),
        ])),
      live ? null : h('div', { className: cx('bp-sub', 'tq-caption') }, t('queue.d.summary')),
      live ? null : task.summary
        ? h('div', { className: cx('tq-d-summary') }, task.summary)
        : h('div', { className: cx('bp-sub', 'tq-empty') }, t('queue.d.noSummary'))))
}

/**
 * The sidebar-foot task-queue row, directly above the balance row: live
 * dispatch tasks and what each waits for, recent endings, and whether patrol
 * is running, giving way or between rounds. Same foot geometry, tones, glyph
 * badge, popover and refresh button as the balance; renders nothing on a
 * host without the dispatcher (or before its first answer).
 */
export function TaskQueueSidebarAction(props: TaskQueueSidebarActionProps): React.ReactElement | null {
  const t = props.t
  const state = useTaskQueue(props)
  // Which task's detail layer is up (by id, so each poll shows its fresh copy).
  const [detailId, setDetailId] = useState<string | null>(null)
  // The last copy seen, so a task that ages out of both lists keeps its layer.
  const lastSeen = useRef<{ task: DispatchTask; live: boolean } | null>(null)
  const backRef = useRef<HTMLButtonElement | null>(null)
  const closeDetail = (): boolean => {
    if (detailId === null) return false
    const id = detailId
    setDetailId(null)
    // Hand focus back to the row that opened the layer (the list was inert).
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(() => {
        const row = rootRef.current?.querySelector<HTMLElement>('[data-tq-task="' + CSS.escape(id) + '"]')
        row?.focus({ preventScroll: false })
      })
    }
    return true
  }
  const { open, setOpen, anchor, place, rootRef } = useFootPopover(closeDetail)
  const instanceId = useId()
  // Reopening the popover always lands on the list.
  useEffect(() => { if (!open) setDetailId(null) }, [open])
  // Keyboard focus follows the layer: the row that opened it is now inert.
  useEffect(() => { if (detailId !== null) backRef.current?.focus({ preventScroll: true }) }, [detailId])
  const result = state.data.result
  if (result === null || !result.available) return null
  const now = Date.now()
  const headline = _queueHeadline(result, t, now)
  const found = detailId === null ? null : findTask(result, detailId) ?? (lastSeen.current?.task.id === detailId ? lastSeen.current : null)
  lastSeen.current = found
  return h('div', { className: cx('pbc', 'pbf', 'tqf', !props.wide && 'rail'), ref: rootRef },
    h('button', {
      type: 'button',
      className: cx('bchip'),
      'data-balance-state': headline.tone,
      'data-clawock-action': TASK_QUEUE_PANEL,
      'data-active': open ? '' : undefined,
      'aria-expanded': open,
      'aria-haspopup': 'dialog',
      'aria-label': t('queue.panelTitle'),
      title: headline.title,
      onClick: () => {
        if (!open) place()
        setOpen(!open)
      },
    }, props.wide
      ? h('span', { className: cx('bchip-item'), 'data-balance-state': headline.tone },
        h('span', { className: cx('bal-lead') }, renderQueueGlyph(headline.tone, 16, instanceId)),
        h('span', { className: cx('bchip-name') }, t('queue.name')),
        h('span', { className: cx('bchip-v'), 'data-used-level': headline.busy ? 'mid' : undefined }, headline.value),
        h('span', { className: cx('bchip-sub'), 'aria-hidden': 'true' }, headline.sub))
      : h('span', { className: cx('bal-lead'), 'data-balance-state': headline.tone },
        renderQueueGlyph(headline.tone, 18, instanceId))),
    h('div', panelAttrs(open, t('queue.panelTitle'), {
      'data-clawock-popover': TASK_QUEUE_PANEL,
      ...(anchor === null ? {} : {
        style: { left: anchor.left + 'px', bottom: anchor.bottom + 'px', maxHeight: anchor.room + 'px' },
      }),
    }),
    // While a task is open the list stays mounted but inert and out of the box (see .tq-list[inert]).
    h('div', { className: cx('tq-list'), key: 'list', inert: found !== null ? '' : undefined, 'aria-hidden': found !== null ? 'true' : undefined },
      renderQueuePanelBody(state, t, now, (id) => { setDetailId(id) })),
    found === null ? null : h('div', { className: cx('tq-layer'), key: 'detail' },
      renderTaskDetail(found, t, now, () => { closeDetail() }, backRef))))
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
        h('span', { className: cx('down') }, soldEarly), ' / ', h('span', { className: cx('up') }, soldRight))),
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
            t('trace.fillCount', { count: traces.length }) + (rate === null ? '' : ' · @' + rate))),
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
  }
  /** Injected host layout face; `selectPanel` exists only where `main` is keyed (DSH >= 0.1.5-rc.1). */
  layout?: LayoutProbe
  /** Service lookup; each call site narrows the face it asked for. */
  get: (name: string) => unknown
}

/** Remote face of the gateway: one async method per `@Remote`, ok/error wrapped. */
type StudioRemoteFace = Record<string, (...args: unknown[]) => Promise<unknown>>

/** `selectPanel` exists only where `main` is keyed (DSH >= 0.1.5-rc.1). */
type LayoutProbe = { selectPanel?: (panelId: string | null) => void }

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
  // The chip is app-level account chrome, not decision data, and belongs to
  // no session. On hosts with global panels (`ctx.layout.selectPanel`,
  // DSH >= 0.1.5-rc.1) it lives at the sidebar foot beside Settings
  // (`sidebar.footer.action`) with a trigger-owned popover; older hosts keep
  // it in the session header's utilities seat.
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
    // The dispatch queue sits directly above the balance: registered first and
    // ordered first; the foot's own row layout is turned into a column by the
    // stylesheet (see .tqf), so the two read as one stack.
    let cachedTaskQueue: TaskQueueResult | null = null
    ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
      name: 'sidebar.footer.action',
      id: 'dispatch-queue',
      order: -1,
      locale: LOCALE_NS,
      inject: (): TaskQueueInjected => ({
        cachedTaskQueue: () => cachedTaskQueue,
        fetchTaskQueue: async (force) => {
          cachedTaskQueue = await call<TaskQueueResult>('taskQueue', [force])
          return cachedTaskQueue
        },
      }),
    }, TaskQueueSidebarAction))
    ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
      name: 'sidebar.footer.action',
      id: 'provider-balance',
      store: balancesStore,
      locale: LOCALE_NS,
      inject: balancesInjected,
    }, ProviderBalanceSidebarAction))
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
