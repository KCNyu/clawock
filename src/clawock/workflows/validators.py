"""Code-enforced invariants for portable decision-workflow artifacts."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from clawock.harness.model import ValidationIssue


DECISION_ARTIFACT = "decision.json"
ACTIONS = {"buy", "add", "hold", "watch", "trim", "sell", "exit", "abstain"}
STANCES = {"supporting", "opposing", "context"}
SOURCE_CLASSES = {"primary", "secondary", "market", "agent"}
CENT = Decimal("0.01")


def _issue(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, message)


def _aware_time(value: Any, field: str, issues: list[ValidationIssue]):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        issues.append(_issue("invalid_timestamp", f"{field} must include a timezone"))
        return None


def _decimal(value: Any, field: str, issues: list[ValidationIssue]):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError):
        issues.append(_issue("invalid_money", f"{field} must be a positive finite number"))
        return None


def _object_fields(
    value: Any, required: set[str], field: str, issues: list[ValidationIssue]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        issues.append(_issue("invalid_shape", f"{field} must be an object"))
        return {}
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing:
        issues.append(_issue("missing_fields", f"{field} missing fields: {missing}"))
    if extra:
        issues.append(_issue("unknown_fields", f"{field} unknown fields: {extra}"))
    return value


class InvestmentDecisionValidator:
    """Require adversarial evidence and reconcile every proposed-order amount."""

    name = "investment-decision-v1"

    def __init__(self, contract: Mapping[str, Any]) -> None:
        self.contract = contract
        self.parameters = contract.get("parameters", {})

    def validate(self, artifacts: Mapping[str, str]) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        if DECISION_ARTIFACT not in artifacts:
            return (_issue(
                "missing_decision_artifact",
                f"workflow requires {DECISION_ARTIFACT}",
            ),)
        unexpected = sorted(set(artifacts) - {DECISION_ARTIFACT})
        if unexpected:
            issues.append(_issue(
                "unexpected_workflow_artifact",
                f"workflow does not declare artifacts: {unexpected}",
            ))
        try:
            document = json.loads(artifacts[DECISION_ARTIFACT])
        except json.JSONDecodeError as exc:
            return (_issue("invalid_decision_json", f"decision.json is invalid JSON: {exc}"),)

        top = _object_fields(document, {
            "schema_version", "workflow", "decision_id", "as_of", "subject",
            "evidence", "debate", "thesis", "decision",
        }, "decision", issues)
        if top.get("schema_version") != 1:
            issues.append(_issue("schema_version", "decision schema_version must be 1"))
        workflow = _object_fields(
            top.get("workflow"), {"id", "version"}, "workflow", issues
        )
        if workflow.get("id") != self.contract.get("id"):
            issues.append(_issue("workflow_mismatch", "decision workflow id is not prepared workflow"))
        if workflow.get("version") != self.contract.get("version"):
            issues.append(_issue("workflow_mismatch", "decision workflow version is not prepared version"))
        if not isinstance(top.get("decision_id"), str) or not top.get("decision_id", "").strip():
            issues.append(_issue("missing_decision_id", "decision_id must be a non-empty string"))
        as_of = _aware_time(top.get("as_of"), "as_of", issues)

        subject = _object_fields(
            top.get("subject"), {"ticker", "market", "currency"}, "subject", issues
        )
        for field in ("ticker", "market", "currency"):
            if not isinstance(subject.get(field), str) or not subject.get(field, "").strip():
                issues.append(_issue("invalid_subject", f"subject.{field} is required"))

        evidence = top.get("evidence")
        if not isinstance(evidence, list):
            issues.append(_issue("invalid_evidence", "evidence must be a list"))
            evidence = []
        evidence_by_id: dict[str, dict[str, Any]] = {}
        for index, raw in enumerate(evidence):
            item = _object_fields(raw, {
                "id", "stance", "summary", "source", "source_class", "observed_at",
            }, f"evidence[{index}]", issues)
            evidence_id = item.get("id")
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                issues.append(_issue("invalid_evidence_id", f"evidence[{index}].id is required"))
            elif evidence_id in evidence_by_id:
                issues.append(_issue("duplicate_evidence", f"duplicate evidence id: {evidence_id}"))
            else:
                evidence_by_id[evidence_id] = item
            if item.get("stance") not in STANCES:
                issues.append(_issue("invalid_stance", f"evidence[{index}].stance is invalid"))
            if item.get("source_class") not in SOURCE_CLASSES:
                issues.append(_issue("invalid_source_class", f"evidence[{index}].source_class is invalid"))
            for field in ("summary", "source"):
                if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                    issues.append(_issue("incomplete_evidence", f"evidence[{index}].{field} is required"))
            observed = _aware_time(item.get("observed_at"), f"evidence[{index}].observed_at", issues)
            if as_of and observed and observed > as_of:
                issues.append(_issue("future_evidence", f"evidence[{index}] is later than as_of"))

        min_supporting = int(self.parameters.get("min_supporting_evidence", 1))
        min_opposing = int(self.parameters.get("min_opposing_evidence", 1))
        supporting = {
            key for key, item in evidence_by_id.items()
            if item.get("stance") == "supporting"
        }
        opposing = {
            key for key, item in evidence_by_id.items()
            if item.get("stance") == "opposing"
        }
        if len(supporting) < min_supporting:
            issues.append(_issue(
                "insufficient_supporting_evidence",
                f"requires at least {min_supporting} supporting evidence item(s)",
            ))
        if len(opposing) < min_opposing:
            issues.append(_issue(
                "insufficient_opposing_evidence",
                f"requires at least {min_opposing} opposing evidence item(s)",
            ))

        debate = _object_fields(top.get("debate"), {"bull_case", "bear_case"}, "debate", issues)
        bull_refs = self._case_refs(debate.get("bull_case"), "bull_case", issues)
        bear_refs = self._case_refs(debate.get("bear_case"), "bear_case", issues)
        self._check_refs(bull_refs, set(evidence_by_id), "bull_case", issues)
        self._check_refs(bear_refs, set(evidence_by_id), "bear_case", issues)
        if bull_refs and not (set(bull_refs) & supporting):
            issues.append(_issue("unsupported_bull_case", "bull_case must cite supporting evidence"))
        if bear_refs and not (set(bear_refs) & opposing):
            issues.append(_issue("unsupported_bear_case", "bear_case must cite opposing evidence"))

        thesis = _object_fields(
            top.get("thesis"), {"statement", "confidence", "invalidation_conditions"},
            "thesis", issues,
        )
        if not isinstance(thesis.get("statement"), str) or not thesis.get("statement", "").strip():
            issues.append(_issue("empty_thesis", "thesis.statement is required"))
        confidence = thesis.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            issues.append(_issue("invalid_confidence", "thesis.confidence must be between 0 and 1"))
        invalidations = thesis.get("invalidation_conditions")
        if not isinstance(invalidations, list) or not invalidations or any(
            not isinstance(item, str) or not item.strip() for item in invalidations
        ):
            issues.append(_issue("missing_invalidation", "thesis requires non-empty invalidation conditions"))

        decision = _object_fields(
            top.get("decision"), {"action", "rationale", "evidence_ids", "order"},
            "decision", issues,
        )
        action = decision.get("action")
        if action not in ACTIONS:
            issues.append(_issue("invalid_action", f"decision.action must be one of {sorted(ACTIONS)}"))
        if not isinstance(decision.get("rationale"), str) or not decision.get("rationale", "").strip():
            issues.append(_issue("empty_rationale", "decision.rationale is required"))
        raw_decision_refs = decision.get("evidence_ids")
        if not isinstance(raw_decision_refs, list) or not raw_decision_refs:
            issues.append(_issue("unlinked_decision", "decision must cite evidence_ids"))
            raw_decision_refs = []
        if any(not isinstance(ref, str) or not ref for ref in raw_decision_refs):
            issues.append(_issue(
                "invalid_evidence_reference",
                "decision evidence_ids must be non-empty strings",
            ))
        decision_refs = [
            ref for ref in raw_decision_refs if isinstance(ref, str) and ref
        ]
        if len(decision_refs) != len(set(decision_refs)):
            issues.append(_issue(
                "duplicate_evidence_reference",
                "decision evidence_ids must be unique",
            ))
        self._check_refs(decision_refs, set(evidence_by_id), "decision", issues)

        max_without_primary = float(
            self.parameters.get("max_confidence_without_primary_source", 0.65)
        )
        cited = [evidence_by_id.get(ref, {}) for ref in decision_refs]
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and confidence > max_without_primary
            and not any(item.get("source_class") == "primary" for item in cited)
        ):
            issues.append(_issue(
                "confidence_without_primary_source",
                f"confidence above {max_without_primary} requires cited primary evidence",
            ))
        self._validate_order(
            action, decision.get("order"), subject.get("currency"), issues
        )
        return tuple(issues)

    @staticmethod
    def _case_refs(value, name, issues):
        case = _object_fields(value, {"summary", "evidence_ids"}, name, issues)
        if not isinstance(case.get("summary"), str) or not case.get("summary", "").strip():
            issues.append(_issue("empty_debate_case", f"{name}.summary is required"))
        refs = case.get("evidence_ids")
        if not isinstance(refs, list) or not refs:
            issues.append(_issue("unlinked_debate_case", f"{name} must cite evidence_ids"))
            return []
        invalid = [ref for ref in refs if not isinstance(ref, str) or not ref]
        if invalid:
            issues.append(_issue(
                "invalid_evidence_reference", f"{name} evidence_ids must be strings"
            ))
        valid = [ref for ref in refs if isinstance(ref, str) and ref]
        if len(valid) != len(set(valid)):
            issues.append(_issue(
                "duplicate_evidence_reference", f"{name} evidence_ids must be unique"
            ))
        return valid

    @staticmethod
    def _check_refs(refs, known, name, issues):
        invalid = sorted({
            str(ref) for ref in refs
            if not isinstance(ref, str) or ref not in known
        })
        if invalid:
            issues.append(_issue("missing_evidence_reference", f"{name} references missing evidence: {invalid}"))

    @staticmethod
    def _validate_order(action, raw, subject_currency, issues):
        if raw is None:
            if action in {"buy", "add", "trim", "sell", "exit"}:
                issues.append(_issue("missing_order", f"action {action} requires an order"))
            return
        if action in {"hold", "watch", "abstain"}:
            issues.append(_issue("unexpected_order", f"action {action} must not carry an order"))
        order = _object_fields(raw, {
            "side", "quantity", "unit_price", "quote_currency",
            "gross_amount_quote", "base_currency", "fx_quote_to_base",
            "gross_amount_base",
        }, "decision.order", issues)
        side = order.get("side")
        expected_side = "buy" if action in {"buy", "add"} else "sell"
        if side not in {"buy", "sell"}:
            issues.append(_issue("invalid_order_side", "decision.order.side must be buy or sell"))
        elif action in ACTIONS and action not in {"hold", "watch", "abstain"} and side != expected_side:
            issues.append(_issue("order_action_mismatch", f"action {action} requires order side {expected_side}"))
        for field in ("quote_currency", "base_currency"):
            if not isinstance(order.get(field), str) or not order.get(field, "").strip():
                issues.append(_issue("invalid_currency", f"decision.order.{field} is required"))
        if (
            isinstance(subject_currency, str)
            and isinstance(order.get("quote_currency"), str)
            and order.get("quote_currency") != subject_currency
        ):
            issues.append(_issue(
                "quote_currency_mismatch",
                "decision.order.quote_currency must match subject.currency",
            ))
        quantity = _decimal(order.get("quantity"), "decision.order.quantity", issues)
        price = _decimal(order.get("unit_price"), "decision.order.unit_price", issues)
        gross_quote = _decimal(
            order.get("gross_amount_quote"), "decision.order.gross_amount_quote", issues
        )
        fx = _decimal(order.get("fx_quote_to_base"), "decision.order.fx_quote_to_base", issues)
        gross_base = _decimal(
            order.get("gross_amount_base"), "decision.order.gross_amount_base", issues
        )
        if quantity and price and gross_quote:
            expected = (quantity * price).quantize(CENT, rounding=ROUND_HALF_UP)
            if gross_quote.quantize(CENT, rounding=ROUND_HALF_UP) != expected:
                issues.append(_issue(
                    "gross_amount_mismatch",
                    f"gross_amount_quote must equal quantity * unit_price ({expected})",
                ))
        if gross_quote and fx and gross_base:
            expected = (gross_quote * fx).quantize(CENT, rounding=ROUND_HALF_UP)
            if gross_base.quantize(CENT, rounding=ROUND_HALF_UP) != expected:
                issues.append(_issue(
                    "fx_amount_mismatch",
                    f"gross_amount_base must equal gross_amount_quote * fx ({expected})",
                ))
        if (
            order.get("quote_currency")
            and order.get("quote_currency") == order.get("base_currency")
            and fx is not None
            and fx != Decimal("1")
        ):
            issues.append(_issue(
                "same_currency_fx_mismatch",
                "fx_quote_to_base must be 1 when quote and base currency match",
            ))


def validators_for(contract: Mapping[str, Any]):
    workflow_id = contract.get("id")
    if not workflow_id:
        return ()
    if workflow_id == "investment-decision":
        return (InvestmentDecisionValidator(contract),)
    raise ValueError(f"no validators registered for workflow: {workflow_id}")
