"""Consumer-boundary contracts for the tab-lazy dashboard lifecycle."""
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "site" / "assets" / "js" / "dashboard.ui.js").read_text()
HERO = (ROOT / "site" / "assets" / "js" / "dashboard.hero.js").read_text()
CHARTS = (ROOT / "site" / "assets" / "js" / "dashboard.charts.js").read_text()


def _sidecar_keys() -> set[str]:
    block = UI.split("const SIDECAR_TAB = {", 1)[1].split("};", 1)[0]
    return set(re.findall(r"([a-z][a-z0-9_]+)\s*:", block))


def _data_plane_outputs() -> set[str]:
    """The artifacts the publisher puts on the `data-plane` branch (#314).

    Declared in the repository, so this resolves identically in a clean
    checkout, a worktree and CI.
    """
    config = json.loads(
        (ROOT / "config" / "dashboard-outputs.json").read_text(encoding="utf-8"))
    return set(config["outputs"])


def test_every_mapped_sidecar_has_a_producer_before_browser_fetches_it():
    """A new optional producer must not ship a first-party 404 window.

    Two publication routes reach the browser and the test has to know both, or
    it measures the machine instead of the contract. A sidecar either ships a
    schema-valid seed in the repository, or it is one of the build outputs #314
    took OUT of the repository and onto the `data-plane` branch — those are
    gitignored by design, so requiring a checked-in file made this assertion
    pass only where a dashboard build had already run. It failed in every clean
    worktree and passed in CI purely because an earlier test wrote the file,
    which is the worst shape a gate can have: green by side effect.

    Asserted against the tracked declaration instead, it is strictly stronger —
    a sidecar mapped with neither a seed nor a declared producer is a real 404
    and is now caught anywhere.
    """
    published = _data_plane_outputs()
    for key in _sidecar_keys():
        relative = f"assets/data/{key}.json"
        path = ROOT / relative
        if relative in published:
            continue
        assert path.is_file(), (
            f"{relative} is mapped in SIDECAR_TAB but has neither a seed in the "
            f"repository nor an entry in config/dashboard-outputs.json — the "
            f"browser would fetch a 404")
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
        # `(t` rather than `(t)`, like the line below it has always been: what
        # this pins is that tab activation is one named owner of the fetch, not
        # its arity. The exact form went red when the retry button needed a
        # `triggeredByUser` argument — a signature is shape, and pinning shape
        # is how a zero-behaviour change reddens a suite (#1364).
        "function activateTabData(t",
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
