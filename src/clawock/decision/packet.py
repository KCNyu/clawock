"""Typed, queryable decision boundary for the daily deep brief.

The expensive producers remain authoritative for prices, technical indicators,
quant factors, evidence and risk.  This module only projects those results into
a compact contract:

* code owns facts, classifications and action bounds;
* the model owns a small judgment overlay made only of opinions;
* Pages receives a stable view-model and never re-implements the joins.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path

from clawock.decision.actions import ACTIVE_ACTIONS
from clawock.decision import add_alpha
from clawock.portfolio.instruments import get as instrument_metadata, is_leveraged_holding
from clawock.workspace import workspace_root


SCHEMA_VERSION = 1
JUDGMENT_SCHEMA_VERSION = 1
PAGES_SCHEMA_VERSION = 1
MAX_PACKET_BYTES = 96 * 1024
MAX_QUERY_BYTES = 24 * 1024
ADD_ALPHA_POLICY = workspace_root(Path.cwd()) / "config" / "add-alpha-policy.json"
VERDICTS = {"bullish", "neutral", "bearish", "mixed"}
TEXT_LIMITS = {
    "portfolio_assessment": 800,
    "portfolio_counterargument": 800,
    "assessment": 500,
    "counterargument": 500,
    "rationale": 500,
}


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
        else "off" if row.get("trend_on") is False or row.get("tag")
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
    return {
        "source_ticker": source_ticker,
        "is_proxy": bool(proxy),
        "status": row.get("status") or ("available" if row else "unavailable"),
        "as_of": row.get("row_as_of"),
        "tag": row.get("tag"),
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


def _thesis_view(context: dict, ticker: str) -> dict:
    row = (((context.get("thesis_registry") or {}).get("theses") or {})
           .get(ticker) or {"status": "unknown"})
    return {
        "status": row.get("status") or "unknown",
        "thesis_id": row.get("thesis_id"),
        "state": row.get("state") or "unknown",
        "checked_at": row.get("checked_at"),
    }


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

    target_max_pct = 60.0
    target_fraction = target_max_pct / 100
    # Solve (position + add) / (invested_book + add) <= target. Cash is an
    # affordability bound, not denominator camouflage.
    room_value = max(
        0.0,
        (target_fraction * capital - (current_value or 0))
        / (1 - target_fraction),
    )
    max_value = min(max(cash, 0.0), room_value)
    position_room_shares = (
        int(max_value // (price * lot)) * lot
        if price and lot else 0
    )
    setup_pcts = [
        row.get("tranche_pct_of_position")
        for row in technical.get("setups") or []
        if row.get("tranche_pct_of_position")
    ]
    tranche_pct = min(setup_pcts) if setup_pcts else 0.05
    overlay = overlay or {}
    sizing_multiplier = float(overlay.get("sizing_multiplier") or 1.0)
    desired = int(shares * tranche_pct * sizing_multiplier)
    rounded = ((desired // lot) * lot if lot else 0)
    if authority_tier == "exploration":
        unit_value = price * lot if price and lot else None
        exploration_budget = max(0.0, capital * exploration_max_book_pct)
        # 2.5% is the target step; the 3% market-book cap is the hard execution
        # envelope. One indivisible broker unit may bridge that small gap, but
        # an expensive HK board lot may not masquerade as a tiny experiment.
        suggested = (
            rounded if rounded > 0
            else lot if unit_value and unit_value <= exploration_budget
            else 0
        )
    else:
        # Existing validated/basic campaigns retain one market unit as their
        # minimum executable size, subject to cash and concentration room.
        suggested = max(lot, rounded) if lot else 0
    suggested = min(suggested, position_room_shares)
    max_tranche_shares = suggested

    thesis_state = thesis.get("state") or "unknown"
    if thesis_state in {"broken", "damaged", "weakening"}:
        thesis_gate = "blocked"
        max_tranche_shares = suggested = 0
    elif thesis_state == "intact":
        thesis_gate = "intact"
    else:
        # No canonical thesis is not treated as intact. It may gather one small
        # prospective sample, but cannot pyramid multiple tranches.
        thesis_gate = "exploration_only"
        max_tranche_shares = min(max_tranche_shares, suggested)

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
        "exploration_budget_value": round(
            max(0.0, capital * exploration_max_book_pct), 2
        ),
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
    }


def _add_alpha_policy(context: dict) -> dict:
    supplied = context.get("add_alpha_policy")
    if isinstance(supplied, dict) and supplied:
        return copy.deepcopy(supplied)
    return json.loads(ADD_ALPHA_POLICY.read_text(encoding="utf-8"))


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
        "reddit_mentions_7d": int(row.get("reddit_mentions_7d") or 0),
        "recent_move": row.get("recent_move") if isinstance(row.get("recent_move"), dict) else {},
        "headline_count": len(headlines),
        "headlines": headlines,
        "coverage": "available" if row else "missing",
    }


def _event_view(event: dict) -> dict:
    return {
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
        )
        if event.get(key) not in (None, "", [])
    }


def _risk_map(context: dict, active: set[str]) -> dict[str, list[dict]]:
    guardrail = context.get("risk_guardrail") or {}
    out = {ticker: [] for ticker in active}
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
                "severity": row.get("severity") or "high",
                "detail": row.get("detail"),
                "action_text": row.get("action"),
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
            "type": "leveraged_hard_stop",
            "severity": "critical",
            "detail": row.get("detail"),
            "action_text": row.get("action"),
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


def _status(technical: dict, risks: list[dict]) -> dict:
    if any(item.get("kind") == "hard_stop" for item in risks):
        return {"rank": 0, "label": "止损/换1x", "state": "critical"}
    if any(item.get("scope") == "ticker" for item in risks):
        return {"rank": 1, "label": "减仓", "state": "elevated"}
    if technical.get("trend") == "on":
        return {"rank": 4, "label": "趋势ON", "state": "positive"}
    if technical.get("rsi_state") == "oversold":
        return {"rank": 2, "label": "超卖·观望", "state": "elevated"}
    if technical.get("usable"):
        return {"rank": 3, "label": "趋势off·观望", "state": "neutral"}
    return {"rank": 5, "label": "数据不足", "state": "neutral"}


def _constraints(shares: int, risks: list[dict], actionable_ids: list[str],
                 technical: dict, execution: dict) -> dict:
    hard_stop = any(row.get("kind") == "hard_stop" for row in risks)
    direct_risk = bool(risks)
    if hard_stop:
        allowed = ["cut"]
        forced = ["cut"]
    elif direct_risk:
        allowed = ["trim_on_rebound", "cut"]
        forced = ["trim_on_rebound", "cut"]
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
    return {
        "allowed_actions": list(dict.fromkeys(allowed)),
        "forced_action_one_of": forced,
        "max_sell_shares": shares,
        "active_action_requires_evidence": True,
        "actionable_evidence_ids": actionable_ids,
        "technical_setup_ids": setup_ids,
        "max_add_shares": execution.get("max_add_shares", 0),
        "position_room_shares": execution.get("position_room_shares", 0),
        "max_add_value": execution.get("max_add_value", 0),
        "target_max_pct": execution.get("target_max_pct"),
        "min_tranche_shares": execution.get("min_tranche_shares"),
        "lot_size": execution.get("lot_size"),
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
    tickers = {}
    portfolios = (context.get("portfolio") or {}).get("portfolios") or {}
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

    for leg, holding in holdings:
        ticker = str(holding.get("ticker"))
        source_ticker = ticker if ticker in quant_rows else proxies.get(ticker, ticker)
        technical = _apply_setup_usage(_technical(
            quant_rows.get(source_ticker) or {},
            source_ticker,
            source_ticker != ticker,
        ), setup_usage.get(ticker) or {})
        matching_events = [
            _event_view(event) for event in events
            if str(event.get("ticker") or event.get("reported_ticker") or "")
            in {ticker, source_ticker}
        ]
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
        )
        if alpha_authority.get("tier") == "exploration":
            # A current-universe backfill can discover an interaction worth
            # collecting, but never upgrade itself into validated authority.
            alpha_authority["limitations"] = [
                "prospective_collection_only",
                "current_universe_survivorship_limit",
            ]
        alpha_setup = add_alpha.confirmation_setup(
            technical, alpha_authority, add_policy, ticker=ticker
        )
        if alpha_setup is not None:
            technical["setups"].append(alpha_setup)
            technical = _apply_setup_usage(
                technical, ticker_usage
            )
        execution = _execution_view(
            holding, leg, invested[leg], cash[leg], technical, thesis, leveraged,
            authority_tier=alpha_authority.get("tier") or "none",
            exploration_max_book_pct=float(
                add_policy.get("exploration_max_book_pct") or 0.03
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
                "activation": {
                    "factor": bool(
                        ((context.get("cross_sectional_factor") or {}).get("activation") or {})
                        .get("usable_for_decisions")
                    ),
                    "peer": bool(
                        ((context.get("peer_residual") or {}).get("rule_activation") or {})
                        .get("active")
                    ),
                },
            },
            "sentiment": _sentiment_view(sentiment_rows, ticker, source_ticker),
            "information": information_view,
            "evidence": matching_events,
            "risk": ticker_risks,
            "status": _status(technical, ticker_risks),
            "constraints": _constraints(
                shares, ticker_risks, actionable_ids, technical, execution
            ),
        }

    tier_counts = {"validated": 0, "exploration": 0, "none": 0}
    blocker_counts = {}
    candidates = []
    for ticker, row in tickers.items():
        authority = ((row.get("quant") or {}).get("add_authority") or {})
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
        constraints = row.get("constraints") or {}
        execution = row.get("execution") or {}
        allowed = "add_only_on_trigger" in (constraints.get("allowed_actions") or [])
        if tier == "none":
            state = "insufficient_evidence"
        elif setup is None:
            state = "waiting_timing"
        elif setup.get("remaining_tranches") == 0:
            state = "already_at_target"
        elif execution.get("blockers") or row.get("risk"):
            state = "risk_blocked"
        elif allowed:
            state = "eligible"
        else:
            state = "constraint_blocked"
        candidates.append({
            "ticker": ticker,
            "leg": row.get("leg"),
            "state": state,
            "tier": tier,
            "target_tranche_level": (
                0.25 if tier == "exploration" else 1.0 if tier == "validated" else 0.0
            ),
            "sources": list(authority.get("sources") or []),
            "authority_blockers": list(authority.get("blockers") or []),
            "entry_price": (setup or {}).get("entry_price"),
            "invalidation_price": (setup or {}).get("invalidation_price"),
            "max_add_shares": constraints.get("max_add_shares"),
            "allowed": allowed,
            "execution_blockers": list(execution.get("blockers") or []),
        })

    packet = {
        "_meta": {
            "schema_version": SCHEMA_VERSION,
            "kind": "brief_decision_packet",
            "generation_id": generation_id,
        },
        "date": context.get("date"),
        "generated_at": context.get("generated_at"),
        "integrity": {
            key: (context.get("integrity") or {}).get(key)
            for key in ("ok", "error_count", "warn_count")
            if key in (context.get("integrity") or {})
        },
        "portfolio": {
            "book_totals": context.get("book_totals") or {},
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
        "judgment_contract": {
            "schema_version": JUDGMENT_SCHEMA_VERSION,
            "verdicts": sorted(VERDICTS),
            "model_owned_fields": [
                "verdict", "confidence", "assessment", "counterargument", "rationale",
            ],
            "harness_owned_fields": [
                "facts", "technical", "quant", "sentiment collection",
                "evidence IDs", "risk", "status", "constraints",
            ],
        },
        "add_alpha_policy": {
            key: add_policy.get(key)
            for key in (
                "schema_version", "registered_at", "minimum_evidence_families",
                "confirmation_window_sessions", "exploration_max_tranches",
                "exploration_tranche_pct", "validated_max_tranches",
                "exploration_max_book_pct",
                "validated_tranche_pct", "markets", "discipline",
            )
        },
        "add_alpha_diagnostics": {
            "held_names": len(tickers),
            "tier_counts": tier_counts,
            "candidate_count": len(candidates),
            "authority_candidate_count": sum(
                row["tier"] in {"exploration", "validated"} for row in candidates
            ),
            "allowed_candidate_count": sum(bool(row["allowed"]) for row in candidates),
            "candidate_rate": round(sum(
                row["tier"] in {"exploration", "validated"} for row in candidates
            ) / len(tickers), 4) if tickers else 0,
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "candidates": candidates,
            "zero_output_visible": True,
        },
    }
    size = len(_compact(packet).encode("utf-8"))
    if size > MAX_PACKET_BYTES:
        raise ValueError(f"decision packet exceeds {MAX_PACKET_BYTES} bytes: {size}")
    return packet


def _decision_provenance(packet: dict, ticker: str) -> dict | None:
    """Machine-owned point-in-time signal state for one ledger decision."""
    row = (packet.get("tickers") or {}).get(str(ticker))
    if not row:
        return None
    execution = row.get("execution") or {}
    quant = row.get("quant") or {}
    return {
        "schema_version": 1,
        "context_generation_id": (packet.get("_meta") or {}).get("generation_id"),
        "observed_at": packet.get("generated_at"),
        "information": copy.deepcopy(row.get("information") or {}),
        "factor": copy.deepcopy(quant.get("factor") or {}),
        "peer_residual": copy.deepcopy(quant.get("peer_residual") or {}),
        "add_authority": copy.deepcopy(quant.get("add_authority") or {}),
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
    decision, rather than today's revised news/factor files.
    """
    bound = copy.deepcopy(plan)
    for decision in bound.get("decisions") or []:
        provenance = _decision_provenance(packet, decision.get("ticker"))
        if provenance is not None:
            decision["signal_provenance"] = provenance
        else:
            decision.pop("signal_provenance", None)
    return bound


