"""One build, four public outputs, one semantic publication contract."""
import json
import pytest
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import dashboard_outputs  # noqa: E402


EXPECTED = {
    "assets/data/overview.json",
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
        "assets/data/overview.json": {
            "schema_version": 1,
            "generation_id": "old",
            "generated_at": "old",
            "book": {"value": 10},
        },
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
        "assets/data/overview.json": {
            "schema_version": 1,
            "generation_id": "new",
            "generated_at": "new",
            "book": {"value": 10},
        },
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


def test_payload_change_outside_the_projection_republishes_the_projection(tmp_path):
    """The failure that reddened master on 2026-08-03.

    ``workflow_outcomes`` moved, the overview projection did not carry it, so the
    projection looked clock-only and was restored to HEAD — leaving its
    ``generation_id`` one build behind the payload committed beside it.
    """
    original = _repo(tmp_path)
    _write(tmp_path, "assets/data/overview.json", {
        **original["assets/data/overview.json"],
        "generation_id": "new",
        "generated_at": "new",
    })
    _write(tmp_path, "assets/data/dashboard.json", {
        **original["assets/data/dashboard.json"],
        "generated_at": "new",
        "workflow_outcomes": {"failures": 1},
    })

    assert dashboard_outputs.semantic_changed_paths(tmp_path) == [
        "assets/data/overview.json",
        "assets/data/dashboard.json",
    ]
    overview = json.loads((tmp_path / "assets/data/overview.json").read_text())
    dashboard = json.loads((tmp_path / "assets/data/dashboard.json").read_text())
    assert overview["generation_id"] == dashboard["generated_at"]


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


def test_a_failed_write_set_publishes_nothing(tmp_path):
    """#262 slice 3 step 3: the four outputs are one generation, so a failure
    part-way must leave the old generation intact rather than mix them.

    `safe_write_text` is atomic per file, which is why this is not already true:
    four successful-then-failing calls each land atomically, and the reader gets
    two new files beside two old ones.
    """
    for name in ("overview.json", "dashboard.json"):
        (tmp_path / name).write_text("OLD", encoding="utf-8")
    # A directory where a file must go: the staged write fails, and it fails
    # after the first two payloads have already been staged.
    (tmp_path / "decision_audit.json").mkdir()

    with pytest.raises(OSError):
        dashboard_outputs.write_generation({
            str(tmp_path / "overview.json"): "NEW",
            str(tmp_path / "dashboard.json"): "NEW",
            str(tmp_path / "decision_audit.json"): "NEW",
        })

    assert (tmp_path / "overview.json").read_text(encoding="utf-8") == "OLD"
    assert (tmp_path / "dashboard.json").read_text(encoding="utf-8") == "OLD"
    assert not list(tmp_path.glob(".staged-*")), "staged temporaries must be cleaned up"


def test_a_complete_write_set_swaps_every_file(tmp_path):
    written = dashboard_outputs.write_generation({
        str(tmp_path / "overview.json"): "A",
        str(tmp_path / "nested" / "shadow_portfolio.json"): "B",
    })

    assert [Path(p).name for p in written] == ["overview.json", "shadow_portfolio.json"]
    assert (tmp_path / "overview.json").read_text(encoding="utf-8") == "A"
    assert (tmp_path / "nested" / "shadow_portfolio.json").read_text(encoding="utf-8") == "B"
    assert not list(tmp_path.glob(".staged-*"))


def _generation(directory, *, clock, value):
    """One generation of the four outputs, each stamped with its own clock field.

    overview/dashboard carry `generated_at`; the two sidecars carry `as_of`.
    Using one field for all four would make the sidecars look semantically
    changed and quietly stop the test from exercising the clock-only path.
    """
    directory.mkdir(parents=True, exist_ok=True)
    # `generation_id` is stripped for overview.json only — dashboard.json does
    # not carry it in the clock-field set, so putting it there would read as a
    # semantic change.
    (directory / "overview.json").write_text(
        json.dumps({"generated_at": clock, "generation_id": clock, "totals": value}),
        encoding="utf-8")
    (directory / "dashboard.json").write_text(
        json.dumps({"generated_at": clock, "totals": value}), encoding="utf-8")
    for name in ("decision_audit.json", "shadow_portfolio.json"):
        (directory / name).write_text(
            json.dumps({"as_of": clock, "totals": value}), encoding="utf-8")


def test_the_diff_baseline_can_be_a_directory_instead_of_this_repository(tmp_path):
    """#262: the outputs are on their way out of repository history, so "what did
    we publish last time" stops being a git question. This helper was the one
    place that assumed otherwise."""
    published = tmp_path / "published"
    # Laid out the way `FilesystemStore` and the data branch hold a
    # generation: by workspace-relative path, not flattened to basename.
    _generation(published / "assets" / "data", clock="2026-08-05T00:00:00Z", value=1)
    worktree = tmp_path / "worktree" / "assets" / "data"
    _generation(worktree, clock="2026-08-05T03:00:00Z", value=1)
    # Exactly one output genuinely changed. Asserting the precise subset is what
    # makes this test mean anything: `tmp_path` is not a git repository, so the
    # default GitBaseline cannot read any previous version and conservatively
    # reports ALL FOUR as changed. A test that expected "everything" would pass
    # with the baseline argument ignored entirely.
    (worktree / "dashboard.json").write_text(
        json.dumps({"generated_at": "2026-08-05T03:00:00Z", "totals": 2}),
        encoding="utf-8")

    changed = dashboard_outputs.semantic_changed_paths(
        tmp_path / "worktree", restore_clock_only=False,
        baseline=dashboard_outputs.DirectoryBaseline(published))

    assert changed == ["assets/data/overview.json", "assets/data/dashboard.json"], (
        "only the changed payload and its generation-linked projection publish, "
        "decided with no git involved")


def test_a_clock_only_rebuild_is_restored_from_whatever_the_baseline_is(tmp_path):
    """The restore is what keeps a publisher from shipping a file whose only
    change is when it was built. A directory baseline has to give the same
    guarantee `git restore` does, or moving the data plane reintroduces the
    no-op publish this contract exists to stop."""
    published = tmp_path / "published"
    # Laid out the way `FilesystemStore` and the data branch hold a
    # generation: by workspace-relative path, not flattened to basename.
    _generation(published / "assets" / "data", clock="2026-08-05T00:00:00Z", value=1)
    root = tmp_path / "worktree"
    _generation(root / "assets" / "data", clock="2026-08-05T03:00:00Z", value=1)

    changed = dashboard_outputs.semantic_changed_paths(
        root, baseline=dashboard_outputs.DirectoryBaseline(published))

    assert changed == []
    restored = json.loads(
        (root / "assets" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    assert restored["generated_at"] == "2026-08-05T00:00:00Z", (
        "the clock-only rebuild must be rolled back, not left dirty")
