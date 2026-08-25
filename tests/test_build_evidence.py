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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from clawock.evidence import build_evidence as ev


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
        # Multi-cluster on purpose: a straddling CI is a different verdict from
        # an uninterpretable single-cluster sample, and this test owns the first.
        "factors": {"thin": {"hit_rate": 0.55, "ci95": [0.38, 0.71],
                             "n_events": 40, "n_dates": 12, "n_tickers": 5,
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


def test_add_campaign_is_separate_and_zero_samples_stay_collecting(
        tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "CARDS", tmp_path)
    (tmp_path / "add_alpha_walkforward-20260812-fixture.json").write_text(
        json.dumps({
            "run_id": "add_alpha_walkforward-20260812-fixture",
            "metrics": {
                "us": {"interaction": {
                    "t1": {"n": 4, "mean_return": .031, "hit_rate": 1,
                           "status": "collecting"},
                    "t5": {"n": 0, "status": "collecting"},
                    "t20": {"n": 0, "status": "collecting"},
                }},
                "hk": {"interaction": {
                    horizon: {"n": 0, "status": "collecting"}
                    for horizon in ("t1", "t5", "t20")
                }},
                "coverage": {"factor_dates": 11, "information_dates": 12,
                             "overlap_dates": 10,
                             "prospective_information_dates": 0,
                             "authority_classifications": {
                                 "none": 186, "exploration": 6, "validated": 0,
                             }},
            },
        })
    )

    section = ev.add_alpha_section()

    assert section["verdict"] == ev.VERDICT["undecided"]
    assert "不是 validated alpha" in section["reading"]
    assert "mixed/legacy" in section["reading"]
    assert any("collecting · n=0" in value for _, value in section["rows"])
    assert not any("0.0%" in value for _, value in section["rows"] if "n=0" in value)


def test_not_yet_elapsed_is_neither_a_pass_nor_a_failure(tmp_path, monkeypatch):
    """A prospective criterion at zero while its forward window has not elapsed
    is waiting, not failing. Rendering the two the same is the exact conflation
    this page exists to avoid."""
    monkeypatch.setattr(ev, "DATA", tmp_path)
    monkeypatch.setattr(ev, "WS", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "factor-universe.json").write_text(json.dumps({
        "forward_horizon_sessions": 21,
        "activation_criteria": {"min_prospective_dates": 24},
    }))
    (tmp_path / "cross_sectional_factor.json").write_text(json.dumps({
        "registered_at": "2026-07-26",
        "activation": {"usable_for_decisions": False, "checks": {
            "prospective_dates": {"actual": 0, "required": 24, "pass": False}}},
    }))

    section = ev.cross_sectional_section()

    assert section["verdict"] == ev.VERDICT["pending"]
    assert section["verdict"] not in (ev.VERDICT["passed"], ev.VERDICT["undecided"])
    assert "还没到期" in section["reading"]
    # The wait has to be quantified, not just asserted.
    assert "2026-" in section["reading"]


def test_a_measured_shortfall_still_reads_as_not_yet_decidable(tmp_path, monkeypatch):
    """Once observations exist, a shortfall is a real measurement again — the
    pending state must not swallow it."""
    monkeypatch.setattr(ev, "DATA", tmp_path)
    monkeypatch.setattr(ev, "WS", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "factor-universe.json").write_text(json.dumps({
        "forward_horizon_sessions": 21,
        "activation_criteria": {"min_prospective_dates": 24},
    }))
    (tmp_path / "cross_sectional_factor.json").write_text(json.dumps({
        "registered_at": "2026-07-26",
        "activation": {"usable_for_decisions": False, "checks": {
            "prospective_dates": {"actual": 9, "required": 24, "pass": False}}},
    }))

    assert ev.cross_sectional_section()["verdict"] == ev.VERDICT["undecided"]


def test_a_single_cluster_sample_is_labelled_instead_of_showing_a_bare_rate(
        tmp_path, monkeypatch):
    """trend_on_follow's 3.1% is one ticker over 32 sessions. Shown bare it reads
    as a catastrophically wrong factor; it is an uninterpretable sample."""
    monkeypatch.setattr(ev, "DATA", tmp_path)
    (tmp_path / "quant_signal_review.json").write_text(json.dumps({
        "unlock_rule": "cluster_ci_entirely_above_or_below_50pct", "days_logged": 38,
        "factors": {"trend_on_follow": {"hit_rate": 0.031, "ci95": None,
                                        "n_events": 32, "n_dates": 32,
                                        "n_tickers": 1, "edge_significant": False}},
    }))

    row = ev.factor_section()["rows"][0][1]

    assert "单一簇" in row
    assert "锁定" not in row, "a single-cluster sample is not the same as a CI that straddles 50%"


def test_small_sample_ci_clearing_50pct_is_never_a_decision_grade_pass(
        tmp_path, monkeypatch):
    """#935 made the sample floor the first gate: an n<MIN_N factor whose
    clustered CI clears 50% is noise, whatever edge_significant claims. The
    evidence page must not render it as unlocked (#982)."""
    monkeypatch.setattr(ev, "DATA", tmp_path)
    (tmp_path / "quant_signal_review.json").write_text(json.dumps({
        "unlock_rule": "cluster_ci_entirely_above_or_below_50pct",
        "days_logged": 12,
        "factors": {"tiny": {"hit_rate": 0.75, "ci95": [0.60, 0.90],
                             "n_events": 4, "n_dates": 2, "n_tickers": 2,
                             "edge_significant": True,
                             "sample_sufficient": False, "min_n": 20,
                             "usable": False}},
    }))

    section = ev.factor_section()

    assert section["verdict"] == ev.VERDICT["undecided"]
    assert section["verdict"] != ev.VERDICT["passed"]
    row = section["rows"][0][1]
    assert "可入决策" not in row
    assert "样本不足" in row


def test_unlock_count_and_verdict_follow_the_usable_gate(tmp_path, monkeypatch):
    """unlocked/passed are keyed on #935's usable gate (#982): edge_significant
    alone ignores the sample floor and would count a 4-event factor."""
    monkeypatch.setattr(ev, "DATA", tmp_path)
    (tmp_path / "quant_signal_review.json").write_text(json.dumps({
        "unlock_rule": "cluster_ci_entirely_above_or_below_50pct",
        "days_logged": 40,
        "factors": {
            "real_edge": {"hit_rate": 0.62, "ci95": [0.55, 0.70],
                          "n_events": 120, "n_dates": 30, "n_tickers": 8,
                          "edge_significant": True,
                          "sample_sufficient": True, "usable": True},
            "tiny": {"hit_rate": 0.75, "ci95": [0.60, 0.90],
                     "n_events": 4, "n_dates": 2, "n_tickers": 2,
                     "edge_significant": True,
                     "sample_sufficient": False, "usable": False},
        },
    }))

    section = ev.factor_section()

    assert section["verdict"] == ev.VERDICT["passed"]
    assert section["reading"].startswith(
        "解锁规则是 `cluster_ci_entirely_above_or_below_50pct`")
    assert any("✅ 可入决策" in text for _, text in section["rows"])
    assert any("样本不足" in text for _, text in section["rows"])


def test_reverse_only_factor_reads_as_reverse_not_straddling(
        tmp_path, monkeypatch):
    """A reverse-significant CI is a different verdict from a straddling one;
    conflating them hides the only reading the data actually supports (#982)."""
    monkeypatch.setattr(ev, "DATA", tmp_path)
    (tmp_path / "quant_signal_review.json").write_text(json.dumps({
        "unlock_rule": "cluster_ci_entirely_above_or_below_50pct",
        "days_logged": 40,
        "factors": {"inverted": {"hit_rate": 0.30, "ci95": [0.15, 0.42],
                                 "n_events": 80, "n_dates": 25,
                                 "n_tickers": 6, "edge_significant": False,
                                 "reverse_edge_significant": True,
                                 "sample_sufficient": True, "usable": False}},
    }))

    row = ev.factor_section()["rows"][0][1]

    assert "反向" in row
    assert "锁定" not in row
