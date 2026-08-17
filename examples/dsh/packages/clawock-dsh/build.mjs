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
 * build step — and `harness-regression.yml` rebuilds them on every plugin PR
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
console.log('built clawock-dsh/lib')
