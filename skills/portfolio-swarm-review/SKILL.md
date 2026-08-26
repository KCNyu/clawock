---
name: portfolio-swarm-review
description: Multi-agent swarm review of kcn's current holdings. Inspired by TauricResearch/TradingAgents framework already in workspace — three-tier analysis (analysts → bull/bear debate → risk debate + judge) with confidence scoring. Use for post-close reviews, holiday/next-session planning, pre-add sizing decisions, and any moment where a single-pass review is not enough. For lighter single-shot work, use portfolio-risk-review.
---

# Portfolio Swarm Review

Multi-agent portfolio review. Structure mirrors the TauricResearch/TradingAgents design — analysts (Tier 1) → researchers (Tier 2) → risk debators + judge (Tier 3). Each tier is distinct in the output; the Judge synthesizes. (The reference repo is no longer cloned locally; the structure is recorded here.)

## Required reads

In this order:
1. `/root/.openclaw/workspace/MEMORY.md`
2. `/root/.openclaw/workspace/portfolio.json`
3. `/root/.openclaw/workspace/INVESTMENT_SOP.md`
4. `/root/.openclaw/workspace/TOOLS.md` for data chain detail
5. `../daily-deep-brief/references/technical-playbooks.md` before any add / average-down synthesis

Active vs exited comes from `portfolio.json` alone (`shares > 0` / `== 0`); the
hand-maintained summary that used to be step 3 drifted 3.5 months and was deleted
(#1067).

## Fresh data rule

Refresh quotes before producing conclusions:

```bash
/root/.local/bin/clawock analyze-us    # US 7-route fallback
/root/.local/bin/clawock analyze-hk    # HK Tencent + Eastmoney full-batch cross-check/fallback → stooq → yfinance
```

If a leg is stale, name the exact ticker and limit confidence on conclusions involving it. **00100 only has Tencent** — flag explicitly if that leg fails. KR linkage: 07709/07747 are exited, but SKHY (SK Hynix ADR) can be held — check
`portfolio.json` rather than assuming the whole chain is dead.

## Holdings bucketing — read each run, do not hardcode

Pull live set from `portfolio.json` (`shares > 0`). Stable bucket structure; contents drift:

- **US growth / single-name beta** — active US non-leveraged growth names
- **US leverage ETF** — anything `is_leveraged_etf: true`
- **US theme / special situation** — catalyst-driven names
- **HK lower-beta core** — index/sector ETFs (e.g. 03032, 03033)
- **HK single-name** — individual equities (e.g. 00100 AI, 02208 wind)
- **HK leverage ETF** — 2x/3x recipes (e.g. 07226)

## Regime detection (run first)

Before any role analysis, classify current regime — this calibrates everything downstream:

| Regime | Trigger | Implication for sizing |
|---|---|---|
| **Trending up** | Index ADX > 25, MA20 > MA50, RSI 50-70 across book | Momentum-friendly — leveraged ETF holdable, trim only on overheats (RSI > 75) |
| **Trending down** | Index ADX > 25, MA20 < MA50, broad lower lows | Risk-off — leveraged ETF decay accelerates, prefer cash, no add |
| **Range-bound** | ADX < 20, sideways action, RSI mean-reverting around 50 | Mean-reversion plays — T-only, fade extremes |
| **Volatile / regime change** | High variance, conflicting MA stacks, sentiment chaos | Reduce size, widen stops, no convictions until clarity returns |

Index proxies: 纳指 / QQQ for US growth book; ^HSTECH for HK tech-heavy book.

## Tier 1 — Analysts (parallel)

Four analyst roles, run independently. Mirrors `tradingagents/agents/analysts/`.

### Analyst 1 — Position / Market
- For each active holding: price vs cost, PnL $ and %, distance to breakeven
- Technical state: trend, RSI-14, MA20/50 stance, immediate support/resistance
- Classify: core / tactical / weak / leverage-risk
- Output: one-line verdict per ticker + strongest/weakest called out

### Analyst 2 — Fundamentals
- Recent earnings / revenue trend for non-ETF names
- Valuation snapshot (P/E, P/S vs sector and history)
- Balance sheet headlines for special-situation names (cash runway, debt)
- For ETFs: underlying basket health, NAV premium/discount, decay since holding date
- Output: per non-ETF holding — "fair / stretched / cheap"; per ETF — "structurally OK / decay-risk now"

### Analyst 3 — News / Sentiment
- Finnhub news from scripts (`analyze_*_stocks.py` without `--no-news` already pulls 7 days + keyword sentiment)
- For US names: Reddit (r/wallstreetbets + r/stocks JSON, no auth) + Tavily news/X
- For HK names: 雪球 HK 评论区 + 富途社区 (scrapling StealthyFetcher) + Tavily 中文搜索
- 南向资金 当日 net (web search) for HK macro tone
- Output per holding: sentiment score -1 to +1 + 1-2 narratives + divergence vs price call-out

### Analyst 4 — Cross-Market Linkage
- US side: 纳指 / 罗素 / SOX tone; theme threads (stablecoin reg for CRCL, space/defense for RKLB, AI infra threads)
- HK side: 恒科 direction; 南向资金 flow; sector policy (风电 / AI / 监管)
- Inter-market: US tech overnight → HK tech open relationship; note when the link breaks
- Output: supportive / neutral / weak tag per chain, single most important inter-market signal

## Tier 2 — Bull vs Bear Researchers

Mirrors `tradingagents/agents/researchers/`. Run after Tier 1; each researcher reads all four analyst reports and argues a position.

### Bull Researcher
- Compose the strongest "hold and add" case using Tier 1 outputs
- Cite specific analyst findings as evidence (not gut)
- Identify what would have to be true for the position to work out
- Call out asymmetric upside specifically (leverage, catalyst dates, sentiment-vs-fundamentals gaps)

### Bear Researcher
- Compose the strongest "trim and avoid" case
- Cite specific risk findings, decay math, sentiment topping signals
- Identify the worst plausible outcome and what triggers it
- Counter the bull's strongest point directly

The output is a debate snippet (not a checklist), 100-200 words each side.

## Tier 3 — Risk Debate + Judge

Mirrors `tradingagents/agents/risk_mgmt/` + `managers/risk_manager.py`.

### Aggressive Risk Voice
- Argues for upside capture; pushes for full sizing on conviction names
- Quotes bull's strongest points
- Specifically calls out where the conservative voice misses opportunity cost

### Conservative Risk Voice
- Argues for capital preservation; pushes for trim on weak structure
- Quotes bear's strongest points
- Specifically calls out where the aggressive voice underestimates tail risk

### Neutral Voice
- Calls the middle ground — what specifically should size up, what should size down, what stays
- Required: pick a side for each contested holding, no "it depends" outputs

### Judge (Risk Manager)
Final synthesis. Weighs the three risk voices given:
- The user's documented risk preference: **aggressive** (per workspace MEMORY.md), so the aggressive voice gets weight unless its structural counter is strong
- Current regime (from regime detection above)
- Data freshness — any stale leg downgrades confidence

Output strategy decisions per ticker. The same ticker may have separate `core_position`, `intraday_t`, and `risk_rebalance` decisions on the same day:
- **Hold and watch** — thesis intact, no action
- **Trim on rebound** — thesis weakening, wait for strength
- **T-only** — no overnight conviction, fade extremes
- **Add only on trigger** — explicit trigger (price / MA cross / earnings / policy)
- **Cut** — thesis broken, exit on next acceptable bid (use sparingly)

Each item: ticker + concrete reason + concrete trigger/level if applicable.

### Signal-source weighting (driven_by edge — REQUIRED)

Not every signal source has earned the right to drive a decision. Read the current v2 ledger metrics (`decision_metrics.by_driver`, `by_strategy`, and `by_condition`) and compare `n_episodes`, average benefit, and date-cluster CI. Never copy a point-in-time rate from an old report. If n is small or the CI crosses zero, call it directional evidence only. Hard catalysts may drive an event/tactical decision; soft sentiment only nudges confidence. Policy-based deleveraging is a separate `risk_rebalance` decision with `driven_by=risk_rule`, not a claim of timing edge.

For active-call sizing, the authored confidence is an audit field, not a win probability. Match the proposed `action + driver + condition + regime` against `decision_metrics.hierarchical_calibration.current_group_calibrators`. A missing exact row or `abstain=true` normally contributes zero incremental size. The sole cold-start exception is one packet-approved technical setup tranche at exactly `min_tranche_shares`, with thesis/risk/lot gates passing and `remaining_tranches > 0`; this creates prospective evidence and may not be scaled up or repeated while open. `edge_supported=false` after sufficient evidence disables that exception. Otherwise multiply proposed signal size by `signal_size_multiplier` and show the calibrated probability, CI and resolved hierarchy level. The table carries only `evidence_sufficient=true` rows; omitted counts live in `current_group_calibrators_omitted` / `omitted_abstain_reasons`. This never cancels a mandatory `risk_rebalance + risk_rule` hard-cap action, because that is policy rather than timing alpha.

### Position / leverage hard caps (REQUIRED — overrides signal logic AND regime)

The drawdown was a **construction** problem (US β≈4.4, 73% leveraged ETFs, HK 85% one factor), not a signal problem. Before signal-source weighting even applies, the Judge must check these hard caps against the live book and emit a disciplinary trim/cut for any breach:

| Cap | Threshold | If breached |
|---|---|---|
| Non-leveraged single core | **35–60% review; ≤60% mandatory** | Review thesis in band; trim only above 60% |
| Leveraged single name | **≤35%** | Swap/reduce the leveraged leg |
| Measured correlated cluster | **≤70%** with ≥80% book coverage | Reduce the cluster, leveraged member first; one-name clusters do not count |
| Leveraged ETFs (per leg) | **≤50%** | Trim leverage to ≤50% |
| US β vs S&P | **≤3.0** | De-lever (cut leveraged ETFs first, not the high-conviction single) |
| Single leveraged ETF stop | **−18% vs cost** | Hard stop → swap 2x→1x same factor (keep exposure, stop decay) |

Rules: every breach **must** produce a concrete action in Judge synthesis (no "watch"). A 35–60% non-leveraged review-band row is advisory, not a breach, and must not be converted into a trim merely for diversification. Tag true breaches `driven_by=risk_rule` (disciplinary rebalancing, not news). This is the **one exemption from a trending-up/risk-on HOLD default** — in a melt-up you trim leverage *into* strength, not after the drawdown. De-lever by cutting leveraged ETFs (the β source), never by gutting a high-conviction single's thesis. Leveraged-leg directives use the **2x→1x same-factor swap** (not liquidation) per `brief_preflight.LEV_1X_SWAP`; 1x→2x re-entry only on 🧭 regime green. These caps mirror `brief_preflight.compute_risk_guardrail` / the brief's 「🚦 仓位/杠杆硬闸」 — keep thresholds in sync.

Read `risk_discipline.records` alongside the detector output and report each open breach's stable ID, age, acknowledgement and execution-evidence state. A plan-local override has no authority; only a durable, reasoned, unexpired override does. While a critical/high record remains open, do not recommend adding the same name, leveraged sleeve or factor. Exits remain legal, as does a same-plan 2×→1× pair whose factor-adjusted exposure decreases.

## Confidence scoring

End the report with a confidence score per major call, 0-100%:

| Confidence | Calibration |
|---|---|
| 80-100% | All four analysts align, both researchers' strongest cases converge, fresh data, regime clear |
| 60-79% | Most analysts align, one analyst dissents, regime clear |
| 40-59% | Analysts split, regime mixed, or one major data leg stale |
| 20-39% | Conflicting signals, regime change suspected, multiple stale legs |
| < 20% | Don't act on this read; wait for clarity |

## Final output structure

### Header
- Regime: {trending up / trending down / range / volatile}
- Data freshness: timestamp + any stale ticker flagged with ⚠️
- Book summary: total US PnL, total HK PnL, biggest winner/loser

### Tier 1 — Analyst reports
Four sub-sections (Market, Fundamentals, News/Sentiment, Cross-Market). Each terse — tables where data, prose where judgment.

### Tier 2 — Bull vs Bear
Two paragraphs, side by side framing.

### Tier 3 — Risk debate
- Aggressive voice (paragraph)
- Conservative voice (paragraph)
- Neutral voice (paragraph)

### Judge synthesis
Strategy decisions with ticker, strategy_id, action, condition, driver, and reason. Preserve simultaneous strategies instead of forcing one blended verdict.

### Confidence calls
Bullet list: "{Action} {Ticker} — confidence XX% — {one-line reason}"

### Next-session plan
Concrete plan: what to watch first at the open, which holdings matter most, price/macro triggers that flip the stance.

## Style rules

- Practical, not academic
- Every claim tied to a real ticker in the current book
- The four analysts' outputs must be DIFFERENT angles, not the same content reformatted
- Bull/Bear must actually disagree on at least one position — if they fully agree, the debate failed and the user should know
- Don't let high-conviction theme hide a bad structure (e.g. "RKLB story is strong" doesn't mean today's RSI 75 is a buy)
- Tables for any 3+ data points
- ⚠️ stale data flagged before any conclusion uses it
- Final plan concise enough to trade from
