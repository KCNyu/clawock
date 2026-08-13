"""The compact brief cannot hide deterministic early-positioning hints."""
import json

from clawock.harness import _watchdog_common as common


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

    assert result.count("▎提前布局候选") == 1
    assert "提示 2 个底层机会 · 可小仓试探 0 · 当前可加仓 0" in result
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

    assert "提示 0 个底层机会 · 可小仓试探 0 · 当前可加仓 0" in result
    assert "不是“模型没写”" in result
    assert result.index("▎提前布局候选") < result.index("📈 完整报告")
