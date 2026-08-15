# Examples

Runnable proofs that `clawock` works as an installed package rather than as this
checkout. Each one is executed by CI, so an example that stops working fails a
required check instead of quietly rotting into documentation.

| example | what it proves |
|---|---|
| [`minimal-run/`](minimal-run/) | a clean virtualenv installs the wheel and finishes one complete run — `init` → `run prepare` → `run publish` — with no checkout, no Git, no OpenClaw and an emptied environment |
| [`harness-agnostic/`](harness-agnostic/) | one decision run driven from five harnesses — pure CLI, OpenClaw skill, Claude Code instruction, Codex AGENTS.md, DeepSeek Harness agent — with the same files-and-CLI contract throughout |
| [`profiles/`](profiles/) | a second desk can select markets, workflows, resources, policy, presentation and delivery declaratively, without a Python instance package |

## Why they are files and not workflow steps

The claim these support is that someone else can use the package. A check that
only exists inside `release.yml` cannot be run by that someone, so it proves the
package works for GitHub and nothing more. `release.yml` calls
`examples/minimal-run/run.sh`; there is one copy, and it is the copy a reader
can execute.
