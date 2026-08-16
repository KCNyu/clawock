import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";
//#region packages/clawock-dsh/src/freshness.ts
/**
* Workspace data-freshness signature + trace cache for the clawock-dsh
* gateway. Pure Node (fs/crypto/path only) — unit-testable without the
* typert-protocol dependency, and reused by the benchmark scripts.
*/
/**
* Content signature over every snapshot file, not just the newest filename.
*
* `readSnapshotPrices` parses *all* of `memory/snapshots/`, so the signature
* has to cover all of it. Keying on the newest filename alone missed two real
* cases: an existing snapshot being recomputed and rewritten, and the current
* day's file being rewritten repeatedly intraday — in both the name never
* moves, so a cached trace view would be served indefinitely. A directory
* mtime was rejected for moving on unrelated churn; per-file `stat` does not
* have that problem. Measured 1.4ms steady-state for the current 68 files
* (~8ms on the first cold call), against the ~103ms readTraces it guards.
*/
function snapshotsSignature(ws) {
	const dir = join(ws, "memory", "snapshots");
	let names;
	try {
		names = readdirSync(dir).sort();
	} catch {
		return "none";
	}
	if (names.length === 0) return "none";
	const hash = createHash("sha1");
	for (const name of names) try {
		const st = statSync(join(dir, name));
		hash.update(`${name}:${st.mtimeMs}:${st.size}\n`);
	} catch {
		hash.update(`${name}:missing\n`);
	}
	return `${names.length}:${hash.digest("hex").slice(0, 16)}`;
}
/**
* Freshness signature over the three sources that feed the trace view:
* portfolio.json (fills + notes), every snapshot's stat (T+1 closes), and
* decisions.jsonl (soft pairing). All stat-level reads, no parsing. The
* enriched trace view is valid to reuse iff this signature is unchanged.
*/
function workspaceSignature(ws) {
	const sig = (p) => {
		try {
			const st = statSync(p);
			return `${st.mtimeMs}:${st.size}`;
		} catch {
			return "missing";
		}
	};
	return [
		sig(join(ws, "portfolio.json")),
		snapshotsSignature(ws),
		sig(join(ws, "memory", "decisions.jsonl"))
	].join("|");
}
/** Opaque per-workspace key for the client cache; hashing avoids shipping the host path to the browser. */
function workspaceKeyOf(ws) {
	return createHash("sha1").update(ws).digest("hex").slice(0, 12);
}
/**
* Small signature-keyed cache: one enriched trace result per workspace,
* rebuilt only when the signature moves. readTraces costs 70–140ms (snapshot
* rescan dominates) — a hit returns the cached object in µs.
*/
function createTraceCache() {
	const entries = /* @__PURE__ */ new Map();
	return {
		get(ws, signature) {
			const hit = entries.get(ws);
			return hit !== void 0 && hit.signature === signature ? hit.value : void 0;
		},
		set(ws, signature, value) {
			entries.set(ws, {
				signature,
				value
			});
		}
	};
}
//#endregion
export { createTraceCache, workspaceKeyOf, workspaceSignature };
