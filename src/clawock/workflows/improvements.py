"""Deterministic outcome evaluation and bounded workflow improvement records."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from clawock.runtime_model import CONFIG_NAME
from clawock.workflows.request import load_request
from clawock.publish.store import write_generation

from .registry import load_workflow
from .validators import validators_for


BPS = Decimal("10000")
BPS_PRECISION = Decimal("0.01")
IMPROVEMENT_ROOT = Path(".clawock/improvements")
DIRECTION = {
    "buy": Decimal("1"),
    "add": Decimal("1"),
    "hold": Decimal("1"),
    "trim": Decimal("-1"),
    "sell": Decimal("-1"),
    "exit": Decimal("-1"),
    "watch": Decimal("0"),
    "abstain": Decimal("0"),
}


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_object(path: Path | str, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {label}: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _aware_time(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _positive_decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return number


def _bps(value: Decimal) -> str:
    return str(value.quantize(BPS_PRECISION, rounding=ROUND_HALF_UP))


def evaluate_investment_outcome(
    decision: Mapping[str, Any],
    outcome: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconcile one observed price/FX outcome against a certified decision."""
    artifacts = {"decision.json": json.dumps(decision, ensure_ascii=False)}
    issues = validators_for(contract)[0].validate(artifacts)
    if issues:
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise ValueError(f"decision.json failed workflow validation: {summary}")

    required = {
        "schema_version", "workflow", "decision_id", "observed_at", "evidence"
    }
    if set(outcome) != required or outcome.get("schema_version") != 1:
        raise ValueError(
            "outcome must contain exactly schema_version, workflow, decision_id, "
            "observed_at and evidence"
        )
    expected_workflow = {
        "id": contract.get("id"), "version": contract.get("version")
    }
    if outcome.get("workflow") != expected_workflow:
        raise ValueError("outcome workflow does not match the prepared workflow")
    if outcome.get("decision_id") != decision.get("decision_id"):
        raise ValueError("outcome decision_id does not match decision.json")
    observed_at = _aware_time(outcome.get("observed_at"), "outcome.observed_at")
    decision_as_of = _aware_time(decision.get("as_of"), "decision.as_of")
    if observed_at <= decision_as_of:
        raise ValueError("outcome.observed_at must be later than decision.as_of")

    evidence = outcome.get("evidence")
    evidence_fields = {
        "source", "source_class", "quote_currency", "entry_price",
        "outcome_price", "base_currency", "entry_fx_quote_to_base",
        "outcome_fx_quote_to_base",
    }
    if not isinstance(evidence, dict) or set(evidence) != evidence_fields:
        raise ValueError(
            "outcome.evidence must contain exactly source, source_class, currencies, "
            "prices and entry/outcome FX rates"
        )
    if evidence.get("source_class") not in {"broker", "exchange", "market_data"}:
        raise ValueError("outcome.evidence.source_class must be broker, exchange or market_data")
    if not isinstance(evidence.get("source"), str) or not evidence["source"].strip():
        raise ValueError("outcome.evidence.source is required")
    for field in ("quote_currency", "base_currency"):
        if not isinstance(evidence.get(field), str) or not evidence[field].strip():
            raise ValueError(f"outcome.evidence.{field} is required")
    if evidence["quote_currency"] != decision["subject"]["currency"]:
        raise ValueError("outcome quote_currency must match decision subject currency")

    entry_price = _positive_decimal(evidence["entry_price"], "entry_price")
    outcome_price = _positive_decimal(evidence["outcome_price"], "outcome_price")
    entry_fx = _positive_decimal(
        evidence["entry_fx_quote_to_base"], "entry_fx_quote_to_base"
    )
    outcome_fx = _positive_decimal(
        evidence["outcome_fx_quote_to_base"], "outcome_fx_quote_to_base"
    )
    if evidence["quote_currency"] == evidence["base_currency"] and (
        entry_fx != Decimal("1") or outcome_fx != Decimal("1")
    ):
        raise ValueError("same-currency outcome FX rates must both equal 1")

    quote_move = ((outcome_price / entry_price) - 1) * BPS
    entry_base = entry_price * entry_fx
    outcome_base = outcome_price * outcome_fx
    base_move = ((outcome_base / entry_base) - 1) * BPS
    action = decision["decision"]["action"]
    direction = DIRECTION[action]
    return {
        "schema_version": 1,
        "kind": "outcome-evaluation",
        "evaluation_id": uuid4().hex,
        "created_at": _now(),
        "workflow": dict(contract),
        "decision_id": decision["decision_id"],
        "action": action,
        "decision_as_of": decision["as_of"],
        "observed_at": outcome["observed_at"],
        "outcome_evidence": {
            "sha256": _sha256(outcome),
            "source": evidence["source"],
            "source_class": evidence["source_class"],
        },
        "measurements": {
            "quote_currency": evidence["quote_currency"],
            "base_currency": evidence["base_currency"],
            "quote_market_move_bps": _bps(quote_move),
            "base_market_move_bps": _bps(base_move),
            "decision_value_bps": _bps(direction * base_move),
        },
        "interpretation": (
            "decision_value_bps is a direction-adjusted market outcome, not "
            "realized portfolio P&L; watch and abstain score zero"
        ),
    }


