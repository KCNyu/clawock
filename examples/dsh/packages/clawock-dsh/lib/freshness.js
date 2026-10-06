import { join } from "node:path";
import { readdirSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
//#region src/freshness.ts
/**
* Workspace data-freshness signature + trace cache for the clawock-dsh
* gateway. Pure Node (fs/crypto/path only) — unit-testable without the
* typert-protocol dependency, and reused by the benchmark scripts.
*/
/**
* Content signature over the canonical bar files.
*
* `readBarCloses` reads `memory/bars/<ticker>.json`, so the signature has to
* cover those. Two rewrite paths matter and neither moves a filename: the
* daily writer appends the newly closed session to every ticker's file, and a
* `--repair` run revises a stored bar in place. Keying on anything but the
* files' own stat would serve a cached trace view straight through both.
*
* (Before the store moved to bars this hashed `memory/snapshots/`; the earlier
* version keyed on the newest snapshot *filename* alone, which missed every
* in-place rewrite — see #711.)
*/
function barsSignature(ws) {
	const dir = join(ws, "memory", "bars");
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
* Freshness signature over the four sources that feed the trace view:
* portfolio.json (fills + notes), every canonical bar file's stat (T+1
* closes), decisions.jsonl (soft pairing), and the FX ledger (USDHKD
* conversion for the header total). All stat-level reads, no parsing. The
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
		barsSignature(ws),
		sig(join(ws, "memory", "decisions.jsonl")),
		sig(join(ws, "memory", "fx-rates.jsonl"))
	].join("|");
}
/** Opaque per-workspace key for the client cache; hashing avoids shipping the host path to the browser. */
function workspaceKeyOf(ws) {
	return createHash("sha1").update(ws).digest("hex").slice(0, 12);
}
/** How long an unchanged signature may answer from the cache. */
const TRACE_TTL_MS = 6e4;
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
function createTraceCache(ttlMs = TRACE_TTL_MS, now = Date.now) {
	const entries = /* @__PURE__ */ new Map();
	return {
		get(ws, signature) {
			const hit = entries.get(ws);
			return hit !== void 0 && hit.signature === signature && now() - hit.at < ttlMs ? hit.value : void 0;
		},
		set(ws, signature, value) {
			entries.set(ws, {
				signature,
				value,
				at: now()
			});
		}
	};
}
//#endregion
export { TRACE_TTL_MS, createTraceCache, workspaceKeyOf, workspaceSignature };
