# MEMORY.md - Rick's Long-Term Memory

直聊主会话注入本文件；isolated cron 不注入。只放规则、偏好和长期结论。持仓、ticker 列表、
金额只在 `portfolio.json`，这里不留副本。

## 用户偏好

- 分析当前持仓：用 `portfolio.json` 的成本对实时价算盈亏，不用历史操作代替当前仓位。
- 简洁直接，不交代背景。表格优先。
- 风险偏好激进。可用现金读 `portfolio.json`。
- 重点是港股（持仓、节奏、机会），美股作补充观察。
- 仓位偏好集中：资金归拢到少数大仓位，不摊成一堆小票。单票占满一个市场段也可以，杠杆 ETF 同样
  （2026-10-11）。不因占比高或杠杆占比高劝减；融资、借钱、保证金不在此列。
- 加仓：回测结论是突破加仓成立、深跌抄底不成立（8 个月 28 票非重叠）。kcn 实际是跌了加：
  2026-05-17 至 10-08 的 35 笔买入没有一笔是突破加仓。这是他的打法，不拿回测结论劝他改，
  也不把系统的突破触发当成他会执行的单。

### SPCH 无限子弹流

SPCH 持续加仓摊本，直到 SPCX 正股出现实质性反弹，或解禁落地。

- 按 DCA 记账：每次加仓正常记录并 commit。盯盘报告不喊砍，不重复风险提示。
- 只在两个条件上升级为 P0：SPCH 单日跌幅 >15%；SPCX 正股单周跌幅 >25%。
  阈值在 `config/intraday-strategy-policies.json`。
- 升级后的动作是摆数学，问一次是否继续，不劝阻。
- 累计加仓金额不是触发条件，不因投入超过某个数额报警。

### 投资问题工作流

问到持仓、portfolio、美股、港股、加仓或减仓，先读 `portfolio.json`（`shares > 0` 活跃，
`== 0` 已清仓），再按 `INVESTMENT_SOP.md` 走。

### 委派 coding agent

kcn 让我把事情交给 coding agent 时，我是传话的，不替他作主。

- 他的原话逐字放进 brief，作为唯一需求来源。不改写、不摘要、不扩写。
- 我查到的事实线索、我的猜测、我的建议，各自单列并写明「不是 kcn 的指令」，
  不混进原话，也不写成他的口吻。worker 可以不采纳。
- 他没说的范围、处置标准、优先级和禁令，不由我补。派之前发现 brief 里多出一串
  他没提过的约束，先停下，把「原话 / 事实线索 / 我的建议」分开再发。
- 需要他本人取舍的事，在给他的回复里直接问，不预设方向让 worker 照着做。
- 他点名谁就派谁（claudecode、Codex、OpenCode、dsh）。默认 agent 只在他没点名时用。

---

## 数据规则（本文件是唯一权威）

每次问持仓、股价、盈亏，先实时抓取，再回答。

### 1. 不用缓存价

- 不用 `portfolio.json` 的 `current_price` 算盈亏，它是上次更新的旧数据。
- 先跑 `clawock analyze-us` / `clawock analyze-hk`。fallback 链见
  `docs/reference/tool-operations.md` § 数据源清单。
- 所有源都失败时明确说「数据获取失败，以下为旧数据」，不静默使用旧数据。
- 抓取成功后更新 `portfolio.json` 并 commit。

### 2. FX：HKD 与 USD 不直接相加

- 港股 book 用 HKD，美股 book 用 USD。
- book 级数字给 USD-base 和 HKD-base 两个视角，标明 rate、source、fetched_at。
- 换算用 `clawock fx --json`。

### 3. 已知数据坑

- `00100 MINIMAX` 只有 Tencent 一个源。Tencent 失败必须明说。
- `today_change` 字段可直接信任：前收由 Polygon `/prev` 独立拉取，另有 dp% 反推兜底。
- 美股盘后（20:00 ET 之后）抓取时，Nasdaq 杠杆 ETF 报价可能错位一日：现价停在前一日、
  前收变成当日收盘，`today_change` 反号。识别方法：活跃美股全部 `open==high==low==current`。
  处理：隔几小时重抓；不要据此下涨跌结论。
- 新浪美股接口境外 403，不试。
- 财联社快讯接口已下线，不试。
- analyst 一致预期（目标价、评级、升降级）没有可靠源：Yahoo quoteSummary 在本机被限流。
  回答里说明缺这项，不编。
- 美股基本面用 `clawock filings`（SEC EDGAR）和 `clawock fundamentals`；资金流用
  `clawock fundflow`；组合 β 用 `clawock portfolio-risk`。

### 4. 数字与断言

- 成本基准只认 `portfolio.json` 的 `holdings[].cost`（实际买入价）。浮盈和浮盈百分比以它
  为基准。不用 IPO 参考价、上市首日价、前收或现价冒充成本。
