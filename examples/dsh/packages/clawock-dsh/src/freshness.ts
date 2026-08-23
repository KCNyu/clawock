/**
 * Workspace data-freshness signature + trace cache for the clawock-dsh
 * gateway. Pure Node (fs/crypto/path only) — unit-testable without the
 * typert-protocol dependency, and reused by the benchmark scripts.
 */

import { statSync, readdirSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join } from 'node:path'

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
function barsSignature(ws: string): string {
  const dir = join(ws, 'memory', 'bars')
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
 * Freshness signature over the four sources that feed the trace view:
 * portfolio.json (fills + notes), every canonical bar file's stat (T+1
 * closes), decisions.jsonl (soft pairing), and the FX ledger (USDHKD
 * conversion for the header total). All stat-level reads, no parsing. The
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
    barsSignature(ws),
    sig(join(ws, 'memory', 'decisions.jsonl')),
    sig(join(ws, 'memory', 'fx-rates.jsonl')),
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
