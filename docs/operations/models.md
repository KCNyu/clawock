# Models: one file

`config/models.toml` declares:

- **providers**: endpoint, protocol, timeouts. Credentials never live here.
- **models**: each model with its OpenClaw fields and its defaults (`params`, `runtime`).
- **chains**: which models each scenario uses, in order, plus that scenario's thinking level.
- **openclaw**: host-wide OpenClaw keys copied to the same path in `openclaw.json`
  (`agents.defaults.thinkingDefault`, `talk.consultThinkingLevel`).

Everything else is derived from it:

| Consumer | How it follows the file |
|---|---|
| Cron jobs | `config/cron-schedules.json` profiles say `"chain": "cron"`; `clawock.scheduling.load_contract` resolves model, fallbacks, candidates and thinking |
| clawock's MiniMax client (`clawock.automation.llm`, also in GitHub Actions) | reads chain `clawock-llm` at import |
| OpenClaw (`~/.openclaw/openclaw.json`) | `ops/host/sync_models.py --apply` rewrites the owned sections: provider tables, `agents.defaults.models`, the chat chain, heartbeat, subagents, dreaming, every `[openclaw.*]` key |
| dsh profiles | the same command rewrites the MiniMax provider's `baseURL` and model list |

Common changes:

- **New model id**: edit `ref` under `[models.flash]`.
- **Different parameters**: edit that model's `params`, or one chain's `thinking`.
- **Different model for one scenario**: edit `[chains.<name>].models`.

Then:

```
python3 ops/host/sync_models.py --apply           # OpenClaw + dsh on this host
python3 ops/host/sync_cron_payloads.py --apply    # if a cron chain changed
openclaw gateway restart                          # no cron in flight; dsh: restart if its profile changed
python3 ops/host/sync_models.py --effective       # chat chain, every cron job's model and last run, dsh ids
```

## Dream Diary fallback

`chains.dreaming` keeps MiniMax-M3.1-Flash first and uses Luna only after a
retryable model failure. Luna runs through the Codex login/runtime with its
per-model `thinking = "max"`; no OpenAI API key is required. Chat, ordinary
subagents and the memory-promotion cron keep their own chains.

The frozen fork implements `dreaming.fallbacks`. `sync_models.py` derives the
ordered fallback list and subagent allowlist from the registry. The fork retries
model-unavailable, rate-limit, quota, and selected transient server failures in
fresh sessions. Policy denials and genuinely running attempts stay visible.
Read the active chain using `sync_models.py --effective`.

## MiniMax thinking

Only `MiniMax-M3.1-Flash` is used (kcn, 2026-10-20). MiniMax's
[Anthropic API reference](https://platform.minimax.cn/docs/api-reference/text-anthropic-api)
is the authority for how it thinks:

| Request | M3.1-Flash |
|---|---|
| `thinking` omitted or `{"type": "adaptive"}` | thinks |
| `{"type": "disabled"}` | HTTP 400 (`requires adaptive thinking`) |
| `output_config.effort` | `low` / `medium` / `high` / `xhigh` / `max`; omitted = `max`; `none` is HTTP 400 |

So there are two knobs, and they are set in different places:

- **Level** (OpenClaw's `/think`, `params.thinking`, a chain's `thinking`,
  `talk.consultThinkingLevel`): OpenClaw offers `off` and `adaptive` for M3.x
  and clamps other levels to `adaptive`. The frozen fork sends `{"type": "adaptive"}` whatever
  the level and OpenClaw sends no effort, so every OpenClaw turn on M3.1 runs at
  the endpoint's default `max`. Write `adaptive` wherever only M3.1 reads the
  value. The strategy cron payload retains `max` as its chain default.
  Each candidate applies its own `params.thinking` before resolving what the
  model and runtime support. Both MiniMax hops use `adaptive` and Luna uses
  `max`.
- **Effort** (clawock's own client, `clawock.automation.llm`): a thinking call
  sends `{"type": "adaptive"}` plus `output_config.effort` when the caller passes
  `thinking_effort` (`llm.MINIMAX_EFFORTS`); none means `max`. The weekly review
  asks for `high` to stay inside its deadline. A `thinking_disabled` call (the
  influencer filter) cannot turn thinking off on M3.1 and sends effort `low`.

`tests/test_model_registry.py` fails when an M3.1 level is anything but `adaptive`.

Without `--apply`, `sync_models.py` only reports which owned sections differ.
The host system check warns when the registry-owned fields in live
`openclaw.json` drift, including the per-model overrides and global thinking
defaults.
`tests/test_model_registry.py` keeps model ids out of the cron contract and keeps
the client on the registry.

The registry emits the same model defaults for the `minimax-2` retry alias.
Out of scope for the registry are history in docs and memory, the family matchers
(`/^MiniMax-M3(\b|[-.])/`) in OpenClaw/dsh patches; dsh's own default model and
non-MiniMax dsh catalogs; ports.
