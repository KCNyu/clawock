# Product vs instance: what belongs in `src/clawock/`, what stays instance-owned

kcn's definition of done for this repository:

> 一个标准的易迁移的，而不是寄生于 openclaw 上面的一个四不像

That is a statement about *shape*, and shape is only real if a reviewer can apply
it to a file they have not seen. This page is that rule, plus the classification
of every module in `scripts/data/` against it (#331).

It classifies before moving. The point is that the migration afterwards is
mechanical and reviewable one file at a time, and that a new file has an obvious
home instead of defaulting to `scripts/data/` because that is where things go.
The same rule now covers all 11 modules in the separately packaged
`instances/kcnyu/` adapter (#365).

## The rule

Ask one question about a module:

> **Would someone running clawock against their own book need this, unchanged?**

- **Yes → product.** It belongs in `src/clawock/`: importable, no assumption about
  where the workspace is, no knowledge of which runtime or which repository it is
  deployed into. Prices, ledger schema, risk math, validation gates, the decision
  contract.
- **No → instance.** It is kcn's desk: this portfolio's particular holdings, this
  host's cron wiring, this repository's publishing identity, this deployment's
  delivery channel. It stays in `scripts/`, and may assume anything it likes.

Two clarifications that decide most of the hard cases:

**A fetcher is product; a fetcher's *subject* is instance.** `clawock us-quotes`
is product — any book with US equities needs multi-provider price fetching with
the same staleness rules. `fetch_gold_dca.py` is instance: it exists because kcn
holds 000217, and nobody else's book has that position by construction.

**Knowing a runtime is instance, even when the code is generic.** Anything that
spawns OpenClaw, writes its schedule, reads its state, or targets this
repository's Pages/branches is instance no matter how cleanly it is written. That
is the same boundary the runtime-coupling ratchet counts, and `src/clawock/providers/`
is the one place allowed to cross it.

## What this rule is not

It is not "big files move, small files stay", and not "anything with a test is
product". `build_dashboard.py` is 3,141 lines of product; `clawock mark-followed` is 44
lines of product; `assemble_dashboard_gif.py` is 92 lines of instance.

It is also not a promise that product code is *currently* importable from a
foreign workspace. Several product modules still read `WS/config/` (#356). The
classification says where a file belongs, not that it has arrived.

## Classification

The package now has a standard `src/clawock/` source boundary. The historical
counts below classify the original `scripts/data/` migration inventory; they are
not a claim that `scripts/` is an acceptable final product home.

Historical classification counts: **product 60 · instance 27**. The two cron
synchronizers now live in `ops/host/`; the table retains them to preserve the
decision record while the rest of `scripts/data/` is migrated. Canonical
instrument metadata now ships as `clawock.portfolio.instruments`; configured
instruments remain workspace data and are not bundled in the wheel. The
dependency-free `bar_checks`,
`json_repair`, `safe_io`, and `trading_calendar` utilities have also moved into
`src/clawock/`. The generation-bound brief context and typed decision packet now
ship there too; tools never import executable Python from a user's workspace.
The v2 decision ledger and settlement engine is now `clawock.decision_v2`; its
default data root is the caller's workspace, never the package installation path.
Planning continuity, durable risk governance, dashboard output ownership,
numeric research provenance, and backtest run cards also ship in `clawock`.
The risk engine derives leverage pairs from the workspace instrument registry;
the dashboard diff engine reads `config/dashboard-outputs.json`. Neither desk's
tickers nor artifact paths are compiled into the public package.
The entry gate, thesis registry, earnings ledger, research queue, and claim
scanner now ship there as well. KCNyu's research cutover date, cadence and list
of claim-bearing backtests remain workspace configuration.
Realized P&L, snapshot attribution, aggregate rebuilding, cash derivation,
shadow-book simulation, and their shared ledger arithmetic now ship in the
package. KCNyu's decision-leg/book mapping, book names, cash-field bindings,
market calendars, and per-book percentage precision remain in
`config/portfolio-derivations.json`.
Quant factors, leverage-regime calculation, T+0 setup grading and both
forward-return review loops now ship in the package as `clawock quant`,
`regime`, `t0`, `quant-review`, and `t0-review`. They discover holdings from
the ledger and instrument registry rather than assuming KCNyu's book keys.
East Money symbol resolution, HK/US fundamentals, fund flow and Chinese-news
collection now ship as `clawock fundamentals`, `fundflow`, and `em-news`.
The news collector discovers HK holdings from the selected workspace's ledger
and registry rather than assuming a book named `hk_stocks`.
The artifact-backed evidence page and expiring news graph now ship as
`clawock evidence` and `clawock news-evidence`. `build_dashboard.py` remains in
the repository boundary until its three explicit dependencies on the KCNyu
adapter and operator-only `workflow_outcomes` are extracted; moving it first
would make the wheel depend on instance code.

The evidence slice is also the first migrated area placed in its terminal
domain namespace rather than copied flat from `scripts/data`: provenance gates,
research status, run cards, the evidence page and the news graph live under
`src/clawock/evidence/`. Stable CLI command names are the public interface;
historical Python module paths are not retained as package-root shims. The
remaining flat package modules are transitional inventory and move with their
`decision/`, `market_data/`, `context/` or adapter-owned batch —
they are not the accepted terminal layout.

The complete portable portfolio core now lives under `src/clawock/portfolio/`:
instrument and book resolution, pure ledger math, realized and snapshot
attribution, aggregate and cash reconstruction, FX, risk, integrity, and shadow
simulation. Historical filenames such as `recompute_cash.py` and
`portfolio_risk_metrics.py` are not retained as package-root aliases. Stable
CLI commands remain unchanged, so runtimes depend on product capabilities
rather than Python file layout.

### Product — the engine

| Area | Modules |
|---|---|
| Ledger + decision contract | `plan_surface` `clawock mark-followed` `clawock audit-resettle` |
| Portfolio + money integrity | `clawock.portfolio.instruments` `clawock.portfolio.books` `clawock aggregates` `clawock cash` `clawock realized` `clawock shadow` `clawock fx` `clawock portfolio-risk` `clawock integrity` |
| Decision risk + governance | `risk_discipline` `thesis_registry` `entry_gate` `earnings_review` `research_surface` |
| Quant + research | `clawock quant` `clawock regime` `clawock t0` `clawock quant-review` `clawock t0-review` `clawock cross-factor` `clawock peer-residual` `peer_scan` `suggest_peers` |
| Evidence + provenance | `clawock news-evidence` `clawock.evidence.research_provenance` `clawock.evidence.claim_provenance` `clawock.evidence.run_card` `clawock evidence` |
| Market data | `clawock fetch-peers` `clawock filings` `clawock fundamentals` `clawock fundflow` `clawock em-news` `clawock daily-bars` `clawock catalysts` `clawock us-quotes` `clawock analyze-us` `clawock analyze-hk` `clawock benchmark` `fetch_sentiment` `fetch_macro` `mover_news` `_em_http` |
| Moved into product | `clawock.portfolio.instruments` `clawock.portfolio.books` `clawock.portfolio.math` `clawock.portfolio.realized` `clawock.portfolio.snapshots` `clawock.portfolio.aggregates` `clawock.portfolio.cash` `clawock.portfolio.shadow` `clawock.portfolio.fx` `clawock.portfolio.risk` `clawock.portfolio.integrity` `clawock.mobile_table` `clawock.bar_checks` `clawock.brief_context` `clawock.brief_decision_packet` `clawock.decision_contract` `clawock.decision_v2` `clawock.plan_surface` `clawock.risk_discipline` `clawock.dashboard_outputs` `clawock.evidence.research_provenance` `clawock.evidence.run_card` `clawock.entry_gate` `clawock.thesis_registry` `clawock.earnings_review` `clawock.evidence.research_surface` `clawock.evidence.claim_provenance` `clawock.compute_quant_signals` `clawock.compute_regime` `clawock.compute_t0_setups` `clawock.quant_signal_review` `clawock.t0_setup_review` `clawock.cross_sectional_factor` `clawock.peer_residual_engine` `clawock.fetch_peers` `clawock.fetch_us_filings` `clawock._em_symbols` `clawock.fetch_fundamentals_em` `clawock.fetch_fundflow_em` `clawock.fetch_em_news` `clawock.fetch_daily_bars` `clawock.fetch_catalysts` `clawock.known_catalysts` `clawock.fetch_us_stocks` `clawock.analyze_us_stocks` `clawock.analyze_hk_stocks` `clawock.fetch_benchmark_history` `clawock.validate_sidecars` `clawock.mark_followed` `clawock.audit_resettle` `clawock.evidence.build_evidence` `clawock.evidence.news_evidence_graph` `clawock.json_repair` `clawock.safe_io` `clawock.trading_calendar` | Code and schemas ship in the wheel; each user's configuration and data stay in their workspace |
| Gates + outputs | `clawock integrity` `clawock validate-sidecar` `dashboard_outputs` `build_dashboard` `workflow_outcomes` `workflow_health` `coverage_badge` `cron_contract` `cron_heartbeat` |

### Instance — kcn's desk

| Area | Modules | Why |
|---|---|---|
| This host's cron wiring | `sync_cron_payloads` `sync_us_cron_dst` `cron_runs` `cron_timeline` `cron_token_audit` `cron_health_check` `generate_cron_docs` `gc_sessions` `intraday_delta_gate` | Reads or writes OpenClaw's schedule and state |
| This repo's publishing | `publish_data_branch` `indexnow_submit` `assemble_dashboard_gif` `rick_broadcast` | Targets this repository's branches, Pages and voice |
| This repo's workflows | `gh_action_brief_fallback` `gh_action_news_digest` `gh_action_weekly_review` `xiaomi_llm` | Entry points for `.github/workflows/`, and the LLM client they use |
| kcn's specific positions | `fetch_gold_dca` `update_gold_dca` `fetch_influencer_feed` | 000217; a feed chosen for this book's theses |
| Claims about this book | `backtest_hstech_regime` `backtest_us_leverage` `backtest_combined_regime` `validate_regime_dial` | Validate kcn's dial against kcn's holdings |
| This site's output contract | `config/dashboard-outputs.json` | Names this desk's generated artifacts, clock fields and linked generation group; the wheel only implements the configured diff algorithm |
| This desk's research rollout | `config/research-governance.json` `config/claim-provenance.json` | Pins the gate cutover/cadence and the KCNyu backtest claim surfaces without compiling either into the wheel |
| This desk's ledger bindings | `config/portfolio-derivations.json` | Pins decision legs, risk books, book names, cash fields, market calendars, and output precision while the wheel owns only the arithmetic |

### Contested — flagging rather than hiding

Three calls are genuinely arguable, and a reviewer may reasonably move them:

- **`build_dashboard.py`** — filed as product because it aggregates any ledger,
  but it also knows this site's tab structure and card set. If the renderer is
  ever split from the aggregation, the aggregation is product and the rest is not.
- **`fetch_influencer_feed.py`** — filed as instance because the figures tracked
  were chosen for this book. The mechanism (scan a feed, score impact) is product.
- **`cron_contract` / `cron_heartbeat`** — filed as product: they describe *a*
  schedule contract, not OpenClaw's. Their callers are instance. If that ever
  stops being true they move.

## `scripts/legacy/` — resolved

#331 asks for this directory to be deleted or justified. Per file:

- **`backfill_t0_history.py` — deleted.** A one-off that seeded
  `t0_setups_history.jsonl` from historical snapshots so `t0_setup_review` had
  data immediately instead of waiting weeks of live accumulation. That job
  completed; the history now accumulates on its own, and the module had **zero
  references anywhere in the repository**.
- **`backfill_snapshot_realized.py` — kept, justified.** A repair for historical
  snapshots missing realized P&L. It stays because it is *destructive* — it
  rewrites `memory/snapshots/` in place — and `tests/test_workspace_portability.py`
  exists specifically to pin that it cannot aim at production when imported. That
  guard is worth more than the disk space, and deleting the script would delete
  the test's subject.
- **`stock_analyzer.py` — kept, justified.** Superseded by `analyze_us_stocks` and
  `analyze_hk_stocks`, and documented as superseded in `docs/reference/scripts.md`.
  It is retained deliberately as reference material: MEMORY.md records that
  retired scripts stay readable for their early fallback ordering and the reasons
  they were replaced.

## `instances/kcnyu/` — the live desk adapter

The portable lifecycle vocabulary and generation-pinned `ArtifactSet` live in
`src/clawock/harness/`; `clawock brief|report|intraday` dispatch phases in-process
through the `clawock.instance_phases` entry-point group. KCNyu's implementation
lives in its own `clawock-kcnyu` distribution under `instances/kcnyu/`, so the
public wheel neither imports nor ships it. The former `scripts/harness/` aliases
were retired after every production and test caller moved to installed commands
or explicit package imports.

| Classification | Modules | Boundary |
|---|---|---|
| Mixed — product preflight plus instance I/O | `brief_preflight` `report_preflight` `intraday_preflight` | Context calculation and gates are product; live paths, refresh side effects and `.tmp` placement are instance adapter concerns |
| Mixed — product validation plus instance publish/delivery | `brief_postflight` `report_postflight` `intraday_postflight` | Validation/assembly is product; git coordination, dashboard publication and channel delivery are instance capabilities |
| Mixed shared implementation | `_harness_common` | Generation/validation helpers are product; this repository's publish and dashboard refresh path is instance |
| Instance runtime supervision | `_watchdog_common` `brief_watchdog` `report_watchdog` `intraday_watchdog` | Reads runtime sessions/run history, mirrors this deployment's channels and applies this desk's retry policy |

The separate distribution is a migration seam, not evidence that all code in it
is instance-specific. Reusable investment preflight, validation,
reconciliation, generation and postflight behavior belongs in `src/clawock/`;
reusable OpenClaw behavior belongs behind a runtime adapter. Only KCNyu delivery
targets, live schedules, repository publication and other desk bindings remain
here. `clawock-kcnyu` is repository-only and must never be published to PyPI or
pulled in by the portable package.

## Note on the counts in #331

The issue states 97 files and cites #269 as having 31 sites. Both have moved:
`scripts/data/` holds **87** files as of this page, and #269's sites are **zero** —
every code import now resolves from the checkout. The issue's fourth acceptance
item ("the classification predicts #269's 31 sites") is therefore satisfied
vacuously rather than by prediction, and is not evidence either way.
