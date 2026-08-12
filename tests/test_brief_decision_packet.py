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
                    "cash_hkd": 2000,
                    "holdings": [{
                        "ticker": "00100", "name": "Example HK", "shares": 100,
                        "lot_size": 20, "current_value": 1100,
                        "cost_basis": 10, "current_price": 11,
                        "pnl_percent": 10, "today_change_pct": 2,
                        "data_source": "fixture",
                    }, {
                        "ticker": "HK2", "name": "Other HK", "shares": 100,
                        "lot_size": 20, "current_value": 1100,
                        "cost_basis": 10, "current_price": 11,
                        "pnl_percent": 10, "today_change_pct": 0,
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
                    "technical_setups": [{
                        "setup_id": "trend_pullback", "label": "趋势回踩",
                        "campaign_id": "trend_pullback:2026-07-28",
                        "entry_type": "price_above", "entry_price": 11,
                        "invalidation_price": 9.5, "max_tranches": 2,
                        "tranche_pct_of_position": 0.1,
                        "detail": "reclaim",
                    }],
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
        "thesis_registry": {
            "status": "ready",
            "theses": {"00100": {
                "status": "resolved", "thesis_id": "thesis-hk",
                "state": "intact", "checked_at": "2026-07-28T00:00:00Z",
            }},
        },
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
    assert hk["execution"]["lot_size"] == 20
    assert hk["constraints"]["min_tranche_shares"] == 20
    assert hk["constraints"]["max_add_shares"] % 20 == 0
    assert "add_only_on_trigger" in hk["constraints"]["allowed_actions"]
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


def test_technical_add_requires_approved_trigger_and_hk_board_lot():
    packet = _compiled()
    good = {"decisions": [{
        "ticker": "00100", "strategy_id": "tactical_entry",
        "action": "add_only_on_trigger", "driven_by": "technical",
        "evidence_event_id": None,
        "condition": {"type": "price_above", "price": 11},
        "technical_setup_id": "trend_pullback",
        "technical_campaign_id": "trend_pullback:2026-07-28",
        "invalidation_price": 9.5,
        "tranche_number": 1,
        "size": {"shares": 20},
    }]}
    assert packet_mod.validate_plan_constraints(good, packet) == []

    odd_lot = json.loads(json.dumps(good))
    odd_lot["decisions"][0]["size"]["shares"] = 21
    issues = packet_mod.validate_plan_constraints(odd_lot, packet)
    assert any("board-lot multiple" in issue for issue in issues)

    invented = json.loads(json.dumps(good))
    invented["decisions"][0]["condition"]["price"] = 10.5
    issues = packet_mod.validate_plan_constraints(invented, packet)
    assert any("approved technical setup" in issue for issue in issues)


def test_leveraged_or_broken_thesis_never_gets_add_authority():
    context = _context()
    context["quant_signals"]["rows"]["BASE"]["technical_setups"] = [{
        "setup_id": "confirmed_breakout", "label": "breakout",
        "entry_type": "price_above", "entry_price": 12,
        "invalidation_price": 10, "max_tranches": 2,
        "tranche_pct_of_position": 0.1, "detail": "breakout",
    }]
    context["thesis_registry"]["theses"]["00100"]["state"] = "broken"
    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )

    assert not any(
        action.startswith("add_")
        for action in packet["tickers"]["LEVX"]["constraints"]["allowed_actions"]
    )


def test_unknown_registry_leveraged_name_is_blocked_without_a_risk_breach():
    context = _context()
    context["risk_guardrail"]["hard_stop_watch"] = []
    context["quant_signals"]["rows"]["BASE"]["technical_setups"] = [{
        "setup_id": "confirmed_breakout", "label": "breakout",
        "entry_type": "price_above", "entry_price": 12,
        "invalidation_price": 10, "max_tranches": 2,
        "tranche_pct_of_position": 0.1, "detail": "breakout",
    }]

    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )

    assert "leveraged_daily_reset" in packet["tickers"]["LEVX"]["execution"]["blockers"]
    assert not any(
        action.startswith("add_")
        for action in packet["tickers"]["LEVX"]["constraints"]["allowed_actions"]
    )


def test_book_cluster_blocks_adds_only_for_its_target_members():
    context = _context()
    context["risk_guardrail"]["breaches"] = [{
        "type": "factor_concentration", "leg": "BOOK", "severity": "high",
        "detail": "measured cluster", "action": "reduce cluster",
        "required_reduction": {"target_tickers": ["00100"]},
    }]

    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )

    assert "add_only_on_trigger" not in (
        packet["tickers"]["00100"]["constraints"]["allowed_actions"]
    )
    assert packet["tickers"]["HK2"]["risk"] == []


