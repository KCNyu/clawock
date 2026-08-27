"""Primary-source earnings review and management accountability ledger.

The artifact under `memory/earnings/<TICKER>/<period>.json` is the canonical
record of one reporting period: which documents were actually read, the
comparable history the numbers were judged against, the earnings-quality math,
the promises management has outstanding, and the evidence this hands to the
thesis registry.

Three rules shape everything here:

1. Numbers are Decimal strings end to end, and every published number must clear
   `clawock.provenance.validate_manifest` (two independent sources)
   before the
   artifact can be released.
2. Earnings quality is computed in code from the comparable history, never
   asserted in prose. A missing input yields `unavailable` plus a reason, not a
   number.
3. This module produces thesis *evidence*. It never sets thesis state — that
   stays with `thesis_registry.evaluate_drift`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from clawock import provenance as research_provenance
from clawock.workspace import engine_config, workspace_root
from clawock.safe_io import parse_iso_utc as _parse_time

WS = workspace_root(Path.cwd())
SCHEMA_FILE = engine_config("earnings_review.schema.json")
ARTIFACT_ROOT = WS / "memory" / "earnings"
SCHEMA_VERSION = 1

MARKETS = {"US", "HK"}
# Source classes, ordered by how directly they come from the issuer. Only a
# primary class can support a footnote claim.
PRIMARY_SOURCES = {"sec_filing", "hkex_announcement", "issuer_ir"}
STRUCTURED_SOURCES = {"sec_xbrl", "eastmoney_fundamentals"}
THIRD_PARTY_SOURCES = {"third_party_summary"}
SOURCE_CLASSES = PRIMARY_SOURCES | STRUCTURED_SOURCES | THIRD_PARTY_SOURCES
# US filings are GAAP; HK issuers report under IFRS/HKFRS. A non-GAAP headline is
# a separate basis and may never be compared against a GAAP one.
BASES = {"GAAP", "IFRS", "HKFRS", "non_GAAP"}
MARKET_BASES = {"US": {"GAAP", "non_GAAP"}, "HK": {"IFRS", "HKFRS", "non_GAAP"}}
# README 契约:盈利质量从「至少四个可比期」算。每个节奏都要求 ≥4 期——
# annual 发行人也需要四个财年(曾为 3,与文档口径不一致,见 #1097)。
CADENCES = {"quarterly": 4, "semiannual": 4, "annual": 4}
FOOTNOTE_CATEGORIES = {
    "related_party", "contingency", "accounting_policy_change",
    "goodwill_intangibles", "customer_concentration", "supplier_concentration",
}
COMMITMENT_STATUSES = {"met", "partial", "missed", "not_due", "unverifiable"}
TERMINAL_COMMITMENT_STATUSES = {"met", "partial", "missed"}
CAPITAL_EVENTS = {
    "buyback", "dividend", "acquisition", "divestiture", "debt_raise",
    "debt_repayment", "equity_raise", "new_business_spend",
}
ARTIFACT_FIELDS = (
    "schema_version", "artifact_id", "ticker", "market", "cadence", "currency",
    "unit", "basis", "period", "published_at", "documents", "comparables",
    "segments", "guidance", "footnotes", "management_commitments",
    "capital_allocation", "thesis_link", "provenance",
)
NUMERIC_FIELDS = (
    "revenue", "operating_income", "net_income", "ocf", "capex",
    "receivables", "inventory", "sbc", "diluted_shares", "cash", "debt",
    "eps_diluted",
)
REQUIRED_COMPARABLE_FIELDS = ("revenue", "net_income", "ocf")
# Named, documented thresholds. Earnings quality is a deterministic verdict on
# these, not a model's impression.
THRESHOLDS = {
    "cash_conversion_min": Decimal("0.8"),       # OCF / net income
    "working_capital_gap_pp": Decimal("15"),     # receivables/inventory growth − revenue growth
    "dilution_pct": Decimal("5"),                # diluted share count growth
    "sbc_pct_revenue": Decimal("15"),
    "guidance_tolerance_pct": Decimal("1"),
}
GRADES = ("A", "B", "C")
QUANTUM = Decimal("0.0001")


def _d(value, field, errors=None):
    """Parse a Decimal string; append an error and return None when malformed."""
    if value is None:
        return None
    try:
        return research_provenance.decimal_value(value, field)
    except ValueError as exc:
        if errors is not None:
            errors.append(str(exc))
        return None


def _exact_fields(item, required, optional, prefix, errors):
    if not isinstance(item, dict):
        errors.append(f"{prefix} must be an object")
        return False
    missing = sorted(set(required) - set(item))
    extra = sorted(set(item) - set(required) - set(optional))
    if missing:
        errors.append(f"{prefix} missing fields: {missing}")
    if extra:
        errors.append(f"{prefix} unknown fields: {extra}")
    return not missing and not extra


def _parse_date(value, field, errors):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        errors.append(f"{field} must be an ISO-8601 date (YYYY-MM-DD)")
        return None




def grade_sources(documents: list) -> dict:
    """Grade information availability from the documents actually retrieved.

    A — a primary issuer document covering the period, plus a structured dataset
        to verify the numbers against.
    B — no covering primary document, but a structured dataset carries numbers.
    C — only third-party summaries: numbers are unverified and footnote claims
        are not available at all.

    A low grade is a statement about the sources, never about the company.
    """
    classes = {
        doc.get("source_class") for doc in documents if isinstance(doc, dict)
    }
    covering_primary = {
        doc.get("source_class") for doc in documents
        if isinstance(doc, dict) and doc.get("covers_period") is True
        and doc.get("source_class") in PRIMARY_SOURCES
    }
    structured = classes & STRUCTURED_SOURCES
    if covering_primary and structured:
        grade = "A"
    elif structured:
        grade = "B"
    else:
        grade = "C"
    gaps = []
    if not covering_primary:
        gaps.append("no primary issuer document covers the reporting period")
    if not structured:
        gaps.append("no structured dataset available to verify reported numbers")
    if classes & THIRD_PARTY_SOURCES:
        gaps.append("third-party summaries are present and rank below issuer sources")
    return {
        "grade": grade,
        "footnote_claims_allowed": bool(covering_primary),
        "source_classes": sorted(c for c in classes if c),
        "gaps": gaps,
    }


def _validate_documents(doc, errors):
    documents = doc.get("documents")
    if not isinstance(documents, list) or not documents:
        errors.append("documents must be a non-empty list")
        return {}
    by_id = {}
    for index, item in enumerate(documents):
        prefix = f"documents[{index}]"
        if not _exact_fields(
            item,
            ("document_id", "source_class", "locator", "retrieved_at", "covers_period"),
            (), prefix, errors,
        ):
            continue
        if item["source_class"] not in SOURCE_CLASSES:
            errors.append(f"{prefix}.source_class must be one of {sorted(SOURCE_CLASSES)}")
        if not isinstance(item["covers_period"], bool):
            errors.append(f"{prefix}.covers_period must be a boolean")
        if not item["locator"]:
            errors.append(f"{prefix}.locator is required")
        _parse_time(item["retrieved_at"], f"{prefix}.retrieved_at", errors)
        if item["document_id"] in by_id:
            errors.append(f"{prefix}.document_id must be unique")
        else:
            by_id[item["document_id"]] = item
    return by_id


def _validate_period(period, prefix, errors):
    if not _exact_fields(period, ("label", "end_date"), (), prefix, errors):
        return None
    if not period.get("label"):
        errors.append(f"{prefix}.label is required")
    return _parse_date(period.get("end_date"), f"{prefix}.end_date", errors)


def _validate_comparables(doc, errors):
    comparables = doc.get("comparables")
    cadence = doc.get("cadence")
    minimum = CADENCES.get(cadence)
    if not isinstance(comparables, list) or not comparables:
        errors.append("comparables must be a non-empty list")
        return []
    if minimum and len(comparables) < minimum:
        errors.append(
            f"{cadence} cadence needs at least {minimum} comparable periods, got {len(comparables)}"
        )
    rows, seen_labels, end_dates = [], set(), []
    for index, item in enumerate(comparables):
        prefix = f"comparables[{index}]"
        if not _exact_fields(
            item, ("period", "basis", "currency", "unit"), NUMERIC_FIELDS, prefix, errors
        ):
            continue
        end_date = _validate_period(item.get("period"), f"{prefix}.period", errors)
        label = (item.get("period") or {}).get("label")
        if label in seen_labels:
            errors.append(f"{prefix}.period.label must be unique")
        seen_labels.add(label)
        # A basis, currency or unit switch mid-history silently changes what the
        # trend means, so it is an error rather than a footnote.
        for field in ("basis", "currency", "unit"):
            if item.get(field) != doc.get(field):
                errors.append(
                    f"{prefix}.{field} ({item.get(field)!r}) does not match the artifact "
                    f"{field} ({doc.get(field)!r}); mixed {field} cannot be compared"
                )
        for field in REQUIRED_COMPARABLE_FIELDS:
            if item.get(field) in (None, ""):
                errors.append(f"{prefix}.{field} is required to judge earnings quality")
        parsed = {"label": label, "end_date": end_date}
        for field in NUMERIC_FIELDS:
            parsed[field] = _d(item.get(field), f"{prefix}.{field}", errors)
        rows.append(parsed)
        if end_date:
            end_dates.append(end_date)
    if end_dates != sorted(end_dates):
        errors.append("comparables must be ordered oldest first by period.end_date")
    if rows and doc.get("period", {}).get("label") != rows[-1]["label"]:
        errors.append("the last comparable must be the artifact's reporting period")
    return rows


def _validate_commitments(doc, by_id, errors):
    commitments = doc.get("management_commitments")
    if not isinstance(commitments, list):
        errors.append("management_commitments must be a list")
        return []
    seen = set()
    for index, item in enumerate(commitments):
        prefix = f"management_commitments[{index}]"
        if not _exact_fields(
            item,
            ("commitment_id", "statement", "source_document_id", "made_at",
             "due_date", "target_metric", "target_value", "actual_value", "status"),
            (), prefix, errors,
        ):
            continue
        if item["commitment_id"] in seen:
            errors.append(f"{prefix}.commitment_id must be unique")
        seen.add(item["commitment_id"])
        for field in ("statement", "target_metric"):
            if not item.get(field):
                errors.append(f"{prefix}.{field} is required")
        if item["source_document_id"] not in by_id:
            errors.append(f"{prefix}.source_document_id is not a listed document")
        _parse_date(item["made_at"], f"{prefix}.made_at", errors)
        _parse_date(item["due_date"], f"{prefix}.due_date", errors)
        if item["status"] not in COMMITMENT_STATUSES:
            errors.append(f"{prefix}.status must be one of {sorted(COMMITMENT_STATUSES)}")
        if item["status"] in TERMINAL_COMMITMENT_STATUSES and item["actual_value"] in (None, ""):
            errors.append(f"{prefix} claims {item['status']} without an actual_value")
        if item["status"] == "not_due" and item["actual_value"] not in (None, ""):
            errors.append(f"{prefix} is not_due but already carries an actual_value")
    return commitments


def validate_artifact(doc: dict, *, now=None) -> list[str]:
    """Return every reason this artifact may not be trusted; empty means valid."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["artifact must be an object"]
    _exact_fields(doc, ARTIFACT_FIELDS, (), "artifact", errors)
    if doc.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for field in ("artifact_id", "ticker"):
        if not doc.get(field):
            errors.append(f"{field} is required")
    market = doc.get("market")
    if market not in MARKETS:
        errors.append(f"market must be one of {sorted(MARKETS)}")
    if doc.get("cadence") not in CADENCES:
        errors.append(f"cadence must be one of {sorted(CADENCES)}")
    if doc.get("basis") not in BASES:
        errors.append(f"basis must be one of {sorted(BASES)}")
    elif market in MARKET_BASES and doc["basis"] not in MARKET_BASES[market]:
        errors.append(
            f"basis {doc['basis']!r} is not a {market} reporting basis "
            f"({sorted(MARKET_BASES[market])})"
        )
    if doc.get("currency") not in research_provenance.CURRENCIES - {"NONE"}:
        errors.append("currency must be a supported reporting currency")
    if not doc.get("unit"):
        errors.append("unit is required")
    published = _parse_time(doc.get("published_at"), "published_at", errors)
    if now and published and published > now:
        errors.append("published_at cannot be in the future")
    period_end = _validate_period(doc.get("period") or {}, "period", errors)
    if period_end and published and published.date() < period_end:
        errors.append("published_at cannot precede the period end_date")

    by_id = _validate_documents(doc, errors)
    _validate_comparables(doc, errors)
    availability = grade_sources(list(by_id.values()))

    segments = doc.get("segments")
    if not isinstance(segments, list):
        errors.append("segments must be a list (empty when the issuer reports one segment)")
        segments = []
    seen = set()
    for index, item in enumerate(segments):
        prefix = f"segments[{index}]"
        if not _exact_fields(
            item, ("segment_id", "name", "revenue"), ("operating_income",), prefix, errors
        ):
            continue
        if item["segment_id"] in seen:
            errors.append(f"{prefix}.segment_id must be unique")
        seen.add(item["segment_id"])
        _d(item.get("revenue"), f"{prefix}.revenue", errors)
        _d(item.get("operating_income"), f"{prefix}.operating_income", errors)

    guidance = doc.get("guidance")
    if guidance is not None:
        if _exact_fields(
            guidance,
            ("metric", "basis", "currency", "unit", "guided_low", "guided_high",
             "actual", "source_document_id"),
            (), "guidance", errors,
        ):
            for field in ("basis", "currency", "unit"):
                if guidance.get(field) != doc.get(field):
                    errors.append(f"guidance.{field} must match the artifact {field}")
            low = _d(guidance.get("guided_low"), "guidance.guided_low", errors)
            high = _d(guidance.get("guided_high"), "guidance.guided_high", errors)
            _d(guidance.get("actual"), "guidance.actual", errors)
            if low is not None and high is not None and low > high:
                errors.append("guidance.guided_low cannot exceed guided_high")
            if guidance.get("source_document_id") not in by_id:
                errors.append("guidance.source_document_id is not a listed document")

    footnotes = doc.get("footnotes")
    if not isinstance(footnotes, list):
        errors.append("footnotes must be a list")
        footnotes = []
    for index, item in enumerate(footnotes):
        prefix = f"footnotes[{index}]"
        if not _exact_fields(
            item, ("category", "summary", "source_document_id"), (), prefix, errors
        ):
            continue
        if item["category"] not in FOOTNOTE_CATEGORIES:
            errors.append(f"{prefix}.category must be one of {sorted(FOOTNOTE_CATEGORIES)}")
        if not item.get("summary"):
            errors.append(f"{prefix}.summary is required")
        source = by_id.get(item.get("source_document_id"))
        if source is None:
            errors.append(f"{prefix}.source_document_id is not a listed document")
        elif source.get("source_class") not in PRIMARY_SOURCES:
            errors.append(
                f"{prefix} cites {source.get('source_class')!r}; footnote claims require "
                "a primary issuer document"
            )
    if footnotes and not availability["footnote_claims_allowed"]:
        errors.append(
            "footnotes are not available at this source grade: no primary document "
            "covers the period"
        )

    _validate_commitments(doc, by_id, errors)

    capital = doc.get("capital_allocation")
    if not isinstance(capital, list):
        errors.append("capital_allocation must be a list")
        capital = []
    seen = set()
    for index, item in enumerate(capital):
        prefix = f"capital_allocation[{index}]"
        if not _exact_fields(
            item, ("event_id", "type", "amount", "currency", "occurred_at",
                   "source_document_id"), (), prefix, errors,
        ):
            continue
        if item["event_id"] in seen:
            errors.append(f"{prefix}.event_id must be unique")
        seen.add(item["event_id"])
        if item["type"] not in CAPITAL_EVENTS:
            errors.append(f"{prefix}.type must be one of {sorted(CAPITAL_EVENTS)}")
        _d(item.get("amount"), f"{prefix}.amount", errors)
        if item.get("currency") != doc.get("currency"):
            errors.append(f"{prefix}.currency must match the artifact currency")
        _parse_date(item.get("occurred_at"), f"{prefix}.occurred_at", errors)
        if item["source_document_id"] not in by_id:
            errors.append(f"{prefix}.source_document_id is not a listed document")

    link = doc.get("thesis_link")
    if link is not None and _exact_fields(
        link, ("thesis_id", "ticker"), (), "thesis_link", errors
    ) and link.get("ticker") != doc.get("ticker"):
        errors.append("thesis_link.ticker must match the artifact ticker")

    if not isinstance(doc.get("provenance"), dict):
        errors.append("provenance must be a manifest object")
    return errors


