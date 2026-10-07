# 持仓外候选发现

clawock 的 `discover-stocks` 从免费美股全市场快照生成跨板块的**待研究候选**，
每日简报自动展示。候选不依赖持仓的 peer-map，不授权建仓、切换或加仓。

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
| 判断上下文 | `decision/packet._packet_payload` / `summary_view` | context → 同代 packet 与常驻 summary 的 `stock_discovery`；不进入持仓加仓授权表 |
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

目前只覆盖美国上市股票，港股跨板块发现尚缺；初始排序偏向大型高流动性公司，
不保证发现小盘或早期主题。板块多样化不代表组合暴露完全分散，ETF 穿透仍须研究。
analyst 目标价和评级没有可靠源，明确缺失。没有增加 LLM 调用或付费额度；
完整估值、催化确认和可执行切换仍交给既有研究与决策契约。

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
