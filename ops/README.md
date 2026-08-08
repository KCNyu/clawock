# Operations

Repository and host operations live here; none of this directory is part of the
portable `clawock` wheel.

- `pages/` reads the published generation, assembles the Jekyll source tree and
  stages the public allowlist used by GitHub Pages.
- `host/` installs the live CLI/watchdog launchers and reapplies the audited
  OpenClaw distribution patches after an upgrade.
- `system_check.py` audits the KCNyu live workspace before a master publish.

Market workflow semantics belong to `src/clawock/`; KCNyu-specific execution
belongs to `instances/kcnyu/`. Shell publishing and scheduler entry points still
under `scripts/data/` are the next migration boundary, not new operations APIs.