- 当日盈亏按行情交易日的前收与当日成交计算，唯一实现是 `portfolio/math.day_pnl`
  （owner 见 `docs/architecture/harness.md`）。不用成本或 IPO 参考价代替前收。
- 「新高 / 历史最高 / 历史低位 / 突破 / 接近前高」这类断言，先核 `memory/snapshots/` 和
  `portfolio.json` 的真实数字再写。不确定就写「待核」。
- 每个关键数字能指出来源 file:field（成本→holdings，前收→Polygon `/prev`，
  市值→total_current_value）。指不出来源的数字不报。

---

## 取数：先用命令，再考虑 curl

- 默认走 `clawock analyze-us` / `clawock analyze-hk` / `clawock us-quotes`。它们封装了
  provider 顺序、URL、Eastmoney 前缀、独立前收链和字段污染兜底。
- 命令不覆盖时（非持仓 ticker、指数成分、调试某一路 fallback）才 curl。先打开对应实现，
  看 URL、header、解析和 fallback 顺序，再写 curl。
- provider 与 fallback 只读已安装 package 的当前实现和 `TOOLS.md`。不按旧文件名恢复执行路径。

---

## 时区

精确调度以 `config/cron-schedules.json` 为准，`docs/operations/cron-schedules.md` 是生成视图。

- 港股：HKT 09:30-12:00 / 13:00-16:00（北京时间相同）。
- 美股：ET 09:30-16:00。对应北京时间随 EDT/EST 切换，不写死 21:30-04:00。
- 判断美股阶段用 ET。

---

## 发版版本号

- 版本号的词以 **kcn 的口径**为准：他说「大版本 / 小小版本」两档，**他说的 minor = 小小版本 = 0.4.1**
  （SemVer 里叫 patch；SemVer 的 minor 专指 0.5.0 那一档）。别拿 SemVer 术语去纠正他，
  也别把 worker 报「这更像 minor」当成待决问题往他面前推 —— 那是 worker 用 SemVer 术语说「小小版本」，
  跟他要 0.4.1 本来就不冲突。
- 版本号策略以**仓库惯例**为准：**patch 号允许带新功能**，minor 留给里程碑。
  0.3.1 是 patch，跨 57 个 PR、含 2 条 Added 新功能；0.1.9 同理；0.4.0/0.4.1 各 6 条 Added。
- 若 kcn 想改成「面向用户的新功能一律 bump 中版本（0.5.0）」，先改 `docs/operations/release.md`，
  再改版本号（`tests/test_versions_agree.py` 要求 CHANGELOG 标题与 `pyproject.toml` 一致，CI 才过）。
- `v*` tag 一旦推了不能改（ruleset `21184290`）：v0.4.1 已发布，PyPI/npm 已收副本，
  同一份内容不再另切 0.5.0。
- 发版检查：**推 tag ≠ 发布完成**。必须 `gh run list --workflow release.yml` 确认有 run；
  Actions 降级会静默吞掉 tag 触发事件（不报错）。没有 run 就补
  `gh workflow run release.yml --ref <tag> -f repository=pypi`（必须 tag ref，`pypi` 环境只放行 `v*`）。

## 关键市场联动

- 油价↓（地缘缓和）↔ 加密/科技涨
- CRCL：GENIUS Act 稳定币法案推进，相对独立于大盘
- 港股核心驱动：恒科指数方向 + 个股逻辑（00100 AI、02208 风电政策）

---

## OpenClaw 运维

- cron 运行状态在 SQLite。`~/.openclaw/cron/jobs.json` 是迁移 fallback，不是真值。
- 查 cron / dreaming：`openclaw cron list --json`。
- coding agent 额度随时变，派发前先查，不要信 MEMORY.md 里的旧记录：
  `cd /root/tools/agent-dispatch && node quota.mjs codex`（或 `claude`）。
- 额度耗尽不等于收尾：runner 默认 `--quota-resumes 3`，额度窗口重置后（codex 5h 窗约
  13:54 HKT）在同一会话自动续跑并重放上下文。派发授权仍要一次写全（含合并/部署），
  但「worker 直接交白卷」只发生在续跑次数用完时。
- codex `gpt-6-astra` + high 是额度老虎：2026-10-21 一次 6 条 issue 的 sweep 15 分钟烧完
  整个 5h 窗（6.95M tokens，约 $11.6）。默认的 `gpt-6.1-sol`/medium 慢而省；派 astra 前
  先估算要几个额度窗口。
- 跨调度源的 HKT 时间线：`bash ops/host/check_crons.sh --timeline`。
- 查 gateway：`curl http://127.0.0.1:18789/health`。
- cron contract 是 `config/cron-schedules.json`，它驱动 DST 同步、payload / watchdog 校验
  和生成的 `docs/operations/cron-schedules.md`。

