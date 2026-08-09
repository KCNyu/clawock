from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_reflect_sidecar_compiles_backtest_from_the_same_decisions(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    from clawock.publish import dashboard as build_dashboard

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
