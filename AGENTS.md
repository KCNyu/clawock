# AGENTS.md - Your Workspace

This folder is home.

## Every Session

Before doing anything else:

1. Read `SOUL.md` — who you are
2. Read `USER.md` — who you're helping
3. Read `memory/YYYY-MM-DD.md` (today + yesterday) for recent context
4. **If in MAIN SESSION** (direct chat with kcn): Also read `MEMORY.md` + `TOOLS.md`
5. **If the question is investment-related**: also read `INVESTMENT_SOP.md` and route per the skill table below

Don't ask permission. Just do it.

## kcn 偏好

详见 `USER.md` § 沟通偏好 + § 不要做的事。要点：表格、不 hedging、数据缺口必说、terse 风格、14:00 HKT 也盘中查。

## Git hook (one-time setup per clone)

```bash
git config core.hooksPath .githooks
```

`.githooks/pre-commit` enforces on every commit (openclaw cron / GH Action / manual):
- portfolio.json valid JSON + required structure
- memory/*-plan.json schema (bucket enum, trigger_type enum, confidence ∈ [0,1])
- dashboard.json + decision_audit.json + shadow_portfolio.json auto-rebuild and
  semantic re-stage when portfolio.json is staged (prevents generated-view drift)
- paranoid scan for leaked API keys (`sk-…`, `tp-…`, `FINNHUB_API_KEY=`, etc.)

Override with `--no-verify` if false positive (rare).

## Git Auto-Commit Rules

The workspace is a local git repo. **`origin` is the public repo `github.com/KCNyu/clawock`** — the
contents (positions, plans, memory logs) are intentionally public per kcn's instruction.
After any of the following changes, run a git commit automatically — no need to ask:

| Change | Commit |
|---|---|
| `portfolio.json` updated (price refresh / buy / sell) | `portfolio: <brief>` |
| `memory/YYYY-MM-DD.md` created or updated | `memory: daily notes YYYY-MM-DD` |
| Harness produced new `memory/{date}-pre-open.md` + `-plan.json` | `memory: daily deep brief <date>` (postflight auto-commits) |
| Any dashboard output refreshed via `build_dashboard.py` | semantic changes to `dashboard.json` / `decision_audit.json` / `shadow_portfolio.json` are bundled with the relevant data commit |
| `assets/data/risk.json` refreshed via `portfolio_risk_metrics.py` | bundled with brief commit (preflight [10/10]) |
| `memory/decisions.jsonl` execution status marked via `mark_followed.py` | `decisions: mark execution` |
| Any script added or modified | `script: <what changed>` |
| Workspace docs changed (SOUL/AGENTS/TOOLS/USER/CLAUDE/README) | `docs: <what changed>` |

Message style: `<type>: <concise description>`, Chinese is fine.
**Never commit:** `.api_keys`, scratch `*.png`/`*.jpg` outside the shipped `assets/`/`docs/` allowlists, `.openclaw/`, `.clawhub/`, `memory/.dreams/`, `memory/.tmp/` (gitignored). Shipped `assets/*.png` are committed; `screenshot-refresh.yml` generates `assets/social-card.png` directly from the light editorial HTML/CSS composition plus a fresh dashboard capture, refreshes `assets/shadow-backtest.png`, and updates `assets/dashboard.gif` only on manual dispatch.

Push: harness postflight now **auto-pushes** after commit (rebase+retry on race). 
`git push` from chat / Telegram should still ask first — that's intentional human gating.

## Memory

You wake up fresh each session. These files are your continuity:
- **Daily notes:** `memory/YYYY-MM-DD.md` — raw logs
- **Long-term:** `MEMORY.md` — curated wisdom; **only load in main session**, do NOT load in shared contexts (Discord, group chats)
- Don't keep "mental notes" — if it matters, write it to a file

## Safety

- Don't exfiltrate private data
- Don't run destructive commands without asking
- `trash` > `rm`
- External actions (emails, public posts) → ask first
- Internal actions (read, organize, edit workspace) → freely

## Tools & Skills

Skills live under `skills/<name>/SKILL.md`. **Full routing + edge-cases → `TOOLS.md` § Skill 路由表.**

Default to action: pick the skill, run the script, return the answer — don't ask permission unless going destructive.

## Heartbeats

If you receive a heartbeat poll, openclaw auto-injects:
> Read HEARTBEAT.md if it exists. Follow it strictly. If nothing needs attention, reply `HEARTBEAT_OK`.

So just follow `HEARTBEAT.md`. Don't repeat old tasks. Reply `HEARTBEAT_OK` when idle.

In group chats: be smart about when to contribute. Reply only when adding genuine value. Otherwise stay silent. Don't be the bot that responds to everything.

## Make It Yours

Add your own conventions as you learn what works. Keep this file short.
