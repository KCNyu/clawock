# Todos 工作流核实与任务回溯改动

核实日期：2026-10-04。读取官网、23 篇中文文档和更新日志；更新日志当时最新条目为 2026-10-02。下面的“确证”指**公开使用文档明确记载，或更新日志记载已发布行为**，不是登录付费产品后的运行验证。网页原始快照保留在本次本机交付目录；文档中的服务端实现与安全声明未做黑盒验证。

人-Agent 关口与总管两项经 kcn 判断**不适用**，不要当成待补的差距。

## 核实后的产品模型

Todos 的单位是 **团队 → 项目 → todo → 构建 → 多次运行/对话回合 → 版本文档**。Todo 是持久的任务与对话容器，不是一次 CLI 进程。Agent 是团队资源，机器领取构建、提供并发槽；Agent 不占有某一台机器。每次运行在独立 git worktree 里工作，消息、方案、diff、token 用量归属到任务/构建。重新运行开启新构建并保留上次历史。

四列看板是九种相位的投影，而不是完整执行状态机。文档还区分了启动方式、运行时权限与最终验收：可以跳过规划；普通执行在确认/审核节点等待；已授权的总管可以代为执行决策，概览称此为全自动模式。独立 AI 审查是只读第二意见，审查后执行方自动收到意见修改，审查本身不确认或合并。我们不吸收这些人工停靠机制。

