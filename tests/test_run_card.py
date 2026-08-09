"""A backtest has to leave evidence behind.

The defect: the three backtest scripts wrote PNGs to `memory/.tmp/` and printed
a table, while their conclusions are quoted as permanent justification — the
production leverage dial is introduced with "-95% to 0%" in
`compute_regime.py`'s own docstring. Those numbers could not be re-derived,
because a rerun refetches a live upstream that has since moved.

Run: python3 -m pytest tests/test_run_card.py -q
"""
import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "data"
PACKAGE = ROOT / "src" / "clawock"
from clawock import run_card

BACKTESTS = (
    "backtest_hstech_regime.py",
    "backtest_us_leverage.py",
    "backtest_combined_regime.py",
)


def _card(**overrides):
    payload = dict(
        params={"ma": 200, "vol_cap": 0.5},
        inputs=[{"symbol": "hkHSTECH", "source": "tencent", "bars": 3,
                 "first_session": "2021-01-04", "last_session": "2021-01-06",
                 "digest": "sha256:deadbeef"}],
        metrics={"regime": {"max_drawdown": -0.44}},
    )
    payload.update(overrides)
    return run_card.build_card("fixture", **payload)


def test_a_card_records_what_a_rerun_would_otherwise_lose():
    card = _card()

    assert card["backtest"] == "fixture"
    assert card["params"]["ma"] == 200
    assert card["inputs"][0]["first_session"] == "2021-01-04"
    assert card["metrics"]["regime"]["max_drawdown"] == -0.44
    assert card["run_id"].startswith("fixture-")


def test_the_series_digest_identifies_the_input_without_republishing_it():
    series = [("2021-01-04", 10.0), ("2021-01-05", 10.5)]

    digest = run_card.series_digest(series)

    assert digest == run_card.series_digest(list(series)), "must be stable"
    # A provider revision to one close changes it.
    assert digest != run_card.series_digest(
        [("2021-01-04", 10.0), ("2021-01-05", 10.51)])
    # And no price survives into the digest itself.
    assert "10.5" not in digest


def test_the_series_digest_reads_bar_dicts_as_well_as_pairs():
    assert run_card.series_digest([{"date": "2021-01-04", "close": 10.0}]) == \
        run_card.series_digest([("2021-01-04", 10.0)])


def test_the_reproduction_key_covers_params_inputs_and_code():
    base = _card()

    assert _card()["reproduction_key"] == base["reproduction_key"]
    assert _card(params={"ma": 150, "vol_cap": 0.5})["reproduction_key"] \
        != base["reproduction_key"]
    moved = [dict(base["inputs"][0], digest="sha256:cafe")]
    assert _card(inputs=moved)["reproduction_key"] != base["reproduction_key"]


def test_a_metric_change_alone_does_not_change_the_reproduction_key():
    """The key answers "same run?", not "same answer?" — that separation is what
    makes a mismatch meaningful: identical key + different metrics means the
    result is not reproducible, and that must be visible rather than hidden by
    folding metrics into the key."""
    base = _card()
    other = _card(metrics={"regime": {"max_drawdown": -0.10}})

    assert other["reproduction_key"] == base["reproduction_key"]
    assert other["metrics"] != base["metrics"]


def test_code_identity_travels_with_the_card():
    card = _card(code_files=[PACKAGE / "compute_regime.py"])

    entry = card["code"][0]
    assert entry["file"] == "compute_regime.py"
    assert entry["digest"].startswith("sha256:")


def test_a_missing_code_file_is_recorded_as_missing_not_silently_dropped():
    card = _card(code_files=[DATA / "does_not_exist.py"])

    assert card["code"] == [{"file": "does_not_exist.py", "digest": None}]


def test_a_written_card_round_trips_as_strict_json(tmp_path):
    path = run_card.write_card(_card(), cards_dir=tmp_path)

    raw = path.read_text()
    assert "NaN" not in raw and "Infinity" not in raw
    assert json.loads(raw)["metrics"]["regime"]["max_drawdown"] == -0.44


def test_a_non_finite_metric_refuses_to_become_a_card(tmp_path):
    """A card is evidence. Publishing `null` for a metric the run actually
    produced would make the evidence lie, and nothing downstream depends on the
    card existing, so failing costs only the card."""
    with pytest.raises(ValueError, match="non-finite"):
        run_card.write_card(
            _card(metrics={"regime": {"max_drawdown": float("nan")}}),
            cards_dir=tmp_path)

    assert list(tmp_path.glob("*.json")) == []


def test_cards_can_be_listed_back(tmp_path):
    run_card.write_card(_card(), cards_dir=tmp_path)

    loaded = run_card.load_cards(cards_dir=tmp_path)

    assert len(loaded) == 1 and loaded[0]["backtest"] == "fixture"


def test_load_cards_is_empty_rather_than_failing_on_a_fresh_checkout(tmp_path):
    assert run_card.load_cards(cards_dir=tmp_path / "nope") == []


# ── the structural gate ─────────────────────────────────────────────────────

@pytest.mark.parametrize("script", BACKTESTS)
def test_every_backtest_records_a_run_card(script):
    """The whole defect was that the runs left nothing behind, so this is the
    load-bearing assertion. Checked through the AST rather than by searching the
    text, so a mention in a docstring cannot satisfy it."""
    tree = ast.parse((DATA / script).read_text())

    imports_it = any(
        (
            isinstance(node, ast.Import)
            and any(alias.name == "run_card" for alias in node.names)
        ) or (
            isinstance(node, ast.ImportFrom)
            and node.module == "clawock"
            and any(alias.name == "run_card" for alias in node.names)
        )
        for node in ast.walk(tree)
    )
    calls_record = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "record"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "run_card"
        for node in ast.walk(tree)
    )

    assert imports_it, f"{script} does not import run_card"
    assert calls_record, f"{script} never calls run_card.record — it leaves no evidence"


@pytest.mark.parametrize("script", BACKTESTS)
def test_each_backtest_hashes_the_code_its_result_depends_on(script):
    """A card that pins the inputs but not the code cannot tell you why two runs
    with the same reproduction key disagreed."""
    tree = ast.parse((DATA / script).read_text())
    code_file_values = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "record"
        for keyword in node.keywords
        if keyword.arg == "code_files"
    ]
    hashes_production = any(
        isinstance(node, ast.Attribute)
        and node.attr == "__file__"
        and isinstance(node.value, ast.Name)
        and node.value.id == "compute_regime"
        for value in code_file_values
        for node in ast.walk(value)
    )

    assert code_file_values, f"{script} records no code identity"
    assert hashes_production, (
        f"{script} does not hash the packaged compute_regime module whose "
        "thresholds it is measuring")
