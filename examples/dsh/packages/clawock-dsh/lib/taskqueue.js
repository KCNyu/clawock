import { expandHome } from "./balance.js";
import { join } from "node:path";
import { closeSync, existsSync, fstatSync, openSync, readFileSync, readSync, readdirSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
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
*   <limitsPath>                         `MAX_RUNNING_<AGENT>=<n>` (each agent's own slots) and
*                                        their display-only sum `MAX_RUNNING`, shared with both
*   <patrolDir>/current-round, rounds.tsv
*   agent-dispatch-<id>.service          active = the task is still alive
*   clawock-patrol.service + its journal the supervisor's own last words
*   <logDir>/<id>/override.env           PRIORITY / MODEL / EFFORT set from the chip (read only here)
*   task_queue_ops.py --json list        per-agent lock holder and queue order
*
* Every WRITE (cancel, priority, model, retry, wrap-up) goes through the
* versioned ops entry `task_queue_ops.py` (ops/host in the clawock repo,
* installed next to the runner): this module never runs systemctl stop,
* flock or edits a task directory. `runQueueAction` is that one door.
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
const DEFAULT_TASK_QUEUE_OPS_PATH = join(homedir(), "tools", "agent-dispatch", "task_queue_ops.py");
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
function runOpsProcess(opsPath, args, timeoutMs) {
	return new Promise((resolve) => {
		execFile("python3", [
			opsPath,
			"--json",
			...args
		], {
			timeout: timeoutMs,
			maxBuffer: 4 << 20
		}, (error, stdout, stderr) => {
			resolve({
				code: error === null ? 0 : typeof error.code === "number" ? error.code : -1,
				stdout: String(stdout ?? ""),
				stderr: String(stderr ?? "")
			});
		});
	});
}
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
	},
	runOps: runOpsProcess
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
/** `weixin,telegram` → ['weixin', 'telegram']; 'none' and blanks dropped, each once. */
function channelList(raw) {
	return [...new Set((raw ?? "").split(",").map((part) => part.trim().toLowerCase()).filter((part) => part !== "" && part !== "none"))];
}
const epochMs = (raw) => {
	const value = Number.parseInt(raw ?? "", 10);
	return Number.isFinite(value) && value > 0 ? value * 1e3 : null;
};
function readTask(logDir, id, alive) {
	const dir = join(logDir, id);
	const meta = readEnvFile(join(dir, "meta.env"));
	const result = readEnvFile(join(dir, "result.env"));
	const override = readEnvFile(join(dir, "override.env"));
	const waiting = alive ? result.WAITING ?? "" : "";
	const log = logTail(dir);
	const event = alive ? lastLogEvent(log) : {
		text: "",
		atMs: null
	};
	let cancelling = false;
	if (alive) try {
		cancelling = Date.now() - statSync(join(dir, "cancel-requested")).mtimeMs < 6e4;
	} catch {}
	return {
		id,
		name: meta.NAME ?? id,
		agent: meta.AGENT ?? "",
		model: result.MODEL_USED || meta.MODEL || "",
		state: result.STATE ?? "queued",
		waiting,
		slot: alive ? result.SLOT ?? "" : "",
		attempts: Number.parseInt(result.ATTEMPTS ?? "0", 10) || 0,
		stalls: Number.parseInt(result.STALLS ?? "0", 10) || 0,
		outcome: result.OUTCOME ?? "",
		startedAtMs: localStampMs(result.STARTED ?? meta.CREATED),
		updatedAtMs: localStampMs(result.UPDATED),
		wakeAtMs: alive && (waiting === "quota" || waiting === "retry") ? epochMs(result.WAKE_AT) ?? wakeAt(log) : null,
		patrol: id.startsWith("patrol-"),
		summary: alive ? "" : finalSummary(log),
		lastEvent: event.text,
		lastEventAtMs: event.atMs,
		queuedAtMs: epochMs(result.QUEUED_AT),
		position: null,
		priority: Number.parseInt(override.PRIORITY ?? "0", 10) || 0,
		protected: false,
		modelRequested: override.MODEL || meta.MODEL || "",
		modelUsed: result.MODEL_USED ?? "",
		effortRequested: override.EFFORT || meta.EFFORT || "",
		effortUsed: result.EFFORT_USED ?? "",
		notify: channelList(meta.NOTIFY),
		notified: channelList(result.NOTIFIED),
		notifyFailed: channelList(result.NOTIFY_FAILED),
		notifyAtMs: localStampMs(result.NOTIFY_AT),
		runnerApi: Number.parseInt(result.RUNNER_API ?? "1", 10) || 1,
		legacy: (Number.parseInt(result.RUNNER_API ?? "1", 10) || 1) < 2,
		session: result.SESSION ?? "",
		cancelling
	};
}
function readLimits(path) {
	const env = readEnvFile(path);
	const count = (raw) => {
		const value = Number.parseInt(raw ?? "", 10);
		return Number.isFinite(value) && value > 0 ? value : 0;
	};
	const slotLimits = Object.keys(env).filter((key) => /^MAX_RUNNING_[A-Z0-9]+$/.test(key)).map((key) => ({
		agent: key.slice(12).toLowerCase(),
		max: count(env[key])
	}));
	return {
		maxRunning: count(env.MAX_RUNNING),
		slotLimits
	};
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
/** sha256 of a file, 12 hex — the same hash the ops entry reports as its ops_version. */
function fileVersion(path) {
	if (path === "") return "";
	try {
		return createHash("sha256").update(readFileSync(path)).digest("hex").slice(0, 12);
	} catch {
		return "";
	}
}
/** The ops entry's `list`, or why it could not be read. */
async function readOps(config, deps) {
	const base = {
		available: false,
		version: "",
		repoVersion: fileVersion(config.repoOpsPath),
		api: 0,
		runnerApi: 0,
		fairWaitSec: 0,
		error: ""
	};
	if (deps.runOps === void 0) return {
		ops: {
			...base,
			error: "no ops runner"
		},
		list: null
	};
	if (!existsSync(config.opsPath)) return {
		ops: {
			...base,
			error: `ops entry not installed at ${config.opsPath}`
		},
		list: null
	};
	const r = await deps.runOps(config.opsPath, ["list"], COMMAND_TIMEOUT_MS);
	let list = null;
	try {
		list = JSON.parse(r.stdout);
	} catch {
		list = null;
	}
	if (r.code !== 0 || list === null) return {
		ops: {
			...base,
			error: (r.stderr || r.stdout).trim().slice(-300) || `ops list exited ${r.code}`
		},
		list: null
	};
	return {
		ops: {
			...base,
			available: true,
			version: list.ops_version ?? "",
			api: list.api ?? 0,
			runnerApi: list.runner?.api ?? 0,
			fairWaitSec: list.fair_wait_sec ?? 0
		},
		list
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
		slotLimits: [],
		running: 0,
		active: [],
		recent: [],
		patrol: empty
	};
	const [activeIds, service, log, opsRead] = await Promise.all([
		deps.activeTaskIds(),
		deps.patrolService(),
		deps.patrolLog(),
		readOps(config, deps)
	]);
	const alive = new Set(activeIds.filter((id) => existsSync(join(config.logDir, id))));
	const since = (task) => task.queuedAtMs ?? task.startedAtMs ?? Number.MAX_SAFE_INTEGER;
	const active = [...alive].map((id) => readTask(config.logDir, id, true)).sort((a, b) => since(a) - since(b));
	const queues = [];
	for (const [agent, group] of Object.entries(opsRead.list?.agents ?? {})) {
		const order = (group.queue ?? []).map((row) => row.id);
		for (const row of group.queue ?? []) {
			const task = active.find((candidate) => candidate.id === row.id);
			if (task !== void 0) {
				Object.assign(task, {
					position: row.position,
					protected: row.protected,
					priority: row.priority,
					legacy: row.legacy === true
				});
				if (task.queuedAtMs == null && typeof row.queued_at === "number") task.queuedAtMs = row.queued_at * 1e3;
			}
		}
		queues.push({
			agent,
			held: group.holder?.held === true,
			holder: group.holder?.id ?? "",
			order,
			holderLegacy: group.holder?.legacy === true,
			holderNote: group.holder?.note ?? "",
			quotaUntilMs: group.quota ? group.quota.until * 1e3 : null,
			quotaBy: group.quota?.by ?? ""
		});
	}
	active.sort((a, b) => since(a) - since(b));
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
		...readLimits(config.limitsPath),
		running: active.filter((task) => task.slot !== "").length,
		active,
		recent: ended,
		patrol: {
			...patrolPhase(service, round, alive.has(round), log),
			rounds: readRounds(config.patrolDir, 3)
		},
		queues,
		ops: opsRead.ops
	};
}
/** TTL cache + in-flight join + stale-on-failure, the balance services' cadence shell in miniature. */
function createTaskQueueService(config = {}, deps = systemDeps) {
	const resolved = {
		logDir: expandHome(config.logDir ?? DEFAULT_DISPATCH_LOG_DIR),
		limitsPath: expandHome(config.limitsPath ?? DEFAULT_DISPATCH_LIMITS_PATH),
		patrolDir: expandHome(config.patrolDir ?? DEFAULT_PATROL_STATE_DIR),
		refreshMs: config.refreshMs ?? 15e3,
		recent: config.recent ?? 5,
		opsPath: expandHome(config.opsPath ?? DEFAULT_TASK_QUEUE_OPS_PATH),
		repoOpsPath: config.repoOpsPath ?? ""
	};
	let last = null;
	let fetchedAt = 0;
	let lastError = null;
	let inFlight = null;
	const answer = (status, message) => ({
		available: false,
		asOf: "",
		maxRunning: 0,
		slotLimits: [],
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
			lastError = null;
			return answer("fresh", null);
		} catch (cause) {
			const message = cause instanceof Error ? cause.message : String(cause);
			if (last !== null) lastError = message;
			return answer(last !== null ? "stale" : "failed", message);
		}
	};
	return {
		invalidate() {
			fetchedAt = 0;
		},
		async get(force) {
			if (!force && last !== null && Date.now() - fetchedAt < TTL_MS) return lastError !== null ? answer("stale", lastError) : answer("cached", null);
			if (inFlight !== null) return inFlight;
			inFlight = exec();
			try {
				return await inFlight;
			} finally {
				inFlight = null;
			}
		}
	};
}
/** The actions the chip may run, and how each maps onto the ops entry's arguments. */
const QUEUE_ACTIONS = [
	"cancel",
	"priority",
	"model",
	"choices",
	"retry",
	"wrapup",
	"log"
];
const TASK_ID = /^[a-z0-9][a-z0-9-]{0,80}$/;
const PRIORITY_ARG = /^(top|up|down|reset|-?\d{1,2})$/;
const MODEL_TOKEN = /^[A-Za-z0-9._/:@-]{1,120}$/;
/** Queued, not interrupting: the task finishes its current step, then lands what it has. */
const WRAPUP_TEXT = "请体面收尾：不要再开新的工作。把已经完成的部分提交/推送（按原任务的流程），写清楚做了什么、没做什么和下一步，然后输出 STATUS 行（没做完就是 STATUS: PARTIAL）。";
/** The ops arguments for one chip action, or why the input is refused before anything runs. */
function opsArgsFor(action, id, arg) {
	if (!QUEUE_ACTIONS.includes(action)) return `unknown action ${JSON.stringify(action)}`;
	if (!TASK_ID.test(id)) return `not a task id: ${JSON.stringify(id)}`;
	switch (action) {
		case "priority": return PRIORITY_ARG.test(arg) ? [
			"priority",
			id,
			arg
		] : `priority takes top, up, down, reset or an integer (got ${JSON.stringify(arg)})`;
		case "model": {
			const [model = "", effort = "keep"] = arg.split("|");
			if (!MODEL_TOKEN.test(model) || !MODEL_TOKEN.test(effort)) return `model takes "<model|keep|default>|<effort|keep|default>" (got ${JSON.stringify(arg)})`;
			return [
				"model",
				id,
				model,
				effort
			];
		}
		case "wrapup": return [
			"append",
			id,
			"--queue",
			"--text",
			WRAPUP_TEXT
		];
		case "log": return [
			"log",
			id,
			"--lines",
			"80"
		];
		default: return [action, id];
	}
}
const ACTION_TIMEOUT_MS = 3e4;
/** A second identical write inside this window returns the first one's answer (a double click). */
const REPEAT_WINDOW_MS = 2e3;
/**
* The chip's write path: validate, then run the ops entry with --source ui.
* Identical calls in flight share one run, and a repeat within 2 s gets the
* same answer, so a double click can never cancel or reorder twice (the ops
* entry also serialises writes per task and treats a repeat cancel as a no-op).
* Never throws: every failure is an in-band `{ ok: false, code, message }`.
*/
function createQueueActionRunner(config = {}, deps = systemDeps, onWrite = () => {}) {
	const opsPath = expandHome(config.opsPath ?? DEFAULT_TASK_QUEUE_OPS_PATH);
	const inFlight = /* @__PURE__ */ new Map();
	const recent = /* @__PURE__ */ new Map();
	const exec = async (action, id, args) => {
		const fail = (code, message) => ({
			ok: false,
			code,
			action,
			id,
			message,
			detail: ""
		});
		if (deps.runOps === void 0) return fail(-1, "no ops runner");
		if (!existsSync(opsPath)) return fail(-1, `ops entry not installed at ${opsPath} (ops/host/install_task_queue_ops.sh)`);
		const r = await deps.runOps(opsPath, [
			"--source",
			"ui",
			...args
		], ACTION_TIMEOUT_MS);
		const answer = (() => {
			try {
				return JSON.parse(r.stdout);
			} catch {
				return null;
			}
		})();
		if (answer === null) return fail(r.code === 0 ? -1 : r.code, (r.stderr || r.stdout).trim().slice(-300) || `ops entry exited ${r.code}`);
		const ok = r.code === 0 && answer.ok === true;
		return {
			ok,
			code: r.code,
			action,
			id,
			message: (ok ? answer.message : answer.error ?? answer.message) ?? "",
			detail: r.stdout.trim()
		};
	};
	return async (action, id, arg) => {
		const args = opsArgsFor(action, id, arg);
		if (typeof args === "string") return {
			ok: false,
			code: 2,
			action,
			id,
			message: args,
			detail: ""
		};
		const key = [
			action,
			id,
			arg
		].join("\0");
		const read = action === "choices" || action === "log";
		const last = recent.get(key);
		if (!read && last !== void 0 && Date.now() - last.at < REPEAT_WINDOW_MS) return last.result;
		const pending = inFlight.get(key);
		if (pending !== void 0) return pending;
		const job = exec(action, id, args).then((result) => {
			if (!read) {
				recent.set(key, {
					at: Date.now(),
					result
				});
				onWrite();
			}
			return result;
		}).finally(() => {
			inFlight.delete(key);
		});
		inFlight.set(key, job);
		return job;
	};
}
//#endregion
export { DEFAULT_DISPATCH_LIMITS_PATH, DEFAULT_DISPATCH_LOG_DIR, DEFAULT_PATROL_STATE_DIR, DEFAULT_TASK_QUEUE_OPS_PATH, DEFAULT_TASK_QUEUE_RECENT, DEFAULT_TASK_QUEUE_REFRESH_MS, QUEUE_ACTIONS, WRAPUP_TEXT, channelList, createQueueActionRunner, createTaskQueueService, fileVersion, finalSummary, lastLogEvent, localStampMs, opsArgsFor, patrolPhase, readEnvFile, readTaskQueue, systemDeps, unquoteShell };
