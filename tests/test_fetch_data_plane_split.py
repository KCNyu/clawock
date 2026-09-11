"""A generation published before an output was split out of dashboard.json may
lack it; any other missing member is still a partial generation (#314)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "pages"))
sys.path.insert(0, str(ROOT / "ops" / "publish"))
import fetch_data_plane  # noqa: E402

TRAIL = "assets/data/decision_trail.json"


class _Store:
    def __init__(self, dashboard):
        self.dashboard = dashboard

    def _git_blob(self, ref, name):
        assert name == "assets/data/dashboard.json"
        return json.dumps(self.dashboard)


def _missing(*names):
    return FileNotFoundError(f"origin/data-plane does not carry {list(names)}")


def test_a_pre_split_generation_may_lack_the_new_sidecar():
    store = _Store({"decision_traces": [], "decision_trace_scope": {}, "plan_timeline": []})
    assert fetch_data_plane.pre_split_members(store, _missing(TRAIL)) == [TRAIL]


def test_a_post_split_generation_without_it_is_still_partial():
    store = _Store({"generated_at": "x"})
    assert fetch_data_plane.pre_split_members(store, _missing(TRAIL)) == []


def test_other_missing_members_are_never_excused():
    store = _Store({"decision_traces": [], "decision_trace_scope": {}, "plan_timeline": []})
    assert fetch_data_plane.pre_split_members(
        store, _missing(TRAIL, "assets/data/overview.json")) == []
