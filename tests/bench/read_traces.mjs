#!/usr/bin/env node
/**
 * readTraces 基准:量化「切到 Decision Mind tab」的 host 侧数据成本。
 *
 * 用法:
 *   node tests/bench/read_traces.mjs [workspace] [runs]
 *
 * 默认 workspace 取 $CLAWOCK_WORKSPACE 或 cwd,默认 5 次。输出 JSON 指标:
 * 总耗时 / 收盘价读取耗时(独立测 readBarCloses)/ bar 文件数、字节数 /
 * 结果序列化字节数。基线对比文件见同目录 perf-baseline.json。
 *
 * 这是「归因闸」(plan #702 v2 Phase 0.5)的 node 侧脚本:每次切到 Decision
 * Mind tab,host 都走一遍 readTraces。Phase 1 加了 host 侧缓存,本脚本承担
 * 「命中路径不再重扫」的回归断言。
 *
 * #717 之后价格源从 memory/snapshots/(全量解析 68 个组合快照)换成
 * memory/bars/<ticker>.json(只读实际成交过的 ticker),所以这里量的也换了。
 */
import { performance } from 'node:perf_hooks'
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { readTraces, readPortfolio, readBarCloses } from '../../examples/dsh/packages/clawock-dsh/lib/ledger.js'

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

// bar 目录静态规模(不解析内容)
const barDir = join(workspace, 'memory', 'bars')
let barFiles = 0
let barBytes = 0
try {
  for (const f of readdirSync(barDir)) {
    barFiles += 1
    barBytes += statSync(join(barDir, f)).size
  }
} catch {
  /* 无 bars 目录 = 0 */
}

// 实际会被读到的 ticker 集合 —— readBarCloses 只读这些,不是整个目录
const tradedTickers = readPortfolio(workspace).trades.map((t) => t.ticker)

// 预热(避开首次文件系统缓存冷启动)
readTraces(workspace)
readBarCloses(workspace, tradedTickers)

const totalMs = []
const closesMs = []
let serializedBytes = 0
for (let i = 0; i < runs; i++) {
  const t = time(() => readTraces(workspace))
  totalMs.push(t.ms)
  serializedBytes = JSON.stringify(t.value).length
  closesMs.push(time(() => readBarCloses(workspace, tradedTickers)).ms)
}

console.log(JSON.stringify({
  workspace,
  runs,
  bars: { files: barFiles, bytes: barBytes, tickersRead: new Set(tradedTickers).size },
  readTracesTotalMs: stats(totalMs),
  barCloseReadMs: stats(closesMs),
  serializedBytes,
}, null, 2))
