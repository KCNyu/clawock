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


def test_a_payload_fragment_is_rendered_into_every_template_that_includes_it(tmp_path):
    """One text for a rule several jobs must obey (#2819): the exec exit-code
    rule had a copy per payload plus a wider one in the brief skill, and the
    wide copy is what told the model to end a failed preflight with `; true`.
    """
    profile_dir = tmp_path / "config/profiles/paper"
    profile_dir.mkdir(parents=True)
    payloads = tmp_path / "config/cron-payloads"
    payloads.mkdir(parents=True)
    (payloads / "_rule.md").write_text("shared rule for {{market}}\n")
    (payloads / "intraday.md").write_text("head\n{{include:_rule.md}}\ntail\n")
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
    job = contract["jobs"][0]
    assert scheduling.render_payload_message(contract, job) == (
        "head\nshared rule for paper\ntail")

    (payloads / "_rule.md").unlink()
    try:
        scheduling.render_payload_message(contract, job)
    except ValueError as exc:
        assert "template fragment" in str(exc)
    else:
        raise AssertionError("a missing fragment rendered a payload without its rule")


def test_the_three_strategy_payloads_carry_the_same_exec_contract():
    contract = scheduling.load_contract(workspace=ROOT, profile="kcnyu")
    fragment = (ROOT / "config/cron-payloads/_exec-contract.md").read_text().rstrip("\n")
    rendered = {
        job["payload_profile"]: scheduling.render_payload_message(contract, job)
        for job in contract["jobs"]
    }
    for profile in ("brief", "report", "intraday"):
        assert rendered[profile].count(fragment) == 1, profile


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


def test_profile_rejects_unread_policy_claims(tmp_path):
    source = json.loads((ROOT / 'examples/profiles/minimal/profile.json').read_text())
    source['policies'] = {'intraday': {'max_setup_lines': 3}}
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(source))
    try:
        load_profile(tmp_path, 'profile.json')
    except ValueError as exc:
        assert 'unknown fields' in str(exc)
    else:
        raise AssertionError('profile accepted a policy field with no runtime reader')


def test_profile_templates_surface_stays_deleted(tmp_path):
    source = json.loads((ROOT / "examples/profiles/minimal/profile.json").read_text())
    source["templates"] = {"intraday": "config/cron-payloads/intraday.md"}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(source))

    try:
        load_profile(tmp_path, "profile.json")
    except ValueError as exc:
        assert "unknown fields" in str(exc)
    else:
        raise AssertionError(
            "profile accepted the unconsumed templates surface; "
            "payload templates belong to config/cron-schedules.json"
        )
