# clawock-kcnyu

This distribution is the KCNyu live HK + US desk adapter for `clawock`. It is
not the portable product and is not installed by ordinary `clawock` users.

The adapter owns live market preflight/postflight phases, delivery and watchdog
behavior. OpenClaw remains the external runtime that owns model calls, chat,
memory, tools and cron scheduling. Portfolio ledgers and generated artifacts
remain in the configured workspace and are never packaged into either wheel.

The temporary `scripts/harness/` source wrappers exist only for repository CI
and old host commands during the cutover. Production OpenClaw calls the stable
`clawock` CLI, which discovers this adapter through Python entry points.
