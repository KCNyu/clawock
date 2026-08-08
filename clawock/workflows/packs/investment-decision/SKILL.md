---
name: investment-decision
description: Produce an evidence-linked investment decision with an explicit bull case, opposing bear case, thesis invalidation conditions, bounded action, and reconciled order/FX amounts. Use when an agent must analyze a security or portfolio action and publish a verifiable decision artifact through clawock.
---

# Investment decision workflow

Use this workflow inside the current agent runtime. Do not launch another agent
or model through clawock: the current runtime owns research, conversation,
memory, skills, tools, repair loops, and permissions.

## Run

1. Run `clawock run prepare --workspace <workspace>` and retain the printed
   `request_file`, `run_id`, `generation_id`, workflow version, and certified
   context.
2. Research with the current runtime's normal tools. Collect traceable evidence
   observed no later than the decision's `as_of` time.
3. Write `decision.json` using
   [the decision contract](references/decision-contract.md) and its linked JSON
   Schema. Include at least one
   supporting and one opposing evidence item. The bull and bear cases must cite
   their evidence rather than merely asserting conclusions.
4. State thesis invalidation conditions before choosing an action. A high
   confidence decision must cite primary evidence.
5. If the action contains an order intent, calculate quote-currency gross amount
   as quantity times unit price, then calculate base-currency gross amount using
   the stated FX rate. Do not estimate either total in prose.
6. Publish with:

   `clawock run publish --workspace <workspace> --request <request_file> --artifact decision.json=<workspace>/decision.json`

7. If publication is rejected, repair only the named artifact issues and retry
   against the same prepared request. Re-run prepare if its context or workflow
   certificate changed.

The final receipt is the proof that one workflow version, certified context, and
artifact generation passed the deterministic gates. It is supporting evidence,
not a substitute for the decision itself.
