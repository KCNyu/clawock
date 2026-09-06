import copy
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "host"))
sys.path.insert(0, str(ROOT))

from clawock import scheduling as cron_contract
import sync_cron_payloads
from clawock.providers.openclaw import OPENCLAW_BIN


JULY = datetime(2026, 7, 30, 0, tzinfo=timezone.utc)


def contract():
    return cron_contract.load_contract(ROOT / "config" / "cron-schedules.json")


def live_from_contract(data):
    live = []
    for index, spec in enumerate(data["jobs"]):
        profile = data["payload_profiles"][spec["payload_profile"]]
        payload = {
            "kind": profile["payload_kind"],
            "model": profile["model"],
            "message": cron_contract.render_payload_message(data, spec),
        }
        for contract_field, live_field in (
            ("fallbacks", "fallbacks"),
            ("thinking", "thinking"),
            ("tools_allow", "toolsAllow"),
            ("timeout_seconds", "timeoutSeconds"),
        ):
            if contract_field in profile:
                value = profile[contract_field]
                if value is not None:
                    payload[live_field] = copy.deepcopy(value)
        live.append({
            "id": f"id-{index}",
            "name": spec["name"],
            "enabled": spec.get("enabled", True),
            "schedule": copy.deepcopy(cron_contract.effective_schedule(spec, JULY)),
            "payload": payload,
            "delivery": {"mode": profile["delivery_mode"]},
            "status": "ok",
            "state": {},
        })
    return live


def test_exact_contract_is_an_idempotent_noop():
    data = contract()
    changes, errors = sync_cron_payloads.desired_changes(
        data, live_from_contract(data), JULY
    )
    assert changes == []
    assert errors == []


def test_drift_plan_and_command_patch_only_declared_fields(
        resolves_the_real_openclaw_binary):
    data = contract()
    live = live_from_contract(data)
    job = next(item for item in live if item["name"] == "美股盘中盯盘")
    job["payload"]["thinking"] = "high"
    job["payload"]["fallbacks"] = []
    job["payload"]["toolsAllow"] = ["exec", "process", "read", "write"]
    job["payload"]["message"] += "\nmanual drift"
    job["delivery"]["to"] = "preserve-me"

    changes, errors = sync_cron_payloads.desired_changes(data, live, JULY)
    assert errors == []
    assert len(changes) == 1
    change = changes[0]
    assert {diff["field"] for diff in change["diffs"]} == {
        "thinking", "fallbacks", "toolsAllow", "message"
    }
    command = sync_cron_payloads.build_edit_command(change)
    assert command[0] == OPENCLAW_BIN
    assert command[1:4] == ["cron", "edit", job["id"]]
    assert command[command.index("--thinking") + 1] == "adaptive"
    profile = data["payload_profiles"]["intraday"]
    assert command[command.index("--fallbacks") + 1] == ",".join(
        profile["fallbacks"]
    )
    assert "--clear-tools" in command
    assert "--tools" not in command
    assert "--message" in command
    assert "preserve-me" not in command


def test_nonzero_scheduler_stagger_is_reset_to_exact():
    data = contract()
    live = live_from_contract(data)
    job = next(item for item in live if item["name"] == "美股开盘报告")
    job["schedule"]["staggerMs"] = 60_000
    changes, errors = sync_cron_payloads.desired_changes(data, live, JULY)
    assert errors == []
    assert len(changes) == 1
    assert changes[0]["patch"]["schedule"]["exact"] is True
    command = sync_cron_payloads.build_edit_command(changes[0])
    assert "--exact" in command


def test_rendering_changes_only_double_brace_contract_tokens():
    data = contract()
    intraday = next(
        job for job in data["jobs"] if job["name"] == "美股盘中盯盘"
    )
    brief = next(job for job in data["jobs"] if job["name"] == "盘前深度简报")
    intraday_message = cron_contract.render_payload_message(data, intraday)
    brief_message = cron_contract.render_payload_message(data, brief)

    assert "{{" not in intraday_message
    assert "{CTXID}" in intraday_message
    assert "${total}" in brief_message

    missing = copy.deepcopy(intraday)
    missing["payload_vars"].pop("market_name")
    try:
        cron_contract.render_payload_message(data, missing)
    except ValueError as exc:
        assert "missing template variables" in str(exc)
    else:
        raise AssertionError("missing template variable was accepted")

    unused = copy.deepcopy(intraday)
    unused["payload_vars"]["unused"] = "x"
    try:
        cron_contract.render_payload_message(data, unused)
    except ValueError as exc:
        assert "unused template variables" in str(exc)
    else:
        raise AssertionError("unused template variable was accepted")


def test_duplicate_or_missing_jobs_abort_before_planning_mutations():
    data = contract()
    live = live_from_contract(data)
    live.append(copy.deepcopy(live[0]))
    changes, errors = sync_cron_payloads.desired_changes(data, live, JULY)
    assert changes == []
    assert any("duplicate live job name" in error for error in errors)

    live = live_from_contract(data)[1:]
    changes, errors = sync_cron_payloads.desired_changes(data, live, JULY)
    assert changes == []
    assert any("missing live job" in error for error in errors)


def test_running_changed_job_is_a_precondition_error():
    data = contract()
    live = live_from_contract(data)
    live[0]["payload"]["thinking"] = "high"
    live[0]["status"] = "running"
    live[0]["state"]["runningAtMs"] = 123
    changes, errors = sync_cron_payloads.desired_changes(data, live, JULY)
    assert changes == []
    assert errors == [
        f"{live[0]['name']}: job is currently running; retry after it finishes"
    ]


def test_apply_stops_at_first_failure_and_uses_argv(
        resolves_the_real_openclaw_binary):
    changes = [
        {
            "id": "one",
            "name": "first",
            "patch": {"thinking": "adaptive"},
            "diffs": [],
        },
        {
            "id": "two",
            "name": "second",
            "patch": {"thinking": "adaptive"},
            "diffs": [],
        },
    ]
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 9, stdout="", stderr="boom")

    errors = sync_cron_payloads.apply_changes(changes, runner=runner)
    assert len(calls) == 1
    assert isinstance(calls[0][0], list)
    # argv[0] is the absolute binary, not a bare name resolved off PATH (#330
    # step 2). The DST sync runs from crontab, where the bare form only works
    # because that entry happens to use a login shell.
    assert calls[0][0][0] == OPENCLAW_BIN
    assert calls[0][0][1:4] == ["cron", "edit", "one"]
    assert "first" in errors[0]
    assert "boom" in errors[0]


def test_apply_rechecks_running_state_before_each_edit():
    change = {
        "id": "one",
        "name": "first",
        "patch": {"thinking": "adaptive"},
        "diffs": [],
    }
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    errors = sync_cron_payloads.apply_changes(
        [change],
        runner=runner,
        live_loader=lambda: [{
            "id": "one",
            "name": "first",
            "status": "running",
            "state": {"runningAtMs": 123},
        }],
    )
    assert errors == ["first: job started running before apply; stopped"]
    assert calls == []


def test_cli_json_parser_tolerates_leading_warning():
    parsed = sync_cron_payloads._json_object('Config warning\n{"jobs": []}\n')
    assert parsed == {"jobs": []}
