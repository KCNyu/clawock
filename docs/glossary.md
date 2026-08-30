# Clawock Glossary

> Source of truth for cross-document terminology. When README, code
> comments, briefs or PR descriptions first introduce one of these terms,
> link to its entry here rather than re-translating. EN/ZH parity is
> enforced at this file by `tests/test_glossary_parity.py`, not at the
> translation site.

Each entry has four fields:

- **EN** — canonical English term (lowercase; title case only for proper
  nouns like author names)
- **中文** — canonical Chinese rendering (one rendering per term;
  translators do not choose)
- **一句话** — one-sentence definition a new reader can act on without
  reading the source
- **First defined** — file or doc where the term was first named in this
  repository

## Methodology — factors and signals

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| composite factor | 复合因子 | Weighted average of sector-neutral ranks; weights must sum to 1 and equal `RAW_FACTORS` (adding a component is a re-registration, not a code change). | `market_data/factors.py::RAW_FACTORS` |
| composite score | 综合得分 | The numeric output of the composite factor for one name on one session; the rank the rest of the decision chain sorts by. | `evaluation/signal_panel.py` |
| composite polarity | 复合因子极性 | Diagnostic table showing each component's declared sign vs measured IC sign; classified as `polarity_suspect` (one component is wrong) or `regime` (many components are wrong together). | PR #1198 |
| polarity suspect | 极性可疑 | A single component carries almost all the negative IC — verdict that the factor is broken, not the regime. | PR #1198 |
| regime | 行情状态 | What this stretch of the market rewards (risk-on / risk-off / trend / mean-revert / high-vol / low-vol), **not** whether the market is up or down. | `decision/regime.py` |
| sector-neutral rank | 行业中性排名 | Rank within each sector first, then merge across sectors — prevents industry β from contaminating cross-sectional scores. | `market_data/factors.py` |
| IC (Information Coefficient) | 信息系数 | Spearman rank correlation between today's ordering and `h`-session-ahead returns. ~0.05 industry-floor, 0.10 good, 0.15+ top-tier. | `evaluation/signal_panel.py` |
| mean IC | 平均 IC | Average IC across recent sessions; one number, masks more than it reveals. | `evaluation/signal_panel.py` |
| forward return | 远期收益 | Return from today to `h` sessions later — `h ∈ {t1, t5, t20}` for the daily bars. | `evaluation/signal_panel.py` |
| triple barrier | 三重屏障 | López de Prado labeling: upper (take-profit), lower (trailing stop), time cap. First touched wins. | `labeling/triple_barrier.py` |
| chandelier stop | 吊灯止损 | Trailing stop at `N`-day high minus `K × ATR`; the lower barrier of the triple-barrier scheme. | `labeling/triple_barrier.py` |
| fixed-horizon | 固定期 | Label that closes a position only at `h`-session close — the **old** panel column, used as a comparator. | `evaluation/signal_panel.py` |
| path-aware | 路径感知 | Label that exits when the trailing stop is hit intraday — the **new** panel column. | `labeling/triple_barrier.py` |
| ambiguous bar | 模糊 K 线 | A bar where both upper and lower barriers were touched in the same period; verdict is the unfavorable one. | `labeling/triple_barrier.py` |
| circular against barrier | 对屏障循环 | A signal whose measured IC is mostly restating the barrier rule itself (e.g. `stop_distance_pct`); flagged `CIRCULAR_AGAINST_BARRIER`. | `evaluation/signal_panel.py` |
| quantile structure | 分位结构 | Per-session split into three buckets (not five — too few names), then per-bucket forward return averaged across sessions. Splits into `top − middle` and `middle − bottom` to identify selection-list vs avoidance-list vs two-sided signals. | `evaluation/signal_panel.py` |
| persistence | 持久性 | Turnover (`1 − Jaccard(top bucket)` between adjacent sessions) + rank autocorrelation of the signal. | `evaluation/signal_panel.py` |
| turnover | 换手率 | Fraction of the top bucket that differs between two adjacent registration sessions. | `evaluation/signal_panel.py` |

