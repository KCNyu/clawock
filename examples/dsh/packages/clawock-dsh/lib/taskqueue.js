import { expandHome } from "./balance.js";
import { join } from "node:path";
import { closeSync, existsSync, fstatSync, openSync, readFileSync, readSync, readdirSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { execFile } from "node:child_process";
//#region src/taskqueue.ts
/**
* The dispatch queue behind the sidebar-foot task chip: which agent-dispatch
* tasks are alive, what each one waits for, what just finished, and what the
* clawock-patrol supervisor is doing (running a round, giving way, or waiting
* for its next one). Everything is read from this host — files the runner and
* the supervisor write, plus systemctl/journalctl — never the network.
*
*   <logDir>/<id>/meta.env, result.env   bash `printf %q` assignments
*   <logDir>/<id>/run.log                `---- <ts> quota; sleeping until <ts>`,
*                                        `<ts> <event>` lines, `final | <text>` (the agent's closing lines)
*   <limitsPath>                         `MAX_RUNNING=<n>`, shared with both
*   <patrolDir>/current-round, rounds.tsv
*   agent-dispatch-<id>.service          active = the task is still alive
*   clawock-patrol.service + its journal the supervisor's own last words
*
* The chip only exists on a host that runs the dispatcher: without `logDir`
* the answer is `available: false` and the client renders nothing, so the
* published plugin stays inert elsewhere. Same in-band contract as the
* balance services: `get()` never throws, a failed read keeps the last good
* snapshot as 'stale'.
*/
const DEFAULT_DISPATCH_LOG_DIR = join(homedir(), "logs", "agent-dispatch");
const DEFAULT_DISPATCH_LIMITS_PATH = join(homedir(), "tools", "agent-dispatch", "limits.env");
const DEFAULT_PATROL_STATE_DIR = join(homedir(), "logs", "clawock-patrol");
const DEFAULT_TASK_QUEUE_REFRESH_MS = 15e3;
const DEFAULT_TASK_QUEUE_RECENT = 5;
/** Host-side cache: every open tab polls, the files are read once per window. */
const TTL_MS = 5e3;
const COMMAND_TIMEOUT_MS = 5e3;
/** How much of a run log's end is read: every line the queue shows sits in its last few KB. */
const LOG_TAIL_BYTES = 65536;
/** The detail panel's cap on the closing report (the runner already keeps only six lines). */
const SUMMARY_MAX_CHARS = 800;
const PATROL_UNIT = "clawock-patrol";
function run(command, args) {
	return new Promise((resolve) => {
		execFile(command, args, { timeout: COMMAND_TIMEOUT_MS }, (_error, stdout) => {
			resolve(String(stdout ?? ""));
		});
	});
}
const systemDeps = {
	async activeTaskIds() {
		return (await run("systemctl", [
			"list-units",
			"agent-dispatch-*",
			"--state=active",
			"--no-legend",
			"--plain"
		])).split("\n").map((line) => line.trim().split(/\s+/)[0] ?? "").filter((unit) => unit.startsWith("agent-dispatch-") && unit.endsWith(".service")).map((unit) => unit.slice(15, -8));
	},
	async patrolService() {
		return (await run("systemctl", ["is-active", PATROL_UNIT])).trim();
	},
	async patrolLog() {
		return (await run("journalctl", [
			"-u",
			PATROL_UNIT,
			"-n",
			"12",
			"-o",
			"cat",
			"--no-pager"
		])).split("\n").filter((line) => line.trim() !== "");
	}
};
/** One `printf %q` value: '' / $'…' / backslash escapes. */
function unquoteShell(raw) {
	if (raw === "''") return "";
	if (raw.startsWith("$'") && raw.endsWith("'")) return raw.slice(2, -1).replace(/\\(.)/g, (_, c) => ({
		n: "\n",
		t: "	"
	})[c] ?? c);
	if (raw.length >= 2 && raw.startsWith("'") && raw.endsWith("'")) return raw.slice(1, -1);
	return raw.replace(/\\(.)/g, "$1");
}
/** KEY=value lines as the runner writes them; unreadable file → {}. */
function readEnvFile(path) {
	let text;
	try {
		text = readFileSync(path, "utf8");
	} catch {
		return {};
	}
	const out = {};
	for (const line of text.split("\n")) {
		const match = /^([A-Z_][A-Z0-9_]*)=(.*)$/.exec(line);
		if (match) out[match[1]] = unquoteShell(match[2]);
	}
	return out;
}
/** `2026-09-23 02:54:09` in the writer's local time (the runner and dsh share this host's zone). */
function localStampMs(stamp) {
	const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/.exec((stamp ?? "").trim());
	if (!match) return null;
	const [, y, mo, d, h, mi, s] = match.map(Number);
	return new Date(y, mo - 1, d, h, mi, s).getTime();
}
/** The end of a task's run.log (a cut first line dropped); '' when there is none. */
function logTail(dir) {
	let fd;
	try {
		fd = openSync(join(dir, "run.log"), "r");
	} catch {
		return "";
	}
	try {
		const size = fstatSync(fd).size;
		const start = Math.max(0, size - LOG_TAIL_BYTES);
		const buffer = Buffer.alloc(size - start);
		readSync(fd, buffer, 0, buffer.length, start);
		const text = buffer.toString("utf8");
		return start === 0 ? text : text.slice(text.indexOf("\n") + 1);
	} catch {
		return "";
	} finally {
		closeSync(fd);
	}
}
/** When a quota/retry wait ends: the last `sleeping until` line of the run log. */
function wakeAt(log) {
	const matches = [...log.matchAll(/sleeping until (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/g)];
	const last = matches[matches.length - 1];
	return last === void 0 ? null : localStampMs(last[1]);
}
/**
* The agent's closing words: the last run of `final | ` lines the runner
* echoes after an attempt (its final report's tail, already redacted), minus
* blank lines and the STATUS line the outcome field carries anyway.
*/
function finalSummary(log) {
	const lines = log.split("\n");
	const isFinal = (line) => /^final \|( |$)/.test(line);
	let end = lines.length - 1;
	while (end >= 0 && !isFinal(lines[end])) end -= 1;
	if (end < 0) return "";
	let start = end;
	while (start > 0 && isFinal(lines[start - 1])) start -= 1;
	return lines.slice(start, end + 1).map((line) => line.replace(/^final \| ?/, "").trimEnd()).filter((line) => line.trim() !== "" && !/^STATUS:\s/.test(line.trim())).join("\n").slice(0, SUMMARY_MAX_CHARS);
}
/** The runner's latest stamped event (`<ts> got run slot 1`, `---- <ts> attempt 2/3 …`). */
function lastLogEvent(log) {
	const lines = log.split("\n");
	for (let i = lines.length - 1; i >= 0; i -= 1) {
		const match = /^(?:---- )?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.+)$/.exec(lines[i]);
		if (match) return {
			text: match[2].trim(),
			atMs: localStampMs(match[1])
		};
	}
	return {
		text: "",
		atMs: null
	};
}
function readTask(logDir, id, alive) {
	const dir = join(logDir, id);
	const meta = readEnvFile(join(dir, "meta.env"));
	const result = readEnvFile(join(dir, "result.env"));
	const waiting = alive ? result.WAITING ?? "" : "";
	const log = logTail(dir);
	const event = alive ? lastLogEvent(log) : {
		text: "",
		atMs: null
	};
	return {
		id,
		name: meta.NAME ?? id,
		agent: meta.AGENT ?? "",
		model: result.MODEL_USED || meta.MODEL || "",
		state: result.STATE ?? "queued",
		waiting,
		slot: alive ? result.SLOT ?? "" : "",
		attempts: Number.parseInt(result.ATTEMPTS ?? "0", 10) || 0,
		outcome: result.OUTCOME ?? "",
		startedAtMs: localStampMs(result.STARTED ?? meta.CREATED),
		updatedAtMs: localStampMs(result.UPDATED),
		wakeAtMs: alive && (waiting === "quota" || waiting === "retry") ? wakeAt(log) : null,
		patrol: id.startsWith("patrol-"),
		summary: alive ? "" : finalSummary(log),
		lastEvent: event.text,
		lastEventAtMs: event.atMs
	};
}
function readMaxRunning(path) {
	const value = Number.parseInt(readEnvFile(path).MAX_RUNNING ?? "", 10);
	return Number.isFinite(value) && value > 0 ? value : 0;
}
function readRounds(patrolDir, limit) {
	let text;
	try {
		text = readFileSync(join(patrolDir, "rounds.tsv"), "utf8");
	} catch {
		return [];
	}
	return text.split("\n").filter((line) => line.trim() !== "").slice(-limit).reverse().map((line) => {
		const [endedAt = "", round = "", axis = "", , result = "", took = ""] = line.split("	");
		const seconds = Number.parseInt(took, 10);
		return {
			endedAt,
			round,
			axis,
			result,
			seconds: Number.isFinite(seconds) ? seconds : null
		};
	});
}
/**
* What the supervisor is doing, from its own last log line: `waiting: <why>`
* (giving way before a round), `preempting …` (cancelling one for a user
* task), `next round in Ns` (gap or backoff), a dispatched/adopted round.
*/
function patrolPhase(service, round, roundAlive, log) {
	const lines = log.map((line) => /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$/.exec(line)).filter((match) => match !== null);
	const last = lines[lines.length - 1];
	const detail = last?.[2] ?? "";
	const base = {
		service: service || "unknown",
		round,
		detail,
		untilMs: null
	};
	if (service !== "active") return {
		...base,
		phase: "stopped"
	};
	if (round !== "" && roundAlive && !/^preempting /.test(detail)) return {
		...base,
		phase: "running"
	};
	if (last === void 0) return {
		...base,
		phase: "unknown"
	};
	if (/^(waiting: |preempting )/.test(detail)) return {
		...base,
		phase: "yielding"
	};
	const gap = /^next round in (\d+)s$/.exec(detail);
	if (gap) {
		const from = localStampMs(last[1]);
		return {
			...base,
			phase: "waiting",
			untilMs: from === null ? null : from + Number(gap[1]) * 1e3
		};
	}
	return {
		...base,
		phase: round !== "" ? "running" : "unknown"
	};
}
async function readTaskQueue(config, deps) {
	const asOf = (/* @__PURE__ */ new Date()).toISOString();
	const empty = {
		service: "unknown",
		phase: "unknown",
		round: "",
		detail: "",
		untilMs: null,
		rounds: []
	};
	if (!existsSync(config.logDir)) return {
		available: false,
		asOf,
		maxRunning: 0,
		running: 0,
		active: [],
		recent: [],
		patrol: empty
	};
	const [activeIds, service, log] = await Promise.all([
		deps.activeTaskIds(),
		deps.patrolService(),
		deps.patrolLog()
	]);
	const alive = new Set(activeIds.filter((id) => existsSync(join(config.logDir, id))));
	const active = [...alive].map((id) => readTask(config.logDir, id, true)).sort((a, b) => (a.startedAtMs ?? Number.MAX_SAFE_INTEGER) - (b.startedAtMs ?? Number.MAX_SAFE_INTEGER));
	const ended = readdirSync(config.logDir, { withFileTypes: true }).filter((entry) => entry.isDirectory() && !alive.has(entry.name) && !entry.name.startsWith("patrol-")).map((entry) => {
		try {
			return {
				id: entry.name,
				at: statSync(join(config.logDir, entry.name, "result.env")).mtimeMs
			};
		} catch {
			return null;
		}
	}).filter((row) => row !== null).sort((a, b) => b.at - a.at).slice(0, config.recent * 3).map((row) => readTask(config.logDir, row.id, false)).sort((a, b) => (b.updatedAtMs ?? 0) - (a.updatedAtMs ?? 0)).slice(0, config.recent);
	let round = "";
	try {
		round = readFileSync(join(config.patrolDir, "current-round"), "utf8").trim();
	} catch {}
	return {
		available: true,
		asOf,
		maxRunning: readMaxRunning(config.limitsPath),
		running: active.filter((task) => task.slot !== "").length,
		active,
		recent: ended,
		patrol: {
			...patrolPhase(service, round, alive.has(round), log),
			rounds: readRounds(config.patrolDir, 3)
		}
	};
}
/** TTL cache + in-flight join + stale-on-failure, the balance services' cadence shell in miniature. */
function createTaskQueueService(config = {}, deps = systemDeps) {
	const resolved = {
		logDir: expandHome(config.logDir ?? DEFAULT_DISPATCH_LOG_DIR),
		limitsPath: expandHome(config.limitsPath ?? DEFAULT_DISPATCH_LIMITS_PATH),
		patrolDir: expandHome(config.patrolDir ?? DEFAULT_PATROL_STATE_DIR),
		refreshMs: config.refreshMs ?? 15e3,
		recent: config.recent ?? 5
	};
	let last = null;
	let fetchedAt = 0;
	let inFlight = null;
	const answer = (status, message) => ({
		available: false,
		asOf: "",
		maxRunning: 0,
		running: 0,
		active: [],
		recent: [],
		patrol: {
			service: "unknown",
			phase: "unknown",
			round: "",
			detail: "",
			untilMs: null,
			rounds: []
		},
		...last ?? {},
		status,
		message,
		refreshMs: resolved.refreshMs
	});
	const exec = async () => {
		try {
			last = await readTaskQueue(resolved, deps);
			fetchedAt = Date.now();
			return answer("fresh", null);
		} catch (cause) {
			const message = cause instanceof Error ? cause.message : String(cause);
			return answer(last !== null ? "stale" : "failed", message);
		}
	};
	return { async get(force) {
		if (!force && last !== null && Date.now() - fetchedAt < TTL_MS) return answer("cached", null);
		if (inFlight !== null) return inFlight;
		inFlight = exec();
		try {
			return await inFlight;
		} finally {
			inFlight = null;
		}
	} };
}
//#endregion
export { DEFAULT_DISPATCH_LIMITS_PATH, DEFAULT_DISPATCH_LOG_DIR, DEFAULT_PATROL_STATE_DIR, DEFAULT_TASK_QUEUE_RECENT, DEFAULT_TASK_QUEUE_REFRESH_MS, createTaskQueueService, finalSummary, lastLogEvent, localStampMs, patrolPhase, readEnvFile, readTaskQueue, systemDeps, unquoteShell };
