#!/usr/bin/env bash
# Add a durable "this conversation" cost to the reply usage footer.
#
# The auto-reply channel path (WeChat/Telegram/etc.) persists usage through
# `persistSessionUsageUpdate` in agent-runner.runtime, not through the CLI
# `updateSessionStoreAfterAgentRun` path.  This patch accumulates the per-run
# estimate that function already computes into `sessionCostUsd` on the session
# entry (one-time backfill from the usage-family transcripts up to the start of
# the current run), passes it through the reply state, and exposes it to the
# template as `cost.session_usd`.
#
# Lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every upgrade;
# re-run after each upgrade (ops/host/reapply_openclaw_patches.sh). Idempotent;
# refuses to edit when a source anchor no longer matches exactly.
set -euo pipefail

OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
DIST="$OCLAW_REAL/dist"
MARK="clawock-reply-session-cost-v1"

find_one() {
  local needle="$1"
  local file
  file=$(grep -rlF --include='*.js' -- "$needle" "$DIST" 2>/dev/null | head -1 || true)
  if [ -z "$file" ] || [ ! -f "$file" ]; then
    echo "[patch] ERROR: cannot locate bundle containing: $needle" >&2
    exit 1
  fi
  printf '%s\n' "$file"
}

REPLY_FILE=$(find_one "function buildReplyUsageState")
RUNNER_FILE=$(find_one "function persistSessionUsageUpdate")

if [ "$REPLY_FILE" = "$RUNNER_FILE" ]; then
  echo "[patch] ERROR: expected reply state and auto-reply runner in distinct bundles" >&2
  exit 1
fi

if grep -qF -- "$MARK" "$REPLY_FILE" && grep -qF -- "$MARK" "$RUNNER_FILE"; then
  echo "[patch] already applied: $REPLY_FILE, $RUNNER_FILE"
  exit 0
fi
if grep -qF -- "$MARK" "$REPLY_FILE" || grep -qF -- "$MARK" "$RUNNER_FILE"; then
  echo "[patch] ERROR: partial marker present; restore the .pre-reply-session-cost.bak files before retrying" >&2
  exit 1
fi

for file in "$REPLY_FILE" "$RUNNER_FILE"; do
  if [ ! -f "$file.pre-reply-session-cost.bak" ]; then
    cp -p "$file" "$file.pre-reply-session-cost.bak"
  fi
done

python3 - "$REPLY_FILE" "$RUNNER_FILE" <<'PY'
from pathlib import Path
import sys

reply_path, runner_path = map(Path, sys.argv[1:])
MARK = "clawock-reply-session-cost-v1"

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"[patch] ERROR: {label}: anchor count {count} != 1")
    return text.replace(old, new, 1)

# --- reply state: carry the number through to the usage contract -----------
reply = reply_path.read_text()
old = "\t\tagentId: params.agentId,\n\t\tsessionId: params.sessionId,\n\t\tchatType: params.chatType,"
new = (
    "\t\tagentId: params.agentId,\n"
    "\t\tsessionId: params.sessionId,\n"
    f"\t\tsessionUsd: typeof params.sessionUsd === \"number\" && Number.isFinite(params.sessionUsd) ? params.sessionUsd : void 0, /* {MARK} */\n"
    "\t\tchatType: params.chatType,"
)
reply = replace_once(reply, old, new, "reply state sessionUsd")

# --- auto-reply runner ------------------------------------------------------
runner = runner_path.read_text()

old = 'import path, { isAbsolute, resolve } from "node:path";\n'
new = old + f'import readline from "node:readline"; /* {MARK} */\n'
runner = replace_once(runner, old, new, "runner readline import")

