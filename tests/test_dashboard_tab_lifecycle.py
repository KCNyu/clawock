"""Consumer-boundary contracts for the tab-lazy dashboard lifecycle."""
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "assets" / "js" / "dashboard.ui.js").read_text()
HERO = (ROOT / "assets" / "js" / "dashboard.hero.js").read_text()
CHARTS = (ROOT / "assets" / "js" / "dashboard.charts.js").read_text()


def _sidecar_keys() -> set[str]:
    block = UI.split("const SIDECAR_TAB = {", 1)[1].split("};", 1)[0]
    return set(re.findall(r"([a-z][a-z0-9_]+)\s*:", block))


def test_every_mapped_sidecar_has_a_valid_seed_before_browser_fetches_it():
    """A new optional producer must not ship a first-party 404 window."""
    for key in _sidecar_keys():
        path = ROOT / "assets" / "data" / f"{key}.json"
        assert path.is_file(), f"{path} needs a schema-valid seed before mapping"
        assert isinstance(json.loads(path.read_text()), dict)


def test_hidden_tabs_have_no_idle_or_timeout_renderer():
    assert "scheduleDeferredTabs" not in HERO
    assert "requestIdleCallback" not in HERO
    assert "didTimeout" not in HERO
    assert "renderLandingTab(activeTab, version" in HERO
    assert "if (currentTab() !== t)" in HERO
    assert "currentTab() !== t" in HERO


def test_tab_activation_owns_sidecar_fetch_and_inflight_deduplication():
    for contract in (
        "const SIDECAR_STATE = new Map()",
        "function activateTabData(t)",
        "function _loadTabSidecars(t",
        "if (state.inFlight) return state.inFlight",
        "if (state.ready && !state.stale)",
        "_applySidecars(DATA)",
        "version !== TAB_ACTIVATION_VERSION",
    ):
        assert contract in UI
    assert "deferred.map(fetchSidecar)" not in UI
    assert "new Set(deferred" not in UI


def test_echarts_uses_one_shared_load_promise_without_polling():
    loader = CHARTS.split("let _echartsPromise", 1)[1].split(
        "function paintCharts", 1
    )[0]
    assert "new Promise" in loader
    assert "s.onload" in loader
    assert "s.onerror" in loader
    assert "_echartsPromise.then" in loader
    assert "setInterval" not in loader
