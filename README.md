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

| **<!-- CW_M:days -->148<!-- /CW_M:days -->** | **<!-- CW_M:rows -->1013<!-- /CW_M:rows -->** | **<!-- CW_M:settled -->166<!-- /CW_M:settled -->** | **47** | **5** | **0** |
|:---:|:---:|:---:|:---:|:---:|:---:|
| days live on a real HK + US account | decisions on the public ledger | episodes settled by code | data modules across 8 layers | agent harnesses, one contract | scores the model wrote for itself |

<sub>Real positions, real P&amp;L, losses included. Numbers and charts refresh weekly; the live dashboard updates through the trading day.</sub>

</div>

## What you get

clawock helps your AI agent analyze your Hong Kong or US holdings and write a trading plan. On the author’s setup, each morning’s plan explains whether to buy, sell or wait, the reasons on both sides, and the prices that would change the recommendation. **You place the orders.** Code later checks the calls against market prices and saves the results for the agent to read next time.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/rsi-loop.svg" width="1016" alt="clawock on one page: eight source layers arrive through fallback routes; Python reconciles the book and certifies one context pack; Claude Code, Codex, OpenClaw, DeepSeek Harness or your own CLI argues a bull and a bear case over it; code reviews concentration and enforces the configured risk boundaries, records what happens when one breaks and enforces evidence requirements; the plan reaches you and you place the orders; code settles each call as a win, a loss or ungradeable; the record returns around two loops, one into the next judgment through history and earlier-date calibration, one into the evidence rules through a bounded proposal and a named review; on the author’s host patrol rounds, a filing gate, background agents and required CI maintain the desk’s own code, watched from DeepSeek Harness"></p>

