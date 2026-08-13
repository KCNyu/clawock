# Rick's Stock Analysis Tools

## 当前结构总览
- 权威持仓：`portfolio.json`
- 长期规则与偏好：`MEMORY.md`
- 投资工作流：`INVESTMENT_SOP.md`
- 当前持仓摘要：`memory/current-portfolio-summary.md`
- 每日复盘/交易日志：`memory/YYYY-MM-DD.md`
- 可移植工具与工作流：安装后的 `clawock`；源码归 `src/clawock/`
- Harness 入口（cron 调起）：`clawock brief|report|intraday`；实现与策略都由根 `clawock` wheel 持有，profile 只选值和资源
- Host / publish / CI / growth 运维：`ops/{host,publish,ci,growth}/`
- 仓库已无 `scripts/data/` 运行入口；OpenClaw 不得恢复或猜测旧脚本路径
- Dashboard 页面：`site/index.html`；完整 generation 由 KCNyu postflight 与 `ops/publish/publish_dashboard.sh` 刷新到 data plane

## 公共发布层（仓库 = `github.com/KCNyu/clawock`）

- Repo 是 **public**，含真实仓位（用户已知情授权）
- Dashboard live: https://kcnyu.github.io/clawock/ — 自动从 `assets/data/dashboard.json` 取数
- Briefs index: https://kcnyu.github.io/clawock/briefs.html — 自动列 `memory/*-pre-open.md`
- `site/_layouts/default.html` 给 markdown 页面统一样式（`site/briefs.md` 等）；dashboard 自身由 `site/index.html` + `site/assets/{css,js}` 构成
- Pages 自动 build on push

### GitHub Actions 分工

| Workflow | 触发 | 写文件 | 备注 |
|---|---|---|---|
| `harness-regression.yml` | 代码/配置 push to master + 每个 PR | (read-only) | 完整 schema/import/pytest 校验；自动生成的 dashboard-only push 走下方轻量门禁 |
| `dashboard-artifact-gate.yml` | dashboard.json push to master | (read-only) | GitHub runner 上零依赖校验已提交首屏 payload，不占 VPS |
| `actionlint.yml` | workflow 变更的 push/PR | (read-only) | pinned actionlint 校验 GHA expression/YAML/shell |
| `weekly-health.yml` | 周日 23:00 UTC | (read-only) | 综合健康检查（含公网数据源活体） |
| `eod-archive.yml` | 周五 22:00 UTC | `memory/archive/eod-history.csv` | 每周持仓快照 audit trail |
| `sentiment-scan.yml` | 周日–四 21:30 UTC | `assets/data/sentiment.json` | 05:30 HKT 盘前 Reddit + Google News 扫描 |
| `macro-scan.yml` | 周日–四 21:45 UTC | `assets/data/macro.json` | 05:45 HKT 盘前宏观扫描 |
| `brief-fallback.yml` | 工作日 00:25 UTC (08:25 HKT) | brief/plan + harness 产物 | 主 brief 缺失且未晚于 10:00 HKT 才由远端 LLM 接管 |
| `weekly-review.yml` | 周日 14:00 UTC (22:00 HKT) | `memory/weekly/{ISO-week}.md` | MiniMax 主、Xiaomi 可选 fallback 的周复盘 |
| `news-digest.yml` | 工作日 13:00 UTC (21:00 HKT) | `assets/data/us_news_digest.json` | 美股开盘前 48h 新闻提炼 |
| `influencer-scan.yml` | 周日–四 21:40 + 工作日 12:50 UTC | `assets/data/influencer_feed.json` | 盘前 + 美股盘前两班影响力雷达 |
| `cron-health.yml` | 工作日 09:00 UTC (17:00 HKT) | (read-only) | 用 tracked cron contract + HKT commit date 巡检漏跑 |
| `screenshot-refresh.yml` | 周日 22:00 UTC | `site/assets/social-card.png` + `site/assets/shadow-backtest.png` | 每周刷新社交卡里的 Hero 截图和实时战绩图；`site/assets/dashboard.gif` 只在手动 dispatch 时生成 |

**远端 LLM 路径**: 本地市场 cron 与远端 `clawock.automation.llm` 都以 MiniMax M3 为主；远端在可选 `XIAOMI_API_KEY` 仍有效时可 fallback 到 MiMo v2.5-pro。4 个 LLM workflow（news-digest / weekly-review / brief-fallback / influencer-scan）均只从 repo secrets 读 key，仓库不落 key。

