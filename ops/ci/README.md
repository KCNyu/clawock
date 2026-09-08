# CI operations

Repository health tools run by GitHub Actions: coverage gating/badge generation,
scheduled-workflow health, and the generated command catalog in
`docs/reference/commands.md` (`python3 ops/ci/generate_tool_reference.py`,
`--check` to fail on drift). They report on package and profile behavior but
are not runtime APIs and do not belong in the wheel.

`backstop_rehearsal.py` answers one question daily from `cron-health.yml`: did
`brief-fallback.yml`'s weekly drill last prove the off-host brief chain works?
Every other run of that workflow is a no-op skip, so its green ticks say
nothing — `--strict` reddens only on a *determined* dead backstop and never on
a `gh` lookup failure.
