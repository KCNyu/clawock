/**
 * clawock-dsh build — three official passes over the real source tree.
 *
 *   1. host pass   `tsdown.host.config.mjs` + `@deepseek-ai/dsh-typert-generator`
 *                  → lib/{index,scan,ledger,freshness}.js and the generated
 *                    reflection lib/typert.{host,client}.* + the client Remote
 *                    contribution lib/typert.remote-client.*
 *   2. client pass `tsdown.client.config.mjs` → lib/client.js (browser bundle,
 *                  CSS Modules inlined), wrapped as a module-loader closure
 *   3. declarations `tsc -p tsconfig.declarations.json` → lib/types
 *
 * The generator discovers packages from the workspace root's
 * tsconfig.host.json / tsconfig.client.json and only accepts project
 * references under `<root>/packages/` — which is exactly this repository's
 * `examples/dsh` layout, so the passes run in place. Until #731 this build
 * fabricated that layout in a temporary directory and copied `src/` into it;
 * the generator then analyzed the copy, and nothing tied the committed `lib/`
 * to the real sources.
 *
 * Generated `lib/` artifacts are committed — CI and DSH consume them without a
 * build step — and `ci.yml` rebuilds them on every plugin PR
 * and fails on any diff, so "does lib/ match src/?" is a machine-checked
 * question.
 */

import { execFile } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { promisify } from 'node:util'

const exec = promisify(execFile)
const pkg = process.cwd()
const node = process.execPath
const tsdown = join(pkg, 'node_modules/tsdown/dist/run.mjs')
const tsc = join(pkg, 'node_modules/typescript/bin/tsc')

const run = (args) => exec(node, [tsdown, ...args, '--tsconfig', 'tsconfig.bundle.json', '--no-report'], { cwd: pkg })

/**
 * Wrap the browser bundle as the `window.__ModuleLoader__.load({...})` closure
 * DSH's client loader evaluates, resolving externals through its `require`.
 * @param file - the emitted lib/client.js, rewritten in place.
 */
async function wrapWebClient(file) {
  let source = (await readFile(file, 'utf8')).replace(/[ \t]+$/gm, '')
  // The bundler stamps each `//#region` with the module's path *as resolved on
  // this machine*, so an inlined dependency would otherwise make the committed
  // artifact a function of the checkout directory rather than of the source.
  source = source.replace(
    /^(\/\/#(?:end)?region )(.*?)(node_modules\/.*)$/gm,
    (_, tag, _absolute, rest) => `${tag}${rest}`,
  )
  const match = source.match(/export \{ ([^}]+) \};\n?$/)
  if (!match) throw new Error('client bundle must end with named exports')
  const exports = match[1]
  let body = source.slice(0, match.index)
  body = body.replace(/^import \{ ([^}]+) \} from ["']([^"']+)["'];?$/gm, (_, names, id) => `const { ${names} } = require("${id}");`)
  body = body.replace(/^import \* as ([A-Za-z_$][\w$]*) from ["']([^"']+)["'];?$/gm, (_, name, id) => `const ${name} = require("${id}");`)
  body = body.replace(/^import ([A-Za-z_$][\w$]*) from ["']([^"']+)["'];?$/gm, (_, name, id) => `const ${name} = require("${id}").default ?? require("${id}");`)
  body = body.replace(/^import ["']([^"']+)["'];?$/gm, (_, id) => `require("${id}");`)
  if (/^\s*(?:import|export)\b/m.test(body)) throw new Error('client bundle must be self-contained')
  await writeFile(file, `window.__ModuleLoader__.load({
  id: "clawock-dsh",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
${body}
    Object.assign(exports, { ${exports} });
    return module.exports;
  }
});
`)
}

// Bootstrap for a lib-less checkout: the client half imports the generated
// Remote contribution through the package's own `./remote` export, which pass
// 1 emits but pass 1 also has to type-check that import. A placeholder here is
// overwritten by the generator moments later; an existing artifact is left
// alone so the pass sees the real descriptors.
const remoteArtifact = join(pkg, 'lib/typert.remote-client.js')
if (!existsSync(remoteArtifact)) {
  await writeFile(remoteArtifact, "export const TYPERT_REMOTE = { package: 'clawock-dsh', descriptors: [] }\n")
  await writeFile(join(pkg, 'lib/typert.remote-client.d.ts'),
    "export declare const TYPERT_REMOTE: import('@deepseek-ai/dsh-typert-protocol').TypertRemoteContribution\n")
}