**数据扫描 GH Action 不写 `assets/data/dashboard.json`**，只写各自 sidecar；dashboard
只由 harness postflight（含远端 brief fallback 复用同一 postflight）和 host 上加锁的
`ops/publish/publish_dashboard.sh` 发布。

## 推荐工作流

### 1. 回答投资问题
按顺序读取：
1. `MEMORY.md`
2. `portfolio.json`
3. `memory/current-portfolio-summary.md`
4. 需要时再读最近 `memory/YYYY-MM-DD.md`
5. 拉最新价格后再分析

### 2. 更新价格
```bash
clawock analyze-us   # 美股
clawock analyze-hk   # 港股
```

### 3. 快速查看持仓
```bash
clawock analyze-hk
clawock analyze-us
```

---

## 数据源清单（当前约定）

### 港股 fallback 链（脚本实现，2026-05-18 加 Eastmoney HK 双源对账）
1. **腾讯财经** `qt.gtimg.cn/q=r_hkXXXXX` — 主源，覆盖最全
2. **东方财富 HK** `push2.eastmoney.com/.../ulist.np/get` (secid prefix 116) — 独立第二源，跟 Tencent **并行抓取**做交叉校验：当两源都成功时，c/pc 偏差 > 1% 会在 `_divergence` 字段标 WARN + stdout 提示，作为 stale-data 漂移的 trip-wire
3. **stooq.com** CSV — 同日 OHLCV，新 IPO 无覆盖；prev_close 用 open 近似（低置信度）
4. **yfinance** — 经常被限速，最后兜底


### 美股 & 港股脚本（推荐用法）

```bash
clawock analyze-us   # 美股完整分析（RSI/MA/新闻/信号）
clawock analyze-hk   # 港股完整分析（恒指/恒科/P&L/信号）
# 共通 flag：--no-news(省Finnhub配额) --no-fetch(用缓存价) ；hk 另有 --dry-run
clawock us-quotes     # 仅刷美股价格
```

### 美股 fallback 链

**脚本内部 provider 顺序：**
1. **Nasdaq API** `api.nasdaq.com/api/quote/{TICKER}/info?assetclass=stocks|etf` — 无需 key，JSON，覆盖股票和 ETF ✅
2. **东方财富** `push2.eastmoney.com` — 批量 JSON，无需 key，`105.{TICKER}`（NASDAQ）/ `106.{TICKER}`（NYSE）
3. **Finnhub** — 需 `FINNHUB_API_KEY`
4. **Yahoo v8 API** `query1.finance.yahoo.com/v8/finance/chart/{TICKER}` — 无需 key，偶有限速
5. **yfinance** 库 — 无需 key，偶有限速
6. **Alpha Vantage** — 需 `ALPHA_VANTAGE_API_KEY`，慢（免费 25次/天）
7. **Polygon** — 需 `POLYGON_API_KEY`，返回前一日收盘价

**Claude 直接 web_fetch 时的顺序：**
1. CNBC `cnbc.com/quotes/{TICKER}` — 网页，快速可靠
2. 东方财富、Finnhub、Yahoo Finance

### 货币 / FX

铁律：**HKD + USD 不能直接相加** — 详见 `MEMORY.md § 数据规则 § 2`。

工具：
- `clawock fx --json` → `{"rate": 7.83, "source": "Frankfurter", ...}`
- 换算：`clawock fx --convert 10000 HKD USD`
- fallback：Frankfurter → exchangerate.host → Yahoo HKD=X；4h 本地缓存

### 美股基本面 / SEC filings
`clawock filings {TICKER}` — SEC EDGAR 免费无 key：10-K/10-Q/8-K、`--financials`(XBRL 13项)、`--form4`(insider)、`--13f`、`--json`。速率 8/sec；非美股票返回 "CIK not found"；**纯基本面补充，不替代 `clawock us-quotes` 抓价**。完整参数表+注意事项 → `docs/reference/commands.md`。

### 港股/美股基本面(中文) — 东财 datacenter
`clawock fundamentals {CODE}` — 无 key，**填港股财报空白**：`--indicators`(GMAININDICATOR ROE/EPS/毛利率/资产负债率，美+港) / `--statements income|balance|cashflow`(中文科目行) / `--json`。美股数字以 SEC 为准、此为中文速查。datacenter-web+searchapi 子域实测稳；**资金流 `clawock fundflow`(push2his)本机 IP 被封暂不可用**。

