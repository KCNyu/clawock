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
import subprocess
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
    return {"book": False, "code": False, "ui": False, "dsplugin": False,
            "workflows": False, "analysable": False}


def _lanes(**overrides):
    lanes = _all_false()
    lanes.update(overrides)
    return lanes


SCENARIOS = [
    pytest.param(
        [".github/ISSUE_TEMPLATE/config.yml"],
        _lanes(code=True, analysable=True), True,
        id="issue chooser alone: public-entry contracts run on PR and push"),
    pytest.param(
        [".github/ISSUE_TEMPLATE/new_template.yml"],
        _lanes(code=True, analysable=True), True,
        id="future issue template: directory gate includes later additions"),
    pytest.param(
        ["docs/operations/release.md", "README.md"],
        _lanes(code=True, analysable=True), True,
        id="docs-only PR or push: contract tests run"),
    pytest.param(
        ["portfolio.json"],
        _lanes(book=True), True,
        id="automation price commit: book lane gates the money file, CodeQL skips"),
    pytest.param(
        ["portfolio.json", "memory/snapshots/2026-10-28.json",
         "logs/dashboard_build_status.json"],
        _lanes(book=True), True,
        id="intraday refresh (the ~24-a-day master push): book lane, not the suite"),
    pytest.param(
        ["memory/2026-08-24-pre-open.md", "memory/2026-08-24-plan.json"],
        _lanes(book=True), True,
        id="daily brief commit (pre-open + plan): book lane, CodeQL skips"),
    pytest.param(
        ["assets/data/sentiment.json", "assets/data/macro.json",
         "assets/data/us_news_digest.json", "assets/data/coverage.json",
         "assets/data/readme_metrics.json"],
        _lanes(), False,
        id="scheduled-scan payloads: zero CI (no loop from CI's own coverage commit)"),
    pytest.param(
        ["memory/archive/2026-W33.csv", "memory/weekly/2026-W34.md"],
        _lanes(), False,
        id="eod-archive / weekly-review commits: zero CI"),
    pytest.param(
        ["memory/decisions.jsonl"],
        _lanes(book=True), True,
        id="ledger-only commit: ledger audit runs in the book lane (#1063)"),
    pytest.param(
        ["portfolio.json", "src/clawock/portfolio/fx.py"],
        _lanes(code=True, analysable=True), True,
        id="book plus code: the whole suite, never the book subset"),
    pytest.param(
        ["portfolio.json", "site/assets/css/main.css"],
        _lanes(code=True, ui=True, analysable=True), True,
        id="book plus UI: browser contract and the whole suite"),
    pytest.param(
        ["memory/peer-map.json"],
        _lanes(code=True, analysable=False), True,
        id="hand-maintained peer registry alone runs its contract test (#2527)"),
    pytest.param(
        ["site/assets/shadow-backtest.png", "site/assets/social-card.png",
         "site/assets/dsh-decision-mind.png"],
        # analysable moot: the push-path filter never starts a run for PNGs.
        _lanes(analysable=True), False,
        id="screenshot-refresh Sunday commit (PNGs are not css/js): zero CI"),
    pytest.param(
        ["examples/dsh/packages/clawock-dsh/src/store.ts"],
        _lanes(code=True, dsplugin=True, analysable=True), True,
        id="plugin-only master push: contracts and suite run (#884, #2199)"),
    pytest.param(
        ["examples/cli/minimal-run/run.sh"],
        _lanes(code=True, analysable=True), True,
        id="portable-workflow shell script: suite and analysis run"),
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
    # `book` is the one lane that narrows the work, so "everything" leaves it
    # off: the whole suite already runs every test the book subset would.
    assert push_scope.EVERYTHING == {**{k: True for k in _all_false()}, "book": False}


def test_main_prints_github_output_pairs(capsys):
    assert push_scope.main(["--everything"]) == 0
    out = capsys.readouterr().out
    pairs = dict(line.split("=") for line in out.strip().splitlines())
    assert pairs == {**{k: "true" for k in _all_false()}, "book": "false"}


def test_main_json_mode(monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("src/x.py\nREADME.md\n"))
    assert push_scope.main(["--files-from", "-", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] is True
    assert payload["ui"] is False
    assert payload["analysable"] is True


def test_node_toolchain_change_runs_the_plugin_build():
    lanes = push_scope.classify([".github/actions/clawock-node/action.yml"])
    assert lanes["dsplugin"] and lanes["code"]


def test_plugin_contract_host_inputs_select_plugin_lane():
    import re
    spec = (ROOT / 'tests/decision_studio_plugin.spec.js').read_text()
    inputs = re.findall(r'path\.join\(repo, "(ops/host/[^"]+)"\)', spec)
    assert inputs
    for path in inputs:
        assert push_scope.classify([path])['dsplugin'], path


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _shallow_push(tmp_path, checkout_at):
    """An origin with a code commit then a book-only commit, cloned at depth 1."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q")
    _git(origin, "config", "user.name", "t")
    _git(origin, "config", "user.email", "t@example.com")
    (origin / "src").mkdir()
    (origin / "src" / "a.py").write_text("x = 1\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-qm", "code")
    (origin / "portfolio.json").write_text("{}\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-qm", "price refresh")
    base, head = (subprocess.run(["git", "-C", str(origin), "rev-parse", rev],
                                 capture_output=True, text=True, check=True).stdout.strip()
                  for rev in ("HEAD~1", "HEAD"))
    _git(origin, "branch", "at-base", base)
    clone = tmp_path / "clone"
    branch = "at-base" if checkout_at == "base" else "HEAD"
    _git(tmp_path, "clone", "-q", "--depth=1", "--single-branch",
         *(["--branch", branch] if branch != "HEAD" else []),
         f"file://{origin}", str(clone))
    return clone, base, head


@pytest.mark.parametrize("checkout_at", ["head", "base"],
                         ids=["push: the base is missing", "pull request: the head is missing"])
def test_a_shallow_checkout_classifies_the_real_range_once_it_fetches_the_ends(
        tmp_path, monkeypatch, capsys, checkout_at):
    """smoke-data-fetch and portable-workflow check out at depth 1. Without the
    range ends the classifier answered "everything", so both jobs ran in full on
    every runtime price push (run 40641898925, the first book-lane push)."""
    clone, base, head = _shallow_push(tmp_path, checkout_at)
    monkeypatch.chdir(clone)
    missing = head if checkout_at == "base" else base
    assert subprocess.run(["git", "cat-file", "-e", f"{missing}^{{commit}}"],
                          capture_output=True).returncode != 0, "the fixture is not shallow"

    assert push_scope.main(["--base", base, "--head", head, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == push_scope.EVERYTHING

    assert push_scope.main(["--fetch-missing", "--base", base, "--head", head, "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == _lanes(book=True)


def test_the_shallow_jobs_fetch_the_range_they_classify():
    """validate checks out full history; the two jobs that classify on a
    depth-1 checkout must ask for the ends."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for job in ("smoke-data-fetch", "portable-workflow"):
        body = text.split(f"\n  {job}:\n", 1)[1].split("\n  analyze:", 1)[0]
        body = body.split("\n  portable-workflow:\n", 1)[0]
        assert "push_scope.py --fetch-missing" in body, job
