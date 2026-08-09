---
name: openclaw-tune
description: OpenClaw **system-level** maintenance — cleans sessions/.bak rotation, disk bloat under ~/.openclaw/, validates model fallback chain, audits cron health, prunes short-term-recall noise. Run after `openclaw update` or every 1-2 weeks. Different from **workspace document tune-up** (single-responsibility canonical .md files, token waste scan) which is handled by Claude auto-memory `openclaw-workspace-tuneup` — triggered when user says "优化下 openclaw 的文档/skill/canonical". This skill is for `openclaw` daemon/CLI maintenance, NOT for workspace docs.
---

# OpenClaw Tune-Up

Use this skill to keep kcn's openclaw setup lean. Run it after every `openclaw update`, or as a periodic chore every 1-2 weeks.

## When to invoke

- User says `/openclaw-tune` or `优化下 openclaw`
- After `openclaw update` (defaults may have shifted; configs may need migration)
- When response feels slow / token costs creeping up
- When `agents/main/sessions/` looks suspiciously large

## Operating principles

1. **Don't delete, archive first**: move stale files to `/tmp/openclaw-cleanup-<date>/` so they can be recovered for a day
2. **Verify before touching live state**: if openclaw gateway is running, only touch files it doesn't actively hold (use `lsof`)
3. **Real holdings, real data**: never propose changes that hardcode portfolio numbers — `portfolio.json` is the only source of truth
4. **Report what was done** with sizes/counts; never silent fixes

## Checklist

### 1. Disk bloat

Big offenders found historically:

| Path | What to look for | Action |
|---|---|---|
| `~/.openclaw/agents/main/sessions/*.bak-*` | Transcript backups, no rotation. One active session can accumulate 100+ files (7MB each = 700MB) | Keep latest 3 per session, archive rest |
| `~/.openclaw/agents/main/sessions/*.bak-*` (orphan) | `.bak` file with no matching `.jsonl` (session deleted but backup stayed) | Archive all |
| `~/.openclaw/openclaw.json.clobbered.*` | Config corruption snapshots (e.g. 2026-04-25 had 78) | Archive all (the `.last-good` retains canonical state) |
| `~/.openclaw/logs/stability/*.json` | Crash dumps from past unhandled rejections | Archive if older than 30 days |
| `~/.openclaw/memory/main.sqlite.tmp-*` | Orphaned SQLite migration tmp file from interrupted write. Verify `lsof` returns empty, mtime > 7d, then delete | Delete only if not held |
| `~/.openclaw/media/` | Generated images, voice clips | Check size; archive if > 100MB and not referenced |
| `~/.openclaw/agents/main/sessions/*.trajectory.jsonl` | Audit trajectory logs — large but useful for debugging | Leave unless > 500MB total |

Sample script:

```bash
ARCHIVE=/tmp/openclaw-cleanup-$(date +%Y%m%d_%H%M%S)
mkdir -p "$ARCHIVE"

# Orphan .bak (no matching .jsonl)
SESS=~/.openclaw/agents/main/sessions
for bak in $SESS/*.bak-*; do
    [ -f "$bak" ] || continue
    base=$(echo "$bak" | sed 's/\.jsonl\.bak-.*//')
    [ -f "$base.jsonl" ] || mv "$bak" "$ARCHIVE/"
done

# Rotate .bak: keep latest 3 per session (by trailing timestamp)
ls $SESS/*.bak-* 2>/dev/null | sed 's/\.jsonl\.bak-.*//' | sort -u | while read pfx; do
    files=$(ls -1 ${pfx}.jsonl.bak-* 2>/dev/null)
    count=$(echo "$files" | wc -l)
    [ "$count" -gt 3 ] && \
        echo "$files" | sort -t'-' -k3,3n | head -n -3 | xargs -I{} mv {} "$ARCHIVE/"
done

# Clobbered configs + old crash dumps
mv ~/.openclaw/openclaw.json.clobbered.* "$ARCHIVE/" 2>/dev/null
mv ~/.openclaw/logs/stability/openclaw-stability-*.json "$ARCHIVE/" 2>/dev/null
```

### 2. Prompt bloat (token cost)

OpenClaw injects these files into every system prompt (order: agents.md=10, soul.md=20, identity.md=30, user.md=40, tools.md=50, memory.md=70). Anything fluffy here gets paid for **per turn**.

Check the size of each:

```bash
wc -c ~/.openclaw/workspace/{AGENTS,SOUL,USER,IDENTITY,MEMORY,TOOLS}.md
```

Rough budget:
- AGENTS.md: < 3 KB (core rules only; no philosophical fluff, no group-chat lore, no heartbeat docs — openclaw injects heartbeat prompt itself)
- MEMORY.md: < 5 KB (durable preferences + data rules + key lessons; not historical trade records — those live in `memory/*.md`)
- SOUL.md / IDENTITY.md / USER.md: < 2 KB each
- TOOLS.md: < 4 KB (script reference + fallback chain summary only)

**Common bloat patterns**:

| Pattern | Where it lives | Fix |
|---|---|---|
| "Promoted From Short-Term Memory" in MEMORY.md | Dreaming auto-promotes summaries; they pile up | Trim entries about already-cleared positions |
| Duplicate fallback chains in MEMORY.md + TOOLS.md + INVESTMENT_SOP.md | Same rules 3x | Keep ONE authoritative copy (TOOLS.md); others reference it |
| Group chat / Discord behavior in AGENTS.md | User uses 1:1 weixin | Drop unless multi-user channels are added |
| Verbose heartbeat instructions in AGENTS.md | openclaw injects `HEARTBEAT_CONTEXT_PROMPT` itself | Keep one short line about HEARTBEAT_OK token |
| 50+ line preamble repeating "real data, no cache" | Said 5 times across files | One铁律 block in MEMORY.md, reference elsewhere |