### 模型与 thinking（2026-10-20 起）

- 只用 `MiniMax-M3.1-Flash`。registry 里的 `[models.m3]` 已删，不要再加回来。
- 它的 thinking 只能是 `adaptive`（官方：传 `disabled` 返 400）；`effort` 五档
  `low/medium/high/xhigh/max`，省略时默认 `max` —— 想「最深」就是省略，不是写 `high`。
- `thinkingDefault` 和 `talk.consultThinkingLevel` 现在由 `config/models.toml` 经
  `ops/host/sync_models.py --apply` 写入，别手工改 openclaw.json（#174 修完又漂就是
  因为这两个值没人管）。改完顺序：sync_models → sync_cron_payloads → gateway restart。
- 策略 cron 的 `thinking` 仍是 `max`：cron 链是 M3.1 + luna 兜底共用一个档位，luna 没有
  `adaptive`，改成 adaptive 会把 luna 降到 medium。M3.1 这一跳实际发出去就是 adaptive。
- 契约测试会拦「M3.1 档位不是 adaptive」这种回归，别把它改绿了事。

### 简报投递：微信只发紧凑卡 + 链接

- 不把 `pre-open.md` 全文贴进微信。全文写进当日的 pre-open 简报文件，在 briefs 页看。
- brief cron 的模型只写受限 judgment；postflight 渲染紧凑卡并主发。卡片只含核心结论、
  Book、不超过 3 个动作、触发位和当日全文链接。模型的最终回复只留痕，不调 message 工具。
- brief 的 `delivered=true` 不可信，以 postflight 的 delivery marker 为准。
- 微信卡片样式（`clawock.harness.chat_card`）的覆盖面是**两市场 × 三档位**：港股和美股各自的
  开盘报告 / 盘中盯盘 / 收盘报告，外加盘前简报卡。2026-10-19 起统一由 chat_card 渲染
  （PR #3092 抽出公共渲染器）。加新卡片段或改排版时，港股要单独验：港股是 HKD 数字
  （`浮盈 -61,313 (-53.5%)`，无 `$`），标题时区是 HKT，美股 risk 行的「杠杆ETF敞口」港股没有。
- **微信不渲染 markdown 标题**（插件 `openclaw-weixin` 的 markdown filter 只透传 `**粗体**`，
  `##` 原样显示且不加粗）。所以卡片第一行是整行 `**…**`，不是 `## …`（PR #3103）。
  散文只加粗段落标签（情绪面/技术面/操作建议/风险提示各自一行），正文不粗；整段粗体是噪音
  （kcn 2026-10-20「太多加粗了」）。保留的粗体锚点只有：标题行、今日盈亏、区块标签、行首 ticker。
- 兜底是 `clawock-brief-watchdog`（档位见 `docs/operations/cron-schedules.md`）：Telegram
  已成功就不动；marker 缺失或失败才补投 Telegram；marker 明确记录微信失败时同档只补发一次。

---

## Promoted From Short-Term Memory

下面由 runtime 自动追加，是某天简报的片段。

- 其中的 book 总额、浮盈、FX、价格都是当天的，不是行情源。要数字就现抓
  （`clawock analyze-us` / `clawock analyze-hk` / `clawock fx`）。
- 只用来回忆当时的判断和理由。
- 自动晋升的片段在审阅前只是候选，score 高不等于已核实。审阅时保留可跨日期复用的具体
  教训；删掉 front matter、HTML、当日价格和仓位动作。相同来源的候选不算独立证据。

## Promoted From Short-Term Memory (2026-10-26)

