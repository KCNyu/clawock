"""The command registry: every `clawock <utility>` and the module that owns it.

Lives here rather than in `cli` because it is data, not an entry point, and two
harness preflights need it (#814). They used to reach up into `clawock.cli` for
it — a module in a lower layer importing the top-level entry point, which is the
most clear-cut import inversion in the package and the one that put `harness` and
`cli` in the same dependency cycle.

Nothing in this module imports anything from clawock. That is the point: it can
be read from any layer without dragging the CLI, argparse, or a single utility
module in behind it.
"""
from __future__ import annotations

# Command -> module owning its `main(argv)`. One table, not a name list plus a
# parallel dispatch chain: those were two copies of the same 49 entries, and the
# four `evaluate-*` commands shipped in #429 pointing at a module with no `main`
# because only one copy was updated.
PACKAGED_UTILITIES = {
    "aggregates": "clawock.portfolio.aggregates",
    "analyze-hk": "clawock.market_data.hk_analysis",
    "analyze-us": "clawock.market_data.us_analysis",
    "audit-resettle": "clawock.decision.settlement",
    "benchmark": "clawock.market_data.benchmarks",
    "cash": "clawock.portfolio.cash",
    "catalysts": "clawock.market_data.calendar",
    "claim-provenance": "clawock.evidence.claim_provenance",
    "cross-factor": "clawock.market_data.factors",
    "daily-bars": "clawock.market_data.bars",
    "dashboard-build": "clawock.publish.dashboard",
    "dashboard-outputs": "clawock.publish.outputs",
    "earnings": "clawock.decision.earnings",
    "em-news": "clawock.market_data.eastmoney_news",
    "entry-gate": "clawock.decision.entry",
    "evaluate-combined-regime": "clawock.evaluation.combined_regime",
    "evaluate-hstech-regime": "clawock.evaluation.hstech_regime",
    "evaluate-us-leverage": "clawock.evaluation.us_leverage",
    "evaluate-add-alpha": "clawock.evaluation.add_alpha_walkforward",
    "evidence": "clawock.evidence.build_evidence",
    "fetch-peers": "clawock.market_data.peer_quotes",
    "filings": "clawock.market_data.filings",
    "fundamentals": "clawock.market_data.fundamentals",
    "fundflow": "clawock.market_data.fund_flows",
    "fx": "clawock.portfolio.fx",
    "integrity": "clawock.portfolio.integrity",
    "macro": "clawock.market_data.macro",
    "mark-followed": "clawock.decision.execution",
    "mover-evidence": "clawock.market_data.mover_evidence",
    "news-evidence": "clawock.evidence.news_evidence_graph",
    "peer-residual": "clawock.market_data.peer_residuals",
    "plan-context": "clawock.decision.plans",
    "portfolio-risk": "clawock.portfolio.risk",
    "provenance": "clawock.evidence.research_provenance",
    "quant": "clawock.decision.signals",
    "quant-review": "clawock.decision.signal_review",
    "realized": "clawock.portfolio.realized",
    "reconcile": "clawock.portfolio.reconcile",
    "record": "clawock.decision.record",
    "regime": "clawock.decision.regime",
    "research": "clawock.evidence.research_surface",
    "risk": "clawock.decision.risk",
    "run-card": "clawock.evidence.run_card",
    "sentiment": "clawock.market_data.sentiment",
    "shadow": "clawock.portfolio.shadow",
    "t0": "clawock.decision.setups",
    "t0-review": "clawock.decision.setup_review",
    "thesis": "clawock.decision.theses",
    "us-quotes": "clawock.market_data.us_quotes",
    "validate-regime-dial": "clawock.evaluation.regime_validation",
    "validate-sidecar": "clawock.publish.artifacts",
    "watch-list": "clawock.decision.watch_list",
}

# Its own exit-code convention: a partial peer fetch must not read as success.
HARD_EXIT_UTILITIES = frozenset({"fetch-peers"})

