"""Reporting GitHub security features that are off — and only nagging about the
ones somebody can actually turn on.

#787 chased two disabled secret-scanning switches and ended at a platform
boundary: on a public repository they cannot be enabled at all. The repo
endpoint refuses `advanced_security` with "always available for public repos"
while scan-history answers "Advanced Security is disabled on this repository";
both hold at once, and the switches hang off the second one. kcn confirmed the
settings page offers nothing further.

That makes the first version of this reporter wrong in a specific way: a weekly
warning nobody can act on is a false alarm with a schedule, and it trains people
to skim exactly the check that is meant to be worth reading. So the thing under
test is the *distinction* — off-and-available is a to-do, off-and-not-offered is
a fact — plus the two ways that distinction could rot into silence.
"""
from __future__ import annotations

import importlib.util
import urllib.error
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
    actionable, unavailable = posture.evaluate(_all_on(), ghas_enabled=False)
    assert actionable == [] and unavailable == []


def test_a_ghas_gated_feature_is_a_fact_not_a_todo_when_ghas_is_off():
    settings = _all_on()
    settings["secret_scanning_validity_checks"] = {"status": "disabled"}
    actionable, unavailable = posture.evaluate(settings, ghas_enabled=False)
    assert actionable == []
    assert [row[0] for row in unavailable] == ["secret_scanning_validity_checks"]


def test_the_same_feature_becomes_a_todo_again_once_ghas_is_available():
    """The repo going private with GHAS, or moving under an organization, is
    exactly when this should start nagging again."""
    settings = _all_on()
    settings["secret_scanning_validity_checks"] = {"status": "disabled"}
    actionable, unavailable = posture.evaluate(settings, ghas_enabled=True)
    assert [row[0] for row in actionable] == ["secret_scanning_validity_checks"]
    assert unavailable == []


def test_an_ungated_feature_is_always_a_todo():
    """Push protection has nothing to do with GHAS. Being generous about one
    class of feature must not leak into the rest."""
    settings = _all_on()
    settings["secret_scanning_push_protection"] = {"status": "disabled"}
    actionable, _ = posture.evaluate(settings, ghas_enabled=False)
    assert [row[0] for row in actionable] == ["secret_scanning_push_protection"]


def test_an_absent_field_counts_as_off_not_as_fine():
    actionable, unavailable = posture.evaluate({}, ghas_enabled=True)
    assert len(actionable) == len(posture.EXPECTED)
    assert all(row[2] == "absent" for row in actionable)


def test_every_gated_feature_is_one_this_script_actually_reports():
    """A typo in GHAS_GATED would silently exempt nothing, or worse, exempt a
    field that no longer exists while the real one keeps warning."""
    known = {field for field, _, _ in posture.EXPECTED}
    assert posture.GHAS_GATED <= known


class _Resp:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_the_ghas_probe_reads_disabled_only_from_githubs_own_words(monkeypatch):
    def raise_404(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", {},
            __import__("io").BytesIO(b'{"message":"Advanced Security is disabled on this repository."}'))
    monkeypatch.setattr(posture.urllib.request, "urlopen", raise_404)
    assert posture.ghas_is_enabled("x") is False


@pytest.mark.parametrize("outcome", ["other-404", "500", "network"])
def test_an_inconclusive_probe_fails_toward_reporting_not_toward_silence(monkeypatch, outcome):
    """The dangerous direction is exempting a real finding forever. If the probe
    cannot tell, the feature stays a to-do."""
    def fail(req, timeout=None):
        if outcome == "other-404":
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {},
                                         __import__("io").BytesIO(b'{"message":"Not Found"}'))
        if outcome == "500":
            raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {},
                                         __import__("io").BytesIO(b"{}"))
        raise OSError("connection reset")
    monkeypatch.setattr(posture.urllib.request, "urlopen", fail)
    assert posture.ghas_is_enabled("x") is True


def test_an_unreadable_posture_is_reported_rather_than_passed(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(posture, "fetch", lambda token: {})
    assert posture.main(["--warn"]) == 0
    assert "posture unknown, not verified" in capsys.readouterr().out


def test_a_missing_token_is_loud(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert posture.main([]) == 2
    assert "not the same as it being fine" in capsys.readouterr().err


def test_this_repository_currently_has_everything_it_can_have(monkeypatch):
    """The state #787 closed on: the only two features off are the two GitHub
    does not offer here, so the weekly check must be quiet."""
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(posture, "ghas_is_enabled", lambda token: False)
    monkeypatch.setattr(posture, "fetch", lambda token: {"security_and_analysis": {
        "secret_scanning": {"status": "enabled"},
        "secret_scanning_push_protection": {"status": "enabled"},
        "dependabot_security_updates": {"status": "enabled"},
        "secret_scanning_non_provider_patterns": {"status": "disabled"},
        "secret_scanning_validity_checks": {"status": "disabled"},
    }})
    assert posture.main([]) == 0, "a finding nobody can act on must not fail the check"


def test_the_weekly_check_runs_it_and_cannot_be_reddened_by_it():
    workflow = (ROOT / ".github" / "workflows" / "weekly-health.yml").read_text(encoding="utf-8")
    step = workflow.split("GitHub security features still off", 1)[1].split("- name:", 1)[0]
    assert "ops/ci/security_posture.py --warn" in step
    assert "continue-on-error: true" in step
