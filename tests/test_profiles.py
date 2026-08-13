import json
from pathlib import Path

from clawock.config.profiles import load_profile
from clawock import scheduling


ROOT = Path(__file__).resolve().parents[1]


def test_kcnyu_profile_drives_the_schedule_resource():
    profile = load_profile(ROOT, "kcnyu")
    contract = scheduling.load_contract(workspace=ROOT, profile="kcnyu")

    assert profile.profile_id == "kcnyu"
    assert profile.markets["us"].timezone == "America/New_York"
    assert contract.workspace == ROOT
    assert len(contract["jobs"]) == 11


def test_schedule_templates_resolve_in_the_selected_profile_workspace(tmp_path):
    profile_dir = tmp_path / "config/profiles/paper"
    profile_dir.mkdir(parents=True)
    (tmp_path / "config/cron-payloads").mkdir(parents=True)
    (tmp_path / "config/cron-payloads/intraday.md").write_text("market={{market}}\n")
    (tmp_path / "config/schedule.json").write_text(json.dumps({
        "schema_version": 2,
        "payload_profiles": {
            "intraday": {"message_template": "config/cron-payloads/intraday.md"}
        },
        "jobs": [{
            "name": "paper slot",
            "schedule": {"expr": "0 * * * *", "tz": "UTC"},
            "payload_profile": "intraday",
            "payload_vars": {"market": "paper"},
        }],
        "dst_sync": {"schedule": {"expr": "0 0 * * *"}, "command": "true"},
    }))
    source = json.loads((ROOT / "examples/profiles/minimal/profile.json").read_text())
    source["id"] = "paper"
    (profile_dir / "profile.json").write_text(json.dumps(source))

    contract = scheduling.load_contract(workspace=tmp_path, profile="paper")
    assert scheduling.render_payload_message(contract, contract["jobs"][0]) == (
        "market=paper"
    )


def test_profile_rejects_unknown_code_shaped_configuration(tmp_path):
    source = json.loads((ROOT / "examples/profiles/minimal/profile.json").read_text())
    source["python_module"] = "customer.strategy"
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(source))

    try:
        load_profile(tmp_path, "profile.json")
    except ValueError as exc:
        assert "unknown fields" in str(exc)
    else:
        raise AssertionError("profile accepted executable instance configuration")
