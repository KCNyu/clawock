# MEMORY.md - Rick's Long-Term Memory

## 用户偏好

### 持仓分析风格
- **直接分析当前持仓**：用 `portfolio.json` 成本 vs 实时价计算盈亏
- 忽略 `trades` 字段的历史操作，focus 当前仓位
- 简洁直接，不交代背景
- **风险偏好：激进型**，可用现金约 15万人民币（≈$20,500 USD）
- **重点：港股**（持仓、节奏、机会），美股作为补充观察
- 表格优先，能用结构化展示就不用大段文字
- **仓位策略：2026-07-08起偏好集中，不散着玩**——见 [feedback_position_concentration.md](memory/feedback_position_concentration.md)
- **SPCH 无限子弹流：2026-08-13 起撤销“累计加仓成本 > $3000 即 P0”纪律**；后续不得因累计投入超过 $3000 单独报警。SPCH 单日跌幅 >15% 与 SPCX 正股单周跌幅 >25% 的异常提醒仍保留。

### 投资问题工作流
凡是问到 `持仓` / `portfolio` / `美股` / `港股` / `加仓/减仓`，按顺序读：
1. `portfolio.json`（权威持仓）
2. `memory/current-portfolio-summary.md`（ticker 列表）
3. 最近 1-3 篇 `memory/YYYY-MM-DD.md`
4. 工作流细节见 `INVESTMENT_SOP.md`

---

## ⚠️ 数据规则（铁律 — 本文件是唯一权威）

**每次问持仓/股价/盈亏，先实时抓取，再回答。**

### 1. 不用缓存价
- **禁止用 portfolio.json 的 `current_price` 计算盈亏** — 那是上次更新的旧数据
- 必须先跑 `clawock analyze-us` / `clawock analyze-hk`（fallback 链详情见 `TOOLS.md` § 数据源清单）
- 所有源均失败 → 明确说"数据获取失败，以下为旧数据"，**禁止静默使用**
- 数据成功后 → 更新 `portfolio.json` + git commit
- 教训：2026-05-11 用缓存价 RKLB 写成 $110 vs 实时 $118，盈利 +$790 错写成 +$550

### 2. FX 铁律 — HKD + USD 不能直接相加
- 港股 book 用 HKD，美股 book 用 USD — **绝不直接相加**
- 所有 book-level 数字必须**双视角**：USD-base + HKD-base，显式标注 rate / source / fetched_at
- 工具：`clawock fx --json` （3 路 fallback，4h 缓存）
- 教训：2026-05-16 deep brief 把 -4936 HKD + +513 USD = -4423 直接相加 → 数字毫无意义

### 3. 已知数据坑
- **00100 MINIMAX 只有 Tencent 一个源**，新 IPO 其他源没数据；Tencent 失败必须明说
- 收盘后 live-quote API 会把 `PreviousClose` 更新为当日收盘价，导致 `today_change = 0`；脚本已修（Polygon `/prev` 独立拉前收 + dp% 反推兜底），`today_change` 字段可直接信任
- **盘后 closed fetch（20:00+ ET）撞 Nasdaq 杠杆 ETF 报价坑**：`lastSalePrice` 停在前一日旧价、`PreviousClose` 反装当日真实收盘 → 价格错位一日 + `today_change` 反号（2026-05-29 MSFU/PLTU 被记成大跌实为大涨）。识别：活跃美股全部 `open==high==low==current` 退化报价。修法见 `memory/openclaw-us-postclose-stale-price-swap.md`（重抓自愈 + Nasdaq netChange 补 today_change + refresh_today_snapshot）
- 新浪美股接口境外 403，跳过不试
- **Vibe-Research 数据源审计（2026-07-11）**：kcn 让学 github.com/simonlin1212/Vibe-Research（A股40端点 + 美港18端点）。结论=**其可达的源我们已全覆盖且多数更优**——① 美股基本面它用 Yahoo quoteSummary，我们用 `clawock filings`（SEC EDGAR XBRL，零 auth 政府源，已接进 brief_preflight）+ `clawock fundamentals`（东财 GMAININDICATOR/三表，US+HK，实测 200 可达）双保险，比它稳；② β 它拉 Yahoo 单股发布值，我们 `clawock portfolio-risk` 用真实收益率算组合级 Cov/Var vs SPX/HSI（>3.0 硬闸），更严谨；③ 美港资金流我们有 `clawock fundflow`。**唯一真缺口=analyst 一致预期（目标价/评级/升降级历史），是 Yahoo quoteSummary 独家 → 本机实测 429（连 crumb 端点都限），建了也不可靠 → 暂不建**。副产：`cls_telegraph()`（财联社快讯）已 404 下线别再试；它东财全系用 `em_get()` 串行≥1s+随机0.1-0.5s 抖动，比我们粗暴 sleep 好，将来 fetcher 防封可抄这个抖动策略