def _ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _growth_pct(current, prior):
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior) * Decimal("100")


def _unavailable(reason):
    return {"status": "unavailable", "reason": reason}


def _measure(value, flags=()):
    # Derived ratios are quantized to four places on purpose: the inputs stay
    # exact Decimals, and a published ratio carrying 28 digits of division tail
    # is noise, not precision.
    return {
        "status": "computed",
        "value": str(value.quantize(QUANTUM)),
        "flags": sorted(flags),
    }


def compute_quality(doc: dict) -> dict:
    """Earnings-quality math over the comparable history, computed here in code."""
    errors: list[str] = []
    rows = _validate_comparables(doc, errors)
    if errors or not rows:
        return {"status": "unavailable", "errors": errors or ["no comparable history"]}
    current, prior = rows[-1], rows[-2] if len(rows) > 1 else None
    flags: set[str] = set()
    metrics: dict[str, dict] = {}

    conversion = _ratio(current["ocf"], current["net_income"])
    if conversion is None:
        metrics["cash_conversion"] = _unavailable(
            "net_income is zero or missing, so OCF conversion is undefined"
        )
    else:
        local = set()
        # A loss-making period inverts the ratio's meaning; say so instead of
        # reading a negative denominator as a clean beat.
        if current["net_income"] < 0:
            local.add("net_income_negative")
        elif conversion < THRESHOLDS["cash_conversion_min"]:
            local.add("weak_cash_conversion")
        metrics["cash_conversion"] = _measure(conversion, local)
        flags |= local

    if current["ocf"] is None or current["capex"] is None:
        metrics["free_cash_flow"] = _unavailable("ocf or capex missing")
    else:
        fcf = current["ocf"] - current["capex"]
        local = {"negative_free_cash_flow"} if fcf < 0 else set()
        metrics["free_cash_flow"] = _measure(fcf, local)
        flags |= local

    revenue_growth = _growth_pct(current["revenue"], prior["revenue"]) if prior else None
    metrics["revenue_growth_pct"] = (
        _measure(revenue_growth) if revenue_growth is not None
        else _unavailable("no prior comparable period with revenue")
    )
    for field, flag in (("receivables", "receivables_outrunning_revenue"),
                        ("inventory", "inventory_outrunning_revenue")):
        growth = _growth_pct(current[field], prior[field]) if prior else None
        if growth is None or revenue_growth is None:
            metrics[f"{field}_growth_pct"] = _unavailable(
                f"{field} or revenue missing in one of the two latest periods"
            )
            continue
        gap = growth - revenue_growth
        local = {flag} if gap > THRESHOLDS["working_capital_gap_pp"] else set()
        metrics[f"{field}_growth_pct"] = _measure(growth, local)
        metrics[f"{field}_vs_revenue_pp"] = _measure(gap, local)
        flags |= local

    dilution = _growth_pct(current["diluted_shares"], prior["diluted_shares"]) if prior else None
    if dilution is None:
        metrics["dilution_pct"] = _unavailable("diluted_shares missing in one of the two periods")
    else:
        local = {"destructive_dilution"} if dilution > THRESHOLDS["dilution_pct"] else set()
        metrics["dilution_pct"] = _measure(dilution, local)
        flags |= local

    sbc_share = _ratio(current["sbc"], current["revenue"])
    if sbc_share is None:
        metrics["sbc_pct_revenue"] = _unavailable("sbc or revenue missing")
    else:
        share = sbc_share * Decimal("100")
        local = {"heavy_stock_compensation"} if share > THRESHOLDS["sbc_pct_revenue"] else set()
        metrics["sbc_pct_revenue"] = _measure(share, local)
        flags |= local

    margin = _ratio(current["net_income"], current["revenue"])
    metrics["net_margin_pct"] = (
        _measure(margin * Decimal("100")) if margin is not None
        else _unavailable("revenue is zero or missing")
    )

    guidance = doc.get("guidance")
    if not isinstance(guidance, dict):
        guidance_result = _unavailable("no guidance was published for this period")
    else:
        low = _d(guidance.get("guided_low"), "guided_low")
        high = _d(guidance.get("guided_high"), "guided_high")
        actual = _d(guidance.get("actual"), "actual")
        if None in (low, high, actual):
            guidance_result = _unavailable("guidance range or actual result missing")
        else:
            tolerance = THRESHOLDS["guidance_tolerance_pct"] / Decimal("100")
            if actual < low * (Decimal("1") - tolerance):
                verdict, flag = "miss", {"guidance_miss"}
            elif actual > high * (Decimal("1") + tolerance):
                verdict, flag = "beat", set()
            else:
                verdict, flag = "inline", set()
            guidance_result = {
                "status": "computed", "verdict": verdict,
                "metric": guidance.get("metric"),
                "guided_low": str(low), "guided_high": str(high), "actual": str(actual),
                "flags": sorted(flag),
            }
            flags |= flag

    return {
        "status": "computed",
        "period": current["label"],
        "compared_periods": [row["label"] for row in rows],
        "metrics": metrics,
        "guidance": guidance_result,
        "anomaly_flags": sorted(flags),
        "thresholds": {name: str(value) for name, value in THRESHOLDS.items()},
    }