## Methodology — validation

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| deflated Sharpe (DSR) | 打折夏普 | Sharpe minus the expected maximum across `n` trials, divided by skew-/kurtosis-corrected standard error. Returns `insufficient_sample` when the underlying sample is too small. | `evaluation/deflated_sharpe.py` |
| CSCV (Combinatorially Symmetric CV) | 组合对称交叉验证 | Split the time series into `S` groups, run every `C(S, S/2)` half-half split, observe how often the in-sample winner wins out-of-sample. | `evaluation/cscv.py` |
| purged CSCV | purged CSCV | CSCV with a gap between train and test to prevent information leakage. | `evaluation/cscv.py` |
| PBO (Probability of Backtest Overfitting) | 回测过拟合概率 | The probability that an in-sample winning strategy loses out-of-sample; 0.5 = random, 1.0 = 100% overfit. | `evaluation/cscv.py` |
| block bootstrap | 块自举 | Bootstrap that draws contiguous blocks instead of single rows — necessary when adjacent sessions share a regime. Politis–Romano stationary variant with geometric block length and wrap-around. | `evaluation/bootstrap.py` |
| BCa interval | BCa 区间 | Bias-corrected and accelerated confidence interval; uses jackknife to correct both bias and skew. Below `MIN_CLUSTERS_FOR_BCA` the engine falls back to percentile. | `evaluation/bootstrap.py` |
| selection rigor | 选 variant 严格度 | The combined DSR + PBO + purged CSCV gate; refuses to print a number when any gate says `insufficient_sample` or `insufficient_search`. | `evaluation/add_alpha_walkforward.py` |
| insufficient sample | 样本不足 | A diagnostic verdict: the data is too small for the measurement to mean anything; published as a string, not as a number. | `evaluation/unified.py` |
| insufficient search | 搜索不足 | A diagnostic verdict: too few variants were tried for the search to be informative. | `evaluation/deflated_sharpe.py` |
| grade | 评级 | Unified verdict from six gates (cscv / DSR / bootstrap / attribution / drift / …); a refused gate pulls the grade down on purpose. The grade `validated` is **structurally unreachable** — that label belongs to rules written before data arrives. | `evaluation/unified.py` |
| validated | 已验证 | Reserved for rules pre-registered before data arrives. Computed grades never return this. | `evaluation/unified.py` |
| diagnostic | 诊断性 | The highest grade a computed evaluation can reach; a working measurement, not a passed gate. | `evaluation/unified.py` |
| reachability | 可达性 | Whether a cohort's two conditions can ever both be true on this book — measured across the **whole** ledger, not the 30-day window. | `decision/ledger.py` |
| unreachable cohort | 不可达 cohort | A cohort whose two conditions have empty intersection on the whole ledger — `warming_up` was the lie, this is the truth. | PR #1198 |

## Methodology — liquidity and volatility

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| Amihud illiquidity | Amihud 非流动性 | Absolute return divided by volume as a proxy for the price impact per dollar traded. | `market_data/bar_signals.py` |
| Roll spread | Roll 点差 | Implicit bid-ask spread estimated from the covariance of adjacent price changes; valid only when that covariance is negative. | `market_data/bar_signals.py` |
| Corwin–Schultz spread | Corwin–Schultz 点差 | Bid-ask spread inferred from intraday high–low ratios; rejects negative estimates from gap days. | `market_data/bar_signals.py` |
| EWMA volatility | EWMA 波动率 | Exponentially weighted moving average with RiskMetrics λ = 0.94. | `market_data/bar_signals.py` |
| GARCH(1,1) | GARCH(1,1) | Variance-targeting GARCH with refined grid; refuses below 200 observations. | `market_data/bar_signals.py` |
| realised volatility | 已实现波动率 | Standard deviation of recent log returns. | `market_data/bar_signals.py` |
| realised skew / kurtosis | 已实现偏度/峰度 | Higher moments of the return distribution; reported alongside vol-of-vol. | `market_data/bar_signals.py` |
| vol of vol | 波动率的波动 | Variance of recent volatility estimates — a regime indicator, not a return predictor. | `market_data/bar_signals.py` |