### 4. 数字与断言铁律（钱相关，kcn 反复当场抓错 → 列为硬闸）
- **成本基准只认 `portfolio.json` holdings[].cost（实际买入价）**：浮盈/浮%/今日盈亏/盈亏金额一律以它为基准。**绝不**用 IPO 参考价/上市首日价/前收/现价冒充成本。教训：SPCX 用 IPO 参考价当 prev_close 算出错误 `today_change +135`，kcn 当场抓。
- **状态断言先核实数再说，禁编造**："新高/历史最高/历史低位/XX 区域/突破/接近前高"这类话**必须先核 `memory/snapshots/` + `portfolio.json` 真实数字**才能下；不许凭记忆、语感或新闻语气脑补。不确定就写"待核"，别给一个听起来对的假断言。教训：RKLB「新高区域」纯属编造被 kcn 抓。
- **每个关键数字能指出来源 file:field**（成本→holdings、前收→Polygon `/prev`、市值→total_current_value…）；报数字时心里先过一遍来源，报不出来源的数字不报。

---

## 脚本与降级 curl 的关系

**默认走脚本**（`clawock analyze-us` / `clawock analyze-hk` / `clawock us-quotes`），它们封装了 provider 顺序、URL pattern、Eastmoney 前缀、prev_close 独立链、各种字段污染兜底——这些是反复踩坑攒下来的，能用就别绕。

**脚本不覆盖时可以 curl，但要先学再 curl：**
- 场景：查非持仓 ticker / 指数成分 / 突发数据源切换 / 调试 fallback 某一路
- 步骤：先 grep / 打开相关脚本，看里面的 URL、header、解析片段、fallback 顺序，再决定 curl 怎么写
- 旧 `scripts/legacy` 已删除；dated memory 里的旧文件名只属历史记录，禁止据此恢复执行路径。provider/fallback 只读 installed package 当前实现与 `TOOLS.md`。
- 永远跳过：新浪美股接口（境外 403）

**Why:** "瞎拉数据"是只看官方文档闭眼写 curl，会重新踩 PreviousClose 污染、Eastmoney 前缀、Sina 境外 403、yfinance 限速这些坑；"自主退化"是脚本里已经写明白的东西先学完，curl 只用来填脚本没覆盖的边缘场景。

---

## 时区
- 港股：HKT 09:30-12:00 / 13:00-16:00（北京时间同）
- 美股：ET 09:30-16:00；对应北京时间随 EDT/EST 自动切换，禁止写死 21:30~04:00
- 判断美股阶段优先用 ET；精确 HKT cron 见自动生成的 `docs/operations/cron-schedules.md`
- 北京时间 16:02 = 港股刚收盘

---

## 关键市场联动
- 油价↓（地缘缓和）↔ 加密/科技涨
- CRCL：GENIUS Act 稳定币法案推进，相对独立于大盘
- 港股核心驱动：恒科指数方向 + 个股逻辑（00100 AI、02208 风电政策）

---

## OpenClaw CLI 注意事项