def summary_view(packet: dict) -> dict:
    return {
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
                "risk_count": len(row.get("risk") or []),
                "constraints": row.get("constraints"),
            }
            for row in packet.get("tickers", {}).values()
        ],
        "judgment_contract": packet.get("judgment_contract"),
    }


def judgment_template(packet: dict) -> dict:
    generation_id = (packet.get("_meta") or {}).get("generation_id")
    return {
        "schema_version": JUDGMENT_SCHEMA_VERSION,
        "context_generation_id": generation_id,
        "portfolio_assessment": "",
        "portfolio_counterargument": "",
        "ticker_judgments": [
            {
                "ticker": ticker,
                "verdict": "neutral",
                "confidence": 0.5,
                "assessment": "",
                "counterargument": "",
                "rationale": "",
            }
            for ticker in packet.get("tickers", {})
        ],
    }


def validate_judgment_overlay(packet: dict, overlay: dict) -> list[str]:
    issues = []
    top_allowed = {
        "schema_version", "context_generation_id", "portfolio_assessment",
        "portfolio_counterargument", "ticker_judgments",
    }
    row_allowed = {
        "ticker", "verdict", "confidence", "assessment",
        "counterargument", "rationale",
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
        value = overlay.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"judgment {field} must be non-empty text")
        elif len(value) > TEXT_LIMITS[field]:
            issues.append(f"judgment {field} exceeds {TEXT_LIMITS[field]} chars")

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
        confidence = _number(row.get("confidence"))
        if confidence is None or not 0 <= confidence <= 1:
            issues.append(f"{label} confidence must be in [0,1]")
        for field in ("assessment", "counterargument", "rationale"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"{label} {field} must be non-empty text")
            elif len(value) > TEXT_LIMITS[field]:
                issues.append(f"{label} {field} exceeds {TEXT_LIMITS[field]} chars")
    missing = sorted(known - seen)
    if missing:
        issues.append(f"judgment missing active tickers: {missing}")
    return issues


