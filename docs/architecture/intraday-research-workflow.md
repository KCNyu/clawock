# Intraday research workflow / 盘中研究工作流

This is a read-only research lane, not a new live strategy. The live composition,
SPCH policy, order ledger and execution permissions are unchanged. The historical
card remains a harness-owned evidence block. An independent advisory layer below can now produce conditional orders for manual confirmation.

## Implemented contracts

The research composition mounts three independently replaceable services:

| Service | Completed-bar mechanism | Failure case |
|---|---|---|
| `intraday_reversion` | Prior-window mean plus standard deviations; sell base, buy back at frozen mean | Persistent upward trend |
| `intraday_vwap` | Session-to-date OHLC4 weighted by volume; weighted dispersion, excluding signal bar | Event trend; volume is not executable depth |
| `intraday_breakout` | Close below prior-window Donchian low; target one prior channel width below signal close | False breakdown, gap through stop |

All use `replay(packet)` and `configured(params)`; the explicit research-kernel
facade is `decision.intraday_reversion.replay_service`. Implementations live in
`strategies/plugins/`; no facade computes a signal. VWAP and breakout are
independent implementations of the indicators reviewed in
[the source research](../research/intraday-strategies.md). OHLC4 session
accumulation, volume-weighted dispersion and the downside inventory sleeve are
explicit adaptations, not claims that the upstream authors validated this strategy.
Breakout only uses `window`; `deviations` is accepted for the shared bounded
contract but does not tune its channel. No fresh long position or short sale.

`execution` optionally adds `delay_bars` (0..3), `participation` (at most .01),
and `cash_reserve` in the market currency to the existing replay packet. Study
runs always supply it and require nonnegative volume on every bar. Entry size
is checked against the preceding completed bar's volume; realised entry/exit
volume checks test fill feasibility. Failed fills or cash-short buybacks produce
`unresolved` and null net performance, not a deleted losing trade. Costs come
from `costs.fill`, including both sides, tax, rounding and half-spread. This is
still an OHLC simulator: no queue priority, tick path or calibrated impact.
Breakout entries must still be below the prior channel and above the frozen
target at the execution open; a gap invalidating either condition cancels entry.
Same-bar ambiguity is stop-first; adverse gaps pay the opening price. A completed
session ending at 16:00 is required; early closes and gaps remain refusals.

## The reversion kernel: packet and configuration

`intraday-reversion` is mounted in `plugins`, not `live`. It provides a replay of
one complete five-minute session with no orders, positions, live plan, delivery
or strategy-registration side effect. The implementation is
`strategies/plugins/intraday_reversion.py` (`inject=('costs',)`, `apply` exposes
`intraday_reversion.replay(packet)`); `decision/intraday_reversion.py` is a
forwarding facade, and the caller passes the research kernel explicitly. Do not
call `facade.install` here: the module facade binds the live kernel. Replacing
the row makes the facade follow the mounted service; unloading the row makes the
call fail instead of falling back to a hard-coded implementation.

```bash
clawock strategy-lab list
clawock strategy-lab intraday-replay /path/to/session.json
```

The packet requires `market` (`hk`/`us`), `ticker`, `session` (local
`YYYY-MM-DD`), `research_allowed: true`, `forbid_reduce_advice: false`, `shares`,
`base_shares`, `lot_size` (positive integers) and `bars` from the session's first
to last completed five-minute bar. Each bar has a timezone-aware `end` and
unadjusted OHLC; the caller supplies a real trading day and its source, and the
replay does not authenticate a market-data vendor. A US session needs 78 bars,
an HK session 66; the first bar ends 09:35 and the last 16:00, with the HK
12:00→13:05 lunch break the only non-five-minute gap. Duplicate, out-of-order,
missing or cross-session bars, non-finite or boolean prices and bad OHLC are
refused. Early closes and halts are refused rather than passed off as a complete
session.

