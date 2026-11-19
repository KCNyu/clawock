"""The compact brief cannot hide deterministic early-positioning hints."""
import json

from clawock.harness import brief_card as common


TODAY = "2026-08-13"


def _packet():
    return {
        "add_alpha_diagnostics": {
            "candidates": [{
                "ticker": "00100", "source_ticker": "00100", "is_proxy": False,
                "tier": "none", "allowed": False,
                "early_trend": {
                    "observed": True, "exploration_ready": False,
                    "state": "wait_pullback_rebreak",
                    "blockers": ["needs_primary_evidence", "overheated_wait_rebreak"],
                },
            }, {
                "ticker": "SPCX", "source_ticker": "SPCX", "is_proxy": False,
                "tier": "none", "allowed": False,
                "early_trend": {
                    "observed": True, "exploration_ready": False,
                    "state": "wait_information",
                    "blockers": ["needs_information_confirmation", "needs_primary_evidence"],
                },
            }, {
                "ticker": "SPCH", "source_ticker": "SPCX", "is_proxy": True,
                "tier": "none", "allowed": False,
                "early_trend": {
                    "observed": True, "exploration_ready": False,
                    "state": "candidate_only",
                    "blockers": ["leveraged_requires_validated_evidence"],
                },
            }],
        },
    }


def test_rich_card_gets_a_deterministic_deduplicated_candidate_section(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(common, "WS", tmp_path)
    card = tmp_path / "memory" / ".tmp" / f"brief-card-{TODAY}.txt"
    card.parent.mkdir(parents=True)
    card.write_text(
        "📊 盘前深度简报\n\n▎提前布局候选\n模型遗漏的旧文字\n\n📈 完整报告：link",
        encoding="utf-8",
    )

    result = common.build_brief_card(TODAY, decision_packet=_packet())

    # An older card file's ▎ header is replaced by the current section.
    assert result.count("提前布局候选") == 1
    assert "早期趋势信号 2 个底层 · 其中可试探 0" in result
    assert "SPCX（SPCH 映射）" in result
    assert "模型遗漏的旧文字" not in result
    assert "缺一手披露" in result


def test_plan_fallback_also_reports_zero_candidate_truth(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "WS", tmp_path)
    plan = tmp_path / "memory" / f"{TODAY}-plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps({"decisions": []}), encoding="utf-8")
    packet = {"add_alpha_diagnostics": {"candidates": []}}

    result = common.build_brief_card(TODAY, decision_packet=packet)

    assert "早期趋势信号 0 个底层 · 其中可试探 0" in result
    assert "登记策略允许条件买腿 0 票" in result
    assert result.index("**提前布局候选**") < result.index("完整报告：")


def test_the_card_names_the_version_it_was_delivered_as(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "WS", tmp_path)
    card = tmp_path / "memory" / ".tmp" / f"brief-card-{TODAY}.txt"
    card.parent.mkdir(parents=True)
    card.write_text("📊 盘前深度简报\n\n完整报告：link", encoding="utf-8")

    result = common.build_brief_card(
        TODAY, decision_packet={"add_alpha_diagnostics": {"candidates": []}},
        version={"id": "v2-8d1e0f2a"})

    assert "本卡版本 v2-8d1e0f2a" in result
    assert result.rstrip().endswith("本卡版本 v2-8d1e0f2a")
    # The version line must not replace or prefix the report link.
    assert "完整报告：link" in result


def test_a_card_without_a_version_keeps_its_old_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "WS", tmp_path)
    result = common.build_brief_card(
        TODAY, decision_packet={"add_alpha_diagnostics": {"candidates": []}})

    assert "本卡版本" not in result


def test_conditional_buy_legs_do_not_create_early_signals():
    rows = [
        {"ticker": "03033", "allowed": True, "tier": "user_experiment",
         "state": "eligible", "max_add_shares": 200},
        {"ticker": "SPCX", "allowed": False, "tier": "user_experiment",
         "state": "risk_blocked", "max_add_shares": 1},
        {"ticker": "RKLB", "allowed": True, "tier": "none"},
    ]
    for row in rows:
        row["early_trend"] = {"observed": False, "state": "not_candidate"}
    result = common._early_candidate_section({"add_alpha_diagnostics": {"candidates": rows}})
    assert "早期趋势信号 0 个底层" in result
    assert "登记策略允许条件买腿 2 票" in result
    assert "03033 200 股" in result
    assert "not_candidate" not in result
    assert "SPCX" not in result