await run(['--config', 'tsdown.host.config.mjs'])
await run(['--config', 'tsdown.client.config.mjs'])
await exec(node, [tsc, '-p', 'tsconfig.declarations.json', '--pretty', 'false'], { cwd: pkg })
await wrapWebClient(join(pkg, 'lib/client.js'))
await patchTypertAlignment()
await patchTypertSide()
await patchTypertBalance()
await patchTypertTaskQueue()
await patchTypertVerdictKind()

/**
 * Same discipline as the alignment patch: the clawock checkout cannot
 * regenerate the Typert host face, so the committed artifacts carry the
 * balance wire fields by hand. Re-assert after every build, idempotently;
 * a missing anchor throws instead of silently shipping a box the wire
 * cannot carry.
 */
async function patchTypertBalance() {
  const files = ['lib/typert.host.js', 'lib/typert.remote-client.js']
  const invocationMarker = `id: 'clawock-dsh#clawockStudio/balance',`
  const schemaAnchor = 'const clawock_dsh_clawockStudio_get_parameter_0$schema = z.string()'
  const invocationAnchor = `    {
      id: 'clawock-dsh#clawockStudio/get',`
  const balanceSchemas = `const clawock_dsh_clawockStudio_balance_parameter_0$schema = z.boolean()
const clawock_dsh_clawockStudio_balance_result$schema = z.object({
  'providers': z.array(z.object({
  'provider': z.string(),
  'label': z.string(),
  'result': z.object({
  'configured': z.boolean(),
  'snapshot': z.union([z.literal(null), z.object({
  'isAvailable': z.boolean(),
  'unit': z.string(),
  'currency': z.string(),
  'totalBalance': z.string(),
  'grantedBalance': z.string(),
  'toppedUpBalance': z.string(),
  'asOf': z.string(),
  'note': z.string(),
  'windows': z.array(z.object({
  'label': z.string(),
  'percent': z.union([z.number(), z.literal(null)]),
  'resetAt': z.string(),
  'durationMins': z.union([z.number(), z.literal(null)]),
  'resetAtMs': z.union([z.number(), z.literal(null)]),
})),
})]),
  'status': z.union([z.literal("fresh"), z.literal("cached"), z.literal("stale"), z.literal("failed"), z.literal("no-key")]),
  'low': z.boolean(),
  'message': z.union([z.literal(null), z.string()]),
  'threshold': z.number(),
  'refreshMs': z.number(),
}),
})),
  'refreshMs': z.number(),
})
`
  const balanceInvocation = `    {
      id: 'clawock-dsh#clawockStudio/balance',
      service: 'clawockStudio',
      namespace: 'clawockStudio',
      method: 'balance',
      invocation: { kind: 'direct' },
      parameters: [
        {
          name: 'force',
          wire: 'force',
          source: 'json',
          codec: {
            mode: 'strict',
            typeSymbol: 'clawock-dsh#clawockStudio/balance:force',
            schema: clawock_dsh_clawockStudio_balance_parameter_0$schema,
          },
        },
      ],
      result: {
        mode: 'strict',
        typeSymbol: 'clawock-dsh/types#BalancesResult',
        schema: clawock_dsh_clawockStudio_balance_result$schema,
      },
      sourceLocation: {"file":"packages/clawock-dsh/src/index.ts","line":121,"column":3},
    },
`
  for (const rel of files) {
    const file = join(pkg, rel)
    let source = await readFile(file, 'utf8')
    if (source.includes(invocationMarker)) continue
    if (!source.includes(schemaAnchor) || !source.includes(invocationAnchor)) {
      throw new Error(`patchTypertBalance: anchor missing in ${rel} — generator output changed?`)
    }
    source = source.replace(schemaAnchor, `${balanceSchemas}${schemaAnchor}`)
    source = source.replace(invocationAnchor, `${balanceInvocation}${invocationAnchor}`)
    await writeFile(file, source)
    console.log(`patched ${rel}: +clawockStudio.balance`)
  }
}


/**
 * The task-queue chip's Remote method, hand-carried for the same reason as
 * balance above. The client bundle inlines typert.remote-client.js as
 * committed, so a change here needs two builds before lib/client.js carries
 * it (CI builds once from the committed, already-patched artifact).
 */
