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
import hashlib
import json
import math
import os
from pathlib import Path

from clawock.decision.actions import ACTIVE_ACTIONS


SCHEMA_VERSION = 1
JUDGMENT_SCHEMA_VERSION = 1
PAGES_SCHEMA_VERSION = 1
MAX_PACKET_BYTES = 96 * 1024
MAX_QUERY_BYTES = 24 * 1024
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
        "stop_distance_pct": stop_distance,
        "stop_state": (
            "breached" if stop_distance is not None and stop_distance < 0
            else "intact" if stop_distance is not None
            else "unknown"
        ),
        "usable": bool(row) and fresh,
    }


def _factor_view(row: dict) -> dict:
    row = row if isinstance(row, dict) else {}
    return {
        "as_of": row.get("feature_as_of"),
        "sector": row.get("sector"),
        "composite_score": _number(row.get("composite_score"), 4),
        "coverage_pct": _number(row.get("factor_coverage_pct"), 1),
        "relative_strength": _number(row.get("relative_strength"), 4),
        "breadth": _number(row.get("breadth"), 4),
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
        "usable_for_decisions": bool(row.get("usable_for_decisions")),
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
                "scope": "ticker" if row.get("ticker") else "candidate",
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


def _constraints(shares: int, risks: list[dict], actionable_ids: list[str]) -> dict:
    hard_stop = any(row.get("kind") == "hard_stop" for row in risks)
    direct_risk = any(row.get("scope") == "ticker" for row in risks)
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
            "add_only_on_trigger", "add_on_breakout",
        ]
    return {
        "allowed_actions": allowed,
        "forced_action_one_of": forced,
        "max_sell_shares": shares,
        "active_action_requires_evidence": True,
        "actionable_evidence_ids": actionable_ids,
    }


def compile_packet(context: dict, generation_id: str | None = None) -> dict:
    generation_id = generation_id or context.get("generation_id")
    if not generation_id:
        raise ValueError("decision packet requires context generation_id")
    quant_rows = (context.get("quant_signals") or {}).get("rows") or {}
    cross_rows = (context.get("cross_sectional_factor") or {}).get("held_rankings") or {}
    peer_rows = (context.get("peer_residual") or {}).get("held") or {}
    sentiment_rows = (context.get("sentiment") or {}).get("tickers") or []
    events = (context.get("news_evidence_graph") or {}).get("events") or []
    proxies = _proxy_map(context)
    holdings = list(_active_holdings(context))
    active = {str(holding.get("ticker")) for _, holding in holdings}
    risks = _risk_map(context, active)
    tickers = {}

    for leg, holding in holdings:
        ticker = str(holding.get("ticker"))
        source_ticker = ticker if ticker in quant_rows else proxies.get(ticker, ticker)
        technical = _technical(
            quant_rows.get(source_ticker) or {},
            source_ticker,
            source_ticker != ticker,
        )
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
            "quant": {
                "factor": _factor_view(cross_rows.get(source_ticker) or cross_rows.get(ticker)),
                "peer_residual": _peer_view(peer_rows.get(source_ticker) or peer_rows.get(ticker)),
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
            "evidence": matching_events,
            "risk": ticker_risks,
            "status": _status(technical, ticker_risks),
            "constraints": _constraints(shares, ticker_risks, actionable_ids),
        }

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
    }
    size = len(_compact(packet).encode("utf-8"))
    if size > MAX_PACKET_BYTES:
        raise ValueError(f"decision packet exceeds {MAX_PACKET_BYTES} bytes: {size}")
    return packet


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
                                "rsi_state", "stop_state", "usable")
                },
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