| Config key | Default | Meaning |
|---|---:|---|
| `window` | 20 | prior completed closes, excluding the signal bar |
| `deviations` | 2.0 | standard deviations above the mean before a sell is studied |
| `cost_multiple` | 2.0 | expected reversion spread must exceed both legs' cost by this factor; at least 1 |
| `min_net_bps` | 10.0 | net bps over the sell notional after both legs' costs |
| `max_base_fraction` | 0.1 | roundtrip shares as a fraction of the base position; a research safety default |

At most one roundtrip per ticker per session. A completed signal bar only
proposes: the next bar's open must still be above the frozen mean and clear the
net-cost threshold before a sell is simulated, so the replay does not pretend to
fill at the prior close. Stop = sell price + (sell price − frozen mean). An
adverse opening gap buys back at the open; if one bar touches both stop and
target, the stop wins; a target gap gets the frozen target, not a better price.
The same share count is bought back; an untouched last bar buys back at the
close. Both fills include half-spread and fees, so they are simulated, not
guaranteed executable. `execution` now covers cash, buying power and volume;
circuit breakers and book queue position remain unproven by OHLC. This is not a
risk-free way to lower a position's cost.

Output `status` is `refused`, `no_trade` or `replayed`, always with
`live_permission: false`, the parameters, input SHA256, full cost model and
`evidence_grade: conditional_replay_not_walk_forward`. A trade carries the signal
time, fill bar, target/stop, exit reason, both legs' costs, `net_pnl` and expected
net bps at activation. `net_pnl` is the cash increment from the roundtrip versus
keeping the same base, not the account's or base's return; its currency follows
the market and is never added across markets. No trade is not evidence of zero
risk, and every refused or empty attempt stays in the denominator. The JSON goes
to stdout and writes no daily strategy ledger.

Costs go through the one `costs.trade_cost` owner with direction, ticker and
shares: minimum commission, taxes, exemptions and spread settle per leg. The rank
portfolio has no size, so it uses the config's explicit reference principal and
reference price on the larger side; that is a coarse threshold, not evidence of
day-trading. `method_evaluation` charges every call and averages by episode;
`shadow` maps the instance's market/currency to the tariff and passes the actual
simulated direction and shares, leaving uncovered currencies unavailable rather
than free. `method_trials` freezes the whole dataclass, so an old trial keeps the
old fee model and does not inherit today's waiver or tax table.

## SPCH conflict and open decisions

`infinite_ammo_dca.forbid_reduce_advice` is unchanged. A missing policy value or
`true` makes this replay refuse too; an LLM explanation cannot replace the
authorization. The packet's `research_allowed` only scopes offline research and
does not establish account permission from arbitrary JSON. There is no live
action consumer today, only the historical research card.

A workable future would require kcn to whitelist individual tickers, exclude
every `forbid_reduce_advice` strategy by default, and then bound an authorized
ticker by roundtrip fraction, daily count, cash and lot size. A 10% base and one
roundtrip per day are a research starting point; a daily net-loss stop and the
final thresholds need out-of-sample evidence. SPCH is not an exception unless
kcn separately changes its policy. Four decisions remain open: the real ticker
whitelist, five-minute versus shorter bars, US-first versus HK/US together, and
the LLM's role in live. The research implementation and cost corrections can
proceed without them; every action needing approval is unimplemented.

## Frozen model proposal and walk-forward

`config/intraday-research-manifest.json` is the bounded Astra-authored research
proposal. Its timestamp denotes a **retrospective** preregistration before
outcome computation, not a historical prediction. It fixes the universe,
calendar range, candidate parameters, train/test sizes, account scenario,
mechanism, counterexamples, evidence requirements and presentation emphasis.
Unknown keys, live authority, oversized grids and weakened sample gates fail.
The default candidate is first and fixed, so the fixed-band comparison cannot
quietly change. A study covers one ticker/currency; it cannot combine USD/HKD
performance or claim that an independently simulated ticker has a separate
commission waiver.

Use an existing entitlement, not a new subscription:

