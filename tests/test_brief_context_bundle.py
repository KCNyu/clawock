"""The daily brief's model boundary is budgeted without trimming audit facts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

from clawock import brief_context
from clawock_kcnyu.harness import brief_postflight  # noqa: E402


def test_context_protocol_implementation_is_owned_by_the_product():
    from clawock.decision import packet as brief_decision_packet

    assert {
        Path(module.__file__).relative_to(ROOT).as_posix()
        for module in (brief_context, brief_decision_packet)
    } == {
        "src/clawock/brief_context.py",
        "src/clawock/decision/packet.py",
    }
    assert not any(
        (ROOT / "scripts" / "data" / name).exists()
        for name in ("brief_context.py", "brief_decision_packet.py")
    )


def _fixture():
    return {
        "generated_at": "2026-07-28T08:00:00+08:00",
        "date": "2026-07-28",
        "fx": {"rate": 7.84, "source": "test"},
        "portfolio_path": "portfolio.json",
        "snapshot_path": "memory/snapshots/2026-07-28.json",
        "portfolio": {
            "portfolios": {
                "hk_stocks": {"holdings": [{"ticker": "00100", "shares": 100}]},
                "us_stocks": {"holdings": [{"ticker": "MSFT", "shares": 2}]},
            }
        },
        "book_totals": {"usd_total_pnl": -10},
        "concentration": {"hk": {"hhi": 0.5}, "us": {"hhi": 0.2}},
        "lookthrough_exposure": {"total": 1},
        "risk_guardrail": {"directive": "must preserve", "rules": "R" * 8_000},
        "risk_discipline": {"records": [{"status": "open", "detail": "D" * 8_000}]},
        "integrity": {"ok": True, "findings": []},
        "thesis_registry": {"status": "ok"},
        "research_surface": {"status": "ok", "errors": []},
        "issues": [],
        "breakeven_math": {"rows": [{"ticker": "00100"}]},
        "risk_metrics": {"detail": "X" * 25_000},
        "quant_signals": {"detail": "Q" * 25_000},
        "news_evidence_graph": {
            "as_of": "2026-07-28",
            "events": [{
                "event_id": "evt-1",
                "actionable_escalation": True,
                "detail": "N" * 70_000,
            }],
        },
        "macro": {"detail": "M" * 25_000},
        "retrospective": {"detail": "C" * 25_000},
        "new_feature_surface": {"detail": "E" * 25_000},
    }


def test_same_fixture_reduces_always_loaded_input_and_preserves_action_fields(tmp_path):
    source = _fixture()
    audit_path = tmp_path / "brief-context-2026-07-28.json"

    stamped, manifest = brief_context.write_run_bundle(source, audit_path)
    core = json.loads(Path(manifest["core"]["path"]).read_text())

    assert manifest["budget"]["always_loaded_bytes"] <= 128 * 1024
    assert manifest["budget"]["actual_reduction_pct"] >= 60
    assert manifest["budget"]["target_met"] is True
    for field in brief_context.CORE_FIELDS:
        assert core[field] == stamped[field], field
    assert "new_feature_surface" not in core
    assert manifest["bundles"]["extras"]["fields"] == ["new_feature_surface"]
    assert manifest["bundles"]["evidence"]["freshness"] == {
        "news_evidence_graph": {"as_of": "2026-07-28"}
    }
    assert manifest["bundles"]["evidence"]["summary"][
        "news_evidence_graph"
    ]["actionable_event_ids"] == ["evt-1"]
    assert Path(manifest["audit"]["path"]).parent.name == stamped["generation_id"]
    assert brief_context.validate_run_bundle(
        audit_path, Path(manifest["manifest_path"])
    ) == []


def test_new_optional_feature_cannot_grow_the_always_loaded_core(tmp_path):
    baseline = _fixture()
    baseline.pop("new_feature_surface")
    _, before = brief_context.write_run_bundle(
        baseline, tmp_path / "before.json"
    )
    baseline["another_feature"] = {"rows": ["z" * 25_000]}
    _, after = brief_context.write_run_bundle(
        baseline, tmp_path / "after.json"
    )

    assert after["core"]["bytes"] == before["core"]["bytes"]
    assert after["bundles"]["extras"]["fields"] == ["another_feature"]


def test_new_feature_cannot_silently_create_an_unbounded_lazy_load(tmp_path):
    source = _fixture()
    source["new_feature_surface"] = {"rows": ["z" * 100_000]}

    with pytest.raises(ValueError, match="lazy bundle exceeds per-load budget"):
        brief_context.write_run_bundle(source, tmp_path / "bundle-oversize.json")


def test_tool_artifact_cannot_create_an_unbounded_query_source(tmp_path):
    source = _fixture()
    generation_id = brief_context.compute_generation_id(source)
    tool = {
        "_meta": {
            "schema_version": 1,
            "kind": "test",
            "generation_id": generation_id,
        },
        "payload": "T" * (brief_context.SINGLE_BUNDLE_BUDGET_BYTES + 1),
    }
    with pytest.raises(ValueError, match="tool artifact exceeds"):
        brief_context.write_run_bundle(
            source,
            tmp_path / "tool-oversize.json",
            tool_artifacts={"test": tool},
        )


def test_action_critical_growth_fails_the_final_boundary(tmp_path):
    source = _fixture()
    source["portfolio"]["raw_history"] = "P" * (140 * 1024)

    with pytest.raises(ValueError, match="always-loaded context exceeds budget"):
        brief_context.write_run_bundle(source, tmp_path / "oversize.json")


def test_bundle_read_and_postflight_reject_cross_generation(tmp_path):
    stamped, manifest = brief_context.write_run_bundle(
        _fixture(), tmp_path / "brief.json"
    )
    manifest_path = Path(manifest["manifest_path"])
    research = json.loads(brief_context.read_artifact(manifest_path, "research"))
    assert research["_meta"]["generation_id"] == stamped["generation_id"]

    good = {
        "context_generation_id": stamped["generation_id"],
        "decisions": [{"source_generation_id": stamped["generation_id"]}],
    }
    assert brief_postflight.validate_generation_references(good, stamped) == []

    bad = {
        "context_generation_id": stamped["generation_id"],
        "decisions": [{"source_generation_id": "older-run"}],
    }
    issues = brief_postflight.validate_generation_references(bad, stamped)
    assert any("跨代引用" in issue for issue in issues)


def test_tampered_bundle_is_detected(tmp_path):
    _, manifest = brief_context.write_run_bundle(
        _fixture(), tmp_path / "brief.json"
    )
    bundle = Path(manifest["bundles"]["evidence"]["path"])
    bundle.write_text(bundle.read_text() + " ")

    issues = brief_context.validate_run_bundle(
        tmp_path / "brief.json", Path(manifest["manifest_path"])
    )
    assert any("hash 不匹配" in issue for issue in issues)
