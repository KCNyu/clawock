"""High-value evidence, review and rollback invariants for workflow learning."""
import json

import pytest

from clawock.harness.config import initialize
from clawock.workflows import (
    apply_proposal,
    create_proposal,
    evaluate_files,
    load_workflow,
    review_proposal,
    rollback_change,
)


def _resource(name):
    return load_workflow("investment-decision").resource.joinpath(
        "assets", name
    ).read_text()


def _workspace(tmp_path):
    root = tmp_path / "workspace"
    initialize(root, workflow="investment-decision")
    return root


def _evaluation(tmp_path):
    decision = tmp_path / "decision.json"
    outcome = tmp_path / "outcome.json"
    decision.write_text(_resource("decision.example.json"))
    outcome.write_text(_resource("outcome.example.json"))
    return evaluate_files("investment-decision", decision, outcome)


def _write(path, payload):
    path.write_text(json.dumps(payload))
    return path


def test_outcome_reconciles_quote_and_fx_adjusted_base_returns(tmp_path):
    result = _evaluation(tmp_path)

    assert result["measurements"] == {
        "quote_currency": "USD",
        "base_currency": "HKD",
        "quote_market_move_bps": "200.00",
        "base_market_move_bps": "213.08",
        "decision_value_bps": "0.00",
    }
    assert "not realized portfolio P&L" in result["interpretation"]


def test_rejected_proposal_cannot_mutate_workflow_parameters(tmp_path):
    workspace = _workspace(tmp_path)
    trigger = _write(tmp_path / "evaluation.json", _evaluation(tmp_path))
    proposal = create_proposal(
        workspace,
        trigger,
        {"min_opposing_evidence": 2},
        rationale="One opposing source was too brittle.",
        expected_effect="Require independent opposition.",
    )
    proposal_path = _write(tmp_path / "proposal.json", proposal)
    review_path = _write(tmp_path / "review.json", review_proposal(
        proposal_path,
        disposition="rejected",
        reviewer="risk-owner",
        note="One outcome is insufficient evidence for a policy change.",
    ))
    before = (workspace / "clawock.json").read_text()

    with pytest.raises(ValueError, match="explicitly accepted"):
        apply_proposal(workspace, proposal_path, review_path)

    assert (workspace / "clawock.json").read_text() == before
    assert not (workspace / ".clawock/improvements/history.jsonl").exists()


def test_accepted_parameter_change_restores_exact_config_on_rollback(tmp_path):
    workspace = _workspace(tmp_path)
    original = (workspace / "clawock.json").read_text()
    trigger = _write(tmp_path / "evaluation.json", _evaluation(tmp_path))
    proposal = create_proposal(
        workspace,
        trigger,
        {"min_opposing_evidence": 2},
        rationale="Measured evidence supports a bounded stricter trial.",
        expected_effect="Require two distinct opposing observations.",
    )
    proposal_path = _write(tmp_path / "proposal.json", proposal)
    review_path = _write(tmp_path / "review.json", review_proposal(
        proposal_path,
        disposition="accepted",
        reviewer="risk-owner",
        note="Accept one reversible parameter-only trial.",
    ))

    change = apply_proposal(workspace, proposal_path, review_path)
    updated = json.loads((workspace / "clawock.json").read_text())
    assert updated["workflow_parameters"] == {"min_opposing_evidence": 2}

    rollback_change(workspace, change["change_id"])

    assert (workspace / "clawock.json").read_text() == original
    history = [
        json.loads(line)
        for line in (workspace / ".clawock/improvements/history.jsonl").read_text().splitlines()
    ]
    assert [event["kind"] for event in history] == [
        "workflow-improvement-change", "workflow-improvement-rollback"
    ]
