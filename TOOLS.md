# Rick's Stock Analysis Tools

## 当前结构总览
- 权威持仓：`portfolio.json`
- 长期规则与偏好：`MEMORY.md`
- 投资工作流：`INVESTMENT_SOP.md`
- 当前持仓摘要：`memory/current-portfolio-summary.md`
- 每日复盘/交易日志：`memory/YYYY-MM-DD.md`
- 数据脚本（被 harness / 手动调用）：`scripts/data/`
- Harness 脚本（cron 调起）：`scripts/harness/`
- 历史/参考脚本：`scripts/legacy/`
- Dashboard 入口：`index.html` (落到 `kcnyu.github.io/clawock`)；数据 `assets/data/dashboard.json` 由 `scripts/data/build_dashboard.py` 聚合
- 快速查看：`check_portfolio.sh`

## 公共发布层（仓库 = `github.com/KCNyu/clawock`）

- Repo 是 **public**，含真实仓位（用户已知情授权）
- Dashboard live: https://kcnyu.github.io/clawock/ — 自动从 `assets/data/dashboard.json` 取数
- Briefs index: https://kcnyu.github.io/clawock/briefs.html — 自动列 `memory/*-pre-open.md`
- `_layouts/default.html` 给 markdown 页面统一样式（briefs.md 等）；dashboard 自身（`index.html`）CSS/JS 全 inline，不依赖 `assets/dashboard.{css,js}`（v2 重构已删）
- Pages 自动 build on push

### GitHub Actions 分工

| Workflow | 触发 | 写文件 | 备注 |
|---|---|---|---|
| `harness-regression.yml` | push to master | (read-only) | 每次 push 跑 schema/import 校验 |
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
| `screenshot-refresh.yml` | 周日 22:00 UTC | `social-card.png` + `shadow-backtest.png` | 每周两张 PNG；GIF 只在手动 dispatch 时生成 |

**远端 LLM 路径**: 本地市场 cron 与远端 `xiaomi_llm.chat()` 都以 MiniMax M3 为主；远端在可选 `XIAOMI_API_KEY` 仍有效时可 fallback 到 MiMo v2.5-pro。4 个 LLM workflow（news-digest / weekly-review / brief-fallback / influencer-scan）均只从 repo secrets 读 key，仓库不落 key。

**数据扫描 GH Action 不写 `assets/data/dashboard.json`**，只写各自 sidecar；dashboard
只由 harness postflight（含远端 brief fallback 复用同一 postflight）和 host 上加锁的
`publish_dashboard.sh` 发布。

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
python3 scripts/data/analyze_us_stocks.py   # 美股
python3 scripts/data/analyze_hk_stocks.py   # 港股
```

### 3. 快速查看持仓
```bash
bash check_portfolio.sh
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
python3 scripts/data/analyze_us_stocks.py   # 美股完整分析（RSI/MA/新闻/信号）
python3 scripts/data/analyze_hk_stocks.py   # 港股完整分析（恒指/恒科/P&L/信号）
# 共通 flag：--no-news(省Finnhub配额) --no-fetch(用缓存价) ；hk 另有 --dry-run
python3 scripts/data/fetch_us_stocks.py     # 仅刷美股价格
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
- `python3 scripts/data/fetch_fx.py --json` → `{"rate": 7.83, "source": "Frankfurter", ...}`
- 换算：`python3 scripts/data/fetch_fx.py --convert 10000 HKD USD`
- fallback：Frankfurter → exchangerate.host → Yahoo HKD=X；4h 本地缓存

### 美股基本面 / SEC filings
`fetch_us_filings.py {TICKER}` — SEC EDGAR 免费无 key：10-K/10-Q/8-K、`--financials`(XBRL 13项)、`--form4`(insider)、`--13f`、`--json`。速率 8/sec；非美股票返回 "CIK not found"；**纯基本面补充，不替代 fetch_us_stocks 抓价**。完整参数表+注意事项 → `TOOLS_SCRIPTS.md`。

### 港股/美股基本面(中文) — 东财 datacenter
`fetch_fundamentals_em.py {CODE}` — 无 key，**填港股财报空白**：`--indicators`(GMAININDICATOR ROE/EPS/毛利率/资产负债率，美+港) / `--statements income|balance|cashflow`(中文科目行) / `--json`。美股数字以 SEC 为准、此为中文速查。datacenter-web+searchapi 子域实测稳；**资金流 `fetch_fundflow_em.py`(push2his)本机 IP 被封暂不可用**。

### 说明

数据/缓存铁律 → 见 `MEMORY.md § 数据规则`。本节只补充 TOOLS-specific 实现细节：

- `prev_close` 由 Polygon `/prev` 历史接口独立获取（带日期戳）。回退链：Polygon历史 → API pc字段 → 保留现有（3天内） → 从dp%反推
- `prev_close_date` 字段同步写入 portfolio.json，可验证前收来自哪个交易日
- 脚本跑完后 `today_change` 字段即可直接信任，无需换算

---

## 当前持仓

**Single source of truth：`portfolio.json`**（不在此重复，避免漂移）

### 持仓结构特征（相对稳定）
- 风格激进，波动容忍度较高
- 港股风险集中在 `00100` MiniMax 和 `07226` 两倍恒科
- `03032/03033` 属于相对更稳的科技敞口
- 美股偏高弹性成长 + 杠杆短线仓
- 韩股已完全清仓（07709/07747/000660/005930 不追踪）

---

## 现有脚本梳理（精简索引 — 完整说明见 `TOOLS_SCRIPTS.md`）