async function patchTypertTaskQueue() {
  const files = ['lib/typert.host.js', 'lib/typert.remote-client.js']
  const invocationMarker = `id: 'clawock-dsh#clawockStudio/taskQueue',`
  const schemaAnchor = 'const clawock_dsh_clawockStudio_get_parameter_0$schema = z.string()'
  const invocationAnchor = `    {
      id: 'clawock-dsh#clawockStudio/get',`
  const schemasHead = 'const clawock_dsh_clawockStudio_taskQueue_parameter_0$schema = z.boolean()'
  const schemas = `const clawock_dsh_clawockStudio_taskQueue_parameter_0$schema = z.boolean()
const clawock_dsh_clawockStudio_taskQueue_task$schema = z.object({
  'id': z.string(),
  'name': z.string(),
  'agent': z.string(),
  'model': z.string(),
  'state': z.string(),
  'waiting': z.string(),
  'slot': z.string(),
  'attempts': z.number(),
  'outcome': z.string(),
  'startedAtMs': z.union([z.number(), z.literal(null)]),
  'updatedAtMs': z.union([z.number(), z.literal(null)]),
  'wakeAtMs': z.union([z.number(), z.literal(null)]),
  'patrol': z.boolean(),
  'summary': z.string(),
  'lastEvent': z.string(),
  'lastEventAtMs': z.union([z.number(), z.literal(null)]),
})
const clawock_dsh_clawockStudio_taskQueue_result$schema = z.object({
  'available': z.boolean(),
  'status': z.union([z.literal("fresh"), z.literal("cached"), z.literal("stale"), z.literal("failed")]),
  'message': z.union([z.literal(null), z.string()]),
  'asOf': z.string(),
  'refreshMs': z.number(),
  'maxRunning': z.number(),
  'running': z.number(),
  'active': z.array(clawock_dsh_clawockStudio_taskQueue_task$schema),
  'recent': z.array(clawock_dsh_clawockStudio_taskQueue_task$schema),
  'patrol': z.object({
  'service': z.string(),
  'phase': z.union([z.literal("running"), z.literal("yielding"), z.literal("waiting"), z.literal("stopped"), z.literal("unknown")]),
  'round': z.string(),
  'detail': z.string(),
  'untilMs': z.union([z.number(), z.literal(null)]),
  'rounds': z.array(z.object({
  'endedAt': z.string(),
  'round': z.string(),
  'axis': z.string(),
  'result': z.string(),
  'seconds': z.union([z.number(), z.literal(null)]),
})),
}),
})
`
  const invocation = `    {
      id: 'clawock-dsh#clawockStudio/taskQueue',
      service: 'clawockStudio',
      namespace: 'clawockStudio',
      method: 'taskQueue',
      invocation: { kind: 'direct' },
      parameters: [
        {
          name: 'force',
          wire: 'force',
          source: 'json',
          codec: {
            mode: 'strict',
            typeSymbol: 'clawock-dsh#clawockStudio/taskQueue:force',
            schema: clawock_dsh_clawockStudio_taskQueue_parameter_0$schema,
          },
        },
      ],
      result: {
        mode: 'strict',
        typeSymbol: 'clawock-dsh/types#TaskQueueResult',
        schema: clawock_dsh_clawockStudio_taskQueue_result$schema,
      },
      sourceLocation: {"file":"packages/clawock-dsh/src/index.ts","line":254,"column":3},
    },
`
  for (const rel of files) {
    const file = join(pkg, rel)
    let source = await readFile(file, 'utf8')
    if (source.includes(invocationMarker)) {
      // Already carried: refresh the schema block (it sits right before the
      // anchor) so a field added to DispatchTask reaches the wire too —
      // otherwise zod strips it and the client never sees it.
      const start = source.indexOf(schemasHead)
      const end = source.indexOf(schemaAnchor)
      if (start < 0 || end < start) throw new Error(`patchTypertTaskQueue: schema block not found in ${rel}`)
      if (source.slice(start, end) === schemas) continue
      await writeFile(file, source.slice(0, start) + schemas + source.slice(end))
      console.log(`patched ${rel}: refreshed clawockStudio.taskQueue schemas`)
      continue
    }
    if (!source.includes(schemaAnchor) || !source.includes(invocationAnchor)) {
      throw new Error(`patchTypertTaskQueue: anchor missing in ${rel} — generator output changed?`)
    }
    source = source.replace(schemaAnchor, `${schemas}${schemaAnchor}`)
    source = source.replace(invocationAnchor, `${invocation}${invocationAnchor}`)
    await writeFile(file, source)
    console.log(`patched ${rel}: +clawockStudio.taskQueue`)
  }
}


