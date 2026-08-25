"""Free text from sidecars / external sources may only reach innerHTML escaped.

The page's own convention: LLM narrative goes through `escLLM`, every other
sidecar string through `escapeHtml`. Several cards predated that convention
and interpolated brief-context / ledger / RSS-sourced strings raw (#948 fixed
four market-tab cards; #985/#986 cover the plan-tab and macro/mover stragglers
the first sweep missed) — `innerHTML` executes event-attribute payloads
(`<img onerror=…>`) even though it never executes `<script>`, so the gap is a
real injection class, not style.

Sections are sliced out of the source the same way
test_dashboard_bundle_parity.py finds top-level functions: two-space indented
declarations, closed by a lone `  }`. Source assertions rather than a browser
run because the invariant is about what the template interpolates; the runtime
cost of booting the whole spec for these greps is not justified.
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "site" / "assets" / "js" / "dashboard.render.js"

_DECL = re.compile(r"^  function ([A-Za-z_$][\w$]*)\s*\(")


def _function_body(name: str) -> str:
    lines = RENDERER.read_text(encoding="utf-8").split("\n")
    starts = [i for i, line in enumerate(lines) if _DECL.match(line)]
    names = {i: _DECL.match(lines[i]).group(1) for i in starts}
    own = next((i for i in starts if names[i] == name), None)
    assert own is not None, f"{name} not found in {RENDERER.name}"
    end = own + 1
    while end < len(lines) and lines[end] != "  }":
        end += 1
    return "\n".join(lines[own:end + 1])


def test_sidecar_free_text_never_reaches_innerhtml_raw():
    anomalies = _function_body("renderAnomalies")
    catalysts = _function_body("renderCatalysts")
    sentiment = _function_body("renderSentimentDrill")
    risk_banner = _function_body("renderRiskBanner")

    # anomalies: ticker/type/detail come from the brief-context (agent-written).
    assert "escapeHtml(a.ticker || DASH)" in anomalies
    for field in ("a.ticker", "a.type", "a.detail"):
        assert "${%s}" % field not in anomalies, (
            f"{field} reaches innerHTML unescaped")
    # catalysts: earnings ticker + LLM-assembled detail.
    assert "escapeHtml(tag)" in catalysts and "escapeHtml(detail)" in catalysts
    # sentiment drill: third-party headline text was `<`-only before #948.
    assert ".replace(/</g, '&lt;')" not in sentiment
    assert "escapeHtml(n.title || '')" in sentiment
    assert "escapeHtml(p.title || '')" in sentiment
    assert "escapeHtml(t.ticker)" in sentiment
    # risk keyword banner reads the same sidecar.
    assert "escapeHtml(h.ticker)" in risk_banner


def test_plan_action_ledger_fields_never_reach_innerhtml_raw():
    """recent_decisions is the agent-written decisions.jsonl verbatim; the peer
    plan-timeline card escapes every one of these fields already (#985)."""
    actions = _function_body("renderPlanActions")
    for snippet in (
        "escapeHtml(a.ticker || DASH)",
        'escapeHtml(a.date || "")',
        "escapeHtml(a.action || DASH)",
        "escapeHtml(a.strategy_id || DASH)",
        "escapeHtml(cond.type || DASH)",
    ):
        assert snippet in actions, f"missing escaped interpolation: {snippet}"
    for field in ("a.ticker", "a.date", "a.action", "a.strategy_id", "cond.type"):
        assert "${%s" % field not in actions, (
            f"{field} reaches innerHTML unescaped")


def test_fed_press_external_text_is_escaped_and_https_only():
    """fed_press titles/links are raw federalreserve.gov RSS XML; the influencer
    feed already escapes its external hrefs. escapeHtml stops attribute escape
    but not javascript: URLs, so the anchor itself is https-gated (#986)."""
    macro = _function_body("renderMacro")
    assert "escapeHtml(p.date)" in macro
    assert "escapeHtml((p.title || '').substring(0, 130))" in macro
    assert "/^https:\\/\\//i.test(p.url || '')" in macro
    assert '${p.url}' not in macro
    assert '${p.title' not in macro
    assert '${p.date}' not in macro


def test_mover_provider_fields_never_reach_innerhtml_raw():
    """movers ticker/name come from provider-sourced holdings (trim_holding);
    hero.js escapes the same ticker, so render.js must not diverge (#986)."""
    movers = _function_body("renderMovers")
    assert "escapeHtml(m.ticker || DASH)" in movers
    assert 'escapeHtml(m.name || "")' in movers
    assert "${m.ticker" not in movers
    assert "${m.name" not in movers
