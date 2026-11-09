# Data coverage and health

Sources are independent operators, not URL counts. A mirror of the same filing
adds an access route, not independent financial evidence. Coverage varies by
instrument: a provider listed below does not promise every new IPO or ETF.

| Surface / entry | Assets and fields | Sources and independence | Failure behavior |
|---|---|---|---|
| US quotes (`analyze-us`, `us-quotes`) | US stocks/ETFs: price, prior close, day change, range, volume | Nasdaq, Eastmoney, Finnhub, Yahoo, Alpha Vantage, Polygon, Tencent; key-dependent providers require existing credentials | Completeness/freshness-ranked fallbacks; missing requested tickers prevent whole-leg write; incomplete data explicitly flagged |
| HK quotes (`analyze-hk`) | HK stocks/ETFs: price, prior close, range, volume | Tencent + Eastmoney cross-check; Stooq and Yahoo fallback | Disagreement is surfaced; OHLC-only Stooq cannot invent a previous close; new IPO coverage may effectively be Tencent-only |
| Daily / intraday bars (`bars`, quant, intraday recommendations) | Registered equities, ETFs and underlying indices; OHLCV and sessions | Tencent daily plus asset-specific history providers; intraday provider coverage is separate | Canonical merge rejects conflicts and records them; gaps and stale sessions reported by integrity; no invented bars |
| FX (`fx`) | USD/HKD conversion | Frankfurter (ECB), ExchangeRate-API Open, Yahoo | 4h cache; Open API checks base, success and provider age; all routes fail → explicitly stale cache, then explicitly labelled peg estimate; cached-only readers return unavailable when absent |
| Fund flows (`fundflow`) | Provider-covered HK/US instruments; daily classified order-size net flows | Eastmoney only (one operator) | `status=unavailable` on empty/failed response, not zero flow; source and latest data date included. This is vendor-classified order flow, not audited institutional cash movements |
| Financial statements / fundamentals (`fundamentals`, `filings`) | HK/US issuer periods: revenue, profit, EPS, margins, balance/cash-flow items | Eastmoney for HK/US; SEC XBRL for US (independent access, issuer-reported facts) | Empty Eastmoney result is explicitly unavailable; US exchange-suffix retry is the same source; SEC needs a configured identifying contact, not an API key. ETFs require underlying look-through |
| Disclosures / catalysts | US SEC forms, HK announcements, earnings and official event dates | SEC submissions/full-text, Nasdaq/Finnhub mirrors, HKEXnews, Tencent; mirrors do not count as new underlying facts | Source status and publication time retained; date-only mirrors cannot manufacture acceptance times |
| Macro (`macro`) | VIX, 10Y yield, DXY, HSI/HSTECH, SPX, Nasdaq Composite, F&G and Fed releases | Stooq/Tencent/Yahoo according to symbol; Cboe official VIX fallback; CNN; Federal Reserve | `coverage` reports each quote's availability/date independently. A current SPX cannot hide stale VIX. New-producer snapshots recheck series dates on brief read and omit bad rows |
| Official yield curve (`macro`) | 14 Treasury par maturities from 1 month to 30 years, 10Y−2Y and 10Y−3M in basis points | US Treasury public CSV, independent of Yahoo; also supplies the dated 10Y fallback | No interpolation of missing tenors; same-date spreads only; max 7 calendar-day observation age, explicit dates account for bond holidays |
| Personal analyst research (`fundamentals --analysts`) | US issuer recommendation counts and already-reported quarterly EPS estimate/actual/surprise | Existing Finnhub free key; two requests per issuer, cached 24h | Private stdout/ignored cache only; denied/rate-limited/missing states explicit; historical EPS estimates are not forward consensus |
| Personal credit spread (`macro --credit-spreads`) | Moody's Baa corporate yield minus 10Y Treasury, percentage points and bps | FRED public CSV, no key required for this download | Private stdout/ignored cache only; observation date/lag preserved; over 7 days is stale; not high-yield OAS |
| Volatility structure / tail risk (`macro`) | Cboe VIX (30-day), VIX9D, VIX3M, SKEW; same-session VIX/VIX3M ratio | Cboe official daily CSVs (one independent operator, four series) | Requires latest completed US session; missing prior session means unknown change; mismatched dates mean no ratio. Daily closes, not intraday ticks or return forecasts. Included in brief context; three added indices shown with dates |
| News / attention / statements | Per-issuer HK/US headlines, publication times, market flashes; Reddit attention and public-person statements | Tencent, Eastmoney, Google News RSS, Yahoo RSS, 同花顺, Finnhub; DeepSeek/Tavily search; Reddit and individual statement sources | Per-source status, cache windows and evidence timestamps; unavailable is not “no news”. Search requires existing credentials. Attention is not analyst consensus |
| Portfolio risk (`portfolio-risk`, `integrity`) | Exposure, concentration, underlying leverage, beta, range/stop checks, cash and P&L reconciliation | Derived from ledger, canonical bars, registry and FX; not another independent data vendor | Missing evidence stays unknown; integrity distinguishes arithmetic errors, quote warnings and rejected bar conflicts |