## Methodology — portfolio and risk

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| Ledoit–Wolf shrinkage | Ledoit-Wolf 收缩 | Shrink the sample covariance toward a constant-correlation target; the sample-covariance cure for small samples. | `portfolio/covariance.py` |
| OAS (Oracle Approximating Shrinkage) | OAS 收缩 | A smarter shrinkage target than Ledoit–Wolf; guesses the optimal shrinkage intensity. | `portfolio/covariance.py` |
| Marchenko–Pastur spectrum | Marchenko-Pastur 谱 | Theoretical distribution of eigenvalues of a pure-noise covariance matrix; eigenvalues outside the boundary are "real signal". | `portfolio/covariance.py` |
| shrinkage intensity | 收缩强度 | How far to pull the sample estimate toward the target; 0 = no shrinkage, 1 = full target. | `portfolio/covariance.py` |
| effective bets | 有效持仓数 | How many independent sources of variance the portfolio actually carries; close to 1 = all in one, close to N = well diversified. | `portfolio/covariance.py` |
| HRP (Hierarchical Risk Parity) | 层次风险平价 | López de Prado 2016: hierarchical clustering + recursive bisection. Used as a **yardstick**, not as a recommendation. | `portfolio/allocation.py` |
| Euler risk contribution | Euler 风险贡献 | Each holding's marginal contribution to total portfolio volatility; sums exactly to the total. | `portfolio/allocation.py` |
| minimum-variance portfolio | 最小方差组合 | The portfolio that minimises variance subject to weights summing to 1; here solved by simplex gradient descent because the sample covariance is singular. | `portfolio/allocation.py` |
| historical stress | 历史压力 | Worst observed `k`-session window with dates attached. | `portfolio/stress.py` |
| reverse stress | 反向压力 | Given a target loss, the most plausible (lowest Mahalanobis distance) scenario that produces it — not "everything falls equally". | `portfolio/stress.py` |
| Mahalanobis distance | 马氏距离 | Distance that accounts for correlations; the reverse-stress search criterion. | `portfolio/stress.py` |

## Methodology — attribution

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| Fama–MacBeth regression | Fama-MacBeth 回归 | Per-session cross-sectional regression of forward return on factor loadings, then average coefficients across sessions. Requires ≥3 names per factor; refuses to print below that. | `evaluation/attribution.py` |
| `FACTOR_BLOCKS` | 因子块降维 | Pre-defined grouping of factors into blocks (momentum / stability / quality_liquidity) — a dimensionality reduction, not a search; no other grouping was tried. | `evaluation/attribution.py` |
| factor return | 因子收益 | The mean forward return that a unit exposure to one factor earns across sessions. | `evaluation/attribution.py` |
| `explain_composite` | 复合归因 | Closed-form decomposition of composite score into per-factor contributions: `w_f × rank_f / Σw`. Reconstructs the composite to the sixth decimal in tests. | `evaluation/attribution.py` |
| leave-one-out | 留一法 | Removing one factor from **every name's** composite and re-ranking; answers "would this name's position change if this factor disappeared?". | `evaluation/attribution.py` |
| tilt / timing | 倾斜 / 时机 | Decomposition of common-factor return into a static tilt (allocation) component and a timing (weight-change) component; `tilt + timing ≡ common` by construction. | `evaluation/attribution.py` |
| mean R² | 平均 R² | Average cross-sectional R² of the Fama–MacBeth regressions; how much of the return is explained by the factors. | `evaluation/attribution.py` |
| specific return | 特异性收益 | The residual after subtracting common factor returns; in this book, two-thirds of equal-weight returns. | `evaluation/attribution.py` |

## Decisions and actions

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| decision ledger | 决策账本 | The append-only log of every decision the model produced; ground truth for backtests and provenance. | `decision/ledger.py` |
| tactical entry | 战术入场 | An entry decision with a setup and timing; **structurally rare** — all 7 historical instances pre-date the v1 packet. | `decision/ledger.py` |
| cut | 出场信号 | Decision to exit the position; printed on the scorecard and published in the daily brief. | `decision/actions.py` |
| hold and watch | 持有观望 | Decision to keep the position without sizing up; not the same as "add". | `decision/actions.py` |
| add | 加仓 | Adding to an existing position; rare in this book — see `tactical entry`. | `decision/actions.py` |
| shadow portfolio | 影子组合 | A parallel book that follows signals without placing orders; used to estimate the cost of execution delay. | `decision/shadow.py` |
| shadow book | 影子账本 | The ledger of the shadow portfolio; lives next to the live book in `memory/`. | `decision/shadow.py` |
| mind record | 决策记录 | The structured record of one decision — action, condition, regime, size, confidence, evidence. | `decision/mind_record.py` |
| information packet | 信息包 | Bundle of evidence that turns "warming up" into "active"; carries `activation_progress` for the second gate. | `decision/packet.py` |
| packet carrying population | 带 packet 群体 | The real-world population of decisions that came with an information packet; published separately from the unreachable cohort. | PR #1198 |
| warming up | 预热中 | Old, dishonest status that pretended a cohort was still filling up; replaced by `unreachable_cohort` and `reachability` in PR #1198. | PR #1198 |
| activation progress | 激活进度 | `history_dates` tuple on the packet recording how many sessions have passed for each activation gate. | PR #1198 |

