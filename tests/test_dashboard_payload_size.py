"""dashboard.json is a first-paint payload, not an archive.

Every visitor downloads it before anything renders, so a block nobody reads is a
tax on every page load. Two regressions had crept in: the leverage dial shipped
twice in one document, and 27KB of calibrator posterior state shipped with no
consumer at all.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "assets" / "data" / "dashboard.json"
SIZE_CAP = 200_000            # the same cap scripts/system_check.py enforces
RENDERERS = ("dashboard.render.js", "dashboard.charts.js")


@pytest.fixture(scope="module")
def payload():
    return json.loads(DASHBOARD.read_text())


def _size(obj):
    return len(json.dumps(obj, ensure_ascii=False))


def test_payload_stays_under_the_published_cap():
    size = len(DASHBOARD.read_text())
    assert size < SIZE_CAP, f"{size:,} bytes; trim or move detail to a sidecar"


def test_no_sub_object_is_embedded_twice(payload):
    """The dial was embedded at top level and again inside risk_guardrail."""
    import hashlib

    seen = {}
    duplicates = []
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        for sub_key, sub_value in value.items():
            if _size(sub_value) < 2000:
                continue
            digest = hashlib.md5(
                json.dumps(sub_value, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            if digest in seen:
                duplicates.append(f"{seen[digest]} == {key}.{sub_key}")
            seen[digest] = f"{key}.{sub_key}"
        digest = hashlib.md5(
            json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if digest in seen and _size(value) >= 2000:
            duplicates.append(f"{seen[digest]} == {key}")
        seen.setdefault(digest, key)
    assert duplicates == [], duplicates


def test_the_unread_history_and_calibrator_blocks_stay_out(payload):
    assert "regime_history" not in payload["lev_regime"]
    assert payload["lev_regime"]["regime_history_source"].endswith("lev_regime.json")
    assert "lev_regime" not in payload["risk_guardrail"]
    assert payload["risk_guardrail"]["lev_regime_tier"]      # the derived bit survives

    calibration = payload["decision_metrics"]["hierarchical_calibration"]
    assert "current_group_calibrators" not in calibration
    assert isinstance(calibration["current_group_calibrator_count"], int)
    # the headline fields the card renders are untouched
    for field in ("method", "hierarchy", "abstain_rule", "sizing_rule", "all_predictions"):
        assert field in calibration


def test_dropped_blocks_are_still_reachable_elsewhere():
    """Trimming the payload must not lose the data — only relocate it."""
    standalone = json.loads((ROOT / "assets" / "data" / "lev_regime.json").read_text())
    assert standalone["regime_history"]["hk"]


def test_what_the_charts_actually_read_is_still_present(payload):
    """Guards against over-trimming: a name-based scan once called
    `episode_backtest.horizons` unread because it lives in dashboard.charts.js,
    not the renderer."""
    js = "".join((ROOT / "assets" / "js" / name).read_text() for name in RENDERERS)
    assert 'safe(DATA, "episode_backtest", "horizons", "t1")' in js
    assert payload["episode_backtest"]["horizons"]["t1"]
    assert payload["snapshots"]
    # the dial card reads these off the trimmed copy
    assert 'safe(DATA, "lev_regime")' in js
    for field in ("hk", "us", "as_of", "label", "ma_window"):
        assert field in payload["lev_regime"], field
    assert payload["lev_regime"]["us"]["names"]


def test_rebuild_is_idempotent_and_keeps_the_trim():
    subprocess.run([sys.executable, "scripts/data/build_dashboard.py"],
                   cwd=ROOT, check=True, capture_output=True)
    rebuilt = json.loads(DASHBOARD.read_text())
    assert "regime_history" not in rebuilt["lev_regime"]
    assert "current_group_calibrators" not in rebuilt["decision_metrics"]["hierarchical_calibration"]
    assert len(DASHBOARD.read_text()) < SIZE_CAP


def test_the_brief_still_gets_the_calibrators_the_dashboard_no_longer_ships():
    """Cross-PR interaction guard.

    The daily-brief skill requires an active call to match its group in
    `decision_metrics.hierarchical_calibration.current_group_calibrators` before
    any size multiplier applies (#62). The public payload stopped shipping that
    table (#102) because no chart reads it — which is only safe because the brief
    computes its metrics in-process rather than reading dashboard.json.

    Break either half and sizing silently loses its evidence base.
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    import decision_v2

    metrics = decision_v2.compute_metrics(decision_v2.load_decisions())
    calibration = metrics.get("hierarchical_calibration") or {}
    assert isinstance(calibration.get("current_group_calibrators"), list)

    preflight = (ROOT / "scripts" / "harness" / "brief_preflight.py").read_text()
    computed = preflight.split("def compute_decision_metrics", 1)[1][:1500]
    assert "decision_v2.compute_metrics" in computed
    assert "dashboard.json" not in computed, "the brief must not source metrics from the trimmed payload"

    skill = (ROOT / "skills" / "daily-deep-brief" / "SKILL.md").read_text()
    assert "current_group_calibrators" in skill


def test_the_brief_only_ships_calibrator_rows_that_can_move_size():
    """The brief injects its context on every turn, so an all-abstain posterior
    table costs far more there than in the once-published payload (#131).

    Two things must hold together: the trim has to actually drop the dead rows,
    and it must be incapable of dropping a row that would have multiplied size.
    The second is the one worth a test — decision_v2 defines
    `edge_supported = not abstain and ci[0] > 0.5` and `evidence_sufficient =
    not abstain`, so edge-supported is a strict subset. If anyone ever inverts
    that relationship, sizing loses its evidence base silently.
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    sys.path.insert(0, str(ROOT / "scripts" / "harness"))
    import decision_v2
    import brief_preflight

    raw = decision_v2.compute_metrics(decision_v2.load_decisions())
    rows = raw["hierarchical_calibration"]["current_group_calibrators"]

    trimmed = brief_preflight.trim_abstaining_calibrators(raw)
    calibration = trimmed["hierarchical_calibration"]
    kept = calibration["current_group_calibrators"]

    # every dropped row is one both skills already treat as a missing row
    assert all(r.get("evidence_sufficient") for r in kept)
    assert all(not r.get("abstain") for r in kept)

    # the invariant that makes the filter safe, asserted on real ledger rows
    for row in rows:
        if row.get("edge_supported"):
            assert row.get("evidence_sufficient"), row
            assert row in kept, "a size-moving row was dropped"

    # nothing becomes invisible
    assert calibration["current_group_calibrator_count"] == len(rows)
    assert calibration["current_group_calibrators_omitted"] == len(rows) - len(kept)
    assert sum(calibration["omitted_abstain_reasons"].values()) == len(rows) - len(kept)
    assert calibration["omitted_rule"]

    # headline fields the skills read are untouched by the trim
    for field in ("method", "hierarchy", "abstain_rule", "sizing_rule",
                  "all_predictions", "after_warmup"):
        assert field in calibration, field
