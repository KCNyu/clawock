# Repository ownership: product, instance, operations and state

The terminal shape is a portable `clawock` product plus a separately installed
KCNyu live instance. Directory ownership is part of the product contract: no
generic script or data bucket is an acceptable final home.

## The deciding question

Ask whether a third party using clawock with their own agent, book and deployment
needs the behavior unchanged.

- **Yes: product.** Put it in a named domain under `src/clawock/` and expose it
  through the installed `clawock` CLI or an importable package API.
- **No, it is this investment desk's behavior: instance.** Put it in the
  separately packaged `instances/kcnyu/src/clawock_kcnyu/` adapter.
- **No, it wires a host, repository or delivery surface: operations.** Put it in
  the specific `ops/` domain that owns that external side effect.
- **It is generated or user-authored state:** keep it in the workspace data
  paths; never ship it in either wheel.

File size, language and test coverage do not decide ownership. Stable commands
are APIs; historical Python or shell paths are not.

## Evidence, strategy and instance rule

Investment strategy is a product capability, not an instance implementation.
Use this dependency direction for every new signal or strategy:

```text
market_data provider DTO -> decision strategy -> instance phase/render/delivery
```

- A provider fetches and normalizes attributable evidence and reports source
  degradation. It does not read a portfolio, choose an action, inspect reaction
  thresholds, size exposure, persist strategy state or alert a user.
- A strategy under `src/clawock/decision/` owns the reusable algorithm: portfolio
  scope, instrument look-through, signal state, risk/exploration contract and
  its bounded state. It accepts a generic workspace/book and explicit policy;
  it does not know KCNyu, OpenClaw, a delivery target or prose layout.
- An instance is a thin binding for phase wiring, deployment-only overrides,
  presentation and delivery. Do not move an algorithm into `instances/` merely
  because one live desk consumes it first.
- Consumers depend on public DTO/functions, never another feature's private
  constants, config rule IDs or module globals. For example, an information-first
  strategy must consume a primary-disclosure DTO rather than the internal
  `interrupt` classification of mover attribution.
- Resolve workspace paths when the phase is called. Import-time paths and default
  arguments derived from them bind a long-lived process to whichever workspace
  imported the module first.
- Skills explain how to consume the structured result. They must not redefine
  thresholds, sizing or state transitions already owned by Python policy.

The placement test is therefore not “does this mention a portfolio?” A portable
strategy is expected to operate on a caller's portfolio. The test is “would a
different clawock user need this algorithm unchanged?” If yes, it belongs in
the product; only the live deployment binding belongs in the instance.

## Canonical owners

| Path | Owner |
|---|---|
| `src/clawock/decision/` | decision records, risk governance, theses, entry/earnings lifecycle, signals and outcome evaluation |
| `src/clawock/portfolio/` | ledger math, reconciliation, FX, risk, integrity and shadow accounting |
| `src/clawock/market_data/` | portable providers, canonical bars, sessions, quotes, filings and market context |
| `src/clawock/evidence/` | provenance, run cards, research surface and public evidence generation |
| `src/clawock/context/`, `harness/`, `publish/`, `workflows/`, `adapters/` | runtime-neutral contracts, artifact protocol and cross-runtime integration |
| `instances/kcnyu/` | KCNyu schedule contract, harness phases, workflow outcomes, heartbeat and watchdog behavior |
| `ops/host/` | this host's cron, scheduler inspection, session maintenance and launcher wiring |
| `ops/publish/` | the only protected-branch and data-plane publisher implementation |
| `ops/ci/` | coverage and scheduled-workflow health used by GitHub Actions |
| `ops/growth/` | IndexNow, Nostr and project broadcast delivery |
| `ops/pages/` | Pages source/artifact assembly from the published generation |
| `site/` | static site and browser source |
| `portfolio.json`, `assets/data/`, `memory/`, `logs/` | live instance and generated state; never wheel contents |

`ops/` may call installed product and instance commands. Product code must not
import `ops/` or `clawock_kcnyu`. The public `clawock` wheel must not include or
depend on the KCNyu wheel. `clawock-kcnyu` is repository-only and must never be
published to PyPI.

## OpenClaw compatibility surface

OpenClaw requires selected Markdown and skill files at workspace-relative paths,
so root `AGENTS.md`, `TOOLS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md` and the
main-session context files remain at the repository root. Location compatibility
does not make old scripts APIs: those files instruct the runtime to use installed
`clawock` / `clawock-kcnyu` commands and the named `ops/` entry points only.

## Exact repository-root contract

[`config/root-allowlist.json`](../../config/root-allowlist.json) assigns every
tracked top-level path an owner and a named consumer. `ops/system_check.py`
compares that contract with the actual Git tree, so a new root script, SEO token
or unexplained directory is a critical finding rather than future cleanup.

The apparent root exceptions are intentional:

- OpenClaw context, memory, skills and the live ledger remain at path-sensitive
  locations until #380 proves a supported equivalent.
- `LICENSE`, `NOTICE` and `THIRD_PARTY_LICENSES/` remain standard legal/package
  entry points and are copied by Pages staging.
- Search verification files live under `site/`; the Pages allowlist publishes
  them at the public root without making the repository root their owner.
- `site/evidence.md` is generated by `clawock evidence` and staged into Pages; it is
  product evidence, not hand-maintained source.

## No generic script bucket

`scripts/data/` is gone. Dashboard aggregation and evaluation ship in named
public-package domains; KCNyu gold, influencer, intraday and GitHub-hosted LLM
automation ship in the separate instance distribution. Host, CI, publishing and
growth wiring live only under their named `ops/` owners. Do not recreate
`scripts/data`, add `ops/data`, or preserve an old-path shim.

## Publication boundary

The KCNyu harness may request a dashboard rebuild and publication, but the git
identity, retry and data-plane mechanisms belong only to `ops/publish/`. The
browser consumes the complete published generation; generated outputs are state,
not source-package data and not independently staged by arbitrary callers.