def _catalyst_evidence_issues(tag: str, decision: dict, row: dict) -> list[str]:
    """Evidence check for a decision the model attributed to a catalyst.

    Two tiers, because `actionable_evidence_ids` only ever holds events flagged
    `actionable_escalation` — the escalation set, not the set of real events:

    * an ACTIVE action must point at an escalated event.  That is the harness
      rule named by the sibling constraint `active_action_requires_evidence`:
      you do not trade on a catalyst the harness did not escalate.
    * a PASSIVE stance only has to point at a real event for this ticker.
      "I'm watching CRCL because it reported Q2 yesterday" is a legitimate
      attribution, and requiring escalation there left the model no way to
      record it — the only ways past the gate were to relabel `driven_by` or to
      drop `evidence_event_id`, both of which destroy the attribution that
      `by_driver` win-rate bucketing reads.

    Both tiers still reject an id that matches no event, so a fabricated
    reference is caught either way.
    """
    evidence_id = decision.get("evidence_event_id")
    action = decision.get("action")
    if action in ACTIVE_ACTIONS:
        if evidence_id not in ((row.get("constraints") or {}).get("actionable_evidence_ids") or []):
            return [f"{tag}: evidence_event_id is outside harness evidence gate"]
        return []
    known_ids = {
        event.get("event_id") for event in (row.get("evidence") or [])
        if event.get("event_id")
    }
    if evidence_id not in known_ids:
        return [f"{tag}: evidence_event_id does not match any event for this ticker"]
    return []