def roll_forward_commitments(previous: list, current: list, as_of,
                             *, report_period_end=None) -> tuple[list, list[str]]:
    """Carry management promises across periods.

    Rules, all deterministic:
      * a promise recorded in an earlier period may never be dropped;
      * `met`/`partial`/`missed` are terminal — a later period cannot soften them;
      * an overdue promise with no reported result becomes `missed` when the
        reporting period covers its due date (management had the reporting slot
        and did not deliver), and `unverifiable` when the due date has merely
        passed on the calendar with no covering report yet.
    """
    errors: list[str] = []
    if isinstance(as_of, datetime):
        as_of = as_of.date()
    if isinstance(report_period_end, datetime):
        report_period_end = report_period_end.date()
    by_id = {item.get("commitment_id"): item for item in current if isinstance(item, dict)}
    merged: list[dict] = []
    for old in previous:
        if not isinstance(old, dict):
            continue
        commitment_id = old.get("commitment_id")
        new = by_id.pop(commitment_id, None)
        if new is None:
            errors.append(f"commitment {commitment_id} disappeared from the ledger")
            merged.append(dict(old))
            continue
        if (old.get("status") in TERMINAL_COMMITMENT_STATUSES
                and new.get("status") != old.get("status")):
            errors.append(
                f"commitment {commitment_id} was already {old['status']}; "
                f"it cannot become {new.get('status')}"
            )
        merged.append(dict(new))
    merged.extend(dict(item) for item in by_id.values())

    for item in merged:
        due = None
        try:
            due = date.fromisoformat(str(item.get("due_date")))
        except (TypeError, ValueError):
            errors.append(f"commitment {item.get('commitment_id')} has no usable due_date")
        if item.get("status") in TERMINAL_COMMITMENT_STATUSES or due is None:
            continue
        if due > as_of:
            item["status"] = "not_due"
        elif item.get("actual_value") in (None, ""):
            covered = report_period_end is not None and due <= report_period_end
            item["status"] = "missed" if covered else "unverifiable"
    return merged, errors


