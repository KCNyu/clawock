/**
 * Host half: the node-side gateway plus the official Typert generation pass.
 *
 * `typertPlugin` runs against the real workspace root (`examples/dsh`, which
 * owns tsconfig.host.json / tsconfig.client.json) and emits the Host
 * reflection and the client Remote contribution into `lib/`.
 */
import { defineConfig } from 'tsdown'
import { typertPlugin } from '@deepseek-ai/dsh-typert-generator/tsdown'

export default defineConfig({
  entry: {
    index: 'src/index.ts',
    scan: 'src/scan.ts',
    ledger: 'src/ledger.ts',
    freshness: 'src/freshness.ts',
  },
  outDir: 'lib',
  format: ['esm'],
  platform: 'node',
  target: 'es2024',
  fixedExtension: false,
  dts: false,
  clean: false,
  deps: { neverBundle: [/^@deepseek-ai\//] },
  plugins: [typertPlugin({ mode: 'package', faces: ['host', 'client'] })],
})
