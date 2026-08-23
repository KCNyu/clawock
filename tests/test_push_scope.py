"""Behavioural contract for ops/ci/push_scope.py — unit lanes plus the
change-scenario matrix (#884 adversarial pass).

The matrix encodes how CI must react to every recurring kind of change this
repository actually receives: interactive PRs, the automation commits that
land on master all day (coverage badge, scheduled scans, EOD archive, weekly
review, screenshot refresh), the harness's daily brief commit, plugin edits,
and pure noise. Each row pins BOTH halves of the decision:

  lanes        what ops/ci/push_scope.py answers for that path set;
  ci_triggers  whether the `push:` path filter in ci.yml starts a run at all,
               recomputed from the YAML so the two halves cannot drift apart
               silently.
"""
from __future__ import annotations

import json
import sys
from fnmatch import fnmatch
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "ci"))
import push_scope  # noqa: E402


def _ci_trigger_globs() -> list[str]:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    block = text.split("    paths:", 1)[1].split("\n  pull_request:", 1)[0]
    return [line.strip().strip("-").strip().strip("'")
            for line in block.splitlines()
            if line.strip().startswith("- '")]


def _ci_triggers(files: list[str]) -> bool:
    globs = _ci_trigger_globs()
    return any(
        fnmatch(f, g.replace("**", "*")) for f in files for g in globs
    )


def _all_false():
    return {"code": False, "ui": False, "dsplugin": False,
            "workflows": False, "analysable": False}


def _lanes(**overrides):
    lanes = _all_false()
    lanes.update(overrides)
    return lanes


SCENARIOS = [
    pytest.param(
        ["docs/operations/release.md", "README.md"],
        # analysable is moot here: the trigger gate means ci.yml never starts,
        # and the classifier only answers for ranges it is handed. It stays
        # True because README/docs are outside the automation-data set —
        # faithful to the ignore-list semantics this replaced.
        _lanes(analysable=True), False,
        id="docs-only PR or push: six contexts report, nothing heavy runs"),
    pytest.param(
        ["portfolio.json"],
        _lanes(code=True, analysable=False), True,
        id="automation price commit: full suite gates the money file, CodeQL skips"),
    pytest.param(
        [f"memory/2026-08-24-pre-open.md", "memory/2026-08-24-plan.json"],
        _lanes(code=True, analysable=False), True,
        id="daily brief commit (pre-open + plan): suite runs, CodeQL skips"),
    pytest.param(
        ["assets/data/sentiment.json", "assets/data/macro.json",
         "assets/data/us_news_digest.json", "assets/data/coverage.json",
         "assets/data/readme_metrics.json"],
        _lanes(), False,
        id="scheduled-scan payloads: zero CI (no loop from CI's own coverage commit)"),
    pytest.param(
        ["memory/archive/2026-W33.csv", "memory/weekly/2026-W34.md",
         "memory/decisions.jsonl"],
        _lanes(), False,
        id="eod-archive / weekly-review / ledger commits: zero CI"),
    pytest.param(
        ["site/assets/shadow-backtest.png", "site/assets/social-card.png",
         "site/assets/dsh-decision-mind.png"],
        # analysable moot: the push-path filter never starts a run for PNGs.
        _lanes(analysable=True), False,
        id="screenshot-refresh Sunday commit (PNGs are not css/js): zero CI"),
    pytest.param(
        ["examples/dsh/packages/clawock-dsh/src/store.ts"],
        _lanes(dsplugin=True, analysable=True), True,
        id="plugin-only master push: contracts run (the pre-#884 hole)"),
    pytest.param(
        ["site/assets/css/main.css"],
        _lanes(code=True, ui=True, analysable=True), True,
        id="stylesheet change: browser contract + suite"),
    pytest.param(
        [".github/workflows/pages.yml"],
        _lanes(code=True, workflows=True, analysable=True), True,
        id="workflow edit: lint + suite + analysis"),
    pytest.param(
        [".github/actions/clawock-playwright/action.yml"],
        _lanes(code=True, analysable=True), True,
        id="composite action edit: suite re-runs on master too"),
    pytest.param(
        ["src/clawock/portfolio/fx.py", "assets/data/sentiment.json"],
        _lanes(code=True, analysable=True), True,
        id="mixed code+data: suite runs, analysis runs"),
    pytest.param(
        ["monitor_state.json", "logs/x.log"],
        _lanes(), False,
        id="runtime state/logs: zero CI"),
    pytest.param(
        [], _all_false(), False,
        id="empty diff: every lane false"),
]


@pytest.mark.parametrize("files,expected_lanes,expected_trigger", SCENARIOS)
def test_change_scenarios(files, expected_lanes, expected_trigger):
    assert push_scope.classify(list(files)) == expected_lanes
    assert _ci_triggers(list(files)) == expected_trigger, (
        "the classifier and the ci.yml push-path list disagree about this "
        "scenario — fix whichever half is wrong")


def test_everything_flag_reports_all_lanes():
    assert all(push_scope.EVERYTHING.values())


def test_main_prints_github_output_pairs(capsys):
    assert push_scope.main(["--everything"]) == 0
    out = capsys.readouterr().out
    pairs = dict(line.split("=") for line in out.strip().splitlines())
    assert pairs == {k: "true" for k in _all_false()}


def test_main_json_mode(monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("src/x.py\nREADME.md\n"))
    assert push_scope.main(["--files-from", "-", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] is True
    assert payload["ui"] is False
    assert payload["analysable"] is True