```bash
# grant.json must cite actual account permission for non-display research.
# API access alone does not establish that permission. Keep credentials/grants private.
PYTHONPATH=src python3 ops/research/fetch_intraday.py config/intraday-research-manifest.json \
  --grant /private/grant.json --output /private/spy.json
clawock strategy-lab intraday-study config/intraday-research-manifest.json \
  /private/spy.json --requests-only --output /private/training-requests.json
# Give ONLY the next request to the model; freeze its response. Repeat --requests-only
# with --selections responses.json to advance one fold at a time.
clawock strategy-lab intraday-study config/intraday-research-manifest.json \
  /private/spy.json --selections /private/responses.json --output /private/study.json
```

The grant requires `research_use:true`, `license_evidence` and an explicit
`derived_public_use` boolean. The acquisition adapter reads the existing
`POLYGON_API_KEY`, follows a bounded same-host pagination chain, refuses failed
responses, saves the raw payload hash, and normalizes unadjusted US five-minute
start stamps into timezone-aware end stamps. It does not buy or retry around
access denial. HK acquisition remains blocked pending a verified usable source.
Users with another licensed source may supply the same dataset envelope:
`source` (provider, URL, retrieval time, raw SHA256, license evidence, rights,
`synthetic:false`, `price_basis:unadjusted`, `interval_minutes:5`) plus `sessions`
containing the replay packets. Neither a user assertion nor a hash proves a
vendor license; provenance is an auditable input obligation.

The model response object is keyed by `test_first`. Each value has exactly:
`request_sha256`, `candidate` (-1 hold or a declared index), `author_model`,
`mechanism`, `counterexample`, and `focus` (validation/costs/path). Every response
binds to the exact preceding training receipt. Invalid and missing responses
remain in the report and prevent a complete LLM performance arm. No response is
invented as a successful hold. The CLI never calls a different model silently.
This interface supports the existing agent/tool workflow without another paid
LLM client. Request extraction exposes only the earliest unanswered fold: later training
windows would leak earlier test outcomes if supplied together. Freeze each answer
before advancing. The initial request extraction does not expose test outcomes; the
final report does, so do not feed it back to a model and call the rerun pristine.

The harness chooses the highest training net increment including hold, freezes
it for the next block, and repeats chronologically with 60 training sessions and
20 test sessions. Partial terminal blocks are disclosed. All expected trading
days stay in the denominator, including missing sessions. Benchmarks are retain
base, fixed band, a previous-session-direction regime rule and the separately
recorded model arm. Negative results remain negative. The selected schedule is
held fixed under doubled spread, one-bar delay, normal TAF and an assumed extra
2 bps per leg. No stress scenario is retuned using its test returns.

Reports contain full folds, curves, turnover, costs, net cash increment versus
retaining the same base, return on initial base plus cash reserve, and maximum
**session-close incremental** drawdown. These are not total-account returns,
dividend-adjusted buy-and-hold returns or intrabar maximum drawdowns. A five-day
circular block bootstrap uses a fixed seed and Bonferroni lower tails over all
reported non-hold arms; its bounded replication count is exploratory. Searching
other universes or rerunning after outcomes creates further selection bias not
removed by that interval. Positive retrospective evidence cannot grant live
permission. At least 60 OOS sessions, complete data and successful cost stresses
are required even for the `retrospective_candidate` label. Synthetic data always
receives `synthetic_test_only` regardless of apparent performance.

## Account-cost interpretation

The complete `config/cost-model.json` snapshot travels with each report. Zero
commission is conditional on the shared monthly HKD 500,000 allowance. Opening
usage is an explicit assumption, not an observed account fact; every roundtrip
consumes both notionals. US turnover conversion uses the manifest's disclosed
FX assumption. Exceeding the allowance invalidates full net metrics because the
excess tariff is unknown. Other real account trades are absent; even an
unexhausted simulated path cannot prove the actual allowance remained available.
The study uses the current dated tariff snapshot counterfactually, not an
invoice reconstruction. Normal TAF and extra-fee stresses expose some of that
uncertainty; platform fees, financing and actual impact remain unmeasured.

HK stocks retain stamp duty; only explicitly verified exemptions (currently
02800) omit it. Current CCASS has no old minimum. The much lower assumed US
spread and absence of stamp duty justify starting research with SPY, **not** a
claim of superior observed performance. The shipped receipt now contains real-data
net results under the owner-attested research authorization described below; the
cost assumptions remain conditional and do not reconstruct account invoices.

