"""The CI determinism gate must follow each output's declared clock fields."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "ci"))
from strip_dashboard_clocks import strip_output  # noqa: E402


def test_recursive_and_top_level_clock_fields_are_scoped_per_output():
    contract = json.loads((ROOT / "config/dashboard-outputs.json").read_text())
    sample = {"as_of": "today", "days_behind": 1,
              "nested": {"as_of": "nested", "days_behind": 2}}
    overview = strip_output("assets/data/overview.json", sample, contract)
    assert overview == {"as_of": "today", "nested": {"as_of": "nested"}}
    audit = strip_output("assets/data/decision_audit.json", sample, contract)
    assert audit == {"days_behind": 1,
                     "nested": {"as_of": "nested", "days_behind": 2}}
