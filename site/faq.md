---
layout: default
title: clawock FAQ
lang: en
description: Answers to the questions new users ask about clawock — an open-source, agent-native investment decision workflow with a public self-graded scorecard on a real HK + US account.
---

# FAQ

## What is clawock?

clawock is an open-source, **agent-native investment decision-workflow engine**
with a verifiable harness. It is not a trading bot and not a copy-trading
service: an external agent runtime (Claude Code, Codex, OpenClaw, DeepSeek
Harness, or your own) owns the model and tools, while clawock owns the decision
contract — certified evidence, a mandatory opposing case, deterministic money
and FX reconciliation, and a public scorecard.

It is also the first continuously running proof: a real Hong Kong + US
brokerage account has run it from launch, with every judgment settled by
Python and published — losses included.

## Is this an AI trading bot that makes money?

No, and it says so itself. The live account return is published on the
dashboard — currently negative — and active recommendations have **not beaten
buy-and-hold**. Directional hit rates carry 95% confidence intervals that
straddle 50% — statistically not an edge yet. The project's claim is not "makes
money", it is "**can't be fooled**": the model proposes, Python settles, and the
model can never grade itself. Use it as a measurable, auditable baseline — not
as a get-rich signal.

## Why would I install it if it doesn't beat buy-and-hold?

Three things it delivers today:

1. A daily 08:00 brief with a chain of evidence, delivered to WeChat;
2. An audit framework where every decision can be recomputed and checked
   (`clawock audit-resettle`, `clawock reconcile`, `clawock integrity`);
3. An honest baseline — any future strategy or agent can be compared against
   the live, publicly settled record.

It does not promise "earn"; it promises "every call has a paper trail".

## How is the scorecard different from other AI trading projects?

- **The model can't grade itself.** LLMs propose trades; Python settles them
  from canonical vendor bars on each market's own calendar.
- **No cherry-picking.** The raw ledger (`memory/decisions.jsonl`) is public;
  "if a number doesn't reproduce, we lose."
- **One thesis counts once.** Repeated restatements collapse into one episode,
  so holding a position for five mornings doesn't manufacture five samples.
- **Human-in-the-loop is disclosed.** Follow-through decisions belong to the
  account owner; every followed/not-followed entry carries a source. Until the
  follow-rule set is published for audit, account return is labeled
  human-in-the-loop performance, not model performance.

## Which agent frameworks does it work with?

Any harness that can read a file and write `decision.json`: Claude Code,
Codex, OpenClaw, DeepSeek Harness, or a plain CLI. The contract is files and a
CLI — swap harnesses and the workflow does not move. See
[examples](https://github.com/KCNyu/clawock/tree/master/examples)
for the same run driven from five harnesses.

## Does it work with DeepSeek Harness?

Yes. A skill package is published on npm as `clawock-dsh`; install it with
`dsh plugin --profile web add clawock-dsh`. The agent then follows the same
prepare → `decision.json` → publish loop, with the model call staying entirely
in your runtime.

## How do I install it?

```bash
python -m pip install clawock
clawock workflow install investment-decision --workspace ./my-decision
clawock init ./my-decision --workflow investment-decision
clawock run prepare --workspace ./my-decision
```

Or hand the repository URL to your agent and let it run
`bash examples/cli/minimal-run/run.sh` first — a no-model proof of one complete
decision loop that needs no credentials and no broker (the one network step is
installing clawock from PyPI). Model costs ride on your own API key; clawock itself is
free and open source (MIT).

## Where does the data come from?

41 fetch and compute modules across 8 layers: Tencent, Yahoo, Eastmoney,
Polygon, SEC EDGAR, HKEX, Finnhub, Frankfurter, Reddit, Google News and more —
bilingual HK + US coverage, with multi-source fallback on critical paths. The
influencer radar scans Trump (Truth Social primary feed) and Musk (news
aggregation) twice every trading day over a rolling 48-hour lookback window
(so weekend statements still surface before Monday's brief), links statements
to your holdings, and records misses as well as hits.

## Why is it open source? What's the catch?

The system was already running — this is the author's own real account, with
the author's own money. Open-sourcing is how the ledger and the workflow are
kept honest. There is no paid tier, no advisory group, no copy-trading
subscription; whether you install it has no effect on the author's income.

## Is this investment advice?

No. The repository contains real trading positions and is a personal record
and portable workspace — not investment advice, not a recommendation, and not
a copy-trading system. Every number may be stale by the time you read it.