## Card and LLM contract

Preflight loads `memory/.tmp/intraday-research-latest.json` if explicitly written
by a study; otherwise it loads `config/intraday-research-status.json`. No live
composition row or scheduled optimizer is added. The research context is core,
classified mixed observation/policy, and included before `context_id` is hashed.
The same harness renders its card into `raw_wechat_block`, so postflight's normal
and data-only fallback paths retain the research label. Receipt corruption,
future generation timestamps or foreign authority states fail closed.

The block always identifies historical research, source, data end date,
retrieval/validation time, elapsed age and validation status. Age is not a fresh
quote stamp. Market mismatches show missing evidence. Without explicit derived
public-use permission, numerical market-derived results are withheld. With
permission, harness-owned net/cost/drawdown rows preserve losses, show the last
historical signal→simulated sell→buyback timeline, separate base and sleeve,
and draw net and cost bars on the same bps scale. Those quantities are historical
research sizes, never today's instructions. Full evidence stays in the receipt.

The model can choose an explanatory emphasis and reason about mechanisms,
regime, costs, refusals and uncertainty. It cannot replace numbers, remove the
research label, suppress negative results, send messages or override SPCH. A
prospective shadow experiment and automatic execution remain unstarted; a historical
model rerun does not substitute for a frozen future observation period.

## 已完成与外部缺口

- 已实现三种 research 服务、严格 manifest、模型回执绑定、净 walk-forward、
  基准与压力场景、成交/现金约束、盘中研究卡及双语入口说明。
- Massive/Polygon 已返回 `adjusted:false` 的完整历史，冻结窗口 138 场、每场
  78 根、缺失日期为空；60 场训练后有 78 场 OOS。适配器的 50000 上限按底层
  分钟条目计，不能由五分钟根数推断一次请求足够，实际须跟随分页。
