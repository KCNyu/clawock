# clawock-dsh

[![npm](https://img.shields.io/npm/v/clawock-dsh?label=NPM&style=flat-square&logo=npm&logoColor=white&labelColor=252b35&color=4b91c8)](https://www.npmjs.com/package/clawock-dsh)
[![Tests](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/ci.yml?label=TESTS&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-738391?style=flat-square&labelColor=252b35)](https://github.com/KCNyu/clawock/blob/master/LICENSE)

**AI argues. Code settles. The losses stay on the page.**

The [clawock](https://github.com/KCNyu/clawock) investment-decision workflow,
as a DeepSeek Harness plugin. A skill package that makes the agent walk four
steps — read the request, research and argue both sides, write the decision,
then let Python validate and settle it — plus a Decision Mind tab that renders
every real fill as an expandable decision trace inside the DSH web GUI.

The fourth step is the one that matters: the model never touches settlement.
Prices, FX, P&L and the scorecard are computed by code the agent cannot write
to, so a wrong call shows up as a loss on a public page instead of as a
better-sounding paragraph.

- **Live proof** — a real Hong Kong + US brokerage account, run this way every
  trading day: <https://kcnyu.github.io/clawock/>
- **Evidence, wins and losses both** — <https://kcnyu.github.io/clawock/evidence.html>
- **Source and issues** — <https://github.com/KCNyu/clawock>

![Decision Mind tab inside the DSH web GUI](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-decision-mind.png)

```bash
dsh plugin --profile web add clawock-dsh
```

Installation needs one more step on rc.6 and later (skill discovery), covered
in the installation section below. The rest of this README is in Chinese.

---

DeepSeek Harness 的投资决策工作流插件:agent 走完
「读请求 → 研究 + 正反辩论 → 写决策 → Python 校验结算」四步,
web GUI 多一个 Decision Mind tab 把每笔成交的决策轨迹钉在页面上。

第四步是核心:**模型永远不能给自己打分**——价格、风控、账本、战绩全部由
Python 独立结算,agent 写不到那段代码,下错单显示为一笔公开页上的亏损,
而不是一段更好听的文字。

## 前提

agent 所在环境需要 Python ≥ 3.11,并且:

```bash
python -m pip install clawock
```

## 安装

三步,缺一不可(rc.6 及以后 DSH 只扫项目根与用户根、不扫 node_modules,
所以 skill 必须手动放一步到可发现的位置):

```bash
# 1. 装插件本体
dsh plugin --profile web add clawock-dsh

# 2. 把 skill 放到 DSH 可发现的位置(任选其一,不选这步 agent 不会带这个 skill)
cp -r ~/.dsh/profiles/web/node_modules/clawock-dsh/skills/investment-decision ~/.dsh/skills/
# 或项目级:
cp -r ~/.dsh/profiles/web/node_modules/clawock-dsh/skills/investment-decision <project>/.agents/skills/

# 3. 重启 web profile
```

重启后 skill 即出现在 agent 的 skill 目录。

## 快速开始

装完直接问:

```
你:帮我分析一下 0700.HK 能不能加点仓
```

agent 走完四步,给你一张决策卡——bull / bear / thesis / confidence /
action / run_id,判定和结算是 Python 算的,不是模型说的:

![决策卡示例:agent 跑完一轮决策后输出的回执卡(示例输出,非真实结算)](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/decision-card-example.png)

## 你得到什么

### 一个会辩论、不会自评的 agent

- 主动收集**正反双方**证据——发布时 Python 强制至少一条 opposing 论据,
  熊方必须是真反驳,不是稻草人;
- 有界行动:动作、数量、触发条件写进 `decision.json`,由 Python 校验;
- 情绪状态自认,non-calm 才会出现在面板里。

### 一个只读的 Decision Mind tab

装完后 web GUI 的会话视图多一个 **Decision Mind** tab。它只做一件事:
**每一笔真实成交,都是一条可以点开的决策轨迹**。

- **账本式分组**:一天一组,行内 = 日期 · 标的 · 动作 · 数量@价 ·
  T+1 判定 · 与计划反向标记 · 盈亏焦点数字,同组对齐、竖着扫就是比同一件事;
- **T+1 判定**用官方逐日收盘(`memory/bars/`),绝不读实时快照;未判出就
  显式写「T+1 未判」,不假装没这回事;
- **点开一条轨迹**:当时的计划 → 真实成交(与计划同向/反向)→ T+1 收盘 →
  本笔已实现 / 该持仓当前浮动——两个量永不共用一个「盈亏」标签;
- 没有当日计划的成交显式标注——不假装有判断。

面板是只读 Remote,不改任何文件;结算仍归 clawock 自己的机制。

### 侧边栏左下角的多 Provider 余额

web GUI **左侧栏底部、Settings 正上方**常驻一行余额读数,不跟随当前会话
(没开会话也在)——头条显示**一个** provider 的读数(provider 名 + 数字;默认
第一行;在面板里点任意一行即钉选为头条,选择存在注册 store 里,重挂不丢),
带双窗口的 provider(MiniMax 5h+周、Claude 会话+本周)在头条直接附**周限额副
读数**(侧栏放不下时省略号截断,悬停 title 有全文);侧栏收起时只剩一枚状态点。
点它在这一行正上方弹出**余额面板**(对话留在原处不被替换;钉选、刷新不会关掉它,再点这一行、按 Esc 或点面板外面才收起),看全部 provider 明细(每窗口一行文字读数 + 发丝进度条;条的
填充色按用量档位走:低=绿、≥60% 黄、≥80% 红,阈值由 lowPct 派生)与手动
刷新。

挂载点是 DSH 公开的 `sidebar.footer.action`(侧栏底部 Settings 旁的动作座位),
弹出层照抄宿主自己同座位的 Cordis 面板:固定定位锚在这一行上方、点外面/Esc 关闭。
(第一版曾用 keyed `main` 中间面板,点一下整栏对话就被换成一张几乎空白的页,
体感是「被切走」,已改掉。)插件在 DSH `0.1.5-rc.1` 起(有 `ctx.layout.selectPanel`)
的宿主上挂到侧栏;更早的宿主退回会话标题行右侧 utilities 座位的毛玻璃芯片
(行为同上)。它不是 Decision Mind 的一部分:账户状态是应用级 chrome,
不是交易语义。配额读数一律是**已使用 %**(kcn:「剩余」不直观;头条数字
与进度条同用这套档位配色):

| Provider | 口径 | 读数 |
| :--- | :--- | :--- |
| DeepSeek | 官方 `GET /user/balance`(凭据缝 → 环境变量) | 余额 ¥(CNY 行优先,金额口径不变),面板见赠金/充值拆分 |
| MiniMax | 官方 `GET /v1/token_plan/remains`(Token Plan 配额窗口) | 窗口已使用 %(上游报剩余则取补;`general` 桶);key 解析链=凭据缝 → env → **openclaw 网关配置**(`~/.openclaw/openclaw.json` 的 `models.providers.minimax.apiKey`) |
| Claude | 订阅制额度:OAuth `GET /api/oauth/usage`(`anthropic-beta: oauth-2025-04-20`),token 读自 `~/.claude/.credentials.json` | 会话窗口已使用 %(utilization 本来就是用量,**直读不再取补**)+ 本周已使用;面板附各窗口重置时间 |
| Codex | ChatGPT 订阅额度:本机 Codex CLI 的官方 `codex app-server`(JSON-RPC `account/rateLimits/read`),鉴权归 CLI 自己 | 5h 窗口已使用 % + 本周已使用;后端报额度受限时附「当前额度受限」 |

- OpenCode Zen **无公开余额接口**(上游 issue 还开着),不做假装有数的行;
- 某家未配置 = 面板里诚实的一行「未配置」,不隐藏也不报错;
- 低额红点:DeepSeek ≤¥20、MiniMax/Claude/Codex **已使用 ≥80%**(即剩余 ≤20%);
  `*LowPct` 配置字段保持「剩余水位」原义不动,已有配置值无需改,只是展示
  方向翻转了;进度条与头条数字按同一档位变色(60% 黄 / 80% 红),圆点仍是
  provider 状态灯(绿正常/黄过期/红异常),两者正交;**档位只染色不减信息**
  (kcn 反馈 #908):进红档后面板行的每窗读数、进度条、重置时间与头条的
  副读数、↻ 全部保留,水位警示句只是并排多讲一句,不顶掉任何字段;
- 刷新失败保留最近一次快照并标注 stale(黄点);瞬时 429 不抹掉真数字;
  Claude 行的「请求过于频繁,请稍后再试」就是 `/api/oauth/usage` 被问得太勤的
  429(本机的派发通知 `quota.mjs` 也读这个端点),**额度读不到不代表任务异常**,
  不要据此判断派发任务卡死;
- Claude 的 OAuth token 归 Claude Code 所有,本插件**只读不刷新**——过期时
  面板显示「请在终端跑一次 claude 刷新登录」;
- 宿主侧每 provider TTL 缓存、并发合并:DeepSeek/MiniMax/Claude 60s,Codex 跟
  `codexRefreshMs`(默认 5 分钟——每次读额度要拉起一个 app-server 进程);
  客户端静默轮询 ≥60s;手动 ↻ 强制拉新,不走缓存。

可选配置(profile 的 `cordis.patch.yml` 行内,改后重启 dsh 生效):
`balanceBaseUrl` / `balanceThreshold` / `balanceRefreshMs` /
`minimaxBaseUrl` / `minimaxKeyRef` / `minimaxLowPct` / `minimaxOpenclawConfigPath` /
`claudeCredentialsPath` / `claudeUsageUrl` / `claudeLowPct` /
`codexCommand`(Codex CLI 路径,默认 `~/.local/bin/codex`)/ `codexLowPct` /
`codexRefreshMs`(Codex 轮询与缓存周期,默认 300000)。

三个文件类默认值(`minimaxOpenclawConfigPath` / `claudeCredentialsPath` /
`codexCommand`)都挂在**当前用户的家目录**下(`homedir()`),不是写死的
`/root/...`——本包发布在 npm 上,绝对家目录会把一台机器的布局当成所有人的
默认值;换 uid 跑也会读错账号。profile 行里可以逐个覆盖。

### 余额上方的派发任务队列

装了 agent-dispatch 的主机上(`~/logs/agent-dispatch` 存在),余额那一行**正上方**
多一行「任务」:头条是在跑的任务数 `在跑 n` + 排队数、等内存数、等额度数、等重试数和
巡检状态(运行中 / 让路中 / 某时开下一轮 / 已停)。运行槽**按 agent 分**(2026-09-25 起;
`~/tools/agent-dispatch/limits.env` 的 `MAX_RUNNING_<AGENT>`,不写死),一个 agent 空着的槽
不能给别的 agent 用,所以头条不写 `n/总数`(`MAX_RUNNING` 只是三者之和);每个 agent 的
占用在悬停提示和面板第一段里。点开是同款毛玻璃面板,手动 ↻ 强制重读,
按提问顺序分四段(段名左、计数右):

- 运行槽 · 按 agent:先是一条 `claude 1/1 · codex 0/1 · opencode 1/1`(满了且有同 agent
  任务在排队的那一格变黄,一眼看出卡在谁身上),再是占着槽的任务
  (`agent-dispatch-<id>.service` active 且有 SLOT)。`SLOT` 是 `<agent>-<n>`;
  09-25 前启动的 runner 仍写裸数字 `1`/`2`,那是旧的全体共享槽,单独算作「过渡期共享槽」,
  不记到任何 agent 头上(过渡结束的判据见 `ops/host/README.md`);
- 排队 / 等待:没拿到槽的活任务和它在等什么(等 claude 锁 / 等 claude 运行槽 /
  等内存(只有巡检准入会等)/ 等额度·某时续跑);
- 最近结束的 5 个非巡检任务:状态 / 模型自报 STATUS 与结束于多久前;
- 巡检:`clawock-patrol` 的状态、在跑的轮次、它 journal 里最后一句话,和
  `rounds.tsv` 最近三轮(轮次 · 方向 · 结果 · 耗时 对齐成一张表;
  `preempted:cancelled` 是给人工任务让路,不是故障)。

任务行固定三列:点 · 名字 · 状态,下一行 agent·模型 在名字下、已跑时长·第几次
(或结束于多久前)右对齐在状态下;runner 判过静默卡死(`result.env` 的 `STALLS=`)时
后面再跟 `卡死 n`,说明第几次里有几次是被自动中止重试的。名字过长截断,行尾一个 › 表示可点开。

点一行在同一个面板里推入该任务的详情层(‹ 返回队列;Esc 先退回列表、再关面板;
点面板外直接全关):全名、状态、Agent、模型、开始时刻、已运行 / 用时、结束时刻、
尝试次数、判卡死次数(有才显示)、任务 ID;进行中的任务另有 run.log 最近一条事件(如 `got run slot 1`、
`attempt 2/3 (append)`),已结束的任务附模型收尾报告的末几行(run.log 的
`final |` 行,去掉空行和 STATUS 行)。面板从芯片往上开,高度封顶到视口顶部,
段名下的列表在面板内滚动;手机(≤520px)上面板与余额面板同宽(300px)、行距收紧。

全是本机文件加 `systemctl`/`journalctl`,不走网络;宿主侧 5s 缓存、客户端
15s 轮询。没有派发目录的主机上这一行不出现。可选配置 `dispatchLogDir` /
`dispatchLimitsPath` / `patrolStateDir` / `taskQueueRefreshMs` / `taskQueueRecent`。
宿主把侧栏底部动作排成一行(`.footerActions` 横向 flex),而且 list slot 的每一项
都包在一个 `display:contents` 的 `[data-slot]` 容器里——本行是那格的**孙子**。
样式表用 `:has(> [data-slot] > .tqf)` 越过这层容器把那一格改成竖排,任务行才
叠在余额上方、各占一整行;不支持 `:has()` 的浏览器上两行并排,功能不变。

## 语言

插件不自己写死文案:整个 bundle 只注册一个 `ctx.locale` 命名空间(`clawock`),
三处 slot 注册都声明 `locale: clawock`,文案由宿主的 locale 服务在 `zh` / `en`
之间切换(浏览器端只带这两种)。两本字典的 key 集合由测试断言一致——某一边漏一条
就会在该语言下渲染成 key 本身。

**跨版本兼容是设计的一部分**:两端独立部署(客户端 bundle 换掉下次刷新即生效,
宿主改动要重启 dsh),所以宿主侧格式化的内容一律双写——配额窗口同时下发
`label`/`resetAt`(宿主语言)与 `durationMins`/`resetAtMs`(结构化),T+1 判定同时
下发 `verdict`(宿主文本)与 `verdictKind`(稳定码)。客户端优先用结构化字段按当前
语言渲染,字段缺失时原样透传宿主文本;计数一律走稳定码,绝不匹配显示文案。
provider 自己的错误详情(`message`)保持原文,不做翻译。

## 它不做什么

- **不改文件**。面板只读;账本写入、发布只走 `clawock run` / brief 管线。
- **不替代 clawock**。skill 只把「什么时候跑、产出什么」讲给 agent 听,
  agent 调用的仍是同一套 CLI 与文件契约。
- **不发明判定**。没有 bar 就没有 T+1;`execution.status` 只渲染为
  「账本自评」小标签,成交与计划同向/反向另有独立判定。

## 验证装好了

重启后在会话里问「你现在带哪些 skill?」,应能看到 `investment-decision`;
或直接让 agent 执行 `clawock run prepare`,看它是否打印 `request_file`。

## FAQ

**skill 没出现?**
DSH 只扫 `~/.dsh/skills/` 和 `<project>/.agents/skills/` 两个根,不扫
node_modules——回到安装那一节检查 `cp` 那一步。

**Decision Mind 是空白的?**
面板读的是 clawock workspace(`CLAWOCK_WORKSPACE`)里的真实成交与决策
记录;workspace 还没有数据时 tab 是空的,不是装坏了。

**面板和公开 dashboard 是什么关系?**
同一个「决策轨迹」数据契约,两套渲染:插件是运行期读 workspace 的
TypeScript,网页是构建期算好塞进 `dashboard.json` 的 Python。两边的
规则常量与判词由测试钉住,不会漂移。

## 维护者

```bash
cd examples/dsh/packages/clawock-dsh
npm install --include=dev && npm run build   # 生成的 lib/ 提交入库,CI 断言零漂移
npm publish                                   # 发布当前版本
```

把当前 checkout 装进 self-hosted DSH(开发/自部署):
`ops/host/install_dsh_plugin.sh --restart`。README 截图一条命令:
`node site/tools/shoot_dsh_plugin.js` + `clawock validate-sidecar screenshots`;
决策卡示例图:`node site/tools/shoot_decision_card.js`。
