# Tool operations reference

按当前任务查相应章节；日常对话不需要全文读取。入口与 skill 路由见根目录 `TOOLS.md`。

## 公共发布层（仓库 = `github.com/KCNyu/clawock`）

- Repo 是 **public**，含真实仓位（用户已知情授权）
- Dashboard live: https://kcnyu.github.io/clawock/ — 自动从 `assets/data/dashboard.json` 取数
- Briefs index: https://kcnyu.github.io/clawock/briefs.html — 自动列 `memory/*-pre-open.md`
- `site/_layouts/default.html` 给 markdown 页面统一样式（`site/briefs.md` 等）；dashboard 自身由 `site/index.html` + `site/assets/{css,js}` 构成
- Pages 自动 build on push

### GitHub Actions 分工

| Workflow | 触发 | 写文件 | 备注 |
|---|---|---|---|
| `ci.yml` | push to master + 每个 PR + 周六 03:41 UTC | (read-only) | 合并后的 lint/actionlint、schema/import/pytest、CodeQL；按 `ops/ci/push_scope.py` 分类决定跑哪些 job。只改账本（`BOOK_GLOBS`：portfolio.json、计划、决策账本、EOD 归档）的 push 走 `book` lane：数据闸全跑、pytest 只跑 `-m book`（读真实账本的测试），不跑全量 |
| `dashboard-artifact-gate.yml` | `repository_dispatch: data-plane-published` | (read-only) | 与 `pages.yml` 同一事件，GitHub runner 上零依赖校验发布到 data 分支的首屏 payload；只有语义变了的一代才会派发（时钟字段、以及内容摘要未变的 `code_commit`/`source_ref` 指针按 `config/dashboard-outputs.json` 不算变化） |
| `pages.yml` | 站点/数据 push + `data-plane-published` | (Pages) | 部署 GitHub Pages；并发组 `pages` 排队不取消 |
| `weekly-health.yml` | 周日 20:17 UTC | (read-only) | 综合健康检查（含公网数据源活体） |
| `eod-archive.yml` | 周五 22:00 UTC | `memory/archive/eod-history.csv` | 每周持仓快照 audit trail |
| `sentiment-scan.yml` | 周日–四 21:30 + 21:55 UTC | `assets/data/sentiment.json` + `factor-snapshots/sentiment/` | 05:30 HKT 盘前 Reddit + Google News 扫描；21:55 为失败/取消重试；已有本周期有效产物则排程跳过 |
| `macro-scan.yml` | 周日–四 21:45 + 21:55 UTC | `assets/data/macro.json` + `factor-snapshots/macro/` | 05:45 HKT 盘前宏观扫描；21:55 为失败/取消重试；已有本周期有效产物则排程跳过 |
| `brief-fallback.yml` | 工作日 00:25/00:47/01:09 UTC + 周三 04:23 彩排；host watchdog 09:05 HKT dispatch | brief/plan + harness 产物 | 主 brief 缺失且未晚于 10:00 HKT 才由远端 LLM 接管 |
| `weekly-review.yml` | 周日 14:00 UTC (22:00 HKT) | `memory/weekly/{ISO-week}.md` | MiniMax-M3.1-Flash 周复盘（无回退模型） |
| `news-digest.yml` | 工作日 13:00 UTC (21:00 HKT) | `assets/data/us_news_digest.json` | 美股开盘前 48h 新闻提炼 |
| `influencer-scan.yml` | 周日–四 21:40 + 工作日 12:50 UTC | `assets/data/influencer_feed.json` | 盘前 + 美股盘前两班影响力雷达（Trump 原帖 / Musk 报道 / ARK 日度调仓 / Serenity / 段永平·洪灏·Burry·Pelosi 报道，8 源） |
| `cron-health.yml` | 周一–六 09:17 UTC (17:17 HKT) | (read-only) | 用 tracked cron contract + HKT commit date 巡检漏跑 |
| `screenshot-refresh.yml` | 周日 22:00 UTC | `site/assets/social-card.png` + `site/assets/shadow-backtest.png` + `site/assets/books.svg` / `books-narrow.svg` + README 的 `CW_M` 数字 | 每周刷新社交卡里的 Hero 截图和实时战绩图；美股/港股分账盈亏卡由 `ops/growth/refresh_readme_metrics.py` 调 `site/tools/build_readme_book_charts.py` 从 data-plane 的 `dashboard.json` 重画；`site/assets/dashboard.gif` 只在手动 dispatch 时生成，仅存仓库、不进入 Pages 产物 |
| `repo-traffic.yml` | 周二/六 03:38 UTC | `assets/data/repo-traffic.json` + `schedule-drift.json` | Measurement Capture；漂移按 `config/schedule-punctuality.json` 由 cron-health 判 |
| `seo-visibility.yml` | 周一 06:30 UTC | `assets/data/crawl_visibility*.json` | 每周爬虫/搜索可见度采样 |

