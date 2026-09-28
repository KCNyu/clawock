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
import { PROVIDER_JOIN, byAgentRank, sourceRank, type ProviderJoin } from './providers.ts'
import type { AgentQueue, BalanceResult, BalancesResult, DispatchTask, EnrichedTrade, PatrolRound, QueueActionResult, T1VerdictKind, TaskQueueResult, TraceDecision, TraceT1, TracesResult } from './types.ts'

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
    'driver.catalyst': '催化', 'driver.influencer': '影响力', 'driver.macro': '宏观', 'driver.peer': '同行',
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
    'trace.t1Tally': 'T+1 卖飞/卖对/持平 · 判出 {rated}/{sells} 笔卖出',
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
    'balance.noProviders': '没有可用的余额来源',
    'balance.otherProviders': '(点击查看其他服务)',
    'balance.unknownError': '未知错误',
    'balance.windowNote': '{label} 已用 {percent}%',
    'balance.windowNoteReset': '{label} 已用 {percent}%,{reset} 重置',
    'balance.window.week': '周', 'balance.window.days': '{n}天', 'balance.window.hours': '{n}h',
    'balance.window.minutes': '{n}m',
    'balance.reset.today': '今天 {time}', 'balance.reset.tomorrow': '明天 {time}',
    'balance.reset.dated': '{date} {weekday} {time}',
    'queue.name': '任务', 'queue.panelTitle': '派发任务队列', 'queue.panelHeading': '派发队列',
    'queue.refresh': '刷新任务队列', 'queue.running': '在跑 {n}', 'queue.slotsHeading': '运行槽 · 按 agent',
    'queue.lane': '{agent} {used}/{max}', 'queue.laneNoMax': '{agent} {used}',
    'queue.lanesTitle': '运行槽按 agent 分:每个 agent 只用自己的槽,互不挤占;排队看各自那一格',
    'queue.queued': '排队 {n}', 'queue.memoryWait': '等内存 {n}', 'queue.quotaWait': '等额度 {n}', 'queue.retryWait': '等重试 {n}', 'queue.idle': '没有在跑的任务',
    'queue.readFailed': '任务队列读取失败:{message}', 'queue.staleWith': '刷新失败,显示最近一次: {message}',
    'queue.state.running': '运行中', 'queue.state.runningSlot': '运行中 · 槽 {slot}',
    'queue.state.starting': '启动中',
    'queue.wait.lock': '等 {agent} 锁', 'queue.wait.slot': '等 {agent} 运行槽', 'queue.wait.memory': '等内存',
    'queue.wait.quota': '等额度 · {time} 续跑', 'queue.wait.quotaNoTime': '等额度',
    'queue.wait.retry': '重试等待 · {time}', 'queue.wait.retryNoTime': '重试等待',
    'queue.meta': '{agent} · {model}', 'queue.run': '已跑 {elapsed} · 第 {attempts} 次', 'queue.stalls': '卡死 {n}',
    'queue.waitHeading': '排队 / 等待', 'queue.noneRunning': '没有占用运行槽的任务', 'queue.noneWaiting': '没有排队或等待的任务',
    'queue.recentHeading': '最近结束',
    'queue.waited': '首次排队 {time}', 'queue.d.waited': '首次排队', 'queue.waitUnknown': '排队耗时未记录',
    'queue.execution.ok': '执行完成', 'queue.execution.failed': '执行失败', 'queue.execution.cancelled': '已取消',
    'queue.execution.timeout': '已超时', 'queue.execution.blocked': '执行受阻', 'queue.execution.quota': '额度中止',
    'queue.execution.queued': '未启动', 'queue.execution.unknown': '结果未明',
    'queue.report.DONE': '任务：完成', 'queue.report.claimedDone': '任务：自报完成', 'queue.report.PARTIAL': '任务：部分完成',
    'queue.report.BLOCKED': '任务：受阻', 'queue.report.unknown': '任务：未报告',
    'queue.statusLegend': '前项是 runner 对执行过程的判决；“任务”是模型最终报告。执行完成但任务部分完成或受阻，表示机器运行正常、工作尚未做完。',
    'queue.olderRounds': '更早的 {n} 轮', 'queue.supervisorLog': '监督器原始记录',
    'queue.patrol.waitSlot': '等空闲运行槽', 'queue.patrol.giveWay': '让手工任务先行',
    'queue.patrol.memory': '内存不足，暂缓', 'queue.patrol.memoryUnread': '读不到内存，暂缓', 'queue.patrol.otherReason': '让路（原因见原始记录）',
    'queue.patrol.wrapUp': '收尾后让路', 'queue.patrol.forTask': '等待中的任务 {id}',
    'queue.round.preempted': '让路取消', 'queue.round.yielded': '让路收尾', 'queue.round.name': '{round} · {axis}',
    'queue.chip.elapsed': '已跑 {time}', 'queue.chip.took': '用时 {time}', 'queue.chip.cost': '估算费用（按 API 价，非实际扣费）', 'queue.chip.unpriced': '未定价',
    'queue.patrolHeading': '巡检', 'queue.patrolRound': '当前轮次 {round}', 'queue.roundsHeading': '最近几轮',
    'queue.patrol.running': '巡检运行中', 'queue.patrol.yielding': '巡检让路中',
    'queue.patrol.waiting': '巡检等待下一轮', 'queue.patrol.waitingUntil': '巡检 {time} 开下一轮',
    'queue.patrol.stopped': '巡检已停', 'queue.patrol.unknown': '巡检状态未知',
    'queue.patrolState.running': '运行中', 'queue.patrolState.yielding': '让路中', 'queue.patrolState.waiting': '等下一轮',
    'queue.patrolState.waitingUntil': '{time} 开下一轮', 'queue.patrolState.stopped': '已停', 'queue.patrolState.unknown': '状态未知',
    'queue.duration.minutes': '{m} 分', 'queue.duration.hours': '{h} 小时 {m} 分',
    'queue.ago.now': '刚刚', 'queue.ago.minutes': '{m} 分钟前', 'queue.ago.hours': '{h} 小时前', 'queue.ago.days': '{d} 天前',
    'queue.wait.lockAt': '等 {agent} 锁 · 第 {n} 位', 'queue.state.cancelling': '取消中',
    'queue.attempt': '第 {n} 次', 'queue.slotCount': '槽 {used}/{max}',
    'queue.tag.running': '运行中', 'queue.tag.runningSlot': '运行 · 槽 {slot}', 'queue.tag.starting': '启动中', 'queue.tag.cancelling': '取消中',
    'queue.tag.queued': '排队', 'queue.tag.queuedAt': '排队 #{n}', 'queue.tag.slot': '等运行槽', 'queue.tag.memory': '等内存',
    'queue.tag.quota': '等额度', 'queue.tag.retry': '重试等待',
    'queue.fact.wakes': '{time} 续跑', 'queue.fact.startedAt': '{time} 开始', 'queue.fact.queuedAt': '{time} 起排队', 'queue.chip.waiting': '已等 {time}',
    'queue.fallback': 'fallback', 'queue.patrolTag': '巡检',
    'queue.noRunnerApi': '无 RUNNER_API 2：不在排队顺序里，不能调整顺序或模型',
    'queue.holderOther': '锁被 {id} 占着', 'queue.holderUnnamed': '锁被占着，但没有登记持有者（刚好在拿锁，或不是当前 runner 起的任务）',
    'queue.quotaHint': '额度用尽，{time} 恢复（{by} 触发）；其余任务等到那时再排',
    'queue.ops.missing': 'ops 入口不可用，操作已停用：{error}', 'queue.ops.skew': 'ops 入口与仓库不一致（主机 {host} / 仓库 {repo}），运行 ops/host/install_task_queue_ops.sh',
    'queue.ops.version': 'ops {v}', 'queue.ops.footer': 'ops {v} · runner api {runner}',
    'queue.ch.weixin': '微信', 'queue.ch.telegram': 'Telegram', 'queue.notify.sent': '{ch} 已送达', 'queue.notify.failed': '{ch} 失败', 'queue.notify.planned': '{ch} 结束时通知',
    'queue.d.place': '排队', 'queue.d.placeValue': '{agent} 队列第 {n} 位', 'queue.d.protected': '已等满公平窗口，不会被插队',
    'queue.d.priorityValue': '优先级 {n}', 'queue.d.queued': '开始排队', 'queue.d.notify': '通知', 'queue.d.notifyNone': '不通知',
    'queue.d.runner': 'Runner', 'queue.d.session': '会话', 'queue.d.fallbackFrom': '请求 {model}，已切换', 'queue.d.effortDefault': '默认',
    'queue.a.top': '置顶', 'queue.a.up': '上移', 'queue.a.upOf': '上移 {name}', 'queue.a.down': '下移', 'queue.a.model': '换模型',
    'queue.a.wrapup': '体面收尾', 'queue.a.wrapupTitle': '排队一条收尾指令：做完当前一步后提交已完成的部分并输出 STATUS',
    'queue.a.cancel': '取消', 'queue.a.cancelConfirm': '确认取消', 'queue.a.retry': '重试', 'queue.a.log': '日志', 'queue.a.save': '保存', 'queue.a.close': '关闭',
    'queue.a.modelHint': '下一次尝试生效；正在跑的这一步不受影响。',
    'queue.a.cancelQueued': '它还没开始：取消没有损失。再点一次确认。',
    'queue.a.cancelSleeping': '它在等额度/重试：取消后不再续跑，会话保留可 resume。再点一次确认。',
    'queue.a.cancelRunning': '它正在跑：本轮进度会丢；会话 {session} 可用 --resume 续。再点一次确认。',
    'queue.a.dismissConfirm': '保留原状', 'queue.a.reading': '读取中…',
    'queue.a.readFailed': '读取失败：{message}',
    'queue.r.failed': '没成功：{message}', 'queue.r.cancelledQueued': '已取消（尚未开始，无损失）',
    'queue.r.cancelledRunning': '已停止，本轮进度已丢；续跑：{resume}', 'queue.r.cancelledNoSession': '已停止（还没有会话可续）',
    'queue.r.priority': '现在排第 {n} 位（共 {total}）', 'queue.r.model': '下一次尝试：{model} · {effort}',
    'queue.r.retry': '已作为新任务续跑：{id}', 'queue.r.wrapup': '收尾指令已排队：当前一步结束后送达',
    'queue.back': '返回额度与队列', 'queue.d.open': '查看任务详情', 'queue.d.live': '进行中', 'queue.d.ended': '已结束',
    'queue.d.agent': 'Agent', 'queue.d.model': '模型', 'queue.d.started': '开始', 'queue.d.elapsed': '已运行',
    'queue.d.took': '用时', 'queue.d.endedAt': '结束', 'queue.d.resumes': '续跑', 'queue.d.attempts': '尝试次数',
    'queue.d.stalls': '判卡死', 'queue.d.stallsValue': '{n} 次(静默无进展,已自动重试)',
    'queue.d.latest': '最近事件', 'queue.d.id': '任务 ID', 'queue.d.summary': '结果摘要', 'queue.d.noSummary': '没有留下结果摘要',
    'panel.title': '额度 · 队列', 'panel.aria': '各 provider 的额度与派发队列', 'panel.refresh': '刷新额度与队列',
    'panel.plan.anthropic': 'Anthropic 订阅', 'panel.plan.chatgpt': 'ChatGPT 订阅', 'panel.plan.freePool': '无 provider · 免费池',
    'panel.plan.deepseek': '本机 API 账户', 'panel.plan.minimax': 'Token Plan · 源：OpenClaw 配置',
    'panel.pool': '池 {current} → 下一个 {next}', 'panel.poolOrder': '（表序）', 'panel.poolSize': '池内 {n} 个', 'panel.poolSwap': '{n} 个免费模型同档互替', 'panel.poolUnread': '池文件未读到（需 host 半边新版，重启 dsh 后可见）',
    'queue.verdict.done': '完成', 'queue.verdict.partial': '部分完成', 'queue.verdict.blocked': '受阻', 'queue.verdict.failed': '失败',
    'queue.verdict.timeout': '超时', 'queue.verdict.cancelled': '已取消', 'queue.verdict.quota': '额度中止', 'queue.verdict.noReport': '无报告',
    'queue.verdict.notStarted': '未启动', 'queue.verdict.unknown': '未明',
    'queue.fallbackMark': '回退', 'queue.fallbackTitle': '回退：请求的是 {requested}', 'queue.chip.free': '免费',
    'queue.notify.unknown': '{ch} 无回执',
    'queue.receiptLegend': '以 runner 写入 result.env 的回执为准（openclaw 发送成功/失败）；无回执 = 未知，不当作已送达',
    'panel.q.idle': '闲', 'panel.q.run': '运行 {n}', 'panel.q.queued': '排队 {n}', 'panel.q.quota': '等额度 {n}', 'panel.q.wait': '等待 {n}', 'panel.free': '免费',
    'panel.staleAt': '刷新失败（{message}），显示 {time} 的读数', 'panel.openGroup': '打开 {name} 的额度与队列',
    'panel.railTitle': '额度 · 队列：{summary}', 'panel.warn': '有窗口到阈值或有任务在睡额度',
    'panel.queueLoading': '正在读取派发队列…', 'panel.queueUnavailable': '此主机没有派发队列；额度仍可查看。',
    'panel.noSources': '没有可显示的额度或派发来源。',
    'queue.wait.quotaBoth': '等到 {time}（窗口 {reset} +{pad}m 缓冲）', 'queue.wait.quotaNoWindow': '等到 {time}（窗口重置时刻未读到）',
    'queue.d.cost': '花费', 'queue.d.costFree': '免费（opencode 免费池）',
    'queue.d.costUnpriced': '—（该模型没有价目，不估）', 'queue.d.costLive': '截至上一次尝试结束',
    'queue.d.tokens': 'Tokens',
    'queue.d.deadline': '截止',
    'queue.a.confirmLabel': '确认 {label}', 'queue.a.brief': '任务书', 'queue.a.briefTitle': '在右侧文件预览打开 prompt.md（只读）',
    'queue.a.deadline': '截止 +2h', 'queue.a.attempts': '重试 +1', 'queue.a.resumes': '续跑 +1',
    'queue.a.deadlineConfirm': '延长 deadline 2 小时：该任务占用队列的时间变长（上限：派发 + 72h）。{when} 再点一次确认。',
    'queue.a.attemptsConfirm': '多给一次失败/卡死重试：再失败会多跑一轮。{when} 再点一次确认。',
    'queue.a.resumesConfirm': '多给一次额度续跑：每次都会重放会话上下文，有成本（缓存读）。{when} 再点一次确认。',
    'queue.a.whenNow': '它在排队/等待：几秒内生效。', 'queue.a.whenNext': '它在跑：本次尝试的时限不变，下一次尝试起生效。',
    'queue.a.budgetOld': '这个任务的 runner 是 api {api}：deadline 与重试预算在启动时定死，改了不会生效（api 3 起的任务才支持）。',
    'queue.brief.heading': '任务书与追加', 'queue.brief.prompt': '任务书 prompt.md · {kb} KB', 'queue.brief.append': '追加 {stamp}',
    'queue.brief.delivered': '已投递', 'queue.brief.pending': '待投递', 'queue.brief.big': '原文 {kb} KB（预览里是完整文件；ops 读数已截断到 64 KB）',
    'queue.brief.noSession': '右侧预览要在会话里打开：先进入任意会话，再点一次。文件：{path}', 'queue.brief.noService': '这个 dsh 没有文件预览栏。文件：{path}',
    'queue.brief.noDir': '插件 host 半边是旧版，没有告诉任务目录在哪；重启 dsh 后才能打开任务书。',
    'queue.brief.failed': '预览打不开：{message}。文件：{path}', 'queue.brief.opened': '已在右侧预览打开 {file}',
    'queue.d.sec.run': '运行设置', 'queue.d.sec.allowance': '额度', 'queue.d.sec.time': '时间', 'queue.d.sec.usage': '用量',
    'queue.d.sec.end': '结束任务', 'queue.d.sec.again': '再跑一次', 'queue.d.sec.raw': '原始记录',
    'queue.d.region': '{name} 的详情', 'queue.a.viewGroup': '查看（只读）', 'queue.a.confirm': '确认',
    'queue.d.notRecorded': '未记录', 'queue.d.retries': '重试', 'queue.d.quotaResumes': '额度续跑', 'queue.d.usedOf': '已用 {used} / {max}',
    'queue.d.slotOf': '槽 {slot} / {max}', 'queue.d.slotValue': '槽 {slot}', 'queue.d.source': '额度来源', 'queue.d.windows': '窗口',
    'queue.d.pool': '免费池', 'queue.d.quotaOut': '额度用尽', 'queue.d.costFreeShort': '免费', 'queue.d.costEstimate': '按 API 价估算，非实际扣费',
    'queue.d.tokensTotal': '共 {total}', 'queue.d.tokensSplit': '输入 {in} · 缓存写 {w} · 缓存读 {r} · 输出 {out}',
    'queue.brief.needsHost': '追加列表要等插件 host 半边更新（需重启 dsh）；任务书本身可以打开。', 'queue.brief.none': '没有追加', 'queue.brief.readOnly': '只读：要改请用 dispatch.sh append（运行中加 --queue）',
    'queue.r.needsHost': '主机上的插件 host 半边是旧版，这个动作要重启 dsh 后才可用。',
  },
  en: {
    'action.buy': 'Buy', 'action.add': 'Add', 'action.trim': 'Trim', 'action.sell': 'Sell',
    'action.cut': 'Cut', 'action.hold': 'Hold', 'action.trim_on_rebound': 'Trim on rebound',
    'action.t_only': 'T+0 only', 'action.add_only_on_trigger': 'Add on trigger', 'action.reject': 'No add',
    'action.watch': 'Watch', 'action.abstain': 'Abstain',
    'driver.technical': 'Technical', 'driver.fundamental': 'Fundamental', 'driver.sentiment': 'Sentiment',
    'driver.mixed': 'Mixed', 'driver.risk_rule': 'Risk rule',
    'driver.catalyst': 'Catalyst', 'driver.influencer': 'Influencer', 'driver.macro': 'Macro', 'driver.peer': 'Peer',
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
    'trace.t1Tally': 'T+1 sold-early/sold-well/flat · {rated}/{sells} sells judged',
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
    'balance.noProviders': 'No balance source is available',
    'balance.otherProviders': '(click for other services)',
    'balance.unknownError': 'unknown error',
    'balance.windowNote': '{label} {percent}% used',
    'balance.windowNoteReset': '{label} {percent}% used, resets {reset}',
    'balance.window.week': 'week', 'balance.window.days': '{n}d', 'balance.window.hours': '{n}h',
    'balance.window.minutes': '{n}m',
    'balance.reset.today': 'today {time}', 'balance.reset.tomorrow': 'tomorrow {time}',
    'balance.reset.dated': '{date} {weekday} {time}',
    'queue.name': 'Tasks', 'queue.panelTitle': 'Dispatch task queue', 'queue.panelHeading': 'Dispatch queue',
    'queue.refresh': 'Refresh the task queue', 'queue.running': '{n} running', 'queue.slotsHeading': 'Run slots · per agent',
    'queue.lane': '{agent} {used}/{max}', 'queue.laneNoMax': '{agent} {used}',
    'queue.lanesTitle': 'Run slots are per agent: each agent only uses its own, so a queue is about that agent alone',
    'queue.queued': '{n} queued', 'queue.memoryWait': '{n} waiting on memory', 'queue.quotaWait': '{n} waiting on quota', 'queue.retryWait': '{n} waiting to retry', 'queue.idle': 'No task running',
    'queue.readFailed': 'Task queue read failed: {message}', 'queue.staleWith': 'Refresh failed, showing the last read: {message}',
    'queue.state.running': 'running', 'queue.state.runningSlot': 'running · slot {slot}',
    'queue.state.starting': 'starting',
    'queue.wait.lock': 'waiting for the {agent} lock', 'queue.wait.slot': 'waiting for a {agent} run slot', 'queue.wait.memory': 'waiting for memory',
    'queue.wait.quota': 'quota wait · resumes {time}', 'queue.wait.quotaNoTime': 'quota wait',
    'queue.wait.retry': 'retry wait · {time}', 'queue.wait.retryNoTime': 'retry wait',
    'queue.meta': '{agent} · {model}', 'queue.run': '{elapsed} · attempt {attempts}', 'queue.stalls': '{n} stalled',
    'queue.waitHeading': 'Queued / waiting', 'queue.noneRunning': 'No task holds a slot', 'queue.noneWaiting': 'Nothing queued or waiting',
    'queue.recentHeading': 'Recently ended',
    'queue.waited': 'first queue wait {time}', 'queue.d.waited': 'Queue wait', 'queue.waitUnknown': 'queue wait not recorded',
    'queue.execution.ok': 'Execution complete', 'queue.execution.failed': 'Execution failed', 'queue.execution.cancelled': 'Cancelled',
    'queue.execution.timeout': 'Timed out', 'queue.execution.blocked': 'Execution blocked', 'queue.execution.quota': 'Stopped on quota',
    'queue.execution.queued': 'Never started', 'queue.execution.unknown': 'Result unknown',
    'queue.report.DONE': 'Task: complete', 'queue.report.claimedDone': 'Task: reports complete', 'queue.report.PARTIAL': 'Task: partial',
    'queue.report.BLOCKED': 'Task: blocked', 'queue.report.unknown': 'Task: no report',
    'queue.statusLegend': 'The first status is the runner’s execution verdict. “Task” is the model’s final report. Execution can complete while the task remains partial or blocked.',
    'queue.olderRounds': '{n} earlier rounds', 'queue.supervisorLog': 'Raw supervisor log',
    'queue.patrol.waitSlot': 'Waiting for a free run slot', 'queue.patrol.giveWay': 'Giving way to manual tasks',
    'queue.patrol.memory': 'Low memory, deferred', 'queue.patrol.memoryUnread': 'Memory unreadable, deferred', 'queue.patrol.otherReason': 'Giving way (reason in the raw log)',
    'queue.patrol.wrapUp': 'Wrapping up to give way', 'queue.patrol.forTask': 'Waiting task {id}',
    'queue.round.preempted': 'Cancelled to give way', 'queue.round.yielded': 'Wrapped up to give way', 'queue.round.name': '{round} · {axis}',
    'queue.chip.elapsed': 'running {time}', 'queue.chip.took': 'took {time}', 'queue.chip.cost': 'Estimate at API prices, not a bill', 'queue.chip.unpriced': 'unpriced',
    'queue.patrolHeading': 'Patrol', 'queue.patrolRound': 'current round {round}', 'queue.roundsHeading': 'Recent rounds',
    'queue.patrol.running': 'patrol running', 'queue.patrol.yielding': 'patrol giving way',
    'queue.patrol.waiting': 'patrol between rounds', 'queue.patrol.waitingUntil': 'patrol next round {time}',
    'queue.patrol.stopped': 'patrol stopped', 'queue.patrol.unknown': 'patrol state unknown',
    'queue.patrolState.running': 'running', 'queue.patrolState.yielding': 'giving way', 'queue.patrolState.waiting': 'idle',
    'queue.patrolState.waitingUntil': 'next round {time}', 'queue.patrolState.stopped': 'stopped', 'queue.patrolState.unknown': 'state unknown',
    'queue.duration.minutes': '{m}m', 'queue.duration.hours': '{h}h {m}m',
    'queue.ago.now': 'just now', 'queue.ago.minutes': '{m}m ago', 'queue.ago.hours': '{h}h ago', 'queue.ago.days': '{d}d ago',
    'queue.wait.lockAt': 'waiting for the {agent} lock · #{n}', 'queue.state.cancelling': 'cancelling',
    'queue.attempt': 'attempt {n}', 'queue.slotCount': 'slot {used}/{max}',
    'queue.tag.running': 'running', 'queue.tag.runningSlot': 'running #{slot}', 'queue.tag.starting': 'starting', 'queue.tag.cancelling': 'cancelling',
    'queue.tag.queued': 'queued', 'queue.tag.queuedAt': 'queued #{n}', 'queue.tag.slot': 'slot wait', 'queue.tag.memory': 'memory wait',
    'queue.tag.quota': 'quota wait', 'queue.tag.retry': 'retry wait',
    'queue.fact.wakes': 'resumes {time}', 'queue.fact.startedAt': 'started {time}', 'queue.fact.queuedAt': 'queued since {time}', 'queue.chip.waiting': 'waiting {time}',
    'queue.fallback': 'fallback', 'queue.patrolTag': 'patrol',
    'queue.noRunnerApi': 'No RUNNER_API 2: not in the queue order; its order and model cannot change',
    'queue.holderOther': 'The lock is held by {id}', 'queue.holderUnnamed': 'The lock is held, but no holder is registered (one taking it right now, or a task the current runner did not start)',
    'queue.quotaHint': 'Quota is out until {time} ({by} hit it); the others wait for it',
    'queue.ops.missing': 'The ops entry is unavailable, actions are off: {error}', 'queue.ops.skew': 'The ops entry differs from the repository (host {host} / repo {repo}): run ops/host/install_task_queue_ops.sh',
    'queue.ops.version': 'ops {v}', 'queue.ops.footer': 'ops {v} · runner api {runner}',
    'queue.ch.weixin': 'WeChat', 'queue.ch.telegram': 'Telegram', 'queue.notify.sent': '{ch} delivered', 'queue.notify.failed': '{ch} failed', 'queue.notify.planned': '{ch} on finish',
    'queue.d.place': 'Queue', 'queue.d.placeValue': '#{n} in the {agent} queue', 'queue.d.protected': 'past the fair wait, cannot be overtaken',
    'queue.d.priorityValue': 'priority {n}', 'queue.d.queued': 'Queued', 'queue.d.notify': 'Notify', 'queue.d.notifyNone': 'none',
    'queue.d.runner': 'Runner', 'queue.d.session': 'Session', 'queue.d.fallbackFrom': 'asked for {model}, switched', 'queue.d.effortDefault': 'default',
    'queue.a.top': 'To top', 'queue.a.up': 'Move up', 'queue.a.upOf': 'Move {name} up', 'queue.a.down': 'Move down', 'queue.a.model': 'Model',
    'queue.a.wrapup': 'Wrap up', 'queue.a.wrapupTitle': 'Queue a wrap-up instruction: after the current step, land what is done and report STATUS',
    'queue.a.cancel': 'Cancel', 'queue.a.cancelConfirm': 'Confirm cancel', 'queue.a.retry': 'Retry', 'queue.a.log': 'Log', 'queue.a.save': 'Save', 'queue.a.close': 'Close',
    'queue.a.modelHint': 'Applies to the next attempt; the step running now keeps its model.',
    'queue.a.cancelQueued': 'It has not started: cancelling costs nothing. Tap again to confirm.',
    'queue.a.cancelSleeping': 'It waits for quota or a retry: it will not resume; the session stays resumable. Tap again to confirm.',
    'queue.a.cancelRunning': 'It is running: this step\'s progress is lost; session {session} can be resumed. Tap again to confirm.',
    'queue.a.dismissConfirm': 'Keep unchanged', 'queue.a.reading': 'Loading…',
    'queue.a.readFailed': 'Read failed: {message}',
    'queue.r.failed': 'Did not work: {message}', 'queue.r.cancelledQueued': 'Cancelled (had not started, nothing lost)',
    'queue.r.cancelledRunning': 'Stopped, this step\'s progress is lost; resume: {resume}', 'queue.r.cancelledNoSession': 'Stopped (no session yet)',
    'queue.r.priority': 'Now #{n} of {total}', 'queue.r.model': 'Next attempt: {model} · {effort}',
    'queue.r.retry': 'Continuing as a new task: {id}', 'queue.r.wrapup': 'Wrap-up queued: delivered when the current step ends',
    'queue.back': 'Back to quota and queue', 'queue.d.open': 'Show task details', 'queue.d.live': 'Live', 'queue.d.ended': 'Ended',
    'queue.d.agent': 'Agent', 'queue.d.model': 'Model', 'queue.d.started': 'Started', 'queue.d.elapsed': 'Running for',
    'queue.d.took': 'Took', 'queue.d.endedAt': 'Finished', 'queue.d.resumes': 'Wakes at', 'queue.d.attempts': 'Attempts',
    'queue.d.stalls': 'Stalled', 'queue.d.stallsValue': '{n} (silent with no progress, retried automatically)',
    'queue.d.latest': 'Latest event', 'queue.d.id': 'Task ID', 'queue.d.summary': 'Closing report', 'queue.d.noSummary': 'No closing report was left',
    'panel.title': 'Quota · queue', 'panel.aria': 'Each provider\'s quota and the dispatch queue', 'panel.refresh': 'Refresh quotas and the queue',
    'panel.plan.anthropic': 'Anthropic subscription', 'panel.plan.chatgpt': 'ChatGPT subscription', 'panel.plan.freePool': 'No provider · free pool',
    'panel.plan.deepseek': 'This host\'s API account', 'panel.plan.minimax': 'Token Plan · key from the OpenClaw config',
    'panel.pool': 'pool {current} → next {next}', 'panel.poolOrder': ' (file order)', 'panel.poolSize': '{n} in pool', 'panel.poolSwap': '{n} free models, each a stand-in for the next', 'panel.poolUnread': 'pool file not read (needs the newer host half, after a dsh restart)',
    'queue.verdict.done': 'done', 'queue.verdict.partial': 'partial', 'queue.verdict.blocked': 'blocked', 'queue.verdict.failed': 'failed',
    'queue.verdict.timeout': 'timed out', 'queue.verdict.cancelled': 'cancelled', 'queue.verdict.quota': 'quota stop', 'queue.verdict.noReport': 'no report',
    'queue.verdict.notStarted': 'not started', 'queue.verdict.unknown': 'unknown',
    'queue.fallbackMark': 'fallback', 'queue.fallbackTitle': 'fallback: {requested} was requested', 'queue.chip.free': 'free',
    'queue.notify.unknown': '{ch}: no receipt',
    'queue.receiptLegend': 'From the receipt the runner writes to result.env (openclaw send succeeded / failed); no receipt = unknown, never taken as delivered',
    'panel.q.idle': 'idle', 'panel.q.run': '{n} running', 'panel.q.queued': '{n} queued', 'panel.q.quota': '{n} on quota', 'panel.q.wait': '{n} waiting', 'panel.free': 'free',
    'panel.staleAt': 'Refresh failed ({message}); showing the reading of {time}', 'panel.openGroup': 'Open {name}\'s quota and queue',
    'panel.railTitle': 'Quota · queue: {summary}', 'panel.warn': 'a window is at its threshold or a task sleeps on quota',
    'panel.queueLoading': 'Reading the dispatch queue…', 'panel.queueUnavailable': 'This host has no dispatch queue; quotas are still available.',
    'panel.noSources': 'No quota or dispatch source is available.',
    'queue.wait.quotaBoth': 'until {time} (window {reset} + {pad}m margin)', 'queue.wait.quotaNoWindow': 'until {time} (window reset not read)',
    'queue.d.cost': 'Cost', 'queue.d.costFree': 'free (opencode free pool)',
    'queue.d.costUnpriced': '— (no price for this model, not estimated)', 'queue.d.costLive': 'as of the last finished attempt',
    'queue.d.tokens': 'Tokens',
    'queue.d.deadline': 'Deadline',
    'queue.a.confirmLabel': 'Confirm {label}', 'queue.a.brief': 'Brief', 'queue.a.briefTitle': 'Open prompt.md in the file preview (read-only)',
    'queue.a.deadline': 'Deadline +2h', 'queue.a.attempts': 'Retry +1', 'queue.a.resumes': 'Resume +1',
    'queue.a.deadlineConfirm': 'Two more hours: the task holds its place in the queue longer (ceiling: dispatch + 72h). {when} Tap again to confirm.',
    'queue.a.attemptsConfirm': 'One more retry after a failure or stall: another failure runs one more round. {when} Tap again to confirm.',
    'queue.a.resumesConfirm': 'One more quota resume: each replays the session\'s context, which costs cache reads. {when} Tap again to confirm.',
    'queue.a.whenNow': 'It is queued or waiting: applies within seconds.', 'queue.a.whenNext': 'It is running: this attempt keeps its time cap; applies from the next attempt.',
    'queue.a.budgetOld': 'This task\'s runner is api {api}: its deadline and retry budgets were fixed at start, a change would not apply (tasks from api 3 on accept it).',
    'queue.brief.heading': 'Brief and appends', 'queue.brief.prompt': 'Brief prompt.md · {kb} KB', 'queue.brief.append': 'Append {stamp}',
    'queue.brief.delivered': 'delivered', 'queue.brief.pending': 'pending', 'queue.brief.big': '{kb} KB (the preview shows the whole file; the ops read is capped at 64 KB)',
    'queue.brief.noSession': 'The preview opens inside a conversation: open any conversation, then tap again. File: {path}', 'queue.brief.noService': 'This dsh has no file preview. File: {path}',
    'queue.brief.noDir': 'The plugin\'s host half is older and does not say where task directories are: the brief opens after a dsh restart.',
    'queue.brief.failed': 'The preview did not open: {message}. File: {path}', 'queue.brief.opened': 'Opened {file} in the preview',
    'queue.d.sec.run': 'Run settings', 'queue.d.sec.allowance': 'Allowance', 'queue.d.sec.time': 'Timeline', 'queue.d.sec.usage': 'Usage',
    'queue.d.sec.end': 'End the task', 'queue.d.sec.again': 'Run again', 'queue.d.sec.raw': 'Raw record',
    'queue.d.region': 'Details of {name}', 'queue.a.viewGroup': 'View (read-only)', 'queue.a.confirm': 'Confirm',
    'queue.d.notRecorded': 'not recorded', 'queue.d.retries': 'Retries', 'queue.d.quotaResumes': 'Resumes', 'queue.d.usedOf': '{used} of {max} used',
    'queue.d.slotOf': 'slot {slot} of {max}', 'queue.d.slotValue': 'slot {slot}', 'queue.d.source': 'Paid by', 'queue.d.windows': 'Windows',
    'queue.d.pool': 'Free pool', 'queue.d.quotaOut': 'Out of quota', 'queue.d.costFreeShort': 'free', 'queue.d.costEstimate': 'estimated at API prices, not billed',
    'queue.d.tokensTotal': '{total} total', 'queue.d.tokensSplit': 'in {in} · cache write {w} · cache read {r} · out {out}',
    'queue.brief.needsHost': 'The appends list needs the updated host half (a dsh restart); the brief itself opens now.', 'queue.brief.none': 'No appends', 'queue.brief.readOnly': 'Read-only: change it with dispatch.sh append (--queue while it runs)',
    'queue.r.needsHost': 'The plugin\'s host half on this host is older: this action works after a dsh restart.',
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
    // Hidden tabs do not poll; on return the host's per-provider TTL decides whether a fetch
    // happens at all (non-forced), so coming back never refreshes every provider at once.
    const visible = (): boolean => typeof document === 'undefined' || document.visibilityState === 'visible'
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
    : { tone: 'none' as BalanceTone, title: props.t(data.result === null ? 'balance.loading' : 'balance.noProviders') }
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

// ---------------------------------------------------------------------------
// Dispatch task queue: the foot row above the balance, drawn like the host's
// own foot occupant (ui-cordis: a 42px badge row with a trailing count, a
// fixed menu-material panel with a 44px header and caption-sized groups).
// ---------------------------------------------------------------------------

/** What the task chip's `inject` factory hands the component. */
export interface TaskQueueInjected {
  /** The last answer this registration fetched, or null cold. */
  cachedTaskQueue: () => TaskQueueResult | null
  /** Read the queue; `force` bypasses the short host cache (the manual refresh). */
  fetchTaskQueue: (force: boolean) => Promise<TaskQueueResult>
  /**
   * One write (or on-demand read) through the host's versioned ops entry.
   * Optional: without it the panel is read-only.
   */
  runQueueAction?: (action: string, id: string, arg: string) => Promise<QueueActionResult>
}

/** A live task queued for something another task of its agent holds (the backlog patrol yields to). */
const queuedFor = (task: DispatchTask): boolean =>
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

type SlotLane = { agent: string; used: number; max: number | null; tone: BalanceTone }

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

function laneText(t: Translate, lane: SlotLane): string {
  return lane.max === null
    ? t('queue.laneNoMax', { agent: lane.agent, used: lane.used })
    : t('queue.lane', { agent: lane.agent, used: lane.used, max: lane.max })
}

function durationOf(t: Translate, ms: number): string {
  const mins = Math.max(0, Math.floor(ms / 60000))
  return mins < 60
    ? t('queue.duration.minutes', { m: mins })
    : t('queue.duration.hours', { h: Math.floor(mins / 60), m: mins % 60 })
}

function agoOf(t: Translate, ms: number): string {
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
function executionText(state: string, t: Translate): string {
  const key = ({ ok: 'ok', partial: 'ok', unverified: 'ok', failed: 'failed', cancelled: 'cancelled',
    timeout: 'timeout', blocked: 'blocked', quota: 'quota', queued: 'queued' } as Record<string, string>)[state] ?? 'unknown'
  return t('queue.execution.' + key)
}

function reportText(outcome: string, t: Translate, executionState = 'ok'): string {
  if (outcome === 'DONE' && !['ok', 'partial', 'unverified'].includes(executionState)) return t('queue.report.claimedDone')
  const key = ['DONE', 'PARTIAL', 'BLOCKED'].includes(outcome) ? outcome : 'unknown'
  return t('queue.report.' + key)
}

/**
 * An ended task's tone. Done is not blue (blue means running now) and not a
 * dot at all: ended rows speak in words. Not-done amber, failed red.
 */
function endedTone(task: DispatchTask): BalanceTone {
  if (task.state === 'failed' || task.state === 'timeout') return 'low'
  if (['partial', 'unverified', 'blocked', 'quota'].includes(task.state)
    || (task.state === 'ok' && task.outcome !== 'DONE') || task.outcome === 'BLOCKED') return 'stale'
  return 'none'
}

function patrolPhraseOf(result: TaskQueueResult, t: Translate, now: number): string {
  const patrol = result.patrol
  if (patrol.phase === 'waiting' && patrol.untilMs !== null) {
    return t('queue.patrol.waitingUntil', { time: resetStampOf(t, { resetAt: '', resetAtMs: patrol.untilMs }, now) })
  }
  return t('queue.patrol.' + patrol.phase)
}

/** The ops entry answered, and its installed copy is the repository's. '' when fine, else why not. */
function opsProblem(result: TaskQueueResult, t: Translate): string {
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

// ---- The four layers: executor, model, slot, notification ------------------

/** Executor names as their makers write them. */
const AGENT_LABELS: Record<string, string> = { claude: 'Claude Code', codex: 'Codex', opencode: 'OpenCode' }
export const _agentLabel = (agent: string): string => AGENT_LABELS[agent] ?? agent

/**
 * The executor layer: a 14px outline glyph in the host's icon stroke, one
 * shape per CLI. All three are plugin-drawn pictograms, not vendor marks:
 * Claude a spark, Codex a terminal prompt, OpenCode brackets. The Codex
 * prompt identifies the coding CLI without pretending a generic hexagon is
 * OpenAI artwork. Monochrome label ink keeps these separate from status.
 */
function renderAgentGlyph(agent: string, size = 14): React.ReactElement {
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
function modelLine(task: DispatchTask, _live: boolean): { model: string; effort: string; fallback: boolean } {
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

function notifyChannels(task: DispatchTask): string[] {
  return [...new Set([...(task.notify ?? []), ...(task.notified ?? []), ...(task.notifyFailed ?? [])])]
}

const RECEIPT_GLYPH: Record<ReceiptState, string> = {
  sent: 'M1.6 5.2L3.6 7.2L8.4 2.4', failed: 'M2.2 2.2L7.8 7.8M7.8 2.2L2.2 7.8',
  unknown: 'M3.3 3.4a1.7 1.7 0 1 1 2.3 1.6C5.1 5.2 5 5.5 5 6M5 8v.1', planned: 'M2.2 5H7.8',
}

function renderNotifyIcons(task: DispatchTask, t: Translate, live: boolean): React.ReactElement | null {
  const channels = notifyChannels(task)
  if (channels.length === 0) return null
  const said = channels.map((ch) => t('queue.notify.' + _notifyState(task, ch, live), { ch: t('queue.ch.' + ch) })).join(' · ')
  return h('span', { className: cx('tq-notify'), role: 'img', 'aria-label': said, title: said + ' — ' + t('queue.receiptLegend') },
    channels.map((ch) => {
      const state = _notifyState(task, ch, live)
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

type GlyphPart = { d: string; paint: 'fill' | 'stroke' }
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

function renderRoleGlyph(role: StateRole): React.ReactElement {
  return h('svg', { className: cx('tq-role-glyph'), width: 10, height: 10, viewBox: '0 0 10 10', 'aria-hidden': 'true' },
    STATE_ROLES[role].glyph.map((part, i) => part.paint === 'fill'
      ? h('path', { key: i, d: part.d, fill: 'currentColor' })
      : h('path', { key: i, d: part.d, stroke: 'currentColor', strokeWidth: 1.3, fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' })))
}

type SlotChip = { text: string; role: StateRole; title?: string }

/** THE chip: a row's one state, in its role (bed + glyph + word). */
function renderChip(chip: SlotChip, opts: { key?: string; slot?: string } = {}): React.ReactElement {
  return h('span', {
    className: cx('tq-chip'), key: opts.key ?? opts.slot ?? chip.text,
    'data-role': chip.role, 'data-bed': STATE_ROLES[chip.role].bed, 'data-tq-chip': opts.slot, title: chip.title ?? chip.text,
  }, renderRoleGlyph(chip.role), h('span', { className: cx('tq-chip-text') }, chip.text))
}

/** A BalanceTone (the dots, the rail badge) as the role it means. */
const TONE_ROLE: Record<BalanceTone, StateRole> = { ok: 'run', stale: 'wait', low: 'fail', none: 'off' }

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
export const FACT_ORDER = ['model', 'tries', 'receipt', 'when', 'took', 'cost'] as const
export type FactSlot = typeof FACT_ORDER[number]
export type RowKind = 'source' | 'head' | 'task' | 'ended' | 'round'
export const RESIDENT_CHIPS = 1

/** Each fact's one cell: its line and its track (styles.module.css places `[data-tq-fact=…]` accordingly). */
export const FACT_CELL: Record<FactSlot, { line: 2 | 3; track: 'main' | 'when' | 'took' | 'aside' }> = {
  model: { line: 2, track: 'main' },
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
  // A round uses the patrol section's glyph, just as an ended task carries its executor.
  round: { lead: true, value: false, facts: ['when', 'took'] },
}

/** A fact: its words, what a reader hears (the words with their unit), and a voice when it is a warning. */
type Fact = { text: string; said?: string; title?: string; voice?: 'warn' | 'quiet'; mark?: React.ReactElement | null; node?: React.ReactElement | null }

type RowView = {
  kind: RowKind
  key: string
  lead?: React.ReactElement | null
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

/** A row's cells in grid order, and the sentence it reads as. */
function rowCells(view: RowView): { cells: React.ReactElement[]; said: string } {
  const kind = ROW_KINDS[view.kind]
  const slots = FACT_ORDER.filter((slot) => kind.facts.includes(slot) && view.facts[slot] != null)
  const value = kind.value && view.value != null ? view.value : null
  const caption = (view.caption ?? []).filter((part) => part.text !== '')
  const cells = [
    h('span', { className: cx('tq-lead'), key: 'lead', 'aria-hidden': 'true' }, kind.lead ? view.lead ?? null : null),
    h('span', { className: cx('tq-name'), key: 'name' }, view.name),
    value === null ? null : h('span', {
      className: cx('tq-value'), key: 'value', 'data-balance-state': value.tone, 'data-used-level': value.level ?? undefined,
    }, value.text),
    view.state === null ? null : renderChip(view.state, { slot: 'status' }),
    ...slots.map((slot) => {
      const fact = view.facts[slot]!
      return h('span', {
        className: cx('tq-fact'), key: slot, 'data-tq-fact': slot, 'data-voice': fact.voice, title: fact.title ?? fact.said,
      }, fact.node ?? fact.text, fact.mark ?? null)
    }),
    caption.length === 0 ? null : h('span', { className: cx('tq-caption-line'), key: 'caption' },
      ...caption.map((part, i) => h('span', { key: i, 'data-voice': part.voice, title: part.title }, (i > 0 ? ' · ' : '') + part.text))),
  ].filter((cell): cell is React.ReactElement => cell !== null)
  const said = [view.name, value?.text, view.state?.title ?? view.state?.text, ...slots.map((slot) => view.facts[slot]!.said ?? view.facts[slot]!.text),
    ...caption.map((part) => part.text)]
    .filter((part) => part != null && part !== '').join(' · ')
  return { cells, said }
}

/**
 * One row of the panel on the grid above: a button when it opens the detail
 * layer, else a read-only group (a head is neither: its section is labelled).
 * `after` is a sibling beside the row (the move-up button, laid over the
 * empty lead track so the row keeps its full width) — never a button inside
 * a button.
 */
function renderRow(view: RowView, t: Translate, after: React.ReactElement | null = null): React.ReactElement {
  const { cells, said } = rowCells(view)
  const head = view.kind === 'source' || view.kind === 'head'
  const common = { className: cx('tq-row', view.open === undefined && 'tq-static'), 'data-tq-row': view.kind, ...(view.attrs ?? {}) }
  return h('div', { className: cx('tq-item'), key: view.key, 'data-tq-item': view.key },
    view.open === undefined
      ? h('div', head ? common : { ...common, role: 'group', 'aria-label': said }, ...cells)
      : h('button', { ...common, type: 'button', 'aria-label': said + ' · ' + t('queue.d.open'), title: said, onClick: view.open }, ...cells),
    after)
}

/** A clock for a fixed cell: "19:40" today, "10/4 19:40" another day. */
function clockOf(ms: number, now: number): string {
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
function modelFact(task: DispatchTask, live: boolean, t: Translate): Fact | null {
  const m = modelLine(task, live)
  if (m.model === '') return null
  const text = _modelView(m.model).label + (m.effort ? ' · ' + m.effort : '')
  const requested = task.modelRequested ?? ''
  return {
    text, title: m.model,
    said: text + (m.fallback ? ' · ' + t('queue.fallbackTitle', { requested: _modelView(requested).label }) : ''),
    mark: m.fallback ? h('span', {
      className: cx('tq-mark'), 'data-role': 'fallback', title: t('queue.fallbackTitle', { requested: _modelView(requested).label }),
    }, renderRoleGlyph('fallback'), t('queue.fallbackMark')) : null,
  }
}

/** The cost cell: the API-price estimate, 'free', or '—' when the model has no price row (title says which). */
function costFact(task: DispatchTask, t: Translate, live: boolean): Fact | null {
  const cost = _costOf(task)
  if (cost === null) return null
  const legend = t('queue.chip.cost') + (live ? ' · ' + t('queue.d.costLive') : '')
  return cost.kind === 'unpriced'
    ? { text: '—', said: t('queue.chip.unpriced'), title: t('queue.chip.unpriced') + ' · ' + legend, voice: 'quiet' }
    : { text: cost.kind === 'free' ? t('queue.chip.free') : cost.short, said: legend + ' ' + cost.short, title: legend }
}

/** A live task as a row: state chip; model, tries; when it wakes, how long, cost so far. */
function taskRow(task: DispatchTask, t: Translate, now: number, open: (id: string) => void,
  windows?: ReadonlyArray<{ resetAtMs?: number | null }>): RowView {
  const state = _taskState(task, t, now, windows)
  const since = task.queuedAtMs ?? task.startedAtMs
  const running = _slotOf(task) !== null
  const tries = [task.attempts > 1 ? t('queue.attempt', { n: task.attempts }) : null, task.stalls ? t('queue.stalls', { n: task.stalls }) : null]
    .filter((part): part is string => part !== null)
  return {
    kind: 'task',
    key: task.id,
    lead: renderAgentGlyph(task.agent, 12),
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
function endedRow(task: DispatchTask, t: Translate, now: number, open: (id: string) => void): RowView {
  const stamp = (ms: number): string => resetStampOf(t, { resetAt: '', resetAtMs: ms }, now)
  return {
    kind: 'ended',
    key: task.id,
    lead: renderAgentGlyph(task.agent, 12),
    name: task.name,
    state: _endedState(task.state, task.outcome, t),
    facts: {
      model: modelFact(task, false, t),
      receipt: notifyChannels(task).length === 0 ? null : { text: '', node: renderNotifyIcons(task, t, false),
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

/** A finished patrol round as a row (rounds.tsv: `[preempted:|yielded:]STATE[/OUTCOME]`). */
function roundRow(round: PatrolRound, t: Translate, now: number): RowView {
  const how = /^(preempted|yielded):/.exec(round.result)?.[1] ?? ''
  const [state = '', outcome = ''] = round.result.slice(how === '' ? 0 : how.length + 1).split('/')
  const ended = localStampMs(round.endedAt)
  return {
    kind: 'round',
    key: 'round-' + round.endedAt + round.round,
    lead: renderSectionGlyph('patrol'),
    name: round.axis === '' ? round.round : t('queue.round.name', { round: round.round, axis: round.axis }),
    state: how === 'preempted' ? { text: t('queue.round.preempted'), role: 'partial', title: round.result }
      : how === 'yielded' ? { text: t('queue.round.yielded'), role: 'off', title: round.result }
        : { ..._endedState(state, outcome, t), title: round.result },
    facts: {
      when: ended === null ? null : { text: agoOf(t, now - ended), title: t('queue.d.endedAt') + ' ' + round.endedAt },
      took: round.seconds === null ? null : { text: durationOf(t, round.seconds * 1000), said: t('queue.chip.took', { time: durationOf(t, round.seconds * 1000) }) },
    },
    attrs: { 'data-tq-round': round.round },
  }
}

/**
 * The one fold control both sections use: a native <details> whose summary is
 * a pill (hairline, chevron that turns, press and focus feedback, a 44px
 * target under a finger). Opening is immediate — no height animation.
 */
function renderFold(kind: string, label: string, children: Array<React.ReactElement | null>): React.ReactElement {
  return h('details', { className: cx('tq-fold'), key: 'fold-' + kind, 'data-tq-fold': kind },
    h('summary', { className: cx('tq-fold-summary') },
      h('svg', { className: cx('tq-fold-chev'), width: 12, height: 12, viewBox: '0 0 12 12', 'aria-hidden': 'true' },
        h('path', { d: 'M4.5 2.5L8 6L4.5 9.5', stroke: 'currentColor', strokeWidth: 1.4, fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' })),
      h('span', null, label)),
    h('div', { className: cx('tq-fold-body') }, ...children))
}

/**
 * What stays on screen and what folds — ONE rule for "recently ended" and
 * "patrol" (pinned by tests/decision_studio_plugin.spec.js):
 *
 *   resident = every record of distinct work, and the supervisor's live status;
 *   folded   = repetition of work already on screen (earlier rounds of the same
 *              patrol rotation) and the raw source of a line already rendered
 *              (the journal line behind the patrol status chips).
 *
 * Each ended task is distinct work, and the host already caps the list at
 * `taskQueueRecent`, so no ended task folds. Patrol rounds repeat one
 * rotation, so the newest round is resident and the earlier ones fold.
 */
const RESIDENT_ROUNDS = 1

/** A task the queue may reorder: waiting for the lock, current runner, not patrol, not protected. */
const reorderable = (task: DispatchTask): boolean =>
  task.waiting === 'lock' && !task.patrol && !task.protected && (task.runnerApi ?? 1) >= 2

type QueueUi = {
  open: (id: string) => void
  act: (action: string, task: DispatchTask, arg?: string) => void
  busy: string | null
  writable: boolean
}

/** Live tasks of one agent in the order they hold / will take its lock. */
function groupOrder(tasks: DispatchTask[], queue: AgentQueue | undefined): DispatchTask[] {
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
 * Brand marks the host itself ships, drawn in the glyph ink: DeepSeek's whale
 * is dsh's own logo (the same path its sidebar header draws), so the plugin
 * carries no artwork the host does not already show.
 */
const DEEPSEEK_WHALE = 'M22.9168 1.43018C22.6713 1.31018 22.5658 1.53918 22.4223 1.65519C22.3733 1.69269 22.3318 1.74169 22.2903 1.78669C21.9317 2.1697 21.5127 2.42121 20.9657 2.39121C20.1657 2.34621 19.4827 2.59771 18.8787 3.20973C18.7502 2.45521 18.3236 2.0047 17.6746 1.71569C17.3351 1.56568 16.9916 1.41518 16.7536 1.08867C16.5876 0.856163 16.5421 0.597155 16.4591 0.341647C16.4061 0.187643 16.3536 0.0301382 16.1761 0.00363739C15.9836 -0.0263635 15.9081 0.135141 15.8326 0.270145C15.5306 0.822162 15.4136 1.43018 15.4251 2.0462C15.4516 3.43174 16.0366 4.53527 17.1991 5.3203C17.3311 5.4103 17.3651 5.5003 17.3236 5.63181C17.2441 5.90231 17.1501 6.16482 17.0671 6.43533C17.0141 6.60784 16.9351 6.64584 16.7501 6.57033C16.1121 6.30383 15.5611 5.90931 15.074 5.4328C14.2475 4.63328 13.5 3.75075 12.568 3.05973C12.349 2.89822 12.13 2.74822 11.9034 2.60522C10.9524 1.68169 12.028 0.923165 12.277 0.833162C12.5375 0.739159 12.3675 0.41615 11.5259 0.42015C10.6844 0.42365 9.91439 0.705658 8.93286 1.08117C8.78935 1.13767 8.63835 1.17867 8.48384 1.21267C7.59332 1.04367 6.66829 1.00617 5.70226 1.11517C3.88321 1.31768 2.43016 2.1777 1.36213 3.64575C0.0790928 5.4103 -0.222916 7.41536 0.146595 9.50642C0.535106 11.7105 1.66014 13.535 3.38869 14.9616C5.18125 16.4406 7.24581 17.1657 9.60138 17.0266C11.0319 16.9441 12.6245 16.7526 14.421 15.2321C14.874 15.4576 15.3496 15.5476 16.1381 15.6151C16.7456 15.6716 17.3306 15.5851 17.7836 15.4911C18.4931 15.3411 18.4441 14.6841 18.1876 14.5636C16.1081 13.595 16.5646 13.9891 16.1496 13.67C17.2061 12.42 18.8202 10.1979 19.3182 7.17235C19.3672 6.83834 19.4297 6.36783 19.4222 6.09732C19.4182 5.93231 19.4562 5.86831 19.6447 5.84931C20.1657 5.78931 20.6712 5.64681 21.1357 5.3913C22.4833 4.65528 23.0268 3.44624 23.1548 1.9972C23.1738 1.77569 23.1508 1.54668 22.9168 1.43018ZM11.1749 14.4736C9.15936 12.889 8.18184 12.3675 7.77832 12.39C7.40081 12.4125 7.46881 12.8445 7.55182 13.126C7.63882 13.404 7.75182 13.5955 7.91033 13.8396C8.01983 14.0011 8.09533 14.2411 7.80083 14.4216C7.15181 14.8231 6.02327 14.2866 5.97027 14.2601C4.65673 13.4865 3.5587 12.4655 2.78467 11.069C2.03715 9.72493 1.60314 8.28289 1.53164 6.74384C1.51264 6.37233 1.62214 6.24082 1.99215 6.17332C2.47916 6.08332 2.98118 6.06432 3.46769 6.13582C5.52476 6.43633 7.27581 7.35586 8.74385 8.8129C9.58188 9.64243 10.2159 10.634 10.8689 11.6025C11.5634 12.631 12.3105 13.611 13.262 14.4146C13.598 14.6961 13.866 14.9101 14.1225 15.0681C13.349 15.1546 12.058 15.1731 11.1749 14.4746L11.1749 14.4736ZM12.141 8.25988C12.141 8.09488 12.273 7.96338 12.439 7.96338C12.4765 7.96338 12.5105 7.97088 12.541 7.98188C12.5825 7.99688 12.6205 8.01938 12.6505 8.05338C12.7035 8.10588 12.7335 8.18088 12.7335 8.25988C12.7335 8.42489 12.6015 8.55639 12.4355 8.55639C12.2695 8.55639 12.141 8.42489 12.141 8.25988ZM15.1415 9.79893C14.949 9.87793 14.7565 9.94544 14.5715 9.95294C14.2845 9.96794 13.9715 9.85143 13.8015 9.70893C13.5375 9.48742 13.3485 9.36342 13.2695 8.97691C13.2355 8.8119 13.2545 8.55639 13.2845 8.40989C13.3525 8.09438 13.277 7.89187 13.0545 7.70787C12.8735 7.55786 12.643 7.51636 12.39 7.51636C12.2955 7.51636 12.209 7.47486 12.1445 7.44136C12.039 7.38886 11.9519 7.25735 12.035 7.09585C12.0615 7.04335 12.19 6.91584 12.22 6.89334C12.5635 6.69784 12.9595 6.76184 13.326 6.90834C13.6655 7.04735 13.9225 7.30236 14.292 7.66287C14.6695 8.09838 14.7375 8.21838 14.9525 8.54539C15.1225 8.8009 15.277 9.06341 15.3831 9.36392C15.4471 9.55142 15.3641 9.70493 15.1415 9.79893Z'

/**
 * The provider identity layer for a row with no agent glyph: 14px, the
 * executor glyphs' ink. DeepSeek is its whale; the rest keep a letterform-free
 * outline — MiniMax a wave, anything else a plain ring.
 */
function renderSourceGlyph(source: PanelSource): React.ReactElement {
  if (source.agent !== null || source.join?.agent) return renderAgentGlyph(source.agent ?? source.join!.agent!)
  if (source.key === 'deepseek') {
    return h('svg', {
      className: cx('tq-agent-glyph'), width: 14, height: 14, viewBox: '0 -3.06 23.16 23.16', 'aria-hidden': 'true', 'data-pp-provider': source.key,
    }, h('path', { d: DEEPSEEK_WHALE, fill: 'currentColor' }))
  }
  const stroke = { stroke: 'currentColor', strokeWidth: 1.25, strokeLinecap: 'round', strokeLinejoin: 'round', fill: 'none' }
  const shape = source.join?.kind === 'windows'
    ? h('path', { ...stroke, d: 'M1.8 9.5L4 4.5L7 9.5L10 4.5L12.2 9.5' })
    : h('circle', { ...stroke, cx: 7, cy: 7, r: 5 })
  return h('svg', {
    className: cx('tq-agent-glyph'), width: 14, height: 14, viewBox: '0 0 14 14', 'aria-hidden': 'true', 'data-pp-provider': source.key,
  }, shape)
}

/**
 * A source's value column: the allowance headline (used % of the first
 * window, or the balance) and its tone; for the free pool, "free" — where
 * the rotation stands is a fact of its group. `reset` (the headline window's,
 * resetStampOf) is read out in the line's label; the clocks themselves are
 * drawn once, on the group's window bars.
 */
function sourceReading(source: PanelSource, row: BalanceRow | undefined, queue: TaskQueueResult | null, t: Translate): {
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

type PanelUi = DetailUi & {
  /** Rows by provider id with their display projection (the balance channel). */
  rows: Map<string, BalanceRow>
}

/** Section glyphs in the executor glyphs' 14px outline: a clock turning back (just ended), a shield (patrol). */
function renderSectionGlyph(kind: 'recent' | 'patrol', size = 14): React.ReactElement {
  const stroke = { stroke: 'currentColor', strokeWidth: 1.25, strokeLinecap: 'round', strokeLinejoin: 'round', fill: 'none' }
  return h('svg', { className: cx('tq-agent-glyph'), width: size, height: size, viewBox: '0 0 14 14', 'aria-hidden': 'true' },
    kind === 'recent'
      ? h('path', { ...stroke, d: 'M2.6 7.6A4.5 4.5 0 1 0 3.9 3.8M3.6 1.6V4.1H6.1M7 4.6V7.2L8.7 8.3' })
      : h('path', { ...stroke, d: 'M7 1.8L11.4 3.4V6.9C11.4 9.5 9.6 11.4 7 12.2C4.4 11.4 2.6 9.5 2.6 6.9V3.4ZM5 7L6.4 8.4L9.1 5.7' }))
}

/** The patrol phase's role: running blue, giving way amber (a wait), between rounds off, stopped red. */
const PATROL_ROLE: Record<string, StateRole> = { running: 'run', yielding: 'wait', waiting: 'off', stopped: 'fail', unknown: 'unknown' }

/** rounds.tsv's local "YYYY-MM-DD HH:MM:SS" as epoch ms, null when it is not one. */
function localStampMs(stamp: string): number | null {
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
function patrolCaption(result: TaskQueueResult, t: Translate, now: number): NonNullable<RowView['caption']> {
  const patrol = result.patrol
  const reason = _patrolReason(patrol.detail)
  const current = result.active.find((task) => task.id === patrol.round)
  const dispatched = /round (\S+) \(([^)]+)\)/.exec(patrol.detail)
  const axis = dispatched?.[2] ?? /^patrol-(.+)-\d{8}-\d{6}$/.exec(patrol.round)?.[1] ?? ''
  const out: NonNullable<RowView['caption']> = []
  if (patrol.phase === 'waiting' && patrol.untilMs !== null) {
    out.push({ text: t('queue.patrolState.waitingUntil', { time: resetStampOf(t, { resetAt: '', resetAtMs: patrol.untilMs }, now) }) })
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
    const m = current === undefined ? null : modelLine(current, true)
    if (dispatched || axis) out.push({ text: dispatched ? t('queue.round.name', { round: dispatched[1]!, axis }) : axis, title: patrol.round })
    if (current?.startedAtMs != null) out.push({ text: t('queue.chip.elapsed', { time: durationOf(t, now - current.startedAtMs) }) })
    if (m !== null && m.model !== '') out.push({ text: _modelView(m.model).label, title: m.model })
  }
  return out
}

/** A list of rows on the inset well: the one surface every task, ended task and round sits on. */
function renderWell(key: string, rows: Array<React.ReactElement | null>): React.ReactElement | null {
  const present = rows.filter((row): row is React.ReactElement => row !== null)
  return present.length === 0 ? null : h('div', { className: cx('tq-well'), key: 'well-' + key, 'data-tq-well': key }, ...present)
}

/**
 * Patrol: a section head (the phase as its state chip, the live status as its
 * caption), the newest round on the well, then — folded, by the one rule
 * above — the earlier rounds and the raw journal line.
 */
function renderPatrolSection(result: TaskQueueResult, t: Translate, now: number): React.ReactElement {
  const patrol = result.patrol
  const rounds = (patrol.rounds ?? []).map((round) => roundRow(round, t, now))
  return h('section', { className: cx('tq-group', 'tq-section'), key: 'patrol', 'data-tq-group': 'patrol' },
    renderRow({
      kind: 'head', key: 'head-patrol', lead: renderSectionGlyph('patrol'), name: t('queue.patrolHeading'),
      state: { text: t('queue.patrolState.' + patrol.phase), role: PATROL_ROLE[patrol.phase] ?? 'unknown', title: patrolPhraseOf(result, t, now) },
      facts: {},
      caption: patrolCaption(result, t, now),
      attrs: { 'data-tq-patrol': patrol.phase },
    }, t),
    renderWell('rounds', rounds.slice(0, RESIDENT_ROUNDS).map((round) => renderRow(round, t))),
    rounds.length <= RESIDENT_ROUNDS ? null
      : renderFold('rounds', t('queue.olderRounds', { n: rounds.length - RESIDENT_ROUNDS }), [renderWell('older', rounds.slice(RESIDENT_ROUNDS).map((round) => renderRow(round, t)))]),
    patrol.detail === '' ? null : renderFold('journal', t('queue.supervisorLog'),
      [h('div', { className: cx('tq-log'), key: 'log' }, patrol.detail)]))
}

/**
 * A source as a row: the sidebar's folded line and its group's head in the
 * panel are this one view (the same glyph, name and value in the same
 * columns), so the line a reader taps is the line the panel opens on. The
 * folded line adds the queue's one state chip (its tasks are not on screen);
 * the head adds its caption — the plan, the run slots, the pool — in words.
 */
function sourceView(source: PanelSource, row: BalanceRow | undefined, result: TaskQueueResult | null, t: Translate): RowView & { reading: ReturnType<typeof sourceReading>; queue: ReturnType<typeof _queueState> | null } {
  const reading = sourceReading(source, row, result, t)
  const queue = source.agent === null || result === null || !result.available ? null
    : _queueState(t, result.active.filter((task) => task.agent === source.agent))
  const lane = source.agent === null || result === null || !result.available ? undefined : _slotLanes(result).find((l) => l.agent === source.agent)
  const pool = source.join?.kind === 'pool' ? _poolPosition(result) : null
  const poolSize = result?.opencodePool?.length ?? 0
  return {
    kind: 'source',
    key: source.key,
    lead: renderSourceGlyph(source),
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

/**
 * One provider group of the open panel (2026-09-28, kcn: 「任务现在和 provider
 * 那个上下好像都不明显了」). Two levels, never mixed: the allowance is the
 * group's head on the panel itself (14px strong name and reading, the caption,
 * the window bars on the name's edge); the queue that allowance feeds is a
 * list on an inset well starting on that same edge, one step down in type
 * and in weight. A reader tells the two apart by surface and indent before
 * reading a word.
 */
function renderSourceGroup(source: PanelSource, result: TaskQueueResult | null, t: Translate, now: number, ui: PanelUi): React.ReactElement {
  const row = source.provider === null ? undefined : ui.rows.get(source.provider.provider)
  const agent = source.agent
  const tasks = agent === null || result === null ? [] : result.active.filter((task) => task.agent === agent)
  const queue = agent === null ? undefined : (result?.queues ?? []).find((q) => q.agent === agent)
  const notes: string[] = []
  if (queue?.held && tasks.every((task) => task.id !== queue.holder)) {
    notes.push(queue.holder !== '' ? t('queue.holderOther', { id: queue.holder }) : t('queue.holderUnnamed'))
  }
  if (queue?.quotaUntilMs) notes.push(t('queue.quotaHint', { time: resetStampOf(t, { resetAt: '', resetAtMs: queue.quotaUntilMs }, now), by: queue.quotaBy }))
  // Abnormal balance rows say so with the last good reading and when it was taken (① stale).
  const snapshotAt = row?.result.snapshot?.asOf ? Date.parse(row.result.snapshot.asOf) : NaN
  const balanceNote = row === undefined || row.note === null ? null
    : row.result.status === 'stale' && Number.isFinite(snapshotAt)
      ? t('panel.staleAt', { message: row.result.message ?? '—', time: resetStampOf(t, { resetAt: '', resetAtMs: snapshotAt }, now) })
      : row.note
  // The panel head drops the folded line's state chip: the tasks it counts are right below.
  const head = { ...sourceView(source, row, result, t), state: null }
  const detail = row === undefined ? null : renderRowDetail(row, t, now)
  return h('section', {
    className: cx('tq-group', 'pp-group'), key: 'g-' + source.key, 'data-pp-group': source.key, 'data-tq-group': agent ?? undefined,
    'aria-label': source.label, tabIndex: -1,
  },
    renderRow({ ...head, key: 'head-' + source.key, attrs: { 'data-pp-head': source.key } }, t),
    balanceNote === null && detail === null ? null
      : h('div', { className: cx('pp-allowance', 'tq-inset'), 'data-pb-provider': row!.provider, 'data-pb-role': 'panel', 'data-balance-state': row!.view.tone },
        balanceNote === null ? null : h('div', { className: cx('tq-sub', 'tq-wrap', 'bp-note', row!.view.tone === 'stale' ? 'warn' : 'bad') }, balanceNote),
        detail),
    ...notes.map((note, i) => h('div', { className: cx('tq-sub', 'tq-wrap', 'tq-note', 'tq-inset'), key: 'n' + i }, note)),
    renderWell(source.key, groupOrder(tasks, queue).map((task) => renderRow(taskRow(task, t, now, ui.open, ui.windowsOf(task.agent)), t,
      ui.writable && reorderable(task) && (task.position ?? 0) > 1 ? h('button', {
        type: 'button',
        className: cx('tq-icon-btn', 'tq-up'),
        'data-tq-up': task.id,
        disabled: ui.busy !== null,
        'aria-label': t('queue.a.upOf', { name: task.name }),
        title: t('queue.a.up'),
        onClick: () => { ui.act('priority', task, 'up') },
      }, h('svg', { width: 14, height: 14, viewBox: '0 0 14 14', 'aria-hidden': 'true' },
        h('path', { d: 'M7 11.5V2.5M3 6.5L7 2.5L11 6.5', stroke: 'currentColor', strokeWidth: 1.4, fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' }))) : null))))
}

/**
 * The open panel: title + one refresh for both halves, then a group per
 * source in _panelSources order, then what just ended, patrol, and the ops
 * entry's version. Each half keeps its own read: a failed balance read never
 * hides the queue, and a host without the dispatcher shows providers only.
 */
function renderProviderPanelBody(sources: PanelSource[], queueState: ReturnType<typeof useTaskQueue>, balanceState: ReturnType<typeof useProviderBalances>,
  t: Translate, now: number, ui: PanelUi, notice: { ok: boolean; text: string } | null): Array<React.ReactElement | null> {
  const result = queueState.data.result
  const loading = queueState.data.loading || balanceState.data.loading
  const head = h('div', { className: cx('tq-head'), key: 'head' },
    h('span', { className: cx('tq-title') }, t('panel.title')),
    h('button', {
      type: 'button',
      className: cx('tq-icon-btn', loading && 'spin'),
      'data-refresh': 'true',
      'aria-label': t('panel.refresh'),
      'aria-busy': loading ? 'true' : undefined,
      title: t('panel.refresh'),
      onClick: () => { queueState.refresh(); balanceState.refresh() },
    }, h('svg', { width: 14, height: 14, viewBox: '0 0 14 14', 'aria-hidden': 'true' },
      h('path', { d: 'M11.5 7A4.5 4.5 0 1 1 10 3.6M11.5 1.8V4.4H8.9', stroke: 'currentColor', strokeWidth: 1.3, fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' }))))
  const queueProblem = queueState.data.error ?? (result !== null && (result.status === 'stale' || result.status === 'failed') ? result.message : null)
  const balanceProblem = balanceState.data.error
  const dispatcher = result !== null && result.available
  const ops = dispatcher ? result!.ops : undefined
  const skew = dispatcher ? opsProblem(result!, t) : ''
  const patrol = dispatcher ? result!.patrol : null
  return [head, h('div', { className: cx('tq-scroll'), key: 'scroll' }, [
    notice === null ? null : h('div', { className: cx('tq-sub', 'tq-wrap', 'tq-note', notice.ok ? 'tq-ok' : 'tq-bad'), key: 'notice', role: 'status' }, notice.text),
    queueProblem !== null && queueProblem !== ''
      ? h('div', { className: cx('tq-sub', 'tq-wrap', 'tq-note', 'tq-bad'), key: 'qerr', role: 'status' },
        // 'failed' is a cold in-band failure: nothing was ever read, so there is no "last read" to show (#2053).
        t(result === null || result.status === 'failed' ? 'queue.readFailed' : 'queue.staleWith', { message: queueProblem })) : null,
    queueProblem === null && result === null
      ? h('div', { className: cx('tq-sub', 'tq-note'), key: 'qloading', role: 'status' }, t('panel.queueLoading')) : null,
    queueProblem === null && result !== null && !result.available
      ? h('div', { className: cx('tq-sub', 'tq-note'), key: 'qunavailable', role: 'status' }, t('panel.queueUnavailable')) : null,
    balanceProblem !== null
      ? h('div', { className: cx('tq-sub', 'tq-wrap', 'tq-note', 'tq-bad'), key: 'berr', role: 'status' },
        balanceState.rows.length === 0 ? t('balance.readFailed', { message: balanceProblem }) : t('balance.staleWith', { message: balanceProblem })) : null,
    sources.length === 0 && balanceProblem === null ? h('div', { className: cx('tq-sub', 'tq-empty'), key: 'empty', role: 'status' },
      balanceState.data.result === null ? t('balance.reading') : t('panel.noSources')) : null,
    ...sources.map((source) => renderSourceGroup(source, result, t, now, ui)),
    // Ended work, newest first across agents: every ended task is resident (see RESIDENT_ROUNDS).
    !dispatcher || result!.recent.length === 0 ? null : h('section', { className: cx('tq-group', 'tq-section'), key: 'recent', 'data-tq-group': 'recent' },
      renderRow({ kind: 'head', key: 'head-recent', lead: renderSectionGlyph('recent'), name: t('queue.recentHeading'), state: null, facts: {} }, t),
      renderWell('recent', result!.recent.map((task) => renderRow(endedRow(task, t, now, ui.open), t)))),
    patrol === null ? null : renderPatrolSection(result!, t, now),
    ops === undefined ? null : h('div', { className: cx('tq-sub', 'tq-foot', skew !== '' && 'tq-bad'), key: 'ops', 'data-tq-ops': ops.available ? ops.version : 'missing' },
      skew !== '' ? skew : t('queue.ops.footer', { v: ops.version, runner: ops.runnerApi })),
  ])]
}

/** A task's current copy by id: live first, then recently ended (it may have just finished). */
function findTask(result: TaskQueueResult, id: string): { task: DispatchTask; live: boolean } | null {
  const live = result.active.find((task) => task.id === id)
  if (live !== undefined) return { task: live, live: true }
  const ended = result.recent.find((task) => task.id === id)
  return ended === undefined ? null : { task: ended, live: false }
}

type ModelPicker = { models: string[]; efforts: Record<string, string[]>; flag: string; model: string; effort: string; allowed: boolean; reason: string }

/** What `brief <id>` answered, for the detail layer's list of files (null until asked). */
type BriefView = {
  id: string
  path: string
  bytes: number
  truncated: boolean
  appends: Array<{ file: string; path: string; stamp: string; delivered: boolean; bytes: number }>
  /** The host half predates `brief` (a dsh restart is pending): only prompt.md can be listed. */
  needsHost: boolean
}

/** The one door to dsh's own file preview (right sidebar), or why it cannot open (see apply). */
export type OpenFile = (path: string) => { ok: true } | { ok: false; reason: 'no-service' | 'no-session' | 'error'; message?: string }

type DetailUi = QueueUi & {
  confirm: string | null
  askConfirm: (key: string | null) => void
  picker: ModelPicker | null
  openPicker: (task: DispatchTask) => void
  setPicker: (picker: ModelPicker | null) => void
  log: string[] | null
  loadLog: (task: DispatchTask) => void
  brief: BriefView | null
  readPending: string | null
  openBrief: (task: DispatchTask) => void
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

/** `4200` → `4.2k`, `83123861` → `83.1M`: token counts read at a glance, exact value in the aria text. */
export function _fmtTokens(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1e6) return (n / 1e3).toFixed(n < 1e4 ? 1 : 0) + 'k'
  return (n / 1e6).toFixed(n < 1e7 ? 2 : 1) + 'M'
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
  }, key === 'brief' || key === 'log' ? renderViewGlyph(key) : null, h('span', null, label))
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
function renderTaskDetail(found: { task: DispatchTask; live: boolean }, t: Translate, now: number, back: () => void,
  backRef: { current: HTMLButtonElement | null }, ui: DetailUi, notice: { ok: boolean; text: string } | null): React.ReactElement {
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
      control: budget('deadline', t('queue.a.deadline'), '+2h', '+2h'),
      after: confirmNote('deadline', t('queue.a.deadlineConfirm', { when })),
    } : null,
    task.maxAttempts != null || budgets ? {
      key: 'retries', label: t('queue.d.retries'),
      value: task.maxAttempts == null ? t('queue.d.notRecorded') : t('queue.d.usedOf', { used: task.attempts, max: task.maxAttempts }),
      control: budget('attempts', t('queue.a.attempts'), '+1', String((task.maxAttempts ?? 3) + 1)),
      after: confirmNote('attempts', t('queue.a.attemptsConfirm', { when })),
    } : null,
    task.quotaResumes != null || budgets ? {
      key: 'resumes', label: t('queue.d.quotaResumes'),
      value: task.quotaResumes == null ? t('queue.d.notRecorded') : t('queue.d.usedOf', { used: task.quotaResumesUsed ?? 0, max: task.quotaResumes }),
      control: budget('resumes', t('queue.a.resumes'), '+1', String((task.quotaResumes ?? 3) + 1)),
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
  if (ui.writable) view.push(actionPill('log', ui.readPending === 'log' ? t('queue.a.reading') : t('queue.a.log'), () => { ui.loadLog(task) }, { disabled: reading }))
  const brief = ui.brief !== null && ui.brief.id === task.id ? ui.brief : null
  const kb = (bytes: number): string => (bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)

  // ---- raw: folded, the source lines the fields above were read from.
  const raw = renderFields([
    live && task.lastEvent ? { key: 'latest', label: t('queue.d.latest'), value: task.lastEvent + (task.lastEventAtMs == null ? '' : ' · ' + stamp(task.lastEventAtMs)), mono: true } : null,
    { key: 'runner', label: t('queue.d.runner'), value: live && (task.runnerApi ?? 2) < 2 ? t('queue.noRunnerApi') : task.runnerApi == null ? null : 'api ' + task.runnerApi,
      voice: live && (task.runnerApi ?? 2) < 2 ? 'warn' : undefined },
    { key: 'session', label: t('queue.d.session'), value: task.session || null, mono: true },
    { key: 'id', label: t('queue.d.id'), value: task.id, mono: true },
  ])

  const sections: Record<DetailSection, React.ReactElement | null> = {
    status: h('div', { className: cx('tq-d-sec', 'tq-d-hero'), key: 'status', 'data-tq-section': 'status' },
      h('span', { className: cx('tq-lead'), 'aria-hidden': 'true' }, renderAgentGlyph(task.agent)),
      h('span', { className: cx('tq-d-name'), role: 'heading', 'aria-level': 2 }, task.name),
      renderChip(chip, { slot: 'status' }),
      status.text === chip.text ? null : h('div', {
        className: cx('tq-d-status'), 'data-balance-state': status.tone, title: live ? undefined : t('queue.statusLegend'),
      }, status.text)),
    summary: live ? null : renderSection('summary', t('queue.d.summary'), [task.summary
      ? h('div', { className: cx('tq-d-summary'), key: 'summary' }, task.summary)
      : h('div', { className: cx('tq-empty'), key: 'summary' }, t('queue.d.noSummary'))]),
    view: renderSection('view', null, [
      h('div', { className: cx('tq-actions'), key: 'pills', role: 'group', 'aria-label': t('queue.a.viewGroup') }, ...view),
      brief === null ? null : h('div', { className: cx('tq-brief'), key: 'brief', 'data-tq-brief': task.id, role: 'group', 'aria-label': t('queue.brief.heading') },
        h('div', { className: cx('tq-caption') }, t('queue.brief.heading') + ' · ' + t('queue.brief.readOnly')),
        h('button', { type: 'button', className: cx('tq-file'), 'data-tq-file': brief.path, onClick: () => { ui.openPath(brief.path) } },
          h('span', { className: cx('tq-file-name') }, brief.needsHost ? 'prompt.md' : t('queue.brief.prompt', { kb: kb(brief.bytes) })),
          brief.truncated ? h('span', { className: cx('tq-tag') }, t('queue.brief.big', { kb: kb(brief.bytes) })) : null),
        brief.needsHost ? h('div', { className: cx('tq-note') }, t('queue.brief.needsHost'))
          : brief.appends.length === 0 ? h('div', { className: cx('tq-empty') }, t('queue.brief.none'))
            : brief.appends.map((a) => h('button', {
              type: 'button', key: a.file, className: cx('tq-file'), 'data-tq-file': a.path, onClick: () => { ui.openPath(a.path) },
            },
              h('span', { className: cx('tq-file-name') }, t('queue.brief.append', { stamp: a.stamp || a.file })),
              h('span', { className: cx('tq-tag'), 'data-tq-delivered': a.delivered ? 'true' : 'false' },
                t(a.delivered ? 'queue.brief.delivered' : 'queue.brief.pending'))))),
      // The log scrolls inside itself: focusable and named, so a keyboard and a screen reader can read it.
      ui.log === null ? null : h('pre', { className: cx('tq-log'), key: 'log', 'data-tq-log': task.id, tabIndex: 0, role: 'region', 'aria-label': t('queue.a.log') }, ui.log.join('\n')),
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
    h('div', { className: cx('tq-head', 'tq-d-head') },
      h('button', {
        type: 'button',
        className: cx('tq-back'),
        'data-tq-back': 'true',
        'aria-label': t('queue.back'),
        title: t('queue.back'),
        ref: backRef,
        onClick: back,
      }, h('span', { className: cx('tq-back-chev'), 'aria-hidden': 'true' }), t('panel.title')),
      h('span', { className: cx('tq-caption') }, t(live ? 'queue.d.live' : 'queue.d.ended'))),
    h('div', { className: cx('tq-scroll', 'tq-d-scroll'), role: 'region', 'aria-label': t('queue.d.region', { name: task.name }) },
      ...DETAIL_SECTIONS[live ? 'live' : 'ended'].map((id) => sections[id])),
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
const CONFIRM_MS = 5000

export type ProviderPanelProps = BalancesInjected & PropsStore<BalanceStore> & TaskQueueInjected & {
  /** Sidebar column state: false is the 56px rail (one glyph + a status badge). */
  wide: boolean
  t: Translate
  /** dsh's own file preview (see apply); absent in tests and on hosts without it. */
  openFile?: OpenFile
}

/**
 * The sidebar-foot provider panel (2026-09-27): the balance chip and the
 * dispatch queue as ONE cell, `provider-balance`. Folded, it is one line per
 * source — provider or agent name first, its reading and reset, then who
 * burns that allowance (the agent's queue) or where its key comes from. Any
 * line opens the panel on that source's group: the allowance (windows with
 * their resets, or money), then the queue that allowance feeds. The rail
 * keeps one glyph whose badge warns when a window is at its threshold or a
 * task sleeps on quota. Both halves keep their own read and cadence.
 */
export function ProviderPanelSidebarAction(props: ProviderPanelProps): React.ReactElement {
  const t = props.t
  const balanceState = useProviderBalances(props, BALANCE_PANEL)
  const queueState = useTaskQueue(props)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [picker, setPicker] = useState<ModelPicker | null>(null)
  const [log, setLog] = useState<string[] | null>(null)
  const [brief, setBrief] = useState<BriefView | null>(null)
  const [readPending, setReadPending] = useState<string | null>(null)
  const [focusKey, setFocusKey] = useState<string | null>(null)
  // Every detail request belongs to the task that was open when it began.
  // A late reply must never paint a different task's picker, log or brief.
  const detailRequest = useRef(0)
  const activeDetail = useRef<string | null>(null)
  useEffect(() => () => { detailRequest.current += 1; activeDetail.current = null }, [])
  const lastSeen = useRef<{ task: DispatchTask; live: boolean } | null>(null)
  const backRef = useRef<HTMLButtonElement | null>(null)
  // The control that opened the panel: focus returns to it when the panel closes.
  const openerRef = useRef<HTMLElement | null>(null)
  const closeDetail = (): boolean => {
    if (confirm !== null) { setConfirm(null); return true }
    if (detailId === null) return false
    const id = detailId
    detailRequest.current += 1
    activeDetail.current = null
    setDetailId(null)
    setPicker(null); setLog(null); setConfirm(null); setBrief(null); setReadPending(null)
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(() => {
        rootRef.current?.querySelector<HTMLElement>('[data-tq-task="' + CSS.escape(id) + '"]')?.focus({ preventScroll: false })
      })
    }
    return true
  }
  const { open, setOpen, anchor, place, rootRef } = useFootPopover(closeDetail)
  const instanceId = useId()
  useEffect(() => {
    if (open) return
    detailRequest.current += 1
    activeDetail.current = null
    setDetailId(null); setNotice(null); setConfirm(null); setBrief(null)
    setPicker(null); setLog(null); setReadPending(null)
    // Closed by Escape or an outside tap while focus was inside: hand it back to the opener
    // instead of letting it fall to <body>.
    if (typeof document !== 'undefined' && rootRef.current !== null && openerRef.current !== null
      && (document.activeElement === document.body || rootRef.current.contains(document.activeElement))) {
      openerRef.current.focus({ preventScroll: true })
    }
  }, [open])
  // Opening on a line lands on that source's group (and scrolls it into view).
  useEffect(() => {
    if (!open || focusKey === null || typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') return
    window.requestAnimationFrame(() => {
      rootRef.current?.querySelector<HTMLElement>('[data-pp-group="' + CSS.escape(focusKey) + '"]')?.focus({ preventScroll: false })
    })
  }, [open, focusKey])
  useEffect(() => { if (detailId !== null) backRef.current?.focus({ preventScroll: true }) }, [detailId])
  useEffect(() => {
    if (confirm === null) return undefined
    const timer = setTimeout(() => { setConfirm(null) }, CONFIRM_MS)
    return () => clearTimeout(timer)
  }, [confirm])
  const run = props.runQueueAction
  const needsHost = (result: QueueActionResult): boolean => !result.ok && /unknown action/.test(result.message)
  const act = (action: string, task: DispatchTask, arg = ''): void => {
    if (run === undefined || busy !== null) return
    setBusy(action + ':' + task.id)
    setNotice(null)
    run(action, task.id, arg).then((result) => {
      setBusy(null)
      setNotice({ ok: result.ok, text: needsHost(result) ? t('queue.r.needsHost') : _describeAction(result, t) })
      queueState.refresh()
    }, (err: unknown) => {
      setBusy(null)
      setNotice({ ok: false, text: t('queue.r.failed', { message: err instanceof Error ? err.message : String(err) }) })
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
    // When the ops entry cannot say where the brief is, the host half's own dispatch directory
    // does (`logDir`); a host half older than that field gets no guessed path (#2065).
    const logDir = queueState.data.result?.logDir
    const fallback = logDir ? logDir.replace(/\/+$/, '') + '/' + task.id + '/prompt.md' : null
    setConfirm(null)
    const noDir = (): void => { setNotice({ ok: false, text: t('queue.brief.noDir') }) }
    if (run === undefined) {
      if (fallback === null) { noDir(); return }
      setBrief({ id: task.id, path: fallback, bytes: 0, truncated: false, appends: [], needsHost: true }); openPath(fallback); return
    }
    const request = detailRequest.current
    setReadPending('brief')
    run('brief', task.id, '').then((result) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      type Answer = { path?: string; brief_bytes?: number; truncated?: boolean; appends?: BriefView['appends'] }
      let detail: Answer = {}
      try { detail = JSON.parse(result.detail || '{}') as Answer } catch { detail = {} }
      if (!result.ok && !needsHost(result)) {
        setNotice({ ok: false, text: t('queue.a.readFailed', { message: result.message }) })
        return
      }
      const path = (result.ok ? detail.path : undefined) ?? fallback
      if (path === null) { noDir(); return }
      const view: BriefView = result.ok
        ? { id: task.id, path, bytes: detail.brief_bytes ?? 0, truncated: detail.truncated === true, appends: detail.appends ?? [], needsHost: false }
        : { id: task.id, path, bytes: 0, truncated: false, appends: [], needsHost: true }
      setBrief(view)
      openPath(view.path)
    }, (err: unknown) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      setNotice({ ok: false, text: t('queue.a.readFailed', { message: err instanceof Error ? err.message : String(err) }) })
    })
  }
  const openPicker = (task: DispatchTask): void => {
    if (run === undefined) return
    setConfirm(null)
    const request = detailRequest.current
    setLog(null)
    setPicker(null)
    setReadPending('choices')
    run('choices', task.id, '').then((result) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      let detail: { models?: string[]; efforts?: Record<string, string[]>; effort_flag?: string; allowed?: boolean; reason?: string; requested?: { model?: string; effort?: string } } = {}
      try { detail = JSON.parse(result.detail || '{}') as typeof detail } catch { detail = {} }
      setPicker({
        models: detail.models ?? [], efforts: detail.efforts ?? {}, flag: detail.effort_flag ?? 'effort',
        model: detail.requested?.model ?? task.modelRequested ?? task.model, effort: detail.requested?.effort ?? '',
        allowed: result.ok && detail.allowed === true, reason: result.ok ? detail.reason ?? '' : result.message,
      })
    }, (err: unknown) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      setNotice({ ok: false, text: t('queue.a.readFailed', { message: err instanceof Error ? err.message : String(err) }) })
    })
  }
  const loadLog = (task: DispatchTask): void => {
    if (run === undefined) return
    setConfirm(null)
    const request = detailRequest.current
    setPicker(null)
    setReadPending('log')
    run('log', task.id, '').then((result) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      let lines: string[] = []
      try { lines = (JSON.parse(result.detail || '{}') as { lines?: string[] }).lines ?? [] } catch { lines = [] }
      setLog(result.ok ? lines : [result.message])
    }, (err: unknown) => {
      if (request !== detailRequest.current || activeDetail.current !== task.id) return
      setReadPending(null)
      setNotice({ ok: false, text: t('queue.a.readFailed', { message: err instanceof Error ? err.message : String(err) }) })
    })
  }

  const now = Date.now()
  const result = queueState.data.result
  const dispatcher = result !== null && result.available
  const rows = new Map(balanceState.rows.map((row) => [row.provider, row] as const))
  const sources = _panelSources(balanceState.data.result?.providers ?? [], result)
  const windowsOf = (agent: string): ReadonlyArray<{ resetAtMs?: number | null }> | undefined => {
    const join = PROVIDER_JOIN.find((j) => j.agent === agent)
    const row = join?.provider ? rows.get(join.provider) : undefined
    return row?.result.snapshot?.windows
  }
  const sourceOf = (agent: string): DetailSource => {
    const join = PROVIDER_JOIN.find((j) => j.agent === agent)
    const queue = (result?.queues ?? []).find((q) => q.agent === agent)
    return {
      plan: join?.plan ?? null,
      row: join?.provider ? rows.get(join.provider) : undefined,
      pool: join?.kind === 'pool' ? _poolPosition(result) : undefined,
      poolSize: join?.kind === 'pool' ? result?.opencodePool?.length ?? 0 : 0,
      lane: dispatcher ? _slotLanes(result!).find((l) => l.agent === agent) : undefined,
      quotaUntilMs: queue?.quotaUntilMs ?? null,
      quotaBy: queue?.quotaBy ?? '',
    }
  }
  const found = !dispatcher || detailId === null ? null : findTask(result!, detailId) ?? (lastSeen.current?.task.id === detailId ? lastSeen.current : null)
  lastSeen.current = found
  const writable = run !== undefined && dispatcher && result!.ops?.available === true
  const ui: PanelUi = {
    open: (id) => { detailRequest.current += 1; activeDetail.current = id; setDetailId(id); setNotice(null); setPicker(null); setLog(null); setConfirm(null); setBrief(null); setReadPending(null) },
    act, busy, writable, confirm, askConfirm: setConfirm, picker, openPicker, setPicker, log, loadLog,
    brief, readPending, openBrief, openPath, windowsOf, sourceOf, rows,
  }
  // One line per source (C1), on the row grid: glyph · name · value · the one state chip (sourceView).
  const lines = sources.map((source) => {
    const row = source.provider === null ? undefined : rows.get(source.provider.provider)
    const view = sourceView(source, row, result, t)
    return { source, view, reading: view.reading, text: view.queue?.text ?? '' }
  })
  // The rail badge: amber square when a window is at its threshold or a task sleeps on quota;
  // hollow ring when a read failed; nothing when there is nothing to act on (neutral).
  const warn = lines.some((line) => line.reading.tone === 'low' || line.reading.level === 'low')
    || (dispatcher && result!.active.some((task) => task.waiting === 'quota'))
  const failed = (queueState.data.error !== null && result === null) || (balanceState.data.error !== null && balanceState.rows.length === 0)
    || lines.some((line) => line.reading.tone === 'stale')
  const railTone: BalanceTone = warn ? 'low' : failed ? 'stale' : 'none'
  const summary = lines.map((line) => [line.source.label, line.reading.value, line.reading.reset ?? '', line.text]
    .filter((part) => part !== '').join(' ')).join(' · ')
  const toggle = (key: string | null, opener: HTMLElement | null): void => {
    openerRef.current = opener
    setFocusKey(key)
    if (!open) place()
    setOpen(!open)
  }
  return h('div', { className: cx('pbc', 'pbf', 'tqf', 'ppf', !props.wide && 'rail'), ref: rootRef, 'data-pp-warn': warn ? 'true' : undefined },
    props.wide
      ? h('div', { className: cx('pp-rows'), role: 'group', 'aria-label': t('panel.aria'), 'data-clawock-action': BALANCE_PANEL },
        lines.length === 0
          ? h('button', {
            type: 'button', className: cx('pp-row', 'pp-empty'), 'data-pp-row': '', 'aria-expanded': open, 'aria-haspopup': 'dialog',
            'data-active': open ? '' : undefined,
            onClick: (event: { currentTarget: HTMLElement }) => { toggle(null, event.currentTarget) },
          }, h('span', { className: cx('pp-name') }, t('panel.title')), h('span', { className: cx('tq-sub', 'pp-last') }, balanceState.empty.title))
          : lines.map(({ source, view, reading, text }) => h('button', {
            type: 'button',
            key: source.key,
            className: cx('pp-row'),
            'data-tq-row': 'source',
            'data-pp-row': source.key,
            'data-pb-provider': source.provider?.provider,
            'data-pb-role': source.provider === null ? undefined : 'chip',
            'data-balance-state': reading.tone,
            'data-active': open && focusKey === source.key ? '' : undefined,
            'aria-expanded': open,
            'aria-haspopup': 'dialog',
            'aria-label': [source.label, reading.value, reading.reset ?? '', text, t('panel.openGroup', { name: source.label })]
              .filter((part) => part !== '').join(' · '),
            title: reading.title,
            onClick: (event: { currentTarget: HTMLElement }) => { toggle(source.key, event.currentTarget) },
          }, ...rowCells({ ...view, caption: [] }).cells)))
      : h('button', {
        type: 'button',
        className: cx('bchip', 'pp-rail'),
        'data-clawock-action': BALANCE_PANEL,
        'data-balance-state': railTone,
        'data-active': open ? '' : undefined,
        'aria-expanded': open,
        'aria-haspopup': 'dialog',
        'aria-label': t('panel.railTitle', { summary: (warn ? t('panel.warn') + ' · ' : '') + summary }),
        title: t('panel.railTitle', { summary }),
        onClick: (event: { currentTarget: HTMLElement }) => { toggle(null, event.currentTarget) },
      }, h('span', { className: cx('bal-lead'), 'data-balance-state': railTone }, renderBalanceGlyph(railTone, 18, instanceId))),
    h('div', panelAttrs(open, t('panel.aria'), {
      'data-clawock-popover': BALANCE_PANEL,
      ...(anchor === null ? {} : { style: { left: anchor.left + 'px', bottom: anchor.bottom + 'px', maxHeight: anchor.room + 'px' } }),
    }),
    h('div', { className: cx('tq-list'), key: 'list', inert: found !== null ? '' : undefined, 'aria-hidden': found !== null ? 'true' : undefined },
      renderProviderPanelBody(sources, queueState, balanceState, t, now, ui, found === null ? notice : null)),
    found === null ? null : h('div', { className: cx('tq-layer'), key: 'detail' },
      renderTaskDetail(found, t, now, () => { closeDetail() }, backRef, ui, notice))))
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
    // One foot cell, `provider-balance` (2026-09-27): the balance and the dispatch queue it pays for.
    // `dispatch-queue` is retired; both reads keep their own cadence inside the cell.
    let cachedTaskQueue: TaskQueueResult | null = null
    // dsh's own file preview (the right sidebar). Looked up at click time — long after apply, so the
    // service exists when there is one — and never injected: a host without it keeps the panel.
    const openFile: OpenFile = (path) => {
      const sidebar = ctx.get('sidebarRight') as { openResource?: (address: string, options?: unknown) => void; mounted?: { getSnapshot(): unknown } } | undefined
      if (sidebar === undefined || typeof sidebar.openResource !== 'function') return { ok: false, reason: 'no-service' }
      // Global panels (settings, …) have no right sidebar: it opens inside a conversation only.
      const session = sidebar.mounted?.getSnapshot()
      if (typeof session !== 'string' || session === '') return { ok: false, reason: 'no-session' }
      try {
        sidebar.openResource(_sessionFileAddress(session, path))
        return { ok: true }
      } catch (err) {
        return { ok: false, reason: 'error', message: err instanceof Error ? err.message : String(err) }
      }
    }
    ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
      name: 'sidebar.footer.action',
      id: 'provider-balance',
      store: balancesStore,
      locale: LOCALE_NS,
      inject: (): BalancesInjected & TaskQueueInjected & { openFile: OpenFile } => ({
        ...balancesInjected(),
        cachedTaskQueue: () => cachedTaskQueue,
        fetchTaskQueue: async (force) => {
          cachedTaskQueue = await call<TaskQueueResult>('taskQueue', [force])
          return cachedTaskQueue
        },
        // A host installed before queueAction existed has no such method: stay read-only.
        runQueueAction: typeof studioRemote.queueAction === 'function'
          ? (action, id, arg) => call<QueueActionResult>('queueAction', [action, id, arg])
          : undefined,
        openFile,
      }),
    }, ProviderPanelSidebarAction))
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
