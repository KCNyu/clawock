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

You hold stocks in Hong Kong or the US, and you already use an AI agent such as Claude Code, Codex or OpenClaw. clawock gives that agent a daily routine around your positions. Each morning it reads what Python collected overnight, argues for and against every position, and hands you a plan: what to do, at what price, and at what price the idea is dead. **You place the orders.** After the close, code marks each plan right or wrong, and the next morning's plan is written with that result in front of it.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/rsi-loop.svg" width="1016" alt="clawock on one page: eight source layers arrive through fallback routes; Python reconciles the book and certifies one context pack; Claude Code, Codex, OpenClaw, DeepSeek Harness or your own CLI argues a bull and a bear case over it; code reviews concentration and enforces the configured risk boundaries, records what happens when one breaks and enforces evidence requirements; the plan reaches you and you place the orders; code settles each call as a win, a loss or ungradeable; the record returns around two loops, one into the next judgment through history and earlier-date calibration, one into the evidence rules through a bounded proposal and a named review; on the author’s host patrol rounds, a filing gate, background agents and required CI maintain the desk’s own code, watched from DeepSeek Harness"></p>

**That loop is what RSI, Recursive Self-Improvement, means here.** Every decision leaves behind the evidence it used and the result it got, and the next decision reads both. **It is not a promise of returns.** So far, the calls that told the author to act have not been shown to beat a coin flip. What you get is a record that keeps growing and that you can check line by line.

One real call runs through this page: Goldwind (`02208`, Hong Kong) on the morning of 2026-10-08. The plan said watch, and act only above 8.97. By the next close the stock was 4.22% lower, and the public ledger says `loss` beside it. The sections below keep coming back to that morning.

