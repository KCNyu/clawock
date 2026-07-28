"""One build, three public outputs, one semantic publication contract."""
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import dashboard_outputs  # noqa: E402


EXPECTED = {
    "assets/data/dashboard.json",
    "assets/data/decision_audit.json",
    "assets/data/shadow_portfolio.json",
}


def _git(root, *args):
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    values = {
        "assets/data/dashboard.json": {
            "generated_at": "old",
            "freshness": {"age_hours": 1, "days_behind": 0, "stale": False},
            "book": {"value": 10},
        },
        "assets/data/decision_audit.json": {
            "as_of": "old",
            "records": [{"id": "d1", "outcome": "win"}],
        },
        "assets/data/shadow_portfolio.json": {
            "as_of": "old",
            "curves": {"USD": [{"date": "2026-07-17", "value": 10}]},
        },
    }
    for path, value in values.items():
        _write(tmp_path, path, value)
    _git(tmp_path, "add", "--", *dashboard_outputs.DASHBOARD_OUTPUTS)
    _git(tmp_path, "commit", "-qm", "seed")
    return values


def test_clock_only_rebuild_is_restored_instead_of_published(tmp_path):
    original = _repo(tmp_path)
    rebuilt = {
        "assets/data/dashboard.json": {
            "generated_at": "new",
            "freshness": {"age_hours": 9, "days_behind": 3, "stale": False},
            "book": {"value": 10},
        },
        "assets/data/decision_audit.json": {
            "as_of": "new",
            "records": [{"id": "d1", "outcome": "win"}],
        },
        "assets/data/shadow_portfolio.json": {
            "as_of": "new",
            "curves": {"USD": [{"date": "2026-07-17", "value": 10}]},
        },
    }
    for path, value in rebuilt.items():
        _write(tmp_path, path, value)

    assert dashboard_outputs.semantic_changed_paths(tmp_path) == []
    for path, value in original.items():
        assert json.loads((tmp_path / path).read_text()) == value


def test_real_sidecar_change_is_returned_with_exact_path(tmp_path):
    original = _repo(tmp_path)
    _write(tmp_path, "assets/data/dashboard.json", {
        **original["assets/data/dashboard.json"],
        "generated_at": "new",
    })
    _write(tmp_path, "assets/data/decision_audit.json", {
        **original["assets/data/decision_audit.json"],
        "as_of": "new",
    })
    _write(tmp_path, "assets/data/shadow_portfolio.json", {
        "as_of": "new",
        "curves": {"USD": [
            {"date": "2026-07-17", "value": 10},
            {"date": "2026-07-18", "value": 12},
        ]},
    })

    assert dashboard_outputs.semantic_changed_paths(tmp_path) == [
        "assets/data/shadow_portfolio.json"
    ]
    assert json.loads(
        (tmp_path / "assets/data/decision_audit.json").read_text()
    ) == original["assets/data/decision_audit.json"]


def test_reflect_backtest_change_publishes_the_existing_audit_sidecar(tmp_path):
    original = _repo(tmp_path)
    _write(tmp_path, "assets/data/decision_audit.json", {
        **original["assets/data/decision_audit.json"],
        "as_of": "new",
        "episode_backtest": {"horizons": {"t1": {"settled": 3}}},
    })

    assert dashboard_outputs.semantic_changed_paths(tmp_path) == [
        "assets/data/decision_audit.json"
    ]


def test_every_dashboard_committer_uses_the_shared_contract():
    assert set(dashboard_outputs.DASHBOARD_OUTPUTS) == EXPECTED

    for path in (
        "scripts/harness/brief_postflight.py",
        "scripts/harness/report_postflight.py",
        "scripts/harness/intraday_postflight.py",
    ):
        assert "dashboard_output_changes()" in (ROOT / path).read_text()

    for path in (
        ".githooks/pre-commit",
        "scripts/data/gold_dca_refresh.sh",
        "scripts/data/publish_dashboard.sh",
    ):
        assert "scripts/data/dashboard_outputs.py" in (ROOT / path).read_text()

    assert "semantic_changed_paths(WS_ROOT)" in (
        ROOT / "scripts/data/update_gold_dca.py"
    ).read_text()
