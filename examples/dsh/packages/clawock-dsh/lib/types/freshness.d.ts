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
/**
 * Small signature-keyed cache: one enriched trace result per workspace,
 * rebuilt only when the signature moves. readTraces costs 70–140ms (snapshot
 * rescan dominates) — a hit returns the cached object in µs.
 */
export declare function createTraceCache(): TraceCache;
