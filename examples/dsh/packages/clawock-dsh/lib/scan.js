import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
//#region src/scan.ts
/**
* Read-only scanner over a clawock workspace: prepared runs, the current
* decision artifact, and published receipts. Pure Node, no Cordis/typert
* dependencies — unit-testable in isolation.
*
* Layout (from the clawock contract):
*   <workspace>/.clawock/work/<run_id>/request.json   certified request
*   <workspace>/decision.json                         current artifact
*   <workspace>/.clawock/runs/<run_id>/               receipt store (manifest.json + artifacts)
*/
/** Request files are written under .clawock/work/<32-hex run id>/request.json. */
const RUN_ID_PATTERN = /^[0-9a-f]{32}$/;
/** Validate a run id; this is also the path-safety boundary for directory joins. */
function runIdOf(value) {
	if (typeof value !== "string" || !RUN_ID_PATTERN.test(value)) throw new TypeError(`invalid clawock run id: ${String(value)}`);
	return value;
}
function readJson(path) {
	if (!existsSync(path)) return null;
	try {
		return JSON.parse(readFileSync(path, "utf8"));
	} catch {
		return null;
	}
}
function decisionOf(workspace) {
	return readJson(join(workspace, "decision.json"));
}
function manifestOf(workspace, runId) {
	return readJson(join(workspace, ".clawock", "runs", runId, "manifest.json"));
}
/**
* Snapshot every prepared run with enough to render a list row.
* @param workspace - clawock workspace root.
* @returns runs ordered by request file mtime, newest first.
*/
function listRuns(workspace) {
	const workDir = join(workspace, ".clawock", "work");
	let entries = [];
	try {
		entries = readdirSync(workDir, { withFileTypes: true }).filter((e) => e.isDirectory() && RUN_ID_PATTERN.test(e.name)).map((e) => e.name);
	} catch {
		return [];
	}
	const runs = [];
	const decision = decisionOf(workspace);
	for (const entry of entries) {
		const requestPath = join(workDir, entry, "request.json");
		if (!existsSync(requestPath)) continue;
		const request = readJson(requestPath);
		if (request === null || typeof request !== "object" || Array.isArray(request)) continue;
		const req = request;
		const subject = typeof req["subject"] === "string" ? req["subject"] : null;
		const decisionSubject = decision !== null && typeof decision === "object" && !Array.isArray(decision) && typeof decision["subject"] === "string" ? decision["subject"] : null;
		const decisionAction = decision !== null && typeof decision === "object" && !Array.isArray(decision) && decision["decision"] !== null && typeof decision["decision"] === "object" && decision["decision"] !== void 0 && typeof decision["decision"]["action"] === "string" ? decision["decision"]["action"] : null;
		const asOf = typeof req["as_of"] === "string" ? req["as_of"] : null;
		const task = typeof req["task"] === "string" ? req["task"] : null;
		const workflow = req["workflow"] ?? null;
		const gates = req["workflow"] !== null && typeof req["workflow"] === "object" ? req["workflow"]["parameters"] ?? null : null;
		let mtimeMs = 0;
		try {
			mtimeMs = statSync(requestPath).mtimeMs;
		} catch {}
		runs.push({
			runId: entry,
			subject,
			decisionSubject,
			decisionAction,
			asOf,
			task,
			workflow,
			gates,
			documentCount: Array.isArray((req["context"] ?? {})["documents"]) ? req["context"]["documents"].length : 0,
			decisionPresent: decision !== null,
			receiptPresent: manifestOf(workspace, entry) !== null,
			mtimeMs
		});
	}
	runs.sort((a, b) => b.mtimeMs - a.mtimeMs);
	return runs;
}
/**
* Full detail of one run: certified request, current decision artifact and
* receipt manifest. Missing pieces stay null — a prepared-but-unpublished
* run is a valid state.
* @param workspace - clawock workspace root.
* @param runId - 32-hex run id; anything else is rejected before any path use.
*/
function getRun(workspace, runIdValue) {
	const id = runIdOf(runIdValue);
	const request = readJson(join(workspace, ".clawock", "work", id, "request.json"));
	if (request === null) return {
		runId: id,
		request: null,
		decision: null,
		manifest: null
	};
	return {
		runId: id,
		request,
		decision: decisionOf(workspace),
		manifest: manifestOf(workspace, id)
	};
}
//#endregion
export { RUN_ID_PATTERN, getRun, listRuns, runIdOf };