# These scan `argv` for flags by hand instead of using argparse, so `--help` is
# not a flag to them — it is an unrecognised token they ignore while going on to
# do the real work. `clawock analyze-hk --help` fetched live quotes and rewrote
# portfolio.json. Answering here keeps that one input from reaching them; their
# contract is the module docstring, which is what gets printed.
DOCSTRING_HELP_UTILITIES = frozenset({
    "analyze-hk", "analyze-us", "fetch-peers", "filings", "fundamentals",
    "fundflow", "quant", "quant-review", "t0", "t0-review", "us-quotes",
})

# One help line per table entry, keyed by it. The parser below is built from
# PACKAGED_UTILITIES, not from this dict, because the two used to be a table and a
# parallel name list: #745 is the drift that shape allows. `record` was added to the
# name list on 2026-08-16 and never to the table, so `clawock record` — the only
# write path into the decision-mind ledger — was advertised by `--help`, by the DSH
# skill contract and by docs/, and reachable from none of them. A help line missing
# here is now a KeyError while the parser is built, i.e. on every invocation.
UTILITY_HELP = {
    "aggregates": "recompute portfolio values and P&L from leaves",
    "analyze-hk": "refresh and analyze active HK holdings",
    "analyze-us": "refresh and analyze active US holdings",
    "audit-resettle": "audit decision re-settlement without writing by default",
    "benchmark": "fetch SPY, HSI, and HSTECH daily benchmark history",
    "cash": "recompute cash from its reconciliation ledger",
    "catalysts": "fetch upcoming earnings and macro catalysts",
    "claim-provenance": "verify backtest claims against run cards",
    "cross-factor": "rank a curated universe with sector-neutral factors",
    "daily-bars": "maintain immutable canonical daily OHLC bars",
    "dashboard-build": "build the configured workspace dashboard projection",
    "dashboard-outputs": "compare one generated dashboard write set",
    "earnings": "validate and release primary-source earnings reviews",
    "em-news": "fetch Chinese news for active HK holdings",
    "entry-gate": "validate or assess a pre-investment research gate",
    "evaluate-add-alpha":
        "walk-forward evaluate add factor and information interactions",
    "evaluate-combined-regime": "backtest the combined configured regime dial",
    "evaluate-hstech-regime": "backtest the HSTECH leverage regime",
    "evaluate-us-leverage": "backtest US single-stock leverage regimes",
    "evidence": "rebuild the artifact-backed public evidence page",
    "fetch-peers": "price peer tickers from a JSON request on stdin",
    "filings": "fetch SEC filings and point-in-time XBRL fundamentals",
    "fundamentals": "fetch East Money HK/US statements and indicators",
    "fundflow": "fetch East Money HK/US daily capital flow",
    "fx": "fetch or convert the canonical USD/HKD rate",
    "integrity": "verify portfolio money and market-data invariants",
    "macro": "fetch a portable macro and major-index snapshot",
    "mark-followed": "record execution ground truth in the decision ledger",
    "mover-evidence": "probe bounded filing and news evidence for movers",
    "news-evidence": "build the expiring news and filing evidence graph",
    "peer-residual": "calibrate curated-peer residual and leadership rules",
    "plan-context": "show still-open decisions for a downstream run",
    "portfolio-risk": "compute portfolio beta, volatility, and tail risk",
    "provenance": "verify numeric research provenance",
    "quant": "compute holding-level trend, momentum, and risk factors",
    "quant-review": "reconcile factor signals with forward returns",
    "realized": "recompute realized P&L from the trade ledger",
    "reconcile": "recompute all portfolio derivations and verify integrity",
    "record": "append a conversation verdict to the decision-mind ledger",
    "regime": "compute the configured leverage-risk regime",
    "research": "show or check the configured research work queue",
    "risk": "maintain the durable risk-breach governance ledger",
    "run-card": "inspect durable backtest evidence",
    "sentiment": "scan configured holdings across public sentiment sources",
    "shadow": "simulate followed decisions against buy and hold",
    "t0": "grade intraday setup quality from existing market data",
    "t0-review": "reconcile setup grades with next-session returns",
    "thesis": "validate thesis state or evaluate evidence-only drift",
    "us-quotes": "refresh US holdings through the provider fallback chain",
    "validate-regime-dial": "walk-forward validate the production regime dial",
    "validate-sidecar": "validate a workflow-generated sidecar artifact",
    "watch-list": "scan non-held AI watch names for price opportunities",
}
