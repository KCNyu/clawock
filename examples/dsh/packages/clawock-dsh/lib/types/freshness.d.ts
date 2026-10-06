/**
 * Workspace data-freshness signature + trace cache for the clawock-dsh
 * gateway. Pure Node (fs/crypto/path only) — unit-testable without the
 * typert-protocol dependency, and reused by the benchmark scripts.
 */
/**
 * Freshness signature over the four sources that feed the trace view:
 * portfolio.json (fills + notes), every canonical bar file's stat (T+1
 * closes), decisions.jsonl (soft pairing), and the FX ledger (USDHKD
 * conversion for the header total). All stat-level reads, no parsing. The
 * enriched trace view is valid to reuse iff this signature is unchanged.
 */
export declare function workspaceSignature(ws: string): string;
/** Opaque per-workspace key for the client cache; hashing avoids shipping the host path to the browser. */
export declare function workspaceKeyOf(ws: string): string;
export interface TraceCache {
    get(ws: string, signature: string): unknown;
    set(ws: string, signature: string, value: unknown): void;
}
/** How long an unchanged signature may answer from the cache. */
export declare const TRACE_TTL_MS = 60000;
/**
 * Small signature-keyed cache: one enriched trace result per workspace,
 * rebuilt when the signature moves or the entry is older than `ttlMs`.
 * readTraces costs 70–140ms (snapshot rescan dominates) — a hit returns the
 * cached object in µs.
 *
 * The age bound is there for the one field that depends on the clock rather
 * than on a file: the FX line's "cache Nh not refreshed" warning. It is about
 * `memory/fx-rates.jsonl` no longer being written — exactly the write the
 * signature watches — so a signature-only cache held the first answer for as
 * long as the warning's own condition lasted (#2639).
 */
export declare function createTraceCache(ttlMs?: number, now?: () => number): TraceCache;