def test_open_add_order_blocks_duplicate_tranche():
    context = _context()
    context["open_decisions"] = {"open": [{
        "ticker": "00100", "action": "add_only_on_trigger",
        "execution_status": "unknown",
    }]}

    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )
    hk = packet["tickers"]["00100"]

    assert "open_add_order" in hk["execution"]["blockers"]
    assert "add_only_on_trigger" not in hk["constraints"]["allowed_actions"]


def test_open_add_ledger_error_blocks_every_new_tranche():
    context = _context()
    context["open_decisions"] = {
        "open_add_tickers": [],
        "open_add_gate_error": "OSError: ledger unreadable",
    }

    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )

    assert "open_add_order" in packet["tickers"]["00100"]["execution"]["blockers"]
    assert "add_only_on_trigger" not in (
        packet["tickers"]["00100"]["constraints"]["allowed_actions"]
    )


def test_completed_tranches_exhaust_setup_authority():
    context = _context()
    context["technical_setup_usage"] = {
        "00100": {"trend_pullback:2026-07-28": 2}
    }

    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )
    setup = packet["tickers"]["00100"]["technical"]["setups"][0]

    assert setup["remaining_tranches"] == 0
    assert setup["next_tranche_number"] is None
    assert "add_only_on_trigger" not in (
        packet["tickers"]["00100"]["constraints"]["allowed_actions"]
    )
    assert not any(
        action.startswith("add_")
        for action in packet["tickers"]["00100"]["constraints"]["allowed_actions"]
    )


def test_add_room_solves_the_post_trade_60_percent_boundary():
    context = _context()
    hk_book = context["portfolio"]["portfolios"]["hk_stocks"]
    hk_book["cash_hkd"] = 10_000
    hk_book["holdings"][0].update(
        shares=100, current_price=5, current_value=500, lot_size=20,
    )
    hk_book["holdings"][1].update(
        shares=100, current_price=5, current_value=500, lot_size=20,
    )

    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )
    execution = packet["tickers"]["00100"]["execution"]

    # (500 + 250) / (1_000 + 250) == 60%; cash is only an affordability cap.
    # Concentration room and one-tranche authority are distinct. The setup only
    # authorizes 10% of the existing 100 shares = one 20-share board lot.
    assert execution["position_room_shares"] == 40
    assert execution["max_add_shares"] == 20
    assert execution["max_tranche_shares"] == 20
    assert (500 + execution["position_room_value"]) / (
        1_000 + execution["position_room_value"]
    ) < 0.60
    next_lot_value = execution["position_room_value"] + 20 * 5
    assert (500 + next_lot_value) / (1_000 + next_lot_value) > 0.60


def test_inactive_and_active_information_only_resize_existing_authority():
    context = _context()
    base = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )["tickers"]["00100"]
    assert base["execution"]["information_overlay"]["sizing_multiplier"] == 1

    context["news_evidence_graph"]["information_overlay"] = {
        "as_of": "2026-07-28T08:00:00+08:00",
        "status": "active", "usable_for_decisions": True,
        "activation": {"blockers": []},
        "tickers": {"00100": {
            "status": "active", "usable_for_decisions": True,
            "signed_score": 0.4, "cross_section_rank": 0.9,
            "sizing_tilt": "positive", "event_count": 2,
        }},
    }
    active = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )["tickers"]["00100"]
    assert active["execution"]["information_overlay"]["sizing_multiplier"] == 1.2
    assert active["constraints"]["max_add_shares"] <= active["constraints"]["position_room_shares"]

    # Removing the setup removes action authority even though information stays high.
    context["quant_signals"]["rows"]["00100"]["technical_setups"] = []
    no_setup = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )["tickers"]["00100"]
    assert "add_only_on_trigger" not in no_setup["constraints"]["allowed_actions"]


def test_plan_provenance_is_replaced_from_generation_bound_packet():
    packet = _compiled()
    plan = {"decisions": [{
        "ticker": "00100",
        "signal_provenance": {"information": {"signed_score": 999}},
    }]}

    bound = packet_mod.bind_plan_provenance(plan, packet)

    provenance = bound["decisions"][0]["signal_provenance"]
    assert provenance["context_generation_id"] == packet["_meta"]["generation_id"]
    assert provenance["information"] == packet["tickers"]["00100"]["information"]
    assert provenance["information"].get("signed_score") != 999


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