### OpenClaw 调度状态
- 6.1 后 cron runtime state 在 SQLite，旧 `~/.openclaw/cron/jobs.json` 是迁移 fallback，不能当真值。
- 查 cron / dreaming → `openclaw cron list --json`；跨调度源看 HKT 时间线 → `bash ops/host/check_crons.sh --timeline`。
- CI 不能访问本机 SQLite，读取 `config/cron-schedules.json`；它同时驱动 DST 同步、payload/watchdog 校验和 `docs/operations/cron-schedules.md`，host system check 会对比 live CLI + crontab。
- 查 gateway → `curl http://127.0.0.1:18789/health`。

### ⚠️ brief 投递铁律 — WeChat 只发紧凑卡 + 链接，**绝不贴完整 brief 全文**
- **brief cron Step 4 写紧凑卡，Step 5 postflight 主发**：卡片只含核心结论 + Book + ≤3 动作 + 触发位 + 当日全文链接；LLM 最终回复仅留痕，不调 message 工具。
- **绝不把 pre-open.md 全文(~14-17KB)糊进微信。** 完整 brief 照常写进 pre-open.md → commit → dashboard/briefs 页看（深度不变，全文不裁）。
- **教训：2026-05-31** 让 mimo 把完整 brief 作为最终消息吐出 → **复读死循环**（"Now let me output the WeChat message…"复读几十遍被当回复发出，kcn 收到一屏垃圾），2 次实测都犯。**根因=mimo 在长输出上 commit 不下来**，不是 size 也不是措辞；**短卡片 = 物理上不会 loop**（已验证干净投递）。`delivered=true` 对 brief 不可信（同 report stub 坑）。
- **兜底**：安装命令 `clawock-brief-watchdog`（系统 crontab 08:30 HKT 工作日）读取 postflight delivery marker；Telegram 已成功则不动，marker 缺失/失败才补投 Telegram。它不再重发 WeChat，也不靠截断的 run summary 猜成败。
- WeChat 通道正常（手动 `openclaw message send` 即时送达）；冷会话静默丢弃见 cold-session 坑（本次不是）。
- briefs 页 7 列表格在 mobile 横向滚动（`site/_layouts/default.html` @media≤600px：table display:block+overflow-x:auto），不撑破布局。

---

## 持仓数据
- **单一来源：`portfolio.json`**，不在此维护副本
- ticker 列表：`memory/current-portfolio-summary.md`（提高检索命中）

## Promoted From Short-Term Memory

_（空）_

**促销进来的摘录是历史文本，不是行情源。** 这一段由 runtime 自动追加，内容是某天简报的
片段——里面的 book 总额、浮盈、FX、价格全部是**那天**的。引用它们等于违反本文件
§ 数据规则 § 1（不用缓存价）。要数字就现抓：`clawock analyze-us` / `clawock analyze-hk`
/ `clawock fx`。这里只用来回忆**当时的判断和理由**，不用来回忆数字。

2026-08-09 清空了七条 8/4 的促销摘录：它们把四天前的 `USD −7,426.69 / HKD −58,244.56`
以「长期记忆」的身份注进主会话，正是最容易被当成当前值引用的形状。

## Promoted From Short-Term Memory (2026-08-12)