宏观/情绪以主机 07:20 HKT dispatch 为盘前刷新入口。两档 GitHub 排程保留作
host-down 兜底与失败/取消重试；`skip_completed_scan.py` 在 `data-write` 锁内的
最新 master checkout 上、采集前验证已有 sidecar。`generated_at` 必须介于 health
card 定义的首次日排程与当前时间之间，且通过原有 coverage validator，才跳过
采集、归档和提交。缺失、坏文件、过期或未来时间戳均允许重试。它不消除 GitHub
排程 run 本身，也不保证主机停机时赶上简报；`schedule-punctuality.json` 继续记录
这一被接受的延迟。dispatch 仍是显式刷新（可用于同周期修复）；原有
`hold_unchanged_sidecar.py` 仍只压掉仅时间戳变化的重扫。Influence 早晚两档是
不同采样周期，保留两次真实更新，不套用盘前兜底闸。回滚只需撤销该闸，无状态迁移。

**远端 LLM 路径**: 本地市场 cron 与远端 `clawock.automation.llm` 都以 MiniMax-M3.1-Flash 为主；远端**只有 MiniMax 一个 provider**——2026-09-13 起移除了 opencode-go DeepSeek V4 Flash 回退（钱包早已清零，回退腿只会再报一次 401），链上不挂任何按量付费模型。4 个 LLM workflow（news-digest / weekly-review / brief-fallback / influencer-scan）均只从 repo secrets 读 `MINIMAX_API_KEY`，仓库不落 key。

**数据扫描 GH Action 不写 `assets/data/dashboard.json`**，只写各自 sidecar；dashboard
只由 harness postflight（含远端 brief fallback 复用同一 postflight）和 host 上加锁的
`ops/publish/publish_dashboard.sh` 发布。

## Web 搜索 provider

DeepSeek Search 与 Tavily 是**并列**的两个 web 搜索源（kcn 2026-10-18：并发一起用，谁都不是谁的备份，也不退役）。
`clawock web-search`（`clawock.evidence.web_search`）一次查询**同时**问两边，输出按 provider 分节、各自带 `status`；
一个源 `unavailable`/`empty` 只描述它自己，不改变另一个源的结果。代码里没有「A 失败才问 B」的分支：
`web_search.search_all` 对每个 provider 各起一个并发调用，结果按 provider 存放，合并时每行保留 `provider`。

| provider | 接入 | 限额 | 节流在哪里 |
|---|---|---|---|
| DeepSeek Search/Fetch | `market_data/deepseek_search.py`，`POST https://api.deepseek.com/v1/tools/search`、`/v1/tools/fetch`，Bearer 同 DeepSeek chat key | 无 credits 预算；**账号级 QPS：Search 5、Fetch 5**（与 key 无关，与模型并发独立；Fetch 另有按目标域名的 QPS）；¥5 / 1000 次**成功**请求（Search 结果为空、Fetch 无正文不计费） | 本机所有进程共用一把文件锁限速（`~/.cache/clawock/deepseek-search/<endpoint>.json`，每秒 ≤5 次起跑）；408/429/5xx 在调用方 deadline 内最多重试 3 次，400/401/402/403/404/413 不重试（官方规则） |
| Tavily | `skills/tavily-search/scripts/search.mjs` / `extract.mjs` | 免费档 **1000 credits/月**全局共享，按 bucket 切：brief 300 / report 280 / intraday 120 / research 100 / extract 80 / default 60 | 脚本自己的 credit 账本（`/root/.openclaw/tavily-credit-ledger.json`，预留式扣费，超额 exit 0 返回 unavailable）+ 各调用方的调用策略 |

