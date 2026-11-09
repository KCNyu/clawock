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

The source policies, quotas, credentials and timestamp semantics are owned by
[data coverage](data-coverage.md#web-搜索-provider). This anchor remains for
published links.

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

## 数据源清单（当前约定）

Source contracts now live in [data coverage](data-coverage.md). This compatibility
anchor keeps older workspace routes usable.
