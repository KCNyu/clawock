#!/usr/bin/env node
/**
 * readTraces 基准:量化「切到 Decision Mind tab」的 host 侧数据成本。
 *
 * 用法:
 *   node tests/bench/read_traces.mjs [workspace] [runs]
 *
 * 默认 workspace 取 $CLAWOCK_WORKSPACE 或 cwd,默认 5 次。输出 JSON 指标:
 * 总耗时 / 快照扫描耗时(独立测 readSnapshotPrices)/ 快照文件数、字节数 /
 * 结果序列化字节数。基线对比文件见同目录 perf-baseline.json。
 *
 * 这是「归因闸」(plan #702 v2 Phase 0.5)的 node 侧脚本:每次切到 Decision
 * Mind tab,host 都走一遍 readTraces;快照扫描是其中最大的可重复成本。
 * Phase 1 加 host 侧缓存后,本脚本承担「命中路径不再重扫」的回归断言。
 */
import { performance } from 'node:perf_hooks'
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { readTraces, readSnapshotPrices } from '../../examples/dsh/plugin/lib/ledger.js'

const workspace = process.argv[2] || process.env.CLAWOCK_WORKSPACE || process.cwd()
const runs = Math.max(1, Number(process.argv[3] || 5))

function time(fn) {
  const t0 = performance.now()
  const value = fn()
  return { ms: performance.now() - t0, value }
}

function stats(list) {
  const sorted = [...list].sort((a, b) => a - b)
  const sum = sorted.reduce((a, b) => a + b, 0)
  return {
    avg: Number((sum / sorted.length).toFixed(1)),
    min: Number(sorted[0].toFixed(1)),
    max: Number(sorted[sorted.length - 1].toFixed(1)),
  }
}

// 快照目录静态规模(不解析内容)
const snapDir = join(workspace, 'memory', 'snapshots')
let snapFiles = 0
let snapBytes = 0
try {
  for (const f of readdirSync(snapDir)) {
    snapFiles += 1
    snapBytes += statSync(join(snapDir, f)).size
  }
} catch {
  /* 无快照目录 = 0 */
}

// 预热(避开首次文件系统缓存冷启动)
readTraces(workspace)
readSnapshotPrices(workspace)

const totalMs = []
const snapshotMs = []
let serializedBytes = 0
for (let i = 0; i < runs; i++) {
  const t = time(() => readTraces(workspace))
  totalMs.push(t.ms)
  serializedBytes = JSON.stringify(t.value).length
  snapshotMs.push(time(() => readSnapshotPrices(workspace)).ms)
}

console.log(JSON.stringify({
  workspace,
  runs,
  snapshots: { files: snapFiles, bytes: snapBytes },
  readTracesTotalMs: stats(totalMs),
  snapshotScanMs: stats(snapshotMs),
  serializedBytes,
}, null, 2))
