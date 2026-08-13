"""KCNyu information-first intraday candidates from primary disclosures.

This is instance policy, not portable clawock core: it knows the KCNyu live book,
the one-lot/one-share exploration preference and the held proxy universe.  Core
provides bounded disclosure evidence and instrument primitives; this adapter
chooses what to scan and how to surface a candidate.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clawock.market_data import mover_evidence, peer_quotes
from clawock.portfolio import instruments
from clawock.workspace import workspace_root


WS = workspace_root(Path.cwd())
PORTFOLIO = WS / "portfolio.json"
MAX_ACTIVE_ISSUERS = 4
HOT_REACTION_PCT = 3.0
CONTRADICTED_REACTION_PCT = -2.0
POSITIVE_TERMS = (
    "盈喜", "盈利预喜", "正面盈利", "上调指引", "提高指引", "raise guidance",
    "raised guidance", "record revenue", "beats expectations", "股份回购",
    "购回股份", "buyback", "repurchase", "中标", "获得订单", "contract award",
    "awarded contract", "获批", "获得批准", "approved", "regulatory approval",
)
NEGATIVE_TERMS = (
    "盈利警告", "盈警", "下调指引", "cut guidance", "lowered guidance",
    "配售", "供股", "发行新股", "可转换债券", "先旧后新", "offering",
    "prospectus supplement", "at-the-market", "late filing", "nt 10-",
    "loss of customer", "default", "recall", "调查", "诉讼",
)


def _load_portfolio(path=PORTFOLIO):
    try:
        doc = json.loads(Path(path).read_text())
        return doc if isinstance(doc, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def active_issuer_scope(portfolio: dict, market: str) -> list[dict]:
    """Deduplicated reporting issuers behind active holdings for one market."""
    leg = "hk_stocks" if market == "hk" else "us_stocks"
    holdings = ((portfolio.get("portfolios") or {}).get(leg) or {}).get("holdings") or []
    by_issuer = {}
    for holding in holdings:
        if not isinstance(holding, dict) or (holding.get("shares") or 0) <= 0:
            continue
        ticker = str(holding.get("ticker") or "")
        target = instruments.look_through(ticker)
        issuer = target.get("issuer")
        if not issuer:
            continue
        row = by_issuer.setdefault(str(issuer), {
            "issuer": str(issuer), "holdings": [], "direct_holdings": [],
            "proxy_holdings": [], "leveraged_only": True, "board_lot": None,
        })
        row["holdings"].append(ticker)
        leveraged = instruments.is_leveraged_holding(holding)
        if ticker == issuer:
            row["direct_holdings"].append(ticker)
            if not leveraged:
                row["leveraged_only"] = False
                if market == "hk" and holding.get("lot_size"):
                    row["board_lot"] = int(holding["lot_size"])
        else:
            row["proxy_holdings"].append(ticker)
    return [
        {**row, "holdings": sorted(set(row["holdings"])),
         "direct_holdings": sorted(set(row["direct_holdings"])),
         "proxy_holdings": sorted(set(row["proxy_holdings"]))}
        for _, row in sorted(by_issuer.items())
    ]


def _event_id(issuer: str, item: dict) -> str:
    if item.get("accession"):
        return f"sec:{item['accession']}"
    raw = "|".join(str(value or "") for value in (
        issuer, item.get("published_at"), item.get("url"), item.get("raw_title") or item.get("title")
    ))
    return "primary:" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def extract_expectation(item: dict) -> dict:
    """Classify only language attributable to the primary item itself."""
    title = str(item.get("raw_title") or item.get("title") or "")
    folded = title.casefold()
    negative = next((term for term in NEGATIVE_TERMS if term.casefold() in folded), None)
    positive = next((term for term in POSITIVE_TERMS if term.casefold() in folded), None)
    rule = str(item.get("triage_rule") or "")
    if negative:
        direction = "negative"
        marker = negative
    elif positive:
        direction = "positive"
        marker = positive
    elif rule in {"us-offering", "us-late-filing", "hk-equity-raise", "hk-profit-alert"}:
        # hk-profit-alert combines 盈喜 and 盈警, so only explicit terms above may
        # resolve it.  The other three rule ids are directionally unambiguous.
        if rule == "hk-profit-alert":
            direction, marker = "unknown", None
        else:
            direction, marker = "negative", rule
    else:
        direction, marker = "unknown", None
    category = {
        "us-offering": "dilution", "hk-equity-raise": "dilution",
        "us-late-filing": "filing_delay", "hk-profit-alert": "profit_revision",
        "hk-buyback-programme": "capital_return", "us-13d-activist": "ownership",
        "us-8k": "material_event", "us-periodic": "results",
        "hk-results": "results", "hk-mna": "corporate_action",
        "us-mna": "corporate_action", "hk-inside-information": "inside_information",
    }.get(rule, "material_disclosure")
    return {
        "direction": direction,
        "category": category,
        "detail": title,
        "explicit_marker": marker,
        "detail_status": "explicit" if direction != "unknown" else "needs_detail_extraction",
    }


def _disposition(direction: str, reaction, *, leveraged_only=False) -> tuple[str, list[str]]:
    blockers = ["candidate_is_not_order_authority"]
    if direction == "negative":
        return "reject", blockers + ["adverse_primary_disclosure"]
    if direction != "positive":
        return "wait", blockers + ["needs_detail_extraction"]
    if not isinstance(reaction, (int, float)):
        # Do not erase the event merely because price coverage failed.  It stays a
        # candidate hint, but exploration remains blocked below.
        blockers.append("price_reaction_unavailable")
        if leveraged_only:
            blockers.append("leveraged_holding_cannot_take_unvalidated_exploration")
        return "candidate", blockers
    if reaction >= HOT_REACTION_PCT:
        return "wait", blockers + ["price_already_reacted"]
    if reaction <= CONTRADICTED_REACTION_PCT:
        return "wait", blockers + ["tape_contradicts_positive_event"]
    if leveraged_only:
        blockers.append("leveraged_holding_cannot_take_unvalidated_exploration")
    return "candidate", blockers


def _exploration_hint(scope: dict, market: str, disposition: str, reaction) -> dict | None:
    if disposition != "candidate" or not isinstance(reaction, (int, float)):
        return None
    issuer = scope["issuer"]
    meta = instruments.get(issuer) or {}
    if float(meta.get("leverage_multiple") or 1) > 1:
        return None
    if market == "hk":
        lot = scope.get("board_lot")
        if not isinstance(lot, int) or lot <= 0:
            return None
        shares, unit = lot, "one_board_lot"
    else:
        shares, unit = 1, "one_share"
    return {
        "ticker": issuer, "shares": shares, "unit": unit,
        "status": "unvalidated_exploration_hint",
        "is_order": False,
        "requires": ["independent_support", "cash_gate", "risk_gate", "execution_review"],
    }


def scan(portfolio: dict | None, *, market: str, now=None, http=None,
         quote_fetcher=peer_quotes.fetch_all) -> dict:
    """Scan the bounded live issuer set before any price-anomaly filter."""
    now = now or datetime.now(timezone.utc)
    scope = active_issuer_scope(portfolio or {}, market)
    chased, skipped = scope[:MAX_ACTIVE_ISSUERS], scope[MAX_ACTIVE_ISSUERS:]
    issuers = [row["issuer"] for row in chased]
    evidence = mover_evidence.probe(
        issuers, market=market, now=now, http=http, primary_only=True,
    ) if issuers else {}
    try:
        quotes = quote_fetcher(
            [{"ticker": issuer, "region": market} for issuer in issuers],
            deadline_s=12, workers=min(4, len(issuers)),
        ) if issuers else {}
    except Exception as exc:  # noqa: BLE001 - discovery must not red the slot
        quotes = {issuer: {"error_fetch": type(exc).__name__} for issuer in issuers}

    rows = []
    status_by_issuer = {}
    for target in chased:
        issuer = target["issuer"]
        entry = ((evidence.get("tickers") or {}).get(issuer) or {})
        status_by_issuer[issuer] = entry.get("status") or "not_checked"
        quote = quotes.get(issuer) or {}
        reaction = quote.get("pct_1d") if not quote.get("stale_quote") else None
        primary_interrupts = [
            item for item in (entry.get("items") or [])
            if item.get("tier") == mover_evidence.PRIMARY
            and item.get("signal") == mover_evidence.INTERRUPT
        ]
        for item in primary_interrupts:
            expectation = extract_expectation(item)
            disposition, blockers = _disposition(
                expectation["direction"], reaction,
                leveraged_only=bool(target.get("leveraged_only")),
            )
            hint = _exploration_hint(target, market, disposition, reaction)
            if disposition == "candidate" and hint is None:
                if market == "hk":
                    blockers.append("verified_board_lot_unavailable")
                elif not isinstance(reaction, (int, float)):
                    blockers.append("price_required_before_exploration")
            published = item.get("published_at")
            try:
                expires = datetime.fromisoformat(str(published).replace("Z", "+00:00")) + timedelta(
                    minutes=mover_evidence.WINDOW_MINUTES
                )
                expires_at = expires.isoformat()
            except (TypeError, ValueError):
                expires_at = None
            rows.append({
                "event_id": _event_id(issuer, item),
                "issuer": issuer,
                "held_via": target["holdings"],
                "published_at": published,
                "expires_at": expires_at,
                "source_url": item.get("url"),
                "source_class": item.get("source_class"),
                "source_quality": "primary",
                **expectation,
                "session_reaction_pct": reaction,
                "reaction_source": quote.get("source"),
                "disposition": disposition,
                "blockers": sorted(set(blockers)),
                "exploration_hint": hint,
                "falsifier": (
                    "price rejects the disclosure or a later primary filing reverses the detail"
                    if expectation["direction"] == "positive" else
                    "a later primary filing resolves or reverses the adverse/unknown detail"
                ),
                "next_evidence": (
                    "independent support plus non-overheated price confirmation"
                    if expectation["detail_status"] == "explicit" else
                    "extract the attributable filing detail before any directional action"
                ),
                "judge_contract": {
                    "allowed": ["candidate", "wait", "reject"],
                    "may_upgrade": False,
                    "precomputed": disposition,
                },
            })
    rows.sort(key=lambda row: (row.get("published_at") or "", row["issuer"]), reverse=True)
    return {
        "schema_version": 1,
        "as_of": now.isoformat(),
        "market": market,
        "scope": chased,
        "skipped_scope": [row["issuer"] for row in skipped],
        "issuer_status": status_by_issuer,
        "candidates": rows,
        "candidate_count": sum(row["disposition"] == "candidate" for row in rows),
        "wait_count": sum(row["disposition"] == "wait" for row in rows),
        "reject_count": sum(row["disposition"] == "reject" for row in rows),
        "degraded_issuers": sorted(
            issuer for issuer, status in status_by_issuer.items() if status == "degraded"
        ),
        "discipline": (
            "primary disclosure first; session reaction is a timing check; candidate visibility "
            "does not grant order authority or validated sizing"
        ),
    }


def scan_workspace(market: str, **kwargs) -> dict:
    return scan(_load_portfolio(), market=market, **kwargs)
