import { n as taskQueueConfig, t as createBalanceReader } from "./desk.js";
import { createTaskQueueService } from "./taskqueue.js";
import { join } from "node:path";
import { homedir } from "node:os";
//#region src/copy.ts
/**
* This plugin's copy, in the locales the browser client ships (`zh`, `en` —
* `dsh-client-locale`'s LOCALE_IDS). Keys are grouped by surface; the two
* dictionaries must carry the same key set, which `tests/decision_studio_plugin.spec.js`
* enforces so a missing translation cannot ship.
*/
const dictionaries = {
	zh: {
		"action.buy": "买入",
		"action.add": "加仓",
		"action.trim": "减仓",
		"action.sell": "卖出",
		"action.cut": "割肉",
		"action.hold": "持有",
		"action.trim_on_rebound": "反弹减仓",
		"action.t_only": "仅T+0",
		"action.add_only_on_trigger": "触发加仓",
		"action.reject": "不加",
		"action.watch": "观望",
		"action.abstain": "弃权",
		"driver.technical": "技术面",
		"driver.fundamental": "基本面",
		"driver.sentiment": "情绪面",
		"driver.mixed": "混合",
		"driver.risk_rule": "风控规则",
		"driver.catalyst": "催化",
		"driver.influencer": "影响力",
		"driver.macro": "宏观",
		"driver.peer": "同行",
		"exe.followed": "遵守了计划",
		"exe.not_followed": "没按计划",
		"exe.unknown": "未标注",
		"align.same": "与计划同向",
		"align.opposite": "与计划反向",
		"align.other": "计划未指向买卖",
		"emo.fomo": "追高冲动",
		"emo.revenge": "报复性",
		"emo.averaging_down": "摊薄冲动",
		"emo.fear": "恐慌",
		"emo.euphoria": "亢奋",
		"emo.calm": "平静",
		"emo.mixed": "混合",
		"filter.all": "全部",
		"filter.miss": "无当日计划",
		"filter.sold": "卖出复盘",
		"filter.dec": "有当日计划",
		"t1.up": "涨",
		"t1.down": "跌",
		"t1.soldEarly": "卖飞",
		"t1.soldRight": "卖对",
		"t1.flat": "持平",
		"time.today": "今天",
		"time.yesterday": "昨天",
		"time.daysAgo": "{days}天前",
		"time.date": "{month}月{day}日",
		"time.weekday.0": "周日",
		"time.weekday.1": "周一",
		"time.weekday.2": "周二",
		"time.weekday.3": "周三",
		"time.weekday.4": "周四",
		"time.weekday.5": "周五",
		"time.weekday.6": "周六",
		"trace.title": "决策轨迹",
		"trace.subtitle": "一笔真实成交 + 当时写下的计划 + 官方收盘给的结果",
		"trace.staleSuffix": " · 更新失败,显示此前快照",
		"trace.unreadable": "读不到工作区的 portfolio.json(CLAWOCK_WORKSPACE 未指向 clawock 工作区,或账本无法解析),不是没有成交",
		"trace.titleWithPlan": "决策轨迹 · {date}",
		"trace.titleNoPlan": "决策轨迹 · 无当日计划",
		"trace.planThen": "当时的计划",
		"trace.noPlanRecord": "这一天没有该标的的计划记录",
		"trace.realFill": "真实成交",
		"trace.t1Close": "T+1 收盘",
		"trace.t1Pending": "T+1 未判",
		"trace.unpaired": "这笔成交在决策账本里找不到前后 3 天的同标的计划:成交是真的,当时的判断没有留下记录。",
		"trace.sharesAt": " 股 @ ",
		"trace.shares": " 股",
		"trace.confidence": " · 信心 ",
		"trace.trigger": "触发条件: ",
		"trace.selfGrade": "账本自评: ",
		"trace.realized": "本笔已实现",
		"trace.pnl": "本笔盈亏",
		"trace.openPosition": "— 未平仓",
		"trace.floating": "该持仓当前浮动 ({ticker} 全仓,非本笔)",
		"trace.why": "为什么 ",
		"trace.emotion": "情绪 ",
		"trace.note": "备注 ",
		"trace.holding": "持仓",
		"trace.opposite": "反向",
		"trace.market.hk": "港",
		"trace.market.us": "美",
		"trace.realizedUsd": "已实现 (USD 等值)",
		"trace.realizedUsdNoRate": "已实现 (USD 等值 · HKD 未折算)",
		"trace.t1Tally": "T+1 卖飞/卖对/持平 · 判出 {rated}/{sells} 笔卖出",
		"trace.t1Sideless": " · {sideless} 笔无侧向",
		"trace.matched": "有当日计划",
		"trace.reversed": " · 反向 {reversed}",
		"trace.more": "显示更早的 {fills} 笔成交",
		"trace.less": "收起,只显示最近 {groups} 组",
		"trace.empty": "没有符合条件的成交",
		"trace.fillCount": "{count} 笔成交",
		"balance.loading": "余额加载中",
		"balance.unconfigured": "未配置",
		"balance.unconfiguredKey": "未配置 API Key",
		"balance.fetchFailed": "余额获取失败",
		"balance.windowsUsed": "配额窗口已使用",
		"balance.apiBalance": "API 余额",
		"balance.granted": "赠金 ",
		"balance.toppedUp": "充值 ",
		"balance.insufficient": "官方接口判定余额不足",
		"balance.staleWith": "刷新失败,显示最近一次: {message}",
		"balance.stale": "刷新失败,显示最近一次",
		"balance.windowAt": "窗口已使用达 {percent}%",
		"balance.lowMoney": "余额偏低,低于阈值 {amount}",
		"balance.panelTitle": "各模型服务余额",
		"balance.panelHeading": "API 余额",
		"balance.refreshAll": "刷新全部余额",
		"balance.refreshNow": "立即刷新",
		"balance.readFailed": "余额读取失败:{message}",
		"balance.reading": "正在读取各服务余额…",
		"balance.noProviders": "没有可用的余额来源",
		"balance.otherProviders": "(点击查看其他服务)",
		"balance.unknownError": "未知错误",
		"balance.windowNote": "{label} 已用 {percent}%",
		"balance.windowNoteReset": "{label} 已用 {percent}%,{reset} 重置",
		"balance.window.week": "周",
		"balance.window.days": "{n}天",
		"balance.window.hours": "{n}h",
		"balance.window.minutes": "{n}m",
		"balance.reset.today": "今天 {time}",
		"balance.reset.tomorrow": "明天 {time}",
		"balance.reset.dated": "{date} {weekday} {time}",
		"queue.name": "任务",
		"queue.panelTitle": "派发任务队列",
		"queue.panelHeading": "派发队列",
		"queue.refresh": "刷新任务队列",
		"queue.running": "在跑 {n}",
		"queue.slotsHeading": "运行槽 · 按 agent",
		"queue.lane": "{agent} {used}/{max}",
		"queue.laneNoMax": "{agent} {used}",
		"queue.lanesTitle": "运行槽按 agent 分:每个 agent 只用自己的槽,互不挤占;排队看各自那一格",
		"queue.queued": "排队 {n}",
		"queue.memoryWait": "等内存 {n}",
		"queue.quotaWait": "等额度 {n}",
		"queue.retryWait": "等重试 {n}",
		"queue.idle": "没有在跑的任务",
		"queue.readFailed": "任务队列读取失败:{message}",
		"queue.staleWith": "刷新失败,显示最近一次: {message}",
		"queue.state.running": "运行中",
		"queue.state.runningSlot": "运行中 · 槽 {slot}",
		"queue.state.starting": "启动中",
		"queue.wait.lock": "等 {agent} 锁",
		"queue.wait.slot": "等 {agent} 运行槽",
		"queue.wait.memory": "等内存",
		"queue.wait.quota": "等额度 · {time} 续跑",
		"queue.wait.quotaNoTime": "等额度",
		"queue.wait.retry": "重试等待 · {time}",
		"queue.wait.retryNoTime": "重试等待",
		"queue.meta": "{agent} · {model}",
		"queue.run": "已跑 {elapsed} · 第 {attempts} 次",
		"queue.stalls": "卡死 {n}",
		"queue.waitHeading": "排队 / 等待",
		"queue.noneRunning": "没有占用运行槽的任务",
		"queue.noneWaiting": "没有排队或等待的任务",
		"queue.recentHeading": "最近结束",
		"queue.waited": "首次排队 {time}",
		"queue.d.waited": "首次排队",
		"queue.waitUnknown": "排队耗时未记录",
		"queue.execution.ok": "执行完成",
		"queue.execution.failed": "执行失败",
		"queue.execution.cancelled": "已取消",
		"queue.execution.timeout": "已超时",
		"queue.execution.blocked": "执行受阻",
		"queue.execution.quota": "额度中止",
		"queue.execution.queued": "未启动",
		"queue.execution.unknown": "结果未明",
		"queue.report.DONE": "任务：完成",
		"queue.report.claimedDone": "任务：自报完成",
		"queue.report.PARTIAL": "任务：部分完成",
		"queue.report.BLOCKED": "任务：受阻",
		"queue.report.unknown": "任务：未报告",
		"queue.statusLegend": "前项是 runner 对执行过程的判决；“任务”是模型最终报告。执行完成但任务部分完成或受阻，表示机器运行正常、工作尚未做完。",
		"queue.olderRounds": "更早的 {n} 轮",
		"queue.supervisorLog": "监督器原始记录",
		"queue.patrol.waitSlot": "等空闲运行槽",
		"queue.patrol.giveWay": "让手工任务先行",
		"queue.patrol.memory": "内存不足，暂缓",
		"queue.patrol.memoryUnread": "读不到内存，暂缓",
		"queue.patrol.otherReason": "让路（原因见原始记录）",
		"queue.patrol.wrapUp": "收尾后让路",
		"queue.patrol.forTask": "等待中的任务 {id}",
		"queue.round.preempted": "让路取消",
		"queue.round.yielded": "让路收尾",
		"queue.round.name": "{round} · {axis}",
		"queue.round.digest": "汇总 +{n}",
		"queue.round.comment": "补充 {n}",
		"queue.round.filed": "本轮提报：{what}",
		"queue.round.issueCount": "提报 {n}",
		"queue.round.openIssue": "查看提报 {issue}（新标签页）",
		"queue.patrol.remaining": "还剩 {time}",
		"queue.patrol.due": "已到计划时间",
		"queue.a.fullLog": "完整日志",
		"queue.a.fullLogTitle": "在文件预览中打开完整日志",
		"queue.a.logNoDir": "宿主未报告派发目录；更新插件并重启 dsh 后再打开完整日志。",
		"queue.chip.elapsed": "已跑 {time}",
		"queue.chip.took": "用时 {time}",
		"queue.chip.cost": "估算费用（按 API 价，非实际扣费）",
		"queue.chip.unpriced": "未定价",
		"queue.patrolHeading": "巡检",
		"queue.patrolRound": "当前轮次 {round}",
		"queue.roundsHeading": "最近几轮",
		"queue.patrol.running": "巡检运行中",
		"queue.patrol.yielding": "巡检让路中",
		"queue.patrol.waiting": "巡检等待下一轮",
		"queue.patrol.waitingUntil": "巡检 {time} 开下一轮",
		"queue.patrol.stopped": "巡检已停",
		"queue.patrol.unknown": "巡检状态未知",
		"queue.patrolState.running": "运行中",
		"queue.patrolState.yielding": "让路中",
		"queue.patrolState.waiting": "等下一轮",
		"queue.patrolState.waitingUntil": "{time} 开下一轮",
		"queue.patrolState.stopped": "已停",
		"queue.patrolState.unknown": "状态未知",
		"queue.duration.minutes": "{m} 分",
		"queue.duration.hours": "{h} 小时 {m} 分",
		"queue.ago.now": "刚刚",
		"queue.ago.minutes": "{m} 分钟前",
		"queue.ago.hours": "{h} 小时前",
		"queue.ago.days": "{d} 天前",
		"queue.wait.lockAt": "等 {agent} 锁 · 第 {n} 位",
		"queue.state.cancelling": "取消中",
		"queue.attempt": "第 {n} 次",
		"queue.slotCount": "槽 {used}/{max}",
		"queue.tag.running": "运行中",
		"queue.tag.runningSlot": "运行 · 槽 {slot}",
		"queue.tag.starting": "启动中",
		"queue.tag.cancelling": "取消中",
		"queue.tag.queued": "排队",
		"queue.tag.queuedAt": "排队 #{n}",
		"queue.tag.slot": "等运行槽",
		"queue.tag.memory": "等内存",
		"queue.tag.quota": "等额度",
		"queue.tag.retry": "重试等待",
		"queue.fact.wakes": "{time} 续跑",
		"queue.fact.startedAt": "{time} 开始",
		"queue.fact.queuedAt": "{time} 起排队",
		"queue.chip.waiting": "已等 {time}",
		"queue.fallback": "fallback",
		"queue.patrolTag": "巡检",
		"queue.noRunnerApi": "无 RUNNER_API 2：不在排队顺序里，不能调整顺序或模型",
		"queue.holderOther": "锁被 {id} 占着",
		"queue.holderUnnamed": "锁被占着，但没有登记持有者（刚好在拿锁，或不是当前 runner 起的任务）",
		"queue.quotaHint": "额度用尽，{time} 恢复（{by} 触发）；其余任务等到那时再排",
		"queue.ops.missing": "ops 入口不可用，操作已停用：{error}",
		"queue.ops.skew": "ops 入口与仓库不一致（主机 {host} / 仓库 {repo}），运行 ops/host/install_task_queue_ops.sh",
		"queue.ops.version": "ops {v}",
		"queue.ops.footer": "ops {v} · runner api {runner}",
		"queue.ch.weixin": "微信",
		"queue.ch.telegram": "Telegram",
		"queue.notify.sent": "{ch} 已送达",
		"queue.notify.failed": "{ch} 失败",
		"queue.notify.planned": "{ch} 结束时通知",
		"queue.d.place": "排队",
		"queue.d.placeValue": "{agent} 队列第 {n} 位",
		"queue.d.protected": "已等满公平窗口，不会被插队",
		"queue.d.priorityValue": "优先级 {n}",
		"queue.d.queued": "开始排队",
		"queue.d.notify": "通知",
		"queue.d.notifyNone": "不通知",
		"queue.d.runner": "Runner",
		"queue.d.session": "会话",
		"queue.d.fallbackFrom": "请求 {model}，已切换",
		"queue.d.effortDefault": "默认",
		"queue.a.top": "置顶",
		"queue.a.up": "上移",
		"queue.a.upOf": "上移 {name}",
		"queue.a.down": "下移",
		"queue.a.model": "换模型",
		"queue.a.wrapup": "体面收尾",
		"queue.a.wrapupTitle": "排队一条收尾指令：做完当前一步后提交已完成的部分并输出 STATUS",
		"queue.a.cancel": "取消",
		"queue.a.cancelConfirm": "确认取消",
		"queue.a.retry": "重试",
		"queue.a.log": "日志",
		"queue.a.save": "保存",
		"queue.a.close": "关闭",
		"queue.a.modelHint": "下一次尝试生效；正在跑的这一步不受影响。",
		"queue.a.cancelQueued": "它还没开始：取消没有损失。再点一次确认。",
		"queue.a.cancelSleeping": "它在等额度/重试：取消后不再续跑，会话保留可 resume。再点一次确认。",
		"queue.a.cancelRunning": "它正在跑：本轮进度会丢；会话 {session} 可用 --resume 续。再点一次确认。",
		"queue.a.dismissConfirm": "保留原状",
		"queue.a.reading": "读取中…",
		"queue.a.readFailed": "读取失败：{message}",
		"queue.r.failed": "没成功：{message}",
		"queue.r.cancelledQueued": "已取消（尚未开始，无损失）",
		"queue.r.cancelledRunning": "已停止，本轮进度已丢；续跑：{resume}",
		"queue.r.cancelledNoSession": "已停止（还没有会话可续）",
		"queue.r.priority": "现在排第 {n} 位（共 {total}）",
		"queue.r.model": "下一次尝试：{model} · {effort}",
		"queue.r.retry": "已作为新任务续跑：{id}",
		"queue.r.wrapup": "收尾指令已排队：当前一步结束后送达",
		"queue.back": "返回额度与队列",
		"queue.d.open": "查看任务详情",
		"queue.d.live": "进行中",
		"queue.d.ended": "已结束",
		"queue.d.agent": "Agent",
		"queue.d.model": "模型",
		"queue.d.started": "开始",
		"queue.d.elapsed": "已运行",
		"queue.d.took": "用时",
		"queue.d.endedAt": "结束",
		"queue.d.resumes": "续跑",
		"queue.d.attempts": "尝试次数",
		"queue.d.stalls": "判卡死",
		"queue.d.stallsValue": "{n} 次(静默无进展,已自动重试)",
		"queue.d.latest": "最近事件",
		"queue.d.id": "任务 ID",
		"queue.d.summary": "结果摘要",
		"queue.d.noSummary": "没有留下结果摘要",
		"panel.title": "额度 · 队列",
		"panel.aria": "各 provider 的额度与派发队列",
		"panel.refresh": "刷新额度与队列",
		"panel.plan.anthropic": "Anthropic 订阅",
		"panel.plan.chatgpt": "ChatGPT 订阅",
		"panel.plan.freePool": "无 provider · 免费池",
		"panel.plan.deepseek": "本机 API 账户",
		"panel.plan.minimax": "Token Plan · 源：OpenClaw 配置",
		"panel.pool": "池 {current} → 下一个 {next}",
		"panel.poolOrder": "（表序）",
		"panel.poolSize": "池内 {n} 个",
		"panel.poolSwap": "{n} 个免费模型同档互替",
		"panel.poolUnread": "池文件未读到（需 host 半边新版，重启 dsh 后可见）",
		"queue.verdict.done": "完成",
		"queue.verdict.partial": "部分完成",
		"queue.verdict.blocked": "受阻",
		"queue.verdict.failed": "失败",
		"queue.verdict.timeout": "超时",
		"queue.verdict.cancelled": "已取消",
		"queue.verdict.quota": "额度中止",
		"queue.verdict.noReport": "无报告",
		"queue.verdict.notStarted": "未启动",
		"queue.verdict.unknown": "未明",
		"queue.fallbackMark": "回退",
		"queue.fallbackTitle": "回退：请求的是 {requested}",
		"queue.chip.free": "免费",
		"queue.notify.unknown": "{ch} 无回执",
		"queue.receiptLegend": "以 runner 写入 result.env 的回执为准（openclaw 发送成功/失败）；无回执 = 未知，不当作已送达",
		"panel.q.idle": "闲",
		"panel.q.run": "运行 {n}",
		"panel.q.queued": "排队 {n}",
		"panel.q.quota": "等额度 {n}",
		"panel.q.wait": "等待 {n}",
		"panel.free": "免费",
		"panel.staleAt": "刷新失败（{message}），显示 {time} 的读数",
		"panel.openGroup": "打开 {name} 的额度与队列",
		"panel.railTitle": "额度 · 队列：{summary}",
		"panel.warn": "有窗口到阈值或有任务在睡额度",
		"panel.queueLoading": "正在读取派发队列…",
		"panel.queueUnavailable": "此主机没有派发队列；额度仍可查看。",
		"panel.noSources": "没有可显示的额度或派发来源。",
		"queue.wait.quotaBoth": "等到 {time}（窗口 {reset} +{pad}m 缓冲）",
		"queue.wait.quotaNoWindow": "等到 {time}（窗口重置时刻未读到）",
		"queue.d.cost": "花费",
		"queue.d.costFree": "免费（opencode 免费池）",
		"queue.d.costUnpriced": "—（该模型没有价目，不估）",
		"queue.d.costLive": "截至上一次尝试结束",
		"queue.d.tokens": "Tokens",
		"queue.d.deadline": "截止",
		"queue.a.confirmLabel": "确认 {label}",
		"queue.a.brief": "任务书",
		"queue.a.briefTitle": "在右侧文件预览打开 prompt.md（只读）",
		"queue.a.deadline": "截止 +2h",
		"queue.a.attempts": "重试 +1",
		"queue.a.resumes": "续跑 +1",
		"queue.a.deadlineConfirm": "延长 deadline 2 小时：该任务占用队列的时间变长（上限：派发 + 72h）。{when} 再点一次确认。",
		"queue.a.attemptsConfirm": "多给一次失败/卡死重试：再失败会多跑一轮。{when} 再点一次确认。",
		"queue.a.resumesConfirm": "多给一次额度续跑：每次都会重放会话上下文，有成本（缓存读）。{when} 再点一次确认。",
		"queue.a.whenNow": "它在排队/等待：几秒内生效。",
		"queue.a.whenNext": "它在跑：本次尝试的时限不变，下一次尝试起生效。",
		"queue.a.budgetOld": "这个任务的 runner 是 api {api}：deadline 与重试预算在启动时定死，改了不会生效（api 3 起的任务才支持）。",
		"queue.timeline.heading": "进展时间线",
		"queue.timeline.source": "按已有记录的时间排列，旧任务可能缺少部分事件。",
		"queue.timeline.older": "本机队列 ops 尚未更新，暂时没有时间线。",
		"queue.timeline.missing": "运行日志缺失，只能显示已有记录。",
		"queue.timeline.cut": "部分历史未显示：日志 {bytes} 字节、事件 {count} 条；操作记录也可能截断。完整记录请打开日志与任务目录。",
		"queue.timeline.empty": "没有带时间的事件记录。",
		"queue.timeline.created": "派发",
		"queue.timeline.started": "启动",
		"queue.timeline.ended": "结束",
		"queue.timeline.lock_wait": "等待执行锁",
		"queue.timeline.lock_acquired": "取得执行锁",
		"queue.timeline.slot_wait": "等待执行槽",
		"queue.timeline.slot_acquired": "取得执行槽",
		"queue.timeline.memory_wait": "等待主机资源",
		"queue.timeline.queue": "队列顺序",
		"queue.timeline.attempt": "开始尝试",
		"queue.timeline.attempt_end": "尝试结束",
		"queue.timeline.quota": "等待额度",
		"queue.timeline.retry_wait": "等待重试",
		"queue.timeline.stall": "看门狗判定停滞",
		"queue.timeline.append_submitted": "追加提交",
		"queue.timeline.append_delivered": "投递追加",
		"queue.timeline.append_resume": "继续追加指令",
		"queue.timeline.change": "设置变更",
		"queue.timeline.notification": "最新通知回执",
		"queue.brief.heading": "任务书与追加",
		"queue.brief.prompt": "任务书 prompt.md · {kb} KB",
		"queue.brief.append": "追加 #{number} · {stamp}",
		"queue.brief.delivered": "已投递",
		"queue.brief.pending": "待投递",
		"queue.brief.big": "原文 {kb} KB（预览里是完整文件；ops 读数已截断到 64 KB）",
		"queue.brief.noSession": "右侧预览要在会话里打开：先进入任意会话，再点一次。文件：{path}",
		"queue.brief.noService": "这个 dsh 没有文件预览栏。文件：{path}",
		"queue.brief.noDir": "插件 host 半边是旧版，没有告诉任务目录在哪；重启 dsh 后才能打开任务书。",
		"queue.brief.failed": "预览打不开：{message}。文件：{path}",
		"queue.brief.opened": "已在右侧预览打开 {file}",
		"queue.d.sec.run": "运行设置",
		"queue.d.sec.allowance": "额度",
		"queue.d.sec.time": "时间",
		"queue.d.sec.usage": "用量",
		"queue.d.sec.end": "结束任务",
		"queue.d.sec.again": "再跑一次",
		"queue.d.sec.raw": "原始记录",
		"queue.d.region": "{name} 的详情",
		"queue.a.viewGroup": "查看（只读）",
		"queue.a.confirm": "确认",
		"queue.d.notRecorded": "未记录",
		"queue.d.retries": "重试",
		"queue.d.quotaResumes": "额度续跑",
		"queue.d.usedOf": "已用 {used} / {max}",
		"queue.d.slotOf": "槽 {slot} / {max}",
		"queue.d.slotValue": "槽 {slot}",
		"queue.d.source": "额度来源",
		"queue.d.windows": "窗口",
		"queue.d.pool": "免费池",
		"queue.d.quotaOut": "额度用尽",
		"queue.d.costFreeShort": "免费",
		"queue.d.costEstimate": "按 API 价估算，非实际扣费",
		"queue.d.tokensTotal": "共 {total}",
		"queue.d.tokensSplit": "输入 {in} · 缓存写 {w} · 缓存读 {r} · 输出 {out}",
		"queue.brief.needsHost": "追加列表要等插件 host 半边更新（需重启 dsh）；任务书本身可以打开。",
		"queue.brief.none": "没有追加",
		"queue.brief.readOnly": "只读：要改请用 dispatch.sh append（运行中加 --queue）",
		"queue.r.needsHost": "主机上的插件 host 半边是旧版，这个动作要重启 dsh 后才可用。"
	},
	en: {
		"action.buy": "Buy",
		"action.add": "Add",
		"action.trim": "Trim",
		"action.sell": "Sell",
		"action.cut": "Cut",
		"action.hold": "Hold",
		"action.trim_on_rebound": "Trim on rebound",
		"action.t_only": "T+0 only",
		"action.add_only_on_trigger": "Add on trigger",
		"action.reject": "No add",
		"action.watch": "Watch",
		"action.abstain": "Abstain",
		"driver.technical": "Technical",
		"driver.fundamental": "Fundamental",
		"driver.sentiment": "Sentiment",
		"driver.mixed": "Mixed",
		"driver.risk_rule": "Risk rule",
		"driver.catalyst": "Catalyst",
		"driver.influencer": "Influencer",
		"driver.macro": "Macro",
		"driver.peer": "Peer",
		"exe.followed": "Followed the plan",
		"exe.not_followed": "Did not follow",
		"exe.unknown": "Unmarked",
		"align.same": "Same side as plan",
		"align.opposite": "Against the plan",
		"align.other": "Plan was not a trade",
		"emo.fomo": "FOMO",
		"emo.revenge": "Revenge",
		"emo.averaging_down": "Averaging down",
		"emo.fear": "Fear",
		"emo.euphoria": "Euphoria",
		"emo.calm": "Calm",
		"emo.mixed": "Mixed",
		"filter.all": "All",
		"filter.miss": "No plan that day",
		"filter.sold": "Sell reviews",
		"filter.dec": "Had a plan",
		"t1.up": "up",
		"t1.down": "down",
		"t1.soldEarly": "sold too early",
		"t1.soldRight": "sold well",
		"t1.flat": "flat",
		"time.today": "today",
		"time.yesterday": "yesterday",
		"time.daysAgo": "{days}d ago",
		"time.date": "{month}/{day}",
		"time.weekday.0": "Sun",
		"time.weekday.1": "Mon",
		"time.weekday.2": "Tue",
		"time.weekday.3": "Wed",
		"time.weekday.4": "Thu",
		"time.weekday.5": "Fri",
		"time.weekday.6": "Sat",
		"trace.title": "Decision trace",
		"trace.subtitle": "A real fill + the plan written at the time + the official close",
		"trace.staleSuffix": " · refresh failed, showing the previous snapshot",
		"trace.unreadable": "Could not read the workspace's portfolio.json (CLAWOCK_WORKSPACE does not point at a clawock workspace, or the ledger does not parse) — this is not an empty ledger",
		"trace.titleWithPlan": "Decision trace · {date}",
		"trace.titleNoPlan": "Decision trace · no plan that day",
		"trace.planThen": "The plan at the time",
		"trace.noPlanRecord": "No plan recorded for this ticker that day",
		"trace.realFill": "Real fill",
		"trace.t1Close": "T+1 close",
		"trace.t1Pending": "T+1 unjudged",
		"trace.unpaired": "No plan for this ticker within ±3 days in the decision ledger: the fill is real, the thinking left no record.",
		"trace.sharesAt": " shares @ ",
		"trace.shares": " shares",
		"trace.confidence": " · confidence ",
		"trace.trigger": "Trigger: ",
		"trace.selfGrade": "Ledger self-grade: ",
		"trace.realized": "Realized on this fill",
		"trace.pnl": "P&L on this fill",
		"trace.openPosition": "— still open",
		"trace.floating": "This position is floating ({ticker} whole book, not this fill)",
		"trace.why": "Why ",
		"trace.emotion": "Emotion ",
		"trace.note": "Note ",
		"trace.holding": "Position",
		"trace.opposite": "Against plan",
		"trace.market.hk": "HK",
		"trace.market.us": "US",
		"trace.realizedUsd": "Realized (USD equivalent)",
		"trace.realizedUsdNoRate": "Realized (USD equivalent · HKD unconverted)",
		"trace.t1Tally": "T+1 sold-early/sold-well/flat · {rated}/{sells} sells judged",
		"trace.t1Sideless": " · {sideless} with no side",
		"trace.matched": "Had a plan that day",
		"trace.reversed": " · {reversed} against plan",
		"trace.more": "Show {fills} earlier fills",
		"trace.less": "Collapse to the latest {groups} groups",
		"trace.empty": "No fill matches this filter",
		"trace.fillCount": "{count} fills",
		"balance.loading": "Loading balance",
		"balance.unconfigured": "Not set",
		"balance.unconfiguredKey": "No API key configured",
		"balance.fetchFailed": "Balance unavailable",
		"balance.windowsUsed": "Quota windows in use",
		"balance.apiBalance": "API balance",
		"balance.granted": "Granted ",
		"balance.toppedUp": "Topped up ",
		"balance.insufficient": "The provider reports insufficient balance",
		"balance.staleWith": "Refresh failed, showing the last reading: {message}",
		"balance.stale": "Refresh failed, showing the last reading",
		"balance.windowAt": "A window is at {percent}% used",
		"balance.lowMoney": "Balance low, below the {amount} threshold",
		"balance.panelTitle": "Model service balances",
		"balance.panelHeading": "API balance",
		"balance.refreshAll": "Refresh all balances",
		"balance.refreshNow": "Refresh now",
		"balance.readFailed": "Balance read failed: {message}",
		"balance.reading": "Reading balances…",
		"balance.noProviders": "No balance source is available",
		"balance.otherProviders": "(click for other services)",
		"balance.unknownError": "unknown error",
		"balance.windowNote": "{label} {percent}% used",
		"balance.windowNoteReset": "{label} {percent}% used, resets {reset}",
		"balance.window.week": "week",
		"balance.window.days": "{n}d",
		"balance.window.hours": "{n}h",
		"balance.window.minutes": "{n}m",
		"balance.reset.today": "today {time}",
		"balance.reset.tomorrow": "tomorrow {time}",
		"balance.reset.dated": "{date} {weekday} {time}",
		"queue.name": "Tasks",
		"queue.panelTitle": "Dispatch task queue",
		"queue.panelHeading": "Dispatch queue",
		"queue.refresh": "Refresh the task queue",
		"queue.running": "{n} running",
		"queue.slotsHeading": "Run slots · per agent",
		"queue.lane": "{agent} {used}/{max}",
		"queue.laneNoMax": "{agent} {used}",
		"queue.lanesTitle": "Run slots are per agent: each agent only uses its own, so a queue is about that agent alone",
		"queue.queued": "{n} queued",
		"queue.memoryWait": "{n} waiting on memory",
		"queue.quotaWait": "{n} waiting on quota",
		"queue.retryWait": "{n} waiting to retry",
		"queue.idle": "No task running",
		"queue.readFailed": "Task queue read failed: {message}",
		"queue.staleWith": "Refresh failed, showing the last read: {message}",
		"queue.state.running": "running",
		"queue.state.runningSlot": "running · slot {slot}",
		"queue.state.starting": "starting",
		"queue.wait.lock": "waiting for the {agent} lock",
		"queue.wait.slot": "waiting for a {agent} run slot",
		"queue.wait.memory": "waiting for memory",
		"queue.wait.quota": "quota wait · resumes {time}",
		"queue.wait.quotaNoTime": "quota wait",
		"queue.wait.retry": "retry wait · {time}",
		"queue.wait.retryNoTime": "retry wait",
		"queue.meta": "{agent} · {model}",
		"queue.run": "{elapsed} · attempt {attempts}",
		"queue.stalls": "{n} stalled",
		"queue.waitHeading": "Queued / waiting",
		"queue.noneRunning": "No task holds a slot",
		"queue.noneWaiting": "Nothing queued or waiting",
		"queue.recentHeading": "Recently ended",
		"queue.waited": "first queue wait {time}",
		"queue.d.waited": "Queue wait",
		"queue.waitUnknown": "queue wait not recorded",
		"queue.execution.ok": "Execution complete",
		"queue.execution.failed": "Execution failed",
		"queue.execution.cancelled": "Cancelled",
		"queue.execution.timeout": "Timed out",
		"queue.execution.blocked": "Execution blocked",
		"queue.execution.quota": "Stopped on quota",
		"queue.execution.queued": "Never started",
		"queue.execution.unknown": "Result unknown",
		"queue.report.DONE": "Task: complete",
		"queue.report.claimedDone": "Task: reports complete",
		"queue.report.PARTIAL": "Task: partial",
		"queue.report.BLOCKED": "Task: blocked",
		"queue.report.unknown": "Task: no report",
		"queue.statusLegend": "The first status is the runner’s execution verdict. “Task” is the model’s final report. Execution can complete while the task remains partial or blocked.",
		"queue.olderRounds": "{n} earlier rounds",
		"queue.supervisorLog": "Raw supervisor log",
		"queue.patrol.waitSlot": "Waiting for a free run slot",
		"queue.patrol.giveWay": "Giving way to manual tasks",
		"queue.patrol.memory": "Low memory, deferred",
		"queue.patrol.memoryUnread": "Memory unreadable, deferred",
		"queue.patrol.otherReason": "Giving way (reason in the raw log)",
		"queue.patrol.wrapUp": "Wrapping up to give way",
		"queue.patrol.forTask": "Waiting task {id}",
		"queue.round.preempted": "Cancelled to give way",
		"queue.round.yielded": "Wrapped up to give way",
		"queue.round.name": "{round} · {axis}",
		"queue.round.digest": "digest +{n}",
		"queue.round.comment": "{n} added",
		"queue.round.filed": "filed this round: {what}",
		"queue.round.issueCount": "{n} filed",
		"queue.round.openIssue": "Open finding {issue} (new tab)",
		"queue.patrol.remaining": "{time} remaining",
		"queue.patrol.due": "scheduled time reached",
		"queue.a.fullLog": "Full log",
		"queue.a.fullLogTitle": "Open the full log in file preview",
		"queue.a.logNoDir": "The host did not report the dispatch directory; update the plugin and restart dsh before opening the full log.",
		"queue.chip.elapsed": "running {time}",
		"queue.chip.took": "took {time}",
		"queue.chip.cost": "Estimate at API prices, not a bill",
		"queue.chip.unpriced": "unpriced",
		"queue.patrolHeading": "Patrol",
		"queue.patrolRound": "current round {round}",
		"queue.roundsHeading": "Recent rounds",
		"queue.patrol.running": "patrol running",
		"queue.patrol.yielding": "patrol giving way",
		"queue.patrol.waiting": "patrol between rounds",
		"queue.patrol.waitingUntil": "patrol next round {time}",
		"queue.patrol.stopped": "patrol stopped",
		"queue.patrol.unknown": "patrol state unknown",
		"queue.patrolState.running": "running",
		"queue.patrolState.yielding": "giving way",
		"queue.patrolState.waiting": "idle",
		"queue.patrolState.waitingUntil": "next round {time}",
		"queue.patrolState.stopped": "stopped",
		"queue.patrolState.unknown": "state unknown",
		"queue.duration.minutes": "{m}m",
		"queue.duration.hours": "{h}h {m}m",
		"queue.ago.now": "just now",
		"queue.ago.minutes": "{m}m ago",
		"queue.ago.hours": "{h}h ago",
		"queue.ago.days": "{d}d ago",
		"queue.wait.lockAt": "waiting for the {agent} lock · #{n}",
		"queue.state.cancelling": "cancelling",
		"queue.attempt": "attempt {n}",
		"queue.slotCount": "slot {used}/{max}",
		"queue.tag.running": "running",
		"queue.tag.runningSlot": "running #{slot}",
		"queue.tag.starting": "starting",
		"queue.tag.cancelling": "cancelling",
		"queue.tag.queued": "queued",
		"queue.tag.queuedAt": "queued #{n}",
		"queue.tag.slot": "slot wait",
		"queue.tag.memory": "memory wait",
		"queue.tag.quota": "quota wait",
		"queue.tag.retry": "retry wait",
		"queue.fact.wakes": "resumes {time}",
		"queue.fact.startedAt": "started {time}",
		"queue.fact.queuedAt": "queued since {time}",
		"queue.chip.waiting": "waiting {time}",
		"queue.fallback": "fallback",
		"queue.patrolTag": "patrol",
		"queue.noRunnerApi": "No RUNNER_API 2: not in the queue order; its order and model cannot change",
		"queue.holderOther": "The lock is held by {id}",
		"queue.holderUnnamed": "The lock is held, but no holder is registered (one taking it right now, or a task the current runner did not start)",
		"queue.quotaHint": "Quota is out until {time} ({by} hit it); the others wait for it",
		"queue.ops.missing": "The ops entry is unavailable, actions are off: {error}",
		"queue.ops.skew": "The ops entry differs from the repository (host {host} / repo {repo}): run ops/host/install_task_queue_ops.sh",
		"queue.ops.version": "ops {v}",
		"queue.ops.footer": "ops {v} · runner api {runner}",
		"queue.ch.weixin": "WeChat",
		"queue.ch.telegram": "Telegram",
		"queue.notify.sent": "{ch} delivered",
		"queue.notify.failed": "{ch} failed",
		"queue.notify.planned": "{ch} on finish",
		"queue.d.place": "Queue",
		"queue.d.placeValue": "#{n} in the {agent} queue",
		"queue.d.protected": "past the fair wait, cannot be overtaken",
		"queue.d.priorityValue": "priority {n}",
		"queue.d.queued": "Queued",
		"queue.d.notify": "Notify",
		"queue.d.notifyNone": "none",
		"queue.d.runner": "Runner",
		"queue.d.session": "Session",
		"queue.d.fallbackFrom": "asked for {model}, switched",
		"queue.d.effortDefault": "default",
		"queue.a.top": "To top",
		"queue.a.up": "Move up",
		"queue.a.upOf": "Move {name} up",
		"queue.a.down": "Move down",
		"queue.a.model": "Model",
		"queue.a.wrapup": "Wrap up",
		"queue.a.wrapupTitle": "Queue a wrap-up instruction: after the current step, land what is done and report STATUS",
		"queue.a.cancel": "Cancel",
		"queue.a.cancelConfirm": "Confirm cancel",
		"queue.a.retry": "Retry",
		"queue.a.log": "Log",
		"queue.a.save": "Save",
		"queue.a.close": "Close",
		"queue.a.modelHint": "Applies to the next attempt; the step running now keeps its model.",
		"queue.a.cancelQueued": "It has not started: cancelling costs nothing. Tap again to confirm.",
		"queue.a.cancelSleeping": "It waits for quota or a retry: it will not resume; the session stays resumable. Tap again to confirm.",
		"queue.a.cancelRunning": "It is running: this step's progress is lost; session {session} can be resumed. Tap again to confirm.",
		"queue.a.dismissConfirm": "Keep unchanged",
		"queue.a.reading": "Loading…",
		"queue.a.readFailed": "Read failed: {message}",
		"queue.r.failed": "Did not work: {message}",
		"queue.r.cancelledQueued": "Cancelled (had not started, nothing lost)",
		"queue.r.cancelledRunning": "Stopped, this step's progress is lost; resume: {resume}",
		"queue.r.cancelledNoSession": "Stopped (no session yet)",
		"queue.r.priority": "Now #{n} of {total}",
		"queue.r.model": "Next attempt: {model} · {effort}",
		"queue.r.retry": "Continuing as a new task: {id}",
		"queue.r.wrapup": "Wrap-up queued: delivered when the current step ends",
		"queue.back": "Back to quota and queue",
		"queue.d.open": "Show task details",
		"queue.d.live": "Live",
		"queue.d.ended": "Ended",
		"queue.d.agent": "Agent",
		"queue.d.model": "Model",
		"queue.d.started": "Started",
		"queue.d.elapsed": "Running for",
		"queue.d.took": "Took",
		"queue.d.endedAt": "Finished",
		"queue.d.resumes": "Wakes at",
		"queue.d.attempts": "Attempts",
		"queue.d.stalls": "Stalled",
		"queue.d.stallsValue": "{n} (silent with no progress, retried automatically)",
		"queue.d.latest": "Latest event",
		"queue.d.id": "Task ID",
		"queue.d.summary": "Closing report",
		"queue.d.noSummary": "No closing report was left",
		"panel.title": "Quota · queue",
		"panel.aria": "Each provider's quota and the dispatch queue",
		"panel.refresh": "Refresh quotas and the queue",
		"panel.plan.anthropic": "Anthropic subscription",
		"panel.plan.chatgpt": "ChatGPT subscription",
		"panel.plan.freePool": "No provider · free pool",
		"panel.plan.deepseek": "This host's API account",
		"panel.plan.minimax": "Token Plan · key from the OpenClaw config",
		"panel.pool": "pool {current} → next {next}",
		"panel.poolOrder": " (file order)",
		"panel.poolSize": "{n} in pool",
		"panel.poolSwap": "{n} free models, each a stand-in for the next",
		"panel.poolUnread": "pool file not read (needs the newer host half, after a dsh restart)",
		"queue.verdict.done": "done",
		"queue.verdict.partial": "partial",
		"queue.verdict.blocked": "blocked",
		"queue.verdict.failed": "failed",
		"queue.verdict.timeout": "timed out",
		"queue.verdict.cancelled": "cancelled",
		"queue.verdict.quota": "quota stop",
		"queue.verdict.noReport": "no report",
		"queue.verdict.notStarted": "not started",
		"queue.verdict.unknown": "unknown",
		"queue.fallbackMark": "fallback",
		"queue.fallbackTitle": "fallback: {requested} was requested",
		"queue.chip.free": "free",
		"queue.notify.unknown": "{ch}: no receipt",
		"queue.receiptLegend": "From the receipt the runner writes to result.env (openclaw send succeeded / failed); no receipt = unknown, never taken as delivered",
		"panel.q.idle": "idle",
		"panel.q.run": "{n} running",
		"panel.q.queued": "{n} queued",
		"panel.q.quota": "{n} on quota",
		"panel.q.wait": "{n} waiting",
		"panel.free": "free",
		"panel.staleAt": "Refresh failed ({message}); showing the reading of {time}",
		"panel.openGroup": "Open {name}'s quota and queue",
		"panel.railTitle": "Quota · queue: {summary}",
		"panel.warn": "a window is at its threshold or a task sleeps on quota",
		"panel.queueLoading": "Reading the dispatch queue…",
		"panel.queueUnavailable": "This host has no dispatch queue; quotas are still available.",
		"panel.noSources": "No quota or dispatch source is available.",
		"queue.wait.quotaBoth": "until {time} (window {reset} + {pad}m margin)",
		"queue.wait.quotaNoWindow": "until {time} (window reset not read)",
		"queue.d.cost": "Cost",
		"queue.d.costFree": "free (opencode free pool)",
		"queue.d.costUnpriced": "— (no price for this model, not estimated)",
		"queue.d.costLive": "as of the last finished attempt",
		"queue.d.tokens": "Tokens",
		"queue.d.deadline": "Deadline",
		"queue.a.confirmLabel": "Confirm {label}",
		"queue.a.brief": "Brief",
		"queue.a.briefTitle": "Open prompt.md in the file preview (read-only)",
		"queue.a.deadline": "Deadline +2h",
		"queue.a.attempts": "Retry +1",
		"queue.a.resumes": "Resume +1",
		"queue.a.deadlineConfirm": "Two more hours: the task holds its place in the queue longer (ceiling: dispatch + 72h). {when} Tap again to confirm.",
		"queue.a.attemptsConfirm": "One more retry after a failure or stall: another failure runs one more round. {when} Tap again to confirm.",
		"queue.a.resumesConfirm": "One more quota resume: each replays the session's context, which costs cache reads. {when} Tap again to confirm.",
		"queue.a.whenNow": "It is queued or waiting: applies within seconds.",
		"queue.a.whenNext": "It is running: this attempt keeps its time cap; applies from the next attempt.",
		"queue.a.budgetOld": "This task's runner is api {api}: its deadline and retry budgets were fixed at start, a change would not apply (tasks from api 3 on accept it).",
		"queue.timeline.heading": "Progress timeline",
		"queue.timeline.source": "Sorted by recorded time. Older tasks may have missing events.",
		"queue.timeline.older": "The queue ops entry needs updating before it can supply a timeline.",
		"queue.timeline.missing": "Run log missing; only available records are shown.",
		"queue.timeline.cut": "History omitted: {bytes} log bytes, {count} events; audit records may also be truncated. Open the full log and task directory for complete records.",
		"queue.timeline.empty": "No timestamped events recorded.",
		"queue.timeline.created": "Dispatched",
		"queue.timeline.started": "Started",
		"queue.timeline.ended": "Ended",
		"queue.timeline.lock_wait": "Waiting for lock",
		"queue.timeline.lock_acquired": "Lock acquired",
		"queue.timeline.slot_wait": "Waiting for slot",
		"queue.timeline.slot_acquired": "Slot acquired",
		"queue.timeline.memory_wait": "Waiting for host resources",
		"queue.timeline.queue": "Queue order",
		"queue.timeline.attempt": "Attempt started",
		"queue.timeline.attempt_end": "Attempt ended",
		"queue.timeline.quota": "Waiting for quota",
		"queue.timeline.retry_wait": "Waiting for retry",
		"queue.timeline.stall": "Watchdog detected a stall",
		"queue.timeline.append_submitted": "Append submitted",
		"queue.timeline.append_delivered": "Append delivered",
		"queue.timeline.append_resume": "Resuming with append",
		"queue.timeline.change": "Settings changed",
		"queue.timeline.notification": "Latest notification receipt",
		"queue.brief.heading": "Brief and appends",
		"queue.brief.prompt": "Brief prompt.md · {kb} KB",
		"queue.brief.append": "Append #{number} · {stamp}",
		"queue.brief.delivered": "delivered",
		"queue.brief.pending": "pending",
		"queue.brief.big": "{kb} KB (the preview shows the whole file; the ops read is capped at 64 KB)",
		"queue.brief.noSession": "The preview opens inside a conversation: open any conversation, then tap again. File: {path}",
		"queue.brief.noService": "This dsh has no file preview. File: {path}",
		"queue.brief.noDir": "The plugin's host half is older and does not say where task directories are: the brief opens after a dsh restart.",
		"queue.brief.failed": "The preview did not open: {message}. File: {path}",
		"queue.brief.opened": "Opened {file} in the preview",
		"queue.d.sec.run": "Run settings",
		"queue.d.sec.allowance": "Allowance",
		"queue.d.sec.time": "Time",
		"queue.d.sec.usage": "Usage",
		"queue.d.sec.end": "End the task",
		"queue.d.sec.again": "Run again",
		"queue.d.sec.raw": "Raw record",
		"queue.d.region": "Details of {name}",
		"queue.a.viewGroup": "View (read-only)",
		"queue.a.confirm": "Confirm",
		"queue.d.notRecorded": "not recorded",
		"queue.d.retries": "Retries",
		"queue.d.quotaResumes": "Resumes",
		"queue.d.usedOf": "{used} of {max} used",
		"queue.d.slotOf": "slot {slot} of {max}",
		"queue.d.slotValue": "slot {slot}",
		"queue.d.source": "Paid by",
		"queue.d.windows": "Windows",
		"queue.d.pool": "Free pool",
		"queue.d.quotaOut": "Out of quota",
		"queue.d.costFreeShort": "free",
		"queue.d.costEstimate": "estimated at API prices, not billed",
		"queue.d.tokensTotal": "{total} total",
		"queue.d.tokensSplit": "in {in} · cache write {w} · cache read {r} · out {out}",
		"queue.brief.needsHost": "The appends list needs the updated host half (a dsh restart); the brief itself opens now.",
		"queue.brief.none": "No appends",
		"queue.brief.readOnly": "Read-only: change it with dispatch.sh append (--queue while it runs)",
		"queue.r.needsHost": "The plugin's host half on this host is older: this action works after a dsh restart."
	}
};
/**
* Bind a dictionary to a lookup shaped exactly like the host's `t` seat, with
* `{name}` interpolation. The host supplies the real one through the slot
* registration (`locale: LOCALE_NS`); this factory exists so a render can be
* exercised without a locale service — the same seam the tests use.
*/
function createTranslator(dict) {
	return (key, params) => {
		const template = dict[key];
		if (template === void 0) return key;
		if (params === void 0) return template;
		return template.replace(/\{(\w+)\}/g, (whole, name) => Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : whole);
	};
}
/**
* Window length in minutes → the label in the active locale, host string as
* fallback. The structured fields are typed `| null` but read `== null`: a
* host that predates them omits the key entirely, so the value that actually
* arrives is `undefined`. Checking only for null rendered `NaN m` against a
* previous-version host — the exact half-deployed case this fallback exists
* for, caught by the projection test rather than in the browser.
*/
function windowLabelOf(t, window) {
	const mins = window.durationMins;
	if (mins == null || mins <= 0) return window.label;
	if (mins === 10080) return t("balance.window.week");
	if (mins % 1440 === 0) return t("balance.window.days", { n: mins / 1440 });
	if (mins % 60 === 0) return t("balance.window.hours", { n: mins / 60 });
	return t("balance.window.minutes", { n: Math.round(mins) });
}
/** The reset instant → the stamp in the active locale, host string as fallback. */
function resetStampOf(t, window, now) {
	const ms = window.resetAtMs;
	if (ms == null) return window.resetAt;
	const at = new Date(ms);
	const time = String(at.getHours()).padStart(2, "0") + ":" + String(at.getMinutes()).padStart(2, "0");
	const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
	const days = Math.round((startOfDay(at) - startOfDay(new Date(now))) / 864e5);
	if (days === 0) return t("balance.reset.today", { time });
	if (days === 1) return t("balance.reset.tomorrow", { time });
	return t("balance.reset.dated", {
		date: at.getMonth() + 1 + "/" + at.getDate(),
		weekday: t("time.weekday." + at.getDay()),
		time
	});
}
/** Every window of a snapshot, named and stamped for the active locale. */
function windowsOf(t, result, now) {
	return (result.snapshot?.windows ?? []).map((w) => ({
		label: windowLabelOf(t, w),
		percent: w.percent,
		reset: resetStampOf(t, w, now)
	}));
}
//#endregion
//#region src/providers.ts
/**
* Rows in the order the panel lists them (kcn, 2026-09-27): the paid,
* exclusive allowances first — the two subscriptions, then the balance and
* the token plan — and the free pool last. opencode sits low not because it
* is weaker but because it is free and interchangeable: its models replace
* one another inside the pool, so it is one line for the whole pool, never a
* line per model.
*/
const PROVIDER_JOIN = [
	{
		provider: "claude",
		agent: "claude",
		kind: "windows",
		tier: "paid",
		plan: "panel.plan.anthropic"
	},
	{
		provider: "codex",
		agent: "codex",
		kind: "windows",
		tier: "paid",
		plan: "panel.plan.chatgpt"
	},
	{
		provider: "deepseek",
		agent: null,
		kind: "money",
		tier: "paid",
		plan: "panel.plan.deepseek"
	},
	{
		provider: "minimax",
		agent: null,
		kind: "windows",
		tier: "paid",
		plan: "panel.plan.minimax"
	},
	{
		provider: null,
		agent: "opencode",
		kind: "pool",
		tier: "free",
		plan: "panel.plan.freePool"
	}
];
/**
* A source's place: its row's index, times two. A provider or agent without a
* row costs an unknown amount, so it is treated as scarce: after the known
* paid rows, before the free ones (the odd slot between them).
*/
function sourceRank(key) {
	const at = PROVIDER_JOIN.findIndex((join) => key.provider != null && join.provider === key.provider || key.agent != null && join.agent === key.agent);
	if (at >= 0) return at * 2;
	const free = PROVIDER_JOIN.findIndex((join) => join.tier === "free");
	return (free < 0 ? PROVIDER_JOIN.length : free) * 2 - 1;
}
/** Items that belong to an agent (tasks, slot lanes) in the panel's order; stable, so newest-first stays newest-first within an agent. */
function byAgentRank(items) {
	return items.map((item, at) => ({
		item,
		at,
		rank: sourceRank({ agent: item.agent })
	})).sort((a, b) => a.rank - b.rank || a.at - b.at).map(({ item }) => item);
}
//#endregion
//#region src/panel.ts
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
/**
* Colour tier for one used-percent reading against the REMAINING-watermark
* threshold (lowPct). kcn 的配色口径:已使用低 = 正常绿(--ok),逼近额度
* 上限先黄(--warn)再红(--bad)。档位从既有 lowPct 派生,不新增配置:
* warn at 100−2·lowPct, red inside 100−lowPct(默认 20 → 60% 黄 / 80% 红)。
* 档位只决定颜色,绝不增删信息(kcn 反馈 #908:变红不许吃掉任何字段)。
*/
function _usedLevel(percent, threshold) {
	if (percent === null) return "ok";
	if (percent >= 100 - threshold) return "low";
	if (percent >= 100 - 2 * threshold) return "mid";
	return "ok";
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
function _rowDisplay(result, t, now = Date.now()) {
	if (result === null) return {
		tone: "none",
		value: "—",
		sub: null,
		reset: null,
		level: null,
		title: t("balance.loading")
	};
	if (!result.configured) return {
		tone: "none",
		value: t("balance.unconfigured"),
		sub: null,
		reset: null,
		level: null,
		title: result.message ?? t("balance.unconfiguredKey")
	};
	if (result.snapshot === null) return {
		tone: "none",
		value: "—",
		sub: null,
		reset: null,
		level: null,
		title: result.message ?? t("balance.fetchFailed")
	};
	const snapshot = result.snapshot;
	const isPct = snapshot.unit === "pct";
	const symbol = isPct ? "" : snapshot.currency === "USD" ? "$" : snapshot.currency === "CNY" ? "¥" : "";
	const pctWins = isPct && Array.isArray(snapshot.windows) ? snapshot.windows.filter((w) => w.percent !== null) : [];
	const parsed = Number.parseFloat(snapshot.totalBalance);
	const value = isFinite(parsed) ? isPct ? String(Math.round(parsed)) + "%" : symbol + parsed.toLocaleString(void 0, { maximumFractionDigits: 2 }) : pctWins.length > 0 ? String(Math.round(pctWins[0].percent)) + "%" : snapshot.totalBalance === "" ? "—" : symbol + snapshot.totalBalance;
	const second = pctWins.length > 1 ? pctWins[1] : null;
	const wins = windowsOf(t, result, now);
	const firstReset = wins.length > 0 ? wins[0].reset : "";
	const reset = pctWins.length > 0 && firstReset !== "" ? firstReset : null;
	const secondWin = wins.length > 1 ? wins[1] : null;
	const sub = secondWin !== null && second !== null ? "· " + secondWin.label + " " + Math.round(second.percent) + "%" + (secondWin.reset !== "" ? " ↻" + secondWin.reset : "") : null;
	const tone = result.status === "stale" ? "stale" : result.low || !snapshot.isAvailable ? "low" : "ok";
	const quotaTail = wins.length === 0 ? [] : snapshot.note.split(" · ").slice(snapshot.windows.length).filter((note) => note !== "");
	const quotaLine = wins.length === 0 ? snapshot.note !== "" ? snapshot.note : t("balance.windowsUsed") : [...wins.filter((w) => w.percent !== null).map((w) => w.reset === "" ? t("balance.windowNote", {
		label: w.label,
		percent: Math.round(w.percent)
	}) : t("balance.windowNoteReset", {
		label: w.label,
		percent: Math.round(w.percent),
		reset: w.reset
	})), ...quotaTail].join(" · ");
	const parts = [
		snapshot.unit === "pct" ? quotaLine : t("balance.apiBalance"),
		!isPct && snapshot.grantedBalance !== "" ? t("balance.granted") + symbol + snapshot.grantedBalance : null,
		!isPct && snapshot.toppedUpBalance !== "" ? t("balance.toppedUp") + symbol + snapshot.toppedUpBalance : null,
		snapshot.isAvailable || isPct ? null : t("balance.insufficient"),
		result.status === "stale" && result.message !== null ? t("balance.staleWith", { message: result.message }) : null
	].filter((part) => part !== null);
	const shownPct = isPct ? isFinite(parsed) ? parsed : pctWins.length > 0 ? pctWins[0].percent : null : null;
	return {
		tone,
		value,
		sub,
		reset,
		level: shownPct === null ? null : _usedLevel(Math.round(shownPct), result.threshold),
		title: parts.join(" · ")
	};
}
/**
* The one line a panel row says out loud when something is wrong — stale
* reason, unconfigured key, insufficient money balance. A healthy number
* earns no caption at all; null means silence. An exhausted quota window
* is silence too (kcn 反馈): its 100% bar and reset stamp in the per-window
* rows are the message; a caption would only replace them.
*/
function _balanceNote(result, t) {
	if (result === null) return null;
	if (!result.configured) return result.message ?? t("balance.unconfiguredKey");
	if (result.snapshot === null) return result.message ?? t("balance.fetchFailed");
	if (result.status === "stale") return result.message !== null ? t("balance.staleWith", { message: result.message }) : t("balance.stale");
	if (!result.snapshot.isAvailable) return result.snapshot.unit === "pct" ? null : t("balance.insufficient");
	if (result.low) {
		if (result.snapshot.unit === "pct") return (result.snapshot.windows ?? []).length > 0 ? null : t("balance.windowAt", { percent: 100 - result.threshold });
		return t("balance.lowMoney", { amount: (result.snapshot.currency === "USD" ? "$" : result.snapshot.currency === "CNY" ? "¥" : "") + result.threshold });
	}
	return null;
}
/** A live task queued for something another task of its agent holds (the backlog patrol yields to). */
const queuedFor = (task) => task.waiting === "lock" || task.waiting === "slot";
/**
* Which run slot a live task holds: `SLOT=<agent>-<n>` (slots are per agent).
* Anything else is shown verbatim under the task's own agent. (The shared
* `slot-1..2` of the runners from before 2026-09-25, a bare number, had a
* bucket of its own until 2026-09-27, when none was left.)
*/
function _slotOf(task) {
	if (task.slot === "") return null;
	const lane = /^([a-z][a-z0-9]*)-(\d+)$/.exec(task.slot);
	return lane ? {
		agent: lane[1],
		slot: lane[2]
	} : {
		agent: task.agent,
		slot: task.slot
	};
}
/**
* Each agent's run slots, in the panel's order (providers.ts), limits.env's
* agents and any agent seen holding one that limits.env does not name. A full lane with a task of that agent queued
* is amber: that is the queue's reason at a glance. A host older than
* slotLimits sends none: the lanes then come from the held slots alone,
* without a maximum.
*/
function _slotLanes(result) {
	const held = result.active.map(_slotOf).filter((slot) => slot !== null);
	const limits = new Map((result.slotLimits ?? []).map((limit) => [limit.agent, limit.max]));
	for (const slot of held) if (!limits.has(slot.agent)) limits.set(slot.agent, -1);
	return byAgentRank([...limits].map(([agent, limit]) => ({
		agent,
		limit
	}))).map(({ agent, limit }) => {
		const used = held.filter((slot) => slot.agent === agent).length;
		const max = limit >= 0 ? limit : null;
		const queued = result.active.some((task) => task.agent === agent && queuedFor(task));
		return {
			agent,
			used,
			max,
			tone: max !== null && used >= max && queued ? "stale" : used > 0 ? "ok" : "none"
		};
	});
}
function durationOf(t, ms) {
	const mins = Math.max(0, Math.floor(ms / 6e4));
	return mins < 60 ? t("queue.duration.minutes", { m: mins }) : t("queue.duration.hours", {
		h: Math.floor(mins / 60),
		m: mins % 60
	});
}
function agoOf(t, ms) {
	const mins = Math.max(0, Math.floor(ms / 6e4));
	if (mins < 1) return t("queue.ago.now");
	if (mins < 60) return t("queue.ago.minutes", { m: mins });
	if (mins < 2880) return t("queue.ago.hours", { h: Math.floor(mins / 60) });
	return t("queue.ago.days", { d: Math.floor(mins / 1440) });
}
/**
* One live task's status phrase and its tone. One colour, one meaning:
* 'ok' (the host's business blue) = holding its agent's lock and running,
* 'stale' (the host's warn) = waiting for something (the lock, a slot,
* memory, a quota reset, a retry), 'none' = neither yet (starting).
*/
function _taskStatus(task, t, now = Date.now(), windows) {
	const stamp = (ms) => resetStampOf(t, {
		resetAt: "",
		resetAtMs: ms
	}, now);
	const at = (key, ms) => ms === null ? t(key + "NoTime") : t(key, { time: stamp(ms) });
	if (task.cancelling) return {
		tone: "none",
		text: t("queue.state.cancelling")
	};
	switch (task.waiting) {
		case "lock": return {
			tone: "stale",
			text: task.position ? t("queue.wait.lockAt", {
				agent: task.agent,
				n: task.position
			}) : t("queue.wait.lock", { agent: task.agent })
		};
		case "slot": return {
			tone: "stale",
			text: t("queue.wait.slot", { agent: task.agent })
		};
		case "memory": return {
			tone: "stale",
			text: t("queue.wait.memory")
		};
		case "quota": {
			if (task.wakeAtMs === null || windows === void 0) return {
				tone: "stale",
				text: at("queue.wait.quota", task.wakeAtMs)
			};
			const wake = task.wakeAtMs;
			const resets = windows.map((w) => w.resetAtMs ?? null).filter((ms) => ms !== null && ms <= wake + 6e4 && wake - ms < 216e5);
			if (resets.length === 0) return {
				tone: "stale",
				text: t("queue.wait.quotaNoWindow", { time: stamp(wake) })
			};
			const reset = Math.max(...resets);
			return {
				tone: "stale",
				text: t("queue.wait.quotaBoth", {
					time: stamp(wake),
					reset: stamp(reset),
					pad: Math.max(0, Math.round((wake - reset) / 6e4))
				})
			};
		}
		case "retry": return {
			tone: "stale",
			text: at("queue.wait.retry", task.wakeAtMs)
		};
	}
	const slot = _slotOf(task);
	if (slot === null) return {
		tone: "none",
		text: t("queue.state.starting")
	};
	return {
		tone: "ok",
		text: slot.slot === "1" ? t("queue.state.running") : t("queue.state.runningSlot", { slot: slot.slot })
	};
}
/** Keep the runner's execution verdict and the model's report in separate, named slots. */
function executionText(state, t) {
	return t("queue.execution." + ({
		ok: "ok",
		partial: "ok",
		unverified: "ok",
		failed: "failed",
		cancelled: "cancelled",
		timeout: "timeout",
		blocked: "blocked",
		quota: "quota",
		queued: "queued"
	}[state] ?? "unknown"));
}
function reportText(outcome, t, executionState = "ok") {
	if (outcome === "DONE" && ![
		"ok",
		"partial",
		"unverified"
	].includes(executionState)) return t("queue.report.claimedDone");
	return t("queue.report." + ([
		"DONE",
		"PARTIAL",
		"BLOCKED"
	].includes(outcome) ? outcome : "unknown"));
}
function patrolPhraseOf(result, t, now) {
	const patrol = result.patrol;
	if (patrol.phase === "waiting" && patrol.untilMs !== null) return t("queue.patrol.waitingUntil", { time: resetStampOf(t, {
		resetAt: "",
		resetAtMs: patrol.untilMs
	}, now) });
	return t("queue.patrol." + patrol.phase);
}
/** The ops entry answered, and its installed copy is the repository's. '' when fine, else why not. */
function opsProblem(result, t) {
	const ops = result.ops;
	if (ops === void 0) return "";
	if (!ops.available) return t("queue.ops.missing", { error: ops.error });
	if (ops.repoVersion !== "" && ops.version !== ops.repoVersion) return t("queue.ops.skew", {
		host: ops.version,
		repo: ops.repoVersion
	});
	return "";
}
/** Executor names as their makers write them. */
const AGENT_LABELS = {
	claude: "Claude Code",
	codex: "Codex",
	opencode: "OpenCode"
};
const _agentLabel = (agent) => AGENT_LABELS[agent] ?? agent;
/**
* The model layer, read off the model id itself (never a hand-kept model
* list), as its maker names it in full: `claude-opus-5-5` → Claude Opus 5.5 ·
* `claude-haiku-4-5-20251001` → Claude Haiku 4.5 · `gpt-6-sol` → GPT-6 Sol ·
* `opencode/nemotron-3-ultra-free` → Nemotron 3 Ultra. No letter tile in
* front (kcn, 2026-09-27: the two-letter stand-in was noise); the room goes
* to the whole name.
*/
function _modelView(id) {
	if (id === "") return {
		label: "—",
		family: ""
	};
	const bare = id.includes("/") ? id.slice(id.lastIndexOf("/") + 1) : id;
	const title = (word) => word.charAt(0).toUpperCase() + word.slice(1);
	const claude = /^claude-([a-z]+)(?:-(\d+))?(?:-(\d{1,2}))?(?:-\d{8})?$/.exec(bare);
	if (claude) {
		const version = [claude[2], claude[3]].filter(Boolean).join(".");
		return {
			label: "Claude " + title(claude[1]) + (version ? " " + version : ""),
			family: "claude"
		};
	}
	const gpt = /^gpt-([\d.]+)(?:-([a-z]+))?$/.exec(bare);
	if (gpt) return {
		label: "GPT-" + gpt[1] + (gpt[2] ? " " + title(gpt[2]) : ""),
		family: "gpt"
	};
	if (/^[a-z]+$/.test(bare) && !id.includes("/")) return {
		label: title(bare),
		family: bare
	};
	const words = bare.replace(/-(free|contributor)(?=-|$)/g, "").split("-").filter((word) => word !== "");
	return {
		label: words.map((word) => /^[a-z]/.test(word) ? title(word) : word).join(" "),
		family: words[0] ?? bare
	};
}
/** "Opus 5.5 · high", with the model the task will run on while it waits and the one it ran on after. */
function modelLine(task, _live) {
	const requested = task.modelRequested ?? task.model;
	const ran = task.attempts > 0 && (task.modelUsed ?? "") !== "";
	const used = ran ? task.modelUsed ?? "" : "";
	return {
		model: ran ? used : requested || task.model,
		effort: (ran ? task.effortUsed : "") || task.effortRequested || "",
		fallback: ran && requested !== "" && used !== requested
	};
}
function _notifyState(task, ch, live) {
	if ((task.notifyFailed ?? []).includes(ch)) return "failed";
	if ((task.notified ?? []).includes(ch)) return "sent";
	return live ? "planned" : "unknown";
}
function notifyChannels(task) {
	return [.../* @__PURE__ */ new Set([
		...task.notify ?? [],
		...task.notified ?? [],
		...task.notifyFailed ?? []
	])];
}
/**
* An ended task's (or round's) ONE state: the runner's verdict and the
* model's report folded into the role that most needs the reader. Both axes
* stay readable: the chip's title says both, the detail layer shows both.
*/
function _endedState(state, outcome, t) {
	const title = executionText(state, t) + (outcome === "" && state !== "ok" ? "" : " · " + reportText(outcome, t, state));
	const word = state === "failed" ? "failed" : state === "timeout" ? "timeout" : state === "cancelled" ? "cancelled" : state === "queued" ? "notStarted" : state === "quota" ? "quota" : state === "blocked" || outcome === "BLOCKED" ? "blocked" : ![
		"ok",
		"partial",
		"unverified"
	].includes(state) ? "unknown" : outcome === "DONE" ? "done" : outcome === "PARTIAL" ? "partial" : "noReport";
	const role = {
		failed: "fail",
		timeout: "fail",
		cancelled: "off",
		notStarted: "off",
		quota: "partial",
		blocked: "partial",
		done: "done",
		partial: "partial",
		noReport: "unknown",
		unknown: "unknown"
	}[word];
	return {
		text: t("queue.verdict." + word),
		role,
		title
	};
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
const FACT_ORDER = [
	"model",
	"filed",
	"tries",
	"receipt",
	"when",
	"took",
	"cost"
];
const ROW_KINDS = {
	source: {
		lead: true,
		value: true,
		facts: []
	},
	head: {
		lead: true,
		value: false,
		facts: []
	},
	task: {
		lead: true,
		value: false,
		facts: [
			"model",
			"tries",
			"when",
			"took",
			"cost"
		]
	},
	ended: {
		lead: true,
		value: false,
		facts: [
			"model",
			"receipt",
			"when",
			"took",
			"cost"
		]
	},
	round: {
		lead: true,
		value: false,
		facts: [
			"filed",
			"when",
			"took"
		]
	}
};
/** A clock for a fixed cell: "19:40" today, "10/4 19:40" another day. */
function clockOf(ms, now) {
	const d = new Date(ms);
	const n = new Date(now);
	const hm = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
	return d.toDateString() === n.toDateString() ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
}
/**
* A live task's state chip: the short word (the group head already names the
* agent), its role, and the whole phrase (_taskStatus: which lock, the wake
* and the window it waits for) as the chip's title. A wake time is the 'when'
* cell, where an ended task keeps when it ended.
*/
function _taskState(task, t, now = Date.now(), windows) {
	const status = _taskStatus(task, t, now, windows);
	const stamp = (ms) => resetStampOf(t, {
		resetAt: "",
		resetAtMs: ms
	}, now);
	const since = task.startedAtMs ?? task.queuedAtMs;
	const when = (task.waiting === "quota" || task.waiting === "retry") && task.wakeAtMs !== null ? {
		text: clockOf(task.wakeAtMs, now),
		said: t("queue.fact.wakes", { time: stamp(task.wakeAtMs) }),
		voice: "warn"
	} : since != null ? {
		text: clockOf(since, now),
		said: t(_slotOf(task) === null ? "queue.fact.queuedAt" : "queue.fact.startedAt", { time: stamp(since) })
	} : null;
	const slot = _slotOf(task);
	const word = task.cancelling ? "cancelling" : task.waiting === "lock" ? task.position ? "queuedAt" : "queued" : task.waiting === "slot" ? "slot" : task.waiting === "memory" ? "memory" : task.waiting === "quota" ? "quota" : task.waiting === "retry" ? "retry" : slot === null ? "starting" : slot.slot === "1" ? "running" : "runningSlot";
	const role = word === "running" || word === "runningSlot" ? "run" : word === "queued" || word === "queuedAt" || word === "slot" ? "queue" : word === "quota" ? "sleep" : word === "cancelling" ? "off" : "wait";
	return {
		chip: {
			text: t("queue.tag." + word, {
				n: task.position ?? 0,
				slot: slot?.slot ?? ""
			}),
			role,
			title: status.text
		},
		when
	};
}
/** The model cell: the full model name and effort, and the fallback mark when it ran on another model. */
function modelFact(task, live, t) {
	const m = modelLine(task, live);
	if (m.model === "") return null;
	const text = _modelView(m.model).label + (m.effort ? " · " + m.effort : "");
	const requested = task.modelRequested ?? "";
	return {
		text,
		title: m.model,
		said: text + (m.fallback ? " · " + t("queue.fallbackTitle", { requested: _modelView(requested).label }) : ""),
		mark: m.fallback ? {
			role: "fallback",
			text: t("queue.fallbackMark"),
			title: t("queue.fallbackTitle", { requested: _modelView(requested).label })
		} : null
	};
}
/** The cost cell: the API-price estimate, 'free', or '—' when the model has no price row (title says which). */
function costFact(task, t, live) {
	const cost = _costOf(task);
	if (cost === null) return null;
	const legend = t("queue.chip.cost") + (live ? " · " + t("queue.d.costLive") : "");
	return cost.kind === "unpriced" ? {
		text: "—",
		said: t("queue.chip.unpriced"),
		title: t("queue.chip.unpriced") + " · " + legend,
		voice: "quiet"
	} : {
		text: cost.kind === "free" ? t("queue.chip.free") : cost.short,
		said: legend + " " + cost.short,
		title: legend
	};
}
/** A live task as a row: state chip; model, tries; when it wakes, how long, cost so far. */
function taskRow(task, t, now, open, windows) {
	const state = _taskState(task, t, now, windows);
	const since = task.queuedAtMs ?? task.startedAtMs;
	const running = _slotOf(task) !== null;
	const tries = [task.attempts > 1 ? t("queue.attempt", { n: task.attempts }) : null, task.stalls ? t("queue.stalls", { n: task.stalls }) : null].filter((part) => part !== null);
	return {
		kind: "task",
		key: task.id,
		lead: {
			agent: task.agent,
			size: 12
		},
		name: task.name,
		state: state.chip,
		facts: {
			model: modelFact(task, true, t),
			tries: tries.length === 0 ? null : {
				text: tries.join(" · "),
				voice: task.stalls ? "warn" : void 0
			},
			when: state.when,
			took: since == null ? null : {
				text: durationOf(t, now - since),
				said: t(running ? "queue.chip.elapsed" : "queue.chip.waiting", { time: durationOf(t, now - since) })
			},
			cost: costFact(task, t, true)
		},
		open: () => {
			open(task.id);
		},
		attrs: {
			"data-tq-task": task.id,
			"data-tq-waiting": task.waiting
		}
	};
}
/** An ended task as a row: its one verdict; model and receipts; when, how long, what it cost. */
function endedRow(task, t, now, open) {
	const stamp = (ms) => resetStampOf(t, {
		resetAt: "",
		resetAtMs: ms
	}, now);
	return {
		kind: "ended",
		key: task.id,
		lead: {
			agent: task.agent,
			size: 12
		},
		name: task.name,
		state: _endedState(task.state, task.outcome, t),
		facts: {
			model: modelFact(task, false, t),
			receipt: notifyChannels(task).length === 0 ? null : {
				text: "",
				receipts: notifyChannels(task).map((ch) => ({
					ch,
					state: _notifyState(task, ch, false)
				})),
				said: notifyChannels(task).map((ch) => t("queue.notify." + _notifyState(task, ch, false), { ch: t("queue.ch." + ch) })).join(" · ")
			},
			when: task.updatedAtMs === null ? null : {
				text: agoOf(t, now - task.updatedAtMs),
				title: t("queue.d.endedAt") + " " + stamp(task.updatedAtMs)
			},
			took: task.startedAtMs === null || task.updatedAtMs === null ? null : {
				text: durationOf(t, task.updatedAtMs - task.startedAtMs),
				said: t("queue.chip.took", { time: durationOf(t, task.updatedAtMs - task.startedAtMs) })
			},
			cost: costFact(task, t, false)
		},
		open: () => {
			open(task.id);
		},
		attrs: {
			"data-tq-task": task.id,
			"data-tq-waiting": ""
		}
	};
}
/**
* What a round routed through the filing gate, from the third `/` field patrol.sh writes
* (`P1#2240 P2#2241 +2 digest +1 comment`, 2026-10-01): each issue with its severity, how many
* findings went to the digest, how many were added to an issue on the same root cause. A P0 is
* said as a warning. Null when the round filed nothing (or ran before the field existed).
*/
function roundFiled(filed, t) {
	const issues = [...filed.matchAll(/\b(P[0-3])#(\d+)/g)].map((m) => ({
		sev: m[1],
		n: m[2]
	}));
	const digest = Number(/\+(\d+) digest\b/.exec(filed)?.[1] ?? 0);
	const comment = Number(/\+(\d+) comment\b/.exec(filed)?.[1] ?? 0);
	const parts = [
		...issues.length > 0 ? [{ text: t("queue.round.issueCount", { n: issues.length }) }] : [],
		...issues.map(({ sev, n }) => ({
			text: `${sev} #${n}`,
			severity: sev,
			href: `https://github.com/KCNyu/clawock/issues/${n}`
		})),
		...digest > 0 ? [{ text: t("queue.round.digest", { n: String(digest) }) }] : [],
		...comment > 0 ? [{ text: t("queue.round.comment", { n: String(comment) }) }] : []
	];
	if (parts.length === 0) return null;
	return {
		text: parts.map((part) => part.text).join(" · "),
		parts,
		said: t("queue.round.filed", { what: parts.map((part) => part.text).join(", ") }),
		title: filed,
		voice: issues.some(({ sev }) => sev === "P0") ? "warn" : void 0
	};
}
/** A finished patrol round as a row (rounds.tsv: `[preempted:|yielded:]STATE[/OUTCOME[/FILED]]`). */
function roundRow(round, t, now) {
	const how = /^(preempted|yielded):/.exec(round.result)?.[1] ?? "";
	const [state = "", outcome = "", filed = ""] = round.result.slice(how === "" ? 0 : how.length + 1).split("/");
	const ended = localStampMs(round.endedAt);
	return {
		kind: "round",
		key: "round-" + round.endedAt + round.round,
		lead: { section: "patrol" },
		name: round.axis === "" ? round.round : t("queue.round.name", {
			round: round.round,
			axis: round.axis
		}),
		state: how === "preempted" ? {
			text: t("queue.round.preempted"),
			role: "partial",
			title: round.result
		} : how === "yielded" ? {
			text: t("queue.round.yielded"),
			role: "off",
			title: round.result
		} : {
			..._endedState(state, outcome, t),
			title: round.result
		},
		facts: {
			filed: roundFiled(filed, t),
			when: ended === null ? null : {
				text: agoOf(t, now - ended),
				title: t("queue.d.endedAt") + " " + round.endedAt
			},
			took: round.seconds === null ? null : {
				text: durationOf(t, round.seconds * 1e3),
				said: t("queue.chip.took", { time: durationOf(t, round.seconds * 1e3) })
			}
		},
		attrs: { "data-tq-round": round.round }
	};
}
/** Live tasks of one agent in the order they hold / will take its lock. */
function groupOrder(tasks, queue) {
	const rank = (task) => {
		if (task.slot !== "" || queue?.holder === task.id) return 0;
		const at = queue?.order.indexOf(task.id) ?? -1;
		return at >= 0 ? 1 + at : 1e3;
	};
	return [...tasks].sort((a, b) => rank(a) - rank(b) || (a.queuedAtMs ?? a.startedAtMs ?? 0) - (b.queuedAtMs ?? b.startedAtMs ?? 0));
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
function _panelSources(providers, queue) {
	const dispatcher = queue !== null && queue.available;
	const byId = new Map(providers.map((row) => [row.provider, row]));
	const out = [];
	const placed = /* @__PURE__ */ new Set();
	for (const join of PROVIDER_JOIN) {
		const provider = join.provider === null ? null : byId.get(join.provider) ?? null;
		if (join.agent === null ? provider === null : provider === null && !dispatcher) continue;
		const key = join.provider ?? join.agent;
		out.push({
			key,
			label: provider?.label ?? _agentLabel(join.agent ?? key),
			join,
			provider,
			agent: dispatcher ? join.agent : null
		});
		placed.add(key);
	}
	if (dispatcher) {
		const agents = [.../* @__PURE__ */ new Set([...(queue.slotLimits ?? []).map((l) => l.agent), ...queue.active.map((t) => t.agent)])];
		for (const agent of agents) {
			if (agent === "" || placed.has(agent) || PROVIDER_JOIN.some((j) => j.agent === agent)) continue;
			out.push({
				key: agent,
				label: _agentLabel(agent),
				join: null,
				provider: null,
				agent
			});
			placed.add(agent);
		}
	}
	for (const provider of providers) {
		if (placed.has(provider.provider)) continue;
		out.push({
			key: provider.provider,
			label: provider.label,
			join: null,
			provider,
			agent: null
		});
	}
	return out.map((source, at) => ({
		source,
		at,
		rank: sourceRank({
			provider: source.provider?.provider ?? source.join?.provider,
			agent: source.agent ?? source.join?.agent
		})
	})).sort((a, b) => a.rank - b.rank || a.at - b.at).map(({ source }) => source);
}
/** Where the free pool is: the model the latest opencode task used, and the next one in file order. */
function _poolPosition(result) {
	const pool = result?.opencodePool ?? [];
	const used = [...result?.active ?? [], ...result?.recent ?? []].filter((task) => task.agent === "opencode").find((task) => (task.modelUsed ?? "") !== "" && task.attempts > 0)?.modelUsed ?? "";
	if (pool.length === 0) return used === "" ? null : {
		current: used,
		next: "",
		fromOrder: false
	};
	const at = pool.indexOf(used);
	if (at < 0) return {
		current: pool[0],
		next: pool[1] ?? pool[0],
		fromOrder: true
	};
	return {
		current: used,
		next: pool[(at + 1) % pool.length],
		fromOrder: false
	};
}
/**
* A queue's state chip, the same on the folded line and on its group's head:
* the ONE state that most needs the reader, with its count — asleep on quota,
* then queued behind the lock or a slot, then another wait, then running. A
* wait outranks running because a queue implies its holder runs. Idle is no
* chip at all. `text` is every count (the line's aria-label and title).
*/
function _queueState(t, tasks) {
	const run = tasks.filter((task) => task.slot !== "").length;
	const queued = tasks.filter(queuedFor).length;
	const quota = tasks.filter((task) => task.waiting === "quota").length;
	const other = tasks.filter((task) => task.waiting === "retry" || task.waiting === "memory").length;
	const present = [
		[
			"panel.q.quota",
			quota,
			"sleep"
		],
		[
			"panel.q.queued",
			queued,
			"queue"
		],
		[
			"panel.q.wait",
			other,
			"wait"
		],
		[
			"panel.q.run",
			run,
			"run"
		]
	].filter(([, n]) => n > 0);
	const text = present.length === 0 ? t("panel.q.idle") : present.map(([key, n]) => t(key, { n })).join(" · ");
	const top = present[0];
	return {
		text,
		chip: top === void 0 ? null : {
			text: t(top[0], { n: top[1] }),
			role: top[2],
			title: text
		}
	};
}
/**
* A source's value column: the allowance headline (used % of the first
* window, or the balance) and its tone; for the free pool, "free" — where
* the rotation stands is a fact of its group. `reset` (the headline window's,
* resetStampOf) is read out in the line's label; the clocks themselves are
* drawn once, on the group's window bars.
*/
function sourceReading(source, row, queue, t) {
	if (row !== void 0) return {
		value: row.view.value,
		reset: row.view.reset === null ? null : "↻ " + row.view.reset,
		tone: row.view.tone,
		level: row.view.level,
		title: row.view.title
	};
	if (source.join?.kind === "pool") {
		const pos = _poolPosition(queue);
		const size = queue?.opencodePool?.length ?? 0;
		return {
			value: t("panel.free"),
			reset: null,
			tone: "none",
			level: null,
			title: (pos === null ? t("panel.poolUnread") : t("panel.pool", {
				current: pos.current,
				next: pos.next || "—"
			}) + (pos.fromOrder ? t("panel.poolOrder") : "")) + (size > 1 ? " · " + t("panel.poolSwap", { n: size }) : "")
		};
	}
	return {
		value: "—",
		reset: null,
		tone: "none",
		level: null,
		title: ""
	};
}
/** The patrol phase's role: running blue, giving way amber (a wait), between rounds off, stopped red. */
const PATROL_ROLE = {
	running: "run",
	yielding: "wait",
	waiting: "off",
	stopped: "fail",
	unknown: "unknown"
};
/** rounds.tsv's local "YYYY-MM-DD HH:MM:SS" as epoch ms, null when it is not one. */
function localStampMs(stamp) {
	const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(stamp.trim());
	return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] ?? 0)).getTime() : null;
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
function _patrolReason(detail) {
	const wrap = /^asking \S+ to wrap up within \d+s: (.*)$/.exec(detail);
	const why = wrap?.[1] ?? detail.replace(/^(?:waiting: |preempting \S+?(?: after a \d+s wrap-up grace)?: )/, "");
	const manual = /^(\S+) is (?:waiting for (?:an \S+ run slot|its agent lock|the \S+ lock)|queued behind the round's \S+ lock)/.exec(why);
	return {
		kind: manual ? "manual" : /^the \S+ run slot is busy$/.test(why) ? "slot" : /^memory telemetry unavailable/.test(why) ? "memoryUnread" : /^memory (?:headroom low|pressure):/.test(why) ? "memory" : "other",
		task: manual?.[1] ?? "",
		wrapUp: wrap !== null
	};
}
/** The supervisor's live status as the patrol head's caption: when the next round is, what it runs now, or why it gives way. */
function patrolCaption(result, t, now) {
	const patrol = result.patrol;
	const reason = _patrolReason(patrol.detail);
	const current = result.active.find((task) => task.id === patrol.round);
	const dispatched = /round (\S+) \(([^)]+)\)/.exec(patrol.detail);
	const axis = dispatched?.[2] ?? /^patrol-(.+)-\d{8}-\d{6}$/.exec(patrol.round)?.[1] ?? "";
	const out = [];
	if (patrol.phase === "waiting" && patrol.untilMs !== null) {
		out.push({ text: t("queue.patrolState.waitingUntil", { time: resetStampOf(t, {
			resetAt: "",
			resetAtMs: patrol.untilMs
		}, now) }) });
		out.push({ text: t(patrol.untilMs > now ? "queue.patrol.remaining" : "queue.patrol.due", { time: durationOf(t, Math.max(0, patrol.untilMs - now)) }) });
	}
	if (patrol.phase === "yielding" || reason.wrapUp) {
		const why = reason.kind === "manual" ? t("queue.patrol.giveWay") : reason.kind === "slot" ? t("queue.patrol.waitSlot") : reason.kind === "memory" ? t("queue.patrol.memory") : reason.kind === "memoryUnread" ? t("queue.patrol.memoryUnread") : t("queue.patrol.otherReason");
		if (reason.wrapUp) out.push({
			text: t("queue.patrol.wrapUp"),
			voice: "warn"
		});
		out.push({
			text: why,
			voice: "warn",
			title: patrol.detail
		});
		if (reason.task !== "") out.push({
			text: reason.task,
			title: t("queue.patrol.forTask", { id: reason.task })
		});
	}
	if (patrol.phase === "running" || patrol.phase === "yielding" && current !== void 0) {
		if (dispatched || axis) out.push({
			text: dispatched ? t("queue.round.name", {
				round: dispatched[1],
				axis
			}) : axis,
			title: patrol.round
		});
		if (current?.startedAtMs != null) out.push({ text: t("queue.chip.elapsed", { time: durationOf(t, now - current.startedAtMs) }) });
		if (current !== void 0 && current.waiting !== "") out.push({
			text: _taskStatus(current, t, now).text,
			voice: "warn"
		});
	}
	return out;
}
/** The cost cell: an API-price estimate, 'free', or '—' when the model is unpriced; null when nothing was recorded. */
function _costOf(task) {
	if (task.tokensTotal == null) return null;
	const cost = task.costUsd ?? "";
	if (cost === "free") return {
		short: "free",
		kind: "free"
	};
	if (/^\d+(\.\d+)?$/.test(cost)) return {
		short: "$" + cost,
		kind: "usd"
	};
	return {
		short: "—",
		kind: "unpriced"
	};
}
/**
* A source as a row: the sidebar's folded line and its group's head in the
* panel are this one view (the same glyph, name and value in the same
* columns), so the line a reader taps is the line the panel opens on. The
* folded line adds the queue's one state chip (its tasks are not on screen);
* the head adds its caption — the plan, the run slots, the pool — in words.
*/
function sourceView(source, row, result, t) {
	const reading = sourceReading(source, row, result, t);
	const queue = source.agent === null || result === null || !result.available ? null : _queueState(t, result.active.filter((task) => task.agent === source.agent));
	const lane = source.agent === null || result === null || !result.available ? void 0 : _slotLanes(result).find((l) => l.agent === source.agent);
	const pool = source.join?.kind === "pool" ? _poolPosition(result) : null;
	const poolSize = result?.opencodePool?.length ?? 0;
	return {
		kind: "source",
		key: source.key,
		lead: { source },
		name: source.label,
		value: {
			text: reading.value,
			tone: reading.tone,
			level: reading.level
		},
		state: queue?.chip ?? null,
		facts: {},
		caption: [
			{ text: source.join?.plan === void 0 ? "" : t(source.join.plan) },
			lane === void 0 ? { text: "" } : {
				text: t("queue.slotCount", {
					used: lane.used,
					max: lane.max ?? "—"
				}),
				voice: lane.tone === "stale" ? "warn" : void 0,
				title: t("queue.lanesTitle")
			},
			source.join?.kind !== "pool" ? { text: "" } : pool === null ? { text: t("panel.poolUnread") } : {
				text: t("panel.pool", {
					current: _modelView(pool.current).label,
					next: pool.next === "" ? "—" : _modelView(pool.next).label
				}) + (pool.fromOrder ? t("panel.poolOrder") : ""),
				title: reading.title
			},
			poolSize > 1 && source.join?.kind === "pool" ? {
				text: t("panel.poolSize", { n: poolSize }),
				title: t("panel.poolSwap", { n: poolSize })
			} : { text: "" }
		],
		reading,
		queue
	};
}
/** Provider rows with their display projection: what every surface of the cell reads. */
function balanceRows(result, t, now) {
	return (result?.providers ?? []).map((provider) => ({
		...provider,
		view: _rowDisplay(provider.result, t, now),
		note: _balanceNote(provider.result, t)
	}));
}
/** The provider windows of an agent (a quota wait names the reset it waits for). */
function agentWindows(rows, agent) {
	const join = PROVIDER_JOIN.find((j) => j.agent === agent);
	return (join?.provider ? rows.get(join.provider) : void 0)?.result.snapshot?.windows;
}
function allowanceDetail(row, t, now) {
	const wins = row.result.snapshot === null ? [] : windowsOf(t, row.result, now);
	if (wins.length > 0) return {
		kind: "windows",
		windows: wins.map((w) => {
			const fill = w.percent === null ? null : Math.max(0, Math.min(100, Math.round(w.percent)));
			return {
				label: w.label,
				percent: w.percent,
				fill,
				reset: w.reset,
				state: row.view.tone === "stale" ? "stale" : _usedLevel(fill, row.result.threshold)
			};
		})
	};
	if (row.note !== null) return null;
	const title = row.view.title;
	if (title === "") return null;
	const prefix = t("balance.apiBalance") + " · ";
	return {
		kind: "text",
		text: title.startsWith(prefix) ? title.slice(prefix.length) : title
	};
}
function panelGroup(source, result, rows, t, now, open) {
	const row = source.provider === null ? void 0 : rows.get(source.provider.provider);
	const agent = source.agent;
	const tasks = agent === null || result === null ? [] : result.active.filter((task) => task.agent === agent);
	const queue = agent === null ? void 0 : (result?.queues ?? []).find((q) => q.agent === agent);
	const notes = [];
	if (queue?.held && tasks.every((task) => task.id !== queue.holder)) notes.push(queue.holder !== "" ? t("queue.holderOther", { id: queue.holder }) : t("queue.holderUnnamed"));
	if (queue?.quotaUntilMs) notes.push(t("queue.quotaHint", {
		time: resetStampOf(t, {
			resetAt: "",
			resetAtMs: queue.quotaUntilMs
		}, now),
		by: queue.quotaBy
	}));
	const snapshotAt = row?.result.snapshot?.asOf ? Date.parse(row.result.snapshot.asOf) : NaN;
	const balanceNote = row === void 0 || row.note === null ? null : row.result.status === "stale" && Number.isFinite(snapshotAt) ? t("panel.staleAt", {
		message: row.result.message ?? "—",
		time: resetStampOf(t, {
			resetAt: "",
			resetAtMs: snapshotAt
		}, now)
	}) : row.note;
	const { reading: _reading, queue: _queue, ...view } = sourceView(source, row, result, t);
	return {
		source,
		head: {
			...view,
			state: null,
			key: "head-" + source.key,
			attrs: { "data-pp-head": source.key }
		},
		row,
		balanceNote,
		detail: row === void 0 ? null : allowanceDetail(row, t, now),
		notes,
		tasks: groupOrder(tasks, queue).map((task) => ({
			task,
			row: taskRow(task, t, now, open, agentWindows(rows, task.agent))
		}))
	};
}
/** Ended work, newest first across agents: every ended task is resident (see RESIDENT_ROUNDS). */
function recentSection(result, t, now, open) {
	if (result === null || !result.available || result.recent.length === 0) return null;
	return {
		head: {
			kind: "head",
			key: "head-recent",
			lead: { section: "recent" },
			name: t("queue.recentHeading"),
			state: null,
			facts: {}
		},
		rows: result.recent.map((task) => endedRow(task, t, now, open))
	};
}
/**
* Patrol: a section head (the phase as its state chip, the live status as its
* caption), and one chronological history group. The raw supervisor journal
* is not a task conclusion; the head already projects its useful status.
*/
function patrolSection(result, t, now) {
	if (result === null || !result.available) return null;
	const patrol = result.patrol;
	return {
		head: {
			kind: "head",
			key: "head-patrol",
			lead: { section: "patrol" },
			name: t("queue.patrolHeading"),
			state: {
				text: t("queue.patrolState." + patrol.phase),
				role: PATROL_ROLE[patrol.phase] ?? "unknown",
				title: patrolPhraseOf(result, t, now)
			},
			facts: {},
			caption: patrolCaption(result, t, now),
			attrs: { "data-tq-patrol": patrol.phase }
		},
		rounds: (patrol.rounds ?? []).map((round) => roundRow(round, t, now))
	};
}
/** The ops entry's footer: its version and runner api, or why it is missing / skewed. */
function opsFooter(result, t) {
	if (result === null || !result.available || result.ops === void 0) return null;
	const skew = opsProblem(result, t);
	const ops = result.ops;
	return {
		text: skew !== "" ? skew : t("queue.ops.footer", {
			v: ops.version,
			runner: ops.runnerApi
		}),
		bad: skew !== "",
		version: ops.available ? ops.version : "missing"
	};
}
/**
* Why a half of the cell is not (fully) there: a failed or stale queue read, a
* host without the dispatcher, a failed balance read. `error` is a transport
* failure (the fetch never answered); an in-band failure arrives in the result.
*/
function panelNotices(input, t) {
	const { queue, queueError, balances, balanceError, rowCount } = input;
	const queueProblem = queueError ?? (queue !== null && (queue.status === "stale" || queue.status === "failed") ? queue.message : null);
	const out = [];
	if (queueProblem !== null && queueProblem !== "") out.push({
		key: "qerr",
		bad: true,
		text: t(queue === null || queue.status === "failed" ? "queue.readFailed" : "queue.staleWith", { message: queueProblem })
	});
	if (queueProblem === null && queue === null) out.push({
		key: "qloading",
		bad: false,
		text: t("panel.queueLoading")
	});
	if (queueProblem === null && queue !== null && !queue.available) out.push({
		key: "qunavailable",
		bad: false,
		text: t("panel.queueUnavailable")
	});
	if (balanceError !== null) out.push({
		key: "berr",
		bad: true,
		text: rowCount === 0 ? t("balance.readFailed", { message: balanceError }) : t("balance.staleWith", { message: balanceError })
	});
	return out;
}
function panelModel(input, t, now, open = () => {}) {
	const rows = balanceRows(input.balances, t, now);
	const byProvider = new Map(rows.map((row) => [row.provider, row]));
	const sources = _panelSources(input.balances?.providers ?? [], input.queue);
	return {
		title: t("panel.title"),
		notices: panelNotices({
			...input,
			rowCount: rows.length
		}, t),
		empty: sources.length === 0 && input.balanceError === null ? input.balances === null ? t("balance.reading") : t("panel.noSources") : null,
		groups: sources.map((source) => panelGroup(source, input.queue, byProvider, t, now, open)),
		recent: recentSection(input.queue, t, now, open),
		patrol: patrolSection(input.queue, t, now),
		footer: opsFooter(input.queue, t)
	};
}
//#endregion
//#region src/text.ts
/**
* The task chip's provider panel as plain text: the ASCII rendering of the same
* panel.ts model the sidebar draws, for a chat reply (OpenClaw `/dispatch-list`).
* It decides nothing — groups, rows, words, order and folding all come from the
* model. Only the drawing is its own: a role is a character where the chip has
* a glyph, a window's used share is a bar of blocks where the chip has a
* hairline, and nothing relies on colour or on a monospaced font (WeChat has
* neither).
*/
/** A role's glyph as one character, in the shape the chip draws (panel.ts STATE_ROLES). */
const ROLE_MARK = {
	run: "●",
	queue: "○",
	sleep: "☾",
	wait: "⌛",
	done: "✓",
	partial: "◐",
	fail: "✕",
	off: "–",
	unknown: "?",
	fallback: "↩"
};
const RECEIPT_MARK = {
	sent: "✓",
	failed: "✕",
	unknown: "?",
	planned: "…"
};
const BAR_CELLS = 10;
/** A used share as a bar of blocks: ▓ used, ░ left. */
function bar(fill) {
	if (fill === null) return "░".repeat(BAR_CELLS);
	const used = Math.max(0, Math.min(BAR_CELLS, Math.round(fill / (100 / BAR_CELLS))));
	return "▓".repeat(used) + "░".repeat(BAR_CELLS - used);
}
function factText(fact, t) {
	const words = fact.receipts != null ? fact.receipts.map(({ ch, state }) => t("queue.ch." + ch) + RECEIPT_MARK[state]).join(" ") : fact.text;
	return fact.mark == null ? words : words + " " + ROLE_MARK[fact.mark.role] + fact.mark.text;
}
/** One row on one line: name, value, [state], then its kind's facts in FACT_ORDER; a head's caption on the next. */
function rowText(view, t) {
	const kind = ROW_KINDS[view.kind];
	const value = kind.value && view.value != null ? (view.value.tone === "low" ? "⚠" : "") + view.value.text : null;
	const state = view.state === null ? null : ROLE_MARK[view.state.role] + view.state.text;
	const facts = FACT_ORDER.filter((slot) => kind.facts.includes(slot) && view.facts[slot] != null).map((slot) => factText(view.facts[slot], t)).filter((text) => text !== "");
	const line = [
		view.name,
		value,
		state
	].filter((part) => part !== null && part !== "").join("  ");
	const caption = (view.caption ?? []).map((part) => part.text).filter((text) => text !== "");
	return [facts.length === 0 ? line : line + " · " + facts.join(" · "), ...caption.length === 0 ? [] : [caption.join(" · ")]];
}
const indent = (lines, by) => lines.map((line) => by + line);
function panelText(model, t) {
	const out = [model.title];
	for (const note of model.notices) out.push((note.bad ? "⚠ " : "") + note.text);
	if (model.empty !== null) out.push(model.empty);
	for (const group of model.groups) {
		out.push("");
		const [head, ...caption] = rowText(group.head, t);
		out.push("▌" + head, ...indent(caption, "  "));
		if (group.balanceNote !== null) out.push("  ⚠ " + group.balanceNote);
		if (group.detail?.kind === "windows") for (const w of group.detail.windows) {
			const pct = w.percent === null ? "—" : Math.round(w.percent) + "%";
			out.push(`  ${w.label} ${bar(w.fill)} ${pct}` + (w.reset === "" ? "" : " ↻" + w.reset));
		}
		else if (group.detail?.kind === "text") out.push("  " + group.detail.text);
		for (const note of group.notes) out.push("  " + note);
		for (const { row } of group.tasks) out.push("  • " + rowText(row, t)[0]);
	}
	if (model.recent !== null) {
		out.push("", "▌" + rowText(model.recent.head, t)[0]);
		for (const row of model.recent.rows) out.push("  • " + rowText(row, t)[0]);
	}
	if (model.patrol !== null) {
		const [head, ...caption] = rowText(model.patrol.head, t);
		out.push("", "▌" + head, ...indent(caption, "  "));
		const rounds = model.patrol.rounds;
		const resident = rounds.length <= 4 ? rounds.length : 1;
		for (const row of rounds.slice(0, resident)) out.push("  • " + rowText(row, t)[0]);
		if (rounds.length > resident) out.push("  " + t("queue.olderRounds", { n: rounds.length - resident }));
	}
	if (model.footer !== null) out.push("", (model.footer.bad ? "⚠ " : "") + model.footer.text);
	return out.join("\n");
}
//#endregion
//#region src/chat.ts
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
*/
/** Credential references resolved against the gateway config's `env` block (the balance services then fall back to process env). */
function gatewayCredentials(config) {
	return { async resolve(ref) {
		const env = config?.env;
		const value = env !== null && typeof env === "object" ? env[ref] : void 0;
		return typeof value === "string" && value !== "" ? { value } : void 0;
	} };
}
/** The reply for one read of both halves (the test seam: tests/decision_studio_plugin.spec.js compares it with the panel). */
function dispatchListText(input, t, now) {
	return panelText(panelModel(input, t, now), t);
}
function register(api) {
	const config = api.pluginConfig ?? {};
	const t = createTranslator(dictionaries[config.locale ?? "zh"] ?? dictionaries.zh);
	let balances = null;
	let queue = null;
	api.registerCommand({
		name: "dispatch-list",
		description: t("panel.title"),
		acceptsArgs: true,
		handler: async (ctx) => {
			const force = (ctx.args ?? "").trim() === "refresh";
			const workspace = ctx.config?.agents?.defaults?.workspace ?? process.env.CLAWOCK_WORKSPACE ?? join(homedir(), ".openclaw", "workspace");
			balances ??= createBalanceReader(gatewayCredentials(ctx.config), config);
			queue ??= createTaskQueueService(taskQueueConfig(config, workspace));
			const [balance, tasks] = await Promise.allSettled([balances.get(force), queue.get(force)]);
			const why = (reason) => (reason instanceof Error ? reason.message : String(reason)) || t("balance.unknownError");
			return { text: dispatchListText({
				balances: balance.status === "fulfilled" ? balance.value : null,
				balanceError: balance.status === "rejected" ? why(balance.reason) : null,
				queue: tasks.status === "fulfilled" ? tasks.value : null,
				queueError: tasks.status === "rejected" ? why(tasks.reason) : null
			}, t, Date.now()) };
		}
	});
}
//#endregion
export { register as default, dispatchListText };