def build_manifest(doc: dict) -> dict:
    """The provenance manifest for every headline number this artifact publishes."""
    provenance = doc.get("provenance")
    return provenance if isinstance(provenance, dict) else {}


def release(doc: dict, *, now=None) -> dict:
    """The gate. Nothing leaves this module without a verified manifest."""
    errors = validate_artifact(doc, now=now)
    manifest = build_manifest(doc)
    gate = research_provenance.validate_manifest(manifest)
    if gate["status"] != "pass":
        errors.extend(f"provenance: {error}" for error in gate["errors"])
    quality = compute_quality(doc) if not errors else {"status": "unavailable"}
    availability = grade_sources(
        [item for item in doc.get("documents", []) if isinstance(item, dict)]
    )
    return {
        "status": "pass" if not errors else "fail",
        "artifact_id": doc.get("artifact_id"),
        "ticker": doc.get("ticker"),
        "source_availability": availability,
        "basis": doc.get("basis"),
        "currency": doc.get("currency"),
        "unit": doc.get("unit"),
        "provenance": {
            "status": gate["status"],
            "verified_metrics": gate["verified_metrics"],
            "total_metrics": gate["total_metrics"],
        },
        "quality": quality,
        "errors": errors,
    }


def to_thesis_evidence(doc: dict, quality: dict | None = None) -> dict:
    """Evidence rows for the thesis registry, plus which dimension each informs.

    Returns suggestions only. Thesis state changes stay with
    `thesis_registry.evaluate_drift`, which re-checks evidence freshness itself.
    """
    quality = quality if quality is not None else compute_quality(doc)
    published = doc.get("published_at")
    artifact_id = doc.get("artifact_id")
    primary = next(
        (item for item in doc.get("documents", [])
         if isinstance(item, dict) and item.get("covers_period") is True
         and item.get("source_class") in PRIMARY_SOURCES),
        None,
    )
    source = primary or next(
        (item for item in doc.get("documents", []) if isinstance(item, dict)), {}
    )
    evidence, suggestions = [], []

    def add(kind, dimension, summary, suffix):
        evidence_id = f"{artifact_id}-{suffix}"
        evidence.append({
            "evidence_id": evidence_id,
            "observed_at": published,
            "source_class": source.get("source_class"),
            "locator": source.get("locator"),
            "kind": kind,
            "summary": summary,
        })
        suggestions.append({
            "dimension": dimension,
            "evidence_id": evidence_id,
            "observation": summary,
        })

    metrics = quality.get("metrics", {}) if quality.get("status") == "computed" else {}
    if metrics:
        flags = quality.get("anomaly_flags") or ["none"]
        add(
            "fundamental", "business",
            f"{doc.get('period', {}).get('label')} earnings quality flags: {', '.join(flags)}",
            "business",
        )
    guidance = quality.get("guidance", {})
    if guidance.get("status") == "computed":
        add(
            "fundamental", "management",
            f"guidance {guidance['verdict']} on {guidance.get('metric')} "
            f"(actual {guidance['actual']} vs {guidance['guided_low']}–{guidance['guided_high']})",
            "guidance",
        )
    delivered = [
        item for item in doc.get("management_commitments", [])
        if isinstance(item, dict) and item.get("status") in TERMINAL_COMMITMENT_STATUSES
    ]
    if delivered:
        tally = {status: 0 for status in sorted(TERMINAL_COMMITMENT_STATUSES)}
        for item in delivered:
            tally[item["status"]] += 1
        add(
            "fundamental", "management",
            "promise ledger: " + ", ".join(f"{k}={v}" for k, v in tally.items()),
            "promises",
        )
    if doc.get("capital_allocation"):
        types = sorted({item.get("type") for item in doc["capital_allocation"]})
        add("fundamental", "moat", f"capital allocation this period: {', '.join(types)}", "capital")
    if doc.get("footnotes"):
        categories = sorted({item.get("category") for item in doc["footnotes"]})
        add("filing", "business", f"material footnotes: {', '.join(categories)}", "footnotes")

    return {
        "thesis_id": (doc.get("thesis_link") or {}).get("thesis_id"),
        "ticker": doc.get("ticker"),
        "evidence": evidence,
        "dimension_suggestions": suggestions,
        # Deliberately absent: any thesis state. Earnings evidence never moves the
        # registry on its own.
        "state_change": None,
    }