/**
 * The T+1 verdict code, same hand-carried wire field as the balance schema
 * above. Without it zod strips `verdictKind` from every trace, the client
 * silently falls back to the host's rendered `verdict` text, and a non-Chinese
 * reader gets Chinese verdicts with nothing failing — the reason this is a
 * build step rather than a one-off edit.
 */
async function patchTypertVerdictKind() {
  const files = ['lib/typert.host.js', 'lib/typert.remote-client.js']
  const marker = `'verdictKind': z.union([z.literal("up")`
  const anchor = `  'verdict': z.string(),
  'tone': z.union([z.literal("win"), z.literal("loss"), z.literal("flat")]),`
  const patched = `  'verdictKind': z.union([z.literal("up"), z.literal("down"), z.literal("soldEarly"), z.literal("soldRight"), z.literal("flat")]),
  'verdict': z.string(),
  'tone': z.union([z.literal("win"), z.literal("loss"), z.literal("flat")]),`
  for (const rel of files) {
    const file = join(pkg, rel)
    let source = await readFile(file, 'utf8')
    if (source.includes(marker)) continue
    if (!source.includes(anchor)) {
      throw new Error(`patchTypertVerdictKind: anchor missing in ${rel} — generator output changed?`)
    }
    source = source.replace(anchor, patched)
    await writeFile(file, source)
    console.log(`patched ${rel}: +t1.verdictKind`)
  }
}

console.log('built clawock-dsh/lib')

/**
 * The clawock checkout cannot regenerate the Typert host face: the generator
 * resolves `@Remote` symbols through `isTypeMetaSymbol`, which requires the
 * `@deepseek-ai/dsh-typert-protocol` declaration to be a *workspace* package —
 * true inside the official dsh repo, never here, where it lives in
 * node_modules. The committed `lib/typert.host.js` / `typert.remote-client.js`
 * are therefore a frozen snapshot from the dsh workspace; every wire field
 * added since (e.g. `TraceDecision.alignment`, 2026-08-17 #738) had silently
 * been missing from both the host encode schema and the client decode schema,
 * so the 与计划反向 chip could never render.
 *
 * Until the generator gains a node_modules fallback, this step re-applies the
 * known hand-maintained fields after every build. Idempotent and exact: a
 * field already present is left alone, and the inserted text is a byte-for-
 * byte constant, so the committed artifact stays reproducible and the CI
 * zero-diff gate keeps meaning something.
 */
async function patchTypertAlignment() {
  const files = ['lib/typert.host.js', 'lib/typert.remote-client.js']
  const marker = `  'alignment': z.union([z.literal("same"), z.literal("opposite"), z.literal("other"), z.literal(null)]),`
  for (const rel of files) {
    const file = join(pkg, rel)
    let source = await readFile(file, 'utf8')
    if (source.includes(marker)) continue
    // Insert INSIDE the TraceDecision object: between its last field
    // (`source`) and the closing `})]),` of the decision union — not after it,
    // which would land on the enclosing trade row instead.
    const head = `  'source': z.union([z.literal(null), z.string()]),\n`
    const tail = `})]),`
    if (!source.includes(head) || !source.includes(`${head}${tail}`)) {
      throw new Error(`patchTypertAlignment: decision-object anchor missing in ${rel} — generator output changed?`)
    }
    source = source.replace(`${head}${tail}`, `${head}${marker}\n${tail}`)
    await writeFile(file, source)
    console.log(`patched ${rel}: +TraceDecision.alignment`)
  }
}

/**
 * Preserve the host-computed trade direction across the strict Typert codec.
 * The client uses this field for the sell filter and its T+1 denominator; if
 * it is absent, zod strips it and every fill becomes sideless in the browser.
 */
async function patchTypertSide() {
  const files = ['lib/typert.host.js', 'lib/typert.remote-client.js']
  const marker = `  'side': z.union([z.literal("add"), z.literal("reduce"), z.literal(null)]),`
  const anchor = `  'holdPnl': z.union([z.literal(null), z.number()]),`
  for (const rel of files) {
    const file = join(pkg, rel)
    let source = await readFile(file, 'utf8')
    if (source.includes(marker)) continue
    if (!source.includes(anchor)) {
      throw new Error(`patchTypertSide: trade-object anchor missing in ${rel} — generator output changed?`)
    }
    source = source.replace(anchor, `${marker}\n${anchor}`)
    await writeFile(file, source)
    console.log(`patched ${rel}: +EnrichedTrade.side`)
  }
}
