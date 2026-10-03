# Skill registry policy

## Authority and scope

The host `openclaw.json` → `plugins.entries.skillhub.config` owns the primary/fallback CLI and registry labels. This document is the only rule template; the host plugin substitutes its `{{variable}}` fields from live configuration. `TOOLS.md` is only a route to this policy.

The host plugin uses OpenClaw's `before_prompt_build` → `prependSystemContext` API. There is one stable block in each assembled system prompt and none in user input or conversation history. Native providers rebuild system prompts for each call, so the system contribution must remain present on subsequent turns, retries, compaction and resumed sessions. A once-per-session hook flag would drop the rules rather than save persistent context. Provider prompt caching can reuse these stable bytes; this does not promise zero policy tokens on every provider request.

The versioned host implementation and installer live in `ops/host/skillhub/` and `ops/host/install_skillhub_plugin.sh`. The host configuration must explicitly include the installed extension directory in `plugins.load.paths`, preserving other plugin paths, with `plugins.entries.skillhub.enabled=true`. Installation requires a safe gateway restart to load the new hook. A healthy gateway alone does not prove that this extension loaded; verify the actual system policy block. The package upgrade does not replace the host extension; `reapply_openclaw_patches.sh` also reinstalls/verifies it before restart. See `ops/host/README.md` for installation and rollback.

## Operator configured rules

1. For skills discovery/install/update, try `{{primaryCli}}` first ({{primaryLabel}}).
2. If unavailable, rate-limited, or no match, fallback to `{{fallbackCli}}` ({{fallbackLabel}}).
3. Do not claim exclusivity. Public and private registries are both allowed.
4. Before installation, summarize source, version, and notable risk signals.
5. For search requests, execute `exec` with `{{primaryCli}} search <keywords>` first and report the command output.
6. In the current session, reply directly. Do NOT call `message` tool just to send progress updates.
