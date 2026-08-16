"""Contracts for harness-owned analysis and the Pages projection boundary."""
from __future__ import annotations

import json
import sys
import copy
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
        row["falsifier"] = "突破失效或一手证据转负。"
        row["next_evidence"] = "下一时段价格确认与发行人披露。"
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
    assert hk["quant"]["add_authority"]["tier"] == "none"
    assert len(packet_mod._compact(packet).encode()) < packet_mod.MAX_PACKET_BYTES
    assert len(
        json.dumps(packet_mod.summary_view(packet), ensure_ascii=False).encode()
    ) < packet_mod.MAX_QUERY_BYTES


def _exploration_context():
    """Context where 00100 reaches `exploration` authority through the
    factor/peer/information payloads (used by the #666 zero-value contract)."""
    context = _context()
    context["cross_sectional_factor"] = {
        "activation": {"usable_for_decisions": False},
        "live_rankings": {"00100": {
            "feature_as_of": "2026-07-28", "market_percentile": 0.9,
            "sector_universe_size": 6, "factor_coverage_pct": 95,
            "usable_for_decisions": False,
        }},
    }
    context["peer_residual"] = {
        "rule_activation": {},
        "live": {"00100": {
            "feature_as_of": "2026-07-28",
            "triggered_rules": ["leader_continuation"],
            "available_peer_count": 5, "usable_for_decisions": False,
        }},
    }
    context["news_evidence_graph"]["information_overlay"] = {
        "as_of": "2026-07-28T08:00:00+08:00",
        "status": "warming_up", "usable_for_decisions": False,
        "activation": {"blockers": ["history_dates"]},
        "tickers": {"00100": {
            "status": "warming_up", "usable_for_decisions": False,
            "signed_score": 0.12, "attention_rank": 0.9,
            "attention_acceleration": 2.0, "attention_event_count": 1,
            "attention_source_type_count": 1,
            "attention_components": [{"event_id": "attention-1"}],
            "event_components": [{
                "event_id": "positive-1", "direction": 1,
                "novelty": 1, "reliability": 0.9,
                "price_nonreaction": 1,
            }],
        }},
    }
    context["quant_signals"]["rows"]["00100"].update(
        close=11, ma20=10, prior_5d_high=11.2, prior_5d_low=9.5,
        chandelier_stop=9.8,
    )
    return context


def test_production_factor_and_peer_keys_reach_add_authority():
    context = _exploration_context()

    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )
    row = packet["tickers"]["00100"]

    assert row["quant"]["add_authority"]["tier"] == "exploration"
    assert row["quant"]["add_authority"]["evidence_families"] == [
        "price_relative", "point_in_time_information",
    ]
    assert any(
        setup["setup_id"] == "alpha_confirmation"
        for setup in row["technical"]["setups"]
    )
    # This 20-share lot is 10% of the tiny fixture book, above the separate 3%
    # hard exploration envelope, so it may not masquerade as a 2.5% sample.
    assert row["execution"]["max_add_shares"] == 0
    assert "tranche_below_market_unit" in row["execution"]["blockers"]


def test_exploration_max_book_pct_zero_means_zero_exploration_budget():
    """#666: `exploration_max_book_pct: 0` (0 = 封死探索敞口) is legal config;
    `X or DEFAULT` would silently swallow it into 0.03."""
    context = _exploration_context()
    add_policy = json.loads(
        (ROOT / "config" / "add-alpha-policy.json").read_text(encoding="utf-8"))
    add_policy["exploration_max_book_pct"] = 0
    context["add_alpha_policy"] = add_policy

    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )
    execution = packet["tickers"]["00100"]["execution"]

    assert execution["exploration_budget_value"] == 0.0
    assert execution["max_add_value"] == 0


def test_one_us_share_can_collect_exploration_inside_the_hard_book_cap():
    execution = packet_mod._execution_view(
        {"shares": 2, "current_price": 100, "current_value": 200},
        "US", 10_000, 1_000,
        {"setups": [{"tranche_pct_of_position": 0.025}]},
        {"state": "unknown"}, False,
        authority_tier="exploration", exploration_max_book_pct=0.03,
    )

    assert execution["max_add_shares"] == 1
    assert execution["max_add_value"] == 100


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


