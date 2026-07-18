from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text() + "".join(
    (ROOT / "assets" / "js" / name).read_text()
    for name in (
        "dashboard.core.js",
        "dashboard.charts.js",
        "dashboard.render.js",
        "dashboard.ui.js",
    )
)
BUILD = (ROOT / "scripts" / "data" / "build_dashboard.py").read_text()


def test_reflect_loads_audit_as_sidecar_and_not_dashboard_field():
    assert '"decision_audit"' in HTML
    assert "assets/data/" in HTML
    assert "build_audit_sidecar" in BUILD
    assert "out['decision_audit']" not in BUILD


def test_reflect_card_keeps_timing_claims_narrow():
    # The per-decision audit wall was retired from the card (kcn); what stays
    # inline is the single-event timing diagnostic. Its honesty framing must
    # remain narrow, and the full audit trail must still be linked as a sidecar.
    assert "单事件择时诊断" in HTML
    assert "触发价 vs 同日收盘执行好多少" in HTML
    assert "换仓不跨票比较" in HTML
    assert "HKD/USD 分区" in HTML
    assert "decision_audit.json" in HTML
    assert "听 AI 多赚" not in HTML
    assert "portfolio alpha" not in HTML.lower()


def test_audit_sidecar_still_covers_all_four_states():
    # The list no longer renders inline, but the published sidecar must still
    # account for every decision across all four states (no cherry-picking).
    dv = (ROOT / "scripts" / "data" / "decision_v2.py").read_text()
    for state in ("settled", "not_triggered", "not_evaluable", "pending"):
        assert state in dv