Every number in that plan was computed by [a plugin, one line of configuration each](#everything-that-computes-is-a-plugin-what-a-result-may-do-is-not). A strategy may [search for better settings of its own](#a-strategy-can-search-its-own-parameters-adopting-them-is-a-reviewed-edit), but all it can produce is a proposal for a person to review. Want to run it first? [Try it in five minutes](#try-it-in-five-minutes).

## Everything that computes is a plugin; what a result may do is not

Start with the Goldwind call. The author's account holds 400 shares of Goldwind (`02208`, Hong Kong) at an average cost of 14.084. Here is everything that happened to that stock on the morning of 2026-10-08. One word first: every number clawock computes comes from a plugin, and each plugin is one line in `config/strategy-plugins.json`. This page calls such a line a **row**.

1. **A row computed its numbers.** The `factors` row read Goldwind's daily bars and produced one line about it: trend off, price 31.8% under its 200-day average. A row does this and nothing more. It turns inputs into a reading.
2. **The model argued both sides over that reading.** Bull: it is the only one of its peers with a confirmation price you could act on, and the book has almost nothing that is not Hong Kong tech or AI. Bear: trend off, 31.8% under the average, in a book with four risk limits already tripped; that is adding the weakest position on the weakest evidence. The judge: watch, and write the trigger down before the price gets there.
3. **The plan was specific enough to be wrong.** Watch. Act only if it trades above 8.97 within five sessions. The idea is dead at 8.923. Confidence 0.34.
4. **Code settled it.** Not the model, and not the row. The reference was 8.645, the first price it could have traded at after the plan was published. By the close of the next session it was 4.22% lower. Outcome: `loss`.
5. **The loss went back in.** It is decision `dec-6d9e8bdc8817` on the public ledger, and the track record the next brief reads counts it.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/strategy-plugins.svg" width="1016" alt="One real call, Goldwind on 2026-10-08, in five numbered steps. 01: the factors row, drawn as a module in its socket with an empty socket beside it for a row of your own, computed one reading: trend off, 31.8% under its 200-day average. 02: the model argued a bull case and a bear case over that reading. 03: the plan on paper: watch, act only above 8.97 within five sessions, dead at 8.923, confidence 0.34, contested. A line marked &quot;not rows from here down&quot;. 04: Goldwind's eight daily bars to 2026-10-09 with the act and dead prices ruled across them; code took the open of 2026-10-08, 8.645, as the reference, marked the next close, 8.28, 4.22% lower and called it a loss. 05: the entry as the ledger stores it, dec-6d9e8bdc8817, outcome loss. No row can mark its own call, pick a kinder reference price, turn the loss into something else or keep it off the ledger."></p>

**What you can swap is step 1.** Replace the `factors` row with your own and Goldwind's line is computed another way: a different average, a different window, a different data source. Steps 4 and 5 do not move, because they are not rows. No row can mark its own call, pick a kinder reference price, turn that `loss` into something else or keep it off the ledger. Two strategies can be compared on one record for that reason: the code that judged this call is the code that would judge theirs.

Each row sits in one socket, and what goes into your harness stays small: one skill, one CLI and a JSON contract. Your agent keeps its model, its conversation and its tools.

**A row has to say what it measures.** A row whose readings reach a decision is not mounted until it has declared its inputs, the unit and window of every output, and what it holds when it cannot measure. None may hand back yesterday's reading as today's.

| Row | Measures | When it cannot measure |
|---|---|---|
| `factors` | trend, momentum, RSI, volatility and the exit line per name, from daily bars. Goldwind's "31.8% under" came from here | the field is empty; with fewer than 30 daily bars there is no line at all |
| `bar-signals` | how costly a name is to trade and how much it is likely to move, per session | empty, never zero: "could not be estimated" is not "cheap to trade" |
| `sentiment` | Reddit mentions over seven days, and statements by named public figures | the block is left out, and says whether the scan is missing, too old or unreadable |
| `morning-scans` | the macro snapshot and Chinese-language news, and the one read of every scheduled scan file | the same: left out, with the reason |
| `strategy-scores` | where each name ranks under each research strategy's current setting; reference only | says it is unavailable and why |

**A broken row fails alone.** If one row does not load, the runs that needed it stop and name it. The others carry on.

**Your own row.** A row points at an installed Python module, so it can be yours: one `apply(ctx, config)` function, a declaration of what it reads, one line of configuration. That gets it a socket. It gets it no say over steps 4 and 5. A row is ordinary Python running with your own permissions, not a sandbox, so install only modules you trust.

**The whole system is hot-pluggable, the way dsh is.** Twenty rows in one file: thirteen the brief, the report and the intraday check compute with, and seven the strategy lab mounts for research. Pull one out while the rest run and only the rows that said they need it stop and wait; push it back and they start by themselves. Change a row's setting and that row restarts under the new one. It is the design [dsh](https://github.com/KCNyu/clawock/blob/master/examples/dsh/README.md) plugins are built on, restated in Python.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/plugin-system.svg" width="1016" alt="The whole plugin system in seven numbered parts. 01: whatever agent runs the desk, Claude Code, Codex, OpenClaw, dsh or any CLI, runs the brief, report, intraday and strategy-lab commands. 02: one file, strategy-plugins.json, lists every row: thirteen live rows and seven research rows, each an id, a module and its settings. 03: the host mounts every row in a socket; all twenty are shown by name, with the research row bars pulled out of its socket and one empty socket for a row of your own. 04: pulling bars undoes its one registration, the optimizer row that declared it needs bars waits, and the other five rows are never stopped; pushed back in, the optimizer starts by itself. 05: changing a setting, the adjustment on the daily-bars row from qfq to raw, stops that row and starts it again under the new setting. 06: the five primitives dsh is built on beside their names here: a row in a file, a fiber, provide and inject, effect, update. 07: what has no socket: settlement, the ledger and the risk limits."></p>

```bash
clawock strategy-lab list       # every row, what it provides and what it is waiting for
clawock strategy-lab sources    # each row's inputs, units, windows and missing-data rule
```

[Strategy plugins: kernel, rows, declarations, events and boundaries](https://github.com/KCNyu/clawock/blob/master/docs/architecture/strategy-plugins.md) · [writing a plugin outside this repository](https://github.com/KCNyu/clawock/blob/master/docs/architecture/strategy-plugins.md#writing-a-plugin-outside-this-repository).

## Any harness, one decision contract that accumulates evidence

Say you use Claude Code today and switch to Codex next month. You do not start over, because clawock was never inside the chat. It is one skill (`investment-decision`), one command line tool and a handful of files in your workspace. Any agent that can read a file, write a file and run a command can pick them up: **Claude Code / Codex / OpenClaw / DeepSeek Harness / your own script**.

Your agent keeps what is its own: the model, the conversation, its memory, its research tools, your credentials and your permissions. clawock never starts a model. It does four jobs around your agent: it pins down what went in, checks what came out, marks the result later, and keeps the record.

These are the files. You meet the first, second, fifth and sixth in your own harness. The other two are written by the author's daily setup.

| File | Written by | What it holds |
|---|---|---|
| `request.json` | clawock, when you run `clawock run prepare` | the material for this decision, with a fingerprint of every document so it cannot be swapped afterwards |
| `decision.json` | your agent | its answer: the case for, the case against, the action, and what would prove it wrong |
| `plan.json` | the author's setup, every morning | the same answer for a whole portfolio, one entry per position |
| `decisions.jsonl` | the author's setup | the public ledger: one line per decision, with the result added once code has marked it |
| `outcome.json` | you, once the waiting period is over | the prices you saw and where you got them |
| `evaluation.json` | clawock, when you run `clawock workflow evaluate` | whether the direction was right. It is not money made |

**“Smarter with use” means this pile of files grows.** The model does not change. What changes is what the next decision can read: the evidence behind earlier decisions, what you actually did, how each one turned out, and how far earlier confidence figures could be trusted. When you switch agents, point the new one at the same workspace and it carries on from the same files. A brand-new workspace starts empty. It does not come with the author's data feeds, schedules or history; those you connect yourself.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/product-architecture.svg" width="1016" alt="clawock product architecture — external runtimes own models, conversation, memory and tools while the package supplies portable workflows, certified context, deterministic reconciliation, evaluation and bounded improvement"></p>

[Portable invocation and feedback protocol](https://github.com/KCNyu/clawock/blob/master/docs/architecture/runtime-protocol.md#evaluate-and-improve-without-owning-the-agent) · [Workflow improvement boundaries](https://github.com/KCNyu/clawock/blob/master/docs/architecture/harness.md#ownership).

## Information in: sources before opinions

It is 08:03 on 2026-10-08. The morning job has just started and no model has run yet. Python has already fetched Goldwind's daily bars from Tencent, looked for a company filing, and asked Google News for headlines about it. Four headlines came back. Two had nothing to do with Goldwind. The other two were published before the previous close, so they were labelled old news. No primary financial filing could be reached.

The brief said exactly that, in two lines under `02208`. The primary financial disclosure was “not fetched”. And: “this stock has no usable news evidence today, so today's judgment rests entirely on price and relative strength.”

That is the rule this section is named after. **Sources are collected and labelled before anyone has an opinion.** In practice it comes down to three habits:

- **Every source has a backup.** Quotes come through Tencent or Nasdaq first and fall through to the next provider when one fails. Filings come from the SEC and HKEX, capital flow from Eastmoney, and there is news in Chinese and English, macro data and sentiment. Python then reconciles your book, the exchange rate and the risk numbers.
- **Old news is not passed off as new.** Anything published before the previous close is labelled as old.
- **A failed source says “not fetched”, never “no news”.** Hong Kong has the basic coverage, but **its research breadth is behind US**.

**What your agent receives is a pack of files.** On the author's setup, `preflight` writes the files this judgment needs, plus reference files the agent can open when it wants more. The Goldwind decision still carries the id of the pack it was made from, `c3f65a7beaebb24e`, so anyone can look up which batch of material stood behind it. In your own harness, `clawock run prepare` writes `request.json`: the same kind of pack, with a SHA-256 fingerprint of each document and of the whole, and the workflow version it was prepared for.

**The fingerprint proves which material was used. It does not prove a news story is true.** Each citation carries its source and the time it was published or observed. The passwords for your data sources and your model API key stay in your own runtime and never enter the public repository. In your own harness, your agent may also add evidence from its own research tools, as long as it can be traced. The author's scheduled jobs read only the files Python assembled.

**The live desk’s full information and delivery flow**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/information-flow.svg" width="1016" alt="clawock data flow — eight information layers feed ordered fetch-fallback routes; Python reconciles the book and builds risk; the brief, session reports and intraday check-ins each run a preflight that assembles only the blocks that run can use; the agent reads those files and never fetches; a Python postflight validates, then publishes to master, to the data-plane branch the dashboard polls, and to WeChat and Telegram, with an LLM-free crontab watchdog as the delivery backstop"></p>

[Information layers and source catalog](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#the-information-layer) · [Certification protocol](https://github.com/KCNyu/clawock/blob/master/docs/architecture/runtime-protocol.md).

## Decision out: both sides read the same evidence

The question that morning was simple: is it time to add to Goldwind? The agent is not allowed to answer with a feeling. It has to write the case for, then the strongest case against, and only then an action, the price that triggers it, a confidence figure and the condition under which it admits being wrong. Both sides argue from the same pack of files.

What reached you was one line in the 08:03 brief: after the 09:30 open, act on `02208` only above 8.97, valid for five sessions; back under 8.923, give up at once. During the session, intraday cards compare fresh quotes with that morning's trigger. Goldwind's high that day was 8.71. The price never got to 8.97, so there was nothing for you to do.

**You get a plan and a receipt.** The author's setup leaves the daily brief and `plan.json`. In your own harness, your agent writes `decision.json` and you run `clawock run publish`. Python then checks four things: every claim points at a document in the pack, there is a case against, there is a condition that would prove the call wrong, and any order and currency arithmetic adds up. If all four hold, you get a receipt tied to that exact pack. If the case against is missing, publication is refused. A verdict reached in conversation on the author's setup enters the ledger with `clawock record --source <harness>`. Either way, you decide which orders to place.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/decision-card-example.png" width="640" alt="A clawock decision receipt: the subject, a bull case and a bear case each citing evidence, the thesis, the invalidation condition, confidence and action, and a published run id with a pinned certificate"></p>

<sub>Example output, not a settled call.</sub>

**The live desk’s full bull / bear debate**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/debate-flow.svg" width="1016" alt="clawock's multi-agent debate — one evidence pack feeds four analyst lenses; two researchers argue opposing bull and bear cases and record where they disagree; three risk voices and a judge name the strategy frame and resolve it into plan.json, which enters the next session's grading loop"></p>

On the author's setup this debate is split between several roles: four analysts, a bull and a bear researcher, three risk voices, and a judge who names the strategy behind each call. It is adapted from [TradingAgents](https://github.com/TauricResearch/TradingAgents). In your own harness, the one agent you already have is held to the same two requirements: read the same evidence, and write a case against.

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

Method proposals now retain frozen inputs and versioned forecasts; [method evaluation](https://github.com/KCNyu/clawock/blob/master/docs/architecture/decision-architecture.md#method-records-and-evaluation) separates payoff from hit rate and supports prospective comparisons without automatic promotion.

**From an open proposal to evidence about the method**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/proposal-review.svg" width="1016" alt="One real open proposal, MiniMax on 2026-10-12, in five numbered steps. 01: the model proposes to trim 20 shares if the price trades above 225 within one session, and forecasts with probability 0.55 a close under 213 on the fifth session. 02: code reviews it on three channels; facts and feasibility could refuse it and did not, the strategy channel can only object and objected twice: a sale without an escalated event, an active move without a catalyst. 03: every outcome is kept in the method record: published, published over an objection, refused, unpublished; this one was published with its objections attached. 04: the record is read on two separate axes: its payoff is not triggered, because it never traded above 225, and whether 0.55 was right is scored on its own. 05: a comparison of old policy, observations only and policy reference is frozen before it starts, with first records on 2026-10-13, on the same capital and costs, with a missing mark left as a hole. No automatic promotion, sizing or orders."></p>

## A strategy can search its own parameters; adopting them is a reviewed edit

Stay with Goldwind. One of the numbers the desk computes for it is RSI, and the row that computes it has a setting: look back 14 sessions, and read a low value as a rebound coming. Is that the right setting? Every morning after the brief, the strategy lab asks, on all 28 names it has prices for, Goldwind among them.

1. **It tries only what was declared.** The row lists its settings in advance: six look-back lengths, two ways of reading the number. Twelve in all, and all twelve are counted, so a lucky one cannot be passed off as the only one tried.
2. **A gate judges the best of them.** It needs enough days it was not tuned on, a ranking that beats chance and beats the current setting by a margin that is not noise, a low chance of having been fitted to the past, and prices adjusted for splits and dividends. A configuration line can make this gate stricter. It cannot make it looser than the floor in the code.
3. **Second opinions may object.** Other thresholds judge the same run, for example after trading costs. They can block. They cannot pass what the gate refused.
4. **The verdict is written down.** Every run goes to a ledger, and the ledger is checked against these rules each time it is read.
5. **Then it has to keep working.** A setting that passes is registered, and from then on it is scored only on days that had not happened when it was picked.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/strategy-evolution.svg" width="1016" alt="One real search of a strategy's own setting, RSI on 2026-10-12, in five numbered steps. 01: the rsi row as the file holds it, today's setting and the settings it may try, and those twelve as a grid of six look-back lengths by two ways of reading the number; the row today is on 14 sessions read as a rebound, the search picks 28 sessions read as strength continuing. 02: a gate judges the best of them on five checks, each with what was measured and what it needs: 705 sessions against at least 60, a range of 0.0171 to 0.1117 against chance and 0.0408 to 0.2195 against today's setting, both above zero, 0.0 against a ceiling of 0.5, adjusted prices. 03: two second opinions, after trading costs and on the statistics alone, would pass it. 04: the ledger holds two entries, a candidate on all 28 names and a refusal on the 16 whose prices were confirmed as adjusted, because that range, -0.043 to 0.0529, crosses zero. 05: only later sessions count from here, 0 of 60 so far; the edit to the row, 14 sessions to 28, has not been proposed, and the row keeps 14 sessions until a person reviews one."></p>

On 2026-10-12 the answer for RSI was: a 28-session look-back, read as "strength continues", would have ranked these names better. The gate passed it and it was registered. **The same search on the 16 names whose prices the provider confirmed as adjusted, Goldwind one of them, was refused.** The result leans on the other 12, where all the lab has is one provider's record showing no split or dividend, and no second source to check it against. Every run now carries that second search, so a passing setting says for itself whether it survives it.

**What did this change for Goldwind? Nothing.** The next brief still showed its RSI under 14 sessions, read as a rebound, because that is what the row says. Changing the row is an edit a person reviews. The most the lab can do is propose that edit, and only after the new setting has held up on at least 60 later sessions and passes the check it currently fails. So far it has been scored on none, and nothing has been proposed.

```bash
clawock strategy-lab evolution rsi   # each run, what changed, each registration and how it has done since
clawock strategy-lab row-edits       # edits the lab has proposed, for review
clawock strategy-lab verify          # the ledger against the lab's limits
```

[What a search may conclude, second opinions and the lab's limits](https://github.com/KCNyu/clawock/blob/master/docs/architecture/strategy-plugins.md#boundaries).

## What the model is not allowed to do

The model writes opinions. The arithmetic that could corrupt the record runs in
Python and is unit-tested. Concentration reviews, configured risk boundaries, breach handling, and evidence requirements are panel 04 of the overview at the top.

[All twelve rules, and what the code does for each](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.md#what-the-code-enforces).

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

The author’s host runs its own maintenance through the same queue (panel 09 of the overview): a patrol round audits what the desk published, a filing gate opens an issue only for a finding it could prove, a background agent takes the fix through a PR and required CI, and an issue closed as noise lowers that kind of finding next time.

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
