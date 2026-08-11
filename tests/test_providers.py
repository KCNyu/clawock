"""Three things that would make these providers worse than the status quo.

1. Delivery collapsing back to a boolean. WeChat's CLI reports success for a
   send its cold session silently drops (upstream wontfix), which is why the
   intraday watchdog mirrors to Telegram on suspicion. `unknown` has to be its
   own state: folded into success a dropped report looks delivered; folded into
   failure it triggers duplicate sends.
2. The two run-history sources not actually normalising — the point of the
   interface is that a caller need not know which scheduler answered.
3. A missing binary raising instead of reporting.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawock.providers import (  # noqa: E402
    DeliveryResult, GitHubRuns, NullDelivery, OpenClawDelivery, OpenClawRuns, Run,
)


@pytest.fixture(autouse=True)
def fake_transport_tests_are_explicitly_enabled(monkeypatch):
    """These tests use injected local runners; none can reach a real binary."""
    monkeypatch.setenv("CLAWOCK_DELIVERY_DISABLED", "0")


def test_delivery_disable_gate_never_calls_the_transport(monkeypatch):
    monkeypatch.setenv("CLAWOCK_DELIVERY_DISABLED", "1")

    def must_not_run(_cmd):
        raise AssertionError("the transport was reached while delivery was disabled")

    sent = OpenClawDelivery(runner=must_not_run).send(
        "openclaw-weixin", "real-target", "fixture body")

    assert sent.status == "failed"
    assert "CLAWOCK_DELIVERY_DISABLED" in sent.detail


def test_wechat_success_is_unknown_not_confirmed():
    sent = OpenClawDelivery(runner=lambda cmd: (0, '{"ok":true}')).send(
        "wechat", "kcn", "hello")

    assert sent.status == "unknown"
    assert sent.reached_target is False, (
        "a channel that cannot confirm must never report the message arrived")
    assert sent.worth_mirroring is True


def test_telegram_success_is_confirmed_and_needs_no_mirror():
    sent = OpenClawDelivery(runner=lambda cmd: (0, "{}")).send(
        "telegram", "123", "hello")

    assert sent.status == "confirmed"
    assert sent.reached_target is True
    assert sent.worth_mirroring is False


def test_a_timeout_is_unknown_because_the_message_may_have_gone():
    import subprocess

    def boom(cmd):
        raise subprocess.TimeoutExpired(cmd, 60)

    sent = OpenClawDelivery(runner=boom).send("wechat", "kcn", "hi")

    # Calling this `failed` would invite a duplicate send of a report that
    # possibly arrived.
    assert sent.status == "unknown"


def test_a_missing_binary_reports_instead_of_raising():
    def missing(cmd):
        raise FileNotFoundError(cmd[0])

    sent = OpenClawDelivery(runner=missing).send("wechat", "kcn", "hi")

    assert sent.status == "failed"
    assert "not installed" in sent.detail


def test_the_null_provider_never_claims_delivery():
    provider = NullDelivery()

    sent = provider.send("wechat", "kcn", "hi")

    assert sent.status == "accepted"
    assert sent.reached_target is False
    assert provider.sent[0]["message"] == "hi"


def test_an_invalid_status_cannot_be_constructed():
    with pytest.raises(ValueError, match="unknown delivery status"):
        DeliveryResult("delivered", "wechat", "kcn")


def test_both_run_sources_normalise_to_the_same_shape():
    openclaw = OpenClawRuns(reader=lambda job: [
        {"jobName": "brief", "runAtIso": "2026-08-01T08:00:00+08:00",
         "durationMs": 1167, "action": "finished", "status": "ok",
         "sessionId": "abc"},
    ]).history("brief")
    github = GitHubRuns(runner=lambda cmd: (
        '[{"conclusion":"success","createdAt":"2026-08-01T00:00:00Z",'
        '"event":"schedule","databaseId":42}]')).history("brief-fallback.yml")

    assert [type(r) for r in openclaw + github] == [Run, Run]
    assert openclaw[0].status == github[0].status == "ok"
    # A caller must not have to know which scheduler answered.
    assert {r.source for r in openclaw + github} == {"openclaw", "github"}
    assert openclaw[0].reference == "abc" and github[0].reference == "42"
    assert github[0].trigger == "schedule"


def test_an_unfinished_github_run_is_running_not_success():
    runs = GitHubRuns(runner=lambda cmd: (
        '[{"conclusion":null,"createdAt":"2026-08-02T00:00:00Z",'
        '"event":"schedule","databaseId":7}]')).history("x")

    assert runs[0].status == "running"


def test_cancelled_github_run_stays_neutral_and_keeps_its_trigger():
    runs = GitHubRuns(runner=lambda cmd: (
        '[{"conclusion":"cancelled","createdAt":"2026-08-02T00:00:00Z",'
        '"event":"workflow_dispatch","databaseId":8}]')).history("x")

    assert runs[0].status == "cancelled"
    assert runs[0].trigger == "workflow_dispatch"


def test_an_outcome_the_source_cannot_state_is_unknown_not_ok():
    runs = OpenClawRuns(reader=lambda job: [
        {"jobName": "brief", "runAtIso": "2026-08-01T08:00:00+08:00",
         "action": "finished"},          # no status field at all
    ]).history("brief")

    assert runs[0].status == "unknown", (
        "a recorded run with no stated outcome must not round to success")


def test_delivery_rewire_preserves_the_ok_contract_callers_depend_on():
    """Every caller reads `(ok, tail)`. The provider has four states; `ok` must
    still mean exactly what a non-zero exit meant before, or a WeChat send that
    the cold session drops starts reading as a failure and triggers a duplicate.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from clawock.providers.delivery import OpenClawDelivery

    for code, expected_ok in ((0, True), (1, False)):
        result = OpenClawDelivery(
            runner=lambda cmd, c=code: (c, '{"ok":1}')).send("wechat", "kcn", "hi")
        assert (result.status != "failed") is expected_ok, result


def test_running_a_cron_job_reports_instead_of_raising():
    """`run_cron_job` is a watchdog's recovery lever, so it answers `(ok, tail)`
    like every other adapter call: a scheduler that is down must read as "not
    queued", never as an exception inside a crontab entry (#493)."""
    from types import SimpleNamespace

    from clawock.providers.openclaw import run_cron_job

    calls = []

    def queued(cmd):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="queued run 42", stderr="")

    ok, tail = run_cron_job("job-1", binary="/opt/openclaw", runner=queued)
    assert ok and "queued run 42" in tail
    assert calls == [["/opt/openclaw", "cron", "run", "job-1"]]

    ok, tail = run_cron_job(
        "job-1", runner=lambda _cmd: SimpleNamespace(
            returncode=1, stdout="", stderr="gateway unreachable"))
    assert not ok and "gateway unreachable" in tail

    def explode(_cmd):
        raise TimeoutError("no gateway")

    ok, tail = run_cron_job("job-1", runner=explode)
    assert not ok and "TimeoutError" in tail
