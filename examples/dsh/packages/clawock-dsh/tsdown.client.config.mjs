/**
 * Client half: the browser bundle loaded by the DSH module loader.
 *
 * The CSS Modules plugin below mirrors `packages/client/tsdown.client.ts` in
 * the Harness tree (`dsh-css-modules-inline`): importing `x.module.css`
 * yields the hashed class map, and the stylesheet is injected at factory
 * execution as `<style data-plugin="clawock-dsh">`. That attribute is the
 * loader's ownership mark — `packages/client/modules` removes every tag it
 * finds under the plugin id when the package unloads — which is why a plugin
 * must never hand-roll its own `<style>` tag (#729).
 */
import { readFile } from 'node:fs/promises'
import { basename, dirname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'tsdown'
import { transform } from 'lightningcss'

/** This package's root — the anchor that keeps generated class hashes stable. */
const PACKAGE_ROOT = fileURLToPath(new URL('.', import.meta.url))

/** Plugin id: the module-loader package name, and the `data-plugin` value. */
const PLUGIN_ID = 'clawock-dsh'

/**
 * Virtual-id wrapper keeping module CSS away from tsdown's own css pipeline
 * (its guard matches ids ending in `.css`, so the virtual id must not).
 */
const CSS_VIRTUAL_PREFIX = '\0dsh-css:'
const CSS_VIRTUAL_SUFFIX = '.mjs'

const cssModules = {
  name: 'dsh-css-modules-inline',
  resolveId(source, importer) {
    if (!source.endsWith('.module.css')) return null
    const absolute = importer === undefined ? source : resolve(dirname(importer), source)
    // Package-relative, because the id becomes a `//#region` comment in the
    // committed bundle: an absolute path would differ per checkout.
    return CSS_VIRTUAL_PREFIX + relative(PACKAGE_ROOT, absolute) + CSS_VIRTUAL_SUFFIX
  },
  async load(virtualId) {
    if (!virtualId.startsWith(CSS_VIRTUAL_PREFIX)) return null
    const relativeFile = virtualId.slice(CSS_VIRTUAL_PREFIX.length, -CSS_VIRTUAL_SUFFIX.length)
    const file = resolve(PACKAGE_ROOT, relativeFile)
    this.addWatchFile(file)
    const { code, exports: cssExports } = transform({
      // lightningcss derives the class-name hash from this filename, so it
      // has to be the package-relative path: an absolute one would make the
      // committed bundle a function of the checkout directory, and the CI
      // "rebuild lib/ and diff" gate would fail on every runner.
      filename: relativeFile,
      code: await readFile(file),
      cssModules: { pattern: '[hash]_[local]' },
      minify: true,
    })
    // Sorted: lightningcss hands the export map back in hash order, which is
    // not stable between runs, and this map is serialized into the artifact.
    const classMap = {}
    for (const [local, exported] of Object.entries(cssExports ?? {}).sort()) classMap[local] = exported.name
    // One <style data-plugin> per module file; idempotent under re-evaluation.
    return [
      `const css = ${JSON.stringify(code.toString())};`,
      `const tagId = ${JSON.stringify(`${PLUGIN_ID}/${basename(relativeFile)}`)};`,
      'if (typeof document !== \'undefined\' && document.querySelector(\'style[data-plugin-css=\' + JSON.stringify(tagId) + \']\') === null) {',
      '  const tag = document.createElement(\'style\');',
      `  tag.dataset.plugin = ${JSON.stringify(PLUGIN_ID)};`,
      '  tag.dataset.pluginCss = tagId;',
      '  tag.textContent = css;',
      '  document.head.appendChild(tag);',
      '}',
      `export default ${JSON.stringify(classMap)};`,
    ].join('\n')
  },
}

export default defineConfig({
  entry: { client: 'src/client.ts' },
  outDir: 'lib',
  format: ['esm'],
  platform: 'browser',
  target: 'es2024',
  fixedExtension: false,
  dts: false,
  clean: false,
  outputOptions: { codeSplitting: false },
  // The loader module table answers `react` and the runtime store engine; the
  // generated Remote contribution and every plain library inline.
  deps: {
    neverBundle: ['react', 'react/jsx-runtime', 'react/jsx-dev-runtime', /^@deepseek-ai\//],
    alwaysBundle: ['zod'],
  },
  plugins: [cssModules],
})