old = (
    "\t\tcost: {\n"
    "\t\t\tturn_usd: typeof state.turnUsd === \"number\" ? state.turnUsd : null,\n"
    "\t\t\tavailable: typeof state.turnUsd === \"number\"\n"
    "\t\t},"
)
new = (
    "\t\tcost: {\n"
    "\t\t\tturn_usd: typeof state.turnUsd === \"number\" ? state.turnUsd : null,\n"
    f"\t\t\tsession_usd: typeof state.sessionUsd === \"number\" ? state.sessionUsd : null, /* {MARK} */\n"
    "\t\t\tavailable: typeof state.turnUsd === \"number\",\n"
    "\t\t\tsession_available: typeof state.sessionUsd === \"number\"\n"
    "\t\t},"
)
runner = replace_once(runner, old, new, "usage contract session_usd")

old = "\t\t\ttyping.markDispatchIdle();\n\t\t\treturn;\n\t\t}\n\t\tconst endDeliveryCorrelations = (queued.deliveryCorrelations ?? []).map((correlation) => correlation.begin()).filter((end) => typeof end === \"function\");"
new = "\t\t\ttyping.markDispatchIdle();\n\t\t\treturn;\n\t\t}\n" + f"\t\tconst followupRunStartedAt = Date.now(); /* {MARK} */\n" + "\t\tconst endDeliveryCorrelations = (queued.deliveryCorrelations ?? []).map((correlation) => correlation.begin()).filter((end) => typeof end === \"function\");"
runner = replace_once(runner, old, new, "followup run start")

old = "\t\t\tconst replyUsageState = buildReplyUsageState({\n\t\t\t\tconfig: runtimeConfig,"
new = (
    f"\t\t\tconst sessionCostEntry = (replySessionKey && storePath ? loadSessionEntry({{ storePath, sessionKey: replySessionKey }}) : void 0) ?? (replySessionKey ? sessionStore?.[replySessionKey] : void 0) ?? activeSessionEntry; /* {MARK} */\n"
    "\t\t\tconst replyUsageState = buildReplyUsageState({\n\t\t\t\tconfig: runtimeConfig,"
)
runner = replace_once(runner, old, new, "followup sessionCostEntry")

old = "\t\t\t\tagentId: run.agentId,\n\t\t\t\tsessionId: run.sessionId,"
new = (
    "\t\t\t\tagentId: run.agentId,\n"
    "\t\t\t\tsessionId: run.sessionId,\n"
    "\t\t\t\tsessionUsd: typeof sessionCostEntry?.sessionCostUsd === \"number\" ? sessionCostEntry.sessionCostUsd : void 0,"
)
runner = replace_once(runner, old, new, "followup sessionUsd")

old = "\t\tconst replyUsageState = buildReplyUsageState({\n\t\t\tconfig: cfg,"
new = (
    f"\t\tconst sessionCostEntry = (sessionKey && storePath ? loadSessionEntry({{ storePath, sessionKey }}) : void 0) ?? (sessionKey ? sessionStore?.[sessionKey] : void 0) ?? activeSessionEntry; /* {MARK} */\n"
    "\t\tconst replyUsageState = buildReplyUsageState({\n\t\t\tconfig: cfg,"
)
runner = replace_once(runner, old, new, "main sessionCostEntry")

old = "\t\t\tagentId: followupRun.run.agentId,\n\t\t\tsessionId: followupRun.run.sessionId,"
new = (
    "\t\t\tagentId: followupRun.run.agentId,\n"
    "\t\t\tsessionId: followupRun.run.sessionId,\n"
    "\t\t\tsessionUsd: typeof sessionCostEntry?.sessionCostUsd === \"number\" ? sessionCostEntry.sessionCostUsd : void 0,"
)
runner = replace_once(runner, old, new, "main sessionUsd")

old = "\t\t\tif (storePath && replySessionKey) await persistRunSessionUsage({\n\t\t\t\tstorePath,\n\t\t\t\tsessionKey: replySessionKey,"
new = old + "\n\t\t\t\trunStartedAt: followupRunStartedAt,"
runner = replace_once(runner, old, new, "followup runStartedAt")

old = "\t\tawait persistRunSessionUsage({\n\t\t\tstorePath,\n\t\t\tsessionKey,\n\t\t\tcfg,"
new = old + "\n\t\t\trunStartedAt,"
runner = replace_once(runner, old, new, "main runStartedAt")

