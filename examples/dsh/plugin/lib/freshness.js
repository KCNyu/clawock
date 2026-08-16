/**
 * Workspace data-freshness signature + trace cache for the clawock-dsh
 * gateway. Pure Node (fs/crypto/path only) — unit-testable without the
 * typert-protocol dependency, and reused by the benchmark scripts.
 */

import { statSync, readdirSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join } from 'node:path'

/**
 * Freshness signature over the three sources that feed the trace view:
 * portfolio.json (fills + notes), the newest snapshot filename (T+1 closes
 * land as NEW daily files — an mtime on the directory would also move on
 * unrelated churn), and decisions.jsonl (soft pairing). All three are
 * stat-level (µs) reads, no parsing. The enriched trace view is valid to
 * reuse iff this signature is unchanged.
 */
export function workspaceSignature(ws) {
  const sig = (p) => {
    try {
      const st = statSync(p)
      return `${st.mtimeMs}:${st.size}`
    } catch {
      return 'missing'
    }
  }
  let latestSnapshot = 'none'
  try {
    const files = readdirSync(join(ws, 'memory', 'snapshots')).sort()
    if (files.length > 0) latestSnapshot = files[files.length - 1]
  } catch {
    /* no snapshot dir yet */
  }
  return [
    sig(join(ws, 'portfolio.json')),
    latestSnapshot,
    sig(join(ws, 'memory', 'decisions.jsonl')),
  ].join('|')
}

/** Opaque per-workspace key for the client cache; hashing avoids shipping the host path to the browser. */
export function workspaceKeyOf(ws) {
  return createHash('sha1').update(ws).digest('hex').slice(0, 12)
}

/**
 * Small signature-keyed cache: one enriched trace result per workspace,
 * rebuilt only when the signature moves. readTraces costs 70–140ms (snapshot
 * rescan dominates) — a hit returns the cached object in µs.
 */
export function createTraceCache() {
  const entries = new Map()
  return {
    /** @returns cached value or undefined. */
    get(ws, signature) {
      const hit = entries.get(ws)
      return hit !== undefined && hit.signature === signature ? hit.value : undefined
    },
    set(ws, signature, value) {
      entries.set(ws, { signature, value })
    },
  }
}