def artifact_path(ticker: str, period_label: str) -> Path:
    return ARTIFACT_ROOT / ticker / f"{period_label}.json"


def load_artifact(path: Path) -> tuple[dict | None, list[str]]:
    try:
        return json.loads(path.read_text()), []
    except (OSError, json.JSONDecodeError) as exc:
        return None, [str(exc)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "review", "thesis-evidence"):
        cmd = sub.add_parser(name)
        cmd.add_argument("path", type=Path)
    promises = sub.add_parser("promises")
    promises.add_argument("previous", type=Path)
    promises.add_argument("current", type=Path)
    promises.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)

    if args.command == "promises":
        previous, errors = load_artifact(args.previous)
        current, current_errors = load_artifact(args.current)
        errors += current_errors
        if errors:
            result = {"status": "fail", "errors": errors}
        else:
            period_end = (current.get("period") or {}).get("end_date")
            merged, merge_errors = roll_forward_commitments(
                previous.get("management_commitments", []),
                current.get("management_commitments", []),
                date.fromisoformat(args.as_of),
                report_period_end=(
                    date.fromisoformat(period_end) if isinstance(period_end, str) else None
                ),
            )
            result = {
                "status": "fail" if merge_errors else "pass",
                "commitments": merged, "errors": merge_errors,
            }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["status"] == "pass" else 1

    doc, errors = load_artifact(args.path)
    if errors:
        result = {"status": "fail", "errors": errors}
    elif args.command == "validate":
        found = validate_artifact(doc, now=now)
        result = {"status": "pass" if not found else "fail", "errors": found}
    elif args.command == "review":
        result = release(doc, now=now)
    else:
        gate = release(doc, now=now)
        result = {
            "status": gate["status"],
            "errors": gate["errors"],
            **to_thesis_evidence(doc, gate["quality"]),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