HELPERS = r'''function parseReplyCostTimestamp(entry) { /* clawock-reply-session-cost-v1 */
	const raw = entry.timestamp;
	if (typeof raw === "string") {
		const parsed = Date.parse(raw);
		if (Number.isFinite(parsed)) return parsed;
	}
	const messageTimestamp = entry.message?.timestamp;
	if (typeof messageTimestamp === "number" && Number.isFinite(messageTimestamp)) return messageTimestamp;
	return void 0;
}
async function scanReplyCostFile(params) {
	let total = 0;
	let stream;
	try {
		stream = fs.createReadStream(params.filePath, { encoding: "utf8" });
	} catch {
		return total;
	}
	const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
	try {
		for await (const line of rl) {
			const trimmed = line.trim();
			if (!trimmed) continue;
			let parsed;
			try {
				parsed = JSON.parse(trimmed);
			} catch {
				continue;
			}
			if (!parsed || parsed.type !== "message") continue;
			const message = parsed.message;
			if (!message || message.role !== "assistant") continue;
			const rawUsage = message.usage ?? parsed.usage;
			if (!rawUsage) continue;
			if (params.endMs !== void 0) {
				const timestamp = parseReplyCostTimestamp(parsed);
				if (timestamp !== void 0 && timestamp > params.endMs) continue;
			}
			const usage = normalizeUsage(rawUsage);
			if (!usage) continue;
			const costRaw = rawUsage.cost;
			const recordedTotal = costRaw && typeof costRaw.total === "number" && costRaw.total >= 0 ? costRaw.total : void 0;
			const tokenTotal = (usage.input ?? 0) + (usage.output ?? 0) + (usage.cacheRead ?? 0) + (usage.cacheWrite ?? 0);
			const modelCost = resolveModelCostConfig({
				provider: message.provider ?? parsed.provider,
				model: message.model ?? parsed.model,
				config: params.config
			});
			const pricingKnown = Boolean(modelCost && (modelCost.tieredPricing?.length > 0 || modelCost.input > 0 || modelCost.output > 0 || modelCost.cacheRead > 0 || modelCost.cacheWrite > 0));
			const preservedZero = recordedTotal === 0 && (costRaw?.totalOrigin === "provider-billed" || [costRaw?.input, costRaw?.output, costRaw?.cacheRead, costRaw?.cacheWrite].some((value) => value !== void 0 && value !== 0));
			let amount = recordedTotal;
			if (modelCost?.tieredPricing?.length > 0 && !preservedZero) amount = estimateUsageCost({ usage, cost: modelCost });
			else if (!pricingKnown && !preservedZero && (amount === void 0 || amount === 0) && tokenTotal > 0) amount = void 0;
			else if (amount === void 0 || (amount === 0 && !preservedZero && pricingKnown && tokenTotal > 0)) amount = estimateUsageCost({ usage, cost: modelCost });
			if (typeof amount === "number" && Number.isFinite(amount)) total += amount;
		}
	} catch {
		return total;
	} finally {
		rl.close();
		try {
			stream.destroy();
		} catch {}
	}
	return total;
}
async function resolveBackfilledSessionCostUsd(params) {
	const endMs = params.endMs;
	if (typeof endMs !== "number" || !Number.isFinite(endMs)) return void 0;
	const entry = params.entry;
	const storePath = params.storePath;
	let sessionFile = entry.sessionFile;
	if (typeof sessionFile !== "string" || sessionFile.length === 0 || !fs.existsSync(sessionFile)) {
		if (typeof entry.sessionId !== "string" || entry.sessionId.length === 0 || typeof storePath !== "string" || storePath.length === 0) return void 0;
		sessionFile = path.join(path.dirname(storePath), `${entry.sessionId}.jsonl`);
	}
	if (!fs.existsSync(sessionFile)) return void 0;
	const sessionsDir = path.dirname(sessionFile);
	const ids = /* @__PURE__ */ new Set();
	const familyIds = Array.isArray(entry.usageFamilySessionIds) ? entry.usageFamilySessionIds : [];
	for (const id of [...familyIds, entry.sessionId]) {
		if (typeof id === "string" && /^[A-Za-z0-9._-]+$/.test(id)) ids.add(id);
	}
	let total = 0;
	let scanned = 0;
	try {
		for (const id of ids) {
			const filePath = path.join(sessionsDir, `${id}.jsonl`);
			if (!fs.existsSync(filePath)) continue;
			total += await scanReplyCostFile({ filePath, config: params.cfg, endMs });
			scanned += 1;
		}
	} catch {
		return void 0;
	}
	return scanned > 0 ? total : void 0;
}
'''
old = "async function persistSessionUsageUpdate(params) {"
runner = replace_once(runner, old, HELPERS + old, "runner helpers")

