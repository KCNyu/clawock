"""High-cost invariants unique to the investment decision workflow."""
from pathlib import Path

import copy
import json

from clawock.workflows import (
    load_workflow,
    render_workflow_schema,
    validators_for,
)

PLUGIN_CONTRACT_TWIN = (
    Path(__file__).resolve().parents[1]
    / "examples" / "dsh" / "packages" / "clawock-dsh"
    / "skills" / "investment-decision" / "references" / "decision-contract.md"
)


def _example():
    pack = load_workflow("investment-decision")
    return json.loads(
        pack.resource.joinpath("assets/decision.example.json").read_text()
    )


def _codes(document):
    contract = load_workflow("investment-decision").contract()
    validator = validators_for(contract)[0]
    return {
        issue.code
        for issue in validator.validate({"decision.json": json.dumps(document)})
    }


def test_an_opposing_case_is_code_enforced_not_prompt_advice():
    decision = _example()
    decision["evidence"] = [
        row for row in decision["evidence"] if row["stance"] != "opposing"
    ]
    decision["debate"]["bear_case"]["evidence_ids"] = ["filing-growth"]

    codes = _codes(decision)

    assert "insufficient_opposing_evidence" in codes
    assert "unsupported_bear_case" in codes


def test_order_and_fx_totals_are_reconciled_to_currency_cents():
    decision = copy.deepcopy(_example())
    decision["decision"].update({
        "action": "buy",
        "order": {
            "side": "buy",
            "quantity": "3",
            "unit_price": "10.25",
            "quote_currency": "USD",
            "gross_amount_quote": "30.75",
            "base_currency": "HKD",
            "fx_quote_to_base": "7.8",
            "gross_amount_base": "999.99"
        },
    })

    codes = _codes(decision)

    assert "gross_amount_mismatch" not in codes
    assert "fx_amount_mismatch" in codes


def test_codex_schema_is_a_relaxed_projection_not_the_final_validator():
    canonical = render_workflow_schema(
        "investment-decision", "decision.json", dialect="canonical"
    )
    codex = render_workflow_schema(
        "investment-decision", "decision.json", dialect="codex"
    )
    serialized = json.dumps(codex)

    assert canonical["properties"]["decision"]["properties"][
        "evidence_ids"
    ]["uniqueItems"] is True
    assert "uniqueItems" not in serialized
    assert "minLength" not in serialized
    assert "oneOf" not in serialized
    assert '"const"' not in serialized
    assert codex["properties"]["schema_version"]["enum"] == [1]
    assert "anyOf" in codex["properties"]["decision"]["properties"]["order"]

    # Relaxing the model-facing schema must not relax clawock's own gate.
    invalid = _example()
    invalid["decision"]["evidence_ids"] = ["filing-growth", "filing-growth"]
    assert "duplicate_evidence_reference" in _codes(invalid)


def test_the_dsh_plugin_contract_twin_tracks_the_pack_copy():
    """The decision contract ships twice on purpose: once in the wheel pack
    that `clawock workflow install` copies into workspaces, once inside the
    npm plugin package. Both teach the same contract the same validators.py
    enforces, so they must not diverge — and they have before: #646 had to
    hand-patch both trees because the prose taught fields publish rejects.

    No build step shares the two files, so this pin is the only thing that
    turns a silent fork into a required-check failure. If divergence is ever
    deliberate, edit both copies consciously and relax this test in the same
    commit with a reason.
    """
    pack_copy = load_workflow("investment-decision").resource.joinpath(
        "references/decision-contract.md"
    )
    assert pack_copy.is_file(), f"pack contract missing: {pack_copy}"
    assert PLUGIN_CONTRACT_TWIN.is_file(), (
        f"plugin package contract missing: {PLUGIN_CONTRACT_TWIN}"
    )
    assert PLUGIN_CONTRACT_TWIN.read_bytes() == pack_copy.read_bytes(), (
        "the two shipped copies of references/decision-contract.md diverged:\n"
        f"  pack:   {pack_copy}\n"
        f"  plugin: {PLUGIN_CONTRACT_TWIN}\n"
        "Both teach one contract enforced by one validator. Copy the edited "
        "side over the other (or, if the audiences truly need different docs, "
        "consciously relax this pin with a reason in the same commit)."
    )
