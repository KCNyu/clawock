#!/usr/bin/env node
/**
 * clawock-dsh package contract: the packed tarball, installed on its own,
 * must actually load.
 *
 * Run: node tests/dsh_plugin_package_contract.mjs
 * CI:  harness-regression.yml runs it when plugin files change.
 *
 * Why this gate exists (2026-08-17): #708 added `zod` as a runtime dependency
 * of the generated typert host reflection. Every existing check stayed green —
 * the plugin spec imports lib/ modules straight out of the repo checkout,
 * where the repo's own node_modules happens to satisfy everything — and dsh
 * then crash-looped 83 times in production because the deployed plugin
 * directory had no zod. The class of failure the old gates could not see was
 * "declared dependency that nothing installs".
 *
 * So this test refuses to look at the checkout. It packs the package the way
 * npm would publish it, installs that tarball into an empty directory with
 * only its declared production dependencies, and imports every export entry.
 * A dependency that is imported but not declared fails here.
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync, readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const PLUGIN = resolve(HERE, '..', 'examples', 'dsh', 'packages', 'clawock-dsh')

const run = (cmd, args, cwd) =>
  execFileSync(cmd, args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })

test('packed clawock-dsh installs standalone and every export entry imports', async (t) => {
  const pkg = JSON.parse(readFileSync(join(PLUGIN, 'package.json'), 'utf8'))
  const work = mkdtempSync(join(tmpdir(), 'clawock-dsh-pkg-'))
  try {
    // 1. Pack exactly what would be published.
    const packed = run('npm', ['pack', '--pack-destination', work, '--silent'], PLUGIN).trim().split('\n').pop()
    const tarball = join(work, packed)
    assert.ok(existsSync(tarball), `npm pack produced ${packed}`)

    // 2. Install it into an empty project — nothing from the repo checkout is
    //    reachable from here, which is the whole point.
    const proj = join(work, 'proj')
    run('mkdir', ['-p', proj])
    writeFileSync(join(proj, 'package.json'), JSON.stringify({ name: 'contract', private: true, type: 'module' }))
    run('npm', ['install', '--omit=dev', '--no-audit', '--no-fund', '--silent', tarball], proj)

    const installed = join(proj, 'node_modules', 'clawock-dsh')
    assert.ok(existsSync(installed), 'clawock-dsh installed into the empty project')

    // 3. The package must ship the skill body — rc.6 skill discovery reads it
    //    from the installed package, so a missing file is a silent no-op.
    assert.ok(
      existsSync(join(installed, 'skills', 'investment-decision', 'SKILL.md')),
      'the published package ships skills/investment-decision/SKILL.md',
    )

    // 4. Import every export entry. This is what dsh's typert-loader does, and
    //    it is where a declared-but-uninstalled (or undeclared) dependency dies.
    const entries = Object.entries(pkg.exports || {})
      .filter(([name, spec]) => name !== './package.json' && spec && spec.default)
    assert.ok(entries.length >= 3, 'the package exposes its host/client/remote entries')
    for (const [name, spec] of entries) {
      const file = join(installed, spec.default)
      assert.ok(existsSync(file), `${name} -> ${spec.default} exists in the tarball`)
      // The browser bundle is a window.__ModuleLoader__ closure, not an ES
      // module — importing it outside a DOM proves nothing and throws. Its
      // registration is covered by decision_studio_plugin.spec.js instead.
      if (name === './client') continue
      await t.test(`import ${name}`, async () => {
        await import(pathToFileURL(file).href)
      })
    }

    // 5. Every runtime dependency the shipped code imports must be declared.
    //    (The import above would already fail, but this names the offender.)
    const declared = new Set([
      ...Object.keys(pkg.dependencies || {}),
      ...Object.keys(pkg.peerDependencies || {}),
    ])
    const libDir = join(installed, 'lib')
    const bare = new Set()
    for (const file of readdirSync(libDir).filter((f) => f.endsWith('.js'))) {
      const src = readFileSync(join(libDir, file), 'utf8')
      for (const m of src.matchAll(/\bfrom\s+["']([^."'][^"']*)["']/g)) {
        const id = m[1]
        if (id.startsWith('node:')) continue
        bare.add(id.startsWith('@') ? id.split('/').slice(0, 2).join('/') : id.split('/')[0])
      }
    }
    for (const id of bare) {
      assert.ok(declared.has(id), `lib/ imports "${id}" — it must be a declared dependency`)
    }
  } finally {
    rmSync(work, { recursive: true, force: true })
  }
})

/**
 * The npm page is this project's highest-traffic landing surface — more people
 * reach clawock-dsh through npm than through the repository — and until #790 it
 * was a dead end: `repository`, `homepage`, `bugs` and `author` were all absent
 * from the published metadata, so npm rendered no sidebar links at all, and the
 * README was Chinese-only with no link back to the live proof. A thousand
 * installs a month landed on a page with no exit.
 *
 * Two of these are load-bearing beyond presentation:
 *   - `repository` is what `npm publish --provenance` checks against the
 *     building repository; without it the release silently publishes unsigned.
 *   - relative image paths render as broken images on the npm page, because it
 *     is not served from the repository.
 */
test('the npm page keeps its links back to the repository and the live proof', () => {
  const pkg = JSON.parse(readFileSync(join(PLUGIN, 'package.json'), 'utf8'))

  assert.equal(pkg.repository?.type, 'git')
  assert.match(pkg.repository?.url ?? '', /github\.com\/KCNyu\/clawock/)
  assert.equal(pkg.repository?.directory, 'examples/dsh/packages/clawock-dsh')
  assert.match(pkg.homepage ?? '', /^https:\/\//)
  assert.match(pkg.bugs?.url ?? '', /github\.com\/KCNyu\/clawock\/issues/)
  assert.ok(pkg.author, 'package.json must name an author')

  const readme = readFileSync(join(PLUGIN, 'README.md'), 'utf8')
  for (const url of [
    'https://kcnyu.github.io/clawock/',
    'https://kcnyu.github.io/clawock/evidence.html',
    'https://github.com/KCNyu/clawock',
  ]) {
    assert.ok(readme.includes(url), `README.md must link to ${url}`)
  }

  // The lead has to be readable by someone who does not read Chinese: the npm
  // audience is every DSH user, not only the ones who found the repo first.
  const lead = readme.split('\n---\n')[0]
  assert.ok(/[一-鿿]/.test(readme), 'the Chinese body must stay')
  assert.ok(!/[一-鿿]/.test(lead),
    'the section above the first --- must be the English lead, with no Chinese in it')

  for (const m of readme.matchAll(/!\[[^\]]*\]\(([^)]+)\)/g)) {
    assert.match(m[1], /^https:\/\/raw\.githubusercontent\.com\//,
      `README image ${m[1]} must be an absolute raw.githubusercontent.com URL`)
  }
})
