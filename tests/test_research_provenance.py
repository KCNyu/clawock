import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from clawock.evidence import research_provenance as rp

ROOT = Path(__file__).resolve().parents[1]

def metric():
    return {
        "id": "revenue-fy25",
        "name": "Revenue",
        "ticker": "TEST",
        "period": "FY2025",
        "as_of": "2025-12-31",
        "unit": "million",
        "currency": "USD",
        "basis": "GAAP",
        "reported_value": "100.00",
        "tolerance_pct": "1",
        "source": {
            "source_class": "issuer_filing",
            "locator": "filing:primary",
            "fetched_at": "2026-07-26T10:00:00+08:00",
        },
        "verification": {
            "value": "100.50",
            "source_class": "independent_dataset",
            "locator": "dataset:secondary",
            "fetched_at": "2026-07-26T10:01:00+08:00",
            "period": "FY2025",
            "unit": "million",
            "currency": "USD",
            "basis": "GAAP",
        },
    }


def manifest(metrics=None):
    return {
        "schema_version": 1,
        "artifact_id": "report-test-fy25",
        "referenced_metric_ids": ["revenue-fy25"],
        "metrics": [metric()] if metrics is None else metrics,
    }


def test_decimal_calculation_never_round_trips_through_float():
    assert rp.exact_calculate("0.1 + 0.2") == Decimal("0.3")


def test_market_cap_mismatch_and_bad_currency_fail():
    assert rp.market_cap_result("10", "10", "10000", "USD")["status"] == "fail"
    try:
        rp.market_cap_result("10", "10", "100", "USDT")
    except ValueError:
        pass
    else:
        raise AssertionError("malformed currency passed")


def test_valid_manifest_passes():
    result = rp.validate_manifest(manifest())
    assert result["status"] == "pass"
    assert result["verified_metrics"] == 1


def test_empty_manifest_fails_closed():
    result = rp.validate_manifest(manifest([]))
    assert result["status"] == "fail"


def test_missing_or_single_source_verification_fails_closed():
    missing = metric()
    missing.pop("verification")
    assert rp.validate_manifest(manifest([missing]))["status"] == "fail"

    same = metric()
    same["verification"]["locator"] = same["source"]["locator"]
    result = rp.validate_manifest(manifest([same]))
    assert result["status"] == "fail"
    assert any("independent source" in error for error in result["errors"])

    same_class = metric()
    same_class["verification"]["source_class"] = same_class["source"]["source_class"]
    assert rp.validate_manifest(manifest([same_class]))["status"] == "fail"


def test_period_currency_basis_and_tolerance_gates_turn_red():
    changed = metric()
    changed["verification"]["currency"] = "HKD"
    changed["verification"]["value"] = "80"
    result = rp.validate_manifest(manifest([changed]))
    assert result["status"] == "fail"
    assert any("currency" in error for error in result["errors"])
    assert any("exceeds tolerance" in error for error in result["errors"])


def test_missing_referenced_metric_fails():
    payload = manifest()
    payload["referenced_metric_ids"] = ["not-present"]
    assert rp.validate_manifest(payload)["status"] == "fail"


def test_cli_returns_nonzero_for_failed_gate(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest([])))
    assert rp.main(["verify-manifest", str(path)]) == 1


@pytest.mark.parametrize(
    "expression",
    ["1e", "ee", "0/0", "5%0", "1/0", "9**999999999", "2**1.5", "(", "1+"],
)
def test_hostile_expressions_fail_closed_with_one_json_object(expression, capsys):
    """A gate whose failure mode is a traceback cannot be parsed by its caller."""
    assert rp.main(["calc", "--expr", expression]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert payload["errors"]


def test_calc_cli_subprocess_prints_json_and_no_traceback():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "clawock", "provenance", "calc", "--expr", "0/0"],
        capture_output=True, text=True, check=False, env=env,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert json.loads(result.stdout)["status"] == "fail"


def test_small_exponents_still_evaluate_exactly():
    assert rp.exact_calculate("1.1**2") == Decimal("1.21")


def test_metric_cannot_authorize_its_own_tolerance():
    loose = metric()
    loose["tolerance_pct"] = "500"
    loose["verification"]["value"] = "400"  # 300% away from reported "100.00"
    result = rp.validate_manifest(manifest([loose]))
    assert result["status"] == "fail"
    assert result["verified_metrics"] == 0
    assert any(f"{rp.MAX_TOLERANCE_PCT}% cap" in error for error in result["errors"])


def test_market_cap_rejects_tolerance_above_cap():
    assert rp.market_cap_result("10", "10", "100", "USD", "5")["status"] == "pass"
    try:
        rp.market_cap_result("10", "10", "10000", "USD", "500")
    except ValueError as exc:
        assert "cap" in str(exc)
    else:
        raise AssertionError("an out-of-cap tolerance was honored")
