# CLAUDE.md

Follow `AGENTS.md`. It is the single instruction file for this repository; this file adds
only what is specific to Claude Code.

- Keep the coding-agent identity. `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md` and
  `INVESTMENT_SOP.md` configure the OpenClaw investment assistant; read them only when
  the task is about that assistant's behaviour.
- Skill and tool routing is in `TOOLS.md`. Read `portfolio.json` only when the task needs
  positions or prices.
- Durable memory stays in Claude Code's own store outside this repository. Do not write
  notes under `memory/`, and do not add a second startup scan or memory pipeline on top
  of Claude Code's auto-memory and compaction.
- OpenClaw's claude-cli backend starts Claude with `--setting-sources user`, so this file
  is not loaded in WeChat or Telegram chat. A rule for that assistant belongs in
  `AGENTS.md` or the file it injects.