## Health entry points

- `clawock integrity`: ledger conservation, missing quotes, previous-close
  coverage, dated canonical bars, conflicts and source distribution. Its CLI
  writes an audit artifact; `portfolio.integrity.check(path)` is the read-only API.
- `clawock validate-sidecar macro|sentiment|…`: publication shape and usable
  coverage gates. Macro accepts partial coverage, but never a new snapshot with
  zero healthy market quotes. See `publish/artifacts.py` for each sidecar.
- `strategies.plugins.morning_scans.Scans`: file freshness, market-session gate,
  then per-series filtering and coverage in the brief's macro reading.
- `ops/system_check.py`: host/configuration, scheduled scan delivery, calendar
  horizon, benchmark freshness, read budgets and publication checks.
- Dashboard data-health card: generated-file freshness, integrity, product
  delivery and scheduled jobs. A recent file timestamp alone is not proof that
  all its upstream series worked; inspect the per-source/per-series fields.

## Source contracts and gaps

Cboe CSVs are linked from its [historical data page](https://www.cboe.com/tradable_products/vix/vix_historical_data/).
Only latest closes, their genuine previous closes and provenance are retained;
full downloaded history is not archived by this scanner. Fetches have 10-second
timeouts and at most four concurrent macro tasks. No account or subscription is
created. Refer to [third-party data](../legal/third-party-data.md) for rights.

ExchangeRate-API's [Open API](https://www.exchangerate-api.com/docs/free) updates
daily and requires attribution: **[Rates by ExchangeRate-API](https://www.exchangerate-api.com/)**.
It replaces exchangerate.host's key-required endpoint. The returned base must be
USD and the provider update must be no more than 96 hours old. It is a daily
reference conversion rate, not an executable FX quote.

Remaining coverage gaps include reliable HK IPO backup quotes, independent
order-flow definitions, forward analyst consensus/revisions and publicly
redistributable credit spreads. Private credit and historical analyst readings
are available through the commands above; the official Treasury curve is public.
DXY can remain unavailable during Yahoo throttling; 10Y now has an official fallback. Do not relabel futures, different indices, short interest or
news sentiment as substitutes for those fields. A proposed paid route needs
instrument coverage, licensing/redistribution terms and a current vendor quote;
no subscription, registration or contractual commitment is made by this code.

## Free accounts and low-frequency use

The implementation reuses an existing Finnhub key from the environment or the
workspace `.api_keys`; it does not create duplicate accounts to increase quota.
An analyst query uses two calls per issuer per 24 hours. Missing credentials,
403 entitlement refusals and 429 responses are distinct; no premium endpoint is
silently substituted. Free usage can still have personal-use restrictions.

- [Finnhub terms](https://finnhub.io/terms-of-service) restrict redistribution of
  data **and derived results**. New analyst output remains private and is not
  added to brief contexts, public JSON, historical snapshots or scheduled jobs.
- [FRED BAA10Y notes](https://fred.stlouisfed.org/series/BAA10Y) identify Moody's
  copyright. The private command preserves that series identity and definition;
  it is not a public dashboard feed. The public CSV needs no FRED API key.
- [Treasury data](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve)
  provide all 14 maturities in one request per macro scan, without registration.
  The correct path is `/resource-center/data-chart-center/`, not
  `/resource-center-data-chart-center/`.
- [Alpha Vantage](https://www.alphavantage.co/support/#api-key) offers a free
  25-request/day key. Its Treasury endpoint works with the existing key, but
  using one official CSV avoids spending separate calls per maturity. A generic
  free plan does not entitle every endpoint.
- [Twelve Data Hong Kong](https://twelvedata.com/exchanges/xhkg) requires Pro+;
  its Basic free US quota does not provide general HK coverage.
- [EODHD free EOD](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)
  advertises one year of history, 20 calls/day and no card requirement. This is a
  candidate for a separately verified HK close, not an implemented live-price
  replacement; symbol identity, observation time and account entitlement still
  require an actual returned quote.

These private commands are opt-in and write no `assets/data` output. Cache files
live in `.cache/private-market-data/` with mode 0600 and a 24-hour TTL; failed
refreshes never masquerade as successful cached reads. Do not copy their results
into public artifacts without the relevant redistribution permission.

## Quote quality and previous close

- `prev_close` 由 Polygon 历史收盘接口独立获取（带日期戳）。常规回退链：Polygon 历史 → API pc 字段（不同于当前价）→ 从 API dp% 反推（绝对值 > 0.01%）→ 保留现有（正数、不同于当前价，且 `prev_close_date` 精确等于行情所属时段的上一交易日）→ 当前价作为前收。没有「3 天内」的宽松窗口。
- 盘后若 Polygon 返回的是本交易日正式收盘价，先据此校正当前价，再重建前收：优先保留日期精确等于上一交易日的现有正数前收，其次从 API dp% 反推；两者都不可用时保留本日收盘价作为前收（当日变动为 0）。
- `prev_close_date` 字段同步写入 portfolio.json，可验证前收来自哪个交易日
- 报价质量拆成三个互不替代的字段，而不是一个「不完整」布尔：
  - `quote_incomplete_prev_close`：回退链没能给出日期匹配的前收（包括最后一步 `pc = c` 的占位），**场次涨跌不可算**；有前收时即使日内区间缺失也不置这一位。
  - `quote_incomplete_range`：provider 这次没给日内 high/low（或给的是更早场次的 print），持仓里的 `day_high/day_low` 只由本地累积器和采样价推得，**不能当官方区间读**；它不影响现价相对前收的涨跌。
  - `quote_stale_asof`：价格本身是更早场次的 print（所有 provider 都失败时的最后回退），当日涨跌和区间都不可信。
  - `quote_incomplete` 仍保留为三者的聚合位，供旧数据/旧读者使用。`session_change_pct()` 只被 `quote_incomplete_prev_close` / `quote_stale_asof` 否决；`STALE_PRICE` 仍对三种缺口逐条报警，措辞分开。
- Nasdaq `/info` 的 `keyStats.dayrange`（低 - 高）作为日内区间来源；缺失或无效仍标区间缺口，不用现价制造 OHLC。无需另拼无场次时间戳的 `/summary`；开盘价缺失时仍保留原采样口径。US 保留已有前收时同时验证质量标志与场次日期，旧聚合缺口、占位前收、旧 print 不会因再次刷新变成可信基准。前收仍由既有回退链解析，并由 `PREV_CLOSE_SESSION` 对 canonical bar 复核。
- 脚本跑完后 `today_change` 字段即可直接信任，无需换算；面板「场次涨跌」不是这个字段，它走 `session_change_pct()` 的报价口径。

## SEC access

`market_data/filings.py` uses SEC submissions and company-facts APIs. Configure
a real identifying contact through `SEC_USER_AGENT`; no API key is required.
The client throttles to eight requests per second, below SEC's ten-request limit,
and caches ticker-to-CIK mappings for seven days. A missing CIK is unavailable
coverage, not an issuer with no filings. This source does not replace quotes.

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

**计费**：直连 Search/Fetch 按成功请求计费；自北京时间 2026-11-01 起，
agent 会话中的服务端 Search/Fetch 也按次计费。空搜索/无正文 Fetch 的规则见上表。
