# Skill registry policy

## Authority and scope

The host `openclaw.json` → `plugins.entries.skillhub.config` owns the primary/fallback CLI and registry labels. Read the live values; this document owns the discovery, disclosure and reply constraints below. `TOOLS.md` is only a route to this policy.

The skillhub plugin currently renders a policy prefix through `before_prompt_build`. Its injection placement and frequency are host implementation details, not instructions to duplicate the block in each user request. Changes to that plugin need a separate host change; this repository does not patch its injection logic.

## Operator configured rules

1. For skills discovery/install/update, try the configured primary CLI first (currently `skillhub`).
2. If unavailable, rate-limited, or no match, use the configured fallback CLI (currently `clawhub`).
3. Do not claim exclusivity. Public and private registries are both allowed.
4. Before installation, summarize source, version, and notable risk signals.
5. For search requests, execute `exec` with the configured primary CLI’s `search <keywords>` first and report the command output.
6. In the current session, reply directly. Do NOT call `message` tool just to send progress updates.
