<div align="center">

<h1><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/logo-lockup.svg" alt="clawock" height="48"></h1>

### AI argues. Code settles. The losses stay on the page.

[![PyPI](https://img.shields.io/pypi/v/clawock?label=PYPI&style=flat-square&logo=pypi&logoColor=white&labelColor=252b35&color=4b91c8)](https://pypi.org/project/clawock/)
[![npm](https://img.shields.io/npm/v/clawock-dsh?label=NPM&style=flat-square&logo=npm&logoColor=white&labelColor=252b35&color=4b91c8)](https://www.npmjs.com/package/clawock-dsh)
[![Tests](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/ci.yml?label=TESTS&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/ci.yml)
[![Live Data](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/dashboard-artifact-gate.yml?label=DATA&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/dashboard-artifact-gate.yml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fkcnyu.github.io%2Fclawock%2Fassets%2Fdata%2Fcoverage.json&style=flat-square&logo=python&logoColor=white&labelColor=252b35)](https://github.com/KCNyu/clawock/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-aab5bf?style=flat-square&labelColor=252b35)](https://github.com/KCNyu/clawock/blob/master/LICENSE)

[**Live dashboard**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**Daily briefs**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**Evidence**](https://kcnyu.github.io/clawock/#reflect) &nbsp;·&nbsp; [**简体中文**](https://github.com/KCNyu/clawock/blob/master/README.zh.md)

<a href="https://kcnyu.github.io/clawock/">
  <img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/social-card.png" alt="clawock — portable investment decision workflows for any external AI agent, proven on a live HK and US desk" width="820">
</a>

<sub><i>“The market doesn't care how confident the model was.”</i></sub>

<a href="https://kcnyu.github.io/clawock/"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dashboard.gif" alt="clawock dashboard cycling through its tabs" width="820"></a>

<a href="https://kcnyu.github.io/clawock/#drill"><picture><source media="(max-width: 700px)" srcset="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/books-narrow.svg"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/books.svg" width="820" alt="US book and Hong Kong book, side by side: each book's return, the basis that return is divided by, and its daily P&amp;L curve in its own currency; the combined return sits underneath on a mixed basis"></picture></a>

| **<!-- CW_M:days -->142<!-- /CW_M:days -->** | **<!-- CW_M:rows -->985<!-- /CW_M:rows -->** | **<!-- CW_M:settled -->159<!-- /CW_M:settled -->** | **44** | **5** | **0** |
|:---:|:---:|:---:|:---:|:---:|:---:|
| days live on a real HK + US account | decisions on the public ledger | episodes settled by code | data modules across 8 layers | agent harnesses, one contract | scores the model wrote for itself |

<sub>Real positions, real P&amp;L, losses included. Numbers and charts refresh weekly; the live dashboard updates through the trading day.</sub>

</div>

## What you get

clawock gives the AI agent you already use a continuing investment workflow for a HK + US stock book: **collect information → argue both sides → settle in code → feed the result into the next decision**. You still place the orders.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/rsi-loop.svg" width="1016" alt="clawock on one page: eight source layers arrive through fallback routes; Python reconciles the book and certifies one context pack; Claude Code, Codex, OpenClaw, DeepSeek Harness or your own CLI argues a bull and a bear case over it; code holds six risk limits, currency rules and evidence requirements; the plan reaches you and you place the orders; code settles each call as a win, a loss or ungradeable; history, earlier-date calibration and reviewed proposals return to the next judgment"></p>

**RSI means Recursive Self-Improvement**: each decision leaves evidence and an outcome for the next one to build on. **No promise of returns.** The active calls have yet to show an edge; what you get is an accumulating record you can check.

## Information in: sources before opinions

Before you open the morning brief, Python has collected quotes through fallback routes such as Tencent / Nasdaq, SEC / HKEX filings, Eastmoney capital flow, bilingual news, macro and sentiment, then reconciled your book, FX and risk. Old news is labelled separately from live information. A failed source says “not fetched,” never “no news.” Hong Kong has the base coverage, but **its research breadth is behind US**.

**You get an evidence pack.** On the live desk, `preflight` writes the core needed for this judgment and reference layers the agent can load on demand. The agent can trace the batch without reconstructing it from chat. In your own harness, `run prepare` produces `request.json`, pinning per-file and whole-context SHA-256 hashes, the workflow version and the whole-pack certificate.

**Certification pins what was used.** Citations carry the source and publication or observation time; hashes check content and generation, not whether a news story is true. Source access credentials and model API keys remain with your runtime, outside the public repository. The portable skill also lets your agent use its own research tools to add traceable evidence; scheduled desk jobs read the Python-assembled files.

**The live desk’s full information and delivery flow**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/information-flow.svg" width="1016" alt="clawock data flow — eight information layers feed ordered fetch-fallback routes; Python reconciles the book and builds risk; the brief, session reports and intraday check-ins each run a preflight that assembles only the blocks that run can use; the agent reads those files and never fetches; a Python postflight validates, then publishes to master, to the data-plane branch the dashboard polls, and to WeChat and Telegram, with an LLM-free crontab watchdog as the delivery backstop"></p>

[Information layers and source catalog](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#the-information-layer) · [Certification protocol](https://github.com/KCNyu/clawock/blob/master/docs/architecture/runtime-protocol.md).

## Decision out: both sides read the same evidence

Ask “Can I add to this position today?” The agent writes the supporting case, the opposing evidence that could overturn it, then an action, trigger, confidence and thesis invalidation conditions. On the live desk, analysts, bull/bear researchers, risk voices and a judge run that debate. The portable workflow takes the same evidence and opposing-case requirements into your current agent.

**You get a plan and a receipt.** The desk leaves a daily brief and `plan.json`; intraday cards compare fresh quotes with the morning's triggers. A portable run produces `decision.json`. Python checks citations, opposing evidence, invalidation and order / FX arithmetic before returning a generation-pinned publication receipt. Without an opposing case it refuses publication. Conversation verdicts on the live desk enter the ledger through `clawock record --source <harness>`. You decide which orders to place.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/decision-card-example.png" width="640" alt="A clawock decision receipt: the subject, a bull case and a bear case each citing evidence, the thesis, the invalidation condition, confidence and action, and a published run id with a pinned certificate"></p>

<sub>Example output, not a settled call.</sub>

**The live desk’s full bull / bear debate**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/debate-flow.svg" width="1016" alt="clawock's multi-agent debate — one evidence pack feeds four analyst lenses; two researchers argue opposing bull and bear cases and record where they disagree; three risk voices and a judge name the strategy frame and resolve it into plan.json, which enters the next session's grading loop"></p>

The desk debate is adapted from [TradingAgents](https://github.com/TauricResearch/TradingAgents); the judge names the strategy frame behind each call.

## After the close: results feed the next decision

The close is not the end of the conversation. You use `mark-followed` to mark followed / not-followed execution evidence. Code checks triggers and outcomes on canonical bars using each market's calendar, groups repeated calls on the same thesis into one episode, and keeps the ungradeable cases visible.

**The next decision starts from this record.** The next live brief reads decision metrics, past reviews and confidence calibration. Calibration uses earlier dates only, shrinking or abstaining when evidence is thin. A failed call stays linked to its original evidence, so the agent can revisit yesterday's reasoning instead of starting the story over.

**A different harness can continue the feedback.** Portable runs turn source-linked `outcome.json` into `evaluation.json` (a directional evaluation, not realized P&L). An evaluation or rejection receipt can anchor a bounded proposal, applied after a named review accepts it, with a rollback record. Today those parameters govern evidence counts and the confidence cap without a primary source; they cannot silently change strategy, trading rules or the skill. This is a reviewable improvement path, not an automatic increase in returns.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/feedback-learning.svg" width="1016" alt="After the close: a call is recorded once by the model, checked against canonical daily bars on each market’s calendar, grouped into one episode per thesis and settled by code as a win, a loss or ungradeable, all published; on the live desk execution, settlement, history and calibration loop back into the next brief; in any other harness an observed outcome can anchor a bounded proposal that a named review accepts or rejects, applied with a rollback record"></p>

Every call is settled mechanically and published: wins, losses, and the cases
that can't be graded. Nothing is hand-tuned after the fact.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/shadow-backtest.png" alt="cumulative episode win rate against a 50% directional-hit line" width="760"></p>

<sub>Cumulative episode win rate against a 50% directional-hit line: how often the direction was right, not what it earned. Refreshed weekly by GitHub Actions; live figures are on the <a href="https://kcnyu.github.io/clawock/#drill">Holdings tab</a>.</sub>

Read it with these limits in mind:

- **A diagnostic, not proof of return.** Keeping the model away from its own score stops the desk grading itself. It does not make the market data or the metric definitions correct, and a direction hit rate is not money earned.
- **The active calls have yet to show an edge.** A factor whose bootstrap interval straddles 50% stays out of decisions, and the leverage dial's timing cannot be distinguished from chance. Both results are published in [Reflect](https://kcnyu.github.io/clawock/#reflect).
- **The shadow portfolio is simulated, not live.** Its gross figure carries no commission and no spread; a net figure with a pre-registered cost haircut is published beside it, and market impact is not modelled.
- **The account result is human plus model.** The owner decides which calls to follow, and every call carries its followed / not-followed / unknown status.

You can recompute it: `clawock scorecard-provenance --check` rebuilds each
published headline from `memory/decisions.jsonl`, and `clawock audit-resettle`
re-settles the whole ledger.
[How the grading handles the hard cases](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#the-public-scorecard) ·
[what we tested, and what failed](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#what-we-tested-and-what-failed).

## Any harness, one decision contract that accumulates evidence

Use the same **`investment-decision` skill and artifact contract in Claude Code / Codex / OpenClaw / DeepSeek Harness / any runtime that can read and write files and call a CLI**. Your agent keeps its model, conversation, memory, research tools, credentials and permissions. clawock certifies inputs, validates outputs, evaluates outcomes and records improvement; it does not launch another model.

“Smarter with use” has a record you can inspect: evidence links to decisions, decisions link to execution and outcomes, history enters the next context, earlier samples calibrate confidence, and changes to evidence requirements leave review and rollback records. To switch harnesses, keep the workspace artifacts and reconnect them to context; continuity lives in those files. A new workspace needs its own capability setup to gain the author's live data feeds, schedules and history.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/product-architecture.svg" width="1016" alt="clawock product architecture — external runtimes own models, conversation, memory and tools while the package supplies portable workflows, certified context, deterministic reconciliation, evaluation and bounded improvement"></p>

[Portable invocation and feedback protocol](https://github.com/KCNyu/clawock/blob/master/docs/architecture/runtime-protocol.md#evaluate-and-improve-without-owning-the-agent) · [Workflow improvement boundaries](https://github.com/KCNyu/clawock/blob/master/docs/architecture/harness.md#ownership).

## What the model is not allowed to do

The model writes opinions. The arithmetic that could corrupt the record runs in
Python and is unit-tested. The six risk limits, the currency rules and the evidence requirements are panel 04 of the overview at the top.

[All twelve rules, and what the code does for each](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#what-the-code-enforces).

## Try it in five minutes

Pick the agent you already use; each logo opens that harness's runnable example.

<div align="center">
<table>
<tr>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/claude-code/CLAUDE.md"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/claude-code.svg" width="56" height="56" alt="Claude Code"><br><b>Claude Code</b></a></td>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/codex/AGENTS.md"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/codex.svg" width="56" height="56" alt="Codex"><br><b>Codex</b></a></td>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/openclaw/SKILL.md"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/openclaw.svg" width="56" height="56" alt="OpenClaw"><br><b>OpenClaw</b></a></td>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/dsh/README.md"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/deepseek-harness.svg" width="56" height="56" alt="DeepSeek Harness"><br><b>DeepSeek Harness</b></a></td>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/cli/run.sh"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/any-cli.svg" width="56" height="56" alt="Any CLI"><br><b>Your own / CLI</b></a></td>
</tr>
</table>
</div>

From an empty directory to a published decision:

```bash
pip install clawock
clawock workflow install investment-decision --workspace ./my-book
clawock init ./my-book --workflow investment-decision
cd my-book && mkdir -p .clawock/work
clawock run prepare > .clawock/work/request.json
# your agent reads the request and writes decision.json
clawock run publish --request .clawock/work/request.json --artifact decision.json=decision.json
```

You need Python ≥ 3.11 and an agent that can read a file and write
`decision.json`; the model call stays in your runtime. CI runs
[this same block](https://github.com/KCNyu/clawock/blob/master/examples/cli/workflow-run/run.sh)
on every pull request against the wheel alone. No model at hand?
`bash examples/cli/minimal-run/run.sh` smokes the whole lifecycle without one,
with no credentials and no broker, or open a Codespace:

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/KCNyu/clawock)

Drop the opposing evidence from `decision.json` and `publish` refuses it (exit code 1):

```json
{
  "status": "rejected",
  "validation_issues": [
    {"code": "insufficient_opposing_evidence", "message": "requires at least 1 opposing evidence item(s)"},
    {"code": "unsupported_bear_case", "message": "bear_case must cite opposing evidence"},
    ...
  ]
}
```

Here is the whole run inside Claude Code, from the
[`examples/claude-code`](https://github.com/KCNyu/clawock/blob/master/examples/claude-code/CLAUDE.md) instruction:

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/claude-code-terminal.png" alt="Claude Code running the investment-decision workflow end to end: clawock init, clawock run prepare, Claude writing decision.json, clawock run publish returning status: published" width="820"></p>

## Harness views and background work

**The DeepSeek Harness desk views and background queue**

**Delegate a task, leave the chat, come back to a result.** `clawock-dsh` brings
an investment-decision skill, a Decision Mind tab and a provider panel into the
dsh web GUI. On a host with clawock's **agent-dispatch** runner, that panel also
puts your Claude Code, Codex and OpenCode background team within reach: you ask
in chat for a repository change with its delivery contract, the runner keeps the
task alive, and the plugin lets you see and steer it.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harnesses.svg" width="1016" alt="Your dsh background team: ask in chat to delegate repo work; agent-dispatch starts an independent systemd task for Claude Code, Codex or OpenCode; watch allowances and queue state in the real plugin screenshot, steer waiting work and budgets, then the agent follows the requested PR, required CI, squash-merge and host-refresh contract; the runner returns a final report through best-effort WeChat and Telegram sends, whose receipts stay separate from task outcome"></p>

- **See what is happening.** Subscription use and reset times, provider balances, each agent's real queue, model, elapsed time and API-price cost estimate share one panel.
- **Change course while it runs.** Move waiting work up, change the next attempt's model where allowed, adjust deadlines and retry budgets, cancel a task or retry an unfinished session.
- **Keep the result in reach.** A completed task with a failed send stays visible; a missing message does not erase the work.

**The full-size queue capture** — the real plugin on a live host

<br>

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-dispatch-queue.png" width="400" alt="Full live-host provider panel: Claude and Codex quota windows above their queues, DeepSeek and MiniMax balances, OpenCode free pool, recently ended tasks with notification receipts, patrol rounds with readable filed counts, severity and issue links, and the ops version footer"></p>

[Queue capabilities and setup](https://github.com/KCNyu/clawock/blob/master/examples/dsh/packages/clawock-dsh/README.md#dispatch-queue) ·
[runner and ops contract](https://github.com/KCNyu/clawock/blob/master/docs/architecture/task-queue.md).

**A task's history** — append instructions and the progress timeline

<br>

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-task-detail.png" width="380" alt="Complete live dsh task detail in a phone layout: a finished repository task, numbered append instruction with delivery status, and timestamped progress from dispatch and execution-lock waiting through attempts, instruction delivery, continuation and notification receipts"></p>

Ask “Can I add to 0700.HK?” and the investment skill takes the agent through
evidence, a bull/bear debate and a bounded decision. **Decision Mind** then lets
you open a real fill and follow **plan → execution → T+1 → P&L**. Missing plans
and ungraded fills say so, USD and HKD stay separate, and you place the orders.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-decision-mind.png" width="820" alt="Decision Mind inside the real dsh web GUI: fills grouped by day with paired plans and T+1 verdicts; an expanded trace follows the plan, actual execution and outcome"></p>

```bash
python -m pip install clawock
dsh plugin --profile web add clawock-dsh
mkdir -p ~/.dsh/skills
cp -r ~/.dsh/profiles/web/node_modules/clawock-dsh/skills/investment-decision ~/.dsh/skills/
```

Restart the web profile to load it. Queue controls also need the host runner;
without it the panel still shows provider allowances and balances.
[npm package](https://www.npmjs.com/package/clawock-dsh) ·
[installation and queue setup](https://github.com/KCNyu/clawock/blob/master/examples/dsh/packages/clawock-dsh/README.md).

## Under the hood

How the same loop runs on the author’s real stock book:

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/architecture.svg" width="1016" alt="KCNyu live-desk architecture — Python builds reconciled market context, OpenClaw agents debate the trade, clawock contracts gate the decision, and a public scorecard closes the loop"></p>

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/decision-pipeline.svg" width="1016" alt="One clawock trading day, end to end — Python collects quotes through ordered fallback chains (HK Tencent + Eastmoney, then stooq, then yfinance; US Nasdaq first through a seven-route chain; USD/HKD Frankfurter, exchangerate.host, Yahoo), SEC and HKEX filings, Eastmoney capital flow, bilingual news, Reddit and influencer sentiment, and macro and catalyst calendars; it reconciles the book, computes portfolio risk, per-leg concentration, the leverage regime dial, quant factors, cross-sectional ranks and peer residuals behind a backtest gate, and holds risk caps, the entry gate, earnings quality, thesis drift and the news evidence graph as code gates; a preflight hands the agents one context pack, where four analyst lenses, a bull and a bear who must disagree, three risk voices and a judge write plan.json; a Python postflight validates it, books it in memory/decisions.jsonl, renders the brief card, sends WeChat and Telegram and publishes the dashboard; then code records what was executed with mark-followed, settles each episode on canonical bars, calibrates confidence, replays a shadow portfolio against buy-and-hold and publishes the scorecard, which the next brief reads; in dsh, Decision Mind shows real fills beside their plans and T+1 verdicts for a follow-up, while execution stays human"></p>

The author's desk sends the pre-open plan at **08:03 HKT** and runs this unattended on OpenClaw. Each job is
`clawock … preflight`, then the model writes, then `clawock … postflight`:

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/openclaw-cron.png" alt="OpenClaw's live cron list on the desk host: nine clawock jobs (pre-open brief, HK and US session reports, intraday check-ins) with their cron expressions, the clawock preflight → postflight lifecycle each one runs, last status ok and run time" width="820"></p>

<sub>Rendered from the host's real <code>openclaw cron list --json</code> by <code>site/tools/shoot_openclaw_cron.js</code>; job ids, delivery targets and prompts are left out. The full timetable is the <a href="https://github.com/KCNyu/clawock/blob/master/docs/operations/cron-schedules.md">generated schedule</a>.</sub>

[How the desk works](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md) covers the information layers, run context, settlement rules and code gates.

## Explore

- [**Live dashboard**](https://kcnyu.github.io/clawock/) — positions, risk, and the code-graded scorecard.
- [**Daily briefs**](https://kcnyu.github.io/clawock/briefs.html) — the published morning reads.
- [**Decision Map**](https://kcnyu.github.io/clawock/#reflect) — a dated signal snapshot beside each decision ([reading guide](https://github.com/KCNyu/clawock/blob/master/docs/decision-map.md)).
- [**Examples by harness**](https://github.com/KCNyu/clawock/blob/master/examples/README.md) — one decision run, five harnesses, plus the npm dsh plugin.
- [**How the desk works**](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md) — the information layers, what each run reads, decision gates, grading rules and the twelve code-enforced rules.
- [**Influencer radar**](https://github.com/KCNyu/clawock/blob/master/docs/influencer-radar.md) — eight public sources scanned twice a trading day and linked to holdings; misses are published as misses.
- [**Command reference**](https://github.com/KCNyu/clawock/blob/master/docs/reference/commands.md) · [**glossary**](https://github.com/KCNyu/clawock/blob/master/docs/glossary.md) · [**all project docs**](https://github.com/KCNyu/clawock/blob/master/docs/README.md) · [**contributing**](https://github.com/KCNyu/clawock/blob/master/AGENTS.md#code-changes)

### Research surfaces

| Question | Entry point | Reuse scope |
|---|---|---|
| Analyze a US company | [`us-stock-analysis`](https://github.com/KCNyu/clawock/blob/master/skills/us-stock-analysis/SKILL.md) | Reusable with the clawock workspace |
| Analyze a Hong Kong company | [`hk-stock-analysis`](https://github.com/KCNyu/clawock/blob/master/skills/hk-stock-analysis/SKILL.md) | Reusable with the clawock workspace |
| Review the current portfolio | [`portfolio-risk-review`](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-risk-review/SKILL.md) / [`portfolio-swarm-review`](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-swarm-review/SKILL.md) | Specific to the configured portfolio |
| Stress-test a supply-chain thesis | [`serenity-skill`](https://github.com/KCNyu/clawock/blob/master/skills/serenity-skill/SKILL.md) | Reusable as a manual research framework |
| Review a reported quarter | [`earnings-review`](https://github.com/KCNyu/clawock/blob/master/skills/earnings-review/SKILL.md) | Reusable; artifacts live in `memory/earnings/` |
| Decide whether a new name is worth researching | [`entry-gate`](https://github.com/KCNyu/clawock/blob/master/skills/entry-gate/SKILL.md) | Reusable; artifacts live in `memory/entry-gates/` |

They expect clawock's scripts, data contracts and memory files; they are not standalone one-command products.

Built with [Claude Code](https://claude.com/claude-code), the [openclaw](https://openclaw.com) cron daemon, a static Jekyll + GitHub Pages frontend, and Python. Market, news, macro, and sentiment come from documented public sources; see [third-party data and service terms](https://github.com/KCNyu/clawock/blob/master/docs/legal/third-party-data.md) before reusing any fetched content.

---

## Scope, disclaimer, and license

This repository holds **real trading positions**. It is a personal record and portable workspace — **not investment advice, a recommendation, or a copy-trading system**. The desk analyzes and proposes; it does not place orders for you. No individual outcome is hand-picked — settlement rules and methodology changes are versioned in code — the active calls have yet to show an edge, and every number may be stale by the time you read it.

Original code is under the [MIT License](https://github.com/KCNyu/clawock/blob/master/LICENSE). Adapted third-party code keeps its own license and attribution in [NOTICE](https://github.com/KCNyu/clawock/blob/master/NOTICE) and [`THIRD_PARTY_LICENSES/`](https://github.com/KCNyu/clawock/tree/master/THIRD_PARTY_LICENSES). Third-party market data, news, social posts, filings, trademarks, and API access are **not** relicensed by MIT — see [Third-party data and services](https://github.com/KCNyu/clawock/blob/master/docs/legal/third-party-data.md).

<div align="center">
<br>

**[Live dashboard](https://kcnyu.github.io/clawock/)** &nbsp;·&nbsp; **[Daily briefs](https://kcnyu.github.io/clawock/briefs.html)** &nbsp;·&nbsp; **[简体中文](https://github.com/KCNyu/clawock/blob/master/README.zh.md)**

<sub>Built and maintained by <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> and Rick · 2026</sub>

</div>
