---
name: openclaw-upgrade
description: Build and reinstall the desk's frozen OpenClaw fork. Use for an approved rebuild or recovery of its pinned revision. Do not use for upstream version changes or trading tasks. Supply the approved full commit and matching CI artifact.
---

# Frozen OpenClaw reinstall

Read [the frozen build runbook](../../docs/operations/openclaw-frozen-build.md).
Use its build, install and identity checks and record the actual smoke results.
Keep the current selection until the candidate passes. Report the failed check
and its artifact receipt when installation or smoke fails.

Example use is reinstalling the approved commit after host recovery. For
reclaiming disk space on a healthy install, use `openclaw-tune`.
