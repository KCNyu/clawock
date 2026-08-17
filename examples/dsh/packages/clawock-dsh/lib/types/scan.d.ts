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
import type { ListRunsResult, RunDetailResult } from './types.ts';
/** Request files are written under .clawock/work/<32-hex run id>/request.json. */
export declare const RUN_ID_PATTERN: RegExp;
/** Validate a run id; this is also the path-safety boundary for directory joins. */
export declare function runIdOf(value: unknown): string;
/**
 * Snapshot every prepared run with enough to render a list row.
 * @param workspace - clawock workspace root.
 * @returns runs ordered by request file mtime, newest first.
 */
export declare function listRuns(workspace: string): ListRunsResult['runs'];
/**
 * Full detail of one run: certified request, current decision artifact and
 * receipt manifest. Missing pieces stay null — a prepared-but-unpublished
 * run is a valid state.
 * @param workspace - clawock workspace root.
 * @param runId - 32-hex run id; anything else is rejected before any path use.
 */
export declare function getRun(workspace: string, runIdValue: unknown): RunDetailResult;