def test_judgment_can_downgrade_but_cannot_invent_a_candidate():
    packet = _compiled()
    overlay = _valid_overlay(packet)
    lev = next(row for row in overlay["ticker_judgments"] if row["ticker"] == "LEVX")
    lev["disposition"] = "candidate"

    issues = packet_mod.validate_judgment_overlay(packet, overlay)

    assert any("cannot upgrade" in issue for issue in issues)


def test_judgment_rejects_a_deterministic_candidate_without_removing_the_hint():
    context = _context()
    context["quant_signals"]["rows"]["00100"].update({
        "trend_on": None, "close": 11, "prior_20d_high": 10, "zscore20": 1,
    })
    context["peer_residual"]["held"]["00100"] = {
        "feature_as_of": "2026-07-28", "residual_blend_5d": .2,
        "peer_dispersion_5d": .05, "available_peer_count": 4,
    }
    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )
    overlay = _valid_overlay(packet)
    hk = next(row for row in overlay["ticker_judgments"] if row["ticker"] == "00100")
    hk["disposition"] = "reject"

    assert packet_mod.validate_judgment_overlay(packet, overlay) == []
    projection = packet_mod.compile_pages_projection(packet, overlay)
    row = next(row for row in projection["tickers"] if row["ticker"] == "00100")
    candidate = next(
        row for row in projection["add_campaign"]["candidates"]
        if row["ticker"] == "00100"
    )
    assert row["candidate_disposition"]["effective"] == "reject"
    assert candidate["early_trend"]["observed"] is True


def test_short_history_is_unknown_not_trend_off():
    context = _context()
    context["quant_signals"]["rows"]["00100"].update({
        "trend_on": None, "tag": "趋势OFF · z+2.1σ极端",
    })

    row = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )["tickers"]["00100"]

    assert row["technical"]["trend"] == "unknown"
    assert "趋势未知" in row["technical"]["tag"]
    assert row["status"]["label"] == "趋势未知·短历史"


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


def test_pages_projection_exposes_add_campaign_without_raw_run_card_inputs():
    context = _context()
    context["cross_sectional_factor"] = {
        "activation": {"usable_for_decisions": False},
        "live_rankings": {"00100": {
            "feature_as_of": "2026-07-28", "market_percentile": 0.9,
            "sector_universe_size": 6, "factor_coverage_pct": 95,
            "usable_for_decisions": False,
        }},
    }
    context["news_evidence_graph"]["information_overlay"] = {
        "as_of": "2026-07-28T08:00:00+08:00", "status": "warming_up",
        "usable_for_decisions": False, "activation": {"blockers": []},
        "tickers": {"00100": {
            "status": "warming_up", "usable_for_decisions": False,
            "signed_score": 0.2, "event_components": [{
                "event_id": "positive-1", "direction": 1, "novelty": 1,
                "reliability": 0.9, "price_nonreaction": 1,
            }],
        }},
    }
    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )
    card = {
        "run_id": "add_alpha_walkforward-fixture", "generated_at": "now",
        "reproduction_key": "sha256:fixture", "inputs": [{"raw": "vendor"}],
        "params": {"policy_version": 2, "parameter_fit": "none"},
        "metrics": {
            "us": {"interaction": {
                "t1": {"n": 4, "n_dates": 4, "n_tickers": 1,
                       "mean_return": 0.03, "hit_rate": 1, "status": "collecting"},
                "t5": {"n": 0, "status": "collecting"},
                "t20": {"n": 0, "status": "collecting"},
            }},
            "hk": {"interaction": {
                horizon: {"n": 0, "status": "collecting"}
                for horizon in ("t1", "t5", "t20")
            }},
            "coverage": {
                "factor_dates": 11, "information_dates": 12,
                "overlap_dates": 10, "prospective_information_dates": 0,
                "authority_classifications": {"none": 186, "exploration": 6,
                                               "validated": 0},
                "claim": "diagnostic_not_validated_alpha",
                "early_trend": {"observed_candidates": 5},
            },
            "early_trend": {
                "us": {"observed": {
                    "t1": {"n": 3, "mean_return": .02, "hit_rate": .67,
                           "status": "collecting"},
                    "t5": {"n": 2, "mean_return": .04, "hit_rate": 1,
                           "status": "collecting"},
                }},
                "hk": {"observed": {
                    "t1": {"n": 1, "mean_return": -.01, "hit_rate": 0,
                           "status": "collecting"},
                    "t5": {"n": 0, "status": "collecting"},
                }},
            },
        },
    }

    projection = packet_mod.compile_pages_projection(
        packet, add_alpha_run_card=card
    )
    campaign = projection["add_campaign"]
    assert campaign["status"] == "current"
    assert campaign["diagnostics"]["held_names"] == 3
    assert [row["ticker"] for row in campaign["candidates"]] == [
        "00100", "HK2", "LEVX",
    ]
    hk = next(row for row in campaign["candidates"] if row["ticker"] == "00100")
    assert "price_relative" in hk["evidence_families"]
    assert set(hk) >= {
        "state", "tier", "source_ticker", "is_proxy", "sources", "evidence_families",
        "authority_blockers", "execution_blockers", "entry_price",
        "invalidation_price", "target_tranche_level", "max_add_shares",
    }
    run_card = campaign["run_card"]
    assert run_card["markets"]["us"]["t1"]["n"] == 4
    assert run_card["markets"]["hk"]["t20"]["status"] == "collecting"
    assert run_card["coverage"]["prospective_information_dates"] == 0
    assert run_card["coverage"]["early_trend"]["observed_candidates"] == 5
    assert run_card["early_trend"]["us"]["observed"]["t1"]["n"] == 3
    assert "inputs" not in run_card


