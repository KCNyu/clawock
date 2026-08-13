# Repository ownership: product, profiles, operations and state

The terminal shape is one portable `clawock` product, declarative profiles and
workspace state. A profile selects values and resources; it is not a Python
implementation boundary. Directory ownership is part of the product contract:
no generic script or data bucket is an acceptable final home.

## The deciding question

Ask whether a third party using clawock with their own agent, book and deployment
needs the behavior unchanged.

- **Yes: product.** Put it in a named domain under `src/clawock/` and expose it
  through the installed `clawock` CLI or an importable package API.
- **It is a desk-specific value or resource selection: profile.** Declare it in
  `config/profiles/` or a referenced workspace resource; do not add Python hooks.
- **No, it wires a host, repository or delivery surface: operations.** Put it in
  the specific `ops/` domain that owns that external side effect.
- **It is generated or user-authored state:** keep it in the workspace data
  paths; never ship it in the wheel.

File size, language and test coverage do not decide ownership. Stable commands
are APIs; historical Python or shell paths are not.

## Evidence, strategy and profile rule

Investment strategy is a product capability, not an instance implementation.
Use this dependency direction for every new signal or strategy:

```text
market_data provider DTO -> decision strategy -> package lifecycle -> runtime/provider boundary
```

- A provider fetches and normalizes attributable evidence and reports source
  degradation. It does not read a portfolio, choose an action, inspect reaction
  thresholds, size exposure, persist strategy state or alert a user.
- A strategy under `src/clawock/decision/` owns the reusable algorithm: portfolio
  scope, instrument look-through, signal state, risk/exploration contract and
  its bounded state. It accepts a generic workspace/book and explicit policy;
  it does not know KCNyu, OpenClaw, a delivery target or prose layout.
- A profile supplies declarative markets, policies, templates, schedules,
  resources and delivery selection. Phase wiring, rendering, watchdog behavior
  and reusable policy stay in `src/clawock/`; host and repository side effects
  stay in `ops/`.
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
the product. Only declarative values/resources belong in a profile, and only
host/repository wiring belongs in operations.

## Canonical owners

| Path | Owner |
|---|---|
| `src/clawock/decision/` | decision records, risk governance, theses, entry/earnings lifecycle, signals and outcome evaluation |
| `src/clawock/portfolio/` | ledger math, reconciliation, FX, risk, integrity and shadow accounting |
| `src/clawock/market_data/` | portable providers, canonical bars, sessions, quotes, filings and market context |
| `src/clawock/evidence/` | provenance, run cards, research surface and public evidence generation |
| `src/clawock/context/`, `harness/`, `automation/`, `publish/`, `workflows/`, `providers/` | complete lifecycle, scheduling/watchdogs, strategies, artifact protocol and runtime integrations |
| `config/profiles/` | declarative profile values, resource references, schedules, locale/templates and delivery selection |
| `ops/host/` | this host's cron, scheduler inspection, session maintenance and launcher wiring |
| `ops/publish/` | the only protected-branch and data-plane publisher implementation |
| `ops/ci/` | coverage and scheduled-workflow health used by GitHub Actions |
| `ops/growth/` | IndexNow, Nostr and project broadcast delivery |
| `ops/pages/` | Pages source/artifact assembly from the published generation |
| `site/` | static site and browser source |
| `portfolio.json`, `assets/data/`, `memory/`, `logs/` | live instance and generated state; never wheel contents |

`ops/` may call installed `clawock` commands. Product code must not import
`ops/`. There is no executable instance package: adding a desk means supplying
a profile and its referenced data/resources, never a second Python owner.

## OpenClaw compatibility surface

OpenClaw requires selected Markdown and skill files at workspace-relative paths,
so root `AGENTS.md`, `TOOLS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md` and the
main-session context files remain at the repository root. Location compatibility
does not make old scripts APIs: those files instruct the runtime to use installed
`clawock` commands and the named `ops/` entry points only.

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

`scripts/data/` is gone. Dashboard aggregation, evaluation, market refresh,
intraday lifecycle and GitHub-hosted LLM automation ship in named `clawock`
domains. Host, CI, publishing and growth wiring live only under their named
`ops/` owners. Do not recreate
`scripts/data`, add `ops/data`, or preserve an old-path shim.

## Publication boundary

The package-owned harness may request a dashboard rebuild and publication, but the git
identity, retry and data-plane mechanisms belong only to `ops/publish/`. The
browser consumes the complete published generation; generated outputs are state,
not source-package data and not independently staged by arbitrary callers.
