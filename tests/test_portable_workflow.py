"""High-cost invariants unique to the investment decision workflow."""
import copy
import json

from clawock.workflows import load_workflow, validators_for


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
