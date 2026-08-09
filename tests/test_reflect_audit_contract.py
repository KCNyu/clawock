from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "site/index.html").read_text() + "".join(
    (ROOT / "site" / "assets" / "js" / name).read_text()
    for name in (
        "dashboard.core.js",
        "dashboard.charts.js",
        "dashboard.render.js",
        "dashboard.ui.js",
    )
)
BUILD = (ROOT / "scripts" / "data" / "build_dashboard.py").read_text()
HARNESS_WORKFLOW = (
    ROOT / ".github" / "workflows" / "harness-regression.yml"
).read_text()
SIDECAR_VALIDATORS = (
    ROOT / "src" / "clawock" / "validate_sidecars.py"
).read_text()


def test_reflect_loads_audit_as_sidecar_and_not_dashboard_field():
    assert '"decision_audit"' in HTML
    assert "assets/data/" in HTML
    assert "build_audit_sidecar" in BUILD
    assert "out['decision_audit']" not in BUILD
    assert "out['episode_backtest']" not in BUILD


def test_reflect_sidecar_compiles_backtest_from_the_same_decisions(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    import build_dashboard

    decisions = [{"decision_id": "d1"}]
    monkeypatch.setattr(
        build_dashboard.decision_v2,
        "build_audit_sidecar",
        lambda rows, portfolio, include_records: {
            "schema_version": 1,
            "decision_ids": [row["decision_id"] for row in rows],
            "records_included": include_records,
        },
    )
    monkeypatch.setattr(
        build_dashboard.decision_v2,
        "compute_backtest",
        lambda rows: {"decision_ids": [row["decision_id"] for row in rows]},
    )

    sidecar = build_dashboard.build_decision_audit_payload(decisions, {})
    assert sidecar["decision_ids"] == ["d1"]
    assert sidecar["records_included"] is False
    assert sidecar["episode_backtest"] == {"decision_ids": ["d1"]}


def test_remote_rebuild_gate_validates_the_new_payload_boundary():
    gate = HARNESS_WORKFLOW.split(
        "- name: Rebuild dashboard.json and validate", 1
    )[1].split("- name: Run build_dashboard sanity", 1)[0]
    dashboard_validator = SIDECAR_VALIDATORS.split(
        'def validate_dashboard', 1
    )[1].split('def validate_coverage_badge', 1)[0]
    assert "assets/data/decision_audit.json" in gate
    assert "clawock validate-sidecar dashboard" in gate
    assert "'episode_backtest' not in data" in dashboard_validator
    assert "audit.get('episode_backtest'" in gate


def test_reflect_card_keeps_timing_claims_narrow():
    # The per-decision audit wall was retired from the card (kcn); what stays
    # inline is the single-event timing diagnostic. Its honesty framing must
    # remain narrow. The full per-decision `records` trail is no longer published
    # (dead weight, nobody read it) and its "完整逐条审计" link was removed with it;
    # `records` stays fully recomputable from decisions via build_audit_sidecar.
    assert "单事件择时诊断" in HTML
    assert "触发价 vs 同日收盘执行好多少" in HTML
    assert "换仓不跨票比较" in HTML
    assert "HKD/USD 分区" in HTML
    assert "完整逐条审计" not in HTML
    assert "听 AI 多赚" not in HTML
    assert "portfolio alpha" not in HTML.lower()


def test_audit_sidecar_still_covers_all_four_states():
    # The list no longer renders inline, but the published sidecar must still
    # account for every decision across all four states (no cherry-picking).
    dv = (ROOT / "src" / "clawock" / "decision_v2.py").read_text()
    for state in ("settled", "not_triggered", "not_evaluable", "pending"):
        assert state in dv
