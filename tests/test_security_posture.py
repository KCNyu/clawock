"""Reporting GitHub security features that are off.

#787: two free secret-scanning switches were disabled and could not be enabled
from the API — the repo PATCH endpoint returns 200 and ignores those fields, so
they are web-UI switches. What a script can still do is refuse to let them be
forgotten, and the failure mode to guard against is the reporter that says
nothing when it cannot see.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "security_posture", ROOT / "ops" / "ci" / "security_posture.py")
posture = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(posture)


def _all_on() -> dict:
    return {field: {"status": "enabled"} for field, _, _ in posture.EXPECTED}


def test_everything_on_reports_nothing():
    assert posture.evaluate(_all_on()) == []


def test_a_disabled_feature_is_named_with_the_reason_it_matters_here():
    settings = _all_on()
    settings["secret_scanning_validity_checks"] = {"status": "disabled"}
    off = posture.evaluate(settings)
    assert [row[0] for row in off] == ["secret_scanning_validity_checks"]
    assert off[0][2] == "disabled"
    assert off[0][3], "a switch with no stated reason gets flipped off again next year"


def test_an_absent_field_counts_as_off_not_as_fine():
    """A field GitHub stops returning must not read as enabled. Silence about a
    security control is the one thing this script exists to prevent."""
    off = posture.evaluate({})
    assert len(off) == len(posture.EXPECTED)
    assert all(row[2] == "absent" for row in off)


def test_an_unreadable_posture_is_reported_rather_than_passed(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(posture, "fetch", lambda token: {})
    assert posture.main(["--warn"]) == 0
    out = capsys.readouterr().out
    assert "posture unknown, not verified" in out


def test_a_missing_token_is_loud(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert posture.main([]) == 2
    assert "not the same as it being fine" in capsys.readouterr().err


def test_warn_never_fails_the_job_but_the_default_does(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    broken = {"security_and_analysis": {"secret_scanning": {"status": "disabled"}}}
    monkeypatch.setattr(posture, "fetch", lambda token: broken)
    assert posture.main(["--warn"]) == 0
    assert posture.main([]) == 1


def test_the_weekly_check_runs_it_and_cannot_be_reddened_by_it():
    workflow = (ROOT / ".github" / "workflows" / "weekly-health.yml").read_text(encoding="utf-8")
    step = workflow.split("GitHub security features still off", 1)[1].split("- name:", 1)[0]
    assert "ops/ci/security_posture.py --warn" in step
    assert "continue-on-error: true" in step, (
        "nagging about a repository setting must not be able to red a health run"
    )
