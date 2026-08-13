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