def validate_plan_constraints(plan: dict, packet: dict) -> list[str]:
    issues = []
    rows = packet.get("tickers") or {}
    for index, decision in enumerate(plan.get("decisions") or []):
        ticker = str(decision.get("ticker") or "")
        tag = f"decision[{index}] {ticker}"
        row = rows.get(ticker)
        if not row:
            issues.append(f"{tag}: ticker is outside current decision packet")
            continue
        constraints = row.get("constraints") or {}
        action = decision.get("action")
        if action not in (constraints.get("allowed_actions") or []):
            issues.append(
                f"{tag}: action {action!r} outside harness allowed_actions "
                f"{constraints.get('allowed_actions') or []}"
            )
        if decision.get("driven_by") == "catalyst":
            issues.extend(_catalyst_evidence_issues(tag, decision, row))
        shares = _number((decision.get("size") or {}).get("shares"), 0)
        max_sell = _number(constraints.get("max_sell_shares"), 0)
        if (
            shares is not None and max_sell is not None
            and action in {"cut", "trim_on_rebound", "t_only"}
            and shares > max_sell
        ):
            issues.append(f"{tag}: size.shares {shares:g} exceeds holding {max_sell:g}")
        if action in {"add_only_on_trigger", "add_on_breakout"}:
            max_add = _number(constraints.get("max_add_shares"), 0) or 0
            lot = _number(constraints.get("lot_size"), 0)
            if shares is None or shares <= 0:
                issues.append(f"{tag}: add requires positive integer size.shares")
            elif int(shares) != shares:
                issues.append(f"{tag}: fractional shares are not supported")
            elif lot and int(shares) % int(lot) != 0:
                issues.append(
                    f"{tag}: size.shares {shares:g} is not a board-lot multiple of {lot:g}"
                )
            elif shares > max_add:
                issues.append(
                    f"{tag}: size.shares {shares:g} exceeds max_add_shares {max_add:g}"
                )

            condition = decision.get("condition") or {}
            price = _number(condition.get("price"), 4)
            setups = (row.get("technical") or {}).get("setups") or []
            approved = [
                setup for setup in setups
                if setup.get("setup_id") == decision.get("technical_setup_id")
                and setup.get("campaign_id") == decision.get("technical_campaign_id")
                and setup.get("setup_id") in (constraints.get("technical_setup_ids") or [])
                and setup.get("entry_type") == condition.get("type")
                and _number(setup.get("entry_price"), 4) == price
                and _number(setup.get("invalidation_price"), 4)
                    == _number(decision.get("invalidation_price"), 4)
                and setup.get("next_tranche_number") == decision.get("tranche_number")
            ]
            if action == "add_on_breakout":
                approved = [
                    setup for setup in approved
                    if setup.get("setup_id") == "confirmed_breakout"
                ]
            if not approved:
                issues.append(
                    f"{tag}: add condition does not match an approved technical setup"
                )
            elif int(condition.get("valid_for_sessions") or 1) != int(
                approved[0].get("valid_for_sessions") or 1
            ):
                issues.append(
                    f"{tag}: add condition validity does not match approved setup"
                )
    return issues


