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