## Risk and portfolio

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| leverage dial | 杠杆刻度 | 200-day trend × volatility dial that caps the leveraged-ETF sleeve (×1 / ×0.5 / ×0); a risk-budget control, not a timing signal. | `decision/regime.py` |
| risk budget | 风险预算 | The notional ceiling a sleeve is allowed to risk; published per market per policy. | `README.md` |
| exposure | 敞口 | Dollar or percent-of-book weight of a holding or sleeve; gross or net depending on context. | `portfolio/risk.py` |
| HHI | 赫芬达尔指数 | Concentration measure (Herfindahl–Hirschman Index): `Σ wᵢ²`; higher = more concentrated; gate renders four bands (green / yellow / orange / red) — only band names are pinned to thresholds; the visual indicator is decided by the dashboard CSS. | `portfolio/risk.py` |
| covariance | 协方差 | Second moment of joint returns; the matrix this engine shrinks via Ledoit–Wolf or OAS before any allocation uses it. | `portfolio/covariance.py` |
| correlation | 相关性 | Covariance rescaled by the product of volatilities; bounded in [-1, +1]; SPCH/SPCX observed at 1.000 in this book. | `portfolio/covariance.py` |
| conditional number | 条件数 | Ratio of largest to smallest eigenvalue; 13,241 on this book — the covariance is nearly singular. | `portfolio/covariance.py` |
| stress test | 压力测试 | A scenario projected onto the book's covariance to estimate loss; here transmits through correlations, not "everything falls equally". | `portfolio/stress.py` |

## Workspace and book

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| workspace | 工作区 | Where the book lives on disk; resolved by `workspace_root` for any command. | `workspace.py` |
| engine config | 引擎配置 | A config file that ships with the **engine** rather than with a particular book. | `workspace.py` |
| book | 账本 | One brokerage account + its instrument registry + decision ledger + portfolio snapshot. | `workspace.py` |
| look-through | 透传归因 | Resolving a holding to the issuer whose news, filings and earnings move it (a leveraged ETF to its underlying index). | `instruments.py` |

## Sessions and calendar

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| session | 交易日时段 | One trading day for one market; the atomic unit this engine indexes by. | `sessions.py` |
| trading day | 交易日 | A day on which the market is open for trading. | `sessions.py` |
| trading session | 交易时段 | A resolved trading window (HK afternoon, US pre/regular/post); narrower than `session`. | `sessions.py` |
| in session | 交易中 | Calendar day **and** clock both confirm the market is open. | `sessions.py` |
| closed reason | 休市原因 | Short Chinese label (`休市`, `午休`, `节假日`) for harness banners. | `sessions.py` |
| phase session | 时段映射 | The calendar session a harness phase belongs to — HK afternoon = `pm/close`. | `sessions.py` |
| canonical bar | 规范 K 线 | The single resolved bar a session should publish; defined per-market by the canonical raw-bar writer. | `instruments.py` |

