---
name: portfolio-risk-review
description: Single-pass holdings analysis for kcn using workspace files and the local fetch chain. Use for portfolio review, position risk ranking, US-HK cross-market read, leverage ETF risk assessment, and one-shot actionable reports based on portfolio.json plus fresh quotes from `clawock analyze-us` / `clawock analyze-hk`.
---

# Portfolio Risk Review

Single-pass portfolio review. For multi-role analyst framework, use `portfolio-swarm-review` instead.

## Required reads

In this order:
1. `/root/.openclaw/workspace/MEMORY.md` — rules, traps, user preferences
2. `/root/.openclaw/workspace/portfolio.json` — authoritative holdings
3. `/root/.openclaw/workspace/memory/current-portfolio-summary.md` — active ticker list (also lists exited names so you know what NOT to analyze)
4. `/root/.openclaw/workspace/memory/theses/*.json` — canonical thesis state when present
5. `../daily-deep-brief/references/technical-playbooks.md` — read before any add / average-down plan
6. Recent `memory/YYYY-MM-DD.md` entries when recent trades matter
7. `/root/.openclaw/workspace/TOOLS.md` — data chain reference if anything fails

The thesis registry is read-only during a portfolio review. Missing files mean
`unknown`, not permission to reconstruct a baseline from prior prose. Price moves
may change valuation but cannot by themselves change business, moat, or management.

## Fresh data rule

**Always refresh quotes before judging the book. Use the workspace scripts.**

```bash
# US: 7-route fallback, RSI/MA/news/signal, writes back to portfolio.json
/root/.local/bin/clawock analyze-us
/root/.local/bin/clawock analyze-us --no-news    # skip news

# HK: Tencent primary + Eastmoney full-batch independent cross-check/fallback → stooq → yfinance
/root/.local/bin/clawock analyze-hk
/root/.local/bin/clawock analyze-hk --no-news
```

If any leg of the fallback fails for a holding, mark that line stale in the output. Special trap: **00100 only has Tencent** — Tencent down means 00100 is stale.

KR linkage names are no longer tracked (07709/07747 exited per `current-portfolio-summary.md`). Do not run any KR fetch.

## Holdings bucketing

**Do not hardcode tickers here** — names rotate. Pull the active list from `portfolio.json` (`shares > 0`) and `current-portfolio-summary.md`, then bucket by category each run:

| Bucket | What goes in |
|---|---|
| **US growth / single-name beta** | Active US non-leveraged names (typically aggressive growth) |
| **US leverage ETF** | Anything in `portfolio.json` flagged `is_leveraged_etf: true` (SOXL, RKLX, MSFU, ROBN-class names; rotates over time) |
| **US theme / special situation** | Regulatory / catalyst-driven (e.g. CRCL ~ GENIUS Act stablecoin) |
| **HK lower-beta core** | Index / sector ETFs without leverage (currently 03032, 03033) |
| **HK single-name** | Individual HK equities (currently 00100 AI, 02208 wind) |
| **HK leverage ETF** | 2x/3x recipes (currently 07226 南方2x恒科) |

The framing is stable; the contents drift. Verify each session against `current-portfolio-summary.md`.

## Four-lens analysis

### Lens A — PnL and position quality
For each active holding:
- gain/loss in $ and %
- distance to breakeven
- thesis status: intact / weakening / broken
- holdable / trim / T-only / cut

### Lens B — Cross-market linkage
US side (typically):
- NASDAQ / 纳指夜盘 tone — drives next-day HK tech open
- Specific theme threads (e.g. stablecoin reg for CRCL, space/defense for RKLB)

HK side:
- 恒科指数方向 — primary driver for 03032 / 03033 / 07226
- 南向资金当日净流向 (web search when material)
- Sector policy: 风电 for 02208, AI capex for 00100

Note explicit "supportive / neutral / weak" tag for each chain.

### Lens C — Concentration and drawdown risk
- Largest $ loss contributors right now
- Leverage decay risk (any 2x/3x ETF held > 5 trading days?)
- Correlation clusters (e.g. multiple 杠杆 ETF + single high-beta name = one bet)
- One-bad-day worst case for the book

### Lens D — Action priority
Sort positions into:
- **Hold and watch** — thesis intact
- **Trim on rebound** — thesis weakening but not broken; wait for strength
- **T-only** — don't add, exit on bounces, no overnight conviction
- **Add only on trigger** — define the trigger explicitly (price, MA cross, earnings, policy)

Keep `core_position`, `tactical_entry`, and `risk_rebalance` separate. A concentrated
non-leveraged core may remain held while one packet-approved tactical tranche is added;
loss alone never qualifies. For HK, state board lots and use whole-lot multiples; missing
`lot_size` blocks an add. For US, use integer shares under the current ledger contract.

## Output structure

### Portfolio snapshot
- 总 US PnL / 总 HK PnL
- 最大盈利位 / 最大亏损位
- 主要风险源 (one line)

### Position-by-position
Table format:

| Ticker | Price | PnL ($) | PnL (%) | One-line verdict |
|---|---|---|---|---|

### Cross-market read
- **US side**: tone + key threads
- **HK side**: 恒科方向 + 南向 + sector policy notes

### Top 3 risks (ranked)
Highest to lowest, each with concrete cause.

### Action plan
Four buckets from Lens D, with concrete triggers/levels where applicable.

## Style rules

- Direct, practical, no academic hedging
- Tie every conclusion to actual holdings (no hypothetical names)
- Respect the user's aggressive style — but call real risk plainly
- Tables for any 3+ data points
- Cite data freshness: "数据: clawock analyze-us / clawock analyze-hk {timestamp}"
- Flag stale legs loudly with ⚠️ before any conclusion drawn from them
- Do not substitute external "best practice" frameworks for the workspace data chain
