"""Free text from sidecars / external sources may only reach innerHTML escaped.

The page's own convention: LLM narrative goes through `escLLM`, every other
sidecar string through `escapeHtml`. Four market-tab cards predate that
convention and interpolated brief-context / RSS-sourced strings raw (#948) —
`innerHTML` executes event-attribute payloads (`<img onerror=…>`) even though it
never executes `<script>`, so the gap is a real injection class, not style.

Sections are sliced out of the source the same way
test_dashboard_bundle_parity.py finds top-level functions: two-space indented
declarations, closed by a lone `  }`. Source assertions rather than a browser
run because the invariant is about what the template interpolates; the runtime
cost of booting the whole spec for four greps is not justified.
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
