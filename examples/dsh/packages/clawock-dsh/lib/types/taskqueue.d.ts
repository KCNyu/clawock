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
import type { PatrolStatus, TaskQueueResult } from './types.ts';
export declare const DEFAULT_DISPATCH_LOG_DIR: string;
export declare const DEFAULT_DISPATCH_LIMITS_PATH: string;
export declare const DEFAULT_PATROL_STATE_DIR: string;
export declare const DEFAULT_TASK_QUEUE_REFRESH_MS = 15000;
export declare const DEFAULT_TASK_QUEUE_RECENT = 5;
export interface TaskQueueConfig {
    logDir?: string;
    limitsPath?: string;
    patrolDir?: string;
    refreshMs?: number;
    recent?: number;
}
/** The host commands, injectable so tests run without systemd. */
export interface TaskQueueDeps {
    /** Ids of the active `agent-dispatch-<id>.service` units. */
    activeTaskIds(): Promise<string[]>;
    /** `systemctl is-active clawock-patrol` ('' when systemctl is unavailable). */
    patrolService(): Promise<string>;
    /** The supervisor's most recent journal lines, oldest first, timestamps kept. */
    patrolLog(): Promise<string[]>;
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
/**
 * What the supervisor is doing, from its own last log line: `waiting: <why>`
 * (giving way before a round), `preempting …` (cancelling one for a user
 * task), `next round in Ns` (gap or backoff), a dispatched/adopted round.
 */
export declare function patrolPhase(service: string, round: string, roundAlive: boolean, log: string[]): Omit<PatrolStatus, 'rounds'>;
/** One full read. Throws only when the dispatch log directory itself is unreadable. */
type QueueRead = Omit<TaskQueueResult, 'status' | 'message' | 'refreshMs'>;
export declare function readTaskQueue(config: Required<TaskQueueConfig>, deps: TaskQueueDeps): Promise<QueueRead>;
export type TaskQueueService = {
    get(force: boolean): Promise<TaskQueueResult>;
};
/** TTL cache + in-flight join + stale-on-failure, the balance services' cadence shell in miniature. */
export declare function createTaskQueueService(config?: TaskQueueConfig, deps?: TaskQueueDeps): TaskQueueService;
export {};