| 原始主张 | 核实结果与边界 | 公开依据 |
|---|---|---|
| 总管拆目标、派团队 | 文档确证“常驻跨项目对话”、优先级/路由/派单；没有仓库权限。用户要求的工作直接运行，自行提议的工作先采纳。营销里的“直到完成”不能理解为保证自动闭环 | [总管](https://todos.dev/zh/docs/chief)、[概览](https://todos.dev/zh/docs/overview) |
| 独立职责/模型/记忆、worktree 并行 | 文档确证；记忆按 Agent 独立，团队知识放技能。构建放在任意可用机器，机器并发配置 1–10。不是每个 Agent 永久拥有 worktree 或机器 | [概念](https://todos.dev/zh/docs/concepts)、[Agent](https://todos.dev/zh/docs/agents)、[机器](https://todos.dev/zh/docs/machines)、[记忆](https://todos.dev/zh/docs/memory) |
| 四态看板、“等你处理” | 确证列名为待开始/执行中/待处理/已完成。第三列汇总确认、审核、失败及无改动的问答产出；已完成列保留最近七天。概念页的相位“待处理”却指尚未开始，不能把同名词等同 | [总管](https://todos.dev/zh/docs/chief)、[Todo](https://todos.dev/zh/docs/todos)、[更新日志](https://todos.dev/zh/docs/changelog) 09-28 |
| 对话时间线播报进展与审核 | 对话流式输出、审查署名意见、总管关注后汇报确证。官网“主动汇报”与总管文档“不主动打扰/下次对话汇报”需按自动关注的具体规则理解。更新日志“信息流时间线修正”讲的是官网演示；**未证明有与 runner 状态转换等价的结构化事件台账** | [对话](https://todos.dev/zh/docs/conversation)、[AI 审查](https://todos.dev/zh/docs/ai-review)、[总管](https://todos.dev/zh/docs/chief)、更新日志 09-28 |
| 方案和 diff 是带版本关联文档 | 明确确证：方案每次修订保留版本，diff 按文件查看，过大时明确提示，运行历史保留各自方案、diff 与输入/输出 token。09-28 又说明已提交版本前的回退被锁定 | [方案与改动](https://todos.dev/zh/docs/plans-and-diffs)、更新日志 09-28 |
| 定时、项目、技能、密钥、机器用量是一等资源 | 各有资源/设置页与权限规则；定时规则归 todo 负责人，机器时长与推理共用积分池。外部 CLI 消耗个人订阅，不等于平台代付或实时金额余额 | [定时](https://todos.dev/zh/docs/schedules)、[项目](https://todos.dev/zh/docs/projects)、[技能](https://todos.dev/zh/docs/skills)、[密钥](https://todos.dev/zh/docs/secrets)、[平台机器](https://todos.dev/zh/docs/platform-machines)、[运行时](https://todos.dev/zh/docs/runtimes) |
| 历史任务可搜索回溯 | 09-07 更新日志明确全局搜索任务标题/描述/编号及资源；运行历史确证。**未证明支持全文搜索所有历史对话、日志或 diff**；不能沿用“Coding Agent 历史无法搜索”这一泛化营销比较 | 更新日志 09-07、[方案与改动](https://todos.dev/zh/docs/plans-and-diffs) |
| 手机 PWA + 语音想法 | 文档确证安装到主屏幕、iOS 通知须主屏应用、语音转 todo。未实际测试识别准确率或通知可靠性 | [手机端](https://todos.dev/zh/docs/mobile)、[收件箱](https://todos.dev/zh/docs/inbox) |
| 父子任务、依赖、fan-out | 文档证明多 todo 并行和可引用其他 todo，**没有证明 parent_id、依赖图、失败传播、join 或依赖调度**。自然语言拆单与多个 worktree 不等于 DAG | 概念/Todo/总管/对话/更新日志；这是证据缺口，不给竞品补写能力 |

## 和本机真实实现对照

`dispatch.sh` 与 `run-agent.sh` 实际已在 `ops/host/agent-dispatch/` 版本化，有原子装机和 `.before-update` 回滚。宿主 `dispatch.sh` 与调研基线仓库 SHA-256 相同：`cfa3d83b1fc12c1f196c95c201891aa2dccf86437c0ad2545f070be5b725bd3a`。本次**不改 runner 或 dispatch 生产脚本**。

每个 agent 各自串行锁和队列；本机 `MAX_RUNNING_CLAUDE/CODEX/OPENCODE=1`、总槽 3，并非整个宿主只跑一个 Agent。额度等待释放 agent 锁、保持 session 锁；账户额度 hint 防止后来任务无谓消耗尝试。三档看门狗、deadline、失败重试、quota-resume、append、完成/额度 notifier 均已存在。Quota 等待不耗失败重试，恢复会受独立 quota-resume 预算约束。新增人工中断不是缺口。

| 维度 | Todos 文档模型 | 本机实际模型、含义 |
|---|---|---|
| 编排 | 任务容器、多构建、并行机器槽；DAG 未确证 | 主会话 brief 派单，独立 systemd 单元；每 agent 队列/锁，独立 worktree 按仓库规约建立；无结构化 parent/dependency/join。多 agent 可以并行，不宜为小宿主加无证据的 fan-out |
| 审核与合并 | 版本方案、diff、可邀只读独立审查，确认/完成决策另行授权 | 仓库 AGENTS.md：worktree → PR → required CI → 作者自审 → squash merge → refresh_live。现成自动闭环；无需第二套审核门户 |
| 人-Agent 交互 | 两个默认停靠节点、可交总管代理；排队消息可改/撤回 | 派发即返回、跑完 notifier；append 可立刻续跑或 `--queue` 等本轮结束。维持现行授权规则，不增加中断通道 |
| 展示层级 | 看板摘要，任务内对话/版本文档，资源页管理队列与用量 | foot cell 按 provider/agent 汇总 → 面板队列/最近结束/patrol → 详情里的结果、只读入口、运行设置、额度、时间、用量、通知、原始记录。层级已合理，缺的是回溯证据和正确排序 |
| 余额/用量 | 平台积分与机器唤醒时长；按模型汇总输入输出 token、费用贡献图；外部 CLI 订阅窗口按账号汇总 | provider 余额/订阅窗口与重置时间、每 agent 队列/槽、任务输入/输出/缓存 token 与 API 价估算已有。估算不是订阅实付账单，现有说明保留；任务用量截至最近完成的 attempt，不冒充实时 |

实际状态字段不等于原派单的枚举：`PARTIAL` 是 `OUTCOME`，runner 终态是小写 `partial`；`stale` 是读数刷新失败回退旧快照，**不是任务生命周期状态**。

| 本机来源 | 展示应表达什么 | 与四列看板的关系 |
|---|---|---|
| 活单 `queued`，`WAITING=lock/slot/memory` | 资源等待、顺序与位置 | 他们分排队/机器资源；我们细分原因已有，不压成一个桶 |
| 活单 `running`，`WAITING=''` | 正在执行；attempt/stalls 当前计数 | 执行中 |
| 活单 `WAITING=quota/retry` | 自动等额度/重试，显示 WAKE_AT | 仍自动继续；不归“等人处理” |
| 终态 `ok` + `OUTCOME=DONE` | runner 正常结束、任务自报完成 | 不等价于 CI 或人工验收；摘要/PR 是证据 |
| `partial/unverified`，`OUTCOME=PARTIAL/BLOCKED` | 未完成或没有足够完成声明 | 保留真实结果；不自动重新跑，不新增人工等待态 |
| `failed/blocked/timeout/quota/cancelled` 终态 | 失败/未启动/超时/额度终止/取消 | 我们放“最近结束”，配语义标签，不伪装为成功 |
| queue/balance `status=stale` | 显示旧读数及刷新错误/时间 | 数据新鲜度，与任务状态正交 |

## 最该补的三件事（影响顺序、已实现）

1. **可靠的最近结束列表。** #2417：mtime 预选 `recent * 3` 会先丢掉 UPDATED 最新的任务。现在先读所有非 patrol、非活单的 `result.env`，仅收终态，按 UPDATED 排序并用 id 稳定打破平局，再 cap；只对入选项读取完整任务/日志。无有效 UPDATED 的旧记录置尾，不拿 mtime 假造事件时间。历史再漂亮也不能建在丢任务的名单上。
2. **任务事件时间线。** 详情新增只读按钮，复用现有 `queueAction('log')`，ops 的 JSON 附加 `timeline`，无新 RPC、无写操作、无 runner 变更。按需从已有日志提取启动、等锁/槽、尝试、额度/重试、看门狗、append 投递、设置修改、结束与最新通知回执；追加提交取文件名时间，与实际投递事件区分。模型/工具正文不进时间线。无日志、旧 ops、空记录分别提示；大日志取头尾各 2 MiB，最多展示 200 事件，截断显式说明，完整日志入口保留。不是完整审计保证：旧日志没写的事件不会补造，只有最新通知回执可由 result 恢复。
3. **追加要求可回溯。** 已有 `brief` 返回原任务书和按提交时间排序的独立追加文件；现在详情显示追加 #1/#2…、时间、投递状态及首行摘要，点按打开原文件。编号表示当前文件列表的顺序，文件名是稳定身份；**不声称 prompt.md 是不可变 v1，也不把 append 等同于整个方案的新版本**。原因写在追加正文里，UI 不猜测；没有摘要时保留文件入口。这样改善要求来源的阅读成本，不重复 PR 自审。

## 三类取舍与剩余清单

| 类别 | 项目 | 结论、触发条件或理由 |
|---|---|---|
| 现在做得到 | 主会话拆 brief、多 agent 独立执行、worktree 隔离、定时/patrol、技能/共享记忆、append、完成通知、PR/CI/自审/合并、预算与日志预览 | 沿用现有规约。Todos 的独立记忆不比本机共享修正天然更好，不改记忆体系 |
| 需要代码，本次做 | 最近结束排序、按需事件时间线、追加文件序列/摘要 | 上面三项；不动折叠阈值、连续段落分组、raw supervisor log |
| 需要代码，留清单 | 历史任务标题/id/结果搜索 | **值得后续评估，优先于重型看板**。当前最近五条限制查找；应走只读分页索引、按 id 打开，与活动轮询分开，先量任务数/查找频率。本次不凑第四项 |
| 需要代码，留清单 | 方案/diff 与任务的关联清单 | 有跨 PR 或非代码产物时才值得。最小 manifest 只引用 PR URL、commit、文档路径与内容 hash；不另存一套 diff、不新增审批。没有一致 producer 就不展示空“版本系统” |
| 需要代码，留清单 | 原生 events.jsonl | 提供完整、去歧义事件源有价值，但涉及 runner/dispatch 写入、原子性、失败策略与旧任务兼容。本次用已有证据，避免把日志推断升级成执行契约。只读 CLI 入口另附未应用 diff |
| 需要代码，不值得现在做 | 父子树、DAG/fan-out/join、自动失败传播 | 无真实依赖需求，竞品也未确证；2 核/2 GiB 与 per-agent=1 是真实边界。关系可先写 brief/PR 引用，不能为对标制造调度复杂度 |
| 需要代码，不值得做 | 把九种相位/四列看板硬套芯片，拖拽改变执行态 | 我们没有方案待批/改动待验收生命周期；现有 provider→队列→详情更适合窄侧栏。失败属于结束结果，额度等待是自动执行过程 |
| 需要代码，不值得现在做 | 模型费用贡献图/年度热图、实时 token 演出 | 当前余额窗口、任务估算/缓存细分已够用；订阅额度不是 API 实付。没有持续采集就不能画可靠实时图，且对任务回溯帮助有限 |
| 依赖平台，本机不适用 | Cloudflare 平台机器、团队积分/充值、跨机器账号调度、团队密钥服务/RBAC | 面向 SaaS 团队/多机器资源，不是本机 dispatcher 的能力差距；不迁移凭据、不增服务 |
| 依赖宿主，不适用本插件 | PWA 壳、扫码登录、语音转 todo、推送权限 | dsh/聊天宿主承担输入、登录和手机壳；插件不复制宿主产品功能 |
| 经用户判断不适用 | 人-Agent 关口、常驻总管 | 本机目标是 Agent 跑到底、完成投递。**不出方案、不实现、不保留成待补差距** |

## 生效与验证边界

- 核心改动：`ops/host/task_queue_ops.py`，插件 `src/taskqueue.ts`、`src/client.ts`、`src/copy.ts`、`src/styles.module.css` 及对应 `lib/`。
- 定向验证：超旧 mtime + 超过原 15 候选边界；未结束记录排除；早期日志事件、提交/投递分离、通知时间不冒充结束、秘密脱敏、长日志和事件截断、旧 ops 提示、详情只读动作/文件预览。
- UI 在真实 dsh 页面加载分支 bundle，以 WebKit + Playwright iPhone 13 配置 tap 实拍。模拟设备浏览器不是物理 iPhone；不靠合成 mouse-down 或截图推断 `:active`。实拍文件在本机交付目录，避免把真实任务/会话信息公开提交。
- 合并后 `refresh_live.sh` 快进；无重启安装插件与 queue ops。新 client 的时间线通过已加载 host 的现有 log RPC 可用。**最近结束排序在 host 模块内，dsh host 与 OpenClaw gateway 的完整新行为仍等待宿主安排重启**；安装不等于内存模块已更新。不会以重启干扰当前任务。
- `dispatch-timeline.proposed.patch` 是可选只读 CLI 入口方案，未应用、未安装。事件格式由 ops 单一维护；无需复制到 dispatch。若将来要全量持久事件，应另做 runner 仓库 PR 与故障注入，不能直接改宿主脚本。
