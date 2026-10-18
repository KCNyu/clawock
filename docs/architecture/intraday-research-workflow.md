# Intraday research workflow / 盘中研究工作流

This is a read-only research lane, not a new live strategy. The live composition,
SPCH policy, order ledger and trading permissions are unchanged. The card is a
harness-owned historical evidence block, never a realtime order recommendation.

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
Same-bar ambiguity is stop-first; adverse gaps pay the opening price. A completed
session ending at 16:00 is required; early closes and gaps remain refusals.

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
claim of superior observed performance. There are no real-data net results while
the documented entitlement blocker remains unresolved.

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
prospective shadow experiment and any live action remain unstarted; a historical
model rerun does not substitute for a frozen future observation period.

## 已完成与外部缺口

- 已实现三种 research 服务、严格 manifest、模型回执绑定、净 walk-forward、
  基准与压力场景、成交/现金约束、盘中研究卡及双语入口说明。
- 实际分钟接口已探测：Massive 成功，Yahoo 429，Dukascopy 403。Massive
  [行情条款 §5](https://massive.com/legal/market-data-terms-of-service) 对非展示研究、
  衍生投资策略及分发另需许可；现有账户未提供该项授权证据。禁止把 HTTP 200
  当许可证。LEAN 的代码 Apache 许可也不能自动替代交易所行情许可。
- 没有用受限数据计算或发布净收益；没有把合成测试称作实证。较长数据仍为权限阻断；已取得的免费短样本以
  `insufficient_or_failed` 显示（见下节），数值未知，而不是零收益。真实净 walk-forward、完整模型
  比较和前瞻观察仍依赖合法历史数据及未来场次。账户实际月度额度和额外费率也
  尚缺证据。不购买数据、不新增付费订阅、不改变 live/SPCH。

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

The shipped status and intraday card use this real sample's provenance and
refusal, superseding the earlier all-sources-unavailable status. The longer
Massive history still has unresolved non-display/derived-research rights. No
fee-adjusted historical return is asserted from the short adjusted sample.