## Reproducibility and provenance

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| run card | 运行卡 | A snapshot of one run: seeds, library versions, config files, inputs, wall time, peak RSS, and a `metrics_digest`. | `evidence/run_card.py` |
| reproduction key | 复现键 | The hash that two runs with identical inputs and code must produce. Library versions are in; interpreter patch and platform are out. | `seeds.py`, `evidence/run_card.py` |
| metrics digest | 度量摘要 | The hash of the produced metrics; matches the `reproduction_key` iff the run is fully explained. | `evidence/run_card.py` |
| `unexplained` | 未解释 | Run state when the key matches but the digest does not — meaning the card still does not describe everything that determined the result. | `evidence/run_card.py` |
| seed | 种子 | A registered random seed; eight modules used to inline literals, now centralised in `seeds.py` (top-level leaf module — `decision` cannot import `evidence`). | `seeds.py` |
| schema 2 | schema 2 | Current run-card schema; **deliberately** breaks the old key — old keys claimed a coverage they did not have. | `evidence/run_card.py` |
| wall time / peak RSS | 运行时间 / 内存峰值 | Performance dimensions of one run, published alongside numeric metrics so regressions show up in the same evidence. | `evidence/run_card.py` |
| rows digest | 行摘要 | Hash over the fields the scorecard consumes for a set of decisions; binds the scorecard to the rows it claims. | `scorecard_provenance.py` |
| slice rows | 窗口行 | The decisions a windowed scorecard saw, by recorded bounds rather than by clock — for reproducible windowing. | `scorecard_provenance.py` |
| series digest | 系列摘要 | Hash of the whole logical series (archived rows + hot window), not of the working file's bytes — survives cold/hot rollovers. | `history_store.py` |

## History storage

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| cold / hot split | 冷热拆分 | Long-lived rows live in `_archive/`; recent rows live in the working file. Re-sewn on read. | `history_store.py` |
| archive path | 归档路径 | Where the cold half of a series lives. | `history_store.py` |

## Architecture and runtime

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| loop | 循环 | A phase of the daily pipeline (preflight, run, postflight, watchdog); shared contract lives in `_harness_common.py`. | `cli.py` |
| channel | 通道 | A delivery surface (Telegram / webhook / etc.); selected by `providers/delivery.py`. | `harness/intraday_watchdog.py` |
| runtime | 运行时 | The external agent (OpenClaw / Claude Code / Codex / DeepSeek Harness / custom) that owns model calls. clawock is the workflow, not the runtime. | `cli.py` |
| harness | Harness | The host process that owns scheduling, retries, gates; lives in `harness/`. | `cli.py` |
| command | 命令 | A registered `clawock <cmd>`; the registry lives in `utilities.py`. | `utilities.py` |
| utility | 子命令 | Same as `command`; the project uses both names. | `utilities.py` |
| plugin | 插件 | A drop-in feature that adds a command or context surface; lives under `plugins/`. | `cli.py` |
| skill | 技能 | A packaged prompt + runtime contract; delivered to the model via `skills_delivery`. | `cli.py` |
| evidence | 证据 | The persisted record (file or run_card) that links a claim to the data behind it. | `evidence/build_evidence.py` |
| verdict | 判定 | A short, decision-facing summary published by the brief or the deck. | `decision/record.py` |
| context profile | 上下文画像 | A pre-validated bundle of capabilities + skills for one kind of run; audited before being used. | `context/assembly.py` |
| capability root | 能力根 | The lazy-discovery root for one capability dimension in an OpenClaw context profile. | `context/assembly.py` |
| skills delivery | 技能下发 | How the model backend receives the skills catalog — full / diff / lazy. | `context/assembly.py` |
| prompt report | prompt 报告 | A redacted view of the model-side prompt state for one session, used for parity checks. | `context/assembly.py` |
| session family | 会话族 | The dialect a session key belongs to, ignoring the job or peer id. | `context/assembly.py` |

## Domain — markets

| EN | 中文 | 一句话 | First defined |
|---|---|---|---|
| ATR (Average True Range) | 平均真实波幅 | Mean of recent intraday true ranges; here `ATR(14)` sets the chandelier distance. | `labeling/triple_barrier.py` |
| stop distance pct | 距止损距离 | `(price − stop) / price`; **is itself the chandelier distance** — circular against barrier when used as a signal. | `labeling/triple_barrier.py` |
| look-through exposure | 透传敞口 | Gross and HHI exposure computed on the **underlying** issuer of a holding, not on the wrapper. | `instruments.py` |
| benchmark | 基准 | The market index used for residualisation and regime comparisons. | `market_data/benchmarks.py` |

## Conventions used here

- One EN term → one 中文 rendering. Translators do not pick alternates.
- `First defined` points to the **earliest** file or doc that defines or
  uses the term; if later code is the authoritative source, this column
  still points to the originating module to keep history honest.
- "Reject" / "refuse" / "print" are used deliberately: many of these
  measurements have a refusal path that returns a string verdict instead
  of a number, and that is part of the contract.
- Code words and identifiers stay in their original case; **bold** is
  reserved for emphasis inside one-line definitions, not for term names.