**数据抓取/分析**：`fetch_us_stocks.py`(美股7路fallback,写回portfolio) · `analyze_us_stocks.py`(刷价+RSI/MA+新闻+信号) · `analyze_hk_stocks.py`(腾讯+东财双源对账→stooq/yf兜底) · `fetch_fx.py`(USDHKD 3路,**book total 必先调**) · `fetch_us_filings.py`(SEC EDGAR) · `fetch_fundamentals_em.py`(东财中文基本面,**港股财报**) · `fetch_catalysts.py`(14d催化→catalysts.json) · `fetch_influencer_feed.py`(Trump/Musk雷达→influencer_feed.json) · `portfolio_risk_metrics.py`(β/Vol/DD/Sharpe→risk.json) · `compute_quant_signals.py`(趋势/动量/RSI/z/ATR吊灯/vol-target→quant_signals.json+history.jsonl留痕,杠杆ETF按标的) · `quant_signal_review.py`(留痕vs前瞻收益→因子edge表,n<20不解锁,brief按edge取信)

**Harness（三明治：preflight 确定性 → LLM 合成 → postflight 校验+commit）**
- brief：`brief_preflight.py` / `brief_postflight.py`（写 `memory/{date}-pre-open.md` + `-plan.json`；postflight 自动跑 build_dashboard + push）
- 报告 Mode 6：`report_preflight.py --market {hk|us} --phase {open|mid|pm|close}` / `report_postflight.py …`
- 盘中 Mode 7：`intraday_preflight.py --market {hk|us}` / `intraday_postflight.py …`（不提交 `portfolio.json`；dashboard 仅语义变化提交，逐 slot heartbeat 必发布）
- 共通：preflight 出 `raw_wechat_block`(LLM **verbatim** 拷) + `anomalies`(必提≥1票)；postflight 出 `wechat_prefix`；context 全落 `memory/.tmp/`(gitignore)

**Dashboard/发布**：`build_dashboard.py`(聚合 portfolio+snapshots+plan+decisions.jsonl+risk+sidecar → `assets/data/dashboard.json`；含 LLM 叙事卡/driven_by/status_banner；三类 postflight 都会自动调) · `safe_push.sh`(统一 push,rebase.autoStash 容脏树)

**LLM-free Telegram 兜底哨兵（系统 crontab，非 openclaw cron）**
- report / brief / intraday postflight 主发 WeChat 并同步 Telegram；watchdog 读真实 delivery marker，只在 Telegram marker 缺失或失败时补投，不再猜 run summary、也不重发 WeChat。
- `.tmp/*-sent-*.json` + slot key 做幂等，避免长 turn / cron retry 双发。

**其它**：`mark_followed.py`(标 `decisions.jsonl` 的 execution.status) · `xiaomi_llm.py`(GH Action 直连 vendor，MiniMax→可选 Xiaomi fallback) · `gh_action_*.py` · `reconcile.sh`(手工记录 `holdings[].trades[]` 与 broker 真值叶子后，统一重算 aggregates/cash/realized 并过完整性闸)。**每脚本详细说明 + 已废弃 legacy → `TOOLS_SCRIPTS.md`**。

### Cron map

11 个 OpenClaw job、10 个 watchdog、EDT/EST 两季表达式和 harness 映射只在
[`config/cron-schedules.json`](config/cron-schedules.json) 维护；人读表由
[`CRON_SCHEDULES.md`](CRON_SCHEDULES.md) 自动生成。每日 06:20 HKT 的同步器按
`America/New_York` 自动调整美股 live cron + watchdog；system check 同时校验 schedule、
payload 语义和 crontab。Mode 7 的逐 slot 结果发布到 `assets/data/cron-heartbeats.json`。

## Skill 安装顺序（重要）

见 `skills-store-policy.md`。**先 `skillhub`（cn-optimized）再 `clawhub`（公开 registry）兜底**：

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
| Web 搜索（新闻 / X / 中文社区 / 政策） | `tavily-search` | 不要让模型自己改用 Yahoo/Google 临时拼搜索 |
| openclaw 升级后健康检查 / 磁盘膨胀 | `openclaw-tune` | 不动股票 |

⚠️ **不要做的 routing 错误**：
- `trading` skill 默认禁止"直接买卖建议" → 用户问"应该买不买" 时不走它，走 `us/hk-stock-analysis`（用户偏好已写在 MEMORY.md）
- 持仓问题不要走 `us-stock-analysis` 的 Full Report → 走 `portfolio-risk-review`（持仓视角）
- 单只股的分析也不要走 `portfolio-swarm-review`（杀鸡用牛刀）→ 走 `us/hk-stock-analysis` Mode 4

## 情绪面数据源速查

按市场和重要性顺序：

### 美股
1. **Finnhub news** —— `scripts/data/analyze_us_stocks.py` 默认拉取，主英文媒体 + 关键词情绪打分
2. **Tavily** —— 新闻 + X/Twitter trending（`node skills/tavily-search/scripts/search.mjs "{TICKER} sentiment" --topic news`）
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
- 交易发生后：记录 `holdings[].trades[]` + broker 真值叶子，跑 `bash scripts/data/reconcile.sh`，再更新当天 `memory/YYYY-MM-DD.md`
- 规则变化后：更新 `MEMORY.md`
- 持仓结构明显变化后：更新 `memory/current-portfolio-summary.md`
- 脚本数据源变化后：同步更新 `TOOLS.md` 与 `MEMORY.md`
