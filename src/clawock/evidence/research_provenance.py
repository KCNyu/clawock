"""Fail-closed numeric provenance gate for long-form research artifacts."""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCHEMA_VERSION = 1
CURRENCIES = {"USD", "HKD", "CNY", "EUR", "JPY", "NONE"}
# A manifest cannot authorize its own escape hatch: no metric may declare a
# looser two-source agreement band than this.
MAX_TOLERANCE_PCT = Decimal("5")
# Powers must stay integer and small: a fractional exponent is not exact arithmetic,
# and a large one pushes the result past Decimal's working precision, which would
# silently round the "exact" number this module exists to protect.
MAX_EXPONENT = 6
_NUMBER = re.compile(r"(?<![\w.])(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_DECIMAL_TOKEN = re.compile(r"D\('[^']*'\)")
_OPERATORS_ONLY = re.compile(r"[+\-*/%()\s]*")


def decimal_value(value, field: str = "value") -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} is not a decimal string") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _exponent_value(node) -> Decimal | None:
    """Return the literal Decimal an already-rewritten `D('n')` node evaluates to."""
    if (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "D" and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        try:
            return Decimal(node.args[0].value)
        except InvalidOperation:
            return None
    return None


def exact_calculate(expression: str) -> Decimal:
    """Evaluate arithmetic after replacing every numeric token with Decimal.

    Every reachable failure raises ValueError so callers — and the CLI, whose
    contract is one JSON object per run — never see a raw traceback instead of a
    verdict.
    """
    if not expression or not re.fullmatch(r"[\d.eE+\-*/()%\s]+", expression):
        raise ValueError("expression contains unsupported characters")
    rewritten = _NUMBER.sub(lambda m: f"D('{m.group(0)}')", expression)
    # `1e` and `ee` survive the character allow-list because `e` is legal inside a
    # numeric exponent. Anything left over after removing the generated Decimal
    # tokens must be operators, or the expression carries a bare identifier.
    if not _OPERATORS_ONLY.fullmatch(_DECIMAL_TOKEN.sub("", rewritten)):
        raise ValueError("expression contains a non-numeric token")
    try:
        tree = ast.parse(rewritten, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"expression is not valid arithmetic: {exc.msg}") from exc
    allowed = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Load, ast.Name,
        ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
        ast.UAdd, ast.USub,
    )
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError("expression contains unsupported syntax")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id != "D"
            or len(node.args) != 1 or node.keywords
        ):
            raise ValueError("expression contains an invalid call")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = _exponent_value(node.right)
            if exponent is None or exponent != exponent.to_integral_value():
                raise ValueError("exponent must be an integer literal")
            if abs(exponent) > MAX_EXPONENT:
                raise ValueError(f"exponent must be within ±{MAX_EXPONENT}")
    try:
        return eval(compile(tree, "<decimal-expression>", "eval"),  # noqa: S307
                    {"__builtins__": {}, "D": Decimal}, {})
    except ArithmeticError as exc:
        # decimal.DecimalException (DivisionUndefined, Overflow, InvalidOperation…)
        # and ZeroDivisionError all land here.
        raise ValueError(f"expression is not computable: {exc.__class__.__name__}") from exc
    except NameError as exc:  # defence in depth behind the token check above
        raise ValueError(f"expression contains an unknown name: {exc}") from exc


def _tolerance(value, field: str) -> Decimal:
    tolerance = decimal_value(value, field)
    if tolerance < 0:
        raise ValueError(f"{field} must be non-negative")
    if tolerance > MAX_TOLERANCE_PCT:
        raise ValueError(f"{field} must not exceed the {MAX_TOLERANCE_PCT}% cap")
    return tolerance


def market_cap_result(price: str, shares: str, reported: str, currency: str,
                      tolerance_pct: str = "1") -> dict:
    if currency not in CURRENCIES - {"NONE"}:
        raise ValueError(f"currency must be one of {sorted(CURRENCIES - {'NONE'})}")
    p = decimal_value(price, "price")
    s = decimal_value(shares, "shares")
    r = decimal_value(reported, "reported")
    tolerance = _tolerance(tolerance_pct, "tolerance_pct")
    if p < 0 or s <= 0 or r <= 0:
        raise ValueError("price must be non-negative; shares/reported positive; tolerance non-negative")
    calculated = p * s
    deviation = abs(calculated - r) / r * Decimal("100")
    return {
        "status": "pass" if deviation <= tolerance else "fail",
        "currency": currency,
        "calculated": str(calculated),
        "reported": str(r),
        "deviation_pct": str(deviation),
        "tolerance_pct": str(tolerance),
    }


