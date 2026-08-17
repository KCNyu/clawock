"""The decision-trace contract exists twice and is not shared code.

`src/clawock/publish/dashboard.py::build_decision_traces` (Python, build time,
published in dashboard.json) and `examples/dsh/packages/clawock-dsh/src/
ledger.ts::readTraces` (TypeScript, read at runtime from the desk workspace)
render the same view from the same desk files. Both call themselves "the same
contract" in their own comments, and by 2026-08-17 they had drifted anyway:

  - the plugin moved T+1 onto the canonical bar store; the dashboard was still
    marking against snapshot `current_price` and got 9 of 40 verdicts wrong
    (#740);
  - the plugin shared one ±1% dead zone between the chip colour and the verdict
    word; the dashboard coloured on `delta >= 0`, so three live rows showed a
    red chip labelled 持平 (#739);
  - the plugin capped the T+1 gap at 4 calendar days; the dashboard had no
    ceiling at all;
  - the plugin used real calendar arithmetic for the ±3-day pairing window; the
    dashboard packed dates as y*400+m*32+d.

This module pins the load-bearing rule constants and vocabulary on both sides so
the next divergence fails a required check instead of shipping. Scope is honest:
it reads the TypeScript source rather than executing it, so it catches a changed
constant, threshold, action set or verdict word — not a behavioural rewrite. The
end-to-end behaviour of each side is covered by its own suite
(tests/test_decision_traces.py, tests/decision_studio_plugin.spec.js).
"""
import re
from pathlib import Path

import pytest

from clawock.publish import dashboard

PLUGIN_LEDGER = (Path(__file__).resolve().parents[1] / "examples" / "dsh"
                 / "packages" / "clawock-dsh" / "src" / "ledger.ts")


@pytest.fixture(scope="module")
def plugin_source():
    assert PLUGIN_LEDGER.exists(), f"plugin ledger source missing: {PLUGIN_LEDGER}"
    return PLUGIN_LEDGER.read_text(encoding="utf-8")


def _const(source, name):
    m = re.search(r'export const ' + re.escape(name) + r'\s*=\s*(-?\d+(?:\.\d+)?)', source)
    assert m, f"{name} not found in {PLUGIN_LEDGER.name}"
    return float(m[1])


def test_t1_gap_ceiling_matches(plugin_source):
    assert dashboard.T1_MAX_GAP_DAYS == _const(plugin_source, "T1_MAX_GAP_DAYS")


def test_t1_flat_band_matches(plugin_source):
    assert dashboard.T1_FLAT_BAND_PCT == _const(plugin_source, "T1_FLAT_BAND_PCT")


def test_reducing_action_set_matches(plugin_source):
    m = re.search(r"const SELL_ACTIONS = new Set\(\[([^\]]*)\]\)", plugin_source)
    assert m, "SELL_ACTIONS not found in the plugin ledger"
    plugin_actions = set(re.findall(r"'([^']+)'", m[1]))
    assert plugin_actions == set(dashboard.T1_SELL_ACTIONS), (
        "the two sides disagree about which actions reduce a position, so the "
        "same fill would be coloured win on one and loss on the other")


def test_verdict_vocabulary_matches(plugin_source):
    """Same five words, same conditions — a fill may not be 卖飞 in the plugin
    and 涨 on the dashboard."""
    m = re.search(r"export function t1VerdictOf\(.*?\n\}", plugin_source, re.S)
    assert m, "t1VerdictOf not found in the plugin ledger"
    plugin_words = set(re.findall(r"'([^']+)'", m[0]))
    ours = {dashboard._t1_verdict(a, d)
            for a in ("buy", "sell") for d in (-5, -0.5, 0.5, 5)}
    assert plugin_words == ours == {"卖飞", "卖对", "持平", "涨", "跌"}


def test_pairing_window_matches(plugin_source):
    """Both sides soft-pair on ±3 days of the fill."""
    m = re.search(r"if \(diff <= (\d+) && diff < bestDiff\)", plugin_source)
    assert m, "the plugin's pairing window is no longer recognisable"
    plugin_window = int(m[1])
    src = Path(dashboard.__file__).read_text(encoding="utf-8")
    ours = re.search(r"if diff <= (\d+) and diff < best_diff:", src)
    assert ours, "the dashboard's pairing window is no longer recognisable"
    assert plugin_window == int(ours[1]) == 3


def test_both_sides_read_the_canonical_bar_store(plugin_source):
    """#740's root cause in one assertion: whichever side reaches for
    memory/snapshots/ to settle a T+1 is the broken one."""
    assert "memory" in plugin_source and "'bars'" in plugin_source
    src = Path(dashboard.__file__).read_text(encoding="utf-8")
    builder = src[src.index("def build_decision_traces("):src.index("def _readable_rationale(")]
    assert "_bar_close_index" in builder
    # The quoted path component, so prose about snapshots stays allowed while
    # any attempt to build a memory/snapshots path here fails.
    assert "'snapshots'" not in builder and '"snapshots"' not in builder, (
        "build_decision_traces must not settle T+1 against snapshot prices")
    assert "_snapshot_close_index" not in builder


def test_verdict_and_tone_agree_on_every_side_of_the_dead_zone():
    """The invariant that failed live: a move the words call 持平 must not be
    coloured, and a coloured move must not be called 持平."""
    for action in ("buy", "add", "sell", "cut", "trim", "trim_on_rebound"):
        for delta in (-9, -1.0001, -1, -0.999, 0, 0.999, 1, 1.0001, 9):
            verdict = dashboard._t1_verdict(action, delta)
            tone = dashboard._t1_tone(action, delta)
            assert (verdict == "持平") == (tone == "flat"), (action, delta, verdict, tone)
