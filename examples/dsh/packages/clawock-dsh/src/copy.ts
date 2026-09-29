/**
 * The plugin's copy and the few formatters every surface shares: the zh/en
 * dictionaries, the translator, and how a quota window's length and reset
 * read in the active locale. No React and no DOM, so the browser panel and the
 * text rendering of the same panel (text.ts) say the same words.
 */
import type { BalanceResult } from './types.ts'

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

/** Every window of a snapshot, named and stamped for the active locale. */
export function windowsOf(t: Translate, result: BalanceResult, now: number): { label: string; percent: number | null; reset: string }[] {
  return (result.snapshot?.windows ?? []).map((w) => ({
    label: windowLabelOf(t, w),
    percent: w.percent,
    reset: resetStampOf(t, w, now),
  }))
}
