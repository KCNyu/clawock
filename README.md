<div align="center">

<h1><img src="assets/logo-lockup.svg" alt="clawock" height="48"></h1>

### Install decision intelligence into any agent.

Evidence-first investment workflows, deterministic money reconciliation, outcome-linked evaluation, and bounded improvement — without replacing your agent runtime.

[![Dashboard](https://img.shields.io/github/deployments/KCNyu/clawock/github-pages?label=LIVE%20PROOF&style=flat-square&logo=githubpages&logoColor=white&labelColor=252b35&color=4b91c8)](https://kcnyu.github.io/clawock/)
[![Tests](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=CONTRACTS&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![Dashboard Data](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/dashboard-artifact-gate.yml?label=DATA&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/dashboard-artifact-gate.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-aab5bf?style=flat-square&labelColor=252b35)](LICENSE)

[**Quickstart**](#quickstart) · [**Architecture**](#architecture) · [**OpenClaw adapter**](#openclaw-is-the-first-production-adapter) · [**Live KCNyu proof**](https://kcnyu.github.io/clawock/) · [**简体中文**](README.zh.md)

</div>

## What clawock is

clawock is an **agent-native investment decision-workflow plugin kit with a
verifiable harness**. An external runtime such as OpenClaw, Hermes, Claude Code,
Codex, or another tool-capable agent owns the model call, conversation, memory,
planning, tools, permissions, and credentials. It installs or calls clawock to
make an investment decision follow a portable, inspectable contract.

The first workflow turns evidence into a bounded decision and preserves the
lineage afterwards:

```text
evidence + opposing case
          │
          ▼
 thesis + invalidation ──► decision ──► execution/outcome
          │                    │                │
          └──── certified context + deterministic money/FX ────┘
                                                   │
                                                   ▼
                              reviewable improvement proposal
                               └─ accept / reject / rollback
```

This is not a trading bot, broker, model router, or another agent framework.
clawock does not decide which model to call and does not execute trades. Its job
is to make the workflow and its financial truth portable across agents.

## Why this layer exists

Agents are good at reading ambiguous evidence and forming a view. They are poor
authorities for arithmetic, provenance, and grading their own decisions. A
broker can provide transaction records; a generic observability product can log
tool calls. Neither, by itself, forces the complete investment-decision loop.

clawock adds four domain-specific properties:

- **A decision must survive opposition.** Supporting evidence alone is
  insufficient; the artifact must carry a genuine opposing case and explicit
  invalidation conditions.
- **Money is settled by code.** Orders, currencies, FX timestamps, fees, cash,
  and P&L are structured inputs to deterministic validation rather than prose
  the model can reinterpret.
- **The record continues after the answer.** Workflow version, certified input,
  decision, execution, and observed outcome share one lineage.
- **Improvement is bounded.** Outcomes may propose changes to declared
  evidence/provenance parameters. A proposal is reviewed, versioned, and
  reversible; it cannot silently rewrite strategy or the external agent.

## Installation status

The package builds and runs as a non-editable wheel outside this repository.
Until the trusted-publishing release in [#379](https://github.com/KCNyu/clawock/issues/379)
is complete, install the current pre-release directly from GitHub:

```bash
python -m pip install "clawock @ git+https://github.com/KCNyu/clawock.git"
clawock --help
```

`pip install clawock` is intentionally not advertised yet: the PyPI project has
not been published. The release workflow will use PyPI trusted publishing and an
isolated-index install smoke before this section changes.

## Quickstart

The following smoke uses the packaged example artifact, so it proves the
workflow lifecycle without pretending that clawock made a model call:

```bash
clawock workflow install investment-decision --workspace ./decision-demo
clawock init ./decision-demo --workflow investment-decision

request_path=$(clawock run prepare --workspace ./decision-demo \
  | python -c 'import json,sys; print(json.load(sys.stdin)["request_file"])')

cp ./decision-demo/.agents/skills/investment-decision/assets/decision.example.json \
  ./decision-demo/decision.json

clawock run publish \
  --workspace ./decision-demo \
  --request "$request_path" \
  --artifact decision.json=./decision-demo/decision.json
```

The receipt correlates the certified request, workflow version, validated
artifact, and immutable generation directory. In real use, replace the `cp`
line with your external agent producing `decision.json` from the same request
and installed skill.

### The external-agent contract

An adapter does not copy the business rules. It needs only to:

1. run `clawock run prepare` and read the emitted request JSON;
2. expose the installed `investment-decision` skill to its agent;
3. have the agent write `decision.json` without changing the request; and
4. run `clawock run publish` with that request and artifact.

clawock validates the output and publishes the receipt. The runtime remains the
only component that can call a model or use its conversation, memory, and tools.

## What ships in the workflow

`clawock workflow show investment-decision` prints the packaged contract.
Version 1.1.0 currently includes:

- a standard `SKILL.md` plus runtime-neutral references and JSON Schemas;
- certified context documents and a workflow certificate;
- supporting and opposing evidence requirements;
- thesis, invalidation, bounded action, order, currency, and FX fields;
- deterministic decision and outcome validation;
- generation-pinned artifacts and local publication receipts; and
- evaluate, propose, review, apply, and rollback commands for bounded changes.

The workflow does not invent a quant factor, catalyst, signal, entry, exit, or
portfolio rule. Those belong to the user's existing strategy and evidence.

## Bounded improvement, not autonomous self-rewriting

```text
decision + observed outcome
            │
            ▼
 clawock workflow evaluate
            │
            ▼
 evidence-linked proposal
            │
      review exact diff
       ┌────┴────┐
    reject     accept ──► apply ──► rollback record
```

Only declared workflow parameters can change. Applying a proposal requires an
accepted review record; rollback restores the prior parameters. Production
instructions, agent memory, model policy, and investment strategy never mutate
implicitly.

## Architecture

![clawock product architecture — external agent runtimes own models, conversation, memory and tools while the clawock package supplies portable workflows, certified context, deterministic reconciliation, evaluation and bounded improvement](assets/product-architecture.svg)

```text
┌──────────────────────────────────────────────────────────────┐
│ External agent runtime                                      │
│ OpenClaw · Hermes · Claude Code · Codex · others             │
│ model · chat · memory · planning · tools · permissions       │
└───────────────────────────┬──────────────────────────────────┘
                            │ installs Skill / calls CLI + JSON
┌───────────────────────────▼──────────────────────────────────┐
│ clawock product (`src/clawock/`)                             │
│ workflows · certified context · artifact contracts          │
│ deterministic validation/reconciliation · evaluation        │
│ generation receipts · bounded proposal/review/rollback       │
└───────────────────────────┬──────────────────────────────────┘
                            │ adapter-owned I/O
┌───────────────────────────▼──────────────────────────────────┐
│ User instance                                                │
│ strategy · evidence · ledger · schedules · delivery · UI     │
└──────────────────────────────────────────────────────────────┘

KCNyu production instance today:
OpenClaw scheduler ─► KCNyu adapter ─► clawock contracts
                  └► reconciled ledger ─► data plane ─► Pages
```

The lower box is not part of the wheel. The public KCNyu dashboard is one live
instance and proof surface, not the reusable product.

### Repository map

```text
src/clawock/        installable product, schemas, workflow pack, adapters
tests/              expensive-invariant and installed-wheel contracts
scripts/harness/    transitional KCNyu lifecycle adapter
scripts/data/       mixed migration inventory; classified product vs instance
scripts/ops/        host/operator entry points
config/             KCNyu instance configuration (product schemas moved out)
skills/             OpenClaw instance skills; runtime path remains stable
memory/             KCNyu ledger, outcomes, research state, and OpenClaw memory
assets/ + *.html    current Pages source and generated dashboard surface
```

This map is deliberately honest about the remaining overlap. The target
product/instance/site/operations separation is tracked in
[#381](https://github.com/KCNyu/clawock/issues/381); root OpenClaw context files
will not move until prompt, memory, skills, tools, cron, and delivery parity are
proven.

## OpenClaw is the first production adapter

The live instance uses OpenClaw for interactive chat and eleven isolated
scheduled jobs. clawock records separate context profiles for interactive chat,
isolated cron, heartbeat, and bootstrap behavior, including memory and skill
discovery rather than treating five Markdown files as the whole context.

Runtime paths are configurable through the OpenClaw adapter. The package never
silently narrows OpenClaw's tool set, and it leaves these runtime responsibilities
with OpenClaw:

- normal conversation history and startup context;
- `AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, and `USER.md` injection;
- `MEMORY.md`, dated memory, indexing, and search;
- skill catalog discovery and selected `SKILL.md` loading;
- tool schemas, permissions, heartbeat, bootstrap, cron, and delivery.

See [the adapter contract](docs/architecture/openclaw-adapter.md) and
[`clawock context audit`](docs/architecture/harness.md). A real OpenClaw
scheduler canary has called the packaged workflow successfully; the complete
market-schedule cutover remains open in
[#380](https://github.com/KCNyu/clawock/issues/380).

## The KCNyu live proof

[The public dashboard](https://kcnyu.github.io/clawock/) operates a real HK + US
portfolio workflow. It is useful because it exposes decisions, losses,
reconciliation, and outcome history instead of presenting a polished sample.
Human ownership remains at the execution boundary.

<p align="center"><a href="https://kcnyu.github.io/clawock/"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/assets/dashboard.gif" alt="KCNyu clawock dashboard cycling through its live proof surfaces" width="300"></a></p>

- [Live dashboard](https://kcnyu.github.io/clawock/)
- [Published briefs](https://kcnyu.github.io/clawock/briefs.html)
- [Evidence and refutation](https://kcnyu.github.io/clawock/evidence.html)
- [Cron contract](docs/operations/cron-schedules.md)
- [Product vs instance classification](docs/reference/product-vs-instance.md)
- [KCNyu live-instance architecture](assets/architecture.svg)

Nothing in the live portfolio is a recommendation, return claim, copy-trading
service, or proof that a workflow has market edge.

## Current boundary — no inflated claims

Implemented and demonstrated:

- package-native `init`, workflow install/discovery, `run prepare`, and
  `run publish` from a wheel outside the source checkout;
- evidence/opposition/decision/outcome schemas and deterministic money/FX checks;
- explicit proposal review, apply, and rollback;
- configurable OpenClaw runtime paths and a real isolated-scheduler canary; and
- a live portfolio/data/dashboard instance with fail-closed publication.

Still required before calling clawock a fully delivered standalone harness:

- a published TestPyPI/PyPI release and isolated public-index install;
- the same real workflow executed by a documented non-OpenClaw runtime;
- extraction of the remaining KCNyu compatibility phases from `scripts/harness`;
- physical instance/site/operations separation; and
- full OpenClaw market-cron cutover and adjacent before/after context parity.

The terminal delivery plan and evidence requirements live in
[#378](https://github.com/KCNyu/clawock/issues/378).

## Development

```bash
git clone https://github.com/KCNyu/clawock.git
cd clawock
python -m pip install -e '.[test]'
python -m pytest -q tests/test_wheel_contains_the_package.py
```

The project deliberately prioritizes installed-wheel behavior, financial
reconciliation, and live receipts over decorative test counts. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License and risk

MIT licensed. See [LICENSE](LICENSE), [NOTICE](NOTICE),
[third-party data terms](docs/legal/third-party-data.md), and
[third-party notices](THIRD_PARTY_LICENSES/README.md).

clawock is research software, not financial advice. It does not place trades or
guarantee accuracy, availability, or returns. Keep human approval, broker-side
controls, and independent reconciliation around any real-money use.