**各入口的调用策略（按 provider 分别定）**

| 入口 | DeepSeek | Tavily |
|---|---|---|
| 盘中 Tier 2 `live_sources`（盘中 / 简报 / 报告共用） | `deepseek_search` 源：每档每个发行人/指数主题一次（`after:` 限窗口，20 分钟 TTL），单次 ≤12 个请求 | 不接（每档每票会烧掉 intraday 桶） |
| 盘中 Tier 3 `anomaly_search`（只在有异动时） | 每只异动票每档刷新一次（25 分钟 TTL） | 每只异动票**每个交易日一次**，`--bucket intraday`；120 credits/月 ÷（22 天 × 2 市场）≈ 每市场每天 2–3 只 |
| 简报 Step 3 板块全景、`tavily_resolution_queue` | 同一条 `clawock web-search` 里并发；同行/催化可另跑 `--providers deepseek` | 每个去重 theme 一次 + 队列事件，`--bucket brief` |
| 人工对话 / 开收盘报告 / swarm review | 随时可用 | 开收盘或真事件，`--bucket report` / `research` |
| 盘中 cron 模型自己补查 | `--providers deepseek` | 禁止 |

**取 key**：`DEEPSEEK_API_KEY` 环境变量（OpenClaw 配置的 `env` 段导出给 cron 与会话）→ `/root/.dsh/.credentials.yaml` 的 `refs.DEEPSEEK_API_KEY`
（`CLAWOCK_DSH_CREDENTIALS` 可改路径）。两处同值；key 不进日志与卡片。
Tavily 用 `TAVILY_API_KEY`（OpenClaw `env`）。

**结果怎么读**：DeepSeek 的 `date` 只有日精度时落在北京时间 00:00（UTC 16:00），归一化为 `filed_date`，卡片写「今日发布、时刻未知」而不是盘中实时；
`date` 为 null 的结果在 live sources 里丢弃（无法判新旧）。`authority`(0–4，−1 未知) 与 `rerank_score`(0–3) 原样保留在行上，
**不**直接当作分级：券商行情页常被打 3 分。分级只看站点（`live_sources.host_grade`：交易所/监管 = primary，Reuters/财新/证券时报/东财等 = authoritative，股吧等论坛 = soft），
行情页/个股概览页（标题只有名称+代码，或含「股价、新闻」「Stock Price, Quote」）丢弃。

**覆盖边界**：DeepSeek 搜的是它自己的索引。雪球、富途、微信公众号这类 JS 渲染或反爬页面，搜索最多给索引摘要，`--fetch` 常返回 404；
不能因为接了搜索就算覆盖了这些源，拿不到要明说缺口。

**计费时间点**：DeepSeek 官方说明，在 DeepSeek Harness / Claude Code / Codex 中使用 DeepSeek API 时由服务端工具调用产生的 Search/Fetch
目前不计费，**自北京时间 2026-11-01 00:00 起按次收费**。本仓库的直连调用（上表）本来就是按次计费；11-01 之后 dsh 等 agent 会话里的服务端搜索也开始计费。

## Task routes

- Commands and arguments: [generated command reference](commands.md), or
  `clawock COMMAND --help`.
- Provider coverage, quote quality and failure semantics: [data coverage](data-coverage.md).
- Lifecycle and delivery: [harness](../architecture/harness.md); intraday-specific
  rules: [intraday agent](../architecture/intraday-agent.md).
- Schedule and watchdog mapping: [generated cron contract](../operations/cron-schedules.md).
- Skill installation: [registry policy](../operations/skills-store-policy.md).
- Trades: record broker truth and `holdings[].trades[]`, then `clawock reconcile`.
  Holdings and closed names are read from `portfolio.json`, never copied here.
