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


def test_a_nonzero_exit_that_still_named_a_message_is_unknown_not_failed():
    """2026-08-31: the exit code lost a race the delivery had already won.

    The brief's Telegram co-send was recorded failed at 08:08:50; the gateway
    handed Telegram messageId 1164 at 08:08:54. `failed` wrote tg_ok=false into
    the marker, the watchdog read that as "never arrived" and mirrored the same
    card at 08:30. An id in the transport's own output is evidence of the
    opposite, so it downgrades the verdict to `unknown` — which still mirrors
    when nothing else confirms, but no longer asserts a miss.
    """
    out = '{"action":"send","messageId":"1164","payload":{"ok":true}}\nEPIPE'
    sent = OpenClawDelivery(runner=lambda cmd: (1, out)).send(
        "telegram", "123", "hello")

    assert sent.status == "unknown"
    assert sent.reached_target is False
    assert sent.worth_mirroring is True


def test_a_nonzero_exit_with_no_message_id_is_still_a_failure():
    sent = OpenClawDelivery(runner=lambda cmd: (1, "connection refused")).send(
        "telegram", "123", "hello")

    assert sent.status == "failed"
    assert "connection refused" in sent.detail


def test_a_null_message_id_is_not_evidence_of_delivery():
    """The transport saying it has no id is the opposite of naming one."""
    sent = OpenClawDelivery(runner=lambda cmd: (1, '{"messageId": null}')).send(
        "telegram", "123", "hello")

    assert sent.status == "failed"


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


def test_a_gateway_timeout_is_not_a_refusal():
    """2026-09-08, measured on the desk: both of the day's "failed" sends landed.

        10:34:20  co-send gives up      GatewayTransportError: gateway timeout
                                        after 10000ms
        10:34:30  gateway logs          [telegram] outbound send ok messageId=1318
                  [ws] res ✓ message.action 16499ms
        10:43:15  watchdog mirror       same 10000ms timeout
        10:43:40  gateway logs          messageId=1319, 25708ms

    The mirror at 10:43 exists only because 10:34 was written down as a
    failure, so kcn got the 10:34 intraday card twice while `watchdog.jsonl`
    recorded the slot as undelivered. The CLI giving up is not the gateway
    giving up, and it is the same event as our own subprocess timeout — which
    this file already calls `unknown` one test above.
    """
    out = ("GatewayTransportError: gateway timeout after 10000ms\n"
           "Gateway target: ws://127.0.0.1:18789\nSource: local loopback")
    sent = OpenClawDelivery(runner=lambda cmd: (1, out)).send(
        "telegram", "123", "hello")

    assert sent.status == "unknown"
    assert sent.reached_target is False
    # Still worth a backstop: `unknown` is not a claim that it arrived.
    assert sent.worth_mirroring is True


def test_the_cli_is_told_to_wait_as_long_as_we_are_waiting():
    """The 10s ceiling is the CLI's default, and it is ours to raise.

    `resolveGatewayCallTimeout` in the runtime takes the call timeout from the
    handshake timeout whenever that is above its 10 000 floor, so one env var
    moves it. Measured against a socket that accepts and never answers:
    unset → gave up at 13.2s wall, `OPENCLAW_HANDSHAKE_TIMEOUT_MS=25000` →
    28.0s. Nothing waits longer than the subprocess budget it was given, which
    is where this number comes from.
    """
    import clawock.providers.delivery as delivery

    seen = {}

    class _Done:
        returncode, stdout, stderr = 0, '{"messageId":"7"}', ""

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return _Done()

    original = delivery.subprocess.run
    delivery.subprocess.run = fake_run
    try:
        provider = OpenClawDelivery(binary="/bin/true", timeout=60)
        result = provider.send("telegram", "123", "hi")
    finally:
        delivery.subprocess.run = original

    assert result.status == "confirmed"
    assert seen["timeout"] == 60
    assert seen["env"]["OPENCLAW_HANDSHAKE_TIMEOUT_MS"] == "45000"
    # Under the process budget it is spawned with, always: a CLI still waiting
    # when we kill it turns a reportable error into an opaque one.
    assert int(seen["env"]["OPENCLAW_HANDSHAKE_TIMEOUT_MS"]) < 60 * 1000
    # And never under the runtime's own floor, where it would be inert.
    assert OpenClawDelivery(timeout=5).rpc_ceiling_ms() == 10_000


def test_a_cron_read_gives_the_cli_the_same_budget_it_gives_the_process():
    """`CRON_TIMEOUT_SECONDS` was 120s of subprocess and 10s of CLI (#1405).

    The comment on that constant says a tight timeout makes callers "read as
    'no data' and quietly fall back to a stale source" — which is exactly what
    the CLI's own 10s ceiling was doing inside the 120s, unseen. `read_jobs`
    then drops to SQLite or to the fossil JSONL it prints STALE over, and
    `brief_cron_job` returns None and logs the brief watchdog inert for the
    slot. Both happen precisely when the host is loaded enough to be slow.
    """
    from types import SimpleNamespace

    import clawock.providers.openclaw as openclaw

    seen = {}

    def fake_run(cmd, **kwargs):
        seen['cmd'] = cmd
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"jobs": []}', stderr='')

    original = openclaw.subprocess.run
    openclaw.subprocess.run = fake_run
    try:
        assert openclaw.cron_cli_json(['list', '--json']) == {'jobs': []}
    finally:
        openclaw.subprocess.run = original

    assert seen['cmd'][1:] == ['cron', 'list', '--json']
    assert seen['timeout'] == openclaw.CRON_TIMEOUT_SECONDS == 120
    assert seen['env']['OPENCLAW_HANDSHAKE_TIMEOUT_MS'] == '105000'


def test_the_ceiling_is_one_rule_for_every_call_that_spawns_the_runtime():
    from clawock.providers.delivery import OpenClawDelivery
    from clawock.providers.openclaw import (
        GATEWAY_CALL_FLOOR_MS, rpc_ceiling_ms, runtime_env)

    # Same rule, whoever asks.
    assert OpenClawDelivery(timeout=60).rpc_ceiling_ms() == rpc_ceiling_ms(60)
    # Under the process budget always: a CLI still waiting when we kill it turns
    # a reportable error into an opaque one.
    for budget in (30, 60, 120, 600):
        assert rpc_ceiling_ms(budget) < budget * 1000
    # Never below the runtime's own floor, where asking would be inert.
    assert rpc_ceiling_ms(1) == GATEWAY_CALL_FLOOR_MS

    # And nothing is set when no budget was named — this env is a statement
    # about one call, not a global.
    assert 'OPENCLAW_HANDSHAKE_TIMEOUT_MS' not in runtime_env({'PATH': '/usr/bin'})
    assert runtime_env({'PATH': '/usr/bin'}, call_timeout=60)[
        'OPENCLAW_HANDSHAKE_TIMEOUT_MS'] == '45000'
    # An operator who typed a number keeps it.
    kept = runtime_env({'PATH': '/usr/bin', 'OPENCLAW_HANDSHAKE_TIMEOUT_MS': '7'},
                       call_timeout=60)
    assert kept['OPENCLAW_HANDSHAKE_TIMEOUT_MS'] == '7'
