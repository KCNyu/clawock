"""Guards for the pre-push secret scan in scripts/system_check.py.

The scan runs in two tiers on purpose:

* LOOSE  — key-ish shapes (`sk-`, `tp-`, …) that can collide with ordinary slugs.
  On 2026-07-15 the string "risk-on-with-trend-conflict" in a plan.json matched
  `sk-` + 21 legal chars and blocked every push, so this tier skips `*.md`.
* STRICT — structurally unambiguous credential markers (PEM headers, vendor keys
  with fixed prefix + fixed length). These cannot occur in prose, so they must
  also scan `*.md` — that is where the memory-promotion cron writes, and it is a
  live path from a credential pasted into a session into the public repo.

Credential literals below are assembled from fragments so this test file does not
itself contain a matching string (the scan would flag its own fixtures).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = str(ROOT / "scripts")


@pytest.fixture(scope="module")
def sc():
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    return pytest.importorskip("system_check")


def _pem() -> str:
    return "-----BEGIN" + " PRIVATE KEY" + "-----"


def _sa_json() -> str:
    return '{"type"' + ': ' + '"service_account", "project_id": "x"}'


def _google_key() -> str:
    return "AIza" + "b" * 35


def _telegram() -> str:
    return "8832401234" + ":AA" + "c" * 33


def _github_pat() -> str:
    return "gh" + "p_" + "d" * 36


def _aws() -> str:
    return "AKIA" + "E" * 16


def _slack() -> str:
    return "xox" + "b-" + "1234567890-abcdef"


STRICT_POSITIVES = [
    pytest.param(_pem, id="pem-private-key"),
    pytest.param(_sa_json, id="gcp-service-account-json"),
    pytest.param(_google_key, id="google-api-key"),
    pytest.param(_telegram, id="telegram-bot-token"),
    pytest.param(_github_pat, id="github-pat"),
    pytest.param(_aws, id="aws-access-key-id"),
    pytest.param(_slack, id="slack-token"),
]


@pytest.mark.parametrize("make", STRICT_POSITIVES)
def test_strict_patterns_catch_real_credential_shapes(sc, make):
    assert re.search(sc.SECRET_PATTERNS_STRICT, make()), (
        "strict tier must flag this credential shape"
    )


@pytest.mark.parametrize(
    "prose",
    [
        "the plan is risk-on-with-trend-conflict for hstech",
        "we rotated the service account yesterday",  # words, not JSON shape
        "BEGIN PRIVATE KEY is discussed in the runbook",  # no PEM dashes
        "港股开盘报告掉链到 codex 之后 bash 炸了",
        "AIzaSy is a prefix people mention in blog posts",  # too short
    ],
)
def test_strict_patterns_do_not_fire_on_prose(sc, prose):
    assert not re.search(sc.SECRET_PATTERNS_STRICT, prose), (
        "strict tier must not fire on ordinary prose — it scans *.md"
    )


def test_loose_tier_still_catches_prefixed_api_keys(sc):
    assert re.search(sc.SECRET_PATTERNS_LOOSE, "key = " + "sk-" + "a" * 24)
    assert re.search(sc.SECRET_PATTERNS_LOOSE, "key = " + "tp-" + "b" * 24)


def test_loose_tier_keeps_the_2026_07_15_false_positive_fix(sc):
    """A hyphenated slug must not read as an sk- key (it blocked every push once)."""
    assert not re.search(
        sc.SECRET_PATTERNS_LOOSE, "driven_by: risk-on-with-trend-conflict"
    )


def test_strict_tier_scans_markdown_but_loose_tier_does_not(sc, monkeypatch):
    """The tier split is the whole point: regressing it silently un-covers memory/*.md."""
    calls = []

    def fake_grep(pattern, extra_excludes=()):
        calls.append((pattern, tuple(extra_excludes)))
        return [], None

    monkeypatch.setattr(sc, "_grep_tracked", fake_grep)

    class _Rec:
        def add(self, *a, **k):
            pass

    sc.check_no_leaked_secrets(_Rec())

    assert len(calls) == 2, "expected one loose scan and one strict scan"
    by_pattern = dict(calls)
    assert ":!*.md" in by_pattern[sc.SECRET_PATTERNS_LOOSE], (
        "loose tier must keep skipping *.md (2026-07-15 false-positive fix)"
    )
    assert ":!*.md" not in by_pattern[sc.SECRET_PATTERNS_STRICT], (
        "strict tier must scan *.md — memory/*.md is the public-repo leak path"
    )


def test_scan_reports_critical_when_it_cannot_run(sc, monkeypatch):
    """Fail closed. A scanner that swallows its own errors certifies nothing.

    The old implementation caught every exception and returned "no matches", so a
    pattern git refused to compile — or git being absent — read as a clean tree.
    """
    monkeypatch.setattr(sc, "_grep_tracked",
                        lambda *a, **k: ([], "git grep rc=129: unknown option"))
    seen = []

    class _Rec:
        def add(self, name, level, msg):
            seen.append((level, msg))

    sc.check_no_leaked_secrets(_Rec())
    assert seen and seen[0][0] == sc.CRITICAL, "a broken scan must not report OK"
    assert "cannot certify" in seen[0][1]


def test_grep_passes_pattern_after_dash_e(sc):
    """The PEM pattern starts with '-'; without -e git reads it as a flag."""
    recorded = {}

    class _P:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kw):
        recorded["cmd"] = cmd
        return _P()

    monkeypatch_run = pytest.MonkeyPatch()
    monkeypatch_run.setattr(sc.subprocess, "run", fake_run)
    try:
        sc._grep_tracked(sc.SECRET_PATTERNS_STRICT)
    finally:
        monkeypatch_run.undo()

    cmd = recorded["cmd"]
    assert "-e" in cmd, "pattern must be introduced with -e"
    assert cmd[cmd.index("-e") + 1] == sc.SECRET_PATTERNS_STRICT


def test_real_scan_runs_against_this_repo(sc):
    """End-to-end: the scan must actually execute, not silently no-op."""
    _, failure = sc._grep_tracked(sc.SECRET_PATTERNS_STRICT)
    assert failure is None, f"strict scan failed to run: {failure}"
    _, failure = sc._grep_tracked(sc.SECRET_PATTERNS_LOOSE,
                                  extra_excludes=(":!*.md",))
    assert failure is None, f"loose scan failed to run: {failure}"


def test_config_and_self_are_always_excluded(sc):
    """openclaw.json holds live keys; this scanner holds the patterns themselves."""
    excludes = set(sc._SCAN_EXCLUDES)
    assert ":!openclaw.json*" in excludes
    assert ":!scripts/system_check.py" in excludes