**That loop is what RSI, Recursive Self-Improvement, means here.** The author’s daily jobs use connected data feeds, a scheduler and accumulated decision history. A new installation needs its own data and scheduling; you can start with the [single-run example](#try-it-in-five-minutes). Saving earlier evidence and results gives the agent something to review before its next decision. **It is not a promise of returns.** The calls that told the author to act have not been shown to beat a coin flip.

One real call runs through this page: Goldwind (`02208`, Hong Kong) on the morning of 2026-10-08. The plan said to keep holding and watch, with an add only above 8.97. The ledger records `loss` because the price fell by the next session’s close: it scores the holding judgment, not a purchase at 8.97. The sections below explain the evidence, plan and score.

The plan’s indicators came from [plugins](#everything-that-computes-is-a-plugin-what-a-result-may-do-is-not). A strategy may [search for better settings of its own](#a-strategy-can-search-its-own-parameters-adopting-them-is-a-reviewed-edit), but adopting them requires a person’s review. [Try it in five minutes](#try-it-in-five-minutes).

## Everything that computes is a plugin; what a result may do is not

On 2026-10-08, the author held 400 shares of Goldwind (`02208`, Hong Kong) at an average cost of 14.084. Here is how its indicators became a plan and then an evaluated judgment. Plugins compute the indicators; `config/strategy-plugins.json` selects the modules and their settings.

1. **The `factors` plugin calculated Goldwind’s indicators from daily prices.** It reported no upward trend, with the price 31.8% below its 200-day average.
2. **The model weighed those indicators with the other evidence.** Bull: Goldwind was the only peer with an actionable confirmation price, and the portfolio had little exposure outside Hong Kong tech and AI. Bear: its weak trend and four breached portfolio risk limits argued against adding. The conclusion was to watch and record the trigger before the price reached it.
3. **The plan was specific enough to be wrong.** Watch. Act only if it trades above 8.97 within five sessions. The idea is dead at 8.923. Confidence 0.34.
4. **Code scored the decision to keep holding.** The reference price was 8.645, the first tradable price after publication. The next session closed 4.22% lower, so the outcome was `loss`. This record assumes no purchase at the add trigger.
5. **The judgment and its result stayed in the record.** Decision `dec-6d9e8bdc8817` is on the public ledger and counts in the history the next brief reads.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/strategy-plugins.svg" width="1016" alt="One real call, Goldwind on 2026-10-08, in five numbered steps. 01: the factors row, drawn as a module in its socket with an empty socket beside it for a row of your own, computed one reading: trend off, 31.8% under its 200-day average. 02: the model argued a bull case and a bear case over that reading. 03: the plan on paper: watch, act only above 8.97 within five sessions, dead at 8.923, confidence 0.34, contested. A line marked &quot;not rows from here down&quot;. 04: Goldwind's eight daily bars to 2026-10-09 with the act and dead prices ruled across them; code took the open of 2026-10-08, 8.645, as the reference, marked the next close, 8.28, 4.22% lower and called it a loss. 05: the entry as the ledger stores it, dec-6d9e8bdc8817, outcome loss. No row can mark its own call, pick a kinder reference price, turn the loss into something else or keep it off the ledger."></p>

**You can replace the plugin in step 1.** Your own plugin could use a different average, observation period or data source. Settlement and recordkeeping in steps 4 and 5 stay outside plugins: a plugin cannot score its own call, choose its reference price, change the result or omit it from the ledger. Strategies can therefore be compared under the same scoring rules.

To use clawock with your agent, you add one skill, a command line tool and a JSON file format for exchanging decisions. Your agent keeps its model, conversation and tools.

**Plugins must identify their inputs and outputs.** Before a plugin’s results can reach a decision, it must declare its data sources, units, observation periods and missing-data behavior. Yesterday’s result cannot be presented as today’s.

| Plugin | Measures | When data is missing |
|---|---|---|
| `factors` | trend, momentum, RSI, volatility and an exit price for each stock, from daily prices | the field is empty; fewer than 30 daily prices means no result for that stock |
| `bar-signals` | how costly a name is to trade and how much it is likely to move, per session | empty, never zero: "could not be estimated" is not "cheap to trade" |
| `sentiment` | Reddit mentions over seven days, and statements by named public figures | the block is left out, and says whether the scan is missing, too old or unreadable |
| `morning-scans` | the macro snapshot and Chinese-language news, and the one read of every scheduled scan file | the same: left out, with the reason |
| `strategy-scores` | where each name ranks under each research strategy's current setting; reference only | says it is unavailable and why |

**If a plugin fails to load, tasks that need it stop and name the failed plugin; other tasks keep running.**

**You can write your own plugin.** Register an installed Python module in the configuration file; the [plugin guide](https://github.com/KCNyu/clawock/blob/master/docs/architecture/strategy-plugins.md#writing-a-plugin-outside-this-repository) covers the interface and required declarations. Plugins run with your permissions, not in a sandbox, so install only modules you trust.

**Plugins can be added, removed or reconfigured while others run.** Removing one pauses its dependents; restoring it restarts them. Changing a plugin’s settings restarts that plugin with the new values. This follows the [dsh](https://github.com/KCNyu/clawock/blob/master/examples/dsh/README.md) plugin design.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/plugin-system.svg" width="1016" alt="The whole plugin system in seven numbered parts. 01: whatever agent runs the desk, Claude Code, Codex, OpenClaw, dsh or any CLI, runs the brief, report, intraday and strategy-lab commands. 02: one file, strategy-plugins.json, lists every row: thirteen live rows and seven research rows, each an id, a module and its settings. 03: the host mounts every row in a socket; all twenty are shown by name, with the research row bars pulled out of its socket and one empty socket for a row of your own. 04: pulling bars undoes its one registration, the optimizer row that declared it needs bars waits, and the other five rows are never stopped; pushed back in, the optimizer starts by itself. 05: changing a setting, the adjustment on the daily-bars row from qfq to raw, stops that row and starts it again under the new setting. 06: the five primitives dsh is built on beside their names here: a row in a file, a fiber, provide and inject, effect, update. 07: what has no socket: settlement, the ledger and the risk limits."></p>

```bash
clawock strategy-lab list       # plugins, their services and missing dependencies
clawock strategy-lab sources    # inputs, units, observation periods and missing-data behavior
```

[Plugin configuration and boundaries](https://github.com/KCNyu/clawock/blob/master/docs/architecture/strategy-plugins.md) · [Write your own plugin](https://github.com/KCNyu/clawock/blob/master/docs/architecture/strategy-plugins.md#writing-a-plugin-outside-this-repository).

## Any harness, one decision contract that accumulates evidence

Say you use Claude Code today and switch to Codex next month. You do not start over, because clawock was never inside the chat. It is one skill (`investment-decision`), one command line tool and a handful of files in your workspace. Any agent that can read a file, write a file and run a command can pick them up: **Claude Code / Codex / OpenClaw / DeepSeek Harness / your own script**.

Your agent keeps what is its own: the model, the conversation, its memory, its research tools, your credentials and your permissions. clawock never starts a model. It does four jobs around your agent: it pins down what went in, checks what came out, marks the result later, and keeps the record.

With your own agent, you use `request.json`, `decision.json`, `outcome.json` and `evaluation.json`. The author’s daily setup also writes `plan.json` and `decisions.jsonl`.

| File | Written by | What it holds |
|---|---|---|
| `request.json` | clawock, when you run `clawock run prepare` | the material for this decision, with a fingerprint of every document so it cannot be swapped afterwards |
| `decision.json` | your agent | its answer: the case for, the case against, the action, and what would prove it wrong |
| `plan.json` | the author's setup, every morning | the same answer for a whole portfolio, one entry per position |
| `decisions.jsonl` | the author's setup | the public ledger: one line per decision, with the result added once code has marked it |
| `outcome.json` | you, once the waiting period is over | the prices you saw and where you got them |
| `evaluation.json` | clawock, when you run `clawock workflow evaluate` | whether the direction was right. It is not money made |

**Before writing the next plan, the agent can review earlier judgments and their results.** The model itself does not change. The files preserve evidence, actions and outcomes; enough evaluated history also lets the author’s setup check how reliable earlier confidence estimates were. Switching agents does not erase that history if you keep the same workspace. A new workspace has no history of your decisions: you build it by recording decisions and evaluating them after their observation periods.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/product-architecture.svg" width="1016" alt="clawock product architecture — external runtimes own models, conversation, memory and tools while the package supplies portable workflows, certified context, deterministic reconciliation, evaluation and bounded improvement"></p>

[Portable invocation and feedback protocol](https://github.com/KCNyu/clawock/blob/master/docs/architecture/runtime-protocol.md#evaluate-and-improve-without-owning-the-agent) · [Workflow improvement boundaries](https://github.com/KCNyu/clawock/blob/master/docs/architecture/harness.md#ownership).

## Information in: sources before opinions

It is 08:03 on 2026-10-08. The morning job has just started and no model has run yet. Python has already fetched Goldwind's daily bars from Tencent, looked for a company filing, and asked Google News for headlines about it. Four headlines came back. Two had nothing to do with Goldwind. The other two were published before the previous close, so they were labelled old news. No primary financial filing could be reached.

The brief said exactly that, in two lines under `02208`. The primary financial disclosure was “not fetched”. And: “this stock has no usable news evidence today, so today's judgment rests entirely on price and relative strength.”

That is the rule this section is named after. **Sources are collected and labelled before anyone has an opinion.** In practice it comes down to three habits:

- **Quote sources have fallback routes.** On the author’s configured desk, quotes come through Tencent or Nasdaq first and fall through to the next provider when one fails. Filings come from the SEC and HKEX, capital flow from Eastmoney, and there is news in Chinese and English, macro data and sentiment. Python then reconciles your book, the exchange rate and the risk numbers.
- **Old news is not passed off as new.** Anything published before the previous close is labelled as old.
- **A failed source says “not fetched”, never “no news”.** Hong Kong has the basic coverage, but **its research breadth is behind US**.

**What your agent receives is a pack of files.** On the author's setup, `preflight` writes the files this judgment needs, plus reference files the agent can open when it wants more. The Goldwind decision still carries the id of the pack it was made from, `c3f65a7beaebb24e`, so anyone can look up which batch of material stood behind it. In your own harness, `clawock run prepare` writes `request.json`: the same kind of pack, with a SHA-256 fingerprint of each document and of the whole, and the workflow version it was prepared for.

**The fingerprint proves which material was used. It does not prove a news story is true.** Each citation carries its source and the time it was published or observed. The passwords for your data sources and your model API key stay in your own runtime and never enter the public repository. In your own harness, your agent may also add evidence from its own research tools, as long as it can be traced. The author's scheduled jobs read only the files Python assembled.

**The live desk’s full information and delivery flow**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/information-flow.svg" width="1016" alt="clawock data flow — eight information layers feed ordered fetch-fallback routes; Python reconciles the book and builds risk; the brief, session reports and intraday check-ins each run a preflight that assembles only the blocks that run can use; the agent reads those files and never fetches; a Python postflight validates, then publishes to master, to the data-plane branch the dashboard polls, and to WeChat and Telegram, with an LLM-free crontab watchdog as the delivery backstop"></p>

[Information layers and source catalog](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#the-information-layer) · [Certification protocol](https://github.com/KCNyu/clawock/blob/master/docs/architecture/runtime-protocol.md).

## Decision out: both sides read the same evidence

The question that morning was simple: is it time to add to Goldwind? The agent is not allowed to answer with a feeling. It has to write the case for, then the strongest case against, and only then an action, the price that triggers it, a confidence figure and the condition under which it admits being wrong. Both sides argue from the same pack of files.

The author’s 08:03 brief set an add trigger above 8.97, valid for five sessions, and an invalidation price of 8.923. Intraday cards compared fresh quotes with that trigger. Goldwind’s high that day was 8.71, so the add did not trigger that day. The existing holding remained subject to the separate holding-judgment score below.

**You get a plan and a receipt.** The author's setup leaves the daily brief and `plan.json`. In your own harness, your agent writes `decision.json` and you run `clawock run publish`. Python then checks four things: every claim points at a document in the pack, there is a case against, there is a condition that would prove the call wrong, and any order and currency arithmetic adds up. If all four hold, you get a receipt tied to that exact pack. If the case against is missing, publication is refused. A verdict reached in conversation on the author's setup enters the ledger with `clawock record --source <harness>`. Either way, you decide which orders to place.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/decision-card-example.png" width="640" alt="A clawock decision receipt: the subject, a bull case and a bear case each citing evidence, the thesis, the invalidation condition, confidence and action, and a published run id with a pinned certificate"></p>

<sub>Example output, not a settled call.</sub>

**The live desk’s full bull / bear debate**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/debate-flow.svg" width="1016" alt="clawock's multi-agent debate — one evidence pack feeds four analyst lenses; two researchers argue opposing bull and bear cases and record where they disagree; three risk voices and a judge name the strategy frame and resolve it into plan.json, which enters the next session's grading loop"></p>

On the author's setup this debate is split between several roles: four analysts, a bull and a bear researcher, three risk voices, and a judge who names the strategy behind each call. It is adapted from [TradingAgents](https://github.com/TauricResearch/TradingAgents). In your own harness, the one agent you already have is held to the same two requirements: read the same evidence, and write a case against.

## After the close: results feed the next decision

For the 2026-10-08 Goldwind record, code evaluated the judgment to keep holding over the next trading session. It used 8.645, the first tradable price after publication, as the reference. The next session closed at 8.28, down 4.22%, so the record’s outcome is `loss`. The record is `watch`, evaluated as `passive_stance`, with `fill_assumed: false`: no purchase at the 8.97 trigger is assumed. This is a score for the holding judgment, not profit or loss from a new trade.

Three rules keep that score honest, and each has a real case behind it:

- **Saying the same thing every day counts once.** Between 2026-07-29 and 2026-10-08 the brief said “hold and watch” on Goldwind 45 times. Those are one result (`ep-f31982c6d511`), not 45.
- **A call that cannot be graded stays on the ledger.** On 2026-10-01 the plan set a trigger for Goldwind, but Hong Kong was closed. Record `dec-143614125e34` has an unknown result (`outcome: unknown`), cannot be evaluated (`status: not_evaluable`), and gives the session reason separately (`session_reason: market_closed`).
- **What you did is recorded apart from what the plan said.** `clawock mark-followed` marks each call followed or not followed, because the account's result is the model's advice plus your own choices.

Prices come from one standard set of daily bars, read on each market's own trading calendar.

**The next decision starts from this record.** The brief of 2026-10-12 printed that Goldwind call again, in a table headed “Yesterday's results (the 2026-10-08 plan)”, with `loss` beside it. In the same brief the judge wrote about Goldwind: no move; the third-quarter report is ten days away, and waiting for the filing beats guessing a direction. The model also reads how reliable its earlier confidence figures turned out to be. That check uses earlier dates only, and when there are too few cases it trusts the figure less or gives no reading at all. A call that failed stays attached to the evidence it was made on, so the agent can go back over yesterday's reasoning instead of telling the story from scratch.

**To evaluate a decision in your own harness,** put the observed prices and their sources in `outcome.json` after the observation period. Run `clawock workflow evaluate` to produce `evaluation.json`, which checks the direction of the call. It does not measure realized profit or loss.

Results or a rejected publication can support a proposed change to evidence requirements. A reviewer’s name and decision are recorded before an accepted change is applied; it can be rolled back. This process permits only changes to the required evidence count and the confidence limit without a primary source. It cannot change strategies, trading rules or the skill itself. The [feedback protocol](https://github.com/KCNyu/clawock/blob/master/docs/architecture/runtime-protocol.md#evaluate-and-improve-without-owning-the-agent) explains the review and rollback steps.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/feedback-learning.svg" width="1016" alt="After the close: a call is recorded once by the model, checked against canonical daily bars on each market’s calendar, grouped into one episode per thesis and settled by code as a win, a loss or ungradeable, all published; on the live desk execution, settlement, history and calibration loop back into the next brief; in any other harness an observed outcome can anchor a bounded proposal that a named review accepts or rejects, applied with a rollback record"></p>

Every call is settled this way and published: the wins, the losses and the ones that cannot be graded. Nobody adjusts a result afterwards.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/shadow-backtest.png" alt="cumulative episode win rate against a 50% directional-hit line" width="760"></p>

<sub>Cumulative episode win rate against a 50% directional-hit line: how often the direction was right, not what it earned. Refreshed weekly by GitHub Actions; live figures are on the <a href="https://kcnyu.github.io/clawock/#drill">Holdings tab</a>.</sub>

Read it with these limits in mind:

- **It measures direction, not money.** The chart shows how often the direction was right, not what it earned. Keeping the model away from its own score stops it grading itself. It does not make the market data or the definitions correct.
- **The calls to act have not been shown to beat a coin flip.** A signal whose measured range still includes 50% is kept out of decisions, and the timing of the leverage dial cannot be told apart from chance. Both results are published in [Reflect](https://kcnyu.github.io/clawock/#reflect).
- **The shadow portfolio is a simulation, not the account.** Its headline figure leaves out commission and spread. A second figure, with a cost deduction fixed in advance, is published beside it. Neither models what a large order would do to the price.
- **The account's result is yours plus the model's.** The owner decides which calls to follow, and every call carries its status: followed, not followed or unknown.

With ledger data available, you can redo the sums. `clawock scorecard-provenance --check` rebuilds each
published headline number from `memory/decisions.jsonl`, and `clawock audit-resettle`
settles the whole ledger again.
[How the grading handles the hard cases](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#the-public-scorecard) ·
[what we tested, and what failed](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#what-we-tested-and-what-failed).

A proposal is scored on more than whether it paid. On 2026-10-12 the model proposed trimming 20 shares of MiniMax (`00100`) if the price traded above 225 within one session, and it forecast, with probability 0.55, a close under 213 on the fifth session. Code kept the proposal (`prop-7c966b4a33172e8c`) together with the inputs it was made from, the method it named and two objections. It is then read in two ways that are kept apart: did the trade pay, and was 0.55 a fair probability. [Method evaluation](https://github.com/KCNyu/clawock/blob/master/docs/architecture/decision-architecture.md#method-records-and-evaluation) reports both, and a method that scores well is not promoted automatically.

**From an open proposal to evidence about the method**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/proposal-review.svg" width="1016" alt="One real open proposal, MiniMax on 2026-10-12, in five numbered steps. 01: the model proposes to trim 20 shares if the price trades above 225 within one session, and forecasts with probability 0.55 a close under 213 on the fifth session. 02: code reviews it on three channels; facts and feasibility could refuse it and did not, the strategy channel can only object and objected twice: a sale without an escalated event, an active move without a catalyst. 03: every outcome is kept in the method record: published, published over an objection, refused, unpublished; this one was published with its objections attached. 04: the record is read on two separate axes: its payoff is not triggered, because it never traded above 225, and whether 0.55 was right is scored on its own. 05: a comparison of old policy, observations only and policy reference is frozen before it starts, with first records on 2026-10-13, on the same capital and costs, with a missing mark left as a hole. No automatic promotion, sizing or orders."></p>

## A strategy can search its own parameters; adopting them is a reviewed edit

Goldwind’s indicators include RSI, a measure of recent price gains and losses. The `rsi` plugin’s configuration uses a 14-session look-back and treats a low value as a possible rebound. On the author’s setup, the strategy lab runs after the morning brief to test other settings. The 2026-10-12 search used the 28 stocks with available price history, including Goldwind.

1. **It tries only declared settings.** The plugin’s configuration lists six look-back lengths and two interpretations in advance. All twelve combinations are counted, so a lucky result cannot be presented as the only one tried.
2. **A gate judges the best of them.** It needs enough days it was not tuned on, a ranking that beats chance and beats the current setting by a margin that is not noise, a low chance of having been fitted to the past, and prices adjusted for splits and dividends. A configuration line can make this gate stricter. It cannot make it looser than the floor in the code.
3. **Second opinions may object.** Other thresholds judge the same run, for example after trading costs. They can block. They cannot pass what the gate refused.
4. **The verdict is written down.** Every run goes to a ledger, and the ledger is checked against these rules each time it is read.
5. **Then it has to keep working.** A setting that passes is registered, and from then on it is scored only on days that had not happened when it was picked.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/strategy-evolution.svg" width="1016" alt="One real search of a strategy's own setting, RSI on 2026-10-12, in five numbered steps. 01: the rsi row as the file holds it, today's setting and the settings it may try, and those twelve as a grid of six look-back lengths by two ways of reading the number; the row today is on 14 sessions read as a rebound, the search picks 28 sessions read as strength continuing. 02: a gate judges the best of them on five checks, each with what was measured and what it needs: 705 sessions against at least 60, a range of 0.0171 to 0.1117 against chance and 0.0408 to 0.2195 against today's setting, both above zero, 0.0 against a ceiling of 0.5, adjusted prices. 03: two second opinions, after trading costs and on the statistics alone, would pass it. 04: the ledger holds two entries, a candidate on all 28 names and a refusal on the 16 whose prices were confirmed as adjusted, because that range, -0.043 to 0.0529, crosses zero. 05: only later sessions count from here, 0 of 60 so far; the edit to the row, 14 sessions to 28, has not been proposed, and the row keeps 14 sessions until a person reviews one."></p>

On 2026-10-12 the answer for RSI was: a 28-session look-back, read as "strength continues", would have ranked these names better. The gate passed it and it was registered. **The same search on the 16 names whose prices the provider confirmed as adjusted, Goldwind one of them, was refused.** The result leans on the other 12, where all the lab has is one provider's record showing no split or dividend, and no second source to check it against. Every run now carries that second search, so a passing setting says for itself whether it survives it.

**The search did not change Goldwind’s RSI settings.** The next brief still used 14 sessions and the rebound interpretation. Adopting new settings requires a reviewed configuration change. The lab can propose it only after the candidate holds up over at least 60 later sessions and passes the check it currently fails. As of the 2026-10-12 run, no later session had been scored and no edit had been proposed.

```bash
clawock strategy-lab evolution rsi   # each run, what changed, each registration and how it has done since
clawock strategy-lab row-edits       # proposed configuration changes, for review
clawock strategy-lab verify          # the ledger against the lab's limits
```

[What a search may conclude, second opinions and the lab's limits](https://github.com/KCNyu/clawock/blob/master/docs/architecture/strategy-plugins.md#boundaries).

## What the model is not allowed to do

The model writes opinions. It does not do the arithmetic and it does not keep its own score; both run in Python and are unit-tested. On the Goldwind morning that meant the model could not:

- **Choose its own reference price.** 8.645 came from a rule in code: the first price that could be traded after the plan was published.
- **Mark its own call.** `loss` was written by the settlement code from the daily bars. The model that wrote the plan never touches that field.
- **Publish without a case against.** A decision with no opposing evidence is refused, as the [five-minute run](#try-it-in-five-minutes) shows.
- **Add Hong Kong dollars to US dollars.** Goldwind is priced in HKD. The two currencies are shown side by side with the exchange rate and its timestamp, never summed raw.
- **Decide whether a risk limit has been crossed.** Code checks the limits at every brief. That morning it found four position limits and two leverage stop-losses crossed, and the brief opened with them. Each breach keeps a dated record of how it was answered: a trim, or a hold with its reason. None of them sells anything by itself.

The risk limits, what happens when one is crossed, and the evidence requirements are drawn in the “Code holds the boundary” panel of the overview at the top.

[All twelve rules, and what the code does for each](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#what-the-code-enforces).

## Harness views and background work

**The DeepSeek Harness desk views and background queue**

**With dsh and the host runner configured, you can hand over a task and return to the result.** In the dsh web GUI, you ask for a change to a repository and say how you want it delivered. A background agent (Claude Code, Codex or OpenCode) takes it and keeps working after you close the tab. When you come back, the panel shows how far it got.

That is what `clawock-dsh` adds to dsh: the investment-decision skill, a Decision Mind tab and a provider panel. The background queue needs clawock's **agent-dispatch** runner on the host. The runner keeps each task alive; the plugin lets you watch it and steer it.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harnesses.svg" width="1016" alt="Your dsh background team: ask in chat to delegate repo work; agent-dispatch starts an independent systemd task for Claude Code, Codex or OpenCode; watch allowances and queue state in the real plugin screenshot, steer waiting work and budgets, then the agent follows the requested PR, required CI, squash-merge and host-refresh contract; the runner returns a final report through best-effort WeChat and Telegram sends, whose receipts stay separate from task outcome"></p>

- **See what is happening.** Subscription use and reset times, provider balances, each agent's real queue, model, elapsed time and API-price cost estimate share one panel.
- **Change course while it runs.** Move waiting work up, change the next attempt's model where allowed, adjust deadlines and retry budgets, cancel a task or retry an unfinished session.
- **Keep the result in reach.** A completed task with a failed send stays visible; a missing message does not erase the work.

The author’s host looks after its own code through the same queue (the “The desk fixes itself the same way” panel of the overview). Separately configured patrol rounds check published outputs. The program checks each finding’s evidence before opening an issue. A background agent takes the fix through a PR and the required CI. An issue closed as noise makes that kind of finding count for less next time. Installing the Python package or dsh plugin does not set up these patrol rounds.

**From the queue to a task’s history** — one annotated view

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-task-tour.svg" width="1016" alt="Annotated composite of real dsh captures, with original proportions preserved: the left column shows Claude allowance windows and a running task, then recently ended tasks with separate outcome and notification indicators; the right column shows a completed Codex task's numbered append and delivered status, followed by recorded append submission, continuation, delivery, attempt completion and notification events. The final receipt shows WeChat delivered and Telegram failed even though the task completed. These are excerpts from two different historical captures, not one task's synchronized state or a new desktop screenshot; links below open both complete originals."></p>

Read the queue to find the work, then open a task to inspect its instructions and recorded progress. Appends are made through the host runner; the detail view shows whether they were delivered. **Task completion and message delivery are separate:** this finished task has a failed Telegram receipt.

The figure combines excerpts from two historical captures at their original proportions, with explanation alongside them. It is not a new desktop screenshot. [Full queue capture](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-dispatch-queue.png) · [Full task history](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-task-detail.png).

[Queue capabilities and setup](https://github.com/KCNyu/clawock/blob/master/examples/dsh/packages/clawock-dsh/README.md#dispatch-queue) · [runner and ops contract](https://github.com/KCNyu/clawock/blob/master/docs/architecture/task-queue.md).

Once you have supplied holdings and evidence, ask “Can I add to 0700.HK?” and the investment skill walks the agent through the same steps as above: gather evidence, argue both sides, then write a decision with a trigger and a way to be wrong. **Decision Mind** reads your workspace’s recorded trades and plans; a new workspace has no trade history to show. Open a real fill and follow it through **plan → execution → T+1 → P&L**: what the plan said, what you did, where the price was one session later, and what it earned or lost. A fill with no plan behind it says so, and so does one that has not been graded yet. USD and HKD stay separate, and you place the orders.

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

The diagrams below show the author’s configured account: market-data access, holdings, stored decisions, scheduled jobs and delivery destinations. Installing clawock gives you the commands and workflows; reproducing this daily service requires configuring those inputs and jobs.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/architecture.svg" width="1016" alt="KCNyu live-desk architecture — Python builds reconciled market context, OpenClaw agents debate the trade, clawock contracts gate the decision, and a public scorecard closes the loop"></p>

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/decision-pipeline.svg" width="1016" alt="One clawock trading day, end to end — Python collects quotes through ordered fallback chains (HK Tencent + Eastmoney, then stooq, then yfinance; US Nasdaq first through a seven-route chain; USD/HKD Frankfurter, exchangerate.host, Yahoo), SEC and HKEX filings, Eastmoney capital flow, bilingual news, Reddit and influencer sentiment, and macro and catalyst calendars; it reconciles the book, computes portfolio risk, per-leg concentration, the leverage regime dial, quant factors, cross-sectional ranks and peer residuals behind a backtest gate, and holds risk caps, the entry gate, earnings quality, thesis drift and the news evidence graph as code gates; a preflight hands the agents one context pack, where four analyst lenses, a bull and a bear who must disagree, three risk voices and a judge write plan.json; a Python postflight validates it, books it in memory/decisions.jsonl, renders the brief card, sends WeChat and Telegram and publishes the dashboard; then code records what was executed with mark-followed, settles each episode on canonical bars, calibrates confidence, replays a shadow portfolio against buy-and-hold and publishes the scorecard, which the next brief reads; in dsh, Decision Mind shows real fills beside their plans and T+1 verdicts for a follow-up, while execution stays human"></p>

The author’s pre-open job starts at **08:03 HKT** on an OpenClaw schedule. Each job has three steps: `clawock … preflight` collects the files, the model writes, and `clawock … postflight` checks and publishes what it wrote:

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/openclaw-cron.png" alt="OpenClaw's live cron list on the desk host: nine clawock jobs (pre-open brief, HK and US session reports, intraday check-ins) with their cron expressions, the clawock preflight → postflight lifecycle each one runs, last status ok and run time" width="820"></p>

<sub>Rendered from the host's real <code>openclaw cron list --json</code> by <code>site/tools/shoot_openclaw_cron.js</code>; job ids, delivery targets and prompts are left out. The full timetable is the <a href="https://github.com/KCNyu/clawock/blob/master/docs/operations/cron-schedules.md">generated schedule</a>.</sub>

[How the desk works](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md) covers the information layers, run context, settlement rules and code gates.

## Try it in five minutes

Choose the agent you already use; each logo opens a runnable integration example. These are five alternative ways to use the same workflow, not five agents installed by the package.

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

For the investment workflow, use Python ≥ 3.11 and an agent that can read and write files. Start in an empty directory:

```bash
pip install clawock
clawock workflow install investment-decision --workspace ./my-book
clawock init ./my-book --workflow investment-decision
cd my-book && mkdir -p .clawock/work
clawock run prepare > .clawock/work/request.json
# your agent reads the installed skill and request, then writes decision.json
clawock run publish --request .clawock/work/request.json --artifact decision.json=decision.json
```

The model call and its costs stay in your runtime; clawock is free and open source. Add your own holdings and evidence for a real investment decision. This setup creates a workspace and validates a decision; it does not install the author’s data feeds, history or schedules. CI exercises these commands with a supplied example decision in a clean environment using [the installed wheel](https://github.com/KCNyu/clawock/blob/master/examples/cli/workflow-run/run.sh).

To test only preparation and publication without a model or credentials, clone this repository and run `bash examples/cli/minimal-run/run.sh` from its root. It creates a temporary environment and publishes a fixed test answer; `isolated run published <run_id>` confirms that basic check, not an investment analysis. You can also open a Codespace:

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

## Scope, disclaimer, and license

This repository holds **real trading positions**. It is one person's record and a workspace you can take with you. It is **not investment advice, a recommendation, or a copy-trading system**. clawock analyzes and proposes; it does not place orders for you. No result is hand-picked: the settlement rules and every change of method are versioned in code. The calls to act have not been shown to beat a coin flip, and every number may be out of date by the time you read it.

Original code is under the [MIT License](https://github.com/KCNyu/clawock/blob/master/LICENSE). Adapted third-party code keeps its own license and attribution in [NOTICE](https://github.com/KCNyu/clawock/blob/master/NOTICE) and [`THIRD_PARTY_LICENSES/`](https://github.com/KCNyu/clawock/tree/master/THIRD_PARTY_LICENSES). Third-party market data, news, social posts, filings, trademarks, and API access are **not** relicensed by MIT — see [Third-party data and services](https://github.com/KCNyu/clawock/blob/master/docs/legal/third-party-data.md).

Built with [Claude Code](https://claude.com/claude-code), the [openclaw](https://openclaw.com) cron daemon, a static Jekyll + GitHub Pages frontend, and Python. Market, news, macro, and sentiment come from documented public sources; see [third-party data and service terms](https://github.com/KCNyu/clawock/blob/master/docs/legal/third-party-data.md) before reusing any fetched content.

<div align="center">
<br>

**[Live dashboard](https://kcnyu.github.io/clawock/)** &nbsp;·&nbsp; **[Daily briefs](https://kcnyu.github.io/clawock/briefs.html)** &nbsp;·&nbsp; **[简体中文](https://github.com/KCNyu/clawock/blob/master/README.zh.md)**

<sub>Built and maintained by <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> and Rick · 2026</sub>

</div>