def evaluate_files(
    workflow_id: str, decision_path: Path | str, outcome_path: Path | str
) -> dict[str, Any]:
    if workflow_id != "investment-decision":
        raise ValueError(f"workflow has no outcome evaluator: {workflow_id}")
    pack = load_workflow(workflow_id)
    return evaluate_investment_outcome(
        _read_object(decision_path, "decision"),
        _read_object(outcome_path, "outcome"),
        pack.contract(),
    )


def _parse_trigger(trigger: Mapping[str, Any], contract: Mapping[str, Any]) -> str:
    if trigger.get("kind") == "outcome-evaluation":
        if trigger.get("workflow") != dict(contract):
            raise ValueError("outcome evaluation workflow does not match workspace")
        return str(trigger.get("evaluation_id") or "")
    if trigger.get("status") == "rejected" and trigger.get("validation_issues"):
        if trigger.get("workflow") != dict(contract):
            raise ValueError("validation receipt workflow does not match workspace")
        return str(trigger.get("run_id") or "")
    raise ValueError(
        "trigger must be an outcome evaluation or a rejected validation receipt"
    )


def create_proposal(
    workspace: Path | str,
    trigger_path: Path | str,
    changes: Mapping[str, Any],
    *,
    rationale: str,
    expected_effect: str,
) -> dict[str, Any]:
    """Create a bounded proposal; it cannot apply or review itself."""
    request = load_request(workspace)
    if not request.workflow:
        raise ValueError("workspace has no pinned workflow")
    if not rationale.strip() or not expected_effect.strip():
        raise ValueError("proposal rationale and expected effect are required")
    if not changes:
        raise ValueError("proposal must change at least one workflow parameter")
    trigger = _read_object(trigger_path, "proposal trigger")
    trigger_id = _parse_trigger(trigger, request.workflow)
    if not trigger_id:
        raise ValueError("proposal trigger has no stable identifier")

    pack = load_workflow(str(request.workflow["id"]))
    before = dict(request.workflow["parameters"])
    after = dict(before)
    after.update(changes)
    checked = pack.contract(after)
    unchanged = [
        name for name in changes
        if checked["parameters"].get(name) == before.get(name)
    ]
    if unchanged:
        raise ValueError(f"proposal parameters are unchanged: {sorted(unchanged)}")
    bounded_changes = {
        name: {"before": before[name], "after": checked["parameters"][name]}
        for name in sorted(changes)
    }
    return {
        "schema_version": 1,
        "kind": "workflow-improvement-proposal",
        "proposal_id": uuid4().hex,
        "created_at": _now(),
        "workflow": dict(request.workflow),
        "trigger": {
            "kind": "outcome_evaluation"
            if trigger.get("kind") == "outcome-evaluation"
            else "validation_receipt",
            "id": trigger_id,
            "sha256": _sha256(trigger),
        },
        "changes": bounded_changes,
        "rationale": rationale.strip(),
        "expected_effect": expected_effect.strip(),
    }


