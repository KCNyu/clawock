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
import type { PatrolStatus, QueueActionResult, TaskQueueResult } from './types.ts';
export declare const DEFAULT_DISPATCH_LOG_DIR: string;
export declare const DEFAULT_DISPATCH_LIMITS_PATH: string;
export declare const DEFAULT_PATROL_STATE_DIR: string;
export declare const DEFAULT_TASK_QUEUE_OPS_PATH: string;
export declare const DEFAULT_TASK_QUEUE_REFRESH_MS = 15000;
export declare const DEFAULT_TASK_QUEUE_RECENT = 5;
export interface TaskQueueConfig {
    logDir?: string;
    limitsPath?: string;
    patrolDir?: string;
    refreshMs?: number;
    recent?: number;
    /** The installed ops entry (default ~/tools/agent-dispatch/task_queue_ops.py). */
    opsPath?: string;
    /** The repository's copy of it, hashed to show a merged-but-not-installed entry ('' = skip). */
    repoOpsPath?: string;
}
/** The host commands, injectable so tests run without systemd. */
export interface TaskQueueDeps {
    /** Ids of the active `agent-dispatch-<id>.service` units. */
    activeTaskIds(): Promise<string[]>;
    /** `systemctl is-active clawock-patrol` ('' when systemctl is unavailable). */
    patrolService(): Promise<string>;
    /** The supervisor's most recent journal lines, oldest first, timestamps kept. */
    patrolLog(): Promise<string[]>;
    /** Run the ops entry: `python3 <opsPath> --json …`. Optional: tests without it get no queue order. */
    runOps?(opsPath: string, args: string[], timeoutMs: number): Promise<OpsRun>;
}
/** One run of the ops entry. `code` is its exit status (-1: it did not run or timed out). */
export interface OpsRun {
    code: number;
    stdout: string;
    stderr: string;
}
export declare const systemDeps: TaskQueueDeps;
/** One `printf %q` value: '' / $'…' / backslash escapes. */
export declare function unquoteShell(raw: string): string;
/** KEY=value lines as the runner writes them; unreadable file → {}. */
export declare function readEnvFile(path: string): Record<string, string>;
/** `2026-09-23 02:54:09` in the writer's local time (the runner and dsh share this host's zone). */
export declare function localStampMs(stamp: string | undefined): number | null;
/**
 * The agent's closing words: the last run of `final | ` lines the runner
 * echoes after an attempt (its final report's tail, already redacted), minus
 * blank lines and the STATUS line the outcome field carries anyway.
 */
export declare function finalSummary(log: string): string;
/** The runner's latest stamped event (`<ts> got run slot 1`, `---- <ts> attempt 2/3 …`). */
export declare function lastLogEvent(log: string): {
    text: string;
    atMs: number | null;
};
/** `weixin,telegram` → ['weixin', 'telegram']; 'none' and blanks dropped, each once. */
export declare function channelList(raw: string | undefined): string[];
/**
 * What the supervisor is doing, from its own last log line: `waiting: <why>`
 * (giving way before a round), `preempting …` (cancelling one for a user
 * task), `next round in Ns` (gap or backoff), a dispatched/adopted round.
 */
export declare function patrolPhase(service: string, round: string, roundAlive: boolean, log: string[]): Omit<PatrolStatus, 'rounds'>;
/** One full read. Throws only when the dispatch log directory itself is unreadable. */
type QueueRead = Omit<TaskQueueResult, 'status' | 'message' | 'refreshMs'>;
/** sha256 of a file, 12 hex — the same hash the ops entry reports as its ops_version. */
export declare function fileVersion(path: string): string;
export declare function readTaskQueue(config: Required<TaskQueueConfig>, deps: TaskQueueDeps): Promise<QueueRead>;
export type TaskQueueService = {
    get(force: boolean): Promise<TaskQueueResult>;
    /** Forget the cached read: the next get() reads the files again (after a write). */
    invalidate(): void;
};
/** TTL cache + in-flight join + stale-on-failure, the balance services' cadence shell in miniature. */
export declare function createTaskQueueService(config?: TaskQueueConfig, deps?: TaskQueueDeps): TaskQueueService;
/** The actions the chip may run, and how each maps onto the ops entry's arguments. */
export declare const QUEUE_ACTIONS: readonly ['cancel', 'priority', 'model', 'choices', 'retry', 'wrapup', 'log'];
export type QueueAction = typeof QUEUE_ACTIONS[number];
/** Queued, not interrupting: the task finishes its current step, then lands what it has. */
export declare const WRAPUP_TEXT: string;
/** The ops arguments for one chip action, or why the input is refused before anything runs. */
export declare function opsArgsFor(action: string, id: string, arg: string): string[] | string;
export type QueueActionRunner = (action: string, id: string, arg: string) => Promise<QueueActionResult>;
/**
 * The chip's write path: validate, then run the ops entry with --source ui.
 * Identical calls in flight share one run, and a repeat within 2 s gets the
 * same answer, so a double click can never cancel or reorder twice (the ops
 * entry also serialises writes per task and treats a repeat cancel as a no-op).
 * Never throws: every failure is an in-band `{ ok: false, code, message }`.
 */
export declare function createQueueActionRunner(config?: TaskQueueConfig, deps?: Pick<TaskQueueDeps, 'runOps'>, onWrite?: () => void): QueueActionRunner;
export {};
