import { createBalanceService, createClaudeService, createCodexService, createMinimaxService } from "./balance.js";
import { join } from "node:path";
//#region src/desk.ts
/**
* What feeds the task chip's provider panel, assembled once for every host that
* shows it: the balance services in display order, and the task queue reader's
* configuration. The dsh gateway (index.ts) serves these to the sidebar; the
* OpenClaw `/dispatch-list` command (openclaw.ts) reads the same services in
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
		create: (deps, config) => createBalanceService(deps, {
			baseUrl: config.balanceBaseUrl,
			threshold: config.balanceThreshold,
			refreshMs: config.balanceRefreshMs
		})
	},
	{
		id: "minimax",
		label: "MiniMax",
		create: (deps, config) => createMinimaxService(deps, {
			baseUrl: config.minimaxBaseUrl,
			keyRef: config.minimaxKeyRef,
			lowPct: config.minimaxLowPct,
			openclawConfigPath: config.minimaxOpenclawConfigPath
		})
	},
	{
		id: "claude",
		label: "Claude",
		create: (deps, config) => createClaudeService(deps, {
			credentialsPath: config.claudeCredentialsPath,
			usageUrl: config.claudeUsageUrl,
			lowPct: config.claudeLowPct
		})
	},
	{
		id: "codex",
		label: "Codex",
		create: (deps, config) => createCodexService(deps, {
			command: config.codexCommand,
			lowPct: config.codexLowPct,
			refreshMs: config.codexRefreshMs
		})
	}
];
function createBalanceReader(credentials, config) {
	const services = BALANCE_PROVIDERS.map((provider) => provider.create({ credentials }, config));
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
