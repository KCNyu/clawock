/**
 * Workspace data-freshness signature + trace cache for the clawock-dsh
 * gateway. Pure Node (fs/crypto/path only) — unit-testable without the
 * typert-protocol dependency, and reused by the benchmark scripts.
 */

import { statSync, readdirSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join } from 'node:path'

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
function snapshotsSignature(ws: string): string {
  const dir = join(ws, 'memory', 'snapshots')
  let names: string[]
  try {
    names = readdirSync(dir).sort()
  } catch {
    return 'none'
  }
  if (names.length === 0) return 'none'
  const hash = createHash('sha1')
  for (const name of names) {
    try {
      const st = statSync(join(dir, name))
      hash.update(`${name}:${st.mtimeMs}:${st.size}\n`)
    } catch {
      hash.update(`${name}:missing\n`)
    }
  }
  return `${names.length}:${hash.digest('hex').slice(0, 16)}`
}

/**
 * Freshness signature over the three sources that feed the trace view:
 * portfolio.json (fills + notes), every snapshot's stat (T+1 closes), and
 * decisions.jsonl (soft pairing). All stat-level reads, no parsing. The
 * enriched trace view is valid to reuse iff this signature is unchanged.
 */
export function workspaceSignature(ws: string): string {
  const sig = (p: string): string => {
    try {
      const st = statSync(p)
      return `${st.mtimeMs}:${st.size}`
    } catch {
      return 'missing'
    }
  }
  return [
    sig(join(ws, 'portfolio.json')),
    snapshotsSignature(ws),
    sig(join(ws, 'memory', 'decisions.jsonl')),
  ].join('|')
}

/** Opaque per-workspace key for the client cache; hashing avoids shipping the host path to the browser. */
export function workspaceKeyOf(ws: string): string {
  return createHash('sha1').update(ws).digest('hex').slice(0, 12)
}

export interface TraceCache {
  get(ws: string, signature: string): unknown
  set(ws: string, signature: string, value: unknown): void
}

/**
 * Small signature-keyed cache: one enriched trace result per workspace,
 * rebuilt only when the signature moves. readTraces costs 70–140ms (snapshot
 * rescan dominates) — a hit returns the cached object in µs.
 */
export function createTraceCache(): TraceCache {
  const entries = new Map<string, { signature: string; value: unknown }>()
  return {
    get(ws: string, signature: string): unknown {
      const hit = entries.get(ws)
      return hit !== undefined && hit.signature === signature ? hit.value : undefined
    },
    set(ws: string, signature: string, value: unknown): void {
      entries.set(ws, { signature, value })
    },
  }
}
