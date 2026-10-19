# Model ids and the MiniMax endpoint

`config/models.json` is the only place to change a model id that appears in more
than one location, or the MiniMax Anthropic endpoint. It holds values only:

```json
"minimax": {"model": "MiniMax-M3.1-Flash", "display_name": "MiniMax M3.1 Flash", "anthropic_base": "https://api.minimaxi.com/anthropic"},
"cron":    {"codex_fallback": "openai/gpt-6-luna", "codex_candidate": "openai/gpt-6.1-sol"},
"chat":    {"fallback": "deepseek/deepseek-flash"}
```

Where each value lives is the `targets()` table in `ops/host/sync_model_refs.py`,
one line per copy. That includes an id kept as a JSON key
(`agents.defaults.models` in `openclaw.json`), which a search for the old string
does not find reliably.

| Command | Effect |
|---|---|
| `python3 ops/host/sync_model_refs.py` | Check every bound copy; exit 1 on drift |
| `python3 ops/host/sync_model_refs.py --apply` | Rewrite drifted copies, then check again |
| `python3 ops/host/sync_model_refs.py --effective` | Show what chat, every cron job and dsh are configured with, and the provider/model each cron job's last run actually used |

Bound locations: the strategy cron profiles in `config/cron-schedules.json`,
`MINIMAX_MODEL`/`MINIMAX_BASE` in `src/clawock/automation/llm.py`, and, on the
host, `~/.openclaw/openclaw.json` and both dsh `cordis.patch.yml` profiles. CI
checks only the repository copies (`tests/test_model_refs.py`). Host files are
skipped when they are absent.

`--apply` restarts nothing. After it:

- cron contract changed: `python3 ops/host/sync_cron_payloads.py --apply`;
- `openclaw.json` changed: `openclaw gateway restart`, after confirming no cron run is in flight;
- a dsh profile changed: restart dsh.

Copies that are intentionally left unbound:

- `MiniMax-M3` stays in both MiniMax provider model tables as the rollback id.
- `minimax` and `minimax-2` share one account on purpose: the second hop is a retry.
- History in docs, the changelog and memory records past facts.
- The `/^MiniMax-M3(\b|[-.])/` matchers in OpenClaw and dsh patches match the whole family, not one id.