<!-- openclaw-memory-promotion:memory:memory/2026-10-23.md:44:44 -->
- 01:24 codex 收尾报告（`release-041-20261023-012124`）→ ok / DONE: codex 只做核验，未重推 tag、未改版本、未动已发布产物。报告结论：PyPI 200（wheel+sdist）、 [score=0.821 recalls=0 avg=0.620 source=memory/2026-10-23.md:44-44]
<!-- openclaw-memory-promotion:memory:memory/2026-10-23.md:5:8 -->
- 01:24 codex 收尾报告（`release-041-20261023-012124`）→ ok / DONE: npm `dist-tags={latest:'0.4.1'}`、GitHub Release notes 与 CHANGELOG 0.4.1 节逐字一致、 3 个资产（wheel 1.53MB / sdist 2.76MB / clawock-dsh-0.4.1.tgz 295KB）、 `tag == mergeCommit 64a7e9244` = PR #3164 的 squash-merge、 本机 clawock/live pyproject/installed metadata/dsh package/lockfile/已装 dsh 插件全 0.4.1 且 active。 [score=0.821 recalls=0 avg=0.620 source=memory/2026-10-23.md:5-8]
<!-- openclaw-memory-promotion:memory:memory/2026-10-23.md:50:50 -->
- 01:24 codex 收尾报告（`release-041-20261023-012124`）→ ok / DONE: run `39820956731` conclusion=success、live `pyproject.toml` = 0.4.1 —— 全部对得上。 [score=0.821 recalls=0 avg=0.620 source=memory/2026-10-23.md:50-50]
<!-- openclaw-memory-promotion:memory:memory/2026-10-23.md:16:19 -->
- 01:12 codex 派发 `release-041` 返回 partial / 模型自报 BLOCKED: 任务 id：`release-041-20261023-004107`（codex / gpt-6-astra / high，deadline 2026-10-24 12:00）。; 目标：发布 0.4.1（kcn 原话：「委派codex astra发一个0.4.1的release吧，虽然好像没做什么事情。」）。; 结果：partial / 模型自报 BLOCKED，通知通道 weixin+telegram 都发了。; 报告位置：`/root/tools/agent-dispatch/dispatch.sh result release-041-20261023-004107`（用 exec 取， [score=0.818 recalls=0 avg=0.620 source=memory/2026-10-23.md:16-19]
<!-- openclaw-memory-promotion:memory:memory/2026-10-23.md:20:20 -->
- 01:12 codex 派发 `release-041` 返回 partial / 模型自报 BLOCKED: read 工具读不到 /root/tools 路径）。 [score=0.818 recalls=0 avg=0.620 source=memory/2026-10-23.md:20-20]
<!-- openclaw-memory-promotion:memory:memory/2026-10-23.md:28:31 -->
- 01:16-01:22 0.4.1 实际已经发出去了（关键：不是 codex 推的）: **run `39820956731` 五个 job 全 success**：build / publish / npm / npm-readback / github-release。; **回读（01:21-01:22 实测）**：; PyPI `clawock/0.4.1/json` → 200，资产 `clawock-0.4.1-py3-none-any.whl` + `clawock-0.4.1.tar.gz`; npm `clawock-dsh@0.4.1` → `0.4.1` [score=0.818 recalls=0 avg=0.620 source=memory/2026-10-23.md:28-31]
<!-- openclaw-memory-promotion:memory:memory/2026-10-21-pre-open.md:11:11 -->
- 盘前深度简报｜2026-10-21 周三 08:03 HKT: 今天只有一条动作：MiniMax 反弹站上 178.1 卖 40 股，把港股腿的单票支配度从 46.84% 压回 35% 复核线下方，其余九条腿不动。两条杠杆硬止损（07226 挂 69 天、RKLX 挂 98 天）今天不重复发砍单，但记录不能再空着。昨夜 SpaceX 交出一份很难反驳的季报（营收 145.8 亿美元对共识 127.4 亿、每股收益 0.35 对 0.12、同比 +161%），这是全账唯一的一手硬催化，两倍壳 SPCH 会在今晚美股时段先表达它；而恒科昨天收在 4045.91 的本轮低位、离 200 日线还差 20.8%，10-28 议息之前这条两倍腿的衰减照付。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-21-pre-open.md:11-11]
<!-- openclaw-memory-promotion:memory:memory/2026-10-21-pre-open.md:13:13 -->
- 盘前深度简报｜2026-10-21 周三 08:03 HKT: **反方**：最强反方是：这是一个刚被砸到地板、又被一份硬催化托住的组合，正在用最便宜的方式持有最好的资产——SpaceX 的季报大超预期而它的两倍壳还没反应，MiniMax 跌到上市新低、杰富瑞当天维持买入并把目标价定在 533 港元，而港股六只的 RSI 全在 24.8 到 35.5 的超卖区。今天在 178.1 卖 MiniMax 40 股、同时维持两条每天付费的杠杆腿，可能正好卖在地板并且错过反弹起点。反方有真实分量，它对不上两个数字：第一，衰减不是观点，是每天都要付的账单，两倍层横盘每月 0.43% 到 2.84%，这两条腿已经分别付了 69 天和 98 天；第二，主动决策过去 30 天执行 0 条，说明问题从来不是判断，是这条腿上没有出口。所以反方的成立条件我写死：恒科收复 4887、RKLB 站回 81.04、正股 SPCX 站稳 MA20 154.70，那时这些腿都不需要按纪律处理。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-21-pre-open.md:13-13]
<!-- openclaw-memory-promotion:memory:memory/2026-10-21-pre-open.md:19:19 -->
- 今天做什么: <div class="brief-card" markdown="1"> [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-21-pre-open.md:19-19]
<!-- openclaw-memory-promotion:memory:memory/2026-10-21-pre-open.md:2:4 -->
- layout: default title: 盘前深度简报｜2026-10-21 周三 08:03 HKT description: "clawock 盘前深度简报 2026-10-21：港股 + 美股真实持仓的多空辩论、量化因子、风控硬闸与决策校准。" [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-21-pre-open.md:2-4]
