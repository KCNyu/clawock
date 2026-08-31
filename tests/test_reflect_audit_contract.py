from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_reflect_sidecar_compiles_backtest_from_the_same_decisions(monkeypatch):
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


def _debated(decision_id, created_at, **over):
    row = {
        "decision_id": decision_id,
        "created_at": created_at,
        "plan_date": created_at[:10],
        "ticker": "SPCH",
        "name": "Leverage Shares 2X Long SpaceX",
        "action": "cut",
        "confidence": 0.9,
        "debate": {
            "bull": "5d +6.4%, the Musk headline is not priced out yet.",
            "bear": "Hard stop is 47 days old and VaR95 is through its limit.",
            "attacked_consensus": "Attacked the aggressive case for keeping half.",
            "judge": "Discipline first: a policy swap is not a timing call.",
            "frames": ["technical_breakdown", "risk_budget"],
        },
    }
    row.update(over)
    return row


def test_debate_sidecar_publishes_the_argument_not_only_its_count():
    """#1117: the claim is 'we debate both sides' — so publish both sides.

    `debate_metrics.debate_coverage` already says how many decisions carried a
    debate. A count is not the claim: a reader could verify that a block was
    recorded, never what was argued. This pins that the block itself goes out,
    joined to the decision that produced it.
    """
    from clawock.publish import dashboard as build_dashboard

    rows = build_dashboard.build_debate_sidecar([
        _debated("d-old", "2026-08-29T08:00:00+08:00"),
        _debated("d-new", "2026-08-31T08:00:00+08:00"),
        {"decision_id": "d-none", "created_at": "2026-08-30T08:00:00+08:00"},
        {"decision_id": "d-empty", "created_at": "2026-08-30T08:00:00+08:00", "debate": {}},
    ])["rows"]

    # Newest first, and only the decisions that actually carry a debate.
    assert [r["decision_id"] for r in rows] == ["d-new", "d-old"]
    row = rows[0]
    # Every side of the argument, plus the id that joins it to the call.
    assert row["bull"] and row["bear"]
    assert row["attacked_consensus"] and row["judge"]
    assert row["frames"] == ["technical_breakdown", "risk_budget"]
    assert row["ticker"] == "SPCH" and row["action"] == "cut" and row["date"] == "2026-08-31"


def test_debate_sidecar_window_is_bounded():
    """~1.1KB of UTF-8 per block, so the sidecar publishes a window.

    The window is the *sidecar's*; the coverage series in `debate_metrics`
    stays whole-ledger, so shrinking this cannot make a falling coverage look
    healthy.
    """
    from clawock.publish import dashboard as build_dashboard

    many = [
        _debated(f"d{i:03d}", f"2026-08-{(i % 28) + 1:02d}T08:00:00+08:00")
        for i in range(80)
    ]
    block = build_dashboard.build_debate_sidecar(many, limit=5)
    assert block["limit"] == 5
    assert len(block["rows"]) == 5


def test_reflect_sidecar_carries_the_debates(monkeypatch):
    from clawock.publish import dashboard as build_dashboard

    monkeypatch.setattr(
        build_dashboard.decision_v2, "build_audit_sidecar",
        lambda rows, portfolio, include_records: {"schema_version": 1},
    )
    monkeypatch.setattr(
        build_dashboard.decision_v2, "compute_backtest", lambda rows: {},
    )
    sidecar = build_dashboard.build_decision_audit_payload(
        [_debated("d1", "2026-08-31T08:00:00+08:00")], {})
    assert sidecar["debates"]["rows"][0]["decision_id"] == "d1"


def test_reflect_tab_renders_the_debate_trail():
    """The sidecar is only observable if the page draws it (#1117).

    Pins the three hand-maintained halves against each other: the card exists
    in the page, the renderer reads the published key and is registered on the
    Reflect tab.
    """
    html = (ROOT / "site" / "index.html").read_text()
    render = (ROOT / "site" / "assets" / "js" / "dashboard.render.js").read_text()

    assert 'id="debate-card"' in html
    assert 'id="debate-body"' in html
    assert 'safe(DATA, "decision_audit", "debates")' in render
    reflect = render.split("reflect: [", 1)[1].split("]", 1)[0]
    assert "renderDebates" in reflect