### 说明

数据/缓存铁律 → 见 `MEMORY.md § 数据规则`。本节只补充 TOOLS-specific 实现细节：

- `prev_close` 由 Polygon `/prev` 历史接口独立获取（带日期戳）。回退链：Polygon历史 → API pc字段 → 保留现有（3天内） → 从dp%反推
- `prev_close_date` 字段同步写入 portfolio.json，可验证前收来自哪个交易日
- 脚本跑完后 `today_change` 字段即可直接信任，无需换算

---

## 当前持仓

**Single source of truth：`portfolio.json`**（不在此重复，避免漂移）

结构特征（风格/集中度/已清仓名单）见 `memory/current-portfolio-summary.md`，不在此重复。

---

## 现有脚本梳理（精简索引 — 完整说明见 `docs/reference/commands.md`）

**数据抓取/分析**：`clawock us-quotes`(美股7路fallback,写回portfolio) · `clawock analyze-us`(刷价+RSI/MA+新闻+信号) · `clawock analyze-hk`(腾讯+东财双源对账→stooq/yf兜底) · `clawock benchmark`(SPY/HSI/HSTECH 日线) · `clawock fx`(USDHKD 3路,**book total 必先调**) · `clawock filings`(SEC EDGAR) · `clawock fundamentals`(东财中文基本面,**港股财报**)双保险 · `clawock catalysts`(14d催化→catalysts.json) · `influencer-scan.yml`(KCNyu 定时 Trump/Musk 雷达) · `clawock portfolio-risk`(β/Vol/DD/Sharpe→risk.json) · `clawock quant`(趋势/动量/RSI/z/ATR吊灯/vol-target→quant_signals.json+history.jsonl留痕,杠杆ETF按标的) · `clawock quant-review`(留痕vs前瞻收益→因子edge表,n<20不解锁,brief按edge取信)

**研究生命周期（手动/事件驱动，产物即真源）**：`clawock entry-gate`(建仓前研究闸,信息分级≠投资质量,硬否决先于计分→`memory/entry-gates/`) · `clawock earnings`(一手财报复盘+管理层承诺账本,盈利质量由代码算→`memory/earnings/`) · `clawock thesis`(canonical thesis + 只认证据的 drift→`memory/theses/`) · `clawock provenance`(数字两源+Decimal 精算,准出闸) · `clawock research`(把上面三类 artifact 汇成待办队列;brief preflight 读它,`--check` 进 system_check 与 CI) · `ops/host/cron_token_audit.py`(每 cron 最新一跑的 token 量 vs **同 provider** 滚动中位数,跨 provider 比是假的;只进 daily health不告警不改 exit code) · `clawock plan-context`(08:00 简报还没成交的决策→report/intraday preflight 的 `plan_context`;真源是 `decisions.jsonl` 不是 plan 文件,因为执行状态只写回账本;永不抛异常) · `clawock mover-evidence`(盘中异动票的一手催化探针:SEC/港交所公告分钟级,券商研报与 7×24 只作 supporting;有预算上限、失败降级、不碰 Tavily;filing 三级分流 `config/filing-triage.json`、基金看穿到标的、美股停牌 feed)

**Harness（三明治：preflight 确定性 → LLM 合成 → postflight 校验+commit）**
实现装在 `clawock` 里，**入口只有 CLI**，仓库里没有第二套 instance harness。
- brief：`clawock brief preflight` / `clawock brief postflight`（写 `memory/{date}-pre-open.md` + `-plan.json`；postflight 自动刷完整 dashboard generation 并 push）
- 报告 Mode 6：`clawock report preflight --market {hk|us} --phase {open|mid|pm|close}` / `clawock report postflight …`
- 盘中 Mode 7：`clawock intraday preflight --market {hk|us}` / `clawock intraday postflight …`（不提交 `portfolio.json`；dashboard 仅语义变化发布，逐 slot heartbeat 必发布）
- 共通：preflight 出 `raw_wechat_block`(LLM **verbatim** 拷) + `anomalies`(必提≥1票) + `plan_context`(08:00 未成交决策,散文必须对账、股数照抄不许心算)；postflight 出 `wechat_prefix`；context 全落 `memory/.tmp/`(gitignore)