def compile_pages_projection(
    packet: dict,
    overlay: dict | None = None,
    overlay_issues: list[str] | None = None,
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
                    if direct else None
                ),
                "breach_ids": [
                    item.get("breach_id") for item in risks if item.get("breach_id")
                ],
            },
            "status": row.get("status"),
            "judgment": judgments.get(ticker),
        })
    rows.sort(
        key=lambda row: (
            (row.get("status") or {}).get("rank", 99),
            (row.get("facts") or {}).get("pnl_pct") or 0,
            row.get("ticker") or "",
        )
    )
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
    projection = compile_pages_projection(packet, overlay, issues)
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


def bounded_payload(value) -> str:
    """Serialise a query result, refusing anything over the per-query cap.

    The cap used to live only on the print path, so any caller that used
    read_packet()/summary_view() directly — every non-CLI consumer, including the
    tool layer — silently bypassed it. The budget is a property of the query, not
    of stdout.
    """
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    size = len(text.encode("utf-8"))
    if size > MAX_QUERY_BYTES:
        raise ValueError(f"decision packet query exceeds {MAX_QUERY_BYTES} bytes: {size}")
    return text


def _print_bounded(value) -> None:
    print(bounded_payload(value), end="")


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
    if args.summary:
        value = summary_view(packet)
    elif args.judgment_template:
        value = judgment_template(packet)
    else:
        value = (packet.get("tickers") or {}).get(str(args.ticker))
        if value is None:
            raise ValueError(f"unknown ticker: {args.ticker}")
        if args.section:
            value = {
                "_meta": packet.get("_meta"),
                "ticker": str(args.ticker),
                args.section: value.get(args.section),
            }
    _print_bounded(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
