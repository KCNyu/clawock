"""Reusable information-first strategy for primary disclosures.

The strategy accepts a generic portfolio, instrument registry, explicit policy
and workspace.  It owns discovery scope, signal state, exploration sizing and
event deduplication; it does not know a live instance, runtime, delivery target
or prose renderer.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clawock.decision import information_signals
from clawock.market_data import peer_quotes, primary_disclosures
from clawock.portfolio import instruments as default_instruments
from clawock.safe_io import safe_write_json


@dataclass(frozen=True)
class ActiveInformationPolicy:
    max_active_issuers: int
    window_minutes: int
    budget_s: float
    hk_exploration_lots: int
    us_exploration_shares: int
    signal: information_signals.InformationPolicy


DEFAULT_POLICY = ActiveInformationPolicy(
    max_active_issuers=4,
    window_minutes=240,
    budget_s=20,
    hk_exploration_lots=1,
    us_exploration_shares=1,
    signal=information_signals.InformationPolicy(
        positive_markers=(
            "盈喜", "盈利预喜", "正面盈利", "上调指引", "提高指引", "raise guidance",
            "raised guidance", "record revenue", "beats expectations", "股份回购",
            "购回股份", "buyback", "repurchase", "中标", "获得订单", "contract award",
            "awarded contract", "获批", "获得批准", "approved", "regulatory approval",
        ),
        negative_markers=(
            "盈利警告", "盈警", "下调指引", "cut guidance", "lowered guidance",
            "配售", "供股", "发行新股", "可转换债券", "先旧后新", "offering",
            "prospectus supplement", "at-the-market", "424b", "s-1", "s-3",
            "late filing", "nt 10-",
            "loss of customer", "default", "recall", "调查", "诉讼",
        ),
        eligible_markers=(
            "8-k", "6-k", "10-q", "10-k", "20-f", "annual report", "quarterly report",
            "results of operations", "sc 13d", "sc to", "425", "defm14a", "merger",
            "内幕消息", "须予公布的交易",
            "非常重大", "收购", "要约", "合并", "出售股权", "重大资产", "业绩公告",
            "中期业绩", "年度业绩", "季度业绩", "未经审核", "停牌", "短暂停止买卖",
            "复牌", "恢复买卖",
        ),
        ignored_markers=(
            "翌日披露报表", "月报表", "证券变动月报表", "下一营业日披露报表",
            "法律意见书", "律师事务所关于", "form 3", "form 4", "form 5",
            "statement of changes in beneficial ownership", "schedule 13g",
            "notice of proposed sale",
        ),
        categories=(
            ("dilution", ("配售", "供股", "发行新股", "可转换债券", "先旧后新",
                          "offering", "prospectus supplement", "at-the-market", "424b",
                          "s-1", "s-3")),
            ("filing_delay", ("late filing", "nt 10-")),
            ("profit_revision", ("盈利警告", "盈警", "盈喜", "盈利预喜", "上调指引",
                                 "raise guidance", "raised guidance")),
            ("capital_return", ("股份回购", "购回股份", "buyback", "repurchase")),
            ("ownership", ("13d",)),
            ("results", ("10-q", "10-k", "20-f", "annual report", "quarterly report",
                         "results of operations", "业绩公告", "中期业绩", "年度业绩", "季度业绩")),
            ("corporate_action", ("merger", "sc to", "425", "defm14a", "收购", "要约",
                                  "合并", "出售股权", "重大资产")),
            ("inside_information", ("内幕消息", "须予公布的交易", "非常重大")),
            ("trading_status", ("停牌", "短暂停止买卖", "复牌", "恢复买卖")),
        ),
        hot_reaction_pct=3.0,
        contradicted_reaction_pct=-2.0,
    ),
)


def _load_portfolio(path):
    try:
        doc = json.loads(Path(path).read_text())
        return doc if isinstance(doc, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def active_issuer_scope(portfolio: dict, market: str, *, registry) -> list[dict]:
    """Deduplicated reporting issuers behind active holdings for one market."""
    leg = "hk_stocks" if market == "hk" else "us_stocks"
    holdings = ((portfolio.get("portfolios") or {}).get(leg) or {}).get("holdings") or []
    by_issuer = {}
    for holding in holdings:
        if not isinstance(holding, dict) or (holding.get("shares") or 0) <= 0:
            continue
        ticker = str(holding.get("ticker") or "")
        target = default_instruments.look_through(ticker, registry=registry)
        issuer = target.get("issuer")
        if not issuer:
            continue
        row = by_issuer.setdefault(str(issuer), {
            "issuer": str(issuer), "holdings": [], "direct_holdings": [],
            "proxy_holdings": [], "leveraged_only": True, "board_lot": None,
        })
        row["holdings"].append(ticker)
        leveraged = default_instruments.is_leveraged_holding(holding, registry=registry)
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
        issuer, item.get("published_at"), item.get("source_url"), item.get("title")
    ))
    return "primary:" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def _exploration_hint(scope: dict, market: str, disposition: str, reaction,
                      *, registry, policy) -> dict | None:
    if (disposition != "candidate" or not isinstance(reaction, (int, float))
            or scope.get("leveraged_only")):
        return None
    issuer = scope["issuer"]
    meta = default_instruments.get(issuer, registry=registry) or {}
    if float(meta.get("leverage_multiple") or 1) > 1:
        return None
    if market == "hk":
        lot = scope.get("board_lot")
        if not isinstance(lot, int) or lot <= 0:
            return None
        shares = lot * int(policy.hk_exploration_lots)
        unit = "one_board_lot" if policy.hk_exploration_lots == 1 else "board_lots"
    else:
        shares = int(policy.us_exploration_shares)
        unit = "one_share" if shares == 1 else "shares"
    return {
        "ticker": issuer, "shares": shares, "unit": unit,
        "status": "unvalidated_exploration_hint",
        "is_order": False,
        "requires": ["independent_support", "cash_gate", "risk_gate", "execution_review"],
    }


def scan(portfolio: dict | None, *, market: str, policy=DEFAULT_POLICY, now=None, http=None,
         quote_fetcher=peer_quotes.fetch_all, disclosure_probe=primary_disclosures.probe,
         registry) -> dict:
    """Scan the bounded live issuer set before any price-anomaly filter."""
    now = now or datetime.now(timezone.utc)
    scope = active_issuer_scope(
        portfolio or {}, market, registry=registry,
    )
    chased = scope[:policy.max_active_issuers]
    skipped = scope[policy.max_active_issuers:]
    issuers = [row["issuer"] for row in chased]
    evidence = disclosure_probe(
        issuers, market=market, now=now, http=http,
        window_minutes=policy.window_minutes, budget_s=policy.budget_s,
        max_issuers=policy.max_active_issuers,
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
    source_health_by_issuer = {}
    for target in chased:
        issuer = target["issuer"]
        entry = ((evidence.get("issuers") or {}).get(issuer) or {})
        status_by_issuer[issuer] = entry.get("status") or "not_checked"
        source_health_by_issuer[issuer] = {
            "healthy_sources": list(entry.get("healthy_sources") or []),
            "degraded_sources": list(entry.get("degraded_sources") or []),
            "partial_degradation": bool(entry.get("partial_degradation")),
        }
        quote = quotes.get(issuer) or {}
        reaction = quote.get("pct_1d") if not quote.get("stale_quote") else None
        for item in (entry.get("events") or []):
            if item.get("evidence_tier") != "primary":
                continue
            signal = information_signals.evaluate(item, reaction, policy.signal)
            if signal is None:
                continue
            disposition = signal["disposition"]
            blockers = list(signal["blockers"])
            if item.get("time_precision") == "date":
                blockers.append("filing_time_unavailable")
                if disposition == "candidate":
                    disposition = "wait"
            if target.get("leveraged_only"):
                blockers.append("leveraged_holding_cannot_take_unvalidated_exploration")
            hint = _exploration_hint(
                target, market, disposition, reaction,
                registry=registry, policy=policy,
            )
            if disposition == "candidate" and hint is None:
                if market == "hk":
                    blockers.append("verified_board_lot_unavailable")
                elif not isinstance(reaction, (int, float)):
                    blockers.append("price_required_before_exploration")
            published = item.get("published_at")
            try:
                expires = datetime.fromisoformat(str(published).replace("Z", "+00:00")) + timedelta(
                    minutes=policy.window_minutes
                )
                expires_at = expires.isoformat()
            except (TypeError, ValueError):
                expires_at = None
            rows.append({
                "event_id": _event_id(issuer, item),
                "issuer": issuer,
                "held_via": target["holdings"],
                "published_at": published,
                "filed_date": item.get("filed_date"),
                "observed_at": item.get("observed_at"),
                "time_precision": item.get("time_precision"),
                "freshness_status": item.get("freshness_status"),
                "expires_at": expires_at,
                "source_url": item.get("source_url"),
                "source_class": item.get("source_class"),
                "source_quality": "primary",
                **{key: value for key, value in signal.items()
                   if key not in {"disposition", "blockers"}},
                "session_reaction_pct": reaction,
                "reaction_source": quote.get("source"),
                "disposition": disposition,
                "blockers": sorted(set(blockers)),
                "exploration_hint": hint,
            })
    rows.sort(key=lambda row: (row.get("published_at") or "", row["issuer"]), reverse=True)
    return {
        "schema_version": 1,
        "as_of": now.isoformat(),
        "market": market,
        "scope": chased,
        "skipped_scope": [row["issuer"] for row in skipped],
        "issuer_status": status_by_issuer,
        "issuer_source_health": source_health_by_issuer,
        "collection": evidence.get("collection") or {},
        "candidates": rows,
        "candidate_count": sum(row["disposition"] == "candidate" for row in rows),
        "wait_count": sum(row["disposition"] == "wait" for row in rows),
        "reject_count": sum(row["disposition"] == "reject" for row in rows),
        "degraded_issuers": sorted(
            issuer for issuer, status in status_by_issuer.items() if status == "degraded"
        ),
        "partially_degraded_issuers": sorted(
            issuer for issuer, health in source_health_by_issuer.items()
            if health["partial_degradation"]
        ),
        "discipline": (
            "primary disclosure first; session reaction is a timing check; candidate visibility "
            "does not grant order authority or validated sizing"
        ),
    }


def scan_workspace(workspace, market: str, *, policy=DEFAULT_POLICY, **kwargs) -> dict:
    workspace = Path(workspace)
    registry = default_instruments.load_registry(
        workspace / "config" / "instruments.json", missing_ok=True,
    )
    if "disclosure_probe" not in kwargs:
        cache_path = workspace / ".cache" / f"primary-disclosures-{market}.json"

        def cached_probe(issuers, **probe_kwargs):
            return primary_disclosures.probe_cached(
                issuers, cache_path=cache_path, cache_ttl_seconds=300,
                **probe_kwargs,
            )

        kwargs["disclosure_probe"] = cached_probe
    result = scan(
        _load_portfolio(workspace / "portfolio.json"), market=market,
        policy=policy, registry=registry, **kwargs,
    )
    path = workspace / "memory" / ".tmp" / f"active-information-seen-{market}.json"
    try:
        seen_doc = json.loads(path.read_text()) if path.exists() else {}
        seen = seen_doc.get("events") if isinstance(seen_doc, dict) else {}
        seen = seen if isinstance(seen, dict) else {}
    except (OSError, json.JSONDecodeError):
        seen = {}
    new_ids = []
    now_text = result["as_of"]
    for row in result["candidates"]:
        row["is_new"] = row["event_id"] not in seen
        if row["is_new"]:
            new_ids.append(row["event_id"])
            seen[row["event_id"]] = now_text
    # Preserve ids across a temporary source outage: clearing the cursor merely
    # because this slot fetched nothing would re-alert the same filing on recovery.
    # One day is bounded yet comfortably longer than the four-hour evidence window.
    cutoff = datetime.fromisoformat(now_text) - timedelta(days=1)
    fresh_seen = {}
    for event_id, first_seen in seen.items():
        try:
            if datetime.fromisoformat(str(first_seen).replace("Z", "+00:00")) >= cutoff:
                fresh_seen[event_id] = first_seen
        except (TypeError, ValueError):
            continue
    seen = fresh_seen
    result["new_event_ids"] = new_ids
    result["new_candidate_count"] = len(new_ids)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_json(str(path), {"schema_version": 1, "events": seen})
    except OSError as exc:
        # Losing dedup state may repeat one alert, but must never erase evidence or
        # break the market slot.  Make that degradation inspectable in context.
        result["cursor_error"] = f"{type(exc).__name__}: {exc}"[:160]
    return result
