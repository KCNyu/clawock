# clawock-kcnyu

This repository-only distribution is the KCNyu live HK + US desk adapter for
`clawock`. It is not published to PyPI, is not a dependency of `clawock`, and
is not installed by ordinary `clawock` users.

During the migration this distribution still hosts live-market phases, delivery
and watchdog code. That location is not evidence that the logic is KCNyu-only:
reusable investment providers and strategies — including portfolio scope,
look-through, signal state and sizing contracts — belong in `clawock`, while
reusable OpenClaw integration belongs to a runtime adapter. This distribution
must shrink to KCNyu-specific configuration and bindings such as phase wiring,
delivery targets, live schedules and repository publication. It must not become
a second strategy package.

OpenClaw remains the external runtime that owns model calls, chat, memory, tools
and cron scheduling. Portfolio ledgers and generated artifacts remain in the
configured workspace and are never packaged into either wheel. Production phase
calls use the stable `clawock` CLI and Python entry points; repository source
wrappers were retired after the installed-command cutover.