- 本次 owner 明确允许账号数据研究和衍生结论公开，`license_evidence` 采用
  真实的 owner 授权陈述，非抓取的供应商许可证文件。没有独立核验账户档位或
  供应商/交易所许可；HTTP 200 只证明接口可用，不证明许可证。
  [行情条款 §5](https://massive.com/legal/market-data-terms-of-service) 的许可范围
  仍须按实际账户理解，本次不公开原始行情。
- 当前状态文件保存完整净 walk-forward、四个压力臂、四折模型回执与净结果，
  费用仍为原冻结情景。主臂和模型臂净值为负，历史候选判据未通过，状态仍为
  `insufficient_or_failed`，但指标不再为空。
  账户实际月度额度、发票和额外费率尚缺证据；前瞻观察未开始。
  不购买数据、不新增付费订阅、不改变 live/SPCH。

## Free sample audit / 免费样本核查

A further source is available: [FirstRate Data's free SPY sample](https://firstratedata.com/free-intraday-data).
Its [license](https://firstratedata.com/about/license) defines a subscriber as
any downloader and expressly permits statistical modeling and derived research,
with attribution. Raw CSVs remain private; no raw data is committed here.

```bash
PYTHONPATH=src python3 ops/research/fetch_free_sample.py --output /private/free-spy.json
clawock strategy-lab intraday-study config/intraday-research-manifest.json \
  /private/free-spy.json --output /private/free-spy-study.json
```

The adapter preserves `price_basis:split_adjusted`. The study therefore produces
an explicit ineligible-data receipt, empty performance metrics and zero evaluated
OOS sessions, not a silently rebased executable-price backtest. The actual ZIP
covers ten regular sessions, shorter than the frozen train-plus-test requirement.
The page's advertised dates differed from the ZIP; use the actual timestamps and
raw SHA256 in the receipt. Since the URL is rolling, a later download can change
its hash and range. Retain the private ZIP for exact input reproduction.

This short adjusted sample remains an ineligible-data audit, not the current
shipped status. The status and intraday card now use the longer unadjusted
Massive/Polygon receipt under the owner attestation above. The adjusted sample
was never used to assert fee-adjusted historical returns.

## Conditional recommendation layer / 独立条件推荐层

The research manifest and receipt keep `live_permission:false`, historical labels
and failed validation. `decision/intraday_recommendations.build` owns a separate
`intraday-recommendations/v1` contract: `advisory_only:true`,
`execution_permission:false`. `harness/intraday_recommendations` renders it after
the historical block in preflight, inside the same hashed context. Normal and
fallback delivery retain the block. No broker, order ledger, live strategy
composition, portfolio writer or SPCH policy is changed.

This is a disclosed exploratory recommendation, **not evidence of positive alpha**.
Negative net validation and absent forward samples do not alone block it. The
rule is fixed to the manifest's first band-reversion candidate, not the sole
positive stress arm. Recommendations are limited to the studied US ticker and
an actual held base; no new long or short position is proposed. The card displays
the base net increment, session-close drawdown and cost next to every suggestion,
plus OHLC execution limitations, conditional allowance/current tariff costs and
`prospective_status`. Both research hashes travel with every row; the additional
live-data hash binds the same-context provider URL, session and completed OHLCV.
The context also keeps the input bars, cost snapshot and real-book fingerprint.
Manifest contents must match their hash. The historical data hash identifies the
receipt's dataset; it does not independently verify a vendor or market-data license.

During the regular US session, fetch today's raw five-minute Polygon aggregates
using the existing key (one request, six-second timeout, no retry, purchase or
subscription change). Require an uninterrupted sequence from the session open,
a latest completed bar younger than five minutes and at least twenty preceding
completed bars. Ignore a forming bar. Signal when the last close exceeds the
preceding twenty closes' mean plus two population standard deviations. Sell-limit
is that close rounded upward to cents; buyback target is the frozen mean rounded
to cents; invalidation buyback is the sell-limit plus that same distance. Unfilled
advice expires at the next five-minute boundary. A changed book/plan or new bar
requires reassessment. Actual fills, rather than the card, determine buyback size.
The human must verify the quote is still above the band and below invalidation,
and reconcile outstanding orders; repeated cards never mean additional orders.
If filled, buy back at target, invalidation or before this session closes. Gaps and
failed fills can exceed the displayed stop loss; there is no automated monitoring.

Size is at most one whole share and at most one tenth of actual inventory, never
the manifest's assumed base. Require at most one percent of the last completed
bar's volume, gross target space greater than twice conditional roundtrip cost,
and at least ten conditional net basis points. Cost arithmetic delegates to
`costs.trade_cost`. Require book cash for the stop buyback deficit including fees.
The last ten minutes of the regular session accept no new recommendation.
These are explicit conservative advisory policy choices, not newly validated
parameters or a replay of the training-selected base arm. This full-session lane
conservatively refuses July 2/3, Christmas Eve and the Friday after Thanksgiving,
including some normal full sessions. Unscheduled exchange closures still require
the human session/order check; this is not an exchange-status feed.

Refuse absent/corrupt/foreign-market/rights-blocked/synthetic evidence, missing
hashes or base metrics, changed first-candidate formula, no real studied holding,
invalid shares, reduction prohibition, any existing open plan for that ticker,
closed or near-close session, missing key/denied source, invalid/gapped/stale bars,
insufficient history, no excursion, insufficient volume/cost space or buyback
cash. The ordinary intraday card remains deliverable after an optional-lane
failure. Only this layer may turn its explicit conditions into a recommendation;
the historical receipt and other candidate lanes acquire no execution authority.

研究块保留历史权限与失败结论；推荐块属于独立的探索性人工建议。历史净增量为负、
零前瞻样本不是阻塞项，但每条必须同屏披露。只覆盖研究标的和真实底仓，前二十根均值
加两倍标准差触发，以信号收盘价向上取整为卖出限价、冻结均价为买回目标、等距离上移
为失效买回位。有效期到下一五分钟边界；状态变化须重评，重复卡不是追加单。
最多一股且不超过真实底仓十分之一，现金、成交量及条件成本空间不足均不建议。
缺持仓、休市、延迟或缺失行情、策略禁减和已有未完成计划会明确显示不出建议。
这不是策略已被验证的声明，也不接券商、自动下单、改 live 组合或 SPCH。