**Dashboard/发布**：KCNyu 三类 postflight 自动刷新完整 generation；host 补发入口 `ops/publish/publish_dashboard.sh` · `clawock dashboard-outputs`(统一 ownership + 语义 diff，忽略纯构建时间并给出精确 staging pathspec) · `ops/publish/safe_push.sh`(唯一 push 路径,rebase.autoStash 容脏树)

**LLM-free Telegram 兜底哨兵（系统 crontab，非 openclaw cron）**
- report / brief / intraday postflight 主发 WeChat 并同步 Telegram；watchdog 读真实 delivery marker，只在 Telegram marker 缺失或失败时补投，不再猜 run summary、也不重发 WeChat。
- `.tmp/*-sent-*.json` + slot key 做幂等，避免长 turn / cron retry 双发。

**其它正式入口**：`clawock mark-followed`(标 `decisions.jsonl` 的 execution.status) · `clawock audit-resettle`(默认只审计结算变化，`--write` 才落账) · `clawock integrity`(资金/行情完整性闸) · `clawock validate-sidecar`(发布产物结构闸) · `clawock evidence`(由实测产物重建证据与反证页) · `clawock news-evidence`(公告/新闻/日历去重、到期与确认图) · `clawock reconcile`(手工记录 `holdings[].trades[]` 与 broker 真值叶子后，统一重算 aggregates/cash/realized 并过完整性闸)。远端 LLM 自动化装成 `clawock-news-digest` / `-weekly-review` / `-influencer-scan` / `-brief-fallback`，只由 GitHub Actions workflow 调用，不是 OpenClaw 工具。**完整命令与内部 job 索引 → `docs/reference/commands.md`**。

### Cron map

11 个 OpenClaw job、11 个 watchdog pass（6 report + 3 intraday + 08:30 brief 投递兜底 + 09:05 brief miss-detector）、EDT/EST 两季表达式和 harness 映射只在
[`config/cron-schedules.json`](config/cron-schedules.json) 维护；人读表由
[`docs/operations/cron-schedules.md`](docs/operations/cron-schedules.md) 自动生成。每日 06:20 HKT 的同步器按
`America/New_York` 自动调整美股 live cron + watchdog；system check 同时校验 schedule、
payload 语义和 crontab。Mode 7 的逐 slot 结果发布到 `assets/data/cron-heartbeats.json`。

## Skill 安装顺序（重要）

见 `docs/operations/skills-store-policy.md`。**先 `skillhub`（cn-optimized）再 `clawhub`（公开 registry）兜底**：

```bash
skillhub search <kw>         # 第一选择
skillhub install <slug>      # cn-optimized 源
# 不可用 / 无匹配 / 限流时 →
clawhub search <kw>
clawhub install <slug>
```

安装前列出 source / version / risk signal 给用户确认。

## Skill 路由表（什么场景用哪个）

| 场景 | 入口 skill | 备注 |
|---|---|---|
| "分析 RKLB" / "compare AAPL vs MSFT" / 美股个股问题 | `us-stock-analysis` | 4 模式（quick/technical/fundamental/full）+ sentiment mode 5 |
| "分析 00100" / "07226 怎么样" / "恒科今天" / 港股问题 | `hk-stock-analysis` | 4 模式 + 港股专属 sentiment（雪球/富途）+ 南向资金 |
| "看下持仓 / 节后操作 / 持仓有什么风险" | `portfolio-risk-review` | 单 pass、4 lens、快速可行动 |
| "深度复盘 / 持仓全面诊断 / 大幅调仓前" | `portfolio-swarm-review` | 3 tier（analyst→bull/bear→risk debate）+ confidence 评分，重，慢 |
| "用 Serenity 的方式看 X" / 产业链卡点深挖 / AI半导体瓶颈选股 / thesis 压力测试 | `serenity-skill` | 供应链 chokepoint 框架（8 因子评分卡 `skills/serenity-skill/scripts/serenity_scorecard.py`）；**重、手动深挖、不进 cron**；证据阶梯把 KOL/社媒判弱证据 → 对冲追微盘 pump |
| 教育性问题（"什么是 MACD"、"position sizing 怎么算"） | `trading`（clawhub 装的） | guardrails 重、不给具体买卖判断；具体判断走上面 4 个 |
| 抓需 JS 渲染 / 反爬的页面（雪球评论 / Futu 社区 / Reddit 深页） | `scrapling` | 配合上面的 stock-analysis Mode 5 调用 |
| Web 搜索（新闻 / X / 中文社区 / 政策） | `tavily-search` | 不要让模型自己改用 Yahoo/Google 临时拼搜索。**免费档 1000 credits/月全局共享**，调用必带 `--bucket`（brief/report/intraday/research/extract）；盘中常规盯盘别烧、超限自动优雅降级回内置搜索 |
| openclaw 升级后健康检查 / 磁盘膨胀 | `openclaw-tune` | 不动股票 |
| 「这票值不值得研究」/ 建仓前先筛新标的 | `entry-gate` | 信息分级 A/B/C 与投资质量分开;四条硬否决先于任何计分;C 级只判 gray 不判死;产物 `memory/entry-gates/` |
| 「财报出了 / 复盘这个季度 / 当初承诺兑现了吗」 | `earnings-review` | 一手 filing/港交所公告优先,盈利质量由代码算,承诺账本跨期滚动;事件驱动、不进 cron;产物 `memory/earnings/` |
| 盘前深度简报（cron #10 自动跑，非人工入口） | `daily-deep-brief` | preflight 出 context → swarm 分析 → plan.json;人工别手动触发,改它先读 SKILL 的 postflight schema |
| openclaw 升级 / 依赖迁移 | `openclaw-upgrade` | 升级后必数 cron 个数;不动股票 |
| issue / PR / CI run / gh api | `github` | 走 `gh` CLI;仓库改动仍遵守 AGENTS.md 的 worktree→PR 规矩,别直接推 master |

