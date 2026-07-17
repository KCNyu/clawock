from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text()
BUILD = (ROOT / "scripts" / "data" / "build_dashboard.py").read_text()


def test_reflect_loads_audit_as_sidecar_and_not_dashboard_field():
    assert '"decision_audit"' in HTML
    assert "assets/data/" in HTML
    assert "build_audit_sidecar" in BUILD
    assert "out['decision_audit']" not in BUILD


def test_reflect_card_keeps_audit_and_timing_claims_narrow():
    assert "当时依据与事后路径" in HTML
    assert "不挑赢家" in HTML
    assert "触发价 vs 同日收盘执行好多少" in HTML
    assert "换仓不跨票比较" in HTML
    assert "HKD/USD 分区" in HTML
    assert "听 AI 多赚" not in HTML
    assert "portfolio alpha" not in HTML.lower()


def test_reflect_card_renders_all_four_audit_states():
    for state in ("settled", "not-triggered", "not-evaluable", "pending"):
        assert state in HTML
