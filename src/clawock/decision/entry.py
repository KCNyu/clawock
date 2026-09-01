"""Pre-investment entry gate: is this name understandable and researchable enough?

This runs *before* a deep-research run or any new exposure, and it answers only
that narrow question. It never sizes a position, never places a trade, and never
overrides the decision, risk, or settlement contracts downstream.

Two ideas are worth keeping from the upstream study, and both are enforced here
rather than requested in prose:

* information richness is graded separately from investment quality, so "few
  public sources" can never read as "bad company"; and
* the outcome is `pass_to_deep_research` / `reject` / `gray_needs_evidence` — a
  gray verdict must name the evidence it is missing instead of guessing.

The gate recomputes the verdict from the artifact's own checks and vetoes and
rejects an artifact whose stated verdict disagrees. A hard veto is decided before
any check is counted, so a high tally can never average one away.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from clawock import instruments as instrument_registry
from clawock.workspace import engine_config, workspace_root
from clawock.safe_io import parse_iso_utc as _parse_time

WS = workspace_root()
SCHEMA_FILE = engine_config("entry_gate.schema.json")
VETO_FILE = WS / "config" / "entry-gate-vetoes.json"
ARTIFACT_ROOT = WS / "memory" / "entry-gates"
SCHEMA_VERSION = 1

MARKETS = {"US", "HK"}
INSTRUMENT_KINDS = {"company", "leveraged_etf"}
# Quotes must come from the workspace pipelines. A generic web price is not an
# accepted input, at any grade.
QUOTE_SOURCES = {
    "analyze_us_stocks", "analyze_hk_stocks", "tencent_quote",
    "eastmoney_quote", "canonical_daily_bars",
}
MAX_QUOTE_AGE_MINUTES = 1440
PRIMARY_EVIDENCE = {
    "sec_filing", "hkex_announcement", "issuer_ir", "sec_xbrl",
    "eastmoney_fundamentals", "earnings_review_artifact",
}
SECONDARY_EVIDENCE = {"regulatory_database", "exchange_data", "workspace_dataset"}
WEAK_EVIDENCE = {"news_media", "third_party_summary", "analyst_note"}
EVIDENCE_CLASSES = PRIMARY_EVIDENCE | SECONDARY_EVIDENCE | WEAK_EVIDENCE
COMPANY_CHECKS = (
    "business_quality", "moat", "management_governance", "valuation",
    "dilution", "downside",
)
LEVERAGED_CHECKS = ("underlying_exposure", "decay_and_regime", "sizing_limit", "liquidity")
CHECKS_BY_KIND = {"company": COMPANY_CHECKS, "leveraged_etf": LEVERAGED_CHECKS}
# A failure here says the name is not worth a research run. Everything else —
# valuation, dilution, moat, decay, liquidity — is a sizing and timing input for
# the existing risk contracts, not a reason to refuse to understand the company.
DISQUALIFYING_CHECKS = {
    "business_quality", "management_governance", "downside",
    "underlying_exposure", "sizing_limit",
}
CHECK_VERDICTS = {"pass", "fail", "unknown"}
VETO_STATUSES = {"clear", "triggered", "unknown"}
VERDICTS = {"pass_to_deep_research", "reject", "gray_needs_evidence"}
ROUTING = {
    ("US", "company"): "us_full_report",
    ("HK", "company"): "hk_full_report",
    ("US", "leveraged_etf"): "leverage_look_through",
    ("HK", "leveraged_etf"): "leverage_look_through",
}
ARTIFACT_FIELDS = (
    "schema_version", "gate_id", "ticker", "market", "instrument_kind", "sector",
    "assessed_at", "quote", "information", "mechanism", "key_variables", "checks",
    "vetoes", "mirror_test", "evidence", "next_evidence", "verdict", "routing",
)
MIRROR_TEST_SENTENCES = 5


def load_vetoes(path: Path = VETO_FILE, *, missing_ok: bool = False) -> dict:
    """The book's standing entry vetoes.

    `missing_ok` splits absence from corruption, same as the instrument registry
    (#356): a workspace that has declared no vetoes is a normal state for any
    book but this one, while malformed JSON is corruption and still raises.
    """
    if missing_ok and not Path(path).exists():
        return {}
    doc = json.loads(Path(path).read_text())
    return {item["id"]: item for item in doc["vetoes"]}


# Absent vetoes must not stop this module importing — brief_preflight imports it
# transitively, so raising here killed the whole preflight against a foreign
# workspace. An empty veto set is not silent: `check` reports any veto a caller
# names as undefined, which is exactly what an unconfigured book should hear.
VETOES = load_vetoes(missing_ok=True)


def _exact_fields(item, required, prefix, errors) -> bool:
    if not isinstance(item, dict):
        errors.append(f"{prefix} must be an object")
        return False
    missing = sorted(set(required) - set(item))
    extra = sorted(set(item) - set(required))
    if missing:
        errors.append(f"{prefix} missing fields: {missing}")
    if extra:
        errors.append(f"{prefix} unknown fields: {extra}")
    return not missing and not extra




def grade_information(evidence: list) -> dict:
    """Grade the sources, never the company.

    A — at least two distinct primary/structured classes.
    B — at least one primary/structured class.
    C — media, analyst notes and third-party summaries only.
    """
    classes = {
        item.get("source_class") for item in (evidence or []) if isinstance(item, dict)
    }
    strong = classes & PRIMARY_EVIDENCE
    supporting = classes & SECONDARY_EVIDENCE
    if len(strong) >= 2:
        grade = "A"
    elif strong:
        grade = "B"
    else:
        grade = "C"
    gaps = []
    if not strong:
        gaps.append("no primary issuer or structured source in the evidence set")
    elif len(strong) < 2:
        gaps.append("only one primary/structured source class; a second is needed to cross-check")
    if not supporting and grade != "A":
        gaps.append("no supporting regulatory/exchange dataset")
    if classes & WEAK_EVIDENCE:
        gaps.append("media or analyst material is present and ranks below issuer sources")
    return {"grade": grade, "gaps": gaps, "source_classes": sorted(c for c in classes if c)}


def quote_freshness(doc: dict) -> dict:
    """Quote age against the assessment time, plus whether the source is allowed."""
    quote = doc.get("quote")
    if not isinstance(quote, dict):
        return {"status": "missing", "reason": "no quote block"}
    errors: list[str] = []
    as_of = _parse_time(quote.get("as_of"), "quote.as_of", errors)
    assessed = _parse_time(doc.get("assessed_at"), "assessed_at", errors)
    if errors or as_of is None or assessed is None:
        return {"status": "missing", "reason": "; ".join(errors) or "unparseable timestamps"}
    age_minutes = int((assessed - as_of).total_seconds() // 60)
    return {
        "status": "stale" if age_minutes > MAX_QUOTE_AGE_MINUTES or age_minutes < 0 else "fresh",
        "age_minutes": age_minutes,
        "source_class": quote.get("source_class"),
        "max_age_minutes": MAX_QUOTE_AGE_MINUTES,
    }


def _valid_exception(veto: dict, sector, evidence_ids) -> tuple[bool, str | None]:
    """An exception counts only when this veto encodes it for this sector."""
    definition = VETOES.get(veto.get("id"))
    exception = veto.get("exception")
    if not isinstance(exception, dict):
        return False, None
    if definition is None:
        return False, f"veto {veto.get('id')!r} is not defined in {VETO_FILE.name}"
    allowed = {
        item["sector"]: item for item in definition.get("exceptions", [])
    }
    if not allowed:
        return False, f"veto {veto['id']} does not encode any exception"
    rule = allowed.get(sector)
    if rule is None:
        return False, (
            f"veto {veto['id']} encodes no exception for sector {sector!r} "
            f"(allowed: {sorted(allowed)})"
        )
    if rule.get("requires_evidence") and exception.get("evidence_id") not in evidence_ids:
        return False, (
            f"veto {veto['id']} exception needs an evidence_id present in evidence[]"
        )
    if not exception.get("reason"):
        return False, f"veto {veto['id']} exception needs a stated reason"
    return True, None


def decide(doc: dict) -> dict:
    """Recompute the verdict from the artifact's own checks, vetoes and sources.

    Order matters and is the whole point: vetoes are resolved before any check is
    counted, so `checks_passed` can never rescue a vetoed name.
    """
    kind = doc.get("instrument_kind")
    required = CHECKS_BY_KIND.get(kind, ())
    evidence_ids = {
        item.get("evidence_id") for item in (doc.get("evidence") or [])
        if isinstance(item, dict)
    }
    sector = doc.get("sector")
    reasons: list[str] = []

    triggered, unknown_vetoes = [], []
    for veto in (doc.get("vetoes") or []):
        if not isinstance(veto, dict):
            continue
        if veto.get("status") == "triggered":
            excepted, _ = _valid_exception(veto, sector, evidence_ids)
            if excepted:
                reasons.append(
                    f"veto {veto.get('id')} triggered but excepted for sector {sector!r}"
                )
            else:
                triggered.append(veto.get("id"))
        elif veto.get("status") == "unknown":
            unknown_vetoes.append(veto.get("id"))

    by_id = {
        item.get("id"): item for item in (doc.get("checks") or [])
        if isinstance(item, dict)
    }
    passed = sorted(k for k in required if (by_id.get(k) or {}).get("verdict") == "pass")
    failed = sorted(k for k in required if (by_id.get(k) or {}).get("verdict") == "fail")
    unknown = sorted(
        k for k in required if (by_id.get(k) or {}).get("verdict") in (None, "unknown")
    )
    information = grade_information(doc.get("evidence") or [])
    freshness = quote_freshness(doc)
    disqualifying = sorted(set(failed) & DISQUALIFYING_CHECKS)

    if triggered:
        verdict = "reject"
        reasons.append(f"hard veto triggered: {', '.join(triggered)}")
    elif disqualifying:
        verdict = "reject"
        reasons.append(f"disqualifying check failed: {', '.join(disqualifying)}")
    elif unknown_vetoes or unknown:
        verdict = "gray_needs_evidence"
        if unknown_vetoes:
            reasons.append(f"veto status unknown: {', '.join(unknown_vetoes)}")
        if unknown:
            reasons.append(f"check unresolved: {', '.join(unknown)}")
    elif information["grade"] == "C":
        # Thin sourcing is a research problem, not a company verdict: gray, never
        # a reject.
        verdict = "gray_needs_evidence"
        reasons.append("information grade C: no primary or structured source to cross-check")
    elif freshness.get("status") != "fresh":
        verdict = "gray_needs_evidence"
        reasons.append(f"quote is {freshness.get('status')} against the workspace pipelines")
    else:
        verdict = "pass_to_deep_research"
        if failed:
            reasons.append(
                "routed to research with open concerns "
                f"({', '.join(failed)}); sizing stays with the risk contracts"
            )
    return {
        "verdict": verdict,
        "reasons": reasons,
        "information": information,
        "quote_freshness": freshness,
        "checks_passed": f"{len(passed)}/{len(required)}",
        "failed_checks": failed,
        "unresolved_checks": unknown,
        "triggered_vetoes": triggered,
        "routing": ROUTING.get((doc.get("market"), kind)),
    }


def validate_artifact(doc: dict, *, now=None) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["artifact must be an object"]
    _exact_fields(doc, ARTIFACT_FIELDS, "artifact", errors)
    if doc.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for field in ("gate_id", "ticker", "sector", "mechanism"):
        if not doc.get(field):
            errors.append(f"{field} is required")
    market, kind = doc.get("market"), doc.get("instrument_kind")
    if market not in MARKETS:
        errors.append(f"market must be one of {sorted(MARKETS)}")
    if kind not in INSTRUMENT_KINDS:
        errors.append(f"instrument_kind must be one of {sorted(INSTRUMENT_KINDS)}")
    assessed = _parse_time(doc.get("assessed_at"), "assessed_at", errors)
    if now and assessed and assessed > now:
        errors.append("assessed_at cannot be in the future")
    if len(str(doc.get("mechanism") or "")) > 300:
        errors.append("mechanism must be one sentence (<=300 characters)")

    # The canonical registry wins over a declaration whenever it knows the symbol.
    known = instrument_registry.get(str(doc.get("ticker")))
    if known is not None:
        registry_leveraged = instrument_registry.is_leveraged(str(doc["ticker"]))
        if registry_leveraged and kind != "leveraged_etf":
            errors.append(
                f"instrument registry lists {doc['ticker']} as leveraged "
                f"(x{known.get('leverage_multiple')}); instrument_kind must be leveraged_etf"
            )
        if not registry_leveraged and kind == "leveraged_etf":
            errors.append(
                f"instrument registry lists {doc['ticker']} as unleveraged; "
                "instrument_kind must be company"
            )

    quote = doc.get("quote")
    if not _exact_fields(quote, ("price", "currency", "as_of", "source_class"), "quote", errors):
        quote = {}
    elif quote.get("source_class") not in QUOTE_SOURCES:
        # Not a gray verdict — a generic web price breaks the data contract.
        errors.append(
            f"quote.source_class must be a workspace pipeline {sorted(QUOTE_SOURCES)}, "
            f"got {quote.get('source_class')!r}"
        )

    evidence_ids = set()
    evidence = doc.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("evidence must be a non-empty list")
        evidence = []
    for index, item in enumerate(evidence):
        prefix = f"evidence[{index}]"
        if not _exact_fields(
            item, ("evidence_id", "observed_at", "source_class", "locator", "summary"),
            prefix, errors,
        ):
            continue
        if item["source_class"] not in EVIDENCE_CLASSES:
            errors.append(f"{prefix}.source_class must be one of {sorted(EVIDENCE_CLASSES)}")
        if item["evidence_id"] in evidence_ids:
            errors.append(f"{prefix}.evidence_id must be unique")
        evidence_ids.add(item["evidence_id"])
        observed = _parse_time(item["observed_at"], f"{prefix}.observed_at", errors)
        if now and observed and observed > now:
            errors.append(f"{prefix}.observed_at cannot be in the future")
        if not item["locator"] or not item["summary"]:
            errors.append(f"{prefix} needs a locator and a summary")

    variables = doc.get("key_variables")
    if not isinstance(variables, list) or not 3 <= len(variables) <= 7:
        errors.append("key_variables must contain 3-7 items")
        variables = []
    seen = set()
    for index, item in enumerate(variables):
        prefix = f"key_variables[{index}]"
        if not _exact_fields(item, ("id", "variable", "why_it_decides"), prefix, errors):
            continue
        if item["id"] in seen:
            errors.append(f"{prefix}.id must be unique")
        seen.add(item["id"])
        if not item["variable"] or not item["why_it_decides"]:
            errors.append(f"{prefix} needs a variable and why it decides the outcome")

    required_checks = CHECKS_BY_KIND.get(kind, ())
    checks = doc.get("checks")
    if not isinstance(checks, list):
        errors.append("checks must be a list")
        checks = []
    seen = set()
    for index, item in enumerate(checks):
        prefix = f"checks[{index}]"
        if not _exact_fields(
            item, ("id", "verdict", "finding", "evidence_ids"), prefix, errors
        ):
            continue
        if item["id"] in seen:
            errors.append(f"{prefix}.id must be unique")
        seen.add(item["id"])
        if kind in CHECKS_BY_KIND and item["id"] not in required_checks:
            # A leveraged ETF has no company fundamentals to grade; it routes to
            # the look-through path instead of pretending to read a moat.
            errors.append(
                f"{prefix}.id {item['id']!r} is not a {kind} check "
                f"({sorted(required_checks)})"
            )
        if item["verdict"] not in CHECK_VERDICTS:
            errors.append(f"{prefix}.verdict must be one of {sorted(CHECK_VERDICTS)}")
        if not item["finding"]:
            errors.append(f"{prefix}.finding is required")
        refs = item.get("evidence_ids")
        if not isinstance(refs, list):
            errors.append(f"{prefix}.evidence_ids must be a list")
        else:
            missing = sorted(set(refs) - evidence_ids)
            if missing:
                errors.append(f"{prefix} references missing evidence: {missing}")
            if item["verdict"] in {"pass", "fail"} and not refs:
                errors.append(f"{prefix} claims {item['verdict']} without evidence")
    if kind in CHECKS_BY_KIND:
        for name in required_checks:
            if name not in seen:
                errors.append(f"checks is missing the required {kind} check {name!r}")

    seen = set()
    veto_ids = set(VETOES)
    for index, item in enumerate(doc.get("vetoes") or []):
        prefix = f"vetoes[{index}]"
        if not _exact_fields(
            item, ("id", "status", "finding", "evidence_ids", "exception"), prefix, errors
        ):
            continue
        if item["id"] not in veto_ids:
            errors.append(f"{prefix}.id must be one of {sorted(veto_ids)}")
        if item["id"] in seen:
            errors.append(f"{prefix}.id must be unique")
        seen.add(item["id"])
        if item["status"] not in VETO_STATUSES:
            errors.append(f"{prefix}.status must be one of {sorted(VETO_STATUSES)}")
        refs = item.get("evidence_ids")
        if not isinstance(refs, list):
            errors.append(f"{prefix}.evidence_ids must be a list")
        elif item["status"] == "triggered" and not refs:
            errors.append(f"{prefix} is triggered without evidence")
        elif sorted(set(refs) - evidence_ids):
            errors.append(f"{prefix} references missing evidence")
        if item.get("exception") is not None:
            excepted, reason = _valid_exception(item, doc.get("sector"), evidence_ids)
            if not excepted:
                errors.append(f"{prefix}: {reason or 'exception is not valid'}")
    for name in sorted(veto_ids - seen):
        errors.append(f"vetoes must state a status for {name!r}")

    mirror = doc.get("mirror_test")
    if not isinstance(mirror, list) or len(mirror) != MIRROR_TEST_SENTENCES:
        errors.append(f"mirror_test must contain exactly {MIRROR_TEST_SENTENCES} sentences")
    else:
        for index, sentence in enumerate(mirror):
            if not isinstance(sentence, str) or not sentence.strip():
                errors.append(f"mirror_test[{index}] must be a non-empty sentence")
            elif len(sentence) > 300:
                errors.append(f"mirror_test[{index}] must stay under 300 characters")
        if len({s.strip() for s in mirror if isinstance(s, str)}) != MIRROR_TEST_SENTENCES:
            errors.append("mirror_test sentences must be distinct")

    next_evidence = doc.get("next_evidence")
    if not isinstance(next_evidence, list):
        errors.append("next_evidence must be a list")
        next_evidence = []
    for index, item in enumerate(next_evidence):
        prefix = f"next_evidence[{index}]"
        if _exact_fields(item, ("question", "where_to_look"), prefix, errors) and not (
            item["question"] and item["where_to_look"]
        ):
            errors.append(f"{prefix} needs a question and where to look")

    if doc.get("verdict") not in VERDICTS:
        errors.append(f"verdict must be one of {sorted(VERDICTS)}")
    if not errors:
        # Only meaningful once the artifact is structurally sound.
        computed = decide(doc)
        if doc["verdict"] != computed["verdict"]:
            errors.append(
                f"verdict {doc['verdict']!r} disagrees with the computed verdict "
                f"{computed['verdict']!r}: {'; '.join(computed['reasons'])}"
            )
        if doc.get("routing") != computed["routing"]:
            errors.append(
                f"routing must be {computed['routing']!r} for a {market} {kind}"
            )
        if doc.get("information") != computed["information"]:
            errors.append(
                "information must match the grade computed from evidence source classes: "
                f"{computed['information']}"
            )
        if computed["verdict"] == "gray_needs_evidence" and not next_evidence:
            errors.append("a gray verdict must name the next evidence needed")
    return errors


def assess(doc: dict, *, now=None) -> dict:
    errors = validate_artifact(doc, now=now)
    computed = decide(doc) if isinstance(doc, dict) else {}
    return {
        "status": "pass" if not errors else "fail",
        "gate_id": doc.get("gate_id") if isinstance(doc, dict) else None,
        "ticker": doc.get("ticker") if isinstance(doc, dict) else None,
        "instrument_kind": doc.get("instrument_kind") if isinstance(doc, dict) else None,
        **{key: computed.get(key) for key in (
            "verdict", "reasons", "information", "quote_freshness", "checks_passed",
            "failed_checks", "unresolved_checks", "triggered_vetoes", "routing",
        )},
        "next_evidence": doc.get("next_evidence") if isinstance(doc, dict) else [],
        "errors": errors,
    }


def artifact_path(ticker: str, assessed_on: str) -> Path:
    return ARTIFACT_ROOT / f"{ticker}-{assessed_on}.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "assess"):
        cmd = sub.add_parser(name)
        cmd.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        doc = json.loads(args.path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "errors": [str(exc)]}, ensure_ascii=False))
        return 1
    if args.command == "validate":
        errors = validate_artifact(doc, now=now)
        result = {"status": "pass" if not errors else "fail", "errors": errors}
    else:
        result = assess(doc, now=now)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