old = "\t\t\t\tif (runEstimatedCostUsd !== void 0) patch.estimatedCostUsd = runEstimatedCostUsd;"
new = (
    old + "\n"
    + f"\t\t\t\tconst previousSessionCostUsd = resolveNonNegativeNumber(entry.sessionCostUsd); /* {MARK} */\n"
    + "\t\t\t\tconst sessionCostBaseline = previousSessionCostUsd ?? await resolveBackfilledSessionCostUsd({\n"
    + "\t\t\t\t\tcfg,\n"
    + "\t\t\t\t\tentry,\n"
    + "\t\t\t\t\tstorePath,\n"
    + "\t\t\t\t\tendMs: params.runStartedAt\n"
    + "\t\t\t\t});\n"
    + "\t\t\t\tif (sessionCostBaseline !== void 0) {\n"
    + "\t\t\t\t\tconst nextSessionCostUsd = resolveNonNegativeNumber(sessionCostBaseline + (runEstimatedCostUsd ?? 0));\n"
    + "\t\t\t\t\tif (nextSessionCostUsd !== void 0) patch.sessionCostUsd = nextSessionCostUsd;\n"
    + "\t\t\t\t}"
)
runner = replace_once(runner, old, new, "auto-reply accumulation")

old = (
    "\t\t\tpreserveFreshTotalTokensOnStaleUsage: preflightCompactionApplied\n"
    "\t\t});\n"
    "\t\tconst successfulSourceReplyDelivery = hasSuccessfulSourceReplyDelivery({"
)
new = (
    "\t\t\tpreserveFreshTotalTokensOnStaleUsage: preflightCompactionApplied\n"
    "\t\t});\n"
    f"\t\tconst persistedSessionCost = (sessionKey && storePath ? loadSessionEntry({{ storePath, sessionKey }}) : void 0)?.sessionCostUsd; /* {MARK} */\n"
    "\t\tif (typeof persistedSessionCost === \"number\") replyUsageState.sessionUsd = persistedSessionCost;\n"
    "\t\tconst successfulSourceReplyDelivery = hasSuccessfulSourceReplyDelivery({"
)
runner = replace_once(runner, old, new, "main post-persist sessionUsd")

if MARK not in reply or MARK not in runner:
    raise SystemExit("[patch] ERROR: marker missing after edit")
reply_path.write_text(reply)
runner_path.write_text(runner)
print("[patch] edits written")
PY

if ! node --check "$REPLY_FILE" || ! node --check "$RUNNER_FILE"; then
  echo "[patch] ERROR: syntax check failed; restoring backups" >&2
  for file in "$REPLY_FILE" "$RUNNER_FILE"; do
    cp -p "$file.pre-reply-session-cost.bak" "$file"
  done
  exit 1
fi

for file in "$REPLY_FILE" "$RUNNER_FILE"; do
  grep -qF -- "$MARK" "$file" || {
    echo "[patch] ERROR: marker missing after patch: $file" >&2
    exit 1
  }
done

echo "[patch] applied: $REPLY_FILE"
echo "[patch] applied: $RUNNER_FILE"
echo "[patch] restart the gateway to take effect"