def test_candidate_diagnostics_deduplicate_proxy_and_underlying_as_one_idea():
    context = _context()
    context["portfolio"]["portfolios"]["us_stocks"]["holdings"].append({
        "ticker": "BASE", "name": "Underlying", "shares": 10,
        "cost_basis": 10, "current_price": 11, "current_value": 110,
    })
    for ticker in ("BASE",):
        context["quant_signals"]["rows"][ticker] = {
            "status": "fresh", "row_as_of": "2026-07-28", "trend_on": None,
            "close": 11, "prior_20d_high": 10, "zscore20": 2.1,
        }
    context["peer_residual"]["held"]["BASE"] = {
        "feature_as_of": "2026-07-28", "residual_blend_5d": .2,
        "peer_dispersion_5d": .05, "available_peer_count": 4,
    }

    diagnostics = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )["add_alpha_diagnostics"]

    assert diagnostics["observed_candidate_count"] == 2
    assert diagnostics["observed_idea_count"] == 1


def test_early_exploration_reports_its_real_tranche_and_evidence_families():
    context = _context()
    context["quant_signals"]["rows"]["00100"].update({
        "trend_on": None, "close": 11, "prior_20d_high": 10,
        "prior_5d_low": 9.5, "ma20": 10, "zscore20": 1,
    })
    context["peer_residual"]["held"]["00100"] = {
        "feature_as_of": "2026-07-28", "residual_blend_5d": .2,
        "peer_dispersion_5d": .05, "available_peer_count": 4,
    }
    context["news_evidence_graph"]["events"][0].update({
        "source_type": "issuer_announcement", "impact_direction": "positive",
    })
    packet = packet_mod.compile_packet(
        context, brief_context.compute_generation_id(context)
    )
    row = next(
        row for row in packet["add_alpha_diagnostics"]["candidates"]
        if row["ticker"] == "00100"
    )

    assert row["state"] == "exploration_ready"
    assert row["target_tranche_level"] == .25
    assert row["evidence_families"] == [
        "point_in_time_information", "price_relative",
    ]
    assert row["entry_price"] == 11


def test_pages_projection_names_a_packet_that_predates_add_policy():
    packet = _compiled()
    packet.pop("add_alpha_diagnostics")
    packet.pop("add_alpha_policy")

    campaign = packet_mod.compile_pages_projection(packet)["add_campaign"]

    assert campaign["status"] == "pre_policy_packet"
    assert campaign["diagnostics"] is None
    assert campaign["candidates"] == []


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

    assert "leveraged_requires_validated_evidence" in (
        packet["tickers"]["LEVX"]["execution"]["blockers"]
    )
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
    assert provenance["early_trend"] == (
        packet["tickers"]["00100"]["quant"]["early_trend"]
    )


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
    assert "const projectedByTicker = new Map" in renderer
    assert "const enriched = holds.map" in renderer
    assert "projectedByTicker.get(h.ticker)" in renderer
    assert "(h.shares ?? 0) > 0" in renderer
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