def _timestamp(value, field, errors):
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        errors.append(f"{field} must be an ISO-8601 timestamp")


def validate_manifest(payload: dict) -> dict:
    errors: list[str] = []
    metrics = payload.get("metrics")
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not payload.get("artifact_id"):
        errors.append("artifact_id is required")
    if not isinstance(metrics, list) or not metrics:
        errors.append("metrics must contain at least one metric")
        metrics = []

    ids = set()
    verified = 0
    for index, metric in enumerate(metrics):
        prefix = f"metrics[{index}]"
        if not isinstance(metric, dict):
            errors.append(f"{prefix} must be an object")
            continue
        metric_id = metric.get("id")
        if not metric_id or metric_id in ids:
            errors.append(f"{prefix}.id must be present and unique")
        if metric_id:
            ids.add(metric_id)
        for field in ("name", "ticker", "period", "as_of", "unit", "basis"):
            if not metric.get(field):
                errors.append(f"{prefix}.{field} is required")
        currency = metric.get("currency")
        if currency not in CURRENCIES:
            errors.append(f"{prefix}.currency must be one of {sorted(CURRENCIES)}")
        try:
            reported = decimal_value(metric.get("reported_value"), f"{prefix}.reported_value")
        except ValueError as exc:
            errors.append(str(exc))
            reported = None

        source = metric.get("source")
        check = metric.get("verification")
        for label, item in (("source", source), ("verification", check)):
            if not isinstance(item, dict):
                errors.append(f"{prefix}.{label} is required")
                continue
            for field in ("source_class", "locator", "fetched_at"):
                if not item.get(field):
                    errors.append(f"{prefix}.{label}.{field} is required")
            _timestamp(item.get("fetched_at"), f"{prefix}.{label}.fetched_at", errors)

        if isinstance(source, dict) and isinstance(check, dict):
            if (source.get("locator") == check.get("locator")
                    or source.get("source_class") == check.get("source_class")):
                errors.append(f"{prefix}.verification must use an independent source")
            for field in ("period", "unit", "currency", "basis"):
                expected = metric.get(field)
                if check.get(field) != expected:
                    errors.append(f"{prefix}.verification.{field} must match metric {field}")
            try:
                fetched = decimal_value(check.get("value"), f"{prefix}.verification.value")
                tolerance = _tolerance(metric.get("tolerance_pct", "1"),
                                       f"{prefix}.tolerance_pct")
                if reported is not None:
                    deviation = (abs(reported - fetched) / abs(reported) * 100
                                 if reported else (Decimal(0) if not fetched else Decimal("Infinity")))
                    if deviation > tolerance:
                        errors.append(f"{prefix} exceeds tolerance ({deviation}% > {tolerance}%)")
                    else:
                        verified += 1
            except ValueError as exc:
                errors.append(str(exc))

    referenced = payload.get("referenced_metric_ids", [])
    if not isinstance(referenced, list) or not referenced:
        errors.append("referenced_metric_ids must be a non-empty list")
    else:
        for metric_id in referenced:
            if metric_id not in ids:
                errors.append(f"referenced metric {metric_id!r} is missing")

    return {
        "status": "pass" if not errors and verified > 0 else "fail",
        "verified_metrics": verified,
        "total_metrics": len(metrics),
        "errors": errors or ([] if verified else ["zero metrics were verified"]),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    calc = sub.add_parser("calc")
    calc.add_argument("--expr", required=True)
    cap = sub.add_parser("market-cap")
    for name in ("price", "shares", "reported", "currency"):
        cap.add_argument(f"--{name}", required=True)
    cap.add_argument("--tolerance-pct", default="1")
    manifest = sub.add_parser("verify-manifest")
    manifest.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "calc":
            result = {"status": "pass", "result": str(exact_calculate(args.expr))}
        elif args.command == "market-cap":
            result = market_cap_result(
                args.price, args.shares, args.reported, args.currency, args.tolerance_pct
            )
        else:
            result = validate_manifest(json.loads(args.path.read_text()))
    except (ValueError, OSError, json.JSONDecodeError, ArithmeticError) as exc:
        result = {"status": "fail", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