def review_proposal(
    proposal_path: Path | str, *, disposition: str, reviewer: str, note: str
) -> dict[str, Any]:
    proposal = _read_object(proposal_path, "proposal")
    _validate_proposal(proposal)
    if disposition not in {"accepted", "rejected"}:
        raise ValueError("review disposition must be accepted or rejected")
    if not reviewer.strip() or not note.strip():
        raise ValueError("reviewer and review note are required")
    return {
        "schema_version": 1,
        "kind": "workflow-improvement-review",
        "review_id": uuid4().hex,
        "created_at": _now(),
        "proposal_id": proposal["proposal_id"],
        "proposal_sha256": _sha256(proposal),
        "disposition": disposition,
        "reviewer": reviewer.strip(),
        "note": note.strip(),
    }


def _validate_proposal(proposal: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "kind", "proposal_id", "created_at", "workflow",
        "trigger", "changes", "rationale", "expected_effect",
    }
    if set(proposal) != required or proposal.get("schema_version") != 1 or (
        proposal.get("kind") != "workflow-improvement-proposal"
    ):
        raise ValueError("invalid workflow improvement proposal")
    if not _is_hex(proposal.get("proposal_id"), 32):
        raise ValueError("proposal has an invalid proposal_id")
    _aware_time(proposal.get("created_at"), "proposal.created_at")
    workflow = proposal.get("workflow")
    if not isinstance(workflow, dict) or set(workflow) != {
        "id", "version", "certificate", "parameters"
    } or not _is_hex(workflow.get("certificate"), 64):
        raise ValueError("proposal has an invalid workflow contract")
    trigger = proposal.get("trigger")
    if not isinstance(trigger, dict) or set(trigger) != {"kind", "id", "sha256"} or (
        trigger.get("kind") not in {"outcome_evaluation", "validation_receipt"}
    ) or not isinstance(trigger.get("id"), str) or not trigger["id"] or (
        not _is_hex(trigger.get("sha256"), 64)
    ):
        raise ValueError("proposal has an invalid evidence trigger")
    if any(
        not isinstance(proposal.get(field), str) or not proposal[field].strip()
        for field in ("rationale", "expected_effect")
    ):
        raise ValueError("proposal rationale and expected effect are required")
    if not isinstance(proposal.get("changes"), dict) or not proposal["changes"]:
        raise ValueError("proposal has no parameter changes")
    for name, change in proposal["changes"].items():
        if not isinstance(name, str) or not isinstance(change, dict) or (
            set(change) != {"before", "after"}
        ):
            raise ValueError("proposal parameter changes are malformed")


def _is_hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_review(review: Mapping[str, Any], proposal: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "kind", "review_id", "created_at", "proposal_id",
        "proposal_sha256", "disposition", "reviewer", "note",
    }
    if set(review) != required or review.get("schema_version") != 1 or (
        review.get("kind") != "workflow-improvement-review"
    ):
        raise ValueError("invalid workflow improvement review")
    if not _is_hex(review.get("review_id"), 32):
        raise ValueError("review has an invalid review_id")
    _aware_time(review.get("created_at"), "review.created_at")
    if review.get("proposal_id") != proposal["proposal_id"] or (
        review.get("proposal_sha256") != _sha256(proposal)
    ):
        raise ValueError("review does not certify this exact proposal")
    if review.get("disposition") not in {"accepted", "rejected"}:
        raise ValueError("review disposition must be accepted or rejected")
    if any(
        not isinstance(review.get(field), str) or not review[field].strip()
        for field in ("reviewer", "note")
    ):
        raise ValueError("reviewer and review note are required")


