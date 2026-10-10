"""Typed, queryable decision boundary for the daily deep brief.

The expensive producers remain authoritative for prices, technical indicators,
quant factors, evidence and risk.  This module only projects those results into
a compact contract:

* code owns facts, arithmetic, feasibility and the authorisations already
  given; the registered rules' classifications travel as their opinion;
* the model owns the hypothesis, the trade-off and the proposal, and a rule
  that disagrees is recorded beside it rather than applied to it (#2842);
* Pages receives a stable view-model and never re-implements the joins.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
from datetime import date
from pathlib import Path

from clawock.decision.actions import (
    ACTIVE_ACTIONS, SELL_ACTIONS, SWAP_SELL_ACTIONS, paired_swap_sells,
)
from clawock.decision import add_alpha, add_policy, early_trend, left_side
from clawock.decision import add_policy as add_policy_module
from clawock.decision import receipts
from clawock.decision import risk as risk_ledger
from clawock.decision.actions import is_risk_swap_buy
from clawock.instruments import get as instrument_metadata, is_leveraged_holding
from clawock.workspace import workspace_root


SCHEMA_VERSION = 1
JUDGMENT_SCHEMA_VERSION = 3
PAGES_SCHEMA_VERSION = 1
MAX_QUERY_BYTES = 24 * 1024
# The whole-book summary is a different animal from a per-ticker section query
# and needs its own budget. One constant served both until 2026-08-17, when the
# book reached 10 active holdings: the summary is O(holdings) and crossed 24KB
# at 33,543 bytes. `decision_packet_summary` then failed outright — and it is
# the brief's Step 2 "唯一常驻输入", so the 盘前深度简报 agent had no way into
# the analysis and burned its whole turn on tool help before ending "ok" with
# nothing written. Nothing warned on the way past the line, because the trigger
# was portfolio growth, not a code change.
#
# Sized from the measured cost, not from a round number: on 2026-10-08 a row
# was ~3.5KB of the printed summary and the book-level blocks ~8KB, so nine
# holdings printed 44KB. 64KB carries ~16, and `READ_BUDGET_WARN_RATIO` speaks
# up at ~12 — three holdings of notice instead of the 700 bytes that were left
# under the old 48KB line (#2816).
MAX_SUMMARY_BYTES = 64 * 1024
#: How full a model-facing read may get before `read_budget_report` calls it
#: near its budget. The budgets bound what one tool call puts in front of the
#: model; the stored packet itself is only ever read whole by harness code, so
#: it has no ceiling of its own. It had one until #2816: 96KiB over the whole
#: artifact, which on 2026-10-09 refused a nine-holding packet for 71 bytes and
#: left the day without a brief, while every read the model would have made was
#: inside its own budget.
READ_BUDGET_WARN_RATIO = 0.8

#: The per-event arithmetic behind `information`'s scores. #1039 tiered these
#: out of the persisted ledger provenance as "zero-reader bulk"; the same two
#: lists were still copied into the packet itself, where they rode along in every
#: `information` query the model made.
INFORMATION_COLD_KEYS = ("attention_components", "event_components")


#: Sections `decision_packet_query` may narrow a ticker row to.
#:
#: Every structured key a compiled row carries belongs here. The list used to
#: live in `tools/context_tools.py` and had drifted to seven of the twelve:
#: `information` — the one section `summary_view` does not project either — had
#: no path of its own at all, so the only way to read it was the whole-row query
#: both the tool description and SKILL.md tell the agent not to make. Owned here
#: because this module is what builds the rows; `test_brief_decision_packet`
#: compiles one and compares.
QUERYABLE_SECTIONS = (
    "facts", "technical", "thesis", "execution", "quant", "sentiment",
    "history", "information", "evidence", "risk", "status", "constraints",
)


def _without_cold_components(information: dict) -> dict:
    """`information` minus the per-event component lists.

    They have to exist while the packet is being built — `classify_authority`
    reads `event_components` to find the positive events that authorise an add,
    and both lists to collect the evidence ids it cites — so this drops them at
    the point of storage, never at the point of computation. What survives is
    what any reader of the stored packet uses: the scores, the ranks, the
    counts, and (in `quant.add_authority`) the event ids the authority decision
    actually cited.

    Their canonical store is `assets/data/news_evidence_graph.json`, committed
    daily under the #951 rolling windows — the same store #1039 named.
    """
    return {k: v for k, v in (information or {}).items()
            if k not in INFORMATION_COLD_KEYS}

ADD_ALPHA_POLICY = workspace_root() / "config" / "add-alpha-policy.json"
VERDICTS = {"bullish", "neutral", "bearish", "mixed"}
DISPOSITIONS = {"candidate", "wait", "reject"}
TEXT_LIMITS = {
    "portfolio_assessment": 800,
    "portfolio_counterargument": 800,
    "assessment": 500,
    "counterargument": 500,
    "rationale": 500,
    "falsifier": 300,
    "next_evidence": 300,
    # Tier 1 cells the harness cannot compute: what the filings say, and how the
    # name sits against its own market.  Short, because they are table cells.
    "fundamentals": 300,
    "cross_market": 300,
    "sentiment_read": 300,
    "peer_read": 300,
    # The narrative slots.  These carry the debate the report used to contain as
    # model-authored markdown; the harness lays them out now, so they are text.
    "regime_read": 600,
    "bull": 700,
    "bear": 700,
    "devils_advocate": 700,
    "attacked_consensus": 200,
    "aggressive": 700,
    "conservative": 700,
    "neutral": 900,
    "sector_read": 700,
    "macro_read": 600,
    "calibration_read": 600,
    "next_session": 400,
    "data_holes": 400,
}
RISK_VOICES = ("aggressive", "conservative", "neutral")
NARRATIVE_TEXT_FIELDS = (
    "regime_read", "bull", "bear", "devils_advocate", "attacked_consensus",
    "aggressive", "conservative", "neutral", "sector_read", "macro_read",
    "calibration_read",
)
NARRATIVE_LIST_FIELDS = {"next_session": (1, 8), "data_holes": (0, 8)}
ROW_TEXT_FIELDS = (
    "assessment", "counterargument", "rationale", "falsifier", "next_evidence",
    "fundamentals", "cross_market", "sentiment_read", "peer_read",
)

# Layout the model must not emit.  The report's markdown is rendered by
# `clawock.harness.brief_render` from these fields plus the deterministic
# context, so a pipe or a heading in a judgment field is not a formatting
# preference — it lands inside a table cell the harness is already drawing and
# breaks the row.  Rejecting it here is what keeps "the model writes thoughts,
# the harness writes layout" true rather than merely intended.
_LAYOUT_MARKERS = (
    ("|", "table pipe"),
    ("```", "code fence"),
    ("▎", "section ornament"),
    ("**", "bold marker"),
)
_LAYOUT_LINE_START = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>\s)")


def _layout_violation(value: str) -> str | None:
    """The formatting complaint about one prose field, or None if it is prose."""
    for marker, label in _LAYOUT_MARKERS:
        if marker in value:
            return f"contains a {label} ({marker!r})"
    for line in value.splitlines():
        if _LAYOUT_LINE_START.match(line):
            return "starts a line with a markdown heading, bullet or quote marker"
    return None


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _number(value, digits=4):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return round(value, digits)


def _active_holdings(context: dict):
    portfolios = (context.get("portfolio") or {}).get("portfolios") or {}
    for region, leg in (("us_stocks", "US"), ("hk_stocks", "HK")):
        for holding in (portfolios.get(region) or {}).get("holdings") or []:
            if _number(holding.get("shares")) and _number(holding.get("shares")) > 0:
                yield leg, holding


def _proxy_map(context: dict) -> dict[str, str]:
    names = (
        ((context.get("risk_guardrail") or {}).get("lev_regime") or {})
        .get("us", {})
        .get("names", [])
    )
    out = {
        str(row.get("etf")): str(row.get("underlying"))
        for row in names
        if row.get("etf") and row.get("underlying")
    }
    # The instrument registry is the production authority for both books;
    # lev_regime.names is only a risk-dial subset and used to omit HK proxies.
    for _, holding in _active_holdings(context):
        ticker = str(holding.get("ticker") or "")
        meta = instrument_metadata(ticker) or {}
        available = (context.get("quant_signals") or {}).get("rows") or {}
        signal = next(
            (
                str(candidate) for candidate in (
                    meta.get("signal_symbol"), meta.get("one_x_substitute")
                )
                if candidate and str(candidate) in available
            ),
            None,
        )
        if signal:
            out[ticker] = str(signal)
    for ticker, row in ((context.get("quant_signals") or {}).get("rows") or {}).items():
        note = str(row.get("note") or "")
        marker = " 的标的"
        if marker in note:
            out[note.split(marker, 1)[0].strip()] = str(ticker)
    return out


def _rsi_state(value):
    value = _number(value, 1)
    if value is None:
        return "unknown"
    if value <= 30:
        return "oversold"
    if value < 45:
        return "weak"
    if value <= 60:
        return "neutral"
    if value < 70:
        return "strong"
    return "overbought"


def _technical(row: dict, source_ticker: str, proxy: bool) -> dict:
    row = row if isinstance(row, dict) else {}
    fresh = row.get("status") in (None, "fresh")
    trend = (
        "on" if row.get("trend_on") is True
        else "off" if row.get("trend_on") is False
        else "unknown"
    )
    stop_distance = _number(row.get("stop_distance_pct"), 1)
    setups = []
    if fresh:
        for setup in row.get("technical_setups") or []:
            entry = _number(setup.get("entry_price"), 4)
            invalidation = _number(setup.get("invalidation_price"), 4)
            if (not setup.get("setup_id") or entry is None
                    or invalidation is None or invalidation >= entry):
                continue
            setups.append({
                "setup_id": str(setup["setup_id"]),
                "campaign_id": str(setup.get("campaign_id") or setup["setup_id"]),
                "label": str(setup.get("label") or setup["setup_id"]),
                "entry_type": setup.get("entry_type"),
                "entry_price": entry,
                "invalidation_price": invalidation,
                "max_tranches": int(setup.get("max_tranches") or 1),
                "tranche_pct_of_position": _number(
                    setup.get("tranche_pct_of_position"), 4
                ),
                "valid_for_sessions": int(
                    setup.get("valid_for_sessions") or 1
                ),
                "signal_date": setup.get("signal_date"),
                "authority_tier": setup.get("authority_tier"),
                "target_tranche_level": _number(
                    setup.get("target_tranche_level"), 2
                ),
                "authority_sources": list(setup.get("authority_sources") or []),
                "evidence_families": list(setup.get("evidence_families") or []),
                "detail": str(setup.get("detail") or "")[:300],
            })
    tag = row.get("tag")
    if trend == "unknown" and isinstance(tag, str):
        tag = tag.replace("趋势OFF", "趋势未知")
    return {
        "source_ticker": source_ticker,
        "is_proxy": bool(proxy),
        "status": row.get("status") or ("available" if row else "unavailable"),
        "as_of": row.get("row_as_of"),
        "tag": tag,
        "trend": trend,
        "rsi14": _number(row.get("rsi14"), 1),
        "rsi_state": _rsi_state(row.get("rsi14")),
        "dist_ma200_pct": _number(row.get("dist_ma200_pct"), 1),
        "pct_52w_range": _number(row.get("pct_52w_range"), 1),
        "mom_1m_pct": _number(row.get("mom_1m"), 1),
        "mom_3m_pct": _number(row.get("mom_3m"), 1),
        "vol20_annualized": _number(row.get("vol20_annualized"), 4),
        "atr14_pct": _number(row.get("atr14_pct"), 2),
        "close": _number(row.get("close"), 4),
        "ma20": _number(row.get("ma20"), 4),
        "prior_5d_high": _number(row.get("prior_5d_high"), 4),
        "prior_5d_low": _number(row.get("prior_5d_low"), 4),
        "prior_20d_high": _number(row.get("prior_20d_high"), 4),
        "prior_20d_low": _number(row.get("prior_20d_low"), 4),
        "zscore20": _number(row.get("zscore20"), 2),
        "chandelier_stop": _number(row.get("chandelier_stop"), 4),
        "stop_distance_pct": stop_distance,
        "stop_state": (
            "breached" if stop_distance is not None and stop_distance < 0
            else "intact" if stop_distance is not None
            else "unknown"
        ),
        "setups": setups,
        "usable": bool(row) and fresh,
    }


def _apply_setup_usage(technical: dict, usage: dict) -> dict:
    for setup in technical.get("setups") or []:
        used = int(usage.get(setup.get("campaign_id")) or 0)
        maximum = int(setup.get("max_tranches") or 1)
        setup["used_tranches"] = used
        setup["remaining_tranches"] = max(0, maximum - used)
        setup["next_tranche_number"] = used + 1 if used < maximum else None
    return technical


def _history_view(context: dict, ticker: str) -> dict:
    """How this ticker's own past calls turned out, as the writer can see it.

    `compute_reflections` settles every episode for a held ticker into a win
    rate, a per-bucket tally (`加×1 胜0; 持×15 胜9`) and the last three calls
    with their realised benefit. It has run every morning since the reflections
    step existed — and it went nowhere a decision could read it. SKILL.md
    Step 2 makes the packet summary the model's *only standing input*
    ("bundle 是审计深钻，不是默认模型输入"), and the packet carried no per-ticker
    outcome history at all: the process writing today's call on CRCL could not
    see that the last 17 calls on CRCL won 59%, and that the one time it added,
    it lost.

    That is the shape #1337 fixed for the add side — a signal that exists,
    is even visible on the dashboard, and has no path into the process that
    writes decisions.

    The last three calls (`recent`) are deliberately NOT projected either, and
    the reason is a measurement: the packet baseline is 94,071 of 98,304 bytes,
    so the whole block has ~4.2KB to live in. Carrying `recent` cost 3,868 and
    landed 295 bytes under a cap whose overrun is a hard `ValueError` — one more
    holding and the morning brief gets no packet at all, which is the 2026-08-17
    failure verbatim. The three tallies below cost 936 bytes for the same
    decision: what the model needs at write time is "how have my calls on this
    name gone, and in which buckets", and the blow-by-blow is audit depth, which
    is what the bundle is for.

    `lesson` is deliberately NOT projected. It is a pre-written sentence
    ("主动 call 多半没跑赢持有，本次谨慎") and this module's contract is that code
    owns facts and the model owns the opinion overlay. Handing the model a
    finished conclusion is the one thing the packet boundary exists to prevent;
    the numbers it was derived from are all here.
    """
    row = (context.get("reflections") or {}).get(ticker) or {}
    if not row:
        # Emitted even when empty: "this ticker has no settled episodes yet" and
        # "history was never wired in" must not look the same to a reader.
        return {"settled_episodes": 0}
    return {
        "settled_episodes": row.get("n"),
        "win_rate": row.get("win_rate"),
        "by_action": row.get("bucket_history"),
    }


def _thesis_view(context: dict, ticker: str) -> dict:
    row = (((context.get("thesis_registry") or {}).get("theses") or {})
           .get(ticker) or {"status": "unknown"})
    return {
        "status": row.get("status") or "unknown",
        "thesis_id": row.get("thesis_id"),
        "state": row.get("state") or "unknown",
        "checked_at": row.get("checked_at"),
    }


EXPLORATION_TIERS = add_policy.EXPLORATION_TIERS
# Bound here because several functions below take the loaded policy dict as a
# parameter named `add_policy`, which hides the module inside them.
is_authorised_tier = add_policy.is_authorised_tier
READ_DEFAULTS = add_policy.READ_DEFAULTS
TARGET_TRANCHE_LEVEL = add_policy.TARGET_TRANCHE_LEVEL


def _execution_view(holding: dict, leg: str, capital: float, cash: float,
                    technical: dict, thesis: dict, leveraged: bool,
                    authority_tier: str = "none",
                    exploration_max_book_pct: float = 0.03,
                    overlay: dict | None = None,
                    open_add: bool = False) -> dict:
    price = _number(holding.get("current_price"), 4)
    shares = int(_number(holding.get("shares"), 0) or 0)
    current_value = _number(holding.get("current_value"), 2)
    if current_value is None and price is not None:
        current_value = price * shares

    # The current brokerage ledger is integer-share only in the US. HK requires
    # the live board lot fetched with the quote; missing lot metadata blocks an
    # add rather than silently treating one share as one lot.
    raw_lot = holding.get("lot_size") if leg == "HK" else 1
    try:
        lot = int(raw_lot) if raw_lot is not None else None
    except (TypeError, ValueError):
        lot = None
    if lot is not None and lot <= 0:
        lot = None

    setup_pcts = [
        row.get("tranche_pct_of_position")
        for row in technical.get("setups") or []
        if row.get("tranche_pct_of_position")
    ]
    overlay = overlay or {}
    plan = add_policy.tranche_plan(
        tier=authority_tier, price=price, lot=lot, shares=shares,
        current_value=current_value, capital=capital, cash=cash,
        setup_pcts=setup_pcts,
        sizing_multiplier=float(overlay.get("sizing_multiplier") or 1.0),
        exploration_max_book_pct=exploration_max_book_pct,
    )
    target_max_pct = plan["target_max_pct"]
    position_room_shares = plan["position_room_shares"]
    desired = plan["desired_shares"]
    suggested = plan["suggested_shares"]
    max_tranche_shares = suggested

    # The canonical thesis registry is a KILL SWITCH, not a licence. Only the
    # first branch changes a number; `intact` and `exploration_only` size
    # identically, and saying so plainly matters because the line that used to
    # sit under `exploration_only` was `min(max_tranche_shares, suggested)` —
    # applied one statement after `max_tranche_shares = suggested`, i.e. a
    # no-op — under a comment claiming it stopped pyramiding. Pyramiding is
    # stopped by the campaign's own `max_tranches` (1 for exploration), which is
    # where it has always actually been enforced. A restriction that lives only
    # in a comment is worse than no restriction: the next reader budgets for it.
    thesis_state = thesis.get("state") or "unknown"
    if thesis_state in {"broken", "damaged", "weakening"}:
        thesis_gate = "blocked"
        max_tranche_shares = suggested = 0
    elif thesis_state == "intact":
        thesis_gate = "intact"
    else:
        # No canonical thesis. Not treated as intact, but it costs nothing here:
        # a name with no thesis is sized by its evidence tier like any other.
        thesis_gate = "exploration_only"

    blockers = []
    if leveraged and authority_tier != "validated":
        blockers.append("leveraged_requires_validated_evidence")
    if open_add:
        blockers.append("open_add_order")
    if leg == "HK" and lot is None:
        blockers.append("board_lot_missing")
    if not technical.get("setups"):
        blockers.append("no_approved_setup")
    if not price:
        blockers.append("price_missing")
    if max_tranche_shares <= 0:
        blockers.append(
            "tranche_below_market_unit"
            if position_room_shares > 0 and desired < (lot or 1)
            else "no_cash_or_target_room"
        )
    return {
        "order_unit": "board_lot" if leg == "HK" else "integer_share",
        "lot_size": lot,
        "fractional_shares_supported": False,
        "min_tranche_shares": lot,
        "suggested_tranche_shares": suggested,
        "max_tranche_shares": max_tranche_shares,
        # max_add_* is the authority for this decision, while position_room_*
        # only records the wider concentration/cash envelope.  Conflating the
        # two lets an authored plan spend every future tranche at once.
        "max_add_shares": max_tranche_shares,
        "position_room_shares": position_room_shares,
        "max_add_value": round(max_tranche_shares * price, 2) if price else 0,
        "exploration_budget_value": plan["exploration_budget_value"],
        "position_room_value": (
            round(position_room_shares * price, 2) if price else 0
        ),
        "target_max_pct": target_max_pct,
        "thesis_gate": thesis_gate,
        "information_overlay": overlay,
        "blockers": sorted(set(blockers)),
    }


def _factor_view(row: dict) -> dict:
    row = row if isinstance(row, dict) else {}
    return {
        "as_of": row.get("feature_as_of"),
        "sector": row.get("sector"),
        "composite_score": _number(row.get("composite_score"), 4),
        "market_percentile": _number(row.get("market_percentile"), 4),
        "sector_universe_size": int(row.get("sector_universe_size") or 0),
        "coverage_pct": _number(row.get("factor_coverage_pct"), 1),
        "relative_strength": _number(row.get("relative_strength"), 4),
        "breadth": _number(row.get("breadth"), 4),
        "membership_history_complete": bool(
            row.get("membership_history_complete")
        ),
        "usable_for_decisions": bool(row.get("usable_for_decisions")),
    }


def _peer_view(row: dict) -> dict:
    row = row if isinstance(row, dict) else {}
    return {
        "as_of": row.get("feature_as_of"),
        "sector_regime": row.get("sector_regime"),
        "residual_1d": _number(row.get("residual_blend_1d"), 4),
        "residual_5d": _number(row.get("residual_blend_5d"), 4),
        "residual_20d": _number(row.get("residual_blend_20d"), 4),
        "dispersion_5d": _number(row.get("peer_dispersion_5d"), 4),
        "leadership_persistence": row.get("leadership_persistence"),
        "laggard_persistence": row.get("laggard_persistence"),
        "available_peer_count": int(row.get("available_peer_count") or 0),
        "triggered_rules": list(row.get("triggered_rules") or []),
        "usable_rules": list(row.get("usable_rules") or []),
        "usable_for_decisions": bool(row.get("usable_for_decisions")),
    }


def _information_view(graph: dict, ticker: str, source_ticker: str) -> dict:
    overlay = graph.get("information_overlay") or {}
    rows = overlay.get("tickers") or {}
    row = rows.get(source_ticker) or rows.get(ticker) or {}
    return {
        "as_of": row.get("as_of") or overlay.get("as_of"),
        "source_ticker": source_ticker,
        "status": row.get("status") or overlay.get("status") or "missing",
        "signed_score": _number(row.get("signed_score"), 6),
        "cross_section_rank": _number(row.get("cross_section_rank"), 4),
        "own_surprise_z": _number(row.get("own_surprise_z"), 4),
        "event_count": int(row.get("event_count") or 0),
        "event_components": copy.deepcopy(row.get("event_components") or []),
        "attention_score": _number(row.get("attention_score"), 6),
        "attention_rank": _number(row.get("attention_rank"), 4),
        "attention_event_count": int(row.get("attention_event_count") or 0),
        "attention_acceleration": _number(
            row.get("attention_acceleration"), 4
        ),
        "attention_source_type_count": int(
            row.get("attention_source_type_count") or 0
        ),
        "attention_components": copy.deepcopy(
            row.get("attention_components") or []
        ),
        "sizing_tilt": row.get("sizing_tilt") or "inactive",
        "usable_for_decisions": bool(
            overlay.get("usable_for_decisions")
            and row.get("usable_for_decisions")
        ),
        "activation_blockers": list(
            ((overlay.get("activation") or {}).get("blockers") or [])
        ),
        # What would flip `usable_for_decisions`, as `{check: [actual, required]}`.
        # The blocker list names which check fails; this says how far off it is,
        # which is the difference between "blocked" and "blocked for another
        # thirteen sessions" (#1132).
        "activation_progress": {
            str(name): [check.get("actual"), check.get("required")]
            for name, check in sorted(
                ((overlay.get("activation") or {}).get("checks") or {}).items())
            if isinstance(check, dict)
        },
    }


def _add_alpha_policy(context: dict) -> dict:
    supplied = context.get("add_alpha_policy")
    if isinstance(supplied, dict) and supplied:
        return copy.deepcopy(supplied)
    return json.loads(ADD_ALPHA_POLICY.read_text(encoding="utf-8"))


def _left_side_policy(context: dict) -> dict:
    supplied = context.get("left_side_policy")
    if isinstance(supplied, dict) and supplied:
        return copy.deepcopy(supplied)
    return left_side.load_policy()


def _information_sizing_overlay(info: dict, factor: dict, peer: dict,
                                policy: dict) -> dict:
    multiplier = 1.0
    contributors = []
    if factor.get("usable_for_decisions"):
        score = factor.get("composite_score")
        if score is not None and score >= policy.get("factor_top_score", 0.25):
            multiplier *= policy.get("factor_top_multiplier", 1.15)
            contributors.append("factor_top")
        elif score is not None and score <= policy.get("factor_bottom_score", -0.25):
            multiplier *= policy.get("factor_bottom_multiplier", 0.75)
            contributors.append("factor_bottom")
    if peer.get("usable_for_decisions"):
        rules = set(peer.get("usable_rules") or [])
        if "laggard_avoidance" in rules:
            multiplier *= policy.get("peer_laggard_multiplier", 0.6)
            contributors.append("peer_laggard")
        elif "leader_continuation" in rules:
            multiplier *= policy.get("peer_leader_multiplier", 1.15)
            contributors.append("peer_leader")
        elif "mean_reversion" in rules:
            multiplier *= policy.get("peer_mean_reversion_multiplier", 1.1)
            contributors.append("peer_mean_reversion")
    if info.get("usable_for_decisions"):
        if info.get("sizing_tilt") == "positive":
            multiplier *= policy.get("information_positive_multiplier", 1.2)
            contributors.append("information_positive_surprise")
        elif info.get("sizing_tilt") == "negative":
            multiplier *= policy.get("information_negative_multiplier", 0.6)
            contributors.append("information_negative_or_low_rank")
    active = any(
        row.get("usable_for_decisions") for row in (info, factor, peer)
    )
    return {
        "sizing_active": active,
        "sizing_multiplier": round(min(
            policy.get("maximum_combined_multiplier", 1.5),
            max(policy.get("minimum_combined_multiplier", 0.5), multiplier),
        ), 4),
        "contributors": contributors,
        "discipline": "resizes an approved technical tranche; never creates add authority",
    }


def _mention_count(raw):
    """An int when one was measured, `None` when it was not.

    Deliberately not `int(raw or 0)`. A mention count of zero and a mention
    count that was never fetched are different facts, and the second one was
    published as the first for the whole life of the sentiment artifact (#1237).
    """
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _sentiment_view(rows: list[dict], ticker: str, source_ticker: str) -> dict:
    row = next(
        (
            item for item in rows
            if str(item.get("ticker")) in {ticker, source_ticker}
        ),
        {},
    )
    headlines = [
        str(item)[:240] for item in (row.get("news_top") or [])[:5] if item
    ]
    return {
        "as_of": row.get("as_of"),
        "source_ticker": row.get("ticker") or source_ticker,
        # `or 0` here told the model "nobody mentioned this name" whenever the
        # fetch had failed, which was every day for three months (#1237). The
        # count passes through as-is — `None` when it was not obtained — and the
        # status travels with it so the reader can tell silence from absence.
        "reddit_mentions_7d": _mention_count(row.get("reddit_mentions_7d")),
        "reddit_status": row.get("reddit_status") or ("ok" if row else "missing"),
        "recent_move": row.get("recent_move") if isinstance(row.get("recent_move"), dict) else {},
        "headline_count": len(headlines),
        "headlines": headlines,
        "coverage": "available" if row else "missing",
    }


def _event_view(event: dict) -> dict:
    view = {
        key: event.get(key)
        for key in (
            "event_id",
            "ticker",
            "reported_ticker",
            "event_type",
            "canonical_headline",
            "headline",
            "summary",
            "source_tier",
            "confidence_tier",
            "actionable_escalation",
            "actionable_reasons",
            "source_type", "primary_source", "direction",
        )
        if event.get(key) not in (None, "", [])
    }
    direction = event.get("direction", event.get("impact_direction"))
    if direction not in (None, "", []):
        view["direction"] = direction
    return view


def _adaptive_view(adaptive: dict | None) -> dict:
    """What the plan writer needs from the breach's adaptive state — and no more.

    The ledger keeps the full history (`stances`, anchors); the model gets the verdict,
    the evidence behind it, and the rails, so it can judge without re-deriving them.
    """
    adaptive = risk_ledger.adaptive_view(adaptive)
    if not adaptive.get("eligible"):
        return {"eligible": False,
                "not_eligible_because": adaptive.get("not_eligible_because") or [],
                # A respond-only cap files a choice from its first day.
                **({"recent_choices": adaptive["recent_choices"]}
                   if adaptive.get("recent_choices") else {})}
    return {
        key: adaptive.get(key)
        for key in ("eligible", "may_stand", "must_reissue", "must_reason", "stance",
                    "last_reissued_on", "days_since_reissue", "forced_on", "rearm_at")
    } | {"recent_choices": adaptive.get("recent_choices") or []}


def _risk_map(context: dict, active: set[str]) -> dict[str, list[dict]]:
    guardrail = context.get("risk_guardrail") or {}
    out = {ticker: [] for ticker in active}
    # A breach kcn declined on the record (`risk override --reason --ttl-hours`)
    # is exempt in postflight, and was still `forced` here: the packet allowed
    # only the cut, so the plan could not write the hold the override granted.
    overridden = {
        row.get("breach_id")
        for row in (context.get("risk_discipline") or {}).get("records") or []
        if risk_ledger.override_is_active(row)
    }
    for row in guardrail.get("breaches") or []:
        reduction = row.get("required_reduction") or {}
        targets = set(str(x) for x in reduction.get("target_tickers") or [])
        if row.get("ticker"):
            targets.add(str(row["ticker"]))
        for ticker in sorted(targets & active):
            out[ticker].append({
                "kind": "breach",
                # A portfolio breach still names the tickers whose exposure must
                # fall. Those members cannot add while the same breach is open;
                # unrelated names are not frozen.
                "scope": "ticker",
                "breach_id": row.get("breach_id"),
                "type": row.get("type"),
                # `forced`: the plan must sell. `respond`: the plan must answer
                # (a trim, or a hold with its reason) and may not add.
                "enforcement": ("forced" if risk_ledger.forces_action(row)
                                else "respond"),
                "severity": row.get("severity") or "high",
                "detail": row.get("detail"),
                "action_text": row.get("action"),
                # Standing-without-a-decision travels with the breach: the plan
                # writer is the one who can turn it into an execute, an
                # acknowledge or an override (#1075).
                "standing": row.get("standing") or {},
                "adaptive": _adaptive_view(row.get("adaptive")),
                "override_active": row.get("breach_id") in overridden,
                "required_reduction": {
                    key: reduction.get(key)
                    for key in (
                        "kind", "minimum_value", "minimum_shares", "currency",
                        "target_pct", "swap_to",
                    )
                    if reduction.get(key) is not None
                },
            })
    for row in guardrail.get("hard_stop_watch") or []:
        ticker = str(row.get("ticker") or "")
        if ticker not in active:
            continue
        reduction = row.get("required_reduction") or {}
        out[ticker].append({
            "kind": "hard_stop",
            "scope": "ticker",
            "breach_id": row.get("breach_id"),
            # The row's own name. This was the only surface that knew the type
            # was `leveraged_hard_stop` while the row it describes carried no
            # `type` at all — one name here, another in the rendered table, and
            # nothing citable in between.
            "type": row.get("type") or "leveraged_hard_stop",
            "enforcement": "forced",
            "severity": "critical",
            "detail": row.get("detail"),
            "action_text": row.get("action"),
            "standing": row.get("standing") or {},
            "adaptive": _adaptive_view(row.get("adaptive")),
            "override_active": row.get("breach_id") in overridden,
            "required_reduction": {
                key: reduction.get(key)
                for key in (
                    "kind", "minimum_value", "minimum_shares", "currency",
                    "target_pct", "swap_to",
                )
                if reduction.get(key) is not None
            },
        })
    return out


def _swap_mandates(risks: dict) -> dict:
    """Target ticker → the open breaches that require buying INTO it.

    A leveraged hard stop prescribes two legs, and says so in its own words:
    「07226 触发杠杆 ETF 硬止损 → 换仓 1x 同因子 03033（敞口保留、停 decay,
    **规则非择时**）」. Only the sell leg was ever expressible. `_constraints`
    gates every add on `bool(setup_ids)` — an approved technical setup — so the
    buy leg of a RULE was made conditional on TIMING, and the plan writer said
    so out loud on 2026-08-26: 「07226 砍完 swap 03033 路径被 packet add 限制
    阻挡 (allowed=[hold_and_watch, watch])」.

    Measured: 07226 / RKLX / SPCH have been told to cut 53 / 38 / 45 times with
    **zero** executions, and three hard stops have been open 42 days
    unacknowledged. Half a prescription is not a smaller version of the
    prescription — it is "sell and hold the cash", which is a different call
    that nobody made.

    CORRECTION (2026-08-26, same night): the first version of this docstring
    blamed an empty `memory/theses/` for the closed buy leg. That was wrong and
    is recorded here rather than quietly deleted, because the wrong version
    shipped. The swap targets were blocked by `no_approved_setup` — they carry
    no quant setup, which is ordinary for a name nobody is running an add
    campaign on — and the thesis registry has nothing to do with it. The add
    side at large is NOT shut: it is gated on `add_authority.tier`, which on the
    same day rated CRCL `eligible`. What is true is narrower and is exactly what
    this function fixes: a RULE's buy leg must not be gated on a TIMING artifact
    at all.
    """
    out: dict[str, list[dict]] = {}
    for source, rows in (risks or {}).items():
        for row in rows or []:
            reduction = row.get("required_reduction") or {}
            target = str(reduction.get("swap_to") or "")
            if not target or target == str(source):
                continue
            out.setdefault(target, []).append({
                "from_ticker": str(source),
                "breach_id": row.get("breach_id"),
                "kind": row.get("kind"),
                "severity": row.get("severity"),
                "detail": row.get("detail"),
                "action_text": row.get("action_text"),
                "max_value": reduction.get("minimum_value"),
                "currency": reduction.get("currency"),
            })
    return out


def _swap_mandate_view(mandates: list[dict], risks: list[dict]) -> dict | None:
    """The authorisation this ticker carries as a swap TARGET, or None.

    Refused when the target is itself breaching: the rule moves exposure out of
    a broken leg into an intact one, so buying into a second breach would
    satisfy the letter of the swap while making the book worse.
    """
    if not mandates or risks:
        return None
    ranked = sorted(
        mandates,
        key=lambda m: (m.get("severity") != "critical", str(m.get("from_ticker"))),
    )
    primary = ranked[0]
    return {
        "authorised_by": "risk_rule",
        "from_ticker": primary["from_ticker"],
        "breach_id": primary.get("breach_id"),
        "severity": primary.get("severity"),
        "max_value": primary.get("max_value"),
        "currency": primary.get("currency"),
        # The two legs are one transaction. `decision_audit`'s swap pairing
        # already refuses to pair cross-ticker legs without it
        # (`swap_pairing_requires_transaction_group_id`), so a buy leg filed
        # without one is measured as a naked buy against the wrong baseline.
        "requires_transaction_group_id": True,
        # Named, not free: the mandate authorises buying THIS ticker because a
        # specific breach names it, and nothing else.
        "requires_action": "add_only_on_trigger",
        "all_mandates": ranked,
    }


def _swap_target_rows(swap_mandates: dict, held: set, context: dict,
                      quant_rows: dict) -> dict:
    """A minimal row for each swap target the book does not hold.

    `tickers` is the holdings, so a prescription into a name that was cleared
    (RKLX → RKLB, 10 packets running) had no row and its buy leg was refused as
    "outside current decision packet": the only writable half of the swap was
    the sell (#2839). These rows carry what the buy leg is judged by — a price,
    the order unit and the mandate — and nothing a holding's row implies: no
    technical setup, no add budget, no judgment slot.

    The price is a quote preflight fetched for this purpose, else the last
    completed session's close from the quant table; either way its basis and
    date are stated, and a leg written against no price at all is refused by
    `_swap_leg_issues`.
    """
    quotes = context.get("unheld_quotes") or {}
    rows = {}
    for target, mandates in sorted(swap_mandates.items()):
        if target in held:
            continue
        leg = "HK" if target.isdigit() else "US"
        quote = quotes.get(target) or {}
        bar = quant_rows.get(target) or {}
        price, basis, as_of = _number(quote.get("price"), 4), "quote", quote.get("as_of")
        if not price:
            fresh = bar.get("status") in (None, "fresh")
            price = _number(bar.get("close"), 4) if fresh else None
            basis, as_of = "last_close", bar.get("row_as_of")
        if not price:
            price, basis, as_of = None, None, None
        lot = 1 if leg == "US" else quote.get("lot_size")
        rows[target] = {
            "ticker": target,
            "name": quote.get("name") or "",
            "leg": leg,
            "held": False,
            "facts": {
                "shares": 0,
                "current_price": price,
                "price_basis": basis,
                "price_as_of": as_of,
            },
            "risk": [],
            "constraints": {
                "allowed_actions": ["add_only_on_trigger"],
                "open_actions": ["add_only_on_trigger"],
                "closed_actions": {},
                "forced_action_one_of": [],
                "max_sell_shares": 0,
                "swap_mandate": _swap_mandate_view(mandates, []),
                "max_add_shares": 0,
                "technical_setup_ids": [],
                "order_unit": "board_lot" if leg == "HK" else "integer_share",
                "lot_size": lot,
            },
        }
    return rows


#: A stored bar older than this many calendar days does not price a proposal.
UNIVERSE_MAX_BAR_AGE_DAYS = 7
ENTRY_GATE_REQUIRED = "entry_gate_required"


def _proposal_universe(context: dict, held: set) -> dict:
    """Names the book does not hold that a plan may still propose buying.

    A proposal has to be evaluable, so the universe is exactly the names with
    stored daily bars (`context.proposal_universe`, read by preflight from
    `memory/bars`): those are the ones settlement can score. Each row carries
    the last completed close with its date, the order unit, and the standing
    fact that the name has not been through the entry gate — an authorisation
    still pending, printed with the proposal, not a reason to refuse it.

    There is no setup, tier or candidate state here: which unheld name is
    worth proposing is the model's question.
    """
    quotes = context.get("unheld_quotes") or {}
    today = str(context.get("date") or "")
    rows = {}
    for ticker, bar in sorted((context.get("proposal_universe") or {}).items()):
        if ticker in held or not isinstance(bar, dict):
            continue
        leg = str(bar.get("leg") or ("HK" if ticker.isdigit() else "US"))
        quote = quotes.get(ticker) or {}
        price, basis, as_of = _number(quote.get("price"), 4), "quote", quote.get("as_of")
        if not price:
            price, basis, as_of = _number(bar.get("close"), 4), "last_close", bar.get("session")
        try:
            age = (date.fromisoformat(today) - date.fromisoformat(str(as_of))).days
        except (TypeError, ValueError):
            age = None
        if not price or age is None or age > UNIVERSE_MAX_BAR_AGE_DAYS:
            continue
        lot = 1 if leg == "US" else quote.get("lot_size")
        closed = {}
        open_actions = ["watch"]
        if lot:
            open_actions.append("add_only_on_trigger")
        else:
            closed["add_only_on_trigger"] = {
                "channel": receipts.FEASIBILITY, "code": "FEAS_BOARD_LOT_UNKNOWN",
                "reason": "the board lot of this unheld name was not fetched"}
        rows[ticker] = {
            "ticker": ticker,
            "leg": leg,
            "held": False,
            "facts": {"shares": 0, "current_price": price,
                      "price_basis": basis, "price_as_of": as_of},
            "risk": [],
            "evidence": [],
            "constraints": {
                "allowed_actions": ["watch"],
                "open_actions": open_actions,
                "closed_actions": closed,
                "forced_action_one_of": [],
                "max_sell_shares": 0,
                "max_add_shares": 0,
                "technical_setup_ids": [],
                "actionable_evidence_ids": [],
                "lot_size": lot,
                "authorization": ENTRY_GATE_REQUIRED,
            },
        }
    return rows


def decision_row(packet: dict, ticker) -> dict | None:
    """The row a plan decision on `ticker` is judged against: a holding's, that
    of a swap target the book does not hold, or an unheld name's in the
    proposal universe."""
    return ((packet.get("tickers") or {}).get(str(ticker))
            or (packet.get("swap_targets") or {}).get(str(ticker))
            or (packet.get("proposal_universe") or {}).get(str(ticker)))


def _status(technical: dict, risks: list[dict]) -> dict:
    if any(item.get("kind") == "hard_stop" for item in risks):
        return {"rank": 0, "label": "止损/换1x", "state": "critical"}
    if any(item.get("enforcement") != "respond" for item in risks):
        return {"rank": 1, "label": "减仓", "state": "elevated"}
    if risks:
        return {"rank": 1, "label": "超限", "state": "elevated"}
    if technical.get("trend") == "on":
        return {"rank": 4, "label": "趋势ON", "state": "positive"}
    if technical.get("rsi_state") == "oversold":
        return {"rank": 2, "label": "超卖·观望", "state": "elevated"}
    if technical.get("usable") and technical.get("trend") == "unknown":
        return {"rank": 3, "label": "趋势未知·短历史", "state": "neutral"}
    if technical.get("usable"):
        return {"rank": 3, "label": "趋势off·观望", "state": "neutral"}
    return {"rank": 5, "label": "数据不足", "state": "neutral"}


def _open_envelope(shares: int, risks: list[dict], forced: list[str],
                   execution: dict, swap_mandate: dict | None) -> tuple[list, dict]:
    """The actions a plan may write for a holding, and why the rest are closed.

    Three things close an action, and none of them is a registered rule's
    opinion: an obligation in force (`forced`), an authorisation kcn has not
    given (adding to a breaching name, adding to a leveraged product without
    validated evidence) and plain feasibility (no board lot, no price, no cash
    or concentration room for one unit, an add already open). Whether the
    policy would have picked the action is `allowed_actions` and is judged
    separately, as an objection.
    """
    every = ("hold_and_watch", "watch", "trim_on_rebound", "cut", "t_only",
             "add_only_on_trigger", "add_on_breakout")
    if forced:
        why = {"channel": receipts.FEASIBILITY, "code": "AUTH_OBLIGATION_IN_FORCE",
               "reason": "an obligation in force on this name requires "
                         + " or ".join(forced)}
        return list(forced), {action: why for action in every if action not in forced}
    open_actions, closed = ["hold_and_watch", "watch"], {}
    no_inventory = {"channel": receipts.FEASIBILITY, "code": "FEAS_NOTHING_TO_SELL",
                    "reason": "the book holds no shares of this name"}
    if shares > 0:
        open_actions += ["trim_on_rebound", "cut"]
    else:
        closed.update({action: no_inventory for action in ("trim_on_rebound", "cut", "t_only")})
    blockers = set(execution.get("blockers") or [])
    unit = execution.get("lot_size") or 1
    if risks:
        add_closed = ("AUTH_ADD_FROZEN_BY_BREACH",
                      "adds are frozen while a risk breach is open on this name")
    elif "leveraged_requires_validated_evidence" in blockers:
        add_closed = ("AUTH_LEVERAGED_ADD",
                      "adding to a leveraged product needs validated evidence")
    elif "open_add_order" in blockers:
        add_closed = ("FEAS_ADD_ALREADY_OPEN", "an earlier add on this name is still open")
    elif "board_lot_missing" in blockers:
        add_closed = ("FEAS_BOARD_LOT_UNKNOWN", "the board lot is unknown")
    elif "price_missing" in blockers:
        add_closed = ("FEAS_PRICE_MISSING", "there is no price to size against")
    elif (execution.get("position_room_shares") or 0) < unit:
        add_closed = ("FEAS_NO_ROOM",
                      "no cash or concentration room for one tradable unit")
    else:
        add_closed = None
    if add_closed is None:
        open_actions += (["t_only"] if shares > 0 else []) + [
            "add_only_on_trigger", "add_on_breakout"]
    else:
        why = {"channel": receipts.FEASIBILITY, "code": add_closed[0],
               "reason": add_closed[1]}
        closed.update({action: why for action in ("add_only_on_trigger", "add_on_breakout")})
        if shares > 0:
            if risks:
                closed["t_only"] = why
            else:
                open_actions.append("t_only")
    if swap_mandate and "add_only_on_trigger" not in open_actions:
        open_actions.append("add_only_on_trigger")
    return open_actions, closed


def _constraints(shares: int, risks: list[dict], actionable_ids: list[str],
                 technical: dict, execution: dict,
                 swap_mandates: list[dict] | None = None) -> dict:
    # A breach the book has kept declining may stand (risk.py `_adaptive`): the plan
    # writer chooses between raising it again and holding, and only the breaches that
    # are NOT allowed to stand still force an action.
    # So may a breach under a durable, unexpired override: declining it was kcn's
    # decision, and it is the same freedom with a different author.
    # And a cap with no destination never forces (`risk.RESPOND_ONLY_TYPES`):
    # the plan answers it, with a trim or with a hold and its reason.
    loud = [row for row in risks
            if row.get("enforcement") != "respond"
            and not (row.get("adaptive") or {}).get("may_stand")
            and not row.get("override_active")]
    hard_stop = any(row.get("kind") == "hard_stop" for row in loud)
    direct_risk = bool(risks)
    if hard_stop:
        allowed = ["cut"]
        forced = ["cut"]
    elif loud:
        allowed = ["trim_on_rebound", "cut"]
        forced = ["trim_on_rebound", "cut"]
    elif direct_risk:
        # Every breach on this name may stand or only asks for an answer. Adds stay
        # shut — `can_add` below still reads `risks` — so holding never turns into
        # buying more of a breach.
        allowed = ["hold_and_watch", "watch", "trim_on_rebound", "cut"]
        forced = []
    else:
        allowed = ["hold_and_watch", "watch"]
        forced = []
        if risks:
            allowed += ["trim_on_rebound", "cut"]
    if actionable_ids and not risks:
        allowed += [
            "trim_on_rebound", "cut", "t_only",
        ]
    setup_ids = [
        row.get("setup_id") for row in technical.get("setups") or []
        if (row.get("remaining_tranches") or 0) > 0
    ]
    can_add = (
        not risks
        and not execution.get("blockers")
        and execution.get("thesis_gate") in {"intact", "exploration_only"}
        and (execution.get("max_add_shares") or 0) > 0
        and bool(setup_ids)
    )
    if can_add:
        allowed += ["add_only_on_trigger"]
        if "confirmed_breakout" in setup_ids:
            allowed += ["add_on_breakout"]
    # The buy leg of a hard-stop swap is authorised by the RULE, not by timing:
    # it needs no setup, no thesis and no add authority, because the exposure it
    # buys is exposure the book already holds in a decaying wrapper. See
    # _swap_mandates for why gating it on `setup_ids` closed it permanently.
    swap_mandate = _swap_mandate_view(swap_mandates or [], risks)
    if swap_mandate:
        allowed += ["add_only_on_trigger"]
    open_actions, closed_actions = _open_envelope(
        shares, risks, forced, execution, swap_mandate)
    return {
        # What the registered policy would do. Departing from it is an
        # objection on the record, not a refusal (`review_plan`).
        "allowed_actions": list(dict.fromkeys(allowed)),
        # What can be written at all: obligations, explicit authorisations
        # and feasibility. Nothing here is a view about the market.
        "open_actions": open_actions,
        "closed_actions": closed_actions,
        "forced_action_one_of": forced,
        # Caps the plan has to answer by name: a decision on this ticker whose
        # rationale says why it trims or why it holds.
        "respond_to_breach_ids": [
            row.get("breach_id") for row in risks
            if row.get("enforcement") == "respond" and not row.get("override_active")
            and row.get("breach_id")
        ],
        "max_sell_shares": shares,
        "active_action_requires_evidence": True,
        "actionable_evidence_ids": actionable_ids,
        "technical_setup_ids": setup_ids,
        "swap_mandate": swap_mandate,
        "max_add_shares": execution.get("max_add_shares", 0),
        "position_room_shares": execution.get("position_room_shares", 0),
        "max_add_value": execution.get("max_add_value", 0),
        "target_max_pct": execution.get("target_max_pct"),
        "min_tranche_shares": execution.get("min_tranche_shares"),
        "lot_size": execution.get("lot_size"),
    }


def _peer_rules_state(rule_activation: dict) -> tuple[bool, bool]:
    """(active, usable_for_decisions) of the peer family.

    `peer_residual` publishes `rule_activation` keyed by rule
    (`leader_continuation`, `laggard_avoidance`, `mean_reversion`, each with
    its own `active`). Reading a top-level `active` from that dict was always
    False, so the peer family stayed "warming" forever and cold start could
    never retire (cloud review F15; the tests fed an invented flat shape). The
    family is active when any rule is — that rule can fire. A flat legacy
    shape is still honoured.
    """
    rule_activation = rule_activation or {}
    if "active" in rule_activation or "usable_for_decisions" in rule_activation:
        return (bool(rule_activation.get("active")),
                bool(rule_activation.get("usable_for_decisions")))
    rules = [row for row in rule_activation.values() if isinstance(row, dict)]
    return (any(bool(row.get("active")) for row in rules),
            any(bool(row.get("usable_for_decisions")) for row in rules))


def add_alpha_activation(context: dict) -> dict:
    """Where each add-side evidence family is in its warm-up, from its own counters.

    Read from the three producers rather than from a date: `cross_sectional_factor`
    and `peer_residual` publish their own activation checks, and the news evidence
    graph publishes its `history_dates` / `cross_section_tickers` progress. On
    2026-09-05 that was factor 8/24, information 16/24, peer missing dates and
    signed_residual_ci — two of three families structurally unable to fire, which
    is why "any two families" behaved like "a breakout is mandatory".
    """
    factor_act = (context.get("cross_sectional_factor") or {}).get("activation") or {}
    peer_act = (context.get("peer_residual") or {}).get("rule_activation") or {}
    info_act = (
        ((context.get("news_evidence_graph") or {}).get("information_overlay") or {})
        .get("activation") or {}
    )

    def _progress(checks):
        out = {}
        for name, check in (checks or {}).items():
            if isinstance(check, dict) and "actual" in check:
                out[name] = [check.get("actual"), check.get("required")]
        return out

    families = {
        "price_relative_factor": {
            "active": bool(factor_act.get("active")),
            "usable_for_decisions": bool(factor_act.get("usable_for_decisions")),
            "progress": _progress(factor_act.get("checks")),
            "blockers": list(factor_act.get("blockers") or []),
        },
        "price_relative_peer": {
            "active": _peer_rules_state(peer_act)[0],
            "usable_for_decisions": _peer_rules_state(peer_act)[1],
            "blockers": sorted({
                blocker
                for rule in peer_act.values() if isinstance(rule, dict)
                for blocker in (rule.get("blockers") or [])
            }) or list(peer_act.get("blockers") or []),
        },
        "point_in_time_information": {
            "active": bool(info_act.get("active")),
            "progress": _progress(info_act.get("checks")),
            "blockers": list(info_act.get("blockers") or []),
        },
    }
    warming = sorted(name for name, row in families.items() if not row["active"])
    return {"families": families, "warming_up": warming, "cold_start": bool(warming)}


def _live_rows(context: dict, ticker: str) -> list:
    """This ticker's live headlines/disclosures (`clawock live-sources`, run by
    the brief preflight): the bounded summary rows, each with its own cite."""
    live = context.get("live_information") or {}
    for market in ("hk", "us"):
        rows = ((live.get(market) or {}).get("summary") or {}).get(ticker)
        if rows:
            return rows
    return []


def _live_health(context: dict) -> dict:
    """Per market: when the live sources were read, each source's status and
    what did not answer — so a gap reads as a gap, never as "no news"."""
    live = context.get("live_information") or {}
    return {
        market: {
            "as_of": (live.get(market) or {}).get("as_of"),
            "sources": {name: row.get("status") for name, row in
                        ((live.get(market) or {}).get("sources") or {}).items()},
            "degraded": list((live.get(market) or {}).get("degraded") or []),
        }
        for market in ("hk", "us") if market in live
    }


def _matching_events(events, ticker, source_ticker) -> list:
    return [
        _event_view(event) for event in events
        if str(event.get("ticker") or event.get("reported_ticker") or "")
        in {ticker, source_ticker}
    ]


def _ticker_rows(holdings, context, *, add_policy, alpha_activation, cash, cross_rows,
                 events, evidence_graph, invested, left_policy, open_add_gate_error,
                 open_adds, peer_rows, proxies, quant_rows, risks, sentiment_rows,
                 setup_usage, swap_mandates) -> dict:
    """One projected row per active holding: its views, authority and add state."""
    tickers = {}
    for leg, holding in holdings:
        ticker = str(holding.get("ticker"))
        source_ticker = ticker if ticker in quant_rows else proxies.get(ticker, ticker)
        technical = _apply_setup_usage(_technical(
            quant_rows.get(source_ticker) or {},
            source_ticker,
            source_ticker != ticker,
        ), setup_usage.get(ticker) or {})
        matching_events = _matching_events(events, ticker, source_ticker)
        actionable_ids = [
            event.get("event_id") for event in matching_events
            if event.get("actionable_escalation") and event.get("event_id")
        ]
        shares = int(_number(holding.get("shares"), 0) or 0)
        ticker_risks = risks.get(ticker) or []
        thesis = _thesis_view(context, ticker)
        factor_view = _factor_view(
            cross_rows.get(source_ticker) or cross_rows.get(ticker)
        )
        peer_view = _peer_view(
            peer_rows.get(source_ticker) or peer_rows.get(ticker)
        )
        information_view = _information_view(
            evidence_graph, ticker, source_ticker
        )
        sizing_policy = (
            (evidence_graph.get("information_overlay") or {})
            .get("sizing_policy") or {}
        )
        sizing_overlay = _information_sizing_overlay(
            information_view, factor_view, peer_view, sizing_policy
        )
        leveraged = is_leveraged_holding(holding)
        ticker_usage = setup_usage.get(ticker) or {}
        continuing_alpha = any(
            ":validated:" in str(campaign) and int(used or 0) > 0
            for campaign, used in ticker_usage.items()
        )
        alpha_authority = add_alpha.classify_authority(
            factor_view,
            peer_view,
            information_view,
            leveraged=leveraged,
            policy=add_policy,
            market=leg,
            continuing=continuing_alpha,
            # The decision lane never saw a price trend until #1086: the one
            # formation #856 measured positive at every horizon fed only the
            # intraday message.
            technical=technical,
            cold_start=alpha_activation["cold_start"],
        )
        if alpha_authority.get("tier") == "exploration":
            # A current-universe backfill can discover an interaction worth
            # collecting, but never upgrade itself into validated authority.
            alpha_authority["limitations"] = [
                "prospective_collection_only",
                "current_universe_survivorship_limit",
            ]
        early_candidate = early_trend.classify(
            technical, peer_view, information_view, matching_events,
            leveraged=leveraged, policy=add_policy, market=leg,
        )
        early_setup = early_trend.exploration_setup(
            technical, early_candidate, add_policy, ticker=ticker,
        )
        # The early lane can grant one exploration intent without changing the
        # mature factor×information authority classification.  Downstream risk,
        # cash, lot and open-order gates remain identical.
        execution_tier = alpha_authority.get("tier") or "none"
        if early_setup is not None and execution_tier == "none":
            execution_tier = "exploration"
        alpha_setup = add_alpha.confirmation_setup(
            technical, alpha_authority, add_policy, ticker=ticker
        )
        if alpha_setup is not None:
            technical["setups"].append(alpha_setup)
            technical = _apply_setup_usage(
                technical, ticker_usage
            )
        if early_setup is not None:
            technical["setups"].append(early_setup)
            technical = _apply_setup_usage(technical, ticker_usage)
        # Left side, observe mode (kcn 2026-09-27; evidence in `left_side`):
        # which gate would hold the ladder back, recorded for the forward
        # sample. It never joins `technical.setups`, so nothing here can size
        # or authorise an add. A stale bar row is no evidence of weakness.
        left_view = (left_side.observe(
            quant_rows.get(source_ticker) or {}, left_policy, leveraged=leveraged,
            thesis_state=thesis.get("state"),
            blockers=alpha_authority.get("blockers") or [])
            if technical.get("usable") else None)
        raw_exploration_book = add_policy.get("exploration_max_book_pct")
        execution = _execution_view(
            holding, leg, invested[leg], cash[leg], technical, thesis, leveraged,
            authority_tier=execution_tier,
            # #666: explicit None check, never `X or DEFAULT` — a config value
            # of 0 (`exploration_max_book_pct: 0` = 封死探索敞口) is legal and
            # must not be swallowed into the 0.03 default.
            exploration_max_book_pct=(
                float(raw_exploration_book)
                if raw_exploration_book is not None
                else READ_DEFAULTS["exploration_max_book_pct"]
            ),
            overlay=sizing_overlay,
            open_add=open_add_gate_error or ticker in open_adds,
        )
        tickers[ticker] = {
            "ticker": ticker,
            "name": holding.get("name") or holding.get("stock_name") or "",
            "leg": leg,
            "facts": {
                "shares": shares,
                "cost_basis": _number(holding.get("cost_basis"), 4),
                "current_price": _number(holding.get("current_price"), 4),
                "pnl_pct": _number(holding.get("pnl_percent"), 2),
                "today_change_pct": _number(holding.get("today_change_pct"), 2),
                "day_high": _number(holding.get("day_high"), 4),
                "day_low": _number(holding.get("day_low"), 4),
                "data_source": holding.get("data_source"),
            },
            "technical": technical,
            "thesis": thesis,
            "execution": execution,
            "quant": {
                "factor": factor_view,
                "peer_residual": peer_view,
                "add_authority": alpha_authority,
                "early_trend": early_candidate,
                **({"left_side": left_view} if left_view else {}),
                "activation": {
                    "factor": bool(
                        ((context.get("cross_sectional_factor") or {}).get("activation") or {})
                        .get("usable_for_decisions")
                    ),
                    "peer": _peer_rules_state(
                        (context.get("peer_residual") or {}).get("rule_activation") or {}
                    )[0],
                },
            },
            "sentiment": _sentiment_view(sentiment_rows, ticker, source_ticker),
            "history": _history_view(context, ticker),
            # Trimmed here, not in `_information_view`: the full view is what
            # `classify_authority` and `_information_sizing_overlay` above were
            # given, and stripping it earlier would quietly withdraw the add
            # authority those two grant.
            "information": {
                **_without_cold_components(information_view),
                # Added after authority and sizing were read from the view:
                # live items inform the judgment, they do not grant an add.
                "live": _live_rows(context, ticker),
            },
            "evidence": matching_events,
            "risk": ticker_risks,
            "status": _status(technical, ticker_risks),
            "constraints": _constraints(
                shares, ticker_risks, actionable_ids, technical, execution,
                swap_mandates.get(ticker) or [],
            ),
        }
    return tickers


def _candidate_state(tier, early, active_setup, execution, row, allowed) -> str:
    """One of the seven mutually exclusive add-candidate states, judged in this order."""
    if tier == "none" and early.get("observed"):
        state = early.get("state") or "candidate_only"
    elif tier == "none":
        state = "insufficient_evidence"
    elif active_setup is None:
        state = "waiting_timing"
    elif active_setup.get("remaining_tranches") == 0:
        state = "already_at_target"
    elif execution.get("blockers") or row.get("risk"):
        state = "risk_blocked"
    elif allowed:
        state = "eligible"
    else:
        state = "constraint_blocked"
    return state


def _candidate_rows(tickers: dict) -> tuple[list, dict, dict]:
    """The add-candidate state of every ticker row, with tier and blocker tallies."""
    tier_counts = {"validated": 0, "exploration": 0, "none": 0}
    blocker_counts = {}
    candidates = []
    for ticker, row in tickers.items():
        authority = ((row.get("quant") or {}).get("add_authority") or {})
        early = ((row.get("quant") or {}).get("early_trend") or {})
        tier = authority.get("tier") or "none"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        for blocker in authority.get("blockers") or []:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        setup = next(
            (
                item for item in (row.get("technical") or {}).get("setups") or []
                if item.get("setup_id") == "alpha_confirmation"
            ),
            None,
        )
        early_setup = next(
            (
                item for item in (row.get("technical") or {}).get("setups") or []
                if item.get("setup_id") == "early_trend_confirmation"
            ),
            None,
        )
        active_setup = setup or early_setup
        constraints = row.get("constraints") or {}
        execution = row.get("execution") or {}
        allowed = "add_only_on_trigger" in (constraints.get("allowed_actions") or [])
        early_ready = bool(early.get("exploration_ready"))
        state = _candidate_state(tier, early, active_setup, execution, row, allowed)
        candidates.append({
            "ticker": ticker,
            "leg": row.get("leg"),
            "source_ticker": (row.get("technical") or {}).get("source_ticker") or ticker,
            "is_proxy": bool((row.get("technical") or {}).get("is_proxy")),
            "state": state,
            "tier": tier,
            "target_tranche_level": (
                TARGET_TRANCHE_LEVEL["validated"] if tier == "validated"
                else TARGET_TRANCHE_LEVEL["exploration"] if early_ready
                else TARGET_TRANCHE_LEVEL.get(tier, 0.0)
            ),
            "sources": sorted(set(
                list(authority.get("sources") or [])
                + (["early_trend", "information"] if early_ready else [])
            )),
            "evidence_families": sorted(set(
                list(authority.get("evidence_families") or [])
                + (list(early.get("evidence_families") or []) if early_ready else [])
            )),
            "authority_blockers": list(authority.get("blockers") or []),
            "entry_price": (active_setup or {}).get("entry_price"),
            "invalidation_price": (active_setup or {}).get("invalidation_price"),
            "max_add_shares": constraints.get("max_add_shares"),
            "allowed": allowed,
            "execution_blockers": list(execution.get("blockers") or []),
            "early_trend": early,
        })
    return candidates, tier_counts, blocker_counts


def _warn_read_budgets(packet: dict) -> None:
    """Say on stderr which model-facing reads are near or over their budget.

    Never refuses the packet. The reads refuse at their own budget when they are
    made (`bounded_payload`); a compile that raised instead would take the audit
    context and every in-budget read down with the one that overran.
    """
    report = read_budget_report(packet)
    for row in report["reads"]:
        if not (row["near_budget"] or row["over_budget"]):
            continue
        print(f"warn: decision packet read `{row['read']}` at {row['bytes']} bytes is "
              f"{row['ratio']:.1%} of its {row['budget']}-byte budget "
              f"({report['tickers']} tickers) — "
              + ("the tool refuses this read as it stands"
                 if row["over_budget"] else
                 "trim a projection or move reference detail behind a query "
                 "before the next holding lands"),
              file=sys.stderr)


def _book_totals(portfolios: dict) -> tuple[dict, dict]:
    """Invested value and cash per leg, in the leg's own currency."""
    invested = {
        "HK": sum(
            float(h.get("current_value") or 0)
            for h in (portfolios.get("hk_stocks") or {}).get("holdings") or []
            if (_number(h.get("shares")) or 0) > 0
        ),
        "US": sum(
            float(h.get("current_value") or 0)
            for h in (portfolios.get("us_stocks") or {}).get("holdings") or []
            if (_number(h.get("shares")) or 0) > 0
        ),
    }
    cash = {
        "HK": float((portfolios.get("hk_stocks") or {}).get("cash_hkd") or 0),
        "US": float((portfolios.get("us_stocks") or {}).get("cash_usd") or 0),
    }
    return invested, cash


def _packet_payload(context, generation_id, *, add_policy, alpha_activation, blocker_counts, candidates, cash, swap_mandates, swap_targets, tickers, tier_counts) -> dict:
    """The packet literal: every section the brief reads, in its published key order."""
    return {
        "_meta": {
            "schema_version": SCHEMA_VERSION,
            "kind": "brief_decision_packet",
            "generation_id": generation_id,
        },
        "stock_discovery": context.get("stock_discovery") or {},
        "date": context.get("date"),
        "generated_at": context.get("generated_at"),
        "integrity": {
            key: (context.get("integrity") or {}).get(key)
            for key in ("ok", "error_count", "warn_count")
            if key in (context.get("integrity") or {})
        },
        "portfolio": {
            "book_totals": context.get("book_totals") or {},
            # Cash per leg in its own currency: what a plan's adds are held to.
            "cash_available": {leg: _number(value, 2) for leg, value in sorted(cash.items())},
            "concentration": context.get("concentration") or {},
            "risk_directive": (context.get("risk_guardrail") or {}).get("directive"),
            "regime": {
                "hk": (
                    ((context.get("risk_guardrail") or {}).get("lev_regime") or {})
                    .get("hk", {})
                    .get("tier")
                ),
                "us": (
                    ((context.get("risk_guardrail") or {}).get("lev_regime") or {})
                    .get("us", {})
                    .get("tier")
                ),
            },
        },
        "tickers": tickers,
        "live_information": _live_health(context),
        "judgment_contract": {
            "schema_version": JUDGMENT_SCHEMA_VERSION,
            "verdicts": sorted(VERDICTS),
            "dispositions": sorted(DISPOSITIONS),
            "model_owned_fields": [
                "verdict", "confidence", "disposition", "assessment",
                "counterargument", "rationale", "falsifier", "next_evidence",
            ],
            "harness_owned_fields": [
                "facts", "technical", "quant", "sentiment collection",
                "evidence IDs", "risk", "status", "constraints",
            ],
            # Harness-owned is not the same as measured (#2843). These are the
            # parts of a row where a registered rule already drew a conclusion:
            # true as a record of what the rule said, arguable as a reading of
            # the market. Everything else in a row is a measurement or a record.
            "rule_outputs": {
                "technical": ["tag", "trend", "rsi_state", "stop_state", "setups"],
                "quant.factor": ["composite_score", "market_percentile",
                                 "usable_for_decisions"],
                "quant.peer_residual": ["triggered_rules", "usable_rules",
                                        "usable_for_decisions"],
                "quant": ["add_authority", "early_trend", "left_side"],
                "information": ["signed_score", "attention_score", "sizing_tilt",
                                "usable_for_decisions"],
                "status": ["label", "state", "rank"],
                "how_to_read": (
                    "weigh them, depart from them when the observations say "
                    "otherwise, and name the departure; `clawock tool observations` "
                    "returns the measurements underneath and `clawock tool compute` "
                    "computes a feature you define"),
            },
        },
        "add_alpha_policy": {
            **{
                key: add_policy.get(key)
                for key in (
                    "schema_version", "registered_at", "minimum_evidence_families",
                    "confirmation_window_sessions", "exploration_max_tranches",
                    "exploration_tranche_pct", "validated_max_tranches",
                    "exploration_max_book_pct", "early_peer_dispersion_multiple",
                    "early_no_chase_zscore",
                    "validated_tranche_pct", "markets", "discipline",
                )
            },
            # Stated once for the packet instead of once per holding (#1086).
            "authority_discipline": add_alpha.AUTHORITY_DISCIPLINE,
        },
        "add_alpha_diagnostics": {
            # Why the count of authorised names is what it is. Without this a
            # zero reads as "nothing qualified" when it means "two of the three
            # families are still collecting their first 24 prospective dates".
            "activation": alpha_activation,
            "held_names": len(tickers),
            "tier_counts": tier_counts,
            "candidate_count": len(candidates),
            "authority_candidate_count": sum(
                row["tier"] in {"exploration", "validated"} for row in candidates
            ),
            "cold_start_candidate_count": sum(
                row["tier"] == "exploration_cold_start" for row in candidates
            ),
            "allowed_candidate_count": sum(bool(row["allowed"]) for row in candidates),
            "observed_candidate_count": sum(
                bool((row.get("early_trend") or {}).get("observed"))
                or is_authorised_tier(row["tier"])
                for row in candidates
            ),
            "observed_idea_count": len({
                row.get("source_ticker") or row["ticker"]
                for row in candidates
                if bool((row.get("early_trend") or {}).get("observed"))
                or is_authorised_tier(row["tier"])
            }),
            "observed_candidate_rate": round(sum(
                bool((row.get("early_trend") or {}).get("observed"))
                or is_authorised_tier(row["tier"])
                for row in candidates
            ) / len(tickers), 4) if tickers else 0,
            "early_exploration_ready_count": sum(
                bool((row.get("early_trend") or {}).get("exploration_ready"))
                for row in candidates
            ),
            "early_exploration_ready_idea_count": len({
                row.get("source_ticker") or row["ticker"]
                for row in candidates
                if bool((row.get("early_trend") or {}).get("exploration_ready"))
            }),
            "candidate_rate": round(sum(
                row["tier"] in {"exploration", "validated"} for row in candidates
            ) / len(tickers), 4) if tickers else 0,
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "candidates": candidates,
            "zero_output_visible": True,
        },
        # Every swap a breach prescribes, INCLUDING the ones whose target the
        # book does not currently hold. `tickers` only carries active holdings,
        # so RKLX's mandate — 「换仓 1x 同因子 RKLB」, and RKLB was cleared on
        # 6/13 — had nowhere to appear at all: the sell leg was forced and the
        # buy leg was not merely blocked, it was invisible. A prescription the
        # plan writer cannot see is one nobody can decline on purpose either.
        "swap_mandates": [
            {
                "to_ticker": target,
                "target_held": target in tickers,
                **mandate,
            }
            for target, mandates in sorted(swap_mandates.items())
            for mandate in mandates
        ],
        # The rows those unheld targets are written against (`_swap_target_rows`).
        "swap_targets": swap_targets,
        # The authorisations every decision in this generation is held to.
        "authorization": receipts.authorization_set(
            caps=(context.get("risk_guardrail") or {}).get("caps"),
            respond_only=list(risk_ledger.RESPOND_ONLY_TYPES),
            target_max_pct=add_policy_module.TARGET_MAX_PCT),
        # Unheld names a plan may propose (`_proposal_universe`).
        "proposal_universe": _proposal_universe(context, set(tickers)),
    }


def compile_packet(context: dict, generation_id: str | None = None) -> dict:
    generation_id = generation_id or context.get("generation_id")
    if not generation_id:
        raise ValueError("decision packet requires context generation_id")
    quant_rows = (context.get("quant_signals") or {}).get("rows") or {}
    cross_payload = context.get("cross_sectional_factor") or {}
    peer_payload = context.get("peer_residual") or {}
    # ``held_rankings``/``held`` were early fixture names. Production has
    # always published ``live_rankings``/``live``. Keeping the aliases is useful
    # for older external runtimes, but the real producer contract comes first.
    cross_rows = (
        cross_payload.get("live_rankings")
        or cross_payload.get("held_rankings")
        or {}
    )
    peer_rows = peer_payload.get("live") or peer_payload.get("held") or {}
    sentiment_rows = (context.get("sentiment") or {}).get("tickers") or []
    events = (context.get("news_evidence_graph") or {}).get("events") or []
    evidence_graph = context.get("news_evidence_graph") or {}
    add_policy = _add_alpha_policy(context)
    left_policy = _left_side_policy(context)
    alpha_activation = add_alpha_activation(context)
    proxies = _proxy_map(context)
    holdings = list(_active_holdings(context))
    active = {str(holding.get("ticker")) for _, holding in holdings}
    # Do not emit another tranche while an earlier add is still open in the
    # authoritative ledger. This is the daily equivalent of an exchange open-
    # order check and prevents repeated briefs from stacking the same setup.
    open_surface = context.get("open_decisions") or {}
    if "open_add_tickers" in open_surface:
        open_adds = {str(ticker) for ticker in open_surface["open_add_tickers"]}
        open_add_gate_error = bool(open_surface.get("open_add_gate_error"))
    else:
        # Backward-compatible input for external runtimes. A generic surface
        # error/truncation cannot prove that no add is open, so fail closed.
        open_adds = {
            str(row.get("ticker") or "")
            for row in open_surface.get("open") or []
            if row.get("action") in {"add_only_on_trigger", "add_on_breakout"}
            and row.get("execution_status") == "unknown"
        }
        open_add_gate_error = bool(
            open_surface.get("error") or open_surface.get("truncated")
        )
    setup_usage = context.get("technical_setup_usage") or {}
    risks = _risk_map(context, active)
    swap_mandates = _swap_mandates(risks)
    portfolios = (context.get("portfolio") or {}).get("portfolios") or {}
    invested, cash = _book_totals(portfolios)

    tickers = _ticker_rows(
        holdings, context, add_policy=add_policy,
        alpha_activation=alpha_activation, cash=cash, cross_rows=cross_rows,
        events=events, evidence_graph=evidence_graph, invested=invested,
        left_policy=left_policy, open_add_gate_error=open_add_gate_error, open_adds=open_adds,
        peer_rows=peer_rows, proxies=proxies, quant_rows=quant_rows,
        risks=risks, sentiment_rows=sentiment_rows, setup_usage=setup_usage,
        swap_mandates=swap_mandates,
    )
    candidates, tier_counts, blocker_counts = _candidate_rows(tickers)
    swap_targets = _swap_target_rows(swap_mandates, set(tickers), context, quant_rows)

    packet = _packet_payload(
        context, generation_id, add_policy=add_policy, alpha_activation=alpha_activation, blocker_counts=blocker_counts,
        candidates=candidates, cash=cash, swap_mandates=swap_mandates,
        swap_targets=swap_targets, tickers=tickers, tier_counts=tier_counts,
    )
    _warn_read_budgets(packet)
    return packet


def _decision_provenance(packet: dict, ticker: str) -> dict | None:
    """Machine-owned point-in-time signal state for one ledger decision.

    Hot/cold tiering (#1039): only fields with a reader of the persisted copy
    survive here. The one live consumer is the ledger's prospective overlay
    metrics, which reads ``sizing`` (+ ``schema_version`` as its gate); the
    identity fields keep the snapshot hash-bound to its generation. The cold
    majority — ``information.attention_components``/``event_components`` and
    the whole ``factor``/``peer_residual`` blocks — had zero readers from
    storage yet was ~85% of per-decision bytes (Aug 2026 plans averaged 42KB,
    3.5 months at 4.4x). Every dropped block is recoverable from a canonical
    store: news/factor/peer histories are committed daily under the #951
    rolling windows, and the full generation-bound packet stays on disk in the
    preflight run bundle. Persisting the copies re-uploaded the same bytes into
    every plan row, every ledger row and every future clone.
    """
    row = (packet.get("tickers") or {}).get(str(ticker))
    if not row:
        return None
    execution = row.get("execution") or {}
    quant = row.get("quant") or {}
    # Still stripped here: a packet written before the components stopped being
    # stored (or read back from an older run bundle) carries them.
    information = _without_cold_components(copy.deepcopy(row.get("information") or {}))
    return {
        "schema_version": 1,
        "context_generation_id": (packet.get("_meta") or {}).get("generation_id"),
        "observed_at": packet.get("generated_at"),
        "information": information,
        "sizing": copy.deepcopy(execution.get("information_overlay") or {}),
        "authority": {
            "max_add_shares": (row.get("constraints") or {}).get("max_add_shares"),
            "position_room_shares": (
                row.get("constraints") or {}
            ).get("position_room_shares"),
            "lot_size": (row.get("constraints") or {}).get("lot_size"),
            "tier": ((quant.get("add_authority") or {}).get("tier")),
        },
    }


def bind_plan_provenance(plan: dict, packet: dict) -> dict:
    """Replace any model-supplied signal claims with packet-owned snapshots.

    The packet is hash-bound to the preflight generation.  Persisting this copy
    is what makes later T+1/T+5/T+20 attribution use the facts visible at the
    decision, rather than today's revised news/factor files. Only the hot tier
    persists (see ``_decision_provenance``); cold signal detail stays in the
    run bundle on disk and in the committed #951 history series.
    """
    bound = copy.deepcopy(plan)
    for decision in bound.get("decisions") or []:
        provenance = _decision_provenance(packet, decision.get("ticker"))
        if provenance is not None:
            decision["signal_provenance"] = provenance
        else:
            decision.pop("signal_provenance", None)
    return bound


def _discovery_summary(discovery: dict) -> dict:
    """`stock_discovery` with what every candidate shares stated once.

    The screen stamps each candidate with the same source evidence, missing
    evidence list, next action and research route, so six candidates printed
    six copies. Nothing is dropped: a key moves to `candidate_shared` only when
    all candidates carry the identical value, and the stored packet keeps the
    rows whole for the renderers.
    """
    candidates = discovery.get("candidates")
    if (not isinstance(candidates, list) or len(candidates) < 2
            or not all(isinstance(row, dict) for row in candidates)):
        return discovery
    shared = {
        key: value for key, value in candidates[0].items()
        if all(key in row and row[key] == value for row in candidates[1:])
    }
    if not shared:
        return discovery
    return {
        **{key: value for key, value in discovery.items() if key != "candidates"},
        "candidate_shared": shared,
        "candidates": [
            {key: value for key, value in row.items() if key not in shared}
            for row in candidates
        ],
    }


def summary_view(packet: dict) -> dict:
    return {
        "stock_discovery": _discovery_summary(packet.get("stock_discovery") or {}),
        "_meta": packet.get("_meta"),
        "date": packet.get("date"),
        "integrity": packet.get("integrity"),
        "portfolio": packet.get("portfolio"),
        "tickers": [
            {
                "ticker": row.get("ticker"),
                "name": row.get("name"),
                "leg": row.get("leg"),
                "status": row.get("status"),
                "technical": {
                    key: (row.get("technical") or {}).get(key)
                    for key in ("source_ticker", "is_proxy", "as_of", "tag", "trend",
                                "rsi_state", "stop_state", "setups", "usable")
                },
                "thesis": row.get("thesis"),
                "execution": row.get("execution"),
                "quant_usable": {
                    "factor": ((row.get("quant") or {}).get("factor") or {})
                    .get("usable_for_decisions"),
                    "peer": ((row.get("quant") or {}).get("peer_residual") or {})
                    .get("usable_for_decisions"),
                },
                "early_trend": ((row.get("quant") or {}).get("early_trend") or {}),
                # The summary — not the full packet — is what SKILL.md Step 2
                # calls the model's 唯一常驻输入, so a field added to
                # `compile_packet` and not to this projection reaches nobody.
                "history": row.get("history"),
                # Two live cites per name (full rows: `--section information`).
                "live": [item.get("cite") for item in
                         ((row.get("information") or {}).get("live") or [])[:2]],
                "risk_count": len(row.get("risk") or []),
                # Closed actions by code; the reason is in the row
                # (`--section constraints`).
                "constraints": {
                    **(row.get("constraints") or {}),
                    "closed_actions": {
                        action: why.get("code") for action, why in
                        ((row.get("constraints") or {}).get("closed_actions") or {}).items()
                    },
                },
            }
            for row in packet.get("tickers", {}).values()
        ],
        # Swap targets the book does not hold: writable as the buy leg of
        # their mandate, and nothing else.
        "swap_targets": packet.get("swap_targets") or {},
        # Unheld names with stored bars: proposable, priced at the stated
        # close, and not yet through the entry gate.
        # One line per name: this is read every morning and the full rows are
        # what the plan review uses, not this.
        "proposal_universe": {
            "columns": "ticker leg price price_as_of price_basis lot_size",
            "rows": [
                " ".join(str(value) for value in (
                    row["ticker"], row["leg"], row["facts"]["current_price"],
                    row["facts"]["price_as_of"], row["facts"]["price_basis"],
                    row["constraints"]["lot_size"] or "unknown"))
                for row in (packet.get("proposal_universe") or {}).values()
            ],
            "open": "watch; add_only_on_trigger where lot_size is known",
            "authorization": ENTRY_GATE_REQUIRED,
        },
        "live_information": packet.get("live_information"),
        "judgment_contract": packet.get("judgment_contract"),
    }


def judgment_template(packet: dict) -> dict:
    generation_id = (packet.get("_meta") or {}).get("generation_id")
    return {
        "schema_version": JUDGMENT_SCHEMA_VERSION,
        "context_generation_id": generation_id,
        "portfolio_assessment": "",
        "portfolio_counterargument": "",
        "narrative": {
            "regime_read": "",
            "bull": "",
            "bear": "",
            "devils_advocate": "",
            "attacked_consensus": "",
            "risk_voice_first": "aggressive",
            "aggressive": "",
            "conservative": "",
            "neutral": "",
            "sector_read": "",
            "macro_read": "",
            "calibration_read": "",
            "next_session": [],
            "data_holes": [],
        },
        "ticker_judgments": [
            {
                "ticker": ticker,
                "verdict": "neutral",
                "confidence": 0.5,
                "disposition": "wait",
                "assessment": "",
                "counterargument": "",
                "rationale": "",
                "falsifier": "",
                "next_evidence": "",
                "fundamentals": "",
                "cross_market": "",
                "sentiment_read": "",
                "peer_read": "",
            }
            for ticker in packet.get("tickers", {})
        ],
    }


def _prose_issues(value, field: str, label: str) -> list[str]:
    """One judgment field: present, within budget, and free of layout."""
    if not isinstance(value, str) or not value.strip():
        return [f"{label} {field} must be non-empty text"]
    if len(value) > TEXT_LIMITS[field]:
        return [f"{label} {field} exceeds {TEXT_LIMITS[field]} chars"]
    complaint = _layout_violation(value)
    if complaint:
        return [f"{label} {field} {complaint}; write the thought, the harness "
                f"writes the layout"]
    return []


def _narrative_issues(narrative) -> list[str]:
    """The debate slots the report is rendered from.

    These used to be markdown the model wrote straight into the report, which is
    why they are checked as hard as the per-ticker rows: an empty `bear` is no
    longer a thin paragraph, it is a section of the published brief with nothing
    in it.
    """
    if not isinstance(narrative, dict):
        return ["judgment narrative must be an object"]
    allowed = set(NARRATIVE_TEXT_FIELDS) | set(NARRATIVE_LIST_FIELDS) | {"risk_voice_first"}
    issues = []
    unknown = sorted(set(narrative) - allowed)
    if unknown:
        issues.append(f"judgment narrative unknown fields: {unknown}")
    for field in NARRATIVE_TEXT_FIELDS:
        issues.extend(_prose_issues(narrative.get(field), field, "judgment narrative"))
    if narrative.get("risk_voice_first") not in RISK_VOICES:
        issues.append(
            "judgment narrative risk_voice_first must be one of "
            f"{sorted(RISK_VOICES)} (the rotation is the model's to state, "
            "the ordering is the harness's to render)")
    for field, (low, high) in NARRATIVE_LIST_FIELDS.items():
        rows = narrative.get(field)
        if not isinstance(rows, list):
            issues.append(f"judgment narrative {field} must be a list")
            continue
        if not low <= len(rows) <= high:
            issues.append(
                f"judgment narrative {field} must hold {low}-{high} entries, got {len(rows)}")
        for index, entry in enumerate(rows):
            issues.extend(
                _prose_issues(entry, field, f"judgment narrative {field}[{index}]"))
    return issues


def validate_judgment_overlay(packet: dict, overlay: dict) -> list[str]:
    from clawock.decision.reflection_claims import episode_claim_mismatches
    issues = []
    reflections = {ticker: {'n': (row.get('history') or {}).get('settled_episodes'),
                            'win_rate': (row.get('history') or {}).get('win_rate')}
                   for ticker, row in (packet.get('tickers') or {}).items()}
    top_allowed = {
        "schema_version", "context_generation_id", "portfolio_assessment",
        "portfolio_counterargument", "narrative", "ticker_judgments",
    }
    row_allowed = {
        "ticker", "verdict", "confidence", "disposition", "assessment",
        "counterargument", "rationale", "falsifier", "next_evidence",
        "fundamentals", "cross_market", "sentiment_read", "peer_read",
    }
    if not isinstance(overlay, dict):
        return ["judgment overlay must be an object"]
    extra = sorted(set(overlay) - top_allowed)
    if extra:
        issues.append(f"judgment overlay unknown fields: {extra}")
    if overlay.get("schema_version") != JUDGMENT_SCHEMA_VERSION:
        issues.append(f"judgment schema_version must be {JUDGMENT_SCHEMA_VERSION}")
    expected_generation = (packet.get("_meta") or {}).get("generation_id")
    if overlay.get("context_generation_id") != expected_generation:
        issues.append("judgment context_generation_id missing or stale")
    for field in ("portfolio_assessment", "portfolio_counterargument"):
        issues.extend(_prose_issues(overlay.get(field), field, "judgment"))
    issues.extend(_narrative_issues(overlay.get("narrative")))

    rows = overlay.get("ticker_judgments")
    if not isinstance(rows, list):
        issues.append("judgment ticker_judgments must be a list")
        return issues
    known = set(packet.get("tickers") or {})
    seen = set()
    for index, row in enumerate(rows):
        label = f"judgment ticker_judgments[{index}]"
        if not isinstance(row, dict):
            issues.append(f"{label} must be an object")
            continue
        unknown = sorted(set(row) - row_allowed)
        if unknown:
            issues.append(f"{label} unknown fields: {unknown}")
        ticker = str(row.get("ticker") or "")
        if ticker not in known:
            issues.append(f"{label} unknown ticker {ticker!r}")
        if ticker in seen:
            issues.append(f"{label} duplicate ticker {ticker!r}")
        seen.add(ticker)
        if row.get("verdict") not in VERDICTS:
            issues.append(f"{label} invalid verdict {row.get('verdict')!r}")
        disposition = row.get("disposition")
        if disposition not in DISPOSITIONS:
            issues.append(f"{label} invalid disposition {disposition!r}")
        # `candidate` on a name the add policy does not rate is the model's
        # nomination. It is not refused: `judgment_departures` reports it.
        confidence = _number(row.get("confidence"))
        if confidence is None or not 0 <= confidence <= 1:
            issues.append(f"{label} confidence must be in [0,1]")
        for field in ROW_TEXT_FIELDS:
            issues.extend(_prose_issues(row.get(field), field, label))
            if isinstance(row.get(field), str):
                issues.extend(f'{label} {field}: {issue}' for issue in
                              episode_claim_mismatches(row[field], reflections, subject=ticker))
    missing = sorted(known - seen)
    if missing:
        issues.append(f"judgment missing active tickers: {missing}")
    return issues


def _catalyst_evidence_findings(tag: str, decision: dict,
                                row: dict) -> list[tuple[str, str, str]]:
    """Evidence check for a decision attributed to a catalyst: (channel, code, message).

    Two different questions. Whether the cited event exists for this ticker is
    a fact: an id that matches nothing is a fabricated reference and blocks,
    for an active call and a passive stance alike. Whether the event was
    *escalated* is the news-evidence policy's opinion of it
    (`actionable_escalation`): trading on a real event the policy did not
    escalate is a departure from that policy, recorded as an objection.
    """
    evidence_id = decision.get("evidence_event_id")
    known_ids = {
        event.get("event_id") for event in (row.get("evidence") or [])
        if event.get("event_id")
    }
    if evidence_id not in known_ids:
        return [(receipts.FACT, "FACT_UNKNOWN_EVENT",
                 f"{tag}: evidence_event_id does not match any event for this ticker")]
    if (decision.get("action") in ACTIVE_ACTIONS and evidence_id not in (
            (row.get("constraints") or {}).get("actionable_evidence_ids") or [])):
        return [(receipts.STRATEGY, "STRAT_EVENT_NOT_ESCALATED",
                 f"{tag}: the news-evidence policy did not escalate {evidence_id}")]
    return []


def _swap_leg_issues(tag: str, decision: dict, row: dict, mandate: dict,
                     decisions: list[dict]) -> list[str] | None:
    """Judge an add on a swap target against its mandate, or None if it is not one.

    `_constraints` opens `add_only_on_trigger` on a swap target without a
    setup or add budget (#1084); judging that leg by the setup and
    `max_add_shares` it was never meant to have refused it again here (#1905).
    What the rule does bound, it is held to: the one named ticker, a sell of
    the mandate's source in the same `decision_group_id` (the field the ledger
    pairs swaps on), and no more than the mandate's `max_value`.
    """
    sources = {
        str(item.get("from_ticker"))
        for item in mandate.get("all_mandates") or [mandate]
    }
    paired = bool(paired_swap_sells(decision, decisions, sources=sources))
    if not paired:
        if decision.get("technical_setup_id"):
            return None  # an ordinary setup add on this name; judged as one
        return [
            f"{tag}: swap buy leg must share decision_group_id with a "
            f"positive integer-sized {'/'.join(SWAP_SELL_ACTIONS)} of {'/'.join(sorted(sources))}"
        ]
    issues = []
    shares = _number((decision.get("size") or {}).get("shares"), 0)
    lot = _number((row.get("constraints") or {}).get("lot_size"), 0)
    if shares is None or shares <= 0 or int(shares) != shares:
        issues.append(f"{tag}: swap buy leg requires positive integer size.shares")
        return issues
    if lot and int(shares) % int(lot) != 0:
        issues.append(
            f"{tag}: size.shares {shares:g} is not a board-lot multiple of {lot:g}")
    elif not lot and row.get("held") is False:
        # A holding's lot arrives with its quote; an unheld HK target has one
        # only when preflight fetched it. One share is not assumed to be a lot.
        issues.append(f"{tag}: board lot of unheld swap target is unknown; "
                      "the buy leg cannot be sized")
    max_value = _number(mandate.get("max_value"), 2)
    price = (_number((decision.get("condition") or {}).get("price"), 4)
             or _number((row.get("facts") or {}).get("current_price"), 4))
    if max_value is not None:
        if not price:
            issues.append(f"{tag}: swap buy leg has no price to hold to max_value")
        elif shares * price > max_value:
            issues.append(
                f"{tag}: swap buy leg {shares:g} x {price:g} exceeds mandate "
                f"max_value {max_value:g} {mandate.get('currency') or ''}".rstrip())
    return issues


def _whole_shares(decision: dict) -> int | None:
    """A leg's size as a positive whole share count, else None."""
    shares = _number((decision.get("size") or {}).get("shares"), 4)
    if shares is None or shares <= 0 or int(shares) != shares:
        return None
    return int(shares)


def _full_position_stops(row: dict, exempt_breach_ids=frozenset()) -> list[float]:
    """Share counts the row's full-position obligations still require, capped at the holding."""
    holding = _number((row.get("constraints") or {}).get("max_sell_shares"), 4)
    out = []
    for risk in row.get("risk") or []:
        if ((risk.get("required_reduction") or {}).get("kind") != "full_leveraged_position"
                or (risk.get("adaptive") or {}).get("may_stand")
                or risk.get("override_active")
                or risk.get("breach_id") in exempt_breach_ids):
            continue
        minimum = _number(
            (risk.get("required_reduction") or {}).get("minimum_shares"), 4)
        if minimum is not None and minimum > 0:
            out.append(min(minimum, holding) if holding is not None else minimum)
    return out


def bind_full_position_cuts(plan: dict, packet: dict) -> dict:
    """Size the one unsized cut that answers a hard stop, from the packet.

    The amount is the position; there is nothing for the plan writer to decide
    and so nothing for it to copy (kcn 2026-10-10: a number the system can write
    should not pass through the model). A size the writer did state is left
    alone and judged by `validate_plan_constraints`.
    """
    bound = copy.deepcopy(plan)
    decisions = [d for d in bound.get("decisions") or [] if isinstance(d, dict)]
    for ticker, row in (packet.get("tickers") or {}).items():
        required = _full_position_stops(row)
        cuts = [d for d in decisions
                if str(d.get("ticker") or "") == ticker and d.get("action") == "cut"]
        if not required or len(cuts) != 1:
            continue
        size = cuts[0].get("size") if isinstance(cuts[0].get("size"), dict) else {}
        full = max(required)
        if size.get("shares") is None and int(full) == full:
            cuts[0]["size"] = {**size, "shares": int(full)}
    return bound


def _full_position_shortfalls(decisions: list[dict], rows: dict,
                              exempt_breach_ids=frozenset()) -> list[str]:
    """Hard stops whose cut legs do not add up to the position they must close.

    `required_reduction.minimum_shares` has been in the packet since the hard
    stop got a row of its own, and nothing read it: the forced action was
    checked by name, so `cut` with `size.shares: 0` on a ten-share position
    answered a full-position stop (#2831). The legs are summed per ticker, so a
    cut split across conditions still counts once it covers the position.

    Only the full-position kind is a per-plan minimum. A `minimum_value` on a
    cap breach is the distance to the cap, and the same row tells the writer to
    work it off in tranches (「借反弹分批、勿在新低日一次砍」) — holding one
    plan to the whole distance would overrule that. A hard stop with no cut at
    all is postflight's finding, which also knows the durable overrides.
    """
    issues = []
    for ticker, row in rows.items():
        cuts = [
            d for d in decisions
            if str(d.get("ticker") or "") == ticker and d.get("action") in SELL_ACTIONS
        ]
        if not cuts:
            continue
        cut_shares = sum(_whole_shares(d) or 0 for d in cuts)
        for minimum in _full_position_stops(row, exempt_breach_ids):
            if cut_shares < minimum:
                issues.append(
                    f"{ticker}: risk obligation requires cutting the full position "
                    f"({minimum:g} shares, required_reduction.minimum_shares); "
                    f"plan cuts {cut_shares:g}"
                )
    return issues


def _policy_objections(tag: str, action: str, row: dict) -> list[tuple[str, str]]:
    """Why the registered policy would not have taken an action that is open:
    (code, message) pairs.

    Read from the same row fields the policy read; the wording names the rule,
    so the reader of the card can tell which opinion was departed from.
    """
    constraints = row.get("constraints") or {}
    if action in (constraints.get("allowed_actions") or []):
        return []
    execution = row.get("execution") or {}
    if action in SELL_ACTIONS:
        return [("STRAT_SELL_WITHOUT_ESCALATED_EVENT",
                 f"{tag}: the registered policy opens a discretionary {action} only on an "
                 "escalated event; none is escalated for this name")]
    reasons = []
    blockers = set(execution.get("blockers") or [])
    tier = (((row.get("quant") or {}).get("add_authority") or {}).get("tier")) or "none"
    if execution.get("thesis_gate") == "blocked":
        reasons.append("the thesis registry marks this thesis as weakened or broken")
    if "no_approved_setup" in blockers or not constraints.get("technical_setup_ids"):
        reasons.append("no registered technical setup is active")
    if not is_authorised_tier(tier):
        reasons.append(f"the add-evidence policy rates this name `{tier}`")
    if action == "add_on_breakout" and "confirmed_breakout" not in (
            constraints.get("technical_setup_ids") or []):
        reasons.append("no confirmed breakout is registered")
    if not reasons:
        reasons.append("the registered policy sizes this add at zero")
    return [("STRAT_ADD_OUTSIDE_POLICY",
             f"{tag}: {action} departs from the registered add policy: " + "; ".join(reasons))]


def _add_findings(tag: str, decision: dict, row: dict) -> list[tuple[str, str, str]]:
    """Size and entry of an add that is not a swap leg: (channel, code, message)."""
    constraints = row.get("constraints") or {}
    condition = decision.get("condition") or {}
    out = []
    # Four digits, not zero: rounding first would turn 20.5 shares into 20.
    shares = _number((decision.get("size") or {}).get("shares"), 4)
    lot = _number(constraints.get("lot_size"), 0)
    room = _number(constraints.get("position_room_shares"), 0)
    max_add = _number(constraints.get("max_add_shares"), 0) or 0
    feas = receipts.FEASIBILITY
    if shares is None or shares <= 0:
        out.append((feas, "FEAS_SIZE_NOT_POSITIVE_INTEGER",
                    f"{tag}: add requires positive integer size.shares"))
    elif int(shares) != shares:
        out.append((feas, "FEAS_FRACTIONAL_SHARES",
                    f"{tag}: fractional shares are not supported"))
    elif lot and int(shares) % int(lot) != 0:
        out.append((feas, "FEAS_NOT_A_BOARD_LOT",
                    f"{tag}: size.shares {shares:g} is not a board-lot multiple of {lot:g}"))
    elif room is not None and shares > room:
        out.append((feas, "AUTH_EXCEEDS_ROOM",
                    f"{tag}: size.shares {shares:g} exceeds the cash and concentration "
                    f"room of {room:g} shares (position_room_shares)"))
    elif shares > max_add:
        out.append((receipts.STRATEGY, "STRAT_SIZE_ABOVE_POLICY_TRANCHE",
                    f"{tag}: size.shares {shares:g} is above the registered policy's "
                    f"tranche of {max_add:g} (max_add_shares)"))
    price = _number(condition.get("price"), 4)
    if condition.get("type") in ("price_above", "price_below") and (
            price is None or price <= 0):
        out.append((receipts.FACT, "FACT_ENTRY_PRICE_MISSING",
                    f"{tag}: a price condition needs a positive condition.price"))
    invalidation = _number(decision.get("invalidation_price"), 4)
    if invalidation is None or invalidation <= 0:
        out.append((feas, "FEAS_NO_INVALIDATION_PRICE",
                    f"{tag}: add requires invalidation_price, the level at which it is wrong"))
    setup_id = decision.get("technical_setup_id")
    setups = (row.get("technical") or {}).get("setups") or []
    named = [setup for setup in setups if setup.get("setup_id") == setup_id]
    if setup_id and not named:
        # Claiming a registered setup that the packet does not carry is a
        # false reference, not a different strategy.
        out.append((receipts.FACT, "FACT_UNKNOWN_SETUP",
                    f"{tag}: technical_setup_id {setup_id!r} is not a setup in this packet"))
    elif named:
        approved = [
            setup for setup in named
            if setup.get("campaign_id") == decision.get("technical_campaign_id")
            and setup.get("setup_id") in (constraints.get("technical_setup_ids") or [])
            and setup.get("entry_type") == condition.get("type")
            and _number(setup.get("entry_price"), 4) == price
            and _number(setup.get("invalidation_price"), 4) == invalidation
            and setup.get("next_tranche_number") == decision.get("tranche_number")
            and (decision.get("action") != "add_on_breakout"
                 or setup.get("setup_id") == "confirmed_breakout")
        ]
        if not approved:
            out.append((receipts.STRATEGY, "STRAT_ENTRY_DIFFERS_FROM_SETUP",
                        f"{tag}: entry, invalidation or tranche differs from the registered "
                        f"setup {setup_id!r} it names"))
        elif int(condition.get("valid_for_sessions") or 1) != int(
                approved[0].get("valid_for_sessions") or 1):
            out.append((receipts.STRATEGY, "STRAT_VALIDITY_DIFFERS_FROM_SETUP",
                        f"{tag}: validity differs from the registered setup {setup_id!r}"))
    else:
        out.append((receipts.STRATEGY, "STRAT_NOT_A_REGISTERED_SETUP",
                    f"{tag}: the entry is the plan's own; it matches no registered setup"))
    return out


def _review_row(packet: dict, decision: dict) -> dict | None:
    """The row a decision is judged against (see `decision_row`).

    A swap target the book does not hold is writable as the paired buy leg; an
    open add on the same name is a proposal on an unheld name and is judged as
    one.
    """
    ticker = str(decision.get("ticker") or "")
    held = (packet.get("tickers") or {}).get(ticker)
    if held:
        return held
    swap = (packet.get("swap_targets") or {}).get(ticker)
    universe = (packet.get("proposal_universe") or {}).get(ticker)
    if swap and (is_risk_swap_buy(decision) or not universe):
        return swap
    return universe


def review_plan(plan: dict, packet: dict, *,
                exempt_breach_ids=frozenset()) -> list[dict]:
    """Every finding about the plan, each in its own channel (`receipts`).

    `fact` and `feasibility` findings block; `strategy` findings are the
    registered policy's objections and are kept with the decision. Nothing here
    changes the plan.
    """
    out: list[dict] = []
    rows = packet.get("tickers") or {}
    decisions = [d for d in plan.get("decisions") or [] if isinstance(d, dict)]
    leg_spend: dict[str, float] = {}

    def add(channel, code, message, index, ticker):
        out.append(receipts.finding(channel, code, message, index=index, ticker=ticker))

    for index, decision in enumerate(plan.get("decisions") or []):
        if not isinstance(decision, dict):
            continue
        ticker = str(decision.get("ticker") or "")
        tag = f"decision[{index}] {ticker}"
        row = _review_row(packet, decision)
        if not row:
            add(receipts.FACT, "FACT_TICKER_NOT_PRICEABLE",
                f"{tag}: ticker is outside current decision packet "
                "(not a holding, a swap target or a name with stored daily bars)",
                index, ticker)
            continue
        constraints = row.get("constraints") or {}
        action = decision.get("action")
        mandate = constraints.get("swap_mandate")
        swap_issues = (
            _swap_leg_issues(tag, decision, row, mandate, decisions)
            if action == "add_only_on_trigger" and mandate
            and (is_risk_swap_buy(decision) or row.get("held") is False
                 or "add_only_on_trigger" in (constraints.get("closed_actions") or {}))
            else None
        )
        open_actions = constraints.get("open_actions")
        if open_actions is None:
            # A packet compiled before the envelope existed: the policy list
            # is the only bound it carries.
            open_actions = constraints.get("allowed_actions") or []
        if swap_issues is not None:
            for message in swap_issues:
                add(receipts.FEASIBILITY, "AUTH_SWAP_MANDATE", message, index, ticker)
        elif action not in open_actions:
            closed = (constraints.get("closed_actions") or {}).get(action) or {}
            add(closed.get("channel") or receipts.FEASIBILITY,
                closed.get("code") or "FEAS_ACTION_NOT_OPEN",
                f"{tag}: action {action!r} is not open on this name"
                + (f": {closed['reason']}" if closed.get("reason") else "")
                + f" (open: {open_actions})",
                index, ticker)
        else:
            for code, message in _policy_objections(tag, action, row):
                add(receipts.STRATEGY, code, message, index, ticker)
        if (swap_issues is None and is_risk_swap_buy(decision)
                and action in open_actions):
            # The label is a claim: `risk_rule` says a breach prescribes this
            # buy. An open add is welcome under its own name, not under a
            # mandate nobody issued.
            add(receipts.FEASIBILITY, "AUTH_NO_SWAP_MANDATE",
                f"{tag}: a risk_rule buy leg needs a swap mandate and no open breach "
                "prescribes buying this name", index, ticker)
        claimed = _number(decision.get("simulated_entry_price"), 4)
        observed = {_number((row.get("facts") or {}).get("current_price"), 4),
                    _number((decision.get("condition") or {}).get("price"), 4)} - {None}
        if claimed is not None and observed and claimed not in observed:
            # A trigger level is the plan's to choose; a price it says was
            # observed has to be one the packet carries.
            add(receipts.FACT, "FACT_PRICE_NOT_OBSERVED",
                f"{tag}: simulated_entry_price {claimed:g} is neither the packet's price "
                "for this name nor the plan's own trigger", index, ticker)
        if decision.get("driven_by") == "catalyst":
            for channel, code, message in _catalyst_evidence_findings(tag, decision, row):
                add(channel, code, message, index, ticker)
        elif (action in ACTIVE_ACTIONS and swap_issues is None
              and decision.get("strategy_id") != "risk_rebalance"
              and not decision.get("technical_setup_id")):
            add(receipts.STRATEGY, "STRAT_ACTIVE_WITHOUT_CATALYST",
                f"{tag}: the registered policy takes an active {action} only on a "
                "catalyst, a registered setup or a risk rule", index, ticker)
        shares = _number((decision.get("size") or {}).get("shares"), 0)
        max_sell = _number(constraints.get("max_sell_shares"), 0)
        if (shares is not None and max_sell is not None
                and action in SELL_ACTIONS and shares > max_sell):
            add(receipts.FEASIBILITY, "FEAS_SELL_EXCEEDS_HOLDING",
                f"{tag}: size.shares {shares:g} exceeds holding {max_sell:g}", index, ticker)
        if action in SELL_ACTIONS and _whole_shares(decision) is None and (
            (decision.get("size") or {}).get("shares") is not None
            or action in (constraints.get("forced_action_one_of") or [])
        ):
            # An unsized sell stays advisory (`missing_size_warnings`); a zero,
            # negative or fractional one is not a sell, and a leg that answers a
            # forced action has to say how much it reduces.
            add(receipts.FEASIBILITY, "FEAS_SELL_NOT_POSITIVE_INTEGER",
                f"{tag}: sell leg requires positive integer size.shares", index, ticker)
        if swap_issues is None and action in {"add_only_on_trigger", "add_on_breakout"} \
                and action in open_actions:
            for channel, code, message in _add_findings(tag, decision, row):
                add(channel, code, message, index, ticker)
            price = (_number((decision.get("condition") or {}).get("price"), 4)
                     or _number((row.get("facts") or {}).get("current_price"), 4))
            if shares and shares > 0 and price:
                leg = str(row.get("leg") or "")
                leg_spend[leg] = leg_spend.get(leg, 0.0) + shares * price
    cash = (packet.get("portfolio") or {}).get("cash_available") or {}
    for leg, spend in sorted(leg_spend.items()):
        available = _number(cash.get(leg), 2)
        if available is not None and spend > available:
            add(receipts.FEASIBILITY, "FEAS_EXCEEDS_CASH",
                f"{leg}: the plan's adds need {spend:,.2f} and the leg holds "
                f"{available:,.2f} in cash", None, None)
    for message in _full_position_shortfalls(decisions, rows, exempt_breach_ids):
        add(receipts.FEASIBILITY, "AUTH_OBLIGATION_SHORTFALL", message, None, None)
    return out


def validate_plan_constraints(plan: dict, packet: dict, *,
                              exempt_breach_ids=frozenset()) -> list[str]:
    """What stops this plan from being filed: facts and feasibility only."""
    return [
        receipts.tagged(item) for item in receipts.blocking(
            review_plan(plan, packet, exempt_breach_ids=exempt_breach_ids))
    ]


def bind_policy_review(plan: dict, packet: dict, *,
                       exempt_breach_ids=frozenset()) -> dict:
    """Stamp each decision with the registered policy's objections to it.

    Harness-written, like `signal_provenance`: an authored `policy_review` is
    replaced. The proposal itself is left exactly as written — an objection is
    printed beside it, never applied to it.
    """
    bound = copy.deepcopy(plan)
    by_index: dict[int, list[dict]] = {}
    for item in review_plan(bound, packet, exempt_breach_ids=exempt_breach_ids):
        if item.get("index") is not None:
            by_index.setdefault(item["index"], []).append(item)
    for index, decision in enumerate(bound.get("decisions") or []):
        if not isinstance(decision, dict):
            continue
        review = receipts.review_of(by_index.get(index, []))
        row = _review_row(packet, decision) or {}
        pending = (row.get("constraints") or {}).get("authorization")
        if pending and decision.get("action") in ACTIVE_ACTIONS:
            review["authorization"] = pending
        review["authorization_version"] = (packet.get("authorization") or {}).get("version")
        decision["policy_review"] = review
    return bound


def compile_pages_projection(
    packet: dict,
    overlay: dict | None = None,
    overlay_issues: list[str] | None = None,
    add_alpha_run_card: dict | None = None,
) -> dict:
    overlay_issues = list(overlay_issues or [])
    valid_overlay = overlay if overlay and not overlay_issues else {}
    judgments = {
        str(row.get("ticker")): row
        for row in valid_overlay.get("ticker_judgments") or []
    }
    rows = []
    for ticker, row in packet.get("tickers", {}).items():
        risks = row.get("risk") or []
        hard = any(item.get("kind") == "hard_stop" for item in risks)
        direct = any(item.get("scope") == "ticker" for item in risks)
        judgment = judgments.get(ticker)
        authority = ((row.get("quant") or {}).get("add_authority") or {})
        early = ((row.get("quant") or {}).get("early_trend") or {})
        deterministic_candidate = bool(
            is_authorised_tier(authority.get("tier"))
            or early.get("observed")
        )
        # The judgment's disposition as written. It used to be replaced with
        # `wait` whenever the add policy had not nominated the name — a
        # conclusion changed on the way to the page with nothing saying so.
        effective_disposition = (judgment or {}).get("disposition") or "wait"
        rows.append({
            "ticker": ticker,
            "name": row.get("name"),
            "leg": row.get("leg"),
            "facts": {
                key: (row.get("facts") or {}).get(key)
                for key in ("today_change_pct", "pnl_pct")
            },
            "technical": {
                key: (row.get("technical") or {}).get(key)
                for key in (
                    "source_ticker", "is_proxy", "as_of", "tag", "trend",
                    "rsi14", "rsi_state", "dist_ma200_pct", "pct_52w_range",
                    "stop_state", "usable",
                )
            },
            "quant": {
                "factor_usable": ((row.get("quant") or {}).get("factor") or {})
                .get("usable_for_decisions"),
                "peer_usable": ((row.get("quant") or {}).get("peer_residual") or {})
                .get("usable_for_decisions"),
            },
            "sentiment": {
                key: (row.get("sentiment") or {}).get(key)
                for key in (
                    "source_ticker", "reddit_mentions_7d", "headline_count", "coverage",
                )
            },
            "risk": {
                "count": len(risks),
                "severity": (
                    "critical" if hard else "high" if risks else "none"
                ),
                "action": (
                    {"kind": "stop", "label": "止损"}
                    if hard else {"kind": "trim", "label": "减仓"}
                    if any(item.get("enforcement") != "respond" for item in risks)
                    # Same chip as a trim on the dashboard; only the word differs.
                    else {"kind": "trim", "label": "超限"}
                    if direct else None
                ),
                "breach_ids": [
                    item.get("breach_id") for item in risks if item.get("breach_id")
                ],
            },
            "status": row.get("status"),
            "judgment": judgment,
            "candidate_disposition": {
                "deterministic_candidate": deterministic_candidate,
                "effective": effective_disposition,
                "departs_from_policy": bool(
                    effective_disposition == "candidate" and not deterministic_candidate),
                "discipline": ("the judgment's disposition is shown as written; "
                               "`deterministic_candidate` is the add policy's own "
                               "nomination, and neither is an order"),
            },
        })
    rows.sort(
        key=lambda row: (
            (row.get("status") or {}).get("rank", 99),
            (row.get("facts") or {}).get("pnl_pct") or 0,
            row.get("ticker") or "",
        )
    )
    diagnostics = packet.get("add_alpha_diagnostics")
    campaign_status = "current" if isinstance(diagnostics, dict) else "pre_policy_packet"
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    candidates = []
    for candidate in diagnostics.get("candidates") or []:
        candidates.append({
            key: candidate.get(key)
            for key in (
                "ticker", "leg", "source_ticker", "is_proxy", "state", "tier",
                "target_tranche_level",
                "sources", "evidence_families", "authority_blockers",
                "execution_blockers", "entry_price", "invalidation_price",
                "max_add_shares", "allowed",
                "early_trend",
            )
        })
    candidates.sort(key=lambda row: (row.get("leg") or "", row.get("ticker") or ""))

    return {
        "schema_version": PAGES_SCHEMA_VERSION,
        "generated_at": packet.get("generated_at"),
        "as_of": packet.get("date"),
        "context_generation_id": (packet.get("_meta") or {}).get("generation_id"),
        "judgment_status": (
            "valid" if valid_overlay
            else "invalid" if overlay is not None
            else "missing"
        ),
        "judgment_issues": overlay_issues[:10],
        "portfolio_judgment": {
            "assessment": valid_overlay.get("portfolio_assessment"),
            "counterargument": valid_overlay.get("portfolio_counterargument"),
        } if valid_overlay else None,
        "tickers": rows,
        "add_campaign": {
            "status": campaign_status,
            "packet_generated_at": packet.get("generated_at"),
            "context_generation_id": (packet.get("_meta") or {}).get("generation_id"),
            "policy": {
                key: (packet.get("add_alpha_policy") or {}).get(key)
                for key in (
                    "schema_version", "registered_at", "minimum_evidence_families",
                    "confirmation_window_sessions", "exploration_max_tranches",
                    "exploration_tranche_pct", "validated_max_tranches",
                    "validated_tranche_pct", "exploration_max_book_pct",
                )
            } if campaign_status == "current" else None,
            "diagnostics": {
                key: diagnostics.get(key)
                for key in (
                    "held_names", "tier_counts", "candidate_count",
                    "authority_candidate_count", "allowed_candidate_count",
                    "observed_candidate_count", "observed_candidate_rate",
                    "observed_idea_count", "early_exploration_ready_count",
                    "early_exploration_ready_idea_count", "candidate_rate",
                    "blocker_counts", "zero_output_visible",
                )
            } if campaign_status == "current" else None,
            "candidates": candidates,
            "run_card": _compact_add_alpha_run_card(add_alpha_run_card),
        },
    }


def _latest_add_alpha_run_card() -> dict | None:
    cards = sorted(
        (workspace_root() / "memory" / "backtests").glob(
            "add_alpha_walkforward-*.json"
        )
    )
    if not cards:
        return None
    try:
        return json.loads(cards[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _compact_add_alpha_run_card(card: dict | None) -> dict | None:
    """Project the latest evaluator receipt without publishing vendor inputs."""
    if not isinstance(card, dict):
        return None
    metrics = card.get("metrics") or {}
    coverage = metrics.get("coverage") or {}
    market_metrics = {}
    early_metrics = {}
    for market in ("us", "hk"):
        interaction = (metrics.get(market) or {}).get("interaction") or {}
        market_metrics[market] = {
            horizon: {
                key: (interaction.get(horizon) or {}).get(key)
                for key in (
                    "n", "n_dates", "n_tickers", "mean_return", "hit_rate",
                    "mean_excess_vs_same_date_setup", "status",
                )
            }
            for horizon in ("t1", "t5", "t20")
        }
        early = (metrics.get("early_trend") or {}).get(market) or {}
        early_metrics[market] = {
            state: {
                horizon: {
                    key: ((early.get(state) or {}).get(horizon) or {}).get(key)
                    for key in (
                        "n", "n_dates", "n_tickers", "mean_return",
                        "hit_rate", "status",
                    )
                }
                for horizon in ("t1", "t5")
            }
            for state in ("observed", "information_confirmed", "exploration_ready")
        }
    return {
        "run_id": card.get("run_id"),
        "generated_at": card.get("generated_at"),
        "reproduction_key": card.get("reproduction_key"),
        "policy_version": (card.get("params") or {}).get("policy_version"),
        "parameter_fit": (card.get("params") or {}).get("parameter_fit"),
        "markets": market_metrics,
        "early_trend": early_metrics,
        "coverage": {
            key: coverage.get(key)
            for key in (
                "factor_dates", "information_dates", "overlap_dates",
                "prospective_information_dates", "authority_classifications",
                "information_grade", "factor_grade", "claim",
            )
        } | {"early_trend": coverage.get("early_trend")},
    }


def write_pages_projection(
    packet: dict,
    overlay_path: Path,
    output_path: Path,
) -> tuple[dict, list[str]]:
    """Publish deterministic Pages data even when the model overlay is unusable."""
    overlay = None
    issues = []
    if overlay_path.exists():
        try:
            overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
            issues = validate_judgment_overlay(packet, overlay)
        except Exception as exc:
            issues = [f"judgment overlay parse failed: {exc}"]
            overlay = {}
    projection = compile_pages_projection(
        packet, overlay, issues, add_alpha_run_card=_latest_add_alpha_run_card()
    )
    _atomic_write(output_path, projection)
    return projection, issues


def read_packet(manifest_path: Path) -> dict:
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    entry = (manifest.get("tools") or {}).get("decision_packet") or {}
    if not entry:
        raise ValueError("manifest has no decision_packet tool artifact")
    path = Path(entry.get("path") or "")
    text = path.read_text(encoding="utf-8")
    packet = json.loads(text)
    generation_id = manifest.get("generation_id")
    if (
        entry.get("sha256") != _sha256(text)
        or entry.get("generation_id") != generation_id
        or (packet.get("_meta") or {}).get("generation_id") != generation_id
    ):
        raise ValueError("decision packet failed generation/hash check")
    return packet


def bounded_payload(value, limit: int = MAX_QUERY_BYTES) -> str:
    """Serialise a query result, refusing anything over its budget.

    The cap used to live only on the print path, so any caller that used
    read_packet()/summary_view() directly — every non-CLI consumer, including the
    tool layer — silently bypassed it. The budget is a property of the query, not
    of stdout.

    `limit` is explicit because the summary and a per-ticker section query have
    genuinely different sizes: the section query stays tight (that is the whole
    point of asking per section), while the summary grows with the book.
    """
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    size = len(text.encode("utf-8"))
    if size > limit:
        raise ValueError(f"decision packet query exceeds {limit} bytes: {size}")
    return text


def judgment_departures(packet: dict, overlay: dict) -> list[str]:
    """Tickers the judgment nominates as candidates against the add policy.

    The registered policy nominates a name only on an authorised evidence tier
    or an observed early trend. A judgment may nominate another; that is a
    strategy departure to be shown, not an error (#2842).
    """
    out = []
    for row in (overlay or {}).get("ticker_judgments") or []:
        if not isinstance(row, dict) or row.get("disposition") != "candidate":
            continue
        ticker = str(row.get("ticker") or "")
        quant = ((packet.get("tickers") or {}).get(ticker) or {}).get("quant") or {}
        if not (is_authorised_tier((quant.get("add_authority") or {}).get("tier"))
                or (quant.get("early_trend") or {}).get("observed")):
            out.append(ticker)
    return out


def query_view(packet: dict, ticker: str, section: str | None = None):
    """What a ticker query returns: the whole row, or one section of it.

    `_meta` carries the generation_id, and a narrowed payload must keep it: the
    protocol is generation-pinned and postflight validates a report against the
    exact generation the model read. Owned here so the CLI, the tool registry
    and `read_budget_report` measure and print the same bytes.
    """
    row = (packet.get("tickers") or {}).get(str(ticker))
    if row is None:
        raise ValueError(f"unknown ticker: {ticker}")
    if section is None:
        return row
    return {
        "_meta": packet.get("_meta"),
        "ticker": str(ticker),
        section: row.get(section),
    }


def _printed_bytes(value) -> int:
    return len((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _budget_row(read: str, value, budget: int) -> dict:
    size = _printed_bytes(value)
    return {
        "read": read,
        "bytes": size,
        "budget": budget,
        "ratio": round(size / budget, 3),
        "over_budget": size > budget,
        "near_budget": size > budget * READ_BUDGET_WARN_RATIO,
    }


def summary_budget_report(packet) -> dict:
    """How close the whole-book summary is to its budget.

    Exists so the next crossing is loud. The 2026-08-17 outage was silent
    precisely because nothing measured this until the tool already refused to
    run: adding a holding is what moves it, and adding a holding is not a change
    anybody thinks to run the packet tests for.
    """
    return {
        **_budget_row("summary", summary_view(packet), MAX_SUMMARY_BYTES),
        "tickers": len(packet.get("tickers") or {}),
    }


def read_budget_report(packet: dict) -> dict:
    """Every read the model can make of this packet, against that read's budget.

    One row for the summary, one for the judgment template, and the largest
    whole-row and single-section ticker queries. This is the budget surface:
    `ops/system_check.py` reads it off the latest generation every day, so a
    read that is filling up is a standing warning well before the tool refuses.
    """
    tickers = packet.get("tickers") or {}
    reads = [
        _budget_row("summary", summary_view(packet), MAX_SUMMARY_BYTES),
        _budget_row("judgment_template", judgment_template(packet), MAX_QUERY_BYTES),
    ]
    rows = [_budget_row(f"ticker:{ticker}", query_view(packet, ticker), MAX_QUERY_BYTES)
            for ticker in tickers]
    sections = [
        _budget_row(f"ticker:{ticker}:{section}",
                    query_view(packet, ticker, section), MAX_QUERY_BYTES)
        for ticker in tickers for section in QUERYABLE_SECTIONS
    ]
    for group in (rows, sections):
        if group:
            reads.append(max(group, key=lambda row: row["bytes"]))
    return {
        "packet_bytes": len(_compact(packet).encode("utf-8")),
        "tickers": len(tickers),
        "reads": reads,
        "near_budget": [row["read"] for row in reads if row["near_budget"]],
        "over_budget": [row["read"] for row in reads if row["over_budget"]],
    }


def _print_bounded(value, limit: int = MAX_QUERY_BYTES) -> None:
    print(bounded_payload(value, limit), end="")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--summary", action="store_true")
    group.add_argument("--ticker")
    group.add_argument("--judgment-template", action="store_true")
    parser.add_argument(
        "--section",
        choices=("facts", "technical", "quant", "sentiment", "evidence", "risk",
                 "constraints"),
    )
    args = parser.parse_args()
    packet = read_packet(args.manifest)
    limit = MAX_QUERY_BYTES
    if args.summary:
        value = summary_view(packet)
        limit = MAX_SUMMARY_BYTES
    elif args.judgment_template:
        value = judgment_template(packet)
    else:
        value = query_view(packet, args.ticker, args.section)
    _print_bounded(value, limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
