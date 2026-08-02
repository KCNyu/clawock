"""The evidence page has exactly two ways to become a lie.

1. A number gets typed into the template instead of read, and goes stale
   silently — the same failure the static-copy rule already names.
2. An inconclusive result gets rendered as a passing one, which would make the
   page worth less than nothing.

Three tests, one per failure, plus idempotency.

Run: python3 -m pytest tests/test_build_evidence.py -q
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import build_evidence as ev  # noqa: E402


def test_every_number_on_the_page_comes_from_an_artifact():
    """A figure present on the page but absent from every source artifact was
    typed, not read."""
    page = ev.build()
    sources = " ".join(
        path.read_text()
        for path in [*sorted((ROOT / "memory" / "backtests").glob("*.json")),
                     ROOT / "assets" / "data" / "quant_signal_review.json",
                     ROOT / "assets" / "data" / "cross_sectional_factor.json"]
        if path.exists())

    typed = []
    for raw in re.findall(r"\d+\.\d+", page):
        # The page rounds what it reads, so match on the leading digits rather
        # than demanding the full-precision string.
        stem = raw.rstrip("0").rstrip(".")
        if stem and stem not in sources and stem.lstrip("0") not in sources:
            digits = stem.replace(".", "")
            if digits[:3] not in sources.replace(".", ""):
                typed.append(raw)

    assert not typed, f"figures that no artifact contains: {sorted(set(typed))}"


def test_an_inconclusive_result_never_renders_as_a_pass(tmp_path, monkeypatch):
    """Absent evidence is not failure, and it is certainly not success."""
    monkeypatch.setattr(ev, "DATA", tmp_path)
    (tmp_path / "quant_signal_review.json").write_text(json.dumps({
        "unlock_rule": "cluster_ci_entirely_above_or_below_50pct",
        "days_logged": 3,
        "factors": {"thin": {"hit_rate": 1.0, "ci95": None, "n_events": 2,
                             "n_dates": 2, "n_tickers": 1,
                             "edge_significant": False}},
    }))

    section = ev.factor_section()

    assert section["verdict"] == ev.VERDICT["undecided"]
    assert "锁定" in section["rows"][0][1]
    assert section["verdict"] != ev.VERDICT["passed"]


def test_a_failed_verdict_is_stated_as_a_failure_to_reject(tmp_path, monkeypatch):
    """The dial's p-value must not be softened into 'inconclusive' prose, nor
    overstated into 'disproved'."""
    monkeypatch.setattr(ev, "CARDS", tmp_path)
    (tmp_path / "regime_dial_validation-20260802-aaaaaaaa.json").write_text(json.dumps({
        "run_id": "regime_dial_validation-20260802-aaaaaaaa",
        "inputs": [{"bars": 1000, "first_session": "2021-01-04",
                    "last_session": "2026-07-31"}],
        "metrics": {
            "in_sample": {"dial_max_drawdown": -0.916, "hold_max_drawdown": -0.955,
                          "drawdown_improvement": 0.039},
            "permutation": {"p_value_drawdown": 0.9245, "p_value_return": 0.97,
                            "null_drawdown_improvement_median": 0.102},
            "walk_forward": {"folds_with_shallower_drawdown": 2, "n_folds": 4,
                             "threshold_stability": "unstable"},
            "sensitivity": {"production_rank": 13, "grid": [{}] * 16},
            "tier_distribution": {"pct": {"green": 30.5, "amber": 59.5, "red": 10.0}},
        },
    }))

    section = ev.dial_section()

    assert section["verdict"] == ev.VERDICT["failed"]
    assert "未能拒绝原假设，不是证伪" in section["reading"]


def test_regenerating_the_page_is_idempotent():
    assert ev.build() == ev.build()