<!-- openclaw-memory-promotion:memory:memory/2026-08-07-pre-open.md:11:11 -->
- 盘前深度简报 · 2026-08-07 (周五) 08:00 HKT: 🧭 **Regime** (packet, per market): US `red` (US β 5.85 + US levered 85.2% + RKLX lev_regime red) · HK `amber` (HK single_name 52.49% + HK Top2 85.2% + HK levered 32.7% + factor breach). **macro.label `neutral`** (VIX 15.81 -4.18%, F&G 59.7 greed, SPX 7,723.55 -0.17% / NDX 26,363.44 -0.83% 8/5 同步小幅回, HSI 25,530.28 -1.49% / HSTECH 4,820.78 -2.28% **8/6 破 4,900**). **8/7 关键宏观 = 8/6 20:30 ET NFP** (前值 7.7M, cons 200k, 强劲 → leveraged 风险 + 反向 USD 强), **risk_rule cuts 不受 risk_on HOLD 默认约束**. [score=0.803 recalls=0 avg=0.620 source=memory/2026-08-07-pre-open.md:11-11]
<!-- openclaw-memory-promotion:memory:memory/2026-08-07-pre-open.md:13:13 -->
- 盘前深度简报 · 2026-08-07 (周五) 08:00 HKT: **FX**: USDHKD = **7.8446** (Frankfurter, fetched 2026-08-07 00:01 UTC, age 7.9h). **🔒 HKD + USD 不能直接相加, book 段双视角展示**. [score=0.803 recalls=0 avg=0.620 source=memory/2026-08-07-pre-open.md:13-13]
<!-- openclaw-memory-promotion:memory:memory/2026-08-07-pre-open.md:15:15 -->
- 盘前深度简报 · 2026-08-07 (周五) 08:00 HKT: **实时价快照**: HK 持仓来自 Tencent 2026-08-06 收盘; US 持仓来自 2026-08-06 16:00 ET close. 8/6 关键事件: HSI -1.49% / HSTECH -2.28% 整体回调, **但 00100 +17.09% 收 297.2 反向领涨 AI 板块** (H3 开源 + 港股通 9 月生效 + 高盛 ARR 130亿); 07226 -4.73% (broker 0/6 5d → 8/6 升级 hard cut 6,200 全部清 sim); RKLX +2.28% (8/6 升级 hard cut 10 sim); SPCH +11.31% (8/6 升级 hard cut 190 sim, user 8/7 01:34 HKT 反而加仓 20 @5.88 摊本); MSFU +5.13% (trim 3 @38 sim +0.87 USD 已 plan 触发); PLTU -3.29% (trim 2 @44 未触发, 8/6 high 估 ≤42.295); SKHY -4.97% 持续消化 8/5 财报日 -13%; SPCX +6.14% 修复. [score=0.803 recalls=0 avg=0.620 source=memory/2026-08-07-pre-open.md:15-15]
<!-- openclaw-memory-promotion:memory:memory/2026-08-07-pre-open.md:17:17 -->
- 盘前深度简报 · 2026-08-07 (周五) 08:00 HKT: > 🔴 **broker 0/6 第 6 日 + 9 breach + 2 硬止损 = 8/7 是 3 杠杆 ETF hard cut 第 2 次升级日 + 00100 trim 第 5 次尝试日**: 7/30-8/6 6d 0/6 swap 阻断 07226/RKLX/SPCH. **00100 8/6 +17% 反弹至 297.2 加剧 single_name 52.49% breach (8/5 47.65% → 8/6 52.49%)**, 8/4 加仓均价 230 守住 +29.2% 浮盈 part, 但距回本 +86.1% 仍远. 8/6 trim 28 @240 反射 sim 错位 -1,601 HKD 但 broker fill 1/1, 8/7 继续 trim 30 @ ≥280 借反弹分批. 8/7 NFP + 8/10 RKLB amc + 8/12 CPI 三事件压顶, leveraged 仓位 (RKLX/SPCH/PLTU/MSFU) 注意. [score=0.803 recalls=0 avg=0.620 source=memory/2026-08-07-pre-open.md:17-17]
<!-- openclaw-memory-promotion:memory:memory/2026-08-07-pre-open.md:2:4 -->
- layout: default title: 盘前深度简报 · 2026-08-07 description: "clawock 2026-08-07 盘前: 00100 +17% 反弹至 297.2 加剧 single_name 52.49% breach, broker 0/6 第 6 日 3 杠杆硬切再升级, NFP 8/6 20:30 ET 压顶." [score=0.803 recalls=0 avg=0.620 source=memory/2026-08-07-pre-open.md:2-4]
<!-- openclaw-memory-promotion:memory:memory/2026-08-07-pre-open.md:9:9 -->
- 盘前深度简报 · 2026-08-07 (周五) 08:00 HKT: > Auto-generated by daily-deep-brief harness. 手写复盘覆盖本文件即可。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-08-07-pre-open.md:9-9]
