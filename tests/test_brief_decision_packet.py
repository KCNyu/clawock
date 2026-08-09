"""Contracts for harness-owned analysis and the Pages projection boundary."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from clawock.context import brief as brief_context
from clawock.decision import packet as packet_mod


def _context():
    return {
        "generated_at": "2026-07-28T08:00:00+08:00",
        "date": "2026-07-28",
        "portfolio": {
            "portfolios": {
                "us_stocks": {
                    "holdings": [{
                        "ticker": "LEVX", "name": "2x Example", "shares": 10,
                        "cost_basis": 20, "current_price": 12,
                        "pnl_percent": -40, "today_change_pct": -3,
                        "data_source": "fixture",
                    }]
                },
                "hk_stocks": {
                    "holdings": [{
                        "ticker": "00100", "name": "Example HK", "shares": 100,
                        "cost_basis": 10, "current_price": 11,
                        "pnl_percent": 10, "today_change_pct": 2,
                        "data_source": "fixture",
                    }]
                },
            }
        },
        "book_totals": {"usd_total_pnl": -10},
        "concentration": {"us": {"hhi": 1}, "hk": {"hhi": 1}},
        "risk_guardrail": {
            "directive": "delever",
            "lev_regime": {
                "us": {
                    "tier": "red",
                    "names": [{"etf": "LEVX", "underlying": "BASE"}],
                },
                "hk": {"tier": "green"},
            },
            "breaches": [],
            "hard_stop_watch": [{
                "ticker": "LEVX",
                "breach_id": "risk-hard",
                "detail": "hard stop",
                "action": "swap to BASE",
                "required_reduction": {
                    "kind": "full_leveraged_position",
                    "minimum_shares": 10,
                    "target_tickers": ["LEVX"],
                    "swap_to": "BASE",
                },
            }],
        },
        "quant_signals": {
            "rows": {
                "BASE": {
                    "status": "fresh", "row_as_of": "2026-07-27",
                    "trend_on": False, "rsi14": 28,
                    "dist_ma200_pct": -12, "pct_52w_range": 9,
                    "stop_distance_pct": -2, "tag": "趋势OFF",
                    "note": "LEVX 的标的",
                },
                "00100": {
                    "status": "fresh", "row_as_of": "2026-07-28",
                    "trend_on": True, "rsi14": 55,
                    "dist_ma200_pct": 8, "pct_52w_range": 70,
                    "stop_distance_pct": 5, "tag": "趋势ON",
                },
            }
        },
        "cross_sectional_factor": {
            "activation": {"usable_for_decisions": False},
            "held_rankings": {
                "BASE": {
                    "feature_as_of": "2026-07-27",
                    "composite_score": 0.4,
                    "factor_coverage_pct": 90,
                    "usable_for_decisions": False,
                }
            },
        },
        "peer_residual": {
            "rule_activation": {"active": False},
            "held": {
                "BASE": {
                    "feature_as_of": "2026-07-27",
                    "residual_blend_1d": 0.1,
                    "usable_for_decisions": False,
                }
            },
        },
        "sentiment": {
            "tickers": [{
                "ticker": "BASE",
                "reddit_mentions_7d": 4,
                "news_top": ["headline one", "headline two"],
            }]
        },
        "news_evidence_graph": {
            "events": [{
                "event_id": "evt_good",
                "ticker": "00100",
                "headline": "primary event",
                "actionable_escalation": True,
            }, {
                # Real, reported, but not escalated — the common case. Most
                # events on a given day look like this one, not like evt_good.
                "event_id": "evt_quiet",
                "ticker": "00100",
                "headline": "quarterly results, no escalation",
                "actionable_escalation": False,
            }]
        },
        "integrity": {"ok": True, "error_count": 0, "warn_count": 0},
    }


def _compiled():
    context = _context()
    generation = brief_context.compute_generation_id(context)
    return packet_mod.compile_packet(context, generation)


def _valid_overlay(packet):
    overlay = packet_mod.judgment_template(packet)
    overlay["portfolio_assessment"] = "风险规则优先。"
    overlay["portfolio_counterargument"] = "反方认为超卖可能快速反弹。"
    for row in overlay["ticker_judgments"]:
        row["assessment"] = "结构化信号支持当前判断。"
        row["counterargument"] = "短线可能反向波动。"
        row["rationale"] = "在趋势和风险约束冲突时优先风险。"
    return overlay


def test_compiler_owns_proxy_join_risk_status_and_action_bounds():
    packet = _compiled()
    lev = packet["tickers"]["LEVX"]
    hk = packet["tickers"]["00100"]

    assert lev["technical"]["source_ticker"] == "BASE"
    assert lev["technical"]["is_proxy"] is True
    assert lev["technical"]["rsi_state"] == "oversold"
    assert lev["status"] == {
        "rank": 0, "label": "止损/换1x", "state": "critical",
    }
    assert lev["constraints"]["allowed_actions"] == ["cut"]
    assert lev["constraints"]["max_sell_shares"] == 10

    assert hk["status"]["label"] == "趋势ON"
    assert "cut" in hk["constraints"]["allowed_actions"]
    assert hk["constraints"]["actionable_evidence_ids"] == ["evt_good"]
    assert len(packet_mod._compact(packet).encode()) < packet_mod.MAX_PACKET_BYTES
    assert len(
        json.dumps(packet_mod.summary_view(packet), ensure_ascii=False).encode()
    ) < packet_mod.MAX_QUERY_BYTES


def test_packet_is_deterministic_and_manifest_hash_bound(tmp_path):
    context = _context()
    generation = brief_context.compute_generation_id(context)
    packet = packet_mod.compile_packet(context, generation)
    audit_path = tmp_path / "brief-context-2026-07-28.json"

    stamped, manifest = brief_context.write_run_bundle(
        context,
        audit_path,
        tool_artifacts={"decision_packet": packet},
    )
    manifest_path = Path(manifest["manifest_path"])
    assert packet_mod.read_packet(manifest_path) == packet
    assert brief_context.validate_run_bundle(audit_path, manifest_path) == []
    assert stamped["generation_id"] == generation

    tool_path = Path(manifest["tools"]["decision_packet"]["path"])
    tool_path.write_text(tool_path.read_text() + " ", encoding="utf-8")
    assert any(
        "tool artifact hash" in issue
        for issue in brief_context.validate_run_bundle(audit_path, manifest_path)
    )


def test_judgment_schema_allows_opinions_but_rejects_market_fields():
    packet = _compiled()
    overlay = _valid_overlay(packet)
    assert packet_mod.validate_judgment_overlay(packet, overlay) == []

    overlay["ticker_judgments"][0]["rsi14"] = 28
    issues = packet_mod.validate_judgment_overlay(packet, overlay)
    assert any("unknown fields" in issue and "rsi14" in issue for issue in issues)

    overlay = _valid_overlay(packet)
    overlay["context_generation_id"] = "stale"
    assert any(
        "generation" in issue
        for issue in packet_mod.validate_judgment_overlay(packet, overlay)
    )


def test_invalid_overlay_cannot_corrupt_deterministic_pages_rows(tmp_path):
    packet = _compiled()
    overlay = _valid_overlay(packet)
    overlay["ticker_judgments"][0]["current_price"] = 999999
    overlay_path = tmp_path / "judgment.json"
    output_path = tmp_path / "brief_projection.json"
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")

    projection, issues = packet_mod.write_pages_projection(
        packet, overlay_path, output_path
    )
    assert issues
    assert projection["judgment_status"] == "invalid"
    assert all(row["judgment"] is None for row in projection["tickers"])
    lev = next(row for row in projection["tickers"] if row["ticker"] == "LEVX")
    assert lev["facts"]["pnl_pct"] == -40
    assert lev["status"]["label"] == "止损/换1x"
    assert json.loads(output_path.read_text()) == projection


def test_plan_is_constrained_by_harness_actions_evidence_and_inventory():
    packet = _compiled()
    good = {
        "decisions": [{
            "ticker": "LEVX",
            "action": "cut",
            "driven_by": "risk_rule",
            "evidence_event_id": None,
            "size": {"shares": 10},
        }]
    }
    assert packet_mod.validate_plan_constraints(good, packet) == []

    bad = {
        "decisions": [{
            "ticker": "LEVX",
            "action": "add_only_on_trigger",
            "driven_by": "catalyst",
            "evidence_event_id": "evt_fake",
            "size": {"shares": 11},
        }]
    }
    issues = packet_mod.validate_plan_constraints(bad, packet)
    assert any("allowed_actions" in issue for issue in issues)
    assert any("evidence gate" in issue for issue in issues)


def _catalyst(action, evidence_id, ticker="00100"):
    return {"decisions": [{
        "ticker": ticker,
        "action": action,
        "driven_by": "catalyst",
        "evidence_event_id": evidence_id,
        "size": {},
    }]}


# --- catalyst evidence gate, active vs passive (#342) -----------------------
#
# `actionable_evidence_ids` holds only escalated events, so requiring it of
# EVERY catalyst-driven decision left a passive stance no way to cite a real but
# un-escalated event. On 2026-08-06 all three watched names (CRCL/SKHY/SPCX) had
# 6-7 real events and zero escalated ones, and the only ways past the gate were
# to relabel `driven_by` or drop the id — both destroying the attribution that
# `by_driver` bucketing reads.

def test_passive_catalyst_may_cite_a_real_unescalated_event():
    packet = _compiled()
    assert packet_mod.validate_plan_constraints(
        _catalyst("hold_and_watch", "evt_quiet"), packet) == []


def test_passive_catalyst_still_rejects_an_event_id_that_matches_nothing():
    """Relaxing escalation must not relax the hallucination check."""
    issues = packet_mod.validate_plan_constraints(
        _catalyst("hold_and_watch", "evt_nonexistent"), _compiled())
    assert any("does not match any event" in issue for issue in issues)


def test_active_catalyst_still_requires_an_escalated_event():
    """The escalation gate is the point of the active tier — it must not move."""
    packet = _compiled()
    issues = packet_mod.validate_plan_constraints(_catalyst("cut", "evt_quiet"), packet)
    assert any("evidence gate" in issue for issue in issues)
    assert packet_mod.validate_plan_constraints(_catalyst("cut", "evt_good"), packet) == []


def test_pages_prefers_projection_and_keeps_a_backward_fallback():
    ui = (ROOT / "site" / "assets" / "js" / "dashboard.ui.js").read_text()
    renderer = (ROOT / "site" / "assets" / "js" / "dashboard.render.js").read_text()
    skill = (ROOT / "skills" / "daily-deep-brief" / "SKILL.md").read_text()

    assert 'brief_projection: "drill"' in ui
    assert 'safe(DATA, "brief_projection")' in renderer
    assert "projection.schema_version === 1" in renderer
    assert "projected.length" in renderer
    assert ": holds.map" in renderer
    # The compiled status schema is {rank, label, state}; keep the Pages
    # consumer on the same key so a populated projection cannot print
    # JavaScript's literal "undefined" in the 综合 column.
    assert "${v.label}" in renderer
    assert "${v.txt}" not in renderer
    # Both reads go through package-owned tool contracts; neither requires a
    # Python source file in the KCNyu workspace.
    assert "decision_packet_summary" in skill
    assert "decision_packet_judgment_template" in skill
    assert "禁止加入价格、RSI、MA" in skill