`skills/_shared/` 不是 skill，是 hk/us 共用的片段（盘中 status sidecar 规范）——改盘中横幅只改那一份。

研究生命周期各环节跑多勤（每天 / 按事件 / 每次 push）见 `docs/operations/research-cadence.md`。

⚠️ **不要做的 routing 错误**：
- `trading` skill 默认禁止"直接买卖建议" → 用户问"应该买不买" 时不走它，走 `us/hk-stock-analysis`（用户偏好已写在 MEMORY.md）
- 持仓问题不要走 `us-stock-analysis` 的 Full Report → 走 `portfolio-risk-review`（持仓视角）
- 单只股的分析也不要走 `portfolio-swarm-review`（杀鸡用牛刀）→ 走 `us/hk-stock-analysis` Mode 4

## 情绪面数据源速查

按市场和重要性顺序：

### 美股
1. **Finnhub news** —— `clawock analyze-us` 默认拉取，主英文媒体 + 关键词情绪打分
2. **Tavily** —— 新闻 + X/Twitter trending（`node skills/tavily-search/scripts/search.mjs "{TICKER} sentiment" --topic news --bucket report`）；⚠️ 仅开/收盘报告或盘中真事件用，带 `--bucket report`/`intraday`，盘中常规盯盘不烧 Tavily
3. **Reddit JSON**（无需 auth）—— r/wallstreetbets（散户动量）+ r/stocks（理性）：
   ```bash
   curl -sH "User-Agent: openclaw/1.0" "https://www.reddit.com/r/wallstreetbets/search.json?q={TICKER}&restrict_sr=1&sort=new&limit=25"
   ```
4. **scrapling** —— 上述源失败或要评论级深度

### 港股
1. **Finnhub news** —— 港股覆盖稀疏但能拿到 Reuters/Bloomberg/SCMP
2. **Tavily 中文搜索** —— 主要中文媒体 + 政策
3. **雪球 HK 评论区**（scrapling StealthyFetcher）—— `https://xueqiu.com/S/HK{TICKER}`，港股散户情绪核心
4. **富途牛牛社区**（scrapling）—— `https://www.futunn.com/stock/{TICKER}-HK`
5. **南向资金 净流入**（Tavily 搜当日）—— 港股大盘情绪锚

### 跨市场宏观情绪
- VIX（美股恐慌指数）—— Tavily 搜或脚本扩展
- HIBOR（港元流动性）—— Tavily 搜，HIBOR 升 = 港股估值压力
- 美债收益率 —— 影响成长股估值

---

## 维护建议
- 交易发生后：记录 `holdings[].trades[]` + broker 真值叶子，跑 `clawock reconcile`，再更新当天 `memory/YYYY-MM-DD.md`
- 规则变化后：更新 `MEMORY.md`
- 持仓结构明显变化后：更新 `memory/current-portfolio-summary.md`
- 脚本数据源变化后：同步更新 `TOOLS.md` 与 `MEMORY.md`
