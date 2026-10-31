# 持仓外候选发现

clawock 的 `discover-stocks` 从免费美股全市场快照生成跨板块的**待研究候选**，
每日简报展示新候选与到期复查项。候选不依赖持仓的 peer-map，不授权建仓、切换或加仓。

## 为什么需要独立入口

`market_data/peer_scan.collect` 从持仓及其同业比较出发，负责相对强弱；
`decision/add_side.read_rows` 的机会面仍以持仓及底层代理为对象。
`decision/entry.py` 和 `skills/entry-gate` 则要求先有人指定单票并提交证据，
只能判断是否值得深研，不能生成股票池。缺口在这三者之前的**候选生成层**。
自动同业扩展也不能替代跨板块发现；尤其港股同业开关受 peer-residual
预注册约束，本功能不修改该实验的股票池。

## 当前数据流与边界

| 层 | 文件与函数 | 输入 → 输出 / 消费者 |
|---|---|---|
| 股票池 | `market_data/stock_discovery.fetch_snapshot` | 一次 Nasdaq 公开 US-listed 下载请求 → 带板块/行业的原始表；无 key、无付费后备源 |
| 确定性筛选 | `stock_discovery.screen_snapshot` | 快照 + `config/stock-discovery.json` + 实际 portfolio/registry → 最多 6 个研究候选、淘汰计数、规则版本与证据时间字段 |
| 排除已有暴露 | `stock_discovery.excluded_exposure` | 活跃持仓及 registry 的 underlying / one_x_substitute / signal_symbol → 排除集合；读不到账本或活跃持仓元数据时拒绝推荐 |
| 简报装配 | `harness/brief_preflight.stock_discovery_node` | WAVE1 有界子进程 → 当代 context；失败是候选源降级，不使持仓判断失败 |
| 判断上下文 | `decision/packet._packet_payload` / `summary_view` | context → 同代 packet 与常驻 summary 的 `stock_discovery`（summary 把各候选相同的字段合并到 `candidate_shared`，packet 保留整行）；不进入持仓加仓授权表 |
| 用户出口 | `harness/brief_render.stock_discovery_section`、`brief_card._early_candidate_section` | `stock_discovery.candidate_lines` → 完整报告与主投/兜底卡；模型省略不能藏掉队列或源失败 |
| 研究交接 | `quote_request` → `fetch-peers`，随后 `entry-gate` | 独立报价核验 + 人工收集一手披露/商业模式/估值/否决项 → entry-gate artifact → 原有单票深研 |

默认规则读配置：最低规模与末价、末价乘成交量的流动性代理、有限的涨跌幅区间，
只接受可识别的普通股/存托凭证，排除基金、权证、优先股和收购壳。
每板块最多一票，板块内按流动性代理排序，再截取候选。这是研究注意力排序，
没有经过收益验证，不称为 alpha 或投资质量评分，也不等于行业热点判断。
参数是透明的初始筛选口径，可在配置中复核。

下载接口没有可靠行情时间，候选的 `observed_at` 为 null、`freshness` 为 unverified；
`retrieved_at` 仅表示抓取时间。即使源出现 `asOf` 原文也不自动认证它。
`snapshot_metrics` 只用于解释筛选，不能作为当前报价或突破证据。
先用每票的 `quote_request` 做独立报价核验：

```bash
clawock discover-stocks --json
printf '%s' '[{"ticker":"CANDIDATE","region":"us"}]' | clawock fetch-peers
```

把 CANDIDATE 换成实际候选。`analyze-us TICKER` 当前不会查询未持仓单票；不要靠往
portfolio 添加假持仓来绕过。报价之外，entry-gate 的人工证据检查仍须完成；本功能
不生成伪造的 gate artifact，不自动注册标的或写入 peer-map/portfolio。

`unavailable`（源/配置/账本失败）与 `no_candidates`（有效快照筛后为空）分开，
不使用上次候选掩盖失败。子进程总预算为 25 秒，请求有 connect/read timeout；
候选数量、源行数和响应字节都有验证上限。无需增加调度：复用每日简报。
关闭 `config/stock-discovery.json` 的 `enabled` 即停抓；外部 workspace 没配置则不抓。

目前只有美国上市股票启用自动发现；港股入口返回明确的授权缺口回执（见下节）。初始排序偏向大型高流动性公司，
不保证发现小盘或早期主题。板块多样化不代表组合暴露完全分散，ETF 穿透仍须研究。
analyst 目标价和评级没有可靠源，明确缺失。没有增加 LLM 调用或付费额度；
完整估值、催化确认和可执行切换仍交给既有研究与决策契约。