def _read_workspace_config(workspace: Path | str) -> tuple[Path, dict[str, Any]]:
    root = Path(workspace).expanduser().resolve()
    config_path = root / CONFIG_NAME
    payload = _read_object(config_path, CONFIG_NAME)
    return root, payload


def _serialize(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _history_with(history_path: Path, event: Mapping[str, Any]) -> str:
    try:
        existing = history_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    if existing and not existing.endswith("\n"):
        raise ValueError(f"improvement history is not newline terminated: {history_path}")
    return existing + _canonical(event) + "\n"


def apply_proposal(
    workspace: Path | str, proposal_path: Path | str, review_path: Path | str
) -> dict[str, Any]:
    """Apply an accepted proposal and persist enough state for strict rollback."""
    proposal = _read_object(proposal_path, "proposal")
    review = _read_object(review_path, "proposal review")
    _validate_proposal(proposal)
    _validate_review(review, proposal)
    if review.get("disposition") != "accepted":
        raise ValueError("only an explicitly accepted proposal can be applied")

    root, config = _read_workspace_config(workspace)
    request = load_request(root)
    if dict(request.workflow) != proposal.get("workflow"):
        raise ValueError("workspace workflow changed after proposal creation")
    before_overrides = config.get("workflow_parameters", {})
    if not isinstance(before_overrides, dict):
        raise ValueError(f"{CONFIG_NAME} workflow_parameters must be an object")
    effective = dict(request.workflow["parameters"])
    after_overrides = dict(before_overrides)
    for name, change in proposal["changes"].items():
        if effective.get(name) != change["before"]:
            raise ValueError(f"workflow parameter changed since proposal: {name}")
        after_overrides[name] = change["after"]
    pack = load_workflow(str(request.workflow["id"]))
    pack.contract(after_overrides)

    updated = dict(config)
    updated["workflow_parameters"] = after_overrides
    change_id = uuid4().hex
    change = {
        "schema_version": 1,
        "kind": "workflow-improvement-change",
        "change_id": change_id,
        "created_at": _now(),
        "proposal_id": proposal["proposal_id"],
        "proposal_sha256": _sha256(proposal),
        "review_id": review.get("review_id"),
        "workflow": dict(request.workflow),
        "before_overrides": before_overrides,
        "after_overrides": after_overrides,
        "status": "applied",
    }
    change_path = root / IMPROVEMENT_ROOT / "changes" / f"{change_id}.json"
    history_path = root / IMPROVEMENT_ROOT / "history.jsonl"
    write_generation({
        str(root / CONFIG_NAME): _serialize(updated),
        str(change_path): _serialize(change),
        str(history_path): _history_with(history_path, change),
    })
    return change


def rollback_change(workspace: Path | str, change_id: str) -> dict[str, Any]:
    root, config = _read_workspace_config(workspace)
    if not _is_hex(change_id, 32):
        raise ValueError("change_id must be 32 lowercase hexadecimal characters")
    change_path = root / IMPROVEMENT_ROOT / "changes" / f"{change_id}.json"
    change = _read_object(change_path, "improvement change")
    if change.get("change_id") != change_id or change.get("status") != "applied":
        raise ValueError("change record is not an applied improvement")
    current = config.get("workflow_parameters", {})
    if current != change.get("after_overrides"):
        raise ValueError("workspace parameters drifted after apply; refusing rollback")

    restored = dict(config)
    before = change.get("before_overrides")
    if before:
        restored["workflow_parameters"] = before
    else:
        restored.pop("workflow_parameters", None)
    event = {
        "schema_version": 1,
        "kind": "workflow-improvement-rollback",
        "rollback_id": uuid4().hex,
        "created_at": _now(),
        "change_id": change_id,
        "workflow": change.get("workflow"),
        "restored_overrides": before,
    }
    history_path = root / IMPROVEMENT_ROOT / "history.jsonl"
    write_generation({
        str(root / CONFIG_NAME): _serialize(restored),
        str(history_path): _history_with(history_path, event),
    })
    return event
