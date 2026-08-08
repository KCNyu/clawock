"""safe_io must never write JSON a strict parser rejects.

`json.dump` emits the bare tokens `NaN` / `Infinity` / `-Infinity` by default.
No strict parser accepts them, including the browser `JSON.parse` that reads
every file under `assets/data/` — so one non-finite float takes a dashboard
card down. `json_repair` already refuses these tokens when reading; these tests
hold the write side to the same contract.
"""
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

from clawock import safe_io  # noqa: E402


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_written_as_null_not_as_python_tokens(tmp_path, bad):
    target = tmp_path / "out.json"

    safe_io.safe_write_json(str(target), {"metric": bad, "ok": 1.5})

    raw = target.read_text()
    assert "NaN" not in raw and "Infinity" not in raw
    # json.loads is strict by default only for the *tokens*; parse and check the
    # value so a future sanitizer that emits a string is caught too.
    assert json.loads(raw) == {"metric": None, "ok": 1.5}


def test_nested_non_finite_values_are_sanitized_everywhere(tmp_path):
    target = tmp_path / "out.json"
    payload = {
        "legs": [{"beta": float("nan")}, {"beta": 1.0}],
        "nested": {"deep": {"sharpe": float("inf")}},
    }

    safe_io.safe_write_json(str(target), payload)

    assert json.loads(target.read_text()) == {
        "legs": [{"beta": None}, {"beta": 1.0}],
        "nested": {"deep": {"sharpe": None}},
    }


def test_sanitizer_reports_the_path_of_every_replaced_value():
    payload = {"us": {"beta": float("nan")}, "hk": [1.0, float("inf")]}

    out, found = safe_io.json_safe(payload)

    assert out == {"us": {"beta": None}, "hk": [1.0, None]}
    assert sorted(found) == ["$.hk[1]", "$.us.beta"]


def test_a_clean_payload_is_untouched_and_reports_nothing():
    payload = {"a": 1, "b": [1.0, 2.5], "c": {"d": "x"}, "e": None, "f": True}

    out, found = safe_io.json_safe(payload)

    assert out == payload
    assert found == []


def test_strict_mode_raises_instead_of_writing_a_hole(tmp_path):
    target = tmp_path / "out.json"

    with pytest.raises(ValueError, match="non-finite"):
        safe_io.safe_write_json(str(target), {"beta": float("nan")}, strict=True)

    assert not target.exists()


def test_a_bad_field_never_costs_the_whole_publish(tmp_path):
    """Detection must not degrade into "publish nothing" — the default path
    keeps every good field and only nulls the bad one."""
    target = tmp_path / "out.json"

    safe_io.safe_write_json(
        str(target), {"good": 42, "bad": float("nan"), "also_good": "kept"}
    )

    written = json.loads(target.read_text())
    assert written["good"] == 42
    assert written["also_good"] == "kept"
    assert written["bad"] is None


def test_numpy_scalars_are_coerced_before_the_finiteness_check():
    np = pytest.importorskip("numpy")
    payload = {"f32_nan": np.float32("nan"), "i64": np.int64(7),
               "f64": np.float64(1.25)}

    out, found = safe_io.json_safe(payload)

    assert found == ["$.f32_nan"]
    assert out["f32_nan"] is None
    assert out["i64"] == 7 and isinstance(out["i64"], int)
    assert out["f64"] == pytest.approx(1.25)
    # The point of the coercion: this is what json.dump would have choked on.
    json.dumps(out, allow_nan=False)


def test_written_file_survives_a_strict_reader(tmp_path):
    target = tmp_path / "out.json"

    safe_io.safe_write_json(str(target), {"x": float("nan")})

    # parse_constant fires exactly on the three tokens we must never emit.
    def _reject(token):
        raise AssertionError(f"strict parser hit {token!r}")

    assert json.loads(target.read_text(), parse_constant=_reject) == {"x": None}


def test_mutate_json_inherits_the_same_guarantee(tmp_path):
    target = tmp_path / "state.json"
    safe_io.safe_write_json(str(target), {"seed": 1})

    safe_io.mutate_json(str(target), lambda d: {**d, "beta": math.inf})

    assert json.loads(target.read_text()) == {"seed": 1, "beta": None}