## 研究收件箱

发现与研究状态分开：`discover-stocks --json` 保持只读，默认 `--market all`，
返回 US 发现结果和 HK 可用性；`--market US|HK` 可单独检查。
简报 preflight 调 `research-inbox collect`，在网络请求结束后将候选
按 `market:ticker` 归并到本机 `.cache/research-inbox.json`。
该文件与锁文件被 Git 忽略；备份或迁移工作区时需另外保留，不能把它当可丢弃的行情缓存。

```bash
clawock research-inbox list
clawock research-inbox list --highlights --limit 12
clawock research-inbox set AAPL --market US --status researching --reason '核验最新披露'
clawock research-inbox set AAPL --market US --status deferred --reason '等财报' --review-on 2026-12-01
```

状态为 pending（待看）、researching（研究中）、deferred（暂缓）、rejected（已否决）。
每次变更必须有理由；暂缓必须有复查日期，其他状态也可安排复查。
重新发现只更新名字、行业及最近发现日期，绝不覆盖人工状态、理由和日期。
同一天重跑仍显示当日新候选；后续只突出到期复查项，不反复展示整个旧队列。
过去发现、当前已不在快照中的到期项仍会显示最近发现日期，不能冒充新报价。

列表提供已有 entry-gate 的相对路径及现有验证器的结论；与已获取的公开 origin/master 内容一致时，另提供固定 commit 的 GitHub 链接。本机尚未发布或已修改的产物只显示本机路径。
核验通过不改变队列状态，也不产生交易授权。
`list` 默认最多 50 项，`--limit` 可设至 2000；
简报最多 6 项、投递卡最多 3 项，截断时提示查看队列。
达到 2000 项、损坏文件或写入失败会显式降级，保持原文件，仍展示本次候选。
写入使用文件锁内重读与原子替换；源失败仍保留到期项，无后台调度或额外模型调用。

## 港股可行性与当前边界

`discover-stocks --market HK --json` 返回
`status=unavailable` / `reason_code=redistribution_permission_missing`，不请求供应商，
也不产生港股候选。默认组合结果与简报明确显示这一缺口，不把它表示成筛选后为空。