### 3. Model fallback chain (token cost)

In `~/.openclaw/openclaw.json`, check `agents.defaults.model`:

```bash
python3 -c "
import json
cfg = json.load(open('/root/.openclaw/openclaw.json'))
m = cfg['agents']['defaults']['model']
print('primary:', m['primary'])
print('fallbacks:')
for f in m['fallbacks']: print(' ', f)
"
```

Red flags:
- **Different paid providers stacked early** (e.g. `minimax → glm → anthropic → openai`): one minimax 429 burns expensive tokens. Stack the cheap/unlimited provider 3-4x at the head before falling through to paid backups.
- **"Spare" provider with same API key** (`minimax-spare` same key as `minimax`): acts as a retry, not real redundancy. Fine if user knows that. Bad if they think it's a quota pool.
- **Stale model IDs after openclaw update**: e.g., changelog deprecated `gpt-5.3-codex`. Cross-check `npm view openclaw versions` changelog for deprecation notices.

### 4. Cron jobs

`openclaw cron list --json` — check each enabled job against
`config/cron-schedules.json`（schedule + payload profile + delivery）；system crontab
watchdog 和 EDT/EST 切换也由同一 contract 管：

- Does it reference an installed command or named `ops/*` entry that still exists?
- Does it reference dead APIs? (e.g. "优先东方财富" but Eastmoney is 502 from this server)
- Does it hardcode tickers? (should read from `portfolio.json` dynamically)
- Pattern to use: **script outputs data block → agent layers analysis on top** (情绪面/技术面/操作建议)
- For intraday: use `--wechat` flag for mobile-friendly compact output

### 5. Short-term-recall noise

`~/.openclaw/workspace/memory/.dreams/short-term-recall.json`:

```bash
python3 -c "
import json
data = json.loads(open('/root/.openclaw/workspace/memory/.dreams/short-term-recall.json','rb').read().decode('utf-8','replace'))
e = data['entries']
recalled = sum(1 for v in e.values() if v.get('recallCount',0) > 0)
print(f'total: {len(e)}  ever recalled: {recalled}  ({recalled*100//len(e)}%)')
"
```

If recall rate < 5% and total > 3000, prune noise:
- Drop `session-corpus` entries with `recallCount=0` AND no trade keywords
- Keep all `memory/*.md` entries (those are real diary)
- Keep all entries with `交易记录|买入|卖出|加仓|减仓|清仓|持仓|盈利|亏损`

### 6. After openclaw update

Run these checks after `openclaw update` succeeds:

```bash
# 1. Defaults shifted? Compare default agent model
diff <(openclaw config get agents.defaults.model) <(cat /tmp/last-known-model.json) 2>/dev/null

# 2. Changelog skim for breaking changes
PKG=$(find /root/.local/share/pnpm/global/5/.pnpm -name "openclaw" -path "*node_modules/openclaw" -type d | sort | tail -1)
head -50 "$PKG/CHANGELOG.md"

# 3. Deprecated model IDs check
grep -i "deprecated\|suppress.*model\|stop advertising" "$PKG/CHANGELOG.md" | head -5

# 4. Re-run the disk + prompt + fallback chain checks above
```

If OpenClaw introduced a new default model, verify the configured provider with a real
smoke call before proposing any change; do not infer upgrades from an old model example.

### 7. Verification before reporting done

```bash
# Confirm openclaw still healthy
curl -sf http://127.0.0.1:18789/health && echo " ✓ gateway up"

# Confirm scripts still run
cd /root/.openclaw/workspace && clawock analyze-hk --no-fetch --no-news --wechat | head -5

# Show cleanup summary
du -sh /tmp/openclaw-cleanup-*/  # what was archived
```

## Output format

End with a structured report:

```
## Tune-Up Report  YYYY-MM-DD

### 清理（已归档到 /tmp/openclaw-cleanup-YYYYMMDD/）
- Session .bak rotation: N 个 → ~X MB
- ...

### Prompt 瘦身
- AGENTS.md: <old> → <new> 行 (-N%)
- ...

### 配置审计
- 模型 fallback 链：<state>
- Cron job 一致性：<state>
- ...

### 建议
- [可选] 重启 gateway: <yes/no, reason>
- [待办] <items needing user attention>

### 跳过项
- <什么没动以及为什么>
```

## Don't

- ❌ Don't restart `openclaw-gateway` automatically — ask user first
- ❌ Don't touch `agents.defaults.model.primary` — that's user's intentional choice
- ❌ Don't delete anything before archiving to /tmp
- ❌ Don't delete `*.trajectory.jsonl` — those are sometimes useful for debugging
- ❌ Don't strip MEMORY.md entries that contain `交易记录` — those are real history kcn refers to
- ❌ Don't propose hardcoding portfolio numbers in any doc/skill — always reference `portfolio.json`

## Inputs / Outputs

- **Reads**: `~/.openclaw/openclaw.json`, live cron state via `openclaw cron list --json`, `config/cron-schedules.json`, workspace canonical MD files, short-term recall state, and disk usage of `~/.openclaw/`
- **Writes**: trimmed `*.md` workspace files (with bak), cron fields only through `openclaw cron edit` / `ops/host/sync_us_cron_dst.py` plus the tracked contract and regenerated `docs/operations/cron-schedules.md`, eventual `portfolio.json` if data refresh happens; everything else archived to `/tmp/openclaw-cleanup-<date>/`
- **Side effects**: may suggest gateway restart at the end (user-confirmed)
