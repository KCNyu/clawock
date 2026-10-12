import { createBalanceService, createClaudeService, createCodexService, createMinimaxService } from "./balance.js";
import { homedir } from "node:os";
import { join } from "node:path";
//#region src/desk.ts
/**
* What feeds the task chip's provider panel, assembled once for every host that
* shows it: the balance services in display order, and the task queue reader's
* configuration. The dsh gateway (index.ts) serves these to the sidebar; the
* OpenClaw `/dispatch-list` command (chat.ts) reads the same services in
* its own process. Neither host builds its own list of providers or paths.
*/
/**
* The providers the balance chip lists, in display order. Adding one is one
* row here plus its service in balance.ts — the gateway method below iterates
* this table instead of naming each provider in four places (#1480 had to
* touch the service map, the Promise.all, the row list and the refresh min).
*/
const BALANCE_PROVIDERS = [
	{
		id: "deepseek",
		label: "DeepSeek",
		create: (deps, config, lastGoodPath) => createBalanceService(deps, {
			baseUrl: config.balanceBaseUrl,
			threshold: config.balanceThreshold,
			refreshMs: config.balanceRefreshMs,
			lastGoodPath
		})
	},
	{
		id: "minimax",
		label: "MiniMax",
		create: (deps, config, lastGoodPath) => createMinimaxService(deps, {
			lastGoodPath,
			baseUrl: config.minimaxBaseUrl,
			keyRef: config.minimaxKeyRef,
			lowPct: config.minimaxLowPct,
			openclawConfigPath: config.minimaxOpenclawConfigPath
		})
	},
	{
		id: "claude",
		label: "Claude",
		create: (deps, config, lastGoodPath) => createClaudeService(deps, {
			credentialsPath: config.claudeCredentialsPath,
			usageUrl: config.claudeUsageUrl,
			lowPct: config.claudeLowPct,
			lastGoodPath
		})
	},
	{
		id: "codex",
		label: "Codex",
		create: (deps, config, lastGoodPath) => createCodexService(deps, {
			command: config.codexCommand,
			lowPct: config.codexLowPct,
			refreshMs: config.codexRefreshMs,
			lastGoodPath
		})
	}
];
/**
* Where each provider's last good reading is kept between processes (one file per provider,
* no secrets in it). Both hosts of the panel resolve the same directory, so the OpenClaw
* command falls back on what the dsh gateway last read and the other way round.
* `CLAWOCK_DSH_STATE_DIR` moves it (the spec points it at a temp dir).
*/
const balanceStateDir = () => process.env.CLAWOCK_DSH_STATE_DIR || join(homedir(), ".cache", "clawock-dsh");
function createBalanceReader(credentials, config) {
	const dir = balanceStateDir();
	const services = BALANCE_PROVIDERS.map((provider) => provider.create({ credentials }, config, join(dir, `balance-${provider.id}.json`)));
	return { async get(force) {
		const results = await Promise.all(services.map((service) => service.get(force)));
		return {
			providers: BALANCE_PROVIDERS.map((provider, i) => ({
				provider: provider.id,
				label: provider.label,
				result: results[i]
			})),
			refreshMs: Math.min(...results.map((result) => result.refreshMs))
		};
	} };
}
/** The task queue reader's (and write door's) configuration; `workspace` holds the repository's copy of the ops entry. */
function taskQueueConfig(config, workspace) {
	return {
		logDir: config.dispatchLogDir,
		limitsPath: config.dispatchLimitsPath,
		patrolDir: config.patrolStateDir,
		refreshMs: config.taskQueueRefreshMs,
		recent: config.taskQueueRecent,
		opsPath: config.taskQueueOpsPath,
		repoOpsPath: join(workspace, "ops", "host", "task_queue_ops.py")
	};
}
//#endregion
export { taskQueueConfig as n, createBalanceReader as t };
