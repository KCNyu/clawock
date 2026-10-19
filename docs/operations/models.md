# Models: one file

`config/models.toml` declares:

- **providers**: endpoint, protocol, timeouts. Credentials never live here.
- **models**: each model with its OpenClaw fields and its defaults (`params`, `runtime`).
- **chains**: which models each scenario uses, in order, plus that scenario's thinking level.

Everything else is derived from it:

| Consumer | How it follows the file |
|---|---|
| Cron jobs | `config/cron-schedules.json` profiles say `"chain": "cron"`; `clawock.scheduling.load_contract` resolves model, fallbacks, candidates and thinking |
| clawock's MiniMax client (`clawock.automation.llm`, also in GitHub Actions) | reads chain `clawock-llm` at import |
| OpenClaw (`~/.openclaw/openclaw.json`) | `ops/host/sync_models.py --apply` rewrites the owned sections: provider tables, `agents.defaults.models`, the chat chain, heartbeat, subagents, dreaming |
| dsh profiles | the same command rewrites the MiniMax provider's `baseURL` and model list |

Common changes:

- **New model id**: edit `ref` under `[models.flash]`.
- **Different parameters**: edit that model's `params`, or one chain's `thinking`.
- **Different model for one scenario**: edit `[chains.<name>].models`.
- **Rollback to M3**: point the chains at `m3`.

Then:

```
python3 ops/host/sync_models.py --apply           # OpenClaw + dsh on this host
python3 ops/host/sync_cron_payloads.py --apply    # if a cron chain changed
openclaw gateway restart                          # no cron in flight; dsh: restart if its profile changed
python3 ops/host/sync_models.py --effective       # chat chain, every cron job's model and last run, dsh ids
```

Without `--apply`, `sync_models.py` only reports which owned sections differ.
`tests/test_model_registry.py` keeps model ids out of the cron contract and keeps
the client on the registry.

Intentionally not covered: `minimax-2` is an alias of `minimax` (same account,
retry hop); history in docs and memory; the family matchers
(`/^MiniMax-M3(\b|[-.])/`) in OpenClaw/dsh patches; dsh's own default model and
non-MiniMax dsh catalogs; ports.
