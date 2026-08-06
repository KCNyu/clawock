#!/usr/bin/env python3
"""Canonical investment-thesis registry and evidence-only drift evaluator."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clawock.workspace import engine_config, workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
SCHEMA_FILE = engine_config("thesis.schema.json")
SCHEMA_VERSION = 1
THESIS_STATES = ("unknown", "broken", "damaged", "weakening", "intact")
STATE_RANK = {"broken": 0, "damaged": 1, "weakening": 2, "intact": 3}
DIMENSIONS = ("business", "moat", "management", "valuation")
ASSUMPTION_STATES = {"unknown", "supported", "weakening", "damaged", "broken"}
RED_LINE_STATES = {"clear", "watch", "triggered", "unknown"}
SEVERITIES = {"warning", "severe", "fatal"}
PRICE_KINDS = {"price", "valuation"}
THESIS_FIELDS = {
    "schema_version", "thesis_id", "ticker", "strategy_scope", "summary",
    "created_at", "checked_at", "state", "dimensions", "assumptions",
    "red_lines", "valuation_anchors", "evidence", "next_review_trigger",
}


def _exact_fields(item, required, prefix, errors):
    if not isinstance(item, dict):
        errors.append(f"{prefix} must be an object")
        return
    missing = sorted(required - set(item))
    extra = sorted(set(item) - required)
    if missing:
        errors.append(f"{prefix} missing fields: {missing}")
    if extra:
        errors.append(f"{prefix} unknown fields: {extra}")


def _parse_time(value, field, errors):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result
    except (TypeError, ValueError):
        errors.append(f"{field} must be an ISO-8601 timestamp with timezone")
        return None


def _refs(items, prefix, evidence_ids, errors):
    refs = items.get("evidence_ids") if isinstance(items, dict) else None
    if not isinstance(refs, list):
        errors.append(f"{prefix}.evidence_ids must be a list")
        return set()
    valid = set()
    for ref in refs:
        if not isinstance(ref, str) or not ref:
            errors.append(f"{prefix}.evidence_ids must contain non-empty strings")
        else:
            valid.add(ref)
    if len(valid) != len(refs):
        errors.append(f"{prefix}.evidence_ids must be unique")
    missing = valid - evidence_ids
    if missing:
        errors.append(f"{prefix} references missing evidence: {sorted(missing)}")
    return valid


def validate_thesis(doc: dict, *, now=None) -> list[str]:
    errors = []
    if not isinstance(doc, dict):
        return ["thesis must be an object"]
    _exact_fields(doc, THESIS_FIELDS, "thesis", errors)
    if doc.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for field in ("thesis_id", "ticker", "summary", "created_at", "checked_at",
                  "state", "next_review_trigger"):
        if doc.get(field) in (None, ""):
            errors.append(f"{field} is required")
    if doc.get("state") not in THESIS_STATES:
        errors.append(f"state must be one of {THESIS_STATES}")
    strategy_scope = doc.get("strategy_scope")
    if not isinstance(strategy_scope, list) or not strategy_scope:
        errors.append("strategy_scope must be a non-empty list")
    elif (
        any(not isinstance(item, str) or not item for item in strategy_scope)
        or len(set(strategy_scope)) != len(strategy_scope)
    ):
        errors.append("strategy_scope must contain unique non-empty strings")
    if len(str(doc.get("summary") or "")) > 400:
        errors.append("summary must be concise (<=400 characters)")
    created = _parse_time(doc.get("created_at"), "created_at", errors)
    checked = _parse_time(doc.get("checked_at"), "checked_at", errors)
    if created and checked and checked < created:
        errors.append("checked_at cannot precede created_at")

    evidence = doc.get("evidence")
    if not isinstance(evidence, list):
        errors.append("evidence must be a list")
        evidence = []
    evidence_map = {}
    for index, item in enumerate(evidence):
        prefix = f"evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        _exact_fields(
            item,
            {"evidence_id", "observed_at", "source_class", "locator", "kind", "summary"},
            prefix, errors,
        )
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in evidence_map:
            errors.append(f"{prefix}.evidence_id must be present and unique")
        else:
            evidence_map[evidence_id] = item
        for field in ("observed_at", "source_class", "locator", "kind", "summary"):
            if not item.get(field):
                errors.append(f"{prefix}.{field} is required")
        observed = _parse_time(item.get("observed_at"), f"{prefix}.observed_at", errors)
        if observed and checked and observed > checked:
            errors.append(f"{prefix}.observed_at cannot be after checked_at")
        if now and observed and observed > now:
            errors.append(f"{prefix}.observed_at cannot be in the future")

    evidence_ids = set(evidence_map)
    dimensions = doc.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        errors.append(f"dimensions must contain exactly {DIMENSIONS}")
        dimensions = {}
    for name in DIMENSIONS:
        dimension = dimensions.get(name, {})
        _exact_fields(dimension, {"state", "evidence_ids"}, f"dimensions.{name}", errors)
        if not isinstance(dimension, dict):
            dimension = {}
        if dimension.get("state") not in THESIS_STATES:
            errors.append(f"dimensions.{name}.state must be one of {THESIS_STATES}")
        refs = _refs(dimension, f"dimensions.{name}", evidence_ids, errors)
        if name != "valuation":
            bad = [
                evidence_id for evidence_id in refs
                if (evidence_map.get(evidence_id) or {}).get("kind") in PRICE_KINDS
            ]
            if bad:
                errors.append(
                    f"dimensions.{name} cannot use price-only evidence: {sorted(bad)}"
                )

    assumptions = doc.get("assumptions")
    if not isinstance(assumptions, list) or not 3 <= len(assumptions) <= 7:
        errors.append("assumptions must contain 3-7 items")
        assumptions = []
    seen = set()
    for index, item in enumerate(assumptions):
        prefix = f"assumptions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        _exact_fields(
            item,
            {"id", "claim", "test", "cadence", "status", "evidence_ids"},
            prefix, errors,
        )
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            errors.append(f"{prefix}.id must be present and unique")
        elif item_id:
            seen.add(item_id)
        for field in ("claim", "test", "cadence"):
            if not item.get(field):
                errors.append(f"{prefix}.{field} is required")
        if item.get("status") not in ASSUMPTION_STATES:
            errors.append(f"{prefix}.status is invalid")
        _refs(item, prefix, evidence_ids, errors)

    red_lines = doc.get("red_lines")
    if not isinstance(red_lines, list) or not red_lines:
        errors.append("red_lines must be a non-empty list")
        red_lines = []
    fatal = severe = False
    seen = set()
    for index, item in enumerate(red_lines):
        prefix = f"red_lines[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        _exact_fields(
            item,
            {"id", "condition", "severity", "status", "required_action", "evidence_ids"},
            prefix, errors,
        )
        for field in ("id", "condition", "required_action"):
            if not item.get(field):
                errors.append(f"{prefix}.{field} is required")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif item_id in seen:
            errors.append(f"{prefix}.id must be unique")
        else:
            seen.add(item_id)
        if item.get("severity") not in SEVERITIES:
            errors.append(f"{prefix}.severity is invalid")
        if item.get("status") not in RED_LINE_STATES:
            errors.append(f"{prefix}.status is invalid")
        refs = _refs(item, prefix, evidence_ids, errors)
        if item.get("status") == "triggered" and not refs:
            errors.append(f"{prefix} triggered without evidence")
        fatal |= item.get("status") == "triggered" and item.get("severity") == "fatal"
        severe |= item.get("status") == "triggered" and item.get("severity") == "severe"
    if fatal and doc.get("state") != "broken":
        errors.append("fatal red line requires overall state=broken")
    if severe and doc.get("state") not in {"damaged", "broken"}:
        errors.append("severe red line requires overall state=damaged or broken")

    anchors = doc.get("valuation_anchors")
    if not isinstance(anchors, list):
        errors.append("valuation_anchors must be a list")
        anchors = []
    seen = set()
    for index, item in enumerate(anchors):
        prefix = f"valuation_anchors[{index}]"
        _exact_fields(
            item,
            {"id", "metric", "value", "currency", "period", "evidence_ids"},
            prefix, errors,
        )
        for field in ("id", "metric", "value", "currency", "period"):
            if (
                not isinstance(item, dict)
                or item.get(field) is None
                or item.get(field) == ""
            ):
                errors.append(f"{prefix}.{field} is required")
        if isinstance(item, dict):
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id:
                errors.append(f"{prefix}.id must be a non-empty string")
            elif item_id in seen:
                errors.append(f"{prefix}.id must be unique")
            else:
                seen.add(item_id)
            _refs(item, prefix, evidence_ids, errors)

    trigger = doc.get("next_review_trigger")
    _exact_fields(trigger, {"type", "description"}, "next_review_trigger", errors)
    if not isinstance(trigger, dict) or not trigger.get("type") or not trigger.get("description"):
        errors.append("next_review_trigger requires type and description")
    return errors


def validate_transition(old: dict, new: dict) -> list[str]:
    errors = []
    if old.get("thesis_id") != new.get("thesis_id"):
        errors.append("thesis_id mismatch")
    if old.get("ticker") != new.get("ticker"):
        errors.append("ticker mismatch")
    time_errors = []
    old_checked = _parse_time(old.get("checked_at"), "old.checked_at", time_errors)
    new_checked = _parse_time(new.get("checked_at"), "new.checked_at", time_errors)
    errors += time_errors
    if old_checked and new_checked and new_checked < old_checked:
        errors.append("checked_at cannot move backwards")
    old_state, new_state = old.get("state"), new.get("state")
    if old_state == "broken" and new_state != "broken":
        errors.append("broken thesis is terminal; create a new thesis_id to reopen")
    if old_state == "damaged" and new_state == "intact":
        errors.append("damaged thesis cannot jump directly to intact")
    return errors


def _drift_failure(status: str, errors: list[str]) -> dict:
    """Same result shape as a passing drift run, so callers never key-miss."""
    return {
        "status": status, "overall": "unknown", "dimensions": {},
        "triggered_red_lines": [], "newly_triggered_red_lines": [],
        "resolved_red_lines": [], "errors": errors,
    }


def _has_fresh_support(supporting, new_evidence, old_checked, label, errors) -> bool:
    """True when a change is backed by evidence first observed after the baseline."""
    if not supporting:
        errors.append(f"{label} without new evidence")
        return False
    fresh = False
    for evidence_id in sorted(supporting):
        observed_errors = []
        observed = _parse_time(
            new_evidence[evidence_id].get("observed_at"),
            f"evidence {evidence_id}.observed_at", observed_errors,
        )
        errors += observed_errors
        fresh |= bool(observed and old_checked and observed > old_checked)
    if not fresh:
        errors.append(f"{label} using stale evidence")
    return fresh


def evaluate_drift(old: dict | None, new: dict, *, now=None) -> dict:
    if old is None:
        return _drift_failure("unknown", ["missing historical baseline"])
    errors = validate_thesis(old, now=now) + validate_thesis(new, now=now)
    if isinstance(old, dict) and isinstance(new, dict):
        errors += validate_transition(old, new)
    if errors:
        return _drift_failure("fail", errors)
    old_checked_errors = []
    old_checked = _parse_time(old.get("checked_at"), "old.checked_at", old_checked_errors)
    errors += old_checked_errors
    old_evidence = {item.get("evidence_id") for item in old.get("evidence", [])}
    new_evidence = {
        item.get("evidence_id"): item for item in new.get("evidence", [])
        if item.get("evidence_id") not in old_evidence
    }
    dimensions = {}
    for name in DIMENSIONS:
        before = (old.get("dimensions") or {}).get(name, {})
        after = (new.get("dimensions") or {}).get(name, {})
        before_state, after_state = before.get("state"), after.get("state")
        if before_state == after_state:
            direction = "unchanged"
        elif before_state in STATE_RANK and after_state in STATE_RANK:
            direction = "improved" if STATE_RANK[after_state] > STATE_RANK[before_state] else "weakened"
        else:
            direction = "unknown"
        supporting = set(after.get("evidence_ids") or []) & set(new_evidence)
        if direction != "unchanged" and not _has_fresh_support(
            supporting, new_evidence, old_checked, f"{name} changed", errors
        ):
            direction = "unknown"
        dimensions[name] = {
            "old_state": before_state,
            "new_state": after_state,
            "direction": direction,
            "new_evidence_ids": sorted(supporting),
        }

    triggered = [
        item for item in new.get("red_lines", [])
        if item.get("status") == "triggered"
    ]
    old_red_lines = {
        item.get("id"): item for item in old.get("red_lines", [])
        if isinstance(item, dict)
    }
    new_red_lines = {
        item.get("id"): item for item in new.get("red_lines", [])
        if isinstance(item, dict)
    }
    newly_triggered = []
    for item in triggered:
        if (old_red_lines.get(item.get("id")) or {}).get("status") == "triggered":
            continue
        newly_triggered.append(item)
        supporting = set(item.get("evidence_ids") or []) & set(new_evidence)
        _has_fresh_support(
            supporting, new_evidence, old_checked,
            f"red line {item.get('id')} triggered", errors,
        )

    # Leaving `triggered` is a judgment too. Without the same evidence rule a
    # triggered red line could be cleared out of thin air and the drift report
    # would still say `unchanged`, erasing the most consequential state in the
    # document.
    resolved = []
    for red_line_id, before in old_red_lines.items():
        if before.get("status") != "triggered":
            continue
        after = new_red_lines.get(red_line_id)
        if after is None:
            errors.append(f"red line {red_line_id} was dropped while triggered")
            continue
        if after.get("status") == "triggered":
            continue
        resolved.append(red_line_id)
        supporting = set(after.get("evidence_ids") or []) & set(new_evidence)
        _has_fresh_support(
            supporting, new_evidence, old_checked,
            f"red line {red_line_id} left triggered", errors,
        )

    directions = {item["direction"] for item in dimensions.values()}
    if triggered:
        overall = "weakened"
    elif "weakened" in directions:
        overall = "weakened"
    elif "improved" in directions:
        overall = "improved"
    elif directions == {"unchanged"}:
        overall = "unchanged"
    else:
        overall = "unknown"
    if old.get("state") != new.get("state"):
        state_direction = (
            "improved"
            if old.get("state") in STATE_RANK
            and new.get("state") in STATE_RANK
            and STATE_RANK[new["state"]] > STATE_RANK[old["state"]]
            else "weakened"
            if old.get("state") in STATE_RANK
            and new.get("state") in STATE_RANK
            else "unknown"
        )
        if state_direction not in directions and not newly_triggered:
            errors.append("overall state changed without matching evidence-backed drift")
    return {
        "status": "fail" if errors else "pass",
        "overall": overall,
        "dimensions": dimensions,
        "triggered_red_lines": [item.get("id") for item in triggered],
        "newly_triggered_red_lines": [item.get("id") for item in newly_triggered],
        "resolved_red_lines": sorted(resolved),
        "errors": errors,
    }


def resolve_decision_links(decisions: list[dict], theses: list[dict]) -> list[dict]:
    """Add resolvable thesis metadata without mutating historical thesis_id."""
    by_id = {doc.get("thesis_id"): doc for doc in theses}
    out = []
    for decision in decisions:
        linked = copy.deepcopy(decision)
        thesis_id = linked.get("thesis_id")
        doc = by_id.get(thesis_id)
        linked["thesis_ref"] = (
            {
                "status": "resolved", "thesis_id": thesis_id,
                "schema_version": doc.get("schema_version"),
                "state": doc.get("state"), "checked_at": doc.get("checked_at"),
            }
            if doc and doc.get("ticker") == linked.get("ticker")
            else {
                "status": "mismatch" if doc else "unknown",
                "thesis_id": thesis_id,
            }
        )
        out.append(linked)
    return out


def load_registry(path: Path) -> tuple[list[dict], list[str]]:
    docs, errors = [], []
    if not path.exists():
        return docs, errors
    thesis_ids = {}
    tickers = {}
    for file in sorted(path.glob("*.json")):
        try:
            doc = json.loads(file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{file.name}: {exc}")
            continue
        doc_errors = validate_thesis(doc, now=datetime.now(timezone.utc))
        if doc_errors:
            errors.extend(f"{file.name}: {error}" for error in doc_errors)
            continue
        duplicate = False
        for field, seen in (("thesis_id", thesis_ids), ("ticker", tickers)):
            value = doc[field]
            if value in seen:
                errors.append(
                    f"duplicate {field} {value!r}: {seen[value]} and {file.name}"
                )
                duplicate = True
        if not duplicate:
            thesis_ids[doc["thesis_id"]] = file.name
            tickers[doc["ticker"]] = file.name
            docs.append(doc)
    return docs, errors


def registry_summary(path: Path, active_tickers: list[str]) -> dict:
    docs, errors = load_registry(path)
    by_ticker = {doc["ticker"]: doc for doc in docs}
    return {
        "status": "invalid" if errors else ("ready" if docs else "empty"),
        "theses": {
            ticker: (
                {
                    "status": "resolved", "thesis_id": by_ticker[ticker]["thesis_id"],
                    "state": by_ticker[ticker]["state"],
                    "checked_at": by_ticker[ticker]["checked_at"],
                    "next_review_trigger": by_ticker[ticker]["next_review_trigger"],
                }
                if ticker in by_ticker else {"status": "unknown"}
            )
            for ticker in active_tickers
        },
        "errors": errors,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("path", type=Path)
    drift = sub.add_parser("drift")
    drift.add_argument("old", type=Path)
    drift.add_argument("new", type=Path)
    args = parser.parse_args(argv)
    try:
        new = json.loads(args.path.read_text()) if args.command == "validate" else json.loads(args.new.read_text())
        if args.command == "validate":
            errors = validate_thesis(new, now=datetime.now(timezone.utc))
            result = {"status": "pass" if not errors else "fail", "errors": errors}
        else:
            old = json.loads(args.old.read_text())
            result = evaluate_drift(old, new, now=datetime.now(timezone.utc))
    except (OSError, json.JSONDecodeError) as exc:
        result = {"status": "fail", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