字段可达不等于允许公开使用。东方财富 clist 可提供代码、行业、成交额、市值和时间字段；
其[法律声明](https://about.eastmoney.com/home/legal)第八、十节限制未经许可的复制、传播与行情再分发。
HKEX 证券名录可作证券身份来源，但其
[使用条款](https://www.hkex.com.hk/Global/Exchange/Terms-of-Use?sc_lang=en)
第 5 节限制程序化获取、衍生数据库和再分发。
目前没有已核验的适用于此用途的授权，故这两路均未加入自动采集或公开产物。
代码回执只记录字段类别与授权缺口，不保存供应商原始行情或证券名录。

后续启用需要同时满足：允许自动获取及公开再分发的源、普通股身份与行业覆盖、
可靠观察时间和场次验证。之后才能复用持仓/底层排除、板块限额、候选 schema 和 entry-gate。
不能仅凭 HTTP 200 或用户希望启用就宣称这些条件成立。

## 参考实现：可以借什么

以下结论对应固定源版本；分析能力与候选发现分开核对，不能从 README 的市场
覆盖推断所有筛选策略都支持那些市场。只参考设计，没有移植第三方代码。

| 项目 | 核验到的机制 | 对 clawock 的启发 |
|---|---|---|
| daily_stock_analysis | `screening.pipeline.screen`：全市场快照 → 快照硬过滤 → 按需日 K 特征/再次硬过滤 → 因子短名单 → 可选 LLM 重排 → 风险/组合约束与评分 → 入选证据增强/单票深研。策略 YAML 声明市场、过滤、因子权重、追涨风险及同主题上限。API 支持同步与后台任务，结果入库，保留策略版本/实际权重和过滤解释。 | 先有股票池，确定性筛选后才花模型/新闻预算；证据时点、缺项、规则版本是产物的一部分。 |
| daily_stock_analysis 的数据边界 | 中国快照默认无 token 从 Sina 起，另有 Efinance/AkShare/东财、可配置 Tushare；日线复用 DataFetcherManager。美国股票池按 Wikipedia S&P 500 → 环境配置 → 内置大型股降级，yfinance 拉快照/日线。pipeline 实际接受 cn/us；抽查的趋势质量/放量突破 YAML 只声明 cn。热点独立走板块榜单/成分股，再按需新闻增强；有配置模型才 LLM 重排，否则规则排序。 | 免费市场股票池可以独立于持仓；不能把持仓同业或备选大盘股池叫作全市场，也不能把基本面多市场分析等同于港股筛选已实现。Tushare 或商业模型的付费权限不作为本功能依赖。 |
| TradingAgents | `TradingAgentsGraph.propagate(company_name, trade_date, …)` 从给定标的/日期出发，分析师并行产出基本面/情绪/新闻/技术报告，再多空辩论、交易/风险判定、记录与结算。 | 适合候选生成之后的评估，入口本身不能补我们的跨市场股票池；多 agent 并不自动意味着自动发现新股票。 |
| FinRobot Desktop | `screen_peers(payload, target_ticker, …)` 以目标公司为锚，按同 FMP 行业 → stock_peers → 同板块分层，再用规模/盈利/证券身份筛选与发行人去重；同业足够时不补跨行业同板块票。 | 确定性筛选、发行人/证券身份排除值得学，但这仍是估值可比公司集合，不能当持仓外主题发现。FMP 全量数据权限没有在免费约束下验证，不接入这一路。 |

来源：

- daily_stock_analysis 固定版本 `ce364e457aab288863a5707e7b3df79786ad07f2`：
  [pipeline](https://github.com/ZhuLinsen/daily_stock_analysis/blob/ce364e457aab288863a5707e7b3df79786ad07f2/src/services/screening/pipeline.py)、
  [筛选文档与 API/缓存/证据流程](https://github.com/ZhuLinsen/daily_stock_analysis/blob/ce364e457aab288863a5707e7b3df79786ad07f2/docs/screening-engine.md)、
  [美国股票池和数据源](https://github.com/ZhuLinsen/daily_stock_analysis/blob/ce364e457aab288863a5707e7b3df79786ad07f2/src/services/screening/snapshot_us.py)、
  [趋势质量条件](https://github.com/ZhuLinsen/daily_stock_analysis/blob/ce364e457aab288863a5707e7b3df79786ad07f2/src/services/screening/strategies/momentum_quality.yaml)、
  [放量突破条件](https://github.com/ZhuLinsen/daily_stock_analysis/blob/ce364e457aab288863a5707e7b3df79786ad07f2/src/services/screening/strategies/volume_breakout.yaml)。
- TradingAgents 固定版本 `1394a3f72aa4393e1a98f51b382434c4b4c2d972`：
  [运行入口](https://github.com/TauricResearch/TradingAgents/blob/1394a3f72aa4393e1a98f51b382434c4b4c2d972/tradingagents/graph/trading_graph.py)。
- FinRobot 固定版本 `2717499b8e30f242640af08c4ad9afd1113c2d45`：
  [同业筛选](https://github.com/AI4Finance-Foundation/FinRobot/blob/2717499b8e30f242640af08c4ad9afd1113c2d45/finrobot_desktop/finrobot/engine/compute/operators/peer_screen.py)。
- 本功能的免费数据接口：[Nasdaq screener](https://api.nasdaq.com/api/screener/stocks?download=true)。

## From discovery to a priceable proposal

Brief preflight reads the latest `memory/entry-gates/*.json` artifact per ticker,
revalidates it, and attaches its receipt to archived-bar candidates. A valid
`pass_to_deep_research` no older than seven calendar days changes the packet's
`entry_gate_required` to `entry_gate_cleared`. A later rejection, malformed
artifact, unresolved check, future date or stale assessment cannot revive an
older pass. A model's separate `research_judgment` cannot clear this prerequisite.
This clears research for a proposal; it does not place a trade or waive cash,
board-lot, hypothesis, invalidation or risk review.

The packet joins existing sentiment, information-event, factor and peer evidence
for unheld candidates. Entry-gate mechanism/key variables carry researched
supply-chain reasoning; inferred links must not be described as verified supply
relationships. Absent coverage is visible rather than counted as neutral data.
Use `decision_packet_query --ticker <candidate>` for the full unheld row.

Discovery candidates without a recent usable `memory/bars` archive are explicitly
`proposal_availability.status=unavailable`: the existing evaluator cannot price
them. Discovery snapshot prices never substitute for settlement OHLC. This
version does not auto-register or backfill newly discovered securities. Once an
instrument has a reviewed registry mapping, `clawock daily-bars --ticker SYMBOL`
archives its canonical bars; reassess its entry gate and regenerate preflight.
